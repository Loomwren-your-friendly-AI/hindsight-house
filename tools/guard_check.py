"""Run the hindsight-house drift check against a stock plugin folder and print one line.

Usage: guard_check.py [STOCK_FOLDER [HOUSE_FOLDER]]
STOCK_FOLDER defaults to $HERMES_HOME/plugins/hindsight; HOUSE_FOLDER (holds drift_guard.py and known_stock.json)
defaults to ../plugin/hindsight-house, relative to this tools folder. No stock code runs: the check reads the source text only.
Exit code: 0 OK, 1 DRIFT, 2 FATAL. Run it with the Hermes interpreter, so hindsight_client can be inspected.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from typing import Any

EXIT = {"OK": 0, "DRIFT": 1}
FATAL = "HINDSIGHT_HOUSE_GUARD status=FATAL revision=none failed=%s"


def load_guard(house_dir: Path) -> Any:
    spec = importlib.util.spec_from_file_location("hh_drift_guard", house_dir / "drift_guard.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # NamedTuple and logging look the module up by name
    spec.loader.exec_module(module)
    return module


def run(stock_dir: Path, house_dir: Path) -> tuple[str, int]:
    guard = load_guard(house_dir)
    init = stock_dir / "__init__.py"
    stock = types.SimpleNamespace(__file__=str(init)) if init.is_file() else None
    result = guard.check(stock, house_dir / "known_stock.json")
    failed = ",".join(result.failed) or "-"
    return f"HINDSIGHT_HOUSE_GUARD status={result.status} revision={result.revision} failed={failed}", EXIT.get(result.status, 2)


def main(argv: list[str]) -> int:
    default_stock = Path(os.environ.get("HERMES_HOME", "")) / "plugins" / "hindsight"
    # the first argument is the STOCK plugin folder (default HERMES_HOME/plugins/hindsight), the second the house folder
    stock_dir = Path(argv[1]) if len(argv) > 1 else default_stock
    house_dir = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent / "plugin" / "hindsight-house"
    if len(argv) < 2 and not os.environ.get("HERMES_HOME"):  # never read ./plugins/hindsight of the working folder
        line, code = FATAL % "home:unset", 2
    else:
        try:
            line, code = run(stock_dir, house_dir)
        except Exception as exc:  # a crash must not exit 1, which reads as DRIFT
            line, code = FATAL % ("tool:" + type(exc).__name__), 2
    print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
