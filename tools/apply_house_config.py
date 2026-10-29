#!/usr/bin/env python3
"""Apply the hindsight-house keys to one home's hindsight/config.json.

    apply_house_config.py --home HOME [--apply] [--drop-legacy]

Without --apply it is a dry run: it prints a key diff and writes nothing. With --apply it
writes HOME/hindsight/config.json: a dated backup copy first, then a temp file in the same
folder renamed over the original (atomic), with the original file mode.

It edits only that file. It never prints the value of any key that is not on WHITELIST
(so never api_key, api_url, a bank key or the preamble text). The diff shows only
whitelisted keys that change, with old and new value. Other key names are never listed.

Keys it writes
  recall_min_scores        {"final": <the profile's own recall_min_score>}; an existing valid
                           value is kept, and no floor is ever invented
  recall_cron              false
  mirror_builtin_memory    false
  recall_query_cuts        the house notice-cut rule
Keys it never touches: recall_max_results and the exclusion, short-query and preamble keys.
--drop-legacy removes recall_min_score when a valid recall_min_scores is in place, or when the legacy value is 0 (no floor either way).

Standard library only. Never imports hermes_bootstrap or any Hermes package.
Exit codes: 0 done (changed, nothing to change, or dry run); 2 refused (usage, no file,
not valid JSON, a value that cannot be copied safely); 1 the write failed.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

CONFIG_REL = os.path.join("hindsight", "config.json")
LEGACY_NAME = "recall_min_score"
FLOORS_NAME = "recall_min_scores"
SCORE_NAME = "final"  # the server guarantees "reranker" and "final" floors
# Keys the script may print a value for (trimmed to what this script touches or reports).
WHITELIST = (
    LEGACY_NAME,
    FLOORS_NAME,
    "recall_max_results",
    "recall_cron",
    "mirror_builtin_memory",
    "recall_query_cuts",
    "recall_exclude_tags",
    "recall_short_query_chars",
    "recall_short_query_context_chars",
    "recall_prompt_preamble",
)
UNCHANGED_REPORTED = (
    "recall_max_results",
    "recall_exclude_tags",
    "recall_short_query_chars",
    "recall_short_query_context_chars",
    "recall_prompt_preamble",
)
# The house notice-cut rule.
HOUSE_QUERY_CUTS: list[dict[str, Any]] = [
    {
        "applies_if": r"\A\s*\[IMPORTANT: Background process proc_[0-9a-f]{8,32} [^\n]{1,160}\n[ \t]*Command:",
        "cut_at": "Output:",
        "window": 400,
        "min_keep": 40,
    }
]
FIXED_HOUSE_VALUES: tuple[tuple[str, Any], ...] = (
    ("recall_cron", False),
    ("mirror_builtin_memory", False),
    ("recall_query_cuts", HOUSE_QUERY_CUTS),
)
MAX_SHOWN = 100


class Absent:
    """Marker: the key is not in the file (old side) or leaves the file (new side)."""


ABSENT = Absent()


class Refusal(Exception):
    """A reason the script will not run; the message never holds a config value."""


def normalize_floors(value: Any) -> dict[str, float] | None:
    """Adapted from stock settings._normalize_min_scores (1.2.3): a mapping or a JSON object
    string of finite numbers, as {name: float}; None when empty or invalid."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict):
        return None
    floors: dict[str, float] = {}
    for name, floor in value.items():
        if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not math.isfinite(floor):
            return None
        floors[str(name)] = float(floor)
    return floors or None


def plan(cfg: dict[str, Any], drop_legacy: bool) -> tuple[dict[str, Any], list[tuple[str, Any, Any]], list[str]]:
    """Pure merge. Returns (new_cfg, changes, notes). changes holds (key, old, new) with ABSENT
    for a missing or removed side. Raises Refusal when a value cannot be copied safely."""
    new = copy.deepcopy(cfg)
    changes: list[tuple[str, Any, Any]] = []
    notes: list[str] = []

    legacy = cfg.get(LEGACY_NAME, ABSENT)
    if FLOORS_NAME in cfg:
        if normalize_floors(cfg[FLOORS_NAME]) is None:
            raise Refusal(f"{FLOORS_NAME} is present but is not a non-empty object of finite numbers; fix it by hand")
        kept = shown(cfg[FLOORS_NAME])
        notes.append(f"{FLOORS_NAME}: kept the existing value {kept} ({LEGACY_NAME} is {shown(legacy)})")
    elif legacy is ABSENT:
        notes.append(f"{FLOORS_NAME}: no {LEGACY_NAME} to copy, so no floor is written")
    else:
        if isinstance(legacy, bool) or not isinstance(legacy, (int, float)) or not math.isfinite(legacy):
            raise Refusal(f"{LEGACY_NAME} is not a finite number; it is not copied")
        if legacy == 0:  # 1.2.1 sends no floor for 0; a 0.0 floor in 1.2.3 drops unscored results
            notes.append(f"{FLOORS_NAME}: {LEGACY_NAME} is 0 (no floor in 1.2.1), so no floor is written")
            legacy = ABSENT
    if legacy is not ABSENT and FLOORS_NAME not in cfg:
        new[FLOORS_NAME] = {SCORE_NAME: legacy}
        changes.append((FLOORS_NAME, ABSENT, new[FLOORS_NAME]))

    for key, wanted in FIXED_HOUSE_VALUES:
        if cfg.get(key, ABSENT) != wanted or (key in cfg and type(cfg[key]) is not type(wanted)):
            new[key] = copy.deepcopy(wanted)
            changes.append((key, cfg.get(key, ABSENT), new[key]))

    if drop_legacy:
        if LEGACY_NAME not in new:
            notes.append(f"{LEGACY_NAME}: already absent")
        else:  # recall_min_scores is in place here (kept or created), or legacy was 0 (no floor either way)
            changes.append((LEGACY_NAME, new[LEGACY_NAME], ABSENT))
            del new[LEGACY_NAME]
    return new, changes, notes


def shown(value: Any) -> str:
    if value is ABSENT:
        return "<absent>"
    text = json.dumps(value, ensure_ascii=True, sort_keys=True)
    return text if len(text) <= MAX_SHOWN else text[: MAX_SHOWN - 3] + "..."


def render(home: str, changes: list[tuple[str, Any, Any]], notes: list[str], cfg: dict[str, Any], dry: bool) -> list[str]:
    lines = [f"{'DRY RUN' if dry else 'APPLY'} home={home}"]
    for key, old, new in changes:
        if key not in WHITELIST:  # a bug guard: nothing outside the whitelist is ever printed
            raise Refusal("internal error: a key outside the whitelist reached the diff")
        lines.append(f"  {key}: {shown(old)} -> {shown(new)}")
    lines.extend(f"  note: {n}" for n in notes)
    present = [k for k in UNCHANGED_REPORTED if k in cfg]
    absent = [k for k in UNCHANGED_REPORTED if k not in cfg]
    lines.append("  untouched, present: " + (", ".join(present) or "-"))
    lines.append("  untouched, absent: " + (", ".join(absent) or "-"))
    if changes:
        lines.append(f"  {len(changes)} key(s) {'would change' if dry else 'changed'}")
    else:
        lines.append("  no change: every key is already in place")
    return lines


def load(path: Path) -> tuple[dict[str, Any], str, int]:
    if path.is_symlink():
        raise Refusal("hindsight/config.json is a symlink; it is not rewritten")
    try:
        st = path.stat()
        if not stat.S_ISREG(st.st_mode):  # checked before any read: a FIFO would block
            raise Refusal("hindsight/config.json is not a regular file")
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise Refusal("HOME has no hindsight/config.json") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal(f"hindsight/config.json is not readable ({type(exc).__name__})") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        line = getattr(exc, "lineno", "?")
        raise Refusal(f"hindsight/config.json is not valid JSON (line {line})") from None
    if not isinstance(data, dict):
        raise Refusal("hindsight/config.json is not a JSON object")
    return data, text, stat.S_IMODE(st.st_mode)


def dump_like(data: dict[str, Any], original: str) -> str:
    """Serialize with the original file's habits: indent, trailing newline, ASCII escapes."""
    indent: int | None = None
    for line in original.split("\n")[1:]:
        stripped = line.lstrip(" ")
        if stripped.startswith('"') and len(line) > len(stripped):
            indent = len(line) - len(stripped)
            break
    text = json.dumps(data, indent=indent, ensure_ascii=original.isascii())
    return text + ("\n" if original.endswith("\n") else "")


def backup_path(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now()))
    candidate = path.with_name(f"{path.name}.bak-{stamp}")
    n = 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.name}.bak-{stamp}-{n}")
    return candidate


def now() -> float:
    return time.time()


def write_atomic(path: Path, text: str, mode: int) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.json.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def run(home: str, apply: bool, drop_legacy: bool) -> tuple[int, list[str]]:
    home_path = Path(home)
    if not home_path.is_dir():
        return 2, ["REFUSED: HOME is not a folder"]
    path = home_path / CONFIG_REL
    try:
        cfg, original, mode = load(path)
        new, changes, notes = plan(cfg, drop_legacy)
        lines = render(home, changes, notes, cfg, dry=not apply)
    except Refusal as exc:
        return 2, [f"REFUSED: {exc}"]
    if not apply or not changes:
        return 0, lines
    try:
        backup = backup_path(path)
        shutil.copy2(path, backup)
        write_atomic(path, dump_like(new, original), mode)
        written, _, _ = load(path)
        if written != new:
            return 1, lines + [f"ERROR: the file read back differs from the plan; backup is {backup}"]
    except (OSError, Refusal) as exc:
        return 1, lines + [f"ERROR: write failed ({type(exc).__name__}); the original is unchanged or backed up"]
    return 0, lines + [f"  backup: {backup}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the hindsight-house keys to HOME/hindsight/config.json")
    parser.add_argument("--home", required=True, help="the Hermes home or a profile folder")
    parser.add_argument("--apply", action="store_true", help="write the file (default: dry run)")
    parser.add_argument("--drop-legacy", action="store_true", help="remove recall_min_score once recall_min_scores is in place")
    args = parser.parse_args(argv)
    code, lines = run(args.home, args.apply, args.drop_legacy)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
