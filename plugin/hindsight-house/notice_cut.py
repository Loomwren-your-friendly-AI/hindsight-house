"""Notice cut for the hindsight-house plugin: drop the output body of a background-process notice before recall.

Pure module: standard library only, no import-time work. ``cut_query(text, rules)`` takes the rules that
house_settings.parse_house_settings builds (each has applies_if, a compiled pattern, plus cut_at, window and
min_keep). Fail open: every doubt returns the text unchanged.
"""

from __future__ import annotations

from typing import Any, Iterable

LINE_STARTS = ("\n", "\r", "\u2028", "\u2029")  # a cut marker counts at index 0 or right after one of these


def _line_start_hit(text: str, marker: str) -> int:
    """Index of the first occurrence of *marker* at a line start, or -1."""
    pos = text.find(marker)
    while pos >= 0:
        if pos == 0 or text[pos - 1] in LINE_STARTS:
            return pos
        pos = text.find(marker, pos + 1)
    return -1


def cut_query(text: Any, rules: Iterable[Any]) -> Any:
    """Return the part of *text* before the first line-start ``cut_at`` marker, trailing whitespace stripped.

    The first rule that applies and gives a usable cut wins. A rule applies when ``applies_if`` matches (re.search)
    the first ``window`` characters. The cut is a prefix of the original text. A cut that keeps nothing, or fewer
    than ``min_keep`` characters, is not used (an empty cut is refused even when min_keep
    is 0). No rule fits: the text itself comes back.
    """
    if not isinstance(text, str):
        return text
    for rule in rules:
        if not rule.cut_at or not rule.applies_if.search(text[: rule.window]):
            continue
        hit = _line_start_hit(text, rule.cut_at)
        if hit < 0:
            continue
        kept = text[:hit].rstrip()
        if kept and len(kept) >= rule.min_keep:  # see the docstring
            return kept
    return text
