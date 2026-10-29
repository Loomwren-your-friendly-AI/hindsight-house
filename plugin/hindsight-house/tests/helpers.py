"""Shared helpers for the plugin tests: stock copies, the scenario runner, fake stock modules."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import types
from pathlib import Path
from typing import Any

HOUSE = Path(__file__).resolve().parents[1]
BUILD = HOUSE.parents[1]  # the package root: it holds fixtures/ and tools/
STOCK_BASE = BUILD / "fixtures" / "stock-base"
VARIANTS = BUILD / "fixtures" / "stock-variants"
DRIVER = Path(__file__).with_name("hh_driver.py")
# Two absolute paths come from the environment. There is no default: a missing variable stops the run with a plain message.
#   HINDSIGHT_HOUSE_TEST_HERMES_AGENT_DIR  the folder of a Hermes checkout that holds hermes_bootstrap.py
#   HINDSIGHT_HOUSE_TEST_HERMES_HOME       a Hermes home that hermes_site() uses once, read only, to find hindsight_client
AGENT_ENV = "HINDSIGHT_HOUSE_TEST_HERMES_AGENT_DIR"
HOME_ENV = "HINDSIGHT_HOUSE_TEST_HERMES_HOME"
BOOT = "import sys; sys.path.insert(0,'%s'); import hermes_bootstrap; import runpy; runpy.run_path('%s', run_name='__main__')"
SKIP = shutil.ignore_patterns("tests", "docs", "__pycache__", "*.lock", ".git")
_STATE: dict[str, Any] = {"root": None, "cache": {}}
SITE_PROBE = ("import sys, os; sys.path.insert(0,'%s'); import hermes_bootstrap; import hindsight_client; "
              "print('HH_SITE ' + os.path.dirname(os.path.dirname(os.path.abspath(hindsight_client.__file__))))")


def required_env(name: str) -> str:
    """The value of an environment variable that the tests need; a plain message when it is missing or empty."""
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set: see the comment at the top of tests/helpers.py")
    return value


def hermes_site() -> str:
    """The site directory that holds hindsight_client, found at run time: the Hermes interpreter form with
    the HERMES_HOME named by HINDSIGHT_HOUSE_TEST_HERMES_HOME and HERMES_DISABLE_LAZY_INSTALLS=1, so the bootstrap only activates the managed environment
    and can never start a source-update sync (venv_sync.prepare_launch returns early on that variable). The tests
    then depend neither on the caller's PYTHONPATH or HERMES_HOME nor on a versioned path."""
    if "site" not in _STATE:
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON") and k != "HERMES_HOME"}
        env.update(HERMES_HOME=required_env(HOME_ENV), HERMES_DISABLE_LAZY_INSTALLS="1")
        proc = subprocess.run(["python3", "-I", "-c", SITE_PROBE % required_env(AGENT_ENV)], env=env, capture_output=True, text=True,
                              check=False, timeout=120, cwd=str(scratch_root()))
        found = [ln[len("HH_SITE "):] for ln in proc.stdout.splitlines() if ln.startswith("HH_SITE ")]
        assert proc.returncode == 0 and found and Path(found[-1]).is_dir(), "no hindsight_client: " + proc.stderr[-2000:]
        _STATE["site"] = found[-1]
    site: str = _STATE["site"]
    return site


def scratch_root() -> Path:
    if _STATE["root"] is None:
        _STATE["root"] = Path(tempfile.mkdtemp(prefix="hh_", dir=os.environ.get("TMPDIR")))
    root: Path = _STATE["root"]
    return root


def stock_source() -> str:
    return (STOCK_BASE / "__init__.py").read_text(encoding="utf-8")


def edited(old: str, new: str) -> str:
    """The stock source with one exact text replaced (the old text must occur once)."""
    source = stock_source()
    assert source.count(old) == 1, old
    return source.replace(old, new)


def stock_folder(name: str, init_text: str | None = None, base: Path | None = None) -> Path:
    """A copy of the stock plugin folder under the scratch root, with __init__.py replaced when given."""
    target = scratch_root() / name
    if not target.exists():
        shutil.copytree(base or STOCK_BASE, target, ignore=SKIP)
        if init_text is not None:
            (target / "__init__.py").write_text(init_text, encoding="utf-8")
    return target


def fake_stock(tmp_path: Path, source: str | None = None) -> Any:
    """A module-like object whose __file__ holds *source* (the guard reads text, it never runs it)."""
    path = tmp_path / "stock_init.py"
    path.write_text(stock_source() if source is None else source, encoding="utf-8")
    return types.SimpleNamespace(__file__=str(path))


def run_scenario(scenario: str, stock: Path | None) -> dict[str, Any]:
    """Run one driver scenario with the real loader, in the exact interpreter form; cached per scenario and stock."""
    key = f"{scenario}:{stock}"
    if key not in _STATE["cache"]:
        home = scratch_root() / "home"
        home.mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env.update(HERMES_HOME=str(home), HERMES_DISABLE_LAZY_INSTALLS="1", HH_SCENARIO=scenario,
                   HH_STOCK=str(stock or ""), HH_HOUSE=str(HOUSE), HH_SITE=hermes_site(),
                   HH_SCRATCH_ROOT=str(scratch_root()))
        cov = os.environ.get("HH_COV_DIR")
        if cov:
            env["HH_COV_FILE"] = str(Path(cov) / f".coverage.{len(_STATE['cache'])}.{os.getpid()}")
        code = BOOT % (required_env(AGENT_ENV), DRIVER)
        proc = subprocess.run(["python3", "-I", "-c", code], env=env, capture_output=True, text=True, check=False, timeout=240, cwd=str(scratch_root()))
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("HH_RESULT ")]
        assert proc.returncode == 0 and lines, proc.stderr[-3000:] + proc.stdout[-1000:]
        _STATE["cache"][key] = json.loads(lines[0][len("HH_RESULT "):])
    result: dict[str, Any] = _STATE["cache"][key]
    return result
