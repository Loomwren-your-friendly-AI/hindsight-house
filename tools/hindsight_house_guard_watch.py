#!/usr/bin/env python3
"""hindsight-house guard-watch: a script for a scheduler (no agent needed).

Reads, for each Hermes home it is given, the memory.provider value in
HOME/config.yaml and the drift-guard flag file HOME/hindsight-house/guard_state.json
(written by the hindsight-house plugin at process start). Prints one JSON line per
home whose provider is hindsight-house and whose flag is missing, unreadable or has
a status other than OK. Prints nothing otherwise. Exit code is 0 in both cases.

Output contract: one json.dumps line per problem (keys sorted), nothing when fine, exit 0.
Every line holds severity (warning or critical), event (a hindsight_house_* name), home,
profile (the last part of the home path) and flag (the flag file path). Some events add
reason; hindsight_house_not_ok adds status, revision, failed, detail and written_at_iso.
No state file: while a problem stands, every run prints its line again, so run it at a fixed interval.

Needs: Python 3.9 or newer, standard library only. PyYAML is used when importable;
without it a strict line scan of config.yaml reads memory.provider and never guesses
(an unusual layout gives provider unknown, which prints nothing).
A flag with an old written_at is NOT an error: the plugin writes it at process start only.

Never imports hermes_bootstrap or any Hermes package. Never runs the hermes command.

Homes: positional arguments, else the environment variable named in HOMES_ENV
(paths joined with os.pathsep). With neither there is no default list: it prints a
message on stderr and exits 2.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import stat
import sys
from typing import Any

PROVIDER = "hindsight-house"
HOMES_ENV = "HINDSIGHT_HOUSE_GUARD_WATCH_HOMES"
FLAG_REL = os.path.join("hindsight-house", "guard_state.json")
MAX_FLAG_BYTES = 65536
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_FAILED_ITEMS = 10

_yaml: Any = None
try:
    _yaml = importlib.import_module("yaml")
except ImportError:
    _yaml = None

_MEMORY_LINE = re.compile(r"^memory:[ ]*(?:#.*)?$")
_PROVIDER_LINE = re.compile(
    r"""^provider:
        (?:[ ]+(?:
            '(?P<sq>[^'\n]*)'
          | "(?P<dq>[^"\\\n]*)"
          | (?P<plain>[^\s#'"\[\]{}&*!|>%`,?:-][^#\n]*?)
        ))?
        (?:[ ]+\#.*)?[ ]*$""",
    re.VERBOSE,
)


def provider_from_lines(text: str) -> str | None:
    """Strict line scan for memory.provider. Returns None when not found or unsure."""
    return scan_lines(text)[0]


def scan_lines(text: str) -> tuple[str | None, bool]:
    """(provider, sure). sure is False when the layout is outside what the scan reads."""
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("memory:"):
            if start is not None or not _MEMORY_LINE.match(ln):
                return None, False
            start = i
    if start is None:
        return None, True
    found: list[str | None] = []
    child_indent: int | None = None
    for ln in lines[start + 1:]:
        body = ln.strip(" ")
        if not body or body.startswith("#"):
            continue
        if ln.startswith("\t"):  # YAML forbids tab indentation; Hermes cannot read this file either
            return None, False
        if not ln.startswith(" "):
            break
        lead = ln[: len(ln) - len(ln.lstrip(" "))]
        if ln[len(lead):].startswith("\t"):
            return None, False
        indent = len(lead)
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        if body.startswith("provider:"):
            m = _PROVIDER_LINE.match(body)
            if m is None:
                return None, False
            plain = (m.group("plain") or "").strip()
            if plain and (": " in plain or plain.endswith(":")):
                return None, False
            found.append(m.group("sq") or m.group("dq") or plain or None)
    if not found:
        return None, True
    if len(found) != 1:
        return None, False
    return found[0], True


def provider_from_yaml(text: str) -> str | None:
    return scan_yaml(text)[0]


def scan_yaml(text: str) -> tuple[str | None, bool]:
    """(provider, sure). An absent key is sure; a value of the wrong type is not."""
    data = _yaml.safe_load(text)
    if data is None:
        return None, True
    if not isinstance(data, dict):
        return None, False
    memory = data.get("memory")
    if memory is None:
        return None, True
    if not isinstance(memory, dict):
        return None, False
    value = memory.get("provider")
    if value is None:
        return None, True
    if not isinstance(value, str):
        return None, False
    return value, True


def provider_state(home: str) -> tuple[str | None, str]:
    """(provider, problem). problem is empty when HOME/config.yaml was read and understood."""
    path = os.path.join(home, "config.yaml")
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            return None, "config too large"
        text = raw.decode("utf-8")
        value, sure = scan_yaml(text) if _yaml is not None else scan_lines(text)
    except FileNotFoundError:
        return None, "config missing"
    except OSError as exc:
        return None, type(exc).__name__
    except ValueError:
        return None, "config not UTF-8"
    except Exception:  # a yaml error or a hostile document must not stop the watch
        return None, "config not parsed"
    return (value, "") if sure else (None, "provider not determinable")


def read_provider(home: str) -> str | None:
    """memory.provider of HOME/config.yaml, or None (missing, unreadable, unknown)."""
    return provider_state(home)[0]


def house_present(home: str) -> bool:
    """True when HOME holds the house plugin folder or a guard flag."""
    plugin = os.path.join(home, "plugins", PROVIDER)
    return os.path.isdir(plugin) or os.path.lexists(os.path.join(home, FLAG_REL))


def read_flag(home: str) -> tuple[str, dict[str, Any] | None, str]:
    """Returns (state, data, reason). state is missing, unreadable or read."""
    path = os.path.join(home, FLAG_REL)
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return "missing", None, ""
    except OSError as exc:
        return "unreadable", None, type(exc).__name__
    if not stat.S_ISREG(st.st_mode):
        return "unreadable", None, "not a regular file"
    if st.st_size > MAX_FLAG_BYTES:
        return "unreadable", None, "too large"
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_FLAG_BYTES + 1)
        data = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return "missing", None, ""
    except OSError as exc:
        return "unreadable", None, type(exc).__name__
    except ValueError:
        return "unreadable", None, "invalid JSON"
    if not isinstance(data, dict):
        return "unreadable", None, "not an object"
    if not isinstance(data.get("status"), str):
        return "unreadable", None, "no status"
    return "read", data, ""


def _clip(value: Any, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def _failed(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:60] for item in value[:MAX_FAILED_ITEMS]]


def label_for(home: str) -> str:
    return os.path.basename(os.path.normpath(home))


def check_home(home: str) -> dict[str, Any] | None:
    """One problem record for HOME, or None when nothing needs saying."""
    flag_path = os.path.join(home, FLAG_REL)
    base: dict[str, Any] = {"home": home, "profile": label_for(home), "flag": flag_path}
    provider, problem = provider_state(home)
    if problem:
        if not house_present(home):
            return None
        return {**base, "severity": "warning", "event": "hindsight_house_provider_unreadable", "reason": problem}
    if provider != PROVIDER:
        near = isinstance(provider, str) and provider.strip(" \t'\"").lower() == PROVIDER
        if near and house_present(home):
            return {**base, "severity": "warning", "event": "hindsight_house_provider_malformed"}
        return None
    state, data, reason = read_flag(home)
    if state == "missing":
        return {**base, "severity": "warning", "event": "hindsight_house_flag_missing"}
    if state == "unreadable" or data is None:
        return {**base, "severity": "warning", "event": "hindsight_house_flag_unreadable", "reason": reason}
    status = data["status"]
    if status == "OK":
        return None
    return {
        **base,
        "severity": "critical" if status == "FATAL" else "warning",
        "event": "hindsight_house_not_ok",
        "status": status[:40],
        "revision": _clip(data.get("revision"), 40),
        "failed": _failed(data.get("failed")),
        "detail": _clip(data.get("detail"), 200),
        "written_at_iso": _clip(data.get("written_at_iso"), 40),
    }


def resolve_homes(args: list[str], env: Any) -> list[str]:
    if args:
        return list(args)
    from_env = str(env.get(HOMES_ENV, ""))
    if from_env.strip():
        return [p for p in from_env.split(os.pathsep) if p]
    return []


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    homes = resolve_homes(args, os.environ)
    if not homes:
        print(f"{PROVIDER}-guard-watch: no homes given: pass home folders as arguments or set {HOMES_ENV}", file=sys.stderr)
        return 2
    for home in homes:
        try:
            record = check_home(home)
        except Exception as exc:  # a bug here must be visible, not silent
            record = {"severity": "warning", "event": "hindsight_house_guard_watch_error",
                      "home": home, "reason": type(exc).__name__}
        if record is not None:
            print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
