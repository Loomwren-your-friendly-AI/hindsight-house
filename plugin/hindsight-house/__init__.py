"""hindsight-house: a memory provider that subclasses the stock Hindsight provider and adds a recall policy.

Stock is reached only through ``plugins.memory.import_provider_module("hindsight")`` and only inside register().
Siblings are imported by relative import. No MemoryProvider subclass is bound at module level, so
a FATAL guard result really registers nothing.

Parts: thread-local context, client proxy, fail-closed check, house settings, notice cut, short-query context,
switches, guard, post_setup.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Mapping

from . import degraded, drift_guard, house_settings, notice_cut, prev_statement, recall_policy

logger = logging.getLogger(__name__)

_CTX = threading.local()  # origin, session_id and recall; a thread-local cannot leak into child threads
GUARD_TAG = "HINDSIGHT_HOUSE_GUARD"
PROVIDER_NAME = "hindsight-house"
NO_MEMORIES = "No relevant memories found."  # stock sentence of _tool_recall (guarded by its hash)
HOUSE_SCHEMA = (
    {"key": "recall_exclude_tags", "description": "Tags excluded from recall, auto and tool path (comma list)", "default": ""},
    {"key": "recall_max_results", "description": "Cap on auto-injected results (0 = no cap)", "default": 0},
    {"key": "recall_cron", "description": "Inject recall on cron sessions", "default": False},
    {"key": "mirror_builtin_memory", "description": "Mirror built-in memory writes into the bank", "default": False},
    {"key": "recall_query_cuts", "description": "Notice cut rules (list of applies_if, cut_at, window, min_keep)", "default": []},
    {"key": "recall_short_query_chars", "description": "Short-query context threshold (0 = off)", "default": 0},
    {"key": "recall_short_query_context_chars", "description": "Characters of the previous statement to add", "default": 400},
)


class HouseGuardError(RuntimeError):
    """Stock recall no longer goes through the house client proxy: fail closed."""


class _RecallClientProxy:
    """Wraps the stock client for one recall. Holds origin and counter from construction: arecall runs on the
    loop thread, so this class must never read the thread-local."""

    def __init__(self, client: Any, counter: list[int], rewrite: Callable[[Mapping[str, Any]], dict[str, Any]]) -> None:
        self._client, self._counter, self._rewrite = client, counter, rewrite

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._client, attr)

    async def arecall(self, **kwargs: Any) -> Any:
        self._counter.append(1)
        return await self._client.arecall(**self._rewrite(kwargs))


def _home() -> Path | None:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return None


def _redactor() -> Callable[[str], str] | None:
    try:
        from agent.memory_manager import _redact_for_provider
    except Exception:
        return None
    redact: Callable[[str], str] = _redact_for_provider
    return redact


def _build_house_class(stock_cls: Any) -> Any:
    """The HouseProvider subclass of the stock class (defined here, never at module level)."""

    class HouseProvider(stock_cls):  # type: ignore[misc]
        name = property(lambda self: PROVIDER_NAME)
        _house = house_settings.HouseSettings()
        _house_cfg: Any = None

        def _refresh_house(self, cfg: Any) -> None:
            if self._house_cfg is not cfg:  # recall and retain hooks get the same dict: parse (and warn) once
                self._house_cfg, self._house = cfg, house_settings.parse_house_settings(cfg)

        def _apply_recall_settings(self, cfg: Any) -> None:
            super()._apply_recall_settings(cfg)
            self._refresh_house(cfg)

        def _apply_retain_policy(self, cfg: Any) -> None:
            super()._apply_retain_policy(cfg)
            self._refresh_house(cfg)

        def _recall_disabled(self) -> bool:
            if super()._recall_disabled():
                return True
            return not self._house.recall_cron and getattr(self, "_agent_context", "primary") == "cron"

        def prefetch(self, query: str, *, session_id: str = "") -> str:
            _CTX.session_id = session_id
            try:
                return super().prefetch(query, session_id=session_id)  # type: ignore[no-any-return]
            finally:
                _CTX.session_id = ""

        def _with_short_query(self, query: Any) -> Any:
            # The length test repeats the compose rule so state.db is opened only for a query that can get context
            limit, session_id = self._house.short_query_chars, getattr(_CTX, "session_id", "")
            if not (self._recall_sync and limit > 0 and session_id and isinstance(query, str) and len(query.strip()) < limit):
                return query
            home = _home()
            previous = prev_statement.previous_assistant_statement(home, session_id) if home else ""
            return recall_policy.compose_short_query(query, previous, self._house, self._recall_max_input_chars, _redactor())

        def _do_recall(self, query: str) -> Any:
            if self._house.query_cuts:
                query = notice_cut.cut_query(query, self._house.query_cuts)
            query = self._with_short_query(query)
            _CTX.origin = recall_policy.ORIGIN_AUTO
            try:
                return super()._do_recall(query)
            finally:
                _CTX.origin = None

        def _recall(self, query: str) -> Any:
            origin = getattr(_CTX, "origin", None) or recall_policy.ORIGIN_TOOL
            counter: list[int] = []
            _CTX.recall = (origin, counter)  # always set: the tool path needs the exclusion too
            try:
                results = super()._recall(query)
            finally:
                _CTX.recall = None
            if not counter:
                logger.error("%s recall-bypass origin=%s", GUARD_TAG, origin)
                raise HouseGuardError("recall bypassed the house client proxy")
            return recall_policy.cap_results(results, self._house, origin)

        def _run_hindsight_operation(self, operation: Callable[[Any], Any]) -> Any:
            active = getattr(_CTX, "recall", None)
            if not active:
                return super()._run_hindsight_operation(operation)
            origin, counter = active
            house = self._house

            def rewrite(kwargs: Mapping[str, Any]) -> dict[str, Any]:
                return recall_policy.rewrite_kwargs(kwargs, house, origin)

            return super()._run_hindsight_operation(lambda client: operation(_RecallClientProxy(client, counter, rewrite)))

        def _tool_recall(self, args: dict[str, Any]) -> str:
            out: str = super()._tool_recall(args)
            # Join format: preamble, blank line, results
            preamble = getattr(self, "_recall_prompt_preamble", "")  # a stock key, not a house key
            return out if not preamble or out == NO_MEMORIES else f"{preamble}\n\n{out}"

        _handler = stock_cls._TOOL_HANDLERS["hindsight_recall"]
        _TOOL_HANDLERS = {**stock_cls._TOOL_HANDLERS, "hindsight_recall": (_handler[0], _tool_recall, _handler[2])}
        del _handler

        def on_memory_write(self, action: str, target: str, content: str, metadata: Any = None) -> None:
            if self._house.mirror_builtin_memory:
                super().on_memory_write(action, target, content, metadata)

        def get_config_schema(self) -> Any:
            return [*super().get_config_schema(), *(dict(entry) for entry in HOUSE_SCHEMA)]

        def post_setup(self, hermes_home: str, config: dict[str, Any]) -> None:
            # Rename only after the stock wizard finished (its last step writes "hindsight" and saves); a
            # wizard cancelled at a prompt returns earlier and must leave the config as stock leaves it.
            # No fallback for a non-dict memory entry; the caller sets a dict (memory_setup._post_setup_hook)
            memory, missing = config["memory"], object()
            before = memory.get("provider", missing)
            memory["provider"] = PROVIDER_NAME  # stock overwrites this only on its finish path
            try:
                super().post_setup(hermes_home, config)
            finally:
                finished = memory.get("provider") == "hindsight"
                if not finished and before is missing:
                    memory.pop("provider", None)
                elif not finished:
                    memory["provider"] = before
            if finished:
                from hermes_cli.config import save_config

                memory["provider"] = PROVIDER_NAME
                save_config(config)

    return HouseProvider


def _build_provider(stock: Any, result: drift_guard.GuardResult) -> Any:
    if result.status == drift_guard.STATUS_OK:
        return _build_house_class(stock.HindsightMemoryProvider)()
    logger.error("%s drift %s", GUARD_TAG, ",".join(result.failed))
    from tools.registry import tool_error

    cls = degraded.make_degraded_provider(stock.HindsightMemoryProvider, tool_error, house_settings.parse_house_settings)
    return cls()


def register(ctx: Any) -> None:
    """Loader entry point: guard first; FATAL registers nothing; DRIFT registers the DegradedProvider."""
    stock = None
    try:
        from plugins.memory import import_provider_module

        stock = import_provider_module("hindsight")
    except Exception as exc:
        logger.error("%s stock import failed: %s", GUARD_TAG, type(exc).__name__)
    result = drift_guard.check(stock)
    drift_guard.write_flag(_home(), result)
    if result.status != drift_guard.STATUS_FATAL:
        try:
            provider = _build_provider(stock, result)
        except Exception as exc:
            result = drift_guard.GuardResult(drift_guard.STATUS_FATAL, "none", ("build:" + type(exc).__name__,))
            drift_guard.write_flag(_home(), result)
        else:
            ctx.register_memory_provider(provider)
            return
    logger.error("%s fatal %s: no provider registered", GUARD_TAG, ",".join(result.failed))
