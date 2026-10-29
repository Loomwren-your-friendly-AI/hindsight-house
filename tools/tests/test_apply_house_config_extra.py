"""Extra tests: a FIFO in place of the config, and indent detection on odd layouts."""
import json
import os
from pathlib import Path

import apply_house_config as ahc


def test_fifo_in_place_of_config_is_refused_not_read(tmp_path, capsys):
    home = tmp_path / "h"
    (home / "hindsight").mkdir(parents=True)
    os.mkfifo(home / "hindsight" / "config.json")
    rc = ahc.main(["--home", str(home), "--apply"])
    out = capsys.readouterr().out
    assert rc == 2 and "not a regular file" in out


def test_directory_in_place_of_config_is_refused(tmp_path, capsys):
    home = tmp_path / "h"
    (home / "hindsight" / "config.json").mkdir(parents=True)
    rc = ahc.main(["--home", str(home)])
    assert rc == 2 and "not a regular file" in capsys.readouterr().out


def test_indent_detection_skips_lines_that_are_not_keys():
    original = '{\n\n  "a": 1}'
    assert ahc.dump_like({"a": 1}, original) == '{\n  "a": 1\n}'
    assert ahc.dump_like({"a": 1}, "{\"a\": 1}") == '{"a": 1}'
    assert ahc.dump_like({"a": [1]}, '{\n    "a": [\n        1\n    ]\n}\n') == '{\n    "a": [\n        1\n    ]\n}\n'


def test_plan_does_not_touch_other_keys_in_a_nested_value():
    cfg = {"nested": {"recall_min_score": 0.5, "recall_cron": True}, "recall_min_score": 0.3}
    new, changes, _ = ahc.plan(cfg, drop_legacy=True)
    assert new["nested"] == {"recall_min_score": 0.5, "recall_cron": True}
    assert "recall_min_score" not in new and new["recall_min_scores"] == {"final": 0.3}
    assert [c[0] for c in changes] == ["recall_min_scores", "recall_cron", "mirror_builtin_memory", "recall_query_cuts", "recall_min_score"]


def test_integer_floor_is_copied_as_given():
    new, _, _ = ahc.plan({"recall_min_score": 1}, drop_legacy=False)
    assert new["recall_min_scores"] == {"final": 1}
    assert json.dumps(new["recall_min_scores"]) == '{"final": 1}'
    assert Path(ahc.__file__).name == "apply_house_config.py"
