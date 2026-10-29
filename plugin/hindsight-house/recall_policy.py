"""Recall policy for the hindsight-house plugin: pure functions, standard library only.

``policy`` is any object with the attributes of house_settings.HouseSettings (exclude_tags, max_results,
short_query_chars, short_query_context_chars). No import-time work, no file or network access.
Parts: rewrite_kwargs and the cap, and the short-query context (see the notes at each function).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Mapping, Sequence

logger = logging.getLogger(__name__.rpartition(".")[0] or __name__)  # same rule as stock settings.py

ORIGIN_AUTO = "auto"
ORIGIN_TOOL = "tool"

# Short-query context shape and limits: the constants of the earlier patched plugin (same values).
CTX_HEADER = "Context (assistant's previous statement): "
CTX_SEP = "\nUser message: "
CUE_LOOKBACK = 40  # the cue rule also reads this many characters before the tail that would be sent
MIN_ROOM = 40  # with a bounded recall_max_input_chars, less room than this adds no context

# Credential cues, ported unchanged from the earlier patched plugin (_SHORT_CTX_CREDENTIAL_CUES). Matching runs on LOWERCASED text.
# Entry = (cue class, regex). Only the cue class is ever logged. An empty tuple turns the rule off.
CREDENTIAL_CUES = (
    ("word", r"password"),
    ("word", r"passwd"),
    ("word", r"passphrase"),
    ("word", r"api[ _-]?key"),
    ("word", r"private[ _-]?key"),
    ("word", r"bearer"),
    ("word", r"credential"),
    # six to eight digits within 40 characters of otp / one-time / verification / 2fa, either order
    ("code", r"(?:otp|one[ -]time|verification|2fa)[^\n]{0,40}?(?<![0-9])[0-9]{6,8}(?![0-9])"),
    ("code", r"(?<![0-9])[0-9]{6,8}(?![0-9])[^\n]{0,40}?(?:otp|one[ -]time|verification|2fa)"),
    ("base64", r"[a-z0-9+/=]{60,}"),  # 60 or more base64-alphabet characters in a row
    ("pem", r"(?m)^[ \t-]*(?:begin|end)\s[a-z0-9 ]{0,30}?\b(?:key|pgp)"),  # PEM / PGP armor line
    ("url", r"://[^\s/@]+:[^\s/@]*@"),  # credentials in URL userinfo
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def credential_cue(text: str, cues: Sequence[tuple[str, str]] = CREDENTIAL_CUES) -> tuple[str, str] | None:
    """The first (cue class, pattern) entry of *cues* that matches *text*, else None."""
    low = text.lower()
    for entry in cues:
        if re.search(entry[1], low):
            return entry
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value]
    return list(value) if isinstance(value, (list, tuple)) else []


def rewrite_kwargs(kwargs: Mapping[str, Any], policy: Any, origin: str) -> dict[str, Any]:
    """Fold the exclusion tags into ``tag_groups``. Port of the earlier ``_tag_filter_kwargs`` (topic scoping not built).

    No exclusion: the kwargs come back unchanged (same object, stock parity). With an exclusion the input is never
    mutated: ``tags`` and ``tags_match`` are removed, the inclusion tags become a leaf, and one ``not`` leaf is added.
    ``tags`` and ``tag_groups`` are never both returned (the API answers HTTP 422). The exclusion applies to every
    origin; *origin* is accepted so the proxy passes one call shape, and the cap is cap_results' business.
    """
    exclusion = list(getattr(policy, "exclude_tags", None) or ())
    if not exclusion:
        return kwargs  # type: ignore[return-value]
    out = {k: v for k, v in kwargs.items() if k not in ("tags", "tags_match")}  # tag_groups is set below
    # a tag_groups list that stock built is kept and appended to (stock 1.2.3 sets none).
    groups = list(kwargs.get("tag_groups") or [])
    inclusion = _as_list(kwargs.get("tags"))
    if inclusion:
        groups.append({"tags": inclusion, "match": kwargs.get("tags_match", "any")})
    groups.append({"not": {"tags": exclusion}})
    out["tag_groups"] = groups
    return out


def cap_results(results: Sequence[Any], policy: Any, origin: str) -> Sequence[Any]:
    """Cut the list to ``policy.max_results`` on the auto path only. 0 or less, or the tool path: unchanged."""
    cap = getattr(policy, "max_results", 0) or 0
    if origin != ORIGIN_AUTO or cap <= 0:
        return results
    return results[:cap]


def compose_short_query(
    query: Any, previous: Any, policy: Any, max_input_chars: int = 0, redact: Callable[[str], str] | None = None
) -> Any:
    """Prefix a short auto-injection query with the tail of the previous assistant statement. Port of the earlier
    ``_with_short_query_context``. *previous* is scrubbed here by *redact* (pass Hermes' _redact_for_provider);
    no redact callable, or one that fails, adds no context (like the earlier ImportError path). Returns *query* itself when there is nothing to add: the rule is
    off, the query is long enough, nothing is known, too little room is left, or a credential cue matches.
    """
    limit = getattr(policy, "short_query_chars", 0) or 0
    ctx_chars = getattr(policy, "short_query_context_chars", 0) or 0
    if not (limit > 0 and ctx_chars > 0 and isinstance(query, str) and query.strip()):
        return query
    if len(query.strip()) >= limit or not isinstance(previous, str):
        return query
    if redact is None:
        logger.debug("Recall: short-query context skipped (no redaction step)")
        return query
    try:
        scrubbed = redact(previous)
    except Exception as exc:  # the earlier helper catches every failure here and sends the query unchanged
        logger.debug("Recall: short-query context skipped (%s)", type(exc).__name__)
        return query
    if not isinstance(scrubbed, str):
        return query
    prev = _CONTROL_CHARS.sub("", scrubbed).strip()
    if max_input_chars:  # the user's own words are never cut: context gets what is left
        room = max_input_chars - len(CTX_HEADER) - len(CTX_SEP) - len(query)
        if room < MIN_ROOM:
            return query
        ctx_chars = min(ctx_chars, room)
    if not prev:
        return query
    cue = credential_cue(prev[-(ctx_chars + CUE_LOOKBACK):])  # the tail plus the text just before it
    if cue:
        logger.debug("Recall: short-query context skipped (credential cue: %s)", cue[0])
        return query
    return f"{CTX_HEADER}{prev[-ctx_chars:]}{CTX_SEP}{query}"
