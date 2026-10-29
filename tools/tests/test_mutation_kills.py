"""Targeted tests added after the mutation run: exact reasons, messages, ordering, boundaries."""
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

import apply_house_config as ahc
import hindsight_house_guard_watch as gw

GOOD_CFG = "memory:\n  provider: hindsight-house\n"


def _home(tmp_path: Path, flag=None, cfg: str = GOOD_CFG, name: str = "h") -> Path:
    home = tmp_path / name
    home.mkdir()
    (home / "config.yaml").write_text(cfg, encoding="utf-8")
    if flag is not None:
        (home / "hindsight-house").mkdir()
        target = home / "hindsight-house" / "guard_state.json"
        target.write_bytes(flag if isinstance(flag, bytes) else json.dumps(flag).encode("utf-8"))
    return home


def test_read_flag_exact_states_and_reasons(tmp_path):
    cases = [
        (b"{not json", ("unreadable", "invalid JSON")),
        (b"[]", ("unreadable", "not an object")),
        (b'{"revision": "x"}', ("unreadable", "no status")),
        (b'{"status": 3}', ("unreadable", "no status")),
        (b'{"status": "OK"}', ("read", "")),
    ]
    for i, (body, (state, reason)) in enumerate(cases):
        home = _home(tmp_path, body, name=f"c{i}")
        got = gw.read_flag(str(home))
        assert (got[0], got[2]) == (state, reason), body
        assert (got[1] is None) == (state != "read")


def test_read_flag_missing_has_empty_reason(tmp_path):
    home = _home(tmp_path)
    assert gw.read_flag(str(home)) == ("missing", None, "")


def test_read_flag_size_boundary(tmp_path):
    pad = gw.MAX_FLAG_BYTES - len('{"status": "OK", "p": ""}')
    exact = ('{"status": "OK", "p": "' + "x" * pad + '"}').encode("utf-8")
    assert len(exact) == gw.MAX_FLAG_BYTES
    home = _home(tmp_path, exact)
    assert gw.read_flag(str(home))[0] == "read"
    flag = home / "hindsight-house" / "guard_state.json"
    flag.write_bytes(exact + b" ")
    assert gw.read_flag(str(home)) == ("unreadable", None, "too large")


def test_read_flag_special_file_reason(tmp_path):
    home = _home(tmp_path)
    (home / "hindsight-house").mkdir()
    (home / "hindsight-house" / "guard_state.json").mkdir()
    assert gw.read_flag(str(home)) == ("unreadable", None, "not a regular file")


def test_read_flag_decodes_utf8_exactly(tmp_path):
    home = _home(tmp_path, json.dumps({"status": "caf\u00e9"}, ensure_ascii=False).encode("utf-8"))
    assert gw.read_flag(str(home))[1] == {"status": "caf\u00e9"}


def test_record_fields_exact(tmp_path):
    home = _home(tmp_path, {"status": "DRIFT", "written_at_iso": "z" * 60, "revision": "r" * 60})
    rec = gw.check_home(str(home))
    assert rec is not None
    assert rec["flag"] == os.path.join(str(home), "hindsight-house", "guard_state.json")
    assert rec["written_at_iso"] == "z" * 40 and rec["revision"] == "r" * 40
    assert rec["severity"] == "warning" and rec["profile"] == "h"
    bad = _home(tmp_path, b"{", name="bad")
    assert gw.check_home(str(bad)) == {
        "severity": "warning", "event": "hindsight_house_flag_unreadable", "reason": "invalid JSON",
        "home": str(bad), "profile": "bad", "flag": os.path.join(str(bad), "hindsight-house", "guard_state.json"),
    }


def test_main_output_is_sorted_json_and_error_record(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path, {"status": "DRIFT"})
    gw.main([str(home)])
    line = capsys.readouterr().out.strip()
    assert list(json.loads(line)) == sorted(json.loads(line))

    def boom(h):
        raise KeyError("x")

    monkeypatch.setattr(gw, "check_home", boom)
    gw.main(["somewhere"])
    rec = json.loads(capsys.readouterr().out)
    assert rec == {"severity": "warning", "event": "hindsight_house_guard_watch_error",
                   "home": "somewhere", "reason": "KeyError"}
    assert list(rec) == sorted(rec)


def test_main_reads_sys_argv_when_called_without_arguments(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)
    monkeypatch.setattr(sys, "argv", ["prog", str(home)])
    monkeypatch.delenv(gw.HOMES_ENV, raising=False)
    assert gw.main() == 0
    assert json.loads(capsys.readouterr().out)["event"] == "hindsight_house_flag_missing"


def test_normalize_floors_exact_shapes():
    assert ahc.normalize_floors({"final": 1}) == {"final": 1.0}
    assert ahc.normalize_floors('{"a": 2, "b": 0.5}') == {"a": 2.0, "b": 0.5}
    assert isinstance(ahc.normalize_floors({"final": 1})["final"], float)
    assert ahc.normalize_floors(None) is None and ahc.normalize_floors("") is None
    assert ahc.normalize_floors({}) is None and ahc.normalize_floors("{}") is None


def test_house_value_is_not_aliased_into_the_output():
    new, _, _ = ahc.plan({}, drop_legacy=False)
    new["recall_query_cuts"][0]["cut_at"] = "changed"
    assert ahc.HOUSE_QUERY_CUTS[0]["cut_at"] == "Output:"
    again, _, _ = ahc.plan({}, drop_legacy=False)
    assert again["recall_query_cuts"][0]["cut_at"] == "Output:"


def test_load_messages_are_exact(tmp_path):
    def load_msg(text=None, link=False, folder=False, blob=None):
        home = tmp_path / f"l{len(list(tmp_path.iterdir()))}"
        (home / "hindsight").mkdir(parents=True)
        path = home / "hindsight" / "config.json"
        if folder:
            path.mkdir()
        elif link:
            path.symlink_to(tmp_path)
        elif blob is not None:
            path.write_bytes(blob)
        elif text is not None:
            path.write_text(text, encoding="utf-8")
        with pytest.raises(ahc.Refusal) as info:
            ahc.load(path)
        return str(info.value)

    assert load_msg(link=True) == "hindsight/config.json is a symlink; it is not rewritten"
    assert load_msg(folder=True) == "hindsight/config.json is not a regular file"
    assert load_msg() == "HOME has no hindsight/config.json"
    assert load_msg(text='{\n"a": 1,\n"b": }') == "hindsight/config.json is not valid JSON (line 3)"
    assert load_msg(text="[1]") == "hindsight/config.json is not a JSON object"
    assert load_msg(blob=b'{"a": "\xff"}') == "hindsight/config.json is not readable (UnicodeDecodeError)"


def test_load_reads_utf8(tmp_path):
    home = tmp_path / "u"
    (home / "hindsight").mkdir(parents=True)
    (home / "hindsight" / "config.json").write_bytes(json.dumps({"k": "caf\u00e9"}, ensure_ascii=False).encode("utf-8"))
    assert ahc.load(home / "hindsight" / "config.json")[0] == {"k": "caf\u00e9"}


def test_render_labels_and_lists():
    cfg = {"recall_max_results": 3, "recall_exclude_tags": "a"}
    dry = ahc.render("H", [], [], cfg, dry=True)
    live = ahc.render("H", [], [], cfg, dry=False)
    assert dry[0] == "DRY RUN home=H" and live[0] == "APPLY home=H"
    assert "  untouched, present: recall_max_results, recall_exclude_tags" in dry
    assert "  untouched, absent: recall_short_query_chars, recall_short_query_context_chars, recall_prompt_preamble" in dry
    none_present = ahc.render("H", [], [], {}, dry=True)
    assert "  untouched, present: -" in none_present
    all_present = ahc.render("H", [], [], {k: 1 for k in ahc.UNCHANGED_REPORTED}, dry=True)
    assert "  untouched, absent: -" in all_present
    with pytest.raises(ahc.Refusal) as info:
        ahc.render("H", [("not_listed", ahc.ABSENT, 1)], [], {}, dry=True)
    assert str(info.value) == "internal error: a key outside the whitelist reached the diff"


def test_shown_boundaries():
    assert ahc.shown("x" * (ahc.MAX_SHOWN - 2)) == json.dumps("x" * (ahc.MAX_SHOWN - 2))  # exactly the cap
    over = ahc.shown("x" * ahc.MAX_SHOWN)
    assert len(over) == ahc.MAX_SHOWN and over.endswith("...")
    assert ahc.shown({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'


def test_backup_name_uses_the_clock_value(tmp_path, monkeypatch):
    monkeypatch.setattr(ahc, "now", lambda: 1_700_000_000.0)
    expected = time.strftime("%Y%m%d-%H%M%S", time.localtime(1_700_000_000.0))
    assert ahc.backup_path(tmp_path / "config.json").name == f"config.json.bak-{expected}"


def test_dump_like_indent_detection():
    assert ahc.dump_like({"a": 1}, '{\n    "a": 1\n}') == '{\n    "a": 1\n}'
    assert ahc.dump_like({"a": 1}, '{\n\t"a": 1\n}') == '{"a": 1}'


def test_write_atomic_temp_name_dir_and_encoding(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    seen = []
    real = os.replace

    def spy(src, dst):
        seen.append(Path(src))
        real(src, dst)

    monkeypatch.setattr(ahc.os, "replace", spy)
    ahc.write_atomic(path, '{"k": "caf\u00e9"}', 0o640)
    assert seen[0].parent == tmp_path and seen[0].name.startswith(".config.json.") and seen[0].name.endswith(".tmp")
    assert path.read_bytes() == '{"k": "caf\u00e9"}'.encode("utf-8")
    assert path.stat().st_mode & 0o7777 == 0o640


def test_write_atomic_cleans_up_and_tolerates_a_vanished_temp(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")

    def boom(src, dst):
        Path(src).unlink()  # the temp file is already gone when the cleanup runs
        raise OSError("disk")

    monkeypatch.setattr(ahc.os, "replace", boom)
    with pytest.raises(OSError, match="disk"):
        ahc.write_atomic(path, "{}", 0o600)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.json"]


def test_help_text_names_the_options(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "250")
    with pytest.raises(SystemExit) as info:
        ahc.main(["--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    assert "\nApply the hindsight-house keys to HOME/hindsight/config.json\n" in out
    assert re.search(r"\sthe Hermes home or a profile folder", out)
    assert re.search(r"\swrite the file \(default: dry run\)", out)
    assert re.search(r"\sremove recall_min_score once recall_min_scores is in place", out)


def test_line_scan_skips_comments_and_nested_lines():
    assert gw.provider_from_lines("memory:\n# top comment\n  provider: hindsight-house\n") == "hindsight-house"
    assert gw.provider_from_lines("memory:\n      # deep comment\n  provider: hindsight-house\n") == "hindsight-house"
    assert gw.provider_from_lines("memory:\n  other:\n    x: 1\n  provider: hindsight-house\n") == "hindsight-house"
    assert gw.provider_from_lines("memory:\n  provider: hindsight-house \t \n") == "hindsight-house"


def test_line_scan_empty_and_odd_values_are_unknown():
    assert gw.provider_from_lines("memory:\n  provider: ''\n") is None
    assert gw.provider_from_lines('memory:\n  provider: ""\n') is None
    assert gw.provider_from_lines("memory:\n  provider:\n") is None
    assert gw.provider_from_lines("memory:\n  provider: abc:\n") is None
    assert gw.provider_from_lines("memory:\n  provider: a: b\n") is None


def test_yaml_reader_direct_shapes():
    if gw._yaml is None:
        pytest.skip("no PyYAML")
    assert gw.provider_from_yaml("- a\n- b\n") is None
    assert gw.provider_from_yaml("memory: text\n") is None
    assert gw.provider_from_yaml("memory:\n  provider: 5\n") is None
    assert gw.provider_from_yaml("memory:\n  provider: [a]\n") is None
    assert gw.provider_from_yaml("") is None


def test_config_size_boundary(tmp_path):
    head = GOOD_CFG
    exact = head + "#" * (gw.MAX_CONFIG_BYTES - len(head) - 1) + "\n"
    assert len(exact.encode("utf-8")) == gw.MAX_CONFIG_BYTES
    home = _home(tmp_path, cfg=exact)
    assert gw.read_provider(str(home)) == "hindsight-house"
    (home / "config.yaml").write_text(exact + "#", encoding="utf-8")
    assert gw.read_provider(str(home)) is None


def test_read_flag_os_errors_and_vanished_flag(tmp_path, monkeypatch):
    if os.geteuid() != 0:
        home = _home(tmp_path, {"status": "OK"})
        flag = home / "hindsight-house" / "guard_state.json"
        flag.chmod(0)
        try:
            assert gw.read_flag(str(home)) == ("unreadable", None, "PermissionError")
        finally:
            flag.chmod(0o600)
        folder = home / "hindsight-house"
        folder.chmod(0)
        try:
            assert gw.read_flag(str(home)) == ("unreadable", None, "PermissionError")
        finally:
            folder.chmod(0o700)
    other = tmp_path / "real.json"
    other.write_text("{}", encoding="utf-8")
    real_stat = os.stat(other)
    gone = _home(tmp_path, name="gone")
    monkeypatch.setattr(gw.os, "stat", lambda path: real_stat)
    assert gw.read_flag(str(gone)) == ("missing", None, "")


def test_stat_oserror_is_reported_by_name(tmp_path, monkeypatch):
    def boom(path):
        raise PermissionError("no")

    monkeypatch.setattr(gw.os, "stat", boom)
    assert gw.read_flag(str(tmp_path)) == ("unreadable", None, "PermissionError")


def test_open_oserror_after_stat_is_reported_by_name(tmp_path, monkeypatch):
    home = _home(tmp_path, {"status": "OK"})

    def boom(*args, **kwargs):
        raise PermissionError("no")

    monkeypatch.setattr("builtins.open", boom)
    assert gw.read_flag(str(home)) == ("unreadable", None, "PermissionError")


def test_shown_is_ascii_only():
    assert ahc.shown("\u00e9") == '"\\u00e9"'


def test_dump_like_indent_edge_cases():
    assert ahc.dump_like({"a": 1}, '{\n"a": 1}') == '{"a": 1}'
    assert ahc.dump_like({"a": [1]}, '{"a": [\n    1]}') == '{"a": [1]}'


def test_run_prints_the_home_it_was_given(tmp_path):
    home = tmp_path / "h"
    (home / "hindsight").mkdir(parents=True)
    (home / "hindsight" / "config.json").write_text("{}", encoding="utf-8")
    code, lines = ahc.run(str(home), apply=False, drop_legacy=False)
    assert code == 0 and lines[0] == f"DRY RUN home={home}"
