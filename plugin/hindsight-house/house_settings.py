"""House settings for hindsight-house: parse and validate the house keys.

Pure module: standard library only, no import-time work. A bad value never raises: it falls back to its default
and logs one WARNING that names the key, never the value.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping, NamedTuple

logger = logging.getLogger(__name__.rpartition(".")[0] or __name__)  # same rule as stock settings.py

_TRUE, _FALSE = frozenset({"1", "true", "yes", "on"}), frozenset({"0", "false", "no", "off", ""})
_NESTED = re.compile(r"\((?:[^()\\]|\\.)*[*+}](?:[^()\\]|\\.)*\)[*+{]")  # (a+)+ shape


class CutRule(NamedTuple):
    """One notice-cut rule. ``applies_if`` is a compiled pattern."""

    applies_if: "re.Pattern[str]"
    cut_at: str
    window: int
    min_keep: int


class HouseSettings(NamedTuple):
    """The house keys. Defaults are stock behaviour, except mirror_builtin_memory and recall_cron: false."""

    exclude_tags: tuple[str, ...] = ()
    max_results: int = 0  # 0 = no cap
    recall_cron: bool = False  # no auto-injection on a cron session unless set true
    mirror_builtin_memory: bool = False
    query_cuts: tuple[CutRule, ...] = ()
    short_query_chars: int = 0  # 0 = off
    short_query_context_chars: int = 400


def _warn(key: str, why: str) -> None:
    logger.warning("hindsight-house: ignoring %s (%s); using the default", key, why)


def _to_int(cfg: Mapping[str, Any], key: str, default: int) -> int:
    """Integer >= 0; missing or empty gives the default, a bad value warns and gives the default."""
    value = cfg.get(key)
    if value is None or value == "":
        return default
    fraction = isinstance(value, float) and not value.is_integer()  # also nan and inf
    try:
        if not (fraction or isinstance(value, bool)) and int(value) >= 0:  # a negative warns
            return int(value)
    except (TypeError, ValueError, OverflowError):
        pass
    _warn(key, "expected an integer")
    return default


def _to_bool(cfg: Mapping[str, Any], key: str, default: bool) -> bool:
    value = cfg.get(key)
    if value is None:
        return default
    text = str(value).strip().lower()  # True and False become "true" and "false"
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    _warn(key, "expected true or false")
    return default


def _to_tags(cfg: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """A list, JSON list string or comma-separated text, as a deduplicated tuple of non-empty strings."""
    value = cfg.get(key)
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        parsed = None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
        items = parsed if isinstance(parsed, list) else text.split(",")
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        _warn(key, "expected a list or comma-separated text")
        return ()
    tags: list[str] = []
    for item in items:
        tag = item.strip() if isinstance(item, str) else ""
        if tag and tag not in tags:
            tags.append(tag)
    return tuple(tags)


def _one_cut(entry: Any) -> CutRule | None:
    if not isinstance(entry, Mapping):
        return None
    applies, cut_at = entry.get("applies_if"), entry.get("cut_at")
    if not (isinstance(applies, str) and applies and isinstance(cut_at, str) and cut_at) or _NESTED.search(applies):
        return None
    window = _to_int(entry, "window", 400)  # 400 and 40: the house values
    if window < 1:
        return None
    try:
        pattern = re.compile(applies)  # once, at config load
    except (re.error, RecursionError, OverflowError):
        return None
    return CutRule(pattern, cut_at, window, _to_int(entry, "min_keep", 40))


def _to_cuts(cfg: Mapping[str, Any], key: str) -> tuple[CutRule, ...]:
    value = cfg.get(key)
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            _warn(key, "not valid JSON")
            return ()
    if not isinstance(value, list):
        _warn(key, "expected a list of rules")
        return ()
    rules = [_one_cut(entry) for entry in value]
    for index in (i for i, rule in enumerate(rules) if rule is None):
        logger.warning("hindsight-house: dropping %s rule %d (bad shape or pattern)", key, index)
    return tuple(rule for rule in rules if rule is not None)


def parse_house_settings(cfg: Mapping[str, Any] | None) -> HouseSettings:
    """Parse the house keys from a provider config dict. Never raises."""
    cfg = {} if cfg is None else cfg
    if not isinstance(cfg, Mapping):
        return _warn("config", "expected a mapping") or HouseSettings()
    if cfg.get("recall_topic_rules"):  # not built; warn and ignore
        logger.warning("hindsight-house: recall_topic_rules is set but topic scoping is not built; ignored")
    return HouseSettings(
        exclude_tags=_to_tags(cfg, "recall_exclude_tags"),
        max_results=_to_int(cfg, "recall_max_results", 0),
        recall_cron=_to_bool(cfg, "recall_cron", False),
        mirror_builtin_memory=_to_bool(cfg, "mirror_builtin_memory", False),
        query_cuts=_to_cuts(cfg, "recall_query_cuts"),
        short_query_chars=_to_int(cfg, "recall_short_query_chars", 0),
        short_query_context_chars=_to_int(cfg, "recall_short_query_context_chars", 400),
    )
