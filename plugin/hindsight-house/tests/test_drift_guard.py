"""Tests for drift_guard.py: hashes, outcomes, the flag writer, no import-time work."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import drift_guard as dg
from helpers import HOUSE, VARIANTS, edited, fake_stock, stock_source

REVIEWED_123 = {  # first 10 characters of the 1.2.3 hashes, as recorded by an independent review of the stock source
    "_recall": "7d6b2ae879", "_do_recall": "ca0f8d1226", "prefetch": "944b8108a3", "queue_prefetch": "e025a3e240",
    "_recall_disabled": "1c9b69e883", "_tool_recall": "a9942b06bd", "handle_tool_call": "187e80e3d5",
    "on_memory_write": "1db709af20", "_apply_recall_settings": "8e00346e13", "_apply_retain_policy": "aa16af4f18",
    "post_setup": "067804defc", "_run_hindsight_operation": "b88a3182a9", "_TOOL_HANDLERS": "7288fcb020",
}


class GoodClient:
    async def arecall(self, bank_id, query, *, tag_groups=None, min_scores=None, **kw):
        return None


class NoMinScores:
    async def arecall(self, bank_id, query, *, tag_groups=None):
        return None


class NoTagGroups:
    async def arecall(self, bank_id, query, *, min_scores=None):
        return None


def run(tmp_path: Path, source: str | None = None, **kw):
    return dg.check(fake_stock(tmp_path, source), client_cls=kw.pop("client_cls", GoodClient), **kw)


def test_stock_123_is_ok(tmp_path):
    assert run(tmp_path) == dg.GuardResult("OK", "1.2.3", (), "")


def test_the_known_row_is_the_recomputed_one_and_matches_the_reviewed_table(tmp_path):
    row = json.loads((HOUSE / "known_stock.json").read_text())["revisions"]["1.2.3"]
    hashes, sigs = dg.symbol_table(stock_source())
    assert row["hashes"] == hashes and row["signatures"] == sigs
    assert {k: v[:10] for k, v in hashes.items()} == REVIEWED_123
    assert set(json.loads((HOUSE / "known_stock.json").read_text())["revisions"]) == {"1.2.3"}
    assert row["source_sha256_12"] == "1b1436b80e27"


def test_main_drifts_on_exactly_the_three_symbols(tmp_path):
    main = (VARIANTS / "stock_main_init.py").read_text(encoding="utf-8")
    assert run(tmp_path, main) == dg.GuardResult("DRIFT", "unknown", ("queue_prefetch", "on_memory_write", "_apply_retain_policy"), "")


def test_121_drifts_and_has_no_on_memory_write(tmp_path):
    old = (VARIANTS / "stock_121" / "__init__.py").read_text(encoding="utf-8")
    res = run(tmp_path, old)
    assert res.status == "DRIFT" and res.revision == "unknown"
    assert res.failed == ("_recall", "_do_recall", "queue_prefetch", "_run_hindsight_operation", "handle_tool_call",
                          "on_memory_write", "_apply_recall_settings", "_apply_retain_policy", "sig:on_memory_write")


def test_a_docstring_only_edit_stays_ok(tmp_path):
    assert run(tmp_path, edited("Semantic recall across the write set", "Edited text across the write set")).status == "OK"
    assert run(tmp_path, edited('        """Guards shared by the async and synchronous recall paths."""\n', "")).status == "OK"


def test_a_comment_or_blank_line_edit_stays_ok(tmp_path):
    assert run(tmp_path, edited("        bank_ids = [\n            bank_id\n", "        # a comment\n\n        bank_ids = [\n            bank_id\n")).status == "OK"


def test_a_logic_edit_is_drift_on_that_symbol_only(tmp_path):
    res = run(tmp_path, edited('"tools-only mode"', '"tools only mode"'))
    assert res == dg.GuardResult("DRIFT", "unknown", ("_recall_disabled",), "")


def test_a_signature_edit_is_drift_with_the_sig_entry(tmp_path):
    res = run(tmp_path, edited('def prefetch(self, query: str, *, session_id: str = "") -> str:', 'def prefetch(self, query: str, session_id: str = "") -> str:'))
    assert res.failed == ("prefetch", "sig:prefetch") and res.status == "DRIFT"


def test_a_docstring_only_function_body_hashes_like_pass():
    base = "class HindsightMemoryProvider:\n    def post_setup(self):\n"
    assert dg.symbol_table(base + '        """Only a docstring."""\n') == dg.symbol_table(base + "        pass\n")
    assert dg.symbol_table(base + '        """one"""\n        return 1\n')[0] == dg.symbol_table(base + '        """two"""\n        return 1\n')[0]
    assert dg.symbol_table(base + "        return 1\n")[0] != dg.symbol_table(base + "        return 2\n")[0]


def test_an_async_guarded_method_is_hashed_and_a_string_statement_that_is_not_first_counts():
    base = "class HindsightMemoryProvider:\n"
    table = dg.symbol_table(base + "    async def prefetch(self, q):\n        return 1\n    def post_setup(self):\n        x = 1\n        'late string'\n")[0]
    assert set(table) == {"prefetch", "post_setup"}
    other = dg.symbol_table(base + "    async def prefetch(self, q):\n        return 1\n    def post_setup(self):\n        x = 1\n")[0]
    assert table["post_setup"] != other["post_setup"] and table["prefetch"] == other["prefetch"]


def test_a_non_string_first_expression_is_not_a_docstring():
    base = "class HindsightMemoryProvider:\n    def post_setup(self):\n"
    assert dg.symbol_table(base + "        1\n        return 2\n")[0] != dg.symbol_table(base + "        return 2\n")[0]


def test_tool_handlers_assignment_is_hashed_and_other_assignments_are_not():
    base = "class HindsightMemoryProvider:\n    OTHER = {1: 2}\n    _TOOL_HANDLERS = %s\n"
    assert set(dg.symbol_table(base % "{1: 2}")[0]) == {"_TOOL_HANDLERS"}
    assert dg.symbol_table(base % "{1: 2}")[0] != dg.symbol_table(base % "{1: 3}")[0]


def test_missing_stock_is_fatal_without_an_exception(tmp_path):
    for stock in (None, object(), fake_stock(tmp_path, "def f(:\n"), fake_stock(tmp_path, "x = 1\n")):
        res = dg.check(stock, client_cls=GoodClient)
        assert res.status == "FATAL" and res.revision == "none" and len(res.failed) == 1
    assert dg.check(None, client_cls=GoodClient).failed == ("stock:missing",)
    assert dg.check(fake_stock(tmp_path, "x = 1\n"), client_cls=GoodClient).failed == ("guard:LookupError",)
    assert dg.check(fake_stock(tmp_path, "def f(:\n"), client_cls=GoodClient).failed == ("guard:SyntaxError",)
    gone = type("M", (), {"__file__": str(tmp_path / "nope.py")})
    assert dg.check(gone, client_cls=GoodClient).failed == ("guard:FileNotFoundError",)


def test_client_problems(tmp_path, monkeypatch):
    assert run(tmp_path, client_cls=NoMinScores) == dg.GuardResult("DRIFT", "1.2.3", ("client:min_scores",), "")
    assert run(tmp_path, client_cls=NoTagGroups).failed == ("client:tag_groups",)
    assert run(tmp_path, client_cls=type("Both", (), {"arecall": lambda self, bank_id: None})).failed == ("client:tag_groups", "client:min_scores")
    assert run(tmp_path, client_cls=object).failed == ("client:missing",)
    assert run(tmp_path, client_cls=type("Odd", (), {"arecall": 5})).failed == ("client:missing",)

    def boom(name):
        raise ImportError(name)

    monkeypatch.setattr(dg.importlib, "import_module", boom)
    res = dg.check(fake_stock(tmp_path))
    assert res == dg.GuardResult("FATAL", "none", ("client:missing",), "client:missing")


def test_the_real_installed_client_passes_check_four(tmp_path):
    assert dg.check(fake_stock(tmp_path)).status == "OK"


def test_known_file_problems(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"revisions": {}}))
    assert dg.check(fake_stock(tmp_path), empty, GoodClient).failed == ("known:empty",)
    assert dg.check(fake_stock(tmp_path), tmp_path / "none.json", GoodClient).failed == ("guard:FileNotFoundError",)


def test_the_closest_revision_is_chosen_and_named(tmp_path):
    row = json.loads((HOUSE / "known_stock.json").read_text())["revisions"]["1.2.3"]
    far = {"hashes": {k: "0" * 16 for k in row["hashes"]}, "signatures": row["signatures"]}
    path = tmp_path / "two.json"
    path.write_text(json.dumps({"revisions": {"far": far, "1.2.3": row}}))
    assert dg.check(fake_stock(tmp_path), path, GoodClient) == dg.GuardResult("OK", "1.2.3", (), "")
    path.write_text(json.dumps({"revisions": {"1.2.3": row, "far": far}}))
    assert dg.check(fake_stock(tmp_path), path, GoodClient).revision == "1.2.3"


def test_flag_first_write_and_content(tmp_path):
    res = dg.GuardResult("DRIFT", "unknown", ("a", "sig:a"), "d")
    assert dg.write_flag(tmp_path, res, now=0.0) is True
    path = tmp_path / "hindsight-house" / "guard_state.json"
    assert json.loads(path.read_text()) == {"status": "DRIFT", "revision": "unknown", "failed": ["a", "sig:a"], "detail": "d",
                                            "written_at": 0.0, "written_at_iso": "1970-01-01T00:00:00Z"}
    assert [p.name for p in path.parent.iterdir()] == ["guard_state.json"]


def test_flag_rewrite_rules(tmp_path):
    ok, drift = dg.GuardResult("OK", "1.2.3", ()), dg.GuardResult("DRIFT", "unknown", ("a",))
    assert dg.write_flag(tmp_path, ok, now=1000.0) is True
    assert dg.write_flag(tmp_path, ok, now=1000.0 + 3599) is False
    assert dg.write_flag(tmp_path, ok, now=1000.0 + 3600) is True
    assert dg.write_flag(tmp_path, drift, now=4601.0) is True
    assert dg.write_flag(tmp_path, dg.GuardResult("DRIFT", "unknown", ("a", "b")), now=4602.0) is True
    assert dg.write_flag(tmp_path, dg.GuardResult("DRIFT", "unknown", ("a", "b")), now=4603.0) is False
    assert dg.write_flag(tmp_path, ok, now=4604.0) is True


def test_flag_uses_the_clock_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(dg.time, "time", lambda: 86400.0)
    assert dg.write_flag(tmp_path, dg.GuardResult("OK", "1.2.3", ())) is True
    assert json.loads((tmp_path / "hindsight-house" / "guard_state.json").read_text())["written_at"] == 86400.0


def test_flag_ignores_a_broken_previous_file(tmp_path):
    path = tmp_path / "hindsight-house" / "guard_state.json"
    path.parent.mkdir()
    ok = dg.GuardResult("OK", "1.2.3", ())
    for text in ("not json", "[]", ""):
        path.write_text(text)
        assert dg.write_flag(tmp_path, ok, now=5.0) is True
        assert json.loads(path.read_text())["status"] == "OK"


def test_flag_never_raises(tmp_path, monkeypatch):
    ok = dg.GuardResult("OK", "1.2.3", ())
    assert dg.write_flag("relative/home", ok) is False
    assert dg.write_flag(None, ok) is False
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert dg.write_flag(blocker, ok) is False
    assert dg.write_flag(tmp_path, ok, now=1.0) is True

    def broken(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    assert dg.write_flag(tmp_path, dg.GuardResult("DRIFT", "unknown", ("a",)), now=2.0) is False
    folder = tmp_path / "hindsight-house"
    assert [p.name for p in folder.iterdir()] == ["guard_state.json"]
    assert json.loads((folder / "guard_state.json").read_text())["status"] == "OK"


def test_no_import_time_work_in_the_new_modules():
    allowed_calls = {"getLogger", "tuple", "NamedTuple"}
    for name in ("drift_guard.py", "degraded.py", "__init__.py"):
        tree = ast.parse((HOUSE / name).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
                continue
            calls = {getattr(n.func, "attr", getattr(n.func, "id", "")) for n in ast.walk(node) if isinstance(n, ast.Call)}
            assert isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)), (name, node.lineno)
            assert calls <= allowed_calls | {"local"}, (name, node.lineno, calls)


def test_flag_file_text_tmp_name_and_missing_home_directory(tmp_path, monkeypatch):
    seen = []
    real = os.replace

    def spy(src, dst):
        seen.append((Path(src), Path(dst)))
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    home = tmp_path / "a" / "b"
    assert dg.write_flag(home, dg.GuardResult("DRIFT", "unknown", ("z", "a"), "d"), now=7.0) is True
    target = home / "hindsight-house" / "guard_state.json"
    body = {"status": "DRIFT", "revision": "unknown", "failed": ["z", "a"], "detail": "d", "written_at": 7.0,
            "written_at_iso": "1970-01-01T00:00:07Z"}
    assert target.read_text(encoding="utf-8") == json.dumps(body, sort_keys=True) + "\n"
    ((src, dst),) = seen
    assert dst == target and src.parent == target.parent and src.name.startswith(".guard_state.") and src.name.endswith(".tmp")


def test_flag_without_written_at_counts_as_epoch_zero(tmp_path):
    path = tmp_path / "hindsight-house" / "guard_state.json"
    path.parent.mkdir()
    ok = dg.GuardResult("OK", "1.2.3", ())
    path.write_text(json.dumps({"status": "OK", "failed": []}))
    assert dg.write_flag(tmp_path, ok, now=3600.5) is True
    path.write_text(json.dumps({"status": "OK", "failed": []}))
    assert dg.write_flag(tmp_path, ok, now=3599.5) is False


def test_the_two_error_log_lines_are_exact(tmp_path, caplog):
    caplog.set_level("WARNING")
    dg.check(type("M", (), {"__file__": str(tmp_path / "nope.py")}), client_cls=GoodClient)
    dg.write_flag(None, dg.GuardResult("OK", "1.2.3", ()))
    assert caplog.messages == ["HINDSIGHT_HOUSE_GUARD check failed: FileNotFoundError", "HINDSIGHT_HOUSE_GUARD flag not written: TypeError"]


def test_symbol_table_errors_and_non_name_assignment_targets():
    try:
        dg.symbol_table("x = 1\n")
        raise AssertionError("expected LookupError")
    except LookupError as exc:
        assert str(exc) == "HindsightMemoryProvider"
    assert dg.symbol_table("class HindsightMemoryProvider:\n    obj.attr = 1\n    a, b = 1, 2\n") == ({}, {})


def test_a_tie_between_revisions_keeps_the_first(tmp_path):
    row = json.loads((HOUSE / "known_stock.json").read_text())["revisions"]["1.2.3"]
    path = tmp_path / "tie.json"
    path.write_text(json.dumps({"revisions": {"first": row, "second": row}}))
    assert dg.check(fake_stock(tmp_path), path, GoodClient) == dg.GuardResult("OK", "first", (), "")
