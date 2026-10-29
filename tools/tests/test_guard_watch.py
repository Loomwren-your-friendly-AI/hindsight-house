"""Tests: hindsight_house_guard_watch (synthetic homes in tmp_path only).

Every scenario runs twice: with PyYAML and with the strict line-scan fallback.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import hindsight_house_guard_watch as gw

TOOLS = Path(gw.__file__).resolve().parent
GOOD_CFG = "memory:\n  provider: hindsight-house\n"


def mode(request, monkeypatch):
    if request.param == "lines":
        monkeypatch.setattr(gw, "_yaml", None)
    else:
        assert gw._yaml is not None, "PyYAML must be importable for the yaml mode"
    return request.param


mode = pytest.fixture(params=["yaml", "lines"])(mode)


def make_home(tmp_path: Path, name: str, cfg: str | None = GOOD_CFG, flag=None) -> str:
    home = tmp_path / name
    home.mkdir()
    if cfg is not None:
        (home / "config.yaml").write_text(cfg, encoding="utf-8")
    if flag is not None:
        (home / "hindsight-house").mkdir()
        target = home / "hindsight-house" / "guard_state.json"
        if isinstance(flag, bytes):
            target.write_bytes(flag)
        elif isinstance(flag, str):
            target.write_text(flag, encoding="utf-8")
        else:
            target.write_text(json.dumps(flag), encoding="utf-8")
    return str(home)


def run(capsys, *homes: str):
    rc = gw.main(list(homes))
    out = capsys.readouterr().out
    return rc, [json.loads(line) for line in out.splitlines()], out


OK_FLAG = {"status": "OK", "revision": "1.2.3", "failed": [], "detail": "", "written_at": 1, "written_at_iso": "2020-01-01T00:00:00Z"}


def test_good_home_prints_nothing(mode, tmp_path, capsys):
    home = make_home(tmp_path, "good", flag=OK_FLAG)
    rc, recs, out = run(capsys, home)
    assert (rc, recs, out) == (0, [], "")


def test_old_written_at_is_not_an_error(mode, tmp_path, capsys):
    flag = dict(OK_FLAG, written_at=1, written_at_iso="1999-01-01T00:00:00Z")
    rc, recs, _ = run(capsys, make_home(tmp_path, "old", flag=flag))
    assert (rc, recs) == (0, [])


def test_missing_flag(mode, tmp_path, capsys):
    home = make_home(tmp_path, "nof")
    rc, recs, _ = run(capsys, home)
    assert rc == 0 and len(recs) == 1
    assert recs[0]["event"] == "hindsight_house_flag_missing"
    assert recs[0]["severity"] == "warning"
    assert recs[0]["home"] == home and recs[0]["profile"] == "nof"
    assert recs[0]["flag"].endswith("hindsight-house/guard_state.json")


def test_missing_flag_dir_is_missing(mode, tmp_path, capsys):
    home = make_home(tmp_path, "nodir")
    (Path(home) / "hindsight-house").write_text("a file, not a folder", encoding="utf-8")
    _, recs, _ = run(capsys, home)
    assert [r["event"] for r in recs] == ["hindsight_house_flag_missing"]


def test_drift_flag(mode, tmp_path, capsys):
    flag = dict(OK_FLAG, status="DRIFT", revision="unknown", failed=["_recall", "sig:prefetch"], detail="two symbols changed")
    rc, recs, _ = run(capsys, make_home(tmp_path, "drift", flag=flag))
    assert rc == 0 and len(recs) == 1
    rec = recs[0]
    assert rec["event"] == "hindsight_house_not_ok" and rec["status"] == "DRIFT"
    assert rec["severity"] == "warning" and rec["revision"] == "unknown"
    assert rec["failed"] == ["_recall", "sig:prefetch"] and rec["detail"] == "two symbols changed"
    assert rec["written_at_iso"] == "2020-01-01T00:00:00Z"


def test_fatal_flag_is_critical(mode, tmp_path, capsys):
    _, recs, _ = run(capsys, make_home(tmp_path, "fatal", flag=dict(OK_FLAG, status="FATAL", failed=["stock:missing"])))
    assert recs[0]["severity"] == "critical" and recs[0]["status"] == "FATAL"


def test_status_is_strict(mode, tmp_path, capsys):
    for i, status in enumerate(["ok", "Ok", "OK ", "", "WEIRD"]):
        _, recs, _ = run(capsys, make_home(tmp_path, f"s{i}", flag=dict(OK_FLAG, status=status)))
        assert len(recs) == 1 and recs[0]["event"] == "hindsight_house_not_ok", status


UNREADABLE = [
    ("empty", ""),
    ("not json", "{not json"),
    ("list", "[]"),
    ("string", '"OK"'),
    ("null", "null"),
    ("no status", '{"revision": "1.2.3"}'),
    ("int status", '{"status": 1}'),
    ("null status", '{"status": null}'),
    ("bad utf8", b'{"status": "\xff"}'),
    ("too large", '{"status": "OK", "detail": "' + "x" * 70000 + '"}'),
]


def test_unreadable_flags(mode, tmp_path, capsys):
    for i, (label, body) in enumerate(UNREADABLE):
        home = make_home(tmp_path, f"u{i}", flag=body)
        rc, recs, _ = run(capsys, home)
        assert rc == 0 and len(recs) == 1, label
        assert recs[0]["event"] == "hindsight_house_flag_unreadable", label
        assert recs[0]["reason"], label


def test_flag_is_a_directory(mode, tmp_path, capsys):
    home = make_home(tmp_path, "dirflag")
    (Path(home) / "hindsight-house" / "guard_state.json").mkdir(parents=True)
    _, recs, _ = run(capsys, home)
    assert recs[0]["event"] == "hindsight_house_flag_unreadable"
    assert recs[0]["reason"] == "not a regular file"


def test_flag_is_a_fifo_does_not_hang(mode, tmp_path, capsys):
    home = make_home(tmp_path, "fifo")
    (Path(home) / "hindsight-house").mkdir()
    os.mkfifo(Path(home) / "hindsight-house" / "guard_state.json")
    _, recs, _ = run(capsys, home)
    assert recs[0]["reason"] == "not a regular file"


def test_permission_denied_flag(mode, tmp_path, capsys):
    if os.geteuid() == 0:
        pytest.skip("root reads any file")
    home = make_home(tmp_path, "perm", flag=OK_FLAG)
    flag = Path(home) / "hindsight-house" / "guard_state.json"
    flag.chmod(0)
    try:
        _, recs, _ = run(capsys, home)
    finally:
        flag.chmod(0o600)
    assert recs[0]["event"] == "hindsight_house_flag_unreadable"
    assert recs[0]["reason"] == "PermissionError"


def test_permission_denied_folder(mode, tmp_path, capsys):
    if os.geteuid() == 0:
        pytest.skip("root reads any file")
    home = make_home(tmp_path, "permdir", flag=OK_FLAG)
    folder = Path(home) / "hindsight-house"
    folder.chmod(0)
    try:
        _, recs, _ = run(capsys, home)
    finally:
        folder.chmod(0o700)
    assert recs[0]["reason"] == "PermissionError"


NOT_HOUSE = [
    "memory:\n  provider: hindsight\n",
    "memory:\n  provider: honcho\n",
    "memory:\n  provider: Hindsight-House\n",
    "memory:\n  provider: hindsight-house-2\n",
    "memory:\n  provider: ''\n",
    "memory:\n  provider:\n",
    "memory:\n  other: hindsight-house\n",
    "memory: {}\n",
    "other:\n  provider: hindsight-house\n",
    "provider: hindsight-house\n",
    "memory:\n  nested:\n    provider: hindsight-house\n",
    "",
    "memory: [unclosed\n",
]


def test_other_providers_print_nothing(mode, tmp_path, capsys):
    for i, cfg in enumerate(NOT_HOUSE):
        home = make_home(tmp_path, f"p{i}", cfg=cfg)  # flag missing, still silent
        rc, recs, out = run(capsys, home)
        assert (rc, recs, out) == (0, [], ""), cfg


def test_missing_or_unreadable_config_is_silent(mode, tmp_path, capsys):
    home = make_home(tmp_path, "nocfg", cfg=None)
    assert run(capsys, home)[1] == []
    bad = make_home(tmp_path, "badcfg", cfg=None)
    (Path(bad) / "config.yaml").write_bytes(b"memory:\n  provider: \xff\n")
    assert run(capsys, bad)[1] == []
    gone = str(tmp_path / "does-not-exist")
    assert run(capsys, gone)[1] == []
    if os.geteuid() != 0:
        locked = make_home(tmp_path, "locked", cfg=GOOD_CFG)
        os.chmod(Path(locked) / "config.yaml", 0)
        try:
            assert run(capsys, locked)[1] == []
        finally:
            os.chmod(Path(locked) / "config.yaml", 0o600)


def test_oversized_config_is_unknown(mode, tmp_path, capsys):
    cfg = GOOD_CFG + "# " + "x" * (gw.MAX_CONFIG_BYTES + 10) + "\n"
    assert run(capsys, make_home(tmp_path, "big", cfg=cfg))[1] == []


SPELLINGS = [
    "memory:\n  provider: hindsight-house\n",
    "memory:\n  provider: 'hindsight-house'\n",
    'memory:\n  provider: "hindsight-house"\n',
    "memory:\n  provider: hindsight-house   # note\n",
    "memory:   # c\n  provider: hindsight-house\n",
    "# top\nmemory:\n  # c\n\n  provider: hindsight-house\n  other: 1\nnext: 2\n",
    "x: 1\nmemory:\n    provider: hindsight-house\n",
    "memory:\r\n  provider: hindsight-house\r\n",
    "memory:\n  provider: hindsight-house",
    "---\nmemory:\n  provider: hindsight-house\n",
]


def test_spellings_both_readers_agree(mode, tmp_path, capsys):
    for i, cfg in enumerate(SPELLINGS):
        assert gw.read_provider(make_home(tmp_path, f"sp{i}", cfg=cfg)) == "hindsight-house", cfg


def test_fallback_is_strict_where_yaml_is_not():
    # The line scan returns None (unknown) rather than guess on these layouts.
    unsure = [
        "memory: {provider: hindsight-house}\n",
        "memory:\n  provider: hindsight-house\n  provider: honcho\n",
        "memory:\n  provider: &a hindsight-house\n",
        "memory:\n  provider: !!str hindsight-house\n",
        "memory:\n  provider: hindsight-house#x\n",
        "memory:\n  provider: 'a''b'\n",
        "memory:\n  provider: a: b\n",
        "memory:\n\tprovider: hindsight-house\n",
        "memory:\nmemory:\n  provider: hindsight-house\n",
        "memory:\n  provider: [hindsight-house]\n",
        "memory:\n  provider: |\n    hindsight-house\n",
    ]
    for cfg in unsure:
        assert gw.provider_from_lines(cfg) is None, cfg


def test_yaml_reads_what_the_fallback_will_not(tmp_path, capsys):
    cfg = "memory: {provider: hindsight-house}\n"
    home = make_home(tmp_path, "flow", cfg=cfg)
    assert gw.provider_from_yaml(cfg) == "hindsight-house"
    assert gw.provider_from_lines(cfg) is None
    assert len(run(capsys, home)[1]) == 1  # yaml present: found


def test_yaml_error_is_silent(mode, tmp_path, monkeypatch, capsys):
    def boom(text):
        raise RecursionError("deep")
    monkeypatch.setattr(gw, "scan_yaml", boom)  # the parse seam is scan_*
    monkeypatch.setattr(gw, "scan_lines", boom)
    assert run(capsys, make_home(tmp_path, "boom"))[1] == []


def test_hostile_flag_text_stays_one_capped_line(mode, tmp_path, capsys):
    nasty = "a\nb\r\x00\x1b[31m\u2028\u2029\x85" + "Z" * 5000
    flag = {"status": "DRIFT" + nasty, "revision": nasty, "failed": [nasty[:12] + "Z" * 300] * 50 + [1, None],
            "detail": nasty, "written_at_iso": nasty}
    home = make_home(tmp_path, "nasty", flag=flag)
    rc = gw.main([home])
    out = capsys.readouterr().out
    assert rc == 0 and out.endswith("\n")
    assert len(out.splitlines()) == 1 and out.count("\n") == 1
    assert all(ord(ch) < 128 for ch in out)
    rec = json.loads(out)
    assert len(rec["status"]) <= 40 and len(rec["revision"]) <= 40 and len(rec["detail"]) <= 200
    assert len(rec["failed"]) == gw.MAX_FAILED_ITEMS and all(len(x) <= 60 for x in rec["failed"])
    assert len(out) < 4000


def test_odd_field_types_do_not_crash(mode, tmp_path, capsys):
    flag = {"status": "DRIFT", "revision": 5, "failed": "x", "detail": ["a"], "written_at_iso": None}
    rec = run(capsys, make_home(tmp_path, "odd", flag=flag))[1][0]
    assert rec["revision"] is None and rec["failed"] == [] and rec["detail"] is None


def test_five_homes_mixed(mode, tmp_path, capsys):
    homes = [
        make_home(tmp_path, "h1", flag=OK_FLAG),
        make_home(tmp_path, "h2"),
        make_home(tmp_path, "h3", flag=dict(OK_FLAG, status="DRIFT")),
        make_home(tmp_path, "h4", cfg="memory:\n  provider: hindsight\n"),
        make_home(tmp_path, "h5", flag="junk"),
    ]
    rc, recs, _ = run(capsys, *homes)
    assert rc == 0
    assert [(r["profile"], r["event"]) for r in recs] == [
        ("h2", "hindsight_house_flag_missing"),
        ("h3", "hindsight_house_not_ok"),
        ("h5", "hindsight_house_flag_unreadable"),
    ]


def test_homes_resolution(tmp_path):
    assert gw.resolve_homes(["a", "b"], {gw.HOMES_ENV: "x"}) == ["a", "b"]
    assert gw.resolve_homes([], {gw.HOMES_ENV: os.pathsep.join(["x", "", "y"])}) == ["x", "y"]
    assert gw.resolve_homes([], {gw.HOMES_ENV: "  "}) == []
    assert gw.resolve_homes([], {}) == []
    assert gw.label_for("/some/folder") == "folder" and gw.label_for("/some/folder/") == "folder"
    assert gw.label_for("rel/dir") == "dir"


def test_no_homes_is_an_error_not_silence(monkeypatch, capsys):
    monkeypatch.delenv(gw.HOMES_ENV, raising=False)
    assert gw.main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and gw.HOMES_ENV in captured.err


def test_env_variable_reaches_main(mode, tmp_path, monkeypatch, capsys):
    h1 = make_home(tmp_path, "e1")
    h2 = make_home(tmp_path, "e2", flag=OK_FLAG)
    monkeypatch.setenv(gw.HOMES_ENV, os.pathsep.join([h1, h2]))
    rc = gw.main([])
    recs = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert rc == 0 and [r["profile"] for r in recs] == ["e1"]


def test_internal_error_is_visible_and_exit_zero(mode, tmp_path, monkeypatch, capsys):
    def boom(home):
        raise KeyError("x")
    monkeypatch.setattr(gw, "check_home", boom)
    rc, recs, _ = run(capsys, "somewhere")
    assert rc == 0 and recs[0]["event"] == "hindsight_house_guard_watch_error" and recs[0]["reason"] == "KeyError"


def _script(*homes: str, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES")}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-I", str(TOOLS / "hindsight_house_guard_watch.py"), *homes],
        capture_output=True, text=True, env=env, timeout=30, check=False,
    )


def test_script_end_to_end_exit_zero_both_cases(tmp_path):
    good = make_home(tmp_path, "g", flag=OK_FLAG)
    bad = make_home(tmp_path, "b", flag=dict(OK_FLAG, status="DRIFT"))
    r1 = _script(good)
    assert (r1.returncode, r1.stdout, r1.stderr) == (0, "", "")
    r2 = _script(good, bad)
    assert r2.returncode == 0 and r2.stderr == ""
    assert [json.loads(x)["profile"] for x in r2.stdout.splitlines()] == ["b"]


def test_script_env_variable_and_no_hermes_import(tmp_path):
    bad = make_home(tmp_path, "b", flag=dict(OK_FLAG, status="FATAL"))
    r = _script(env_extra={gw.HOMES_ENV: bad})
    assert r.returncode == 0 and json.loads(r.stdout)["severity"] == "critical"
    probe = (
        "import runpy, sys\n"
        "sys.argv = ['gw']\n"
        f"ns = runpy.run_path({str(TOOLS / 'hindsight_house_guard_watch.py')!r}, run_name='probe')\n"
        "bad = [m for m in sys.modules if m.startswith('hermes')]\n"
        "assert not bad, bad\n"
        "print('clean')\n"
    )
    p = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 0 and p.stdout.strip() == "clean", p.stderr


def test_source_imports_stdlib_only():
    import ast
    tree = ast.parse((TOOLS / "hindsight_house_guard_watch.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names <= {"__future__", "importlib", "json", "os", "re", "stat", "sys", "typing"}
    text = (TOOLS / "hindsight_house_guard_watch.py").read_text(encoding="utf-8")
    assert "subprocess" not in text and "hermes_bootstrap" not in text.replace("hermes_bootstrap or any", "")


def _only_target_matters(name: str) -> None:
    """The one question the watch asks is: is the provider exactly hindsight-house?

    Both readers must give the same answer on near-miss spellings. A fallback that
    says yes where yaml says no (or the reverse) would hide or invent a home.
    """
    cfg = f"memory:\n  provider: {name}\n"
    try:
        by_yaml = gw.provider_from_yaml(cfg)
    except Exception:  # invalid yaml: read_provider reports unknown, which is "not the target"
        by_yaml = None
    assert (gw.provider_from_lines(cfg) == gw.PROVIDER) == (by_yaml == gw.PROVIDER), cfg


_NEAR = "hindsight-ouse" + " '" + chr(34) + "#:-_"
test_target_answer_agrees = settings(max_examples=300, database=None, deadline=None)(
    given(st.text(alphabet=_NEAR, min_size=0, max_size=24))(_only_target_matters)
)


def test_exact_target_spellings_agree():
    for name in ["hindsight-house", "'hindsight-house'", chr(34) + "hindsight-house" + chr(34),
                 "hindsight-house # c", "hindsight-house #c", " hindsight-house"]:
        _only_target_matters(name)


def _flag_text_check(payload: str) -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / "h"
        (home / "hindsight-house").mkdir(parents=True)
        (home / "config.yaml").write_text(GOOD_CFG, encoding="utf-8")
        (home / "hindsight-house" / "guard_state.json").write_text(
            json.dumps({"status": payload, "detail": payload, "failed": [payload]}), encoding="utf-8"
        )
        rec = gw.check_home(str(home))
        if payload == "OK":
            assert rec is None
        else:
            assert rec is not None
            line = json.dumps(rec, sort_keys=True)
            assert "\n" not in line and "\r" not in line and "\u2028" not in line


test_any_status_text_is_one_safe_line = settings(max_examples=60, database=None, deadline=None)(
    given(st.text(max_size=300))(_flag_text_check)
)
