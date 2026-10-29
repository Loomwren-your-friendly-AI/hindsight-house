"""Drift guard for the hindsight-house plugin. No import-time work, no network, never raises.

``check(stock_module)`` hashes the guarded symbols of the stock provider (docstrings stripped, so a docstring-only
upstream edit stays OK), compares them and the recorded signatures with ``known_stock.json``, and looks at the
``hindsight_client.Hindsight.arecall`` signature. ``write_flag`` records the outcome for the guard-watch job.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import inspect
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

STATUS_OK, STATUS_DRIFT, STATUS_FATAL = "OK", "DRIFT", "FATAL"
CLASS_NAME = "HindsightMemoryProvider"
GUARDED = (
    "_recall", "_do_recall", "prefetch", "queue_prefetch", "_run_hindsight_operation", "_recall_disabled",
    "_tool_recall", "handle_tool_call", "_TOOL_HANDLERS", "on_memory_write", "_apply_recall_settings",
    "_apply_retain_policy", "post_setup",
)
SIGNATURE_SYMBOLS = tuple(name for name in GUARDED if name != "_TOOL_HANDLERS")
CLIENT_PARAMS = ("tag_groups", "min_scores")
KNOWN_FILE = "known_stock.json"
FLAG_DIR, FLAG_FILE = "hindsight-house", "guard_state.json"
FLAG_MIN_INTERVAL_S = 3600.0


class GuardResult(NamedTuple):
    status: str
    revision: str
    failed: tuple[str, ...]
    detail: str = ""


def _strip_docstring(node: Any) -> Any:
    """A copy of a function node without its leading docstring (a docstring-only body becomes ``pass``)."""
    body = list(node.body)
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        node = copy.copy(node)
        node.body = body[1:] or [ast.Pass()]
    return node


def _digest(node: Any) -> str:
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()[:16]


def symbol_table(source: str) -> tuple[dict[str, str], dict[str, str]]:
    """(hashes, signatures) of the guarded symbols in the stock class body. Raises SyntaxError or LookupError."""
    tree = ast.parse(source)
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == CLASS_NAME), None)
    if cls is None:
        raise LookupError(CLASS_NAME)
    hashes: dict[str, str] = {}
    signatures: dict[str, str] = {}
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in GUARDED:
            hashes[node.name] = _digest(_strip_docstring(node))
            signatures[node.name] = ast.unparse(node.args)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_TOOL_HANDLERS" for t in node.targets):
            hashes["_TOOL_HANDLERS"] = _digest(node.value)
    return hashes, signatures


def _client_params(client_cls: Any) -> set[str] | None:
    """Named parameters of ``arecall``; None when the client cannot be read at all."""
    if client_cls is None:
        try:
            client_cls = importlib.import_module("hindsight_client").Hindsight
        except Exception:
            return None
    try:
        return set(inspect.signature(client_cls.arecall).parameters)
    except (AttributeError, TypeError, ValueError):
        return None


def _fatal(why: str) -> GuardResult:
    return GuardResult(STATUS_FATAL, "none", (why,), why)


# The guard reads the stock source text (never runs it); a missing hindsight_client is FATAL
def _check(stock_module: Any, known_path: Path | None, client_cls: Any) -> GuardResult:
    stock_file = getattr(stock_module, "__file__", None)
    if not stock_file:
        return _fatal("stock:missing")
    hashes, signatures = symbol_table(Path(stock_file).read_text(encoding="utf-8"))
    params = _client_params(client_cls)
    if params is None:
        return _fatal("client:missing")
    path = known_path or Path(__file__).with_name(KNOWN_FILE)
    revisions = json.loads(path.read_text(encoding="utf-8")).get("revisions") or {}
    if not revisions:
        return _fatal("known:empty")
    best_rev, best_failed = "unknown", None
    for rev, row in revisions.items():
        failed = tuple(s for s in GUARDED if hashes.get(s) != row["hashes"].get(s))
        failed += tuple("sig:" + s for s in SIGNATURE_SYMBOLS if signatures.get(s) != row["signatures"].get(s))
        if best_failed is None or len(failed) < len(best_failed):
            best_rev, best_failed = rev, failed
    failed = (best_failed or ()) + tuple("client:" + p for p in CLIENT_PARAMS if p not in params)
    revision = best_rev if not best_failed else "unknown"
    return GuardResult(STATUS_DRIFT if failed else STATUS_OK, revision, failed)


def check(stock_module: Any, known_path: Path | None = None, client_cls: Any = None) -> GuardResult:
    """OK, DRIFT or FATAL for the stock provider module. Any internal failure is FATAL, never an exception."""
    try:
        return _check(stock_module, known_path, client_cls)
    except Exception as exc:
        logger.error("HINDSIGHT_HOUSE_GUARD check failed: %s", type(exc).__name__)
        return _fatal("guard:" + type(exc).__name__)


def _previous_flag(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_flag(home: Any, result: GuardResult, now: float | None = None) -> bool:
    """Write ``<home>/hindsight-house/guard_state.json`` atomically when the status or the failed list changed,
    else at most once an hour (a fresh DRIFT is never hidden). Returns True when written. Never raises."""
    try:
        path = Path(home) / FLAG_DIR / FLAG_FILE
        if not path.is_absolute():
            return False
        stamp = time.time() if now is None else now
        old = _previous_flag(path)
        same = old.get("status") == result.status and old.get("failed") == list(result.failed)
        if same and stamp - float(old.get("written_at", 0)) < FLAG_MIN_INTERVAL_S:
            return False
        body = {
            "status": result.status, "revision": result.revision, "failed": list(result.failed),
            "detail": result.detail, "written_at": stamp,
            "written_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp)),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".guard_state.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(body, sort_keys=True) + "\n")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return True
    except Exception as exc:
        logger.warning("HINDSIGHT_HOUSE_GUARD flag not written: %s", type(exc).__name__)
        return False
