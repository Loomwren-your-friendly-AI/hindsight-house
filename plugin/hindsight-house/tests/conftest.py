"""Test setup: put the house folder on sys.path so the pure modules import by name.

The plugin ships no pyproject.toml, so the path is set here, not in pytest config.
"""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
TESTS = str(Path(__file__).resolve().parent)
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)
from helpers import hermes_site  # noqa: E402

if hermes_site() not in sys.path:  # the real installed client for the in-process guard tests, found at run time
    sys.path.append(hermes_site())
