"""DegradedProvider factory: injection off, tool recall kept with the exclusion filter.

No import-time work. ``make_degraded_provider`` is called from register() with the stock class; it accepts any
stock ``_recall`` signature, so it also runs on the stock 1.2.1 class.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

UNAVAILABLE = "recall unavailable: house guard"


def filter_results(results: Any, exclude: Iterable[str]) -> Any:
    """Drop results whose tags hit *exclude*. A result without readable tags is kept."""
    blocked = set(exclude)
    if not blocked or not isinstance(results, (list, tuple)):
        return results
    return [r for r in results if not blocked.intersection(getattr(r, "tags", None) or ())]


def _is_error(output: Any) -> bool:
    try:
        parsed = json.loads(output)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and "error" in parsed


# The DegradedProvider lives in this sibling, built by a factory that register() calls (no stock import at module level)
def make_degraded_provider(stock_cls: Any, tool_error: Callable[[str], str], parse_settings: Callable[[Any], Any]) -> Any:
    """Build the DegradedProvider subclass of *stock_cls*."""
    entered = threading.local()

    class DegradedProvider(stock_cls):  # type: ignore[misc]
        name = property(lambda self: "hindsight-house")
        _house_exclude: tuple[str, ...] = ()

        def _apply_recall_settings(self, cfg: Any) -> None:
            try:
                super()._apply_recall_settings(cfg)
            except Exception as exc:  # a drifted stock may no longer take this call; keep the filter anyway
                logger.error("HINDSIGHT_HOUSE_GUARD degraded settings failed: %s", type(exc).__name__)
            self._house_exclude = tuple(parse_settings(cfg).exclude_tags)

        def _recall_disabled(self) -> bool:
            return True

        def _recall(self, *args: Any, **kwargs: Any) -> Any:
            entered.flag = True
            return filter_results(super()._recall(*args, **kwargs), self._house_exclude)

        def on_memory_write(self, *args: Any, **kwargs: Any) -> None:
            return None

        # Fail closed when a tool recall never reached the filtered _recall
        def handle_tool_call(self, tool_name: str, args: Any, **kwargs: Any) -> Any:
            entered.flag = False
            output = super().handle_tool_call(tool_name, args, **kwargs)
            if tool_name == "hindsight_recall" and not entered.flag and not _is_error(output):
                return tool_error(UNAVAILABLE)
            return output

    return DegradedProvider
