"""Extra tests: no PyYAML at all, a stat/open race, a tab after spaces."""
import json
import os
import subprocess
import sys
from pathlib import Path

import hindsight_house_guard_watch as gw

TOOLS = Path(gw.__file__).resolve().parent
SCRIPT = str(TOOLS / "hindsight_house_guard_watch.py")


def _home(tmp_path: Path, cfg: str, flag: dict | None) -> str:
    home = tmp_path / "h"
    home.mkdir()
    (home / "config.yaml").write_text(cfg, encoding="utf-8")
    if flag is not None:
        (home / "hindsight-house").mkdir()
        (home / "hindsight-house" / "guard_state.json").write_text(json.dumps(flag), encoding="utf-8")
    return str(home)


def test_yaml_not_importable_uses_the_line_scan(tmp_path):
    """A child process where import yaml raises ImportError (sys.modules entry None)."""
    home = _home(tmp_path, "memory:\n  provider: hindsight-house\n", {"status": "DRIFT", "failed": ["_recall"]})
    probe = (
        "import runpy, sys\n"
        "sys.modules['yaml'] = None\n"
        f"ns = runpy.run_path({SCRIPT!r}, run_name='probe')\n"
        "assert ns['_yaml'] is None\n"
        f"sys.exit(ns['main']([{home!r}]))\n"
    )
    p = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 0, p.stderr
    rec = json.loads(p.stdout)
    assert rec["event"] == "hindsight_house_not_ok" and rec["status"] == "DRIFT"


def test_yaml_not_importable_good_home_is_silent(tmp_path):
    home = _home(tmp_path, "memory:\n  provider: hindsight-house\n", {"status": "OK"})
    probe = (
        "import runpy, sys\n"
        "sys.modules['yaml'] = None\n"
        f"ns = runpy.run_path({SCRIPT!r}, run_name='probe')\n"
        f"sys.exit(ns['main']([{home!r}]))\n"
    )
    p = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=30, check=False)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


def test_flag_vanishes_between_stat_and_open(tmp_path, monkeypatch):
    home = _home(tmp_path, "memory:\n  provider: hindsight-house\n", None)
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    real_stat = os.stat(real)
    monkeypatch.setattr(gw.os, "stat", lambda path: real_stat)
    assert gw.read_flag(home)[0] == "missing"


def test_tab_after_spaces_is_unknown():
    assert gw.provider_from_lines("memory:\n  \tprovider: hindsight-house\n") is None


def test_script_as_main_prints_and_exits_zero(tmp_path):
    home = _home(tmp_path, "memory:\n  provider: hindsight-house\n", None)
    p = subprocess.run([sys.executable, "-I", SCRIPT, home], capture_output=True, text=True, timeout=30, check=False)
    assert p.returncode == 0 and json.loads(p.stdout)["event"] == "hindsight_house_flag_missing"
