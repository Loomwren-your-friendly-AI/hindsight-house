"""Provider problems in a house home are reported, not silent."""
import json
from pathlib import Path

import pytest

import hindsight_house_guard_watch as gw

GOOD_FLAG = {"status": "OK", "revision": "r", "failed": [], "written_at_iso": "2026-10-28T19:00:00"}


def _mode(request, monkeypatch):
    if request.param == "lines":
        monkeypatch.setattr(gw, "_yaml", None)
    else:
        assert gw._yaml is not None
    return request.param


mode = pytest.fixture(params=["yaml", "lines"])(_mode)
DIR = object()


def home_with(tmp_path: Path, cfg, marker: str = "flag") -> str:
    home = tmp_path / "h"
    home.mkdir()
    if isinstance(cfg, bytes):
        (home / "config.yaml").write_bytes(cfg)
    elif isinstance(cfg, str):
        (home / "config.yaml").write_text(cfg, encoding="utf-8")
    elif cfg is DIR:
        (home / "config.yaml").mkdir()
    if marker == "flag":
        (home / "hindsight-house").mkdir()
        (home / "hindsight-house" / "guard_state.json").write_text(json.dumps(GOOD_FLAG), encoding="utf-8")
    elif marker == "plugin":
        (home / "plugins" / "hindsight-house").mkdir(parents=True)
    return str(home)


def _event(home: str):
    rec = gw.check_home(home)
    return None if rec is None else (rec["event"], rec.get("reason"), rec["severity"])


def test_not_utf8_config_with_flag_warns(tmp_path, mode):
    home = home_with(tmp_path, b"memory:\n  provider: \xff\xfe\n")
    assert _event(home) == ("hindsight_house_provider_unreadable", "config not UTF-8", "warning")


def test_not_utf8_config_without_house_is_quiet(tmp_path, mode):
    assert _event(home_with(tmp_path, b"\xff\xfe", marker="none")) is None


def test_missing_config_with_plugin_folder_warns(tmp_path, mode):
    home = home_with(tmp_path, None, marker="plugin")
    assert _event(home) == ("hindsight_house_provider_unreadable", "config missing", "warning")


def test_missing_config_without_house_is_quiet(tmp_path, mode):
    assert _event(home_with(tmp_path, None, marker="none")) is None


def test_config_is_directory_warns_with_error_name(tmp_path, mode):
    home = home_with(tmp_path, DIR)
    assert _event(home) == ("hindsight_house_provider_unreadable", "IsADirectoryError", "warning")


def test_too_large_config_warns(tmp_path, mode, monkeypatch):
    monkeypatch.setattr(gw, "MAX_CONFIG_BYTES", 10)
    home = home_with(tmp_path, "memory:\n  provider: hindsight-house\n")
    assert _event(home) == ("hindsight_house_provider_unreadable", "config too large", "warning")


def test_size_exactly_at_cap_is_read(tmp_path, mode, monkeypatch):
    text = "memory:\n  provider: hindsight-house\n"
    monkeypatch.setattr(gw, "MAX_CONFIG_BYTES", len(text.encode()))
    assert _event(home_with(tmp_path, text)) is None


def test_duplicate_provider_key(tmp_path, mode):
    # PyYAML keeps the last key, as Hermes does; the line scan cannot decide and says so.
    cfg = "memory:\n  provider: hindsight-house\n  provider: hindsight\n"
    got = _event(home_with(tmp_path, cfg))
    if mode == "yaml":
        assert got is None
    else:
        assert got == ("hindsight_house_provider_unreadable", "provider not determinable", "warning")


def test_provider_list_value_warns(tmp_path, mode):
    home = home_with(tmp_path, "memory:\n  provider: [hindsight-house]\n")
    assert _event(home) == ("hindsight_house_provider_unreadable", "provider not determinable", "warning")


def test_yaml_error_warns_not_parsed(tmp_path, monkeypatch):
    assert gw._yaml is not None
    home = home_with(tmp_path, "memory: [\n")
    assert _event(home) == ("hindsight_house_provider_unreadable", "config not parsed", "warning")


def test_yaml_top_level_list_and_scalar_memory_warn(tmp_path):
    for cfg in ("- a\n- b\n", "memory: text\n"):
        sub = tmp_path / str(len(cfg))
        sub.mkdir()
        home = home_with(sub, cfg)
        assert _event(home) == ("hindsight_house_provider_unreadable", "provider not determinable", "warning")


def test_yaml_null_memory_and_empty_file_are_quiet(tmp_path):
    for i, cfg in enumerate(("memory:\n", "", "memory:\n  provider:\n", "other: 1\n")):
        sub = tmp_path / str(i)
        sub.mkdir()
        assert _event(home_with(sub, cfg)) is None


def test_lines_absent_block_and_absent_key_are_quiet(tmp_path, mode):
    for i, cfg in enumerate(("", "other: 1\n", "memory:\n  other: 1\nnext: 2\n")):
        sub = tmp_path / str(i)
        sub.mkdir()
        assert _event(home_with(sub, cfg)) is None


def test_other_provider_with_house_present_is_quiet(tmp_path, mode):
    assert _event(home_with(tmp_path, "memory:\n  provider: hindsight\n")) is None


def test_padded_provider_with_house_present_warns_malformed(tmp_path, mode):
    for i, value in enumerate(("' hindsight-house '", "Hindsight-House", "\"hindsight-house \"")):
        sub = tmp_path / str(i)
        sub.mkdir()
        home = home_with(sub, "memory:\n  provider: " + value + "\n")
        assert _event(home) == ("hindsight_house_provider_malformed", None, "warning")


def test_padded_provider_without_house_is_quiet(tmp_path, mode):
    assert _event(home_with(tmp_path, "memory:\n  provider: Hindsight-House\n", marker="none")) is None


def test_exact_provider_and_ok_flag_is_quiet(tmp_path, mode):
    assert _event(home_with(tmp_path, "memory:\n  provider: hindsight-house\n")) is None


def test_dangling_flag_symlink_counts_as_house_present(tmp_path, mode):
    home = Path(home_with(tmp_path, b"\xff", marker="none"))
    (home / "hindsight-house").mkdir()
    (home / "hindsight-house" / "guard_state.json").symlink_to(tmp_path / "nowhere")
    assert gw.house_present(str(home)) is True
    got = _event(str(home))
    assert got is not None and got[0] == "hindsight_house_provider_unreadable"


def test_house_present_false_for_plugin_file_not_folder(tmp_path):
    home = tmp_path / "h"
    (home / "plugins").mkdir(parents=True)
    (home / "plugins" / "hindsight-house").write_text("x", encoding="utf-8")
    assert gw.house_present(str(home)) is False


def test_main_prints_one_json_line_for_unreadable_provider(tmp_path, capsys, mode):
    home = home_with(tmp_path, b"\xff")
    assert gw.main([home]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    rec = json.loads(out[0])
    assert rec["event"] == "hindsight_house_provider_unreadable"
    assert "wakeAgent" not in rec


def test_read_provider_wrapper_keeps_old_contract(tmp_path, mode):
    assert gw.read_provider(home_with(tmp_path, b"\xff")) is None
    assert gw.provider_from_lines("memory:\n  provider: a\n  provider: b\n") is None

def test_lines_unsure_layouts_warn(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "_yaml", None)
    cases = (
        "memory:\n\tprovider: hindsight-house\n",
        "memory:\n  \tprovider: hindsight-house\n",
        "memory:\n  provider: hindsight-house\nmemory:\n  provider: hindsight\n",
        "memory:\n  provider: hind: sight\n",
        "memory:\n  provider: [hindsight-house]\n",
    )
    for i, cfg in enumerate(cases):
        sub = tmp_path / str(i)
        sub.mkdir()
        got = _event(home_with(sub, cfg))
        assert got == ("hindsight_house_provider_unreadable", "provider not determinable", "warning"), cfg


def test_scan_lines_sure_flags():
    assert gw.scan_lines("memory:\n  provider: hindsight-house\n") == ("hindsight-house", True)
    assert gw.scan_lines("memory:\r\n  provider: hindsight-house\r\n") == ("hindsight-house", True)
    assert gw.scan_lines("other: 1\n") == (None, True)
    assert gw.scan_lines("memory:\n\tprovider: x\n") == (None, False)
    assert gw.scan_lines("memory: {provider: x}\n") == (None, False)


def test_literal_quotes_count_as_malformed(tmp_path, mode):
    home = home_with(tmp_path, "memory:\n  provider: \"'hindsight-house'\"\n")
    assert _event(home) == ("hindsight_house_provider_malformed", None, "warning")
