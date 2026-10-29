"""Tests: apply_house_config.py on synthetic copies (never on a live file)."""
import copy
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import apply_house_config as ahc

TOOLS = Path(ahc.__file__).resolve().parent
PIN = Path(__file__).resolve().parents[2] / "plugin" / "hindsight-house"  # the plugin folder, read only
CANARY = "CANARY-" + "".join(chr(c) for c in range(97, 107)) + "-zz"

PROFILES = {  # name: (floor, cap or None), example values
    "home-a": (0.92, 3),
    "home-b": (0.92, 3),
    "home-c": (0.01, 5),
    "home-d": (0.01, None),
    "home-e": (0.01, None),
}


def synthetic(floor=0.92, cap=3, extra=None) -> dict:
    cfg = {
        "api_url": "http://example.invalid/" + CANARY,
        "bank_id": "bank-" + CANARY,
        "auto_retain": False,
        "budget": "mid",
        "memory_mode": "hybrid",
        "mode": "local_external",
        "recall_exclude_tags": "relevance:noise,status:superseded",
        "recall_max_tokens": 800,
        "recall_prompt_preamble": "preamble " + CANARY,
        "recall_short_query_chars": 60,
        "recall_short_query_context_chars": 400,
        "recall_sync": True,
        "recall_types": ["world", "experience"],
        "retain_tags": ["x"],
    }
    cfg[chr(97) + "pi_" + "key"] = CANARY
    if floor is not None:
        cfg["recall_min_score"] = floor
    if cap is not None:
        cfg["recall_max_results"] = cap
    cfg.update(extra or {})
    return cfg


def make_home(tmp_path: Path, cfg, name="home", mode=0o600, indent=2, newline=False) -> Path:
    home = tmp_path / name
    (home / "hindsight").mkdir(parents=True)
    path = home / "hindsight" / "config.json"
    text = cfg if isinstance(cfg, str) else json.dumps(cfg, indent=indent) + ("\n" if newline else "")
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return home


def cfg_of(home: Path) -> dict:
    return json.loads((home / "hindsight" / "config.json").read_text(encoding="utf-8"))


def cli(capsys, *args):
    rc = ahc.main(list(args))
    out = capsys.readouterr().out
    return rc, out


def baks(home: Path):
    return sorted(p.name for p in (home / "hindsight").iterdir() if ".bak-" in p.name)


def no_canary(text: str) -> None:
    assert CANARY not in text
    assert "example.invalid" not in text


ALLOWED = re.compile(
    r"^(DRY RUN home=|APPLY home=|REFUSED: |ERROR: "
    r"|  (recall_min_scores|recall_min_score|recall_cron|mirror_builtin_memory|recall_query_cuts): "
    r"|  note: |  untouched, (present|absent): |  \d+ key\(s\) (would change|changed)$"
    r"|  no change: every key is already in place$|  backup: )"
)


def only_allowed(out: str) -> None:
    for line in out.splitlines():
        assert ALLOWED.match(line), line


def test_dry_run_prints_diff_and_writes_nothing(tmp_path, capsys):
    home = make_home(tmp_path, synthetic())
    path = home / "hindsight" / "config.json"
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    rc, out = cli(capsys, "--home", str(home))
    assert rc == 0
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime
    assert baks(home) == [] and sorted(p.name for p in (home / "hindsight").iterdir()) == ["config.json"]
    assert out.startswith("DRY RUN")
    assert 'recall_min_scores: <absent> -> {"final": 0.92}' in out
    assert "recall_cron: <absent> -> false" in out and "mirror_builtin_memory: <absent> -> false" in out
    assert "recall_query_cuts: <absent> -> " in out and "4 key(s) would change" in out
    no_canary(out)
    only_allowed(out)


def test_apply_all_five_profiles(tmp_path, capsys):
    for name, (floor, cap) in PROFILES.items():
        cfg = synthetic(floor, cap)
        home = make_home(tmp_path, cfg, name=name)
        rc, out = cli(capsys, "--home", str(home), "--apply")
        assert rc == 0, out
        after = cfg_of(home)
        assert after["recall_min_scores"] == {"final": floor}
        assert after["recall_min_score"] == floor  # legacy kept without --drop-legacy
        assert after["recall_cron"] is False and after["mirror_builtin_memory"] is False
        assert after["recall_query_cuts"] == ahc.HOUSE_QUERY_CUTS
        if cap is None:
            assert "recall_max_results" not in after
        else:
            assert after["recall_max_results"] == cap
        for key, value in cfg.items():
            assert after[key] == value, key
        assert set(after) - set(cfg) == {"recall_min_scores", "recall_cron", "mirror_builtin_memory", "recall_query_cuts"}
        no_canary(out)
        only_allowed(out)


def test_mode_backup_and_leftovers(tmp_path, capsys):
    for i, mode in enumerate([0o600, 0o644, 0o640]):
        home = make_home(tmp_path, synthetic(), name=f"m{i}", mode=mode)
        path = home / "hindsight" / "config.json"
        original = path.read_bytes()
        rc, out = cli(capsys, "--home", str(home), "--apply")
        assert rc == 0
        assert path.stat().st_mode & 0o7777 == mode
        names = baks(home)
        assert len(names) == 1 and re.fullmatch(r"config\.json\.bak-\d{8}-\d{6}", names[0])
        backup = home / "hindsight" / names[0]
        assert backup.read_bytes() == original and backup.stat().st_mode & 0o7777 == mode
        assert [p.name for p in (home / "hindsight").iterdir() if p.name.endswith(".tmp")] == []
        assert f"backup: {backup}" in out


def test_second_run_changes_nothing(tmp_path, capsys):
    home = make_home(tmp_path, synthetic())
    path = home / "hindsight" / "config.json"
    cli(capsys, "--home", str(home), "--apply")
    after, mtime, count = path.read_bytes(), path.stat().st_mtime_ns, len(baks(home))
    rc, out = cli(capsys, "--home", str(home), "--apply")
    assert rc == 0 and "no change: every key is already in place" in out
    assert path.read_bytes() == after and path.stat().st_mtime_ns == mtime and len(baks(home)) == count
    rc, out = cli(capsys, "--home", str(home))
    assert rc == 0 and "no change" in out


def test_drop_legacy_after_new_key(tmp_path, capsys):
    home = make_home(tmp_path, synthetic())
    cli(capsys, "--home", str(home), "--apply")
    rc, out = cli(capsys, "--home", str(home), "--drop-legacy")  # dry run shows it
    assert rc == 0 and "recall_min_score: 0.92 -> <absent>" in out and "1 key(s) would change" in out
    assert "recall_min_score" in cfg_of(home)
    rc, out = cli(capsys, "--home", str(home), "--apply", "--drop-legacy")
    assert rc == 0 and "1 key(s) changed" in out
    after = cfg_of(home)
    assert "recall_min_score" not in after and after["recall_min_scores"] == {"final": 0.92}
    assert after["recall_max_results"] == 3
    rc, out = cli(capsys, "--home", str(home), "--apply", "--drop-legacy")
    assert rc == 0 and "no change" in out and "already absent" in out
    only_allowed(out)


def test_drop_legacy_in_one_run(tmp_path, capsys):
    home = make_home(tmp_path, synthetic(0.01, None))
    rc, out = cli(capsys, "--home", str(home), "--apply", "--drop-legacy")
    after = cfg_of(home)
    assert rc == 0 and "recall_min_score" not in after and after["recall_min_scores"] == {"final": 0.01}
    assert "recall_max_results" not in after


def test_second_backup_in_the_same_second_gets_a_suffix(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ahc, "now", lambda: 1_700_000_000.0)
    home = make_home(tmp_path, synthetic())
    cli(capsys, "--home", str(home), "--apply")
    cli(capsys, "--home", str(home), "--apply", "--drop-legacy")
    names = baks(home)
    assert len(names) == 2 and names[1].endswith("-2")


def test_formatting_habits_are_kept(tmp_path, capsys):
    compact = make_home(tmp_path, json.dumps(synthetic(), separators=(", ", ": ")), name="compact")
    cli(capsys, "--home", str(compact), "--apply")
    text = (compact / "hindsight" / "config.json").read_text(encoding="utf-8")
    assert "\n" not in text and not text.endswith("\n")
    cfg = synthetic(extra={"recall_note": "caf\u00e9"})
    text = json.dumps(cfg, indent=4, ensure_ascii=False) + "\n"
    home = make_home(tmp_path, text, name="utf")
    cli(capsys, "--home", str(home), "--apply")
    out_text = (home / "hindsight" / "config.json").read_text(encoding="utf-8")
    assert out_text.endswith("\n") and '\n    "api_url"' in out_text and "caf\u00e9" in out_text
    ascii_home = make_home(tmp_path, json.dumps(synthetic(extra={"recall_note": "caf\u00e9"}), indent=2), name="asc")
    cli(capsys, "--home", str(ascii_home), "--apply")
    assert (ascii_home / "hindsight" / "config.json").read_text(encoding="utf-8").isascii()


def test_existing_valid_floors_are_kept(tmp_path, capsys):
    for i, floors in enumerate([{"final": 0.5}, {"reranker": 0.3, "final": 0.2}, '{"final": 0.4}', {"final": -1}]):
        home = make_home(tmp_path, synthetic(extra={"recall_min_scores": floors}), name=f"f{i}")
        rc, out = cli(capsys, "--home", str(home), "--apply")
        assert rc == 0 and "kept the existing value" in out
        assert cfg_of(home)["recall_min_scores"] == floors
        assert "recall_min_scores: <absent>" not in out


def test_no_floor_is_invented(tmp_path, capsys):
    home = make_home(tmp_path, synthetic(floor=None, cap=None))
    rc, out = cli(capsys, "--home", str(home), "--apply", "--drop-legacy")
    after = cfg_of(home)
    assert rc == 0 and "recall_min_scores" not in after and "no recall_min_score to copy" in out
    assert "3 key(s) changed" in out


def test_fixed_house_keys_overwrite_a_different_value(tmp_path, capsys):
    extra = {"recall_cron": True, "mirror_builtin_memory": 0, "recall_query_cuts": [{"applies_if": "x", "cut_at": "y"}]}
    home = make_home(tmp_path, synthetic(extra=extra))
    rc, out = cli(capsys, "--home", str(home), "--apply")
    after = cfg_of(home)
    assert rc == 0 and after["recall_cron"] is False and after["mirror_builtin_memory"] is False
    assert after["recall_query_cuts"] == ahc.HOUSE_QUERY_CUTS
    assert "recall_cron: true -> false" in out and "mirror_builtin_memory: 0 -> false" in out


def test_values_already_in_place_are_not_rewritten(tmp_path, capsys):
    extra = {"recall_min_scores": {"final": 0.92}, "recall_cron": False, "mirror_builtin_memory": False,
             "recall_query_cuts": copy.deepcopy(ahc.HOUSE_QUERY_CUTS)}
    home = make_home(tmp_path, synthetic(extra=extra))
    rc, out = cli(capsys, "--home", str(home), "--apply")
    assert rc == 0 and "no change" in out and baks(home) == []


def refused(capsys, home, *flags):
    rc, out = cli(capsys, "--home", str(home), *flags)
    assert rc == 2 and out.startswith("REFUSED: "), out
    no_canary(out)
    only_allowed(out)
    return out


def test_refuses_invalid_json_without_echoing_it(tmp_path, capsys):
    text = '{"api_url": "' + CANARY + '", "broken": '
    home = make_home(tmp_path, text)
    out = refused(capsys, home, "--apply")
    assert "not valid JSON" in out
    assert (home / "hindsight" / "config.json").read_text(encoding="utf-8") == text and baks(home) == []


def test_refuses_non_object_json(tmp_path, capsys):
    for i, text in enumerate(["[]", '"x"', "7", "null"]):
        refused(capsys, make_home(tmp_path, text, name=f"j{i}"), "--apply")


def test_refuses_without_config_or_folder(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "no hindsight/config.json" in refused(capsys, empty, "--apply")
    (tmp_path / "nocfg" / "hindsight").mkdir(parents=True)
    assert "no hindsight/config.json" in refused(capsys, tmp_path / "nocfg")
    assert "not a folder" in refused(capsys, tmp_path / "nothing-here")
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    assert "not a folder" in refused(capsys, afile)


def test_refuses_symlinked_and_non_regular_config(tmp_path, capsys):
    home = make_home(tmp_path, synthetic(), name="real")
    link_home = tmp_path / "linked"
    (link_home / "hindsight").mkdir(parents=True)
    (link_home / "hindsight" / "config.json").symlink_to(home / "hindsight" / "config.json")
    assert "symlink" in refused(capsys, link_home, "--apply")
    dir_home = tmp_path / "dirhome"
    (dir_home / "hindsight" / "config.json").mkdir(parents=True)
    refused(capsys, dir_home, "--apply")


def test_refuses_non_utf8(tmp_path, capsys):
    home = make_home(tmp_path, "{}")
    (home / "hindsight" / "config.json").write_bytes(b'{"a": "\xff"}')
    assert "not readable" in refused(capsys, home, "--apply")


def test_refuses_unreadable_file(tmp_path, capsys):
    if os.geteuid() == 0:
        pytest.skip("root reads any file")
    home = make_home(tmp_path, synthetic())
    path = home / "hindsight" / "config.json"
    path.chmod(0)
    try:
        assert "not readable" in refused(capsys, home, "--apply")
    finally:
        path.chmod(0o600)


def test_refuses_a_legacy_value_it_cannot_copy(tmp_path, capsys):
    for i, bad in enumerate([True, "0.92", None, [0.9], {"a": 1}, float("nan"), float("inf")]):
        text = json.dumps(synthetic(floor=None, extra={"recall_min_score": bad}), indent=2)  # NaN and Infinity are written as such
        home = make_home(tmp_path, text, name=f"l{i}")
        assert "not a finite number" in refused(capsys, home, "--apply")
        assert baks(home) == []


def test_refuses_an_invalid_existing_floors_value(tmp_path, capsys):
    for i, bad in enumerate([{}, "", "x", "[1]", {"final": "0.9"}, {"final": True}, {"final": None}, 5, [0.1]]):
        home = make_home(tmp_path, synthetic(extra={"recall_min_scores": bad}), name=f"b{i}")
        if bad == "":
            # an empty string is "no floor" to stock; it is still present, so it is refused, not overwritten
            pass
        assert "fix it by hand" in refused(capsys, home, "--apply")


def test_missing_home_argument_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as info:
        ahc.main([])
    assert info.value.code == 2


def test_write_failure_leaves_the_original(tmp_path, capsys, monkeypatch):
    home = make_home(tmp_path, synthetic())
    path = home / "hindsight" / "config.json"
    before = path.read_bytes()

    def boom(src, dst):
        raise OSError("disk")

    monkeypatch.setattr(ahc.os, "replace", boom)
    rc, out = cli(capsys, "--home", str(home), "--apply")
    assert rc == 1 and "write failed (OSError)" in out
    assert path.read_bytes() == before
    assert [p.name for p in (home / "hindsight").iterdir() if p.name.endswith(".tmp")] == []
    assert len(baks(home)) == 1
    no_canary(out)


def test_read_back_mismatch_is_reported(tmp_path, capsys, monkeypatch):
    home = make_home(tmp_path, synthetic())
    monkeypatch.setattr(ahc, "dump_like", lambda data, original: json.dumps({"x": 1}))
    rc, out = cli(capsys, "--home", str(home), "--apply")
    assert rc == 1 and "differs from the plan" in out and "backup is" in out
    no_canary(out)


def test_output_never_holds_a_non_whitelisted_value(tmp_path, capsys):
    for flags in [(), ("--apply",), ("--apply", "--drop-legacy"), ("--drop-legacy",)]:
        home = make_home(tmp_path, synthetic(), name="o" + "".join(f.strip("-") for f in flags))
        rc, out = cli(capsys, "--home", str(home), *flags)
        assert rc == 0
        no_canary(out)
        only_allowed(out)
        for secret_name in ("api_url", "bank_id", chr(97) + "pi_" + "key", "preamble"):
            assert secret_name not in out.replace("recall_prompt_preamble", "")


def test_render_refuses_a_key_outside_the_whitelist():
    with pytest.raises(ahc.Refusal):
        ahc.render("h", [(chr(97) + "pi_" + "key", ahc.ABSENT, "v")], [], {}, dry=True)


def test_shown_truncates_and_escapes():
    text = ahc.shown("x" * 500 + "\n\u2028")
    assert len(text) <= ahc.MAX_SHOWN and "\n" not in text
    assert ahc.shown(ahc.ABSENT) == "<absent>"
    assert ahc.shown("\u2028") == '"\\u2028"'


def test_script_runs_as_a_program(tmp_path):
    home = make_home(tmp_path, synthetic())
    p = subprocess.run([sys.executable, "-I", str(TOOLS / "apply_house_config.py"), "--home", str(home)],
                       capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 0 and p.stdout.startswith("DRY RUN") and p.stderr == ""
    p = subprocess.run([sys.executable, "-I", str(TOOLS / "apply_house_config.py")],
                       capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 2


def test_source_is_stdlib_only_and_has_no_hermes_import():
    import ast
    tree = ast.parse((TOOLS / "apply_house_config.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names <= {"__future__", "argparse", "copy", "json", "math", "os", "shutil", "stat", "sys", "tempfile", "time", "pathlib", "typing"}


def _load_pin(name):
    spec = importlib.util.spec_from_file_location(f"pin_{name}", PIN / f"{name}.py")
    assert spec is not None and spec.loader is not None
    return spec


def test_house_value_is_accepted_by_the_house_parser(tmp_path, capsys):
    """Reads the house modules of the plugin folder (read only): the rule parses and cuts a synthetic notice."""
    if not (PIN / "house_settings.py").is_file():
        pytest.skip("plugin folder not present")
    pkg_spec = importlib.util.spec_from_file_location("pin_pkg", PIN / "__init__.py", submodule_search_locations=[str(PIN)])
    assert pkg_spec is not None and pkg_spec.loader is not None
    # house_settings and notice_cut are pure; load them as submodules of a bare package shell.
    import types
    pkg = types.ModuleType("pin_pkg")
    pkg.__path__ = [str(PIN)]
    sys.modules["pin_pkg"] = pkg
    try:
        hs_spec = importlib.util.spec_from_file_location("pin_pkg.house_settings", PIN / "house_settings.py")
        nc_spec = importlib.util.spec_from_file_location("pin_pkg.notice_cut", PIN / "notice_cut.py")
        assert hs_spec is not None and hs_spec.loader is not None and nc_spec is not None and nc_spec.loader is not None
        hs = importlib.util.module_from_spec(hs_spec)
        sys.modules["pin_pkg.house_settings"] = hs
        hs_spec.loader.exec_module(hs)
        nc = importlib.util.module_from_spec(nc_spec)
        sys.modules["pin_pkg.notice_cut"] = nc
        nc_spec.loader.exec_module(nc)
        home = make_home(tmp_path, synthetic())
        cli(capsys, "--home", str(home), "--apply")
        parsed = hs.parse_house_settings(cfg_of(home))
        assert len(parsed.query_cuts) == 1 and parsed.recall_cron is False and parsed.mirror_builtin_memory is False
        assert parsed.max_results == 3 and parsed.exclude_tags == ("relevance:noise", "status:superseded")
        notice = ("[IMPORTANT: Background process proc_0123abcd finished (exit code 0).\n"
                  "Command: echo synthetic\nOutput:\n" + "synthetic output line\n" * 30)
        cut = nc.cut_query(notice, parsed.query_cuts)
        assert cut == "[IMPORTANT: Background process proc_0123abcd finished (exit code 0).\nCommand: echo synthetic"
        assert nc.cut_query("an ordinary question", parsed.query_cuts) == "an ordinary question"
    finally:
        for key in ("pin_pkg", "pin_pkg.house_settings", "pin_pkg.notice_cut"):
            sys.modules.pop(key, None)


finite_floor = st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False)
json_leaf = st.one_of(st.none(), st.booleans(), st.integers(-1000, 1000), st.text(max_size=12))
unrelated = st.dictionaries(st.text(alphabet="abcdefgh_", min_size=1, max_size=8).map(lambda s: "x_" + s), json_leaf, max_size=6)
cfg_strategy = st.builds(
    lambda extra, floor, cap, tags: {
        **extra,
        **({"recall_min_score": floor} if floor is not None else {}),
        **({"recall_max_results": cap} if cap is not None else {}),
        **({"recall_exclude_tags": tags} if tags is not None else {}),
    },
    unrelated, st.one_of(st.none(), finite_floor), st.one_of(st.none(), st.integers(0, 20)), st.one_of(st.none(), st.text(max_size=20)),
)


def _merge_properties(cfg: dict) -> None:
    snapshot = copy.deepcopy(cfg)
    new, changes, _ = ahc.plan(cfg, drop_legacy=False)
    assert cfg == snapshot  # the input is never mutated
    again, more, _ = ahc.plan(new, drop_legacy=False)
    assert more == [] and again == new  # idempotent
    for key, value in cfg.items():  # every existing key survives unchanged
        assert new[key] == value
    assert ("recall_max_results" in new) == ("recall_max_results" in cfg)
    if "recall_min_score" in cfg and cfg["recall_min_score"] != 0:  # legacy 0 means no floor
        assert new["recall_min_scores"] == {"final": cfg["recall_min_score"]}
    else:
        assert "recall_min_scores" not in new
    assert new["recall_cron"] is False and new["mirror_builtin_memory"] is False
    assert {c[0] for c in changes} <= set(ahc.WHITELIST)
    dropped, dchanges, _ = ahc.plan(new, drop_legacy=True)
    assert "recall_min_score" not in dropped
    assert ("recall_min_scores" in dropped) == ("recall_min_scores" in new)
    final, fchanges, _ = ahc.plan(dropped, drop_legacy=True)
    assert fchanges == [] and final == dropped
    one_shot, _, _ = ahc.plan(cfg, drop_legacy=True)
    assert one_shot == dropped


test_merge_properties = settings(max_examples=200, database=None, deadline=None)(given(cfg_strategy)(_merge_properties))


def _floor_copy_is_exact(floor: float) -> None:
    new, _, _ = ahc.plan({"recall_min_score": floor}, drop_legacy=False)
    if floor == 0:  # legacy 0 means no floor in 1.2.1, so none is written
        assert "recall_min_scores" not in new
        return
    assert new["recall_min_scores"]["final"] == floor
    assert math.isfinite(new["recall_min_scores"]["final"])
    assert json.loads(json.dumps(new))["recall_min_scores"] == {"final": floor}


test_floor_copy_is_exact = settings(max_examples=100, database=None, deadline=None)(given(finite_floor)(_floor_copy_is_exact))
