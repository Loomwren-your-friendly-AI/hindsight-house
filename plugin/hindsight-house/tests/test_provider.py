"""Provider tests: the REAL loader in a scratch HERMES_HOME (python3 -I), plus static checks and guard_check."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys

import yaml
from helpers import BUILD, HOUSE, STOCK_BASE, VARIANTS, edited, hermes_site, run_scenario, stock_folder

NOISE = ["relevance:noise", "status:superseded"]
NOTICE_KEPT = "[IMPORTANT: Background process proc_a1b2c3d4e5f6 exited (exit code 0).\nCommand: echo synthetic"


def ctx():
    return run_scenario("context", STOCK_BASE)


def test_t1_tool_path_has_preamble_exclusion_and_all_results():
    t1 = ctx()["t1"]
    assert t1["preamble"] is True and t1["lines"] == 5 and t1["has_tags"] is False and t1["thread"] == "hindsight-loop"
    assert t1["tag_groups"][0]["not"]["tags"] == NOISE and len(t1["tag_groups"]) == 1


def test_t2_auto_sync_is_capped_and_filtered():
    assert ctx()["t2"] == {"bullets": 3, "tag_groups": True}


def test_t3_auto_async_runs_on_the_loop_thread_with_the_filter():
    t3 = ctx()["t3"]
    assert t3["bullets"] == 3 and t3["tag_groups"] is True and t3["thread"] == "hindsight-loop"


def test_t4_concurrent_auto_and_tool_recalls_keep_their_own_origin():
    assert ctx()["t4"] == {"auto_bullets": 3, "tool_lines": 5, "all_tag_groups": True, "n": 2}


def test_t4b_eighty_interleaved_recalls_keep_origin_filter_and_a_clean_thread_local():
    s = run_scenario("stress", STOCK_BASE)
    assert s["errors"] == [] and s["auto"] == [3] and s["tool"] == [5] and s["ctx"] == ["(None, None)"]
    assert s["calls"] == 80 and s["all_tag_groups"] is True and s["loop_threads"] == ["hindsight-loop"]
    assert s["after_failure"] == {"tool_error": True, "auto": "", "ctx": "(None, None)", "plain": "FakeClient", "again": 5}

def test_t5_a_bypassing_stock_recall_fails_closed_and_is_logged():
    t5 = ctx()["t5"]
    assert "Failed to search memory" in t5["tool"]["error"] and "bypassed" in t5["tool"]["error"]
    assert t5["auto"] == "" and [m.split("origin=")[1] for m in t5["logged"]] == ["tool", "auto"]


def test_t6_the_stale_daemon_retry_still_carries_the_filter():
    assert ctx()["t6"] == {"ok": True, "calls": 1, "tag_groups": True}


def test_inclusion_tags_and_exclusion_are_both_sent_as_tag_groups():
    inc = ctx()["inclusion"]
    assert inc["has_tags"] is False and len(inc["tag_groups"]) == 2
    assert inc["tag_groups"][0]["tags"] == ["inc"] and inc["tag_groups"][1]["not"]["tags"] == NOISE


def test_notice_cut_applies_to_auto_recall_only():
    assert ctx()["cut"] == {"query": NOTICE_KEPT, "tool_query": True}


def test_short_query_context_only_for_a_short_query_with_a_session_in_sync_mode():
    short = ctx()["short"]
    assert short["on"] == "Context (assistant's previous statement): SYNTH earlier statement about the plan\nUser message: yes"
    assert short["long"] == "x" * 30 and short["nosid"] == "yes" and short["off"] == "yes"


def test_cron_sessions_are_skipped_unless_recall_cron_is_on():
    assert ctx()["cron"] == {"default": {"bullets": 0, "calls": 0}, "on": {"bullets": 3, "calls": 1}}


def test_every_house_switch_off_gives_stock_kwargs_and_output():
    sw = run_scenario("switches", STOCK_BASE)
    assert sw["empty"] == {"same": True, "n_calls": 2, "has_filter": False}
    assert sw["explicit_off"] == {"same": True, "n_calls": 2, "has_filter": False}


def test_mirror_switch_and_tool_handlers_and_schema():
    sw = run_scenario("switches", STOCK_BASE)
    assert sw["writes"] == {"stock": 1, "house_default": 0, "house_on": 1}
    assert sw["handlers"] == {"recall_is_house": True, "others_same": True, "stock_untouched": True}
    keys = ["recall_exclude_tags", "recall_max_results", "recall_cron", "mirror_builtin_memory", "recall_query_cuts",
            "recall_short_query_chars", "recall_short_query_context_chars"]
    assert sw["schema"] == {"keys": keys, "stock_n": sw["schema"]["stock_n"], "n": sw["schema"]["stock_n"] + 7}


def test_the_loader_registers_one_house_provider_with_its_siblings():
    ld = run_scenario("loader", STOCK_BASE)
    assert ld["names"] == ["hindsight", "hindsight-house"] and ld["name"] == "hindsight-house"
    assert ld["regs"] == ["HouseProvider"] and ld["isinstance_stock"] is True and ld["stock_same_object"] is True
    assert ld["house_modules"] == 1 and ld["module_prefix"] == "_hermes_user_memory.hindsight-house"
    assert ld["siblings"] == ["degraded", "drift_guard", "house_settings", "notice_cut", "prev_statement", "recall_policy"]
    assert ld["tools"] == ["hindsight_recall", "hindsight_reflect", "hindsight_retain"]


def guard(name, init_text=None):
    return run_scenario("guard", stock_folder(name, init_text))


def test_guard_ok_registers_the_house_provider_and_writes_an_ok_flag():
    g = guard("ok123")
    assert g["provider"] == "HouseProvider" and g["regs"] == ["HouseProvider"] and g["name"] == "hindsight-house"
    assert g["flag"]["status"] == "OK" and g["flag"]["revision"] == "1.2.3" and g["flag"]["failed"] == []
    assert g["errors"] == [] and g["recall_disabled"] is False and g["mirror"] == 0


def test_guard_docstring_only_edit_still_registers_the_house_provider():
    g = guard("docedit", edited('        """Guards shared by the async and synchronous recall paths."""\n', ""))
    assert g["provider"] == "HouseProvider" and g["flag"]["status"] == "OK"


def test_guard_logic_edit_registers_the_degraded_provider_and_filters_tool_recall():
    g = guard("logicedit", edited('"tools-only mode"', '"tools only mode"'))
    assert g["provider"] == "DegradedProvider" and g["regs"] == ["DegradedProvider"] and g["name"] == "hindsight-house"
    assert g["flag"]["status"] == "DRIFT" and g["flag"]["failed"] == ["_recall_disabled"]
    assert g["errors"] == ["HINDSIGHT_HOUSE_GUARD drift _recall_disabled"]
    assert g["tool"]["result"] == "1. m0\n2. m2\n3. m4" and g["auto"] == "" and g["recall_disabled"] is True and g["mirror"] == 0


def test_guard_main_drifts_to_the_degraded_provider():
    g = guard("mainvar", (VARIANTS / "stock_main_init.py").read_text(encoding="utf-8"))
    assert g["provider"] == "DegradedProvider" and g["flag"]["failed"] == ["queue_prefetch", "on_memory_write", "_apply_retain_policy"]
    assert g["tool"]["result"] == "1. m0\n2. m2\n3. m4"


def test_guard_121_drifts_to_the_degraded_provider_and_still_serves_filtered_tool_recall():
    g = run_scenario("guard", stock_folder("v121", base=VARIANTS / "stock_121"))
    assert g["provider"] == "DegradedProvider" and g["flag"]["status"] == "DRIFT" and "on_memory_write" in g["flag"]["failed"]
    assert g["tool"]["result"] == "1. m0\n2. m2\n3. m4" and g["auto"] == "" and g["recall_disabled"] is True


def test_guard_missing_stock_is_fatal_and_registers_nothing():
    g = run_scenario("guard", None)
    assert g["provider"] is None and g["regs"] == [] and g["flag"]["status"] == "FATAL" and g["flag"]["failed"] == ["stock:missing"]
    assert g["errors"] and "no provider registered" in g["errors"][-1]


def test_post_setup_leaves_the_house_provider_name_in_config_yaml():
    ps = run_scenario("post_setup", STOCK_BASE)
    assert ps["stock_sets_hindsight"] is True
    assert ps["config_dict"] == "hindsight-house" and ps["config_yaml"] == "hindsight-house"
    assert ps["stock_alone_yaml"] == "hindsight"


def test_plugin_yaml():
    meta = yaml.safe_load((HOUSE / "plugin.yaml").read_text(encoding="utf-8"))
    assert meta["name"] == "hindsight-house" and meta["kind"] == "exclusive" and meta["hooks"] == []


def test_size_caps_and_import_shape():
    assert len((HOUSE / "__init__.py").read_text().splitlines()) <= 300
    assert len((HOUSE / "drift_guard.py").read_text().splitlines()) <= 200
    tree = ast.parse((HOUSE / "__init__.py").read_text())
    classes = {n.name: [getattr(b, "id", "") for b in n.bases] for n in tree.body if isinstance(n, ast.ClassDef)}
    assert classes == {"HouseGuardError": ["RuntimeError"], "_RecallClientProxy": []}
    relative = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.level == 1]
    assert [a.name for a in relative[0].names] == ["degraded", "drift_guard", "house_settings", "notice_cut", "prev_statement", "recall_policy"]
    absolute = [n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.level == 0]
    assert "plugins" not in " ".join(m or "" for m in absolute)


def test_the_client_proxy_never_reads_the_thread_local():
    tree = ast.parse((HOUSE / "__init__.py").read_text())
    proxy = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_RecallClientProxy")
    assert "_CTX" not in {n.id for n in ast.walk(proxy) if isinstance(n, ast.Name)}
    assert not re.search(r"^\s*@\w", (HOUSE / "__init__.py").read_text(), re.M)


def load_guard_check():
    spec = importlib.util.spec_from_file_location("guard_check_mod", BUILD / "tools" / "guard_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["guard_check_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_guard_check_lines_and_exit_codes(capsys, tmp_path, monkeypatch):
    gc = load_guard_check()
    assert gc.main(["x", str(STOCK_BASE)]) == 0
    assert capsys.readouterr().out == "HINDSIGHT_HOUSE_GUARD status=OK revision=1.2.3 failed=-\n"
    main_dir = stock_folder("gc_main", (VARIANTS / "stock_main_init.py").read_text(encoding="utf-8"))
    assert gc.main(["x", str(main_dir), str(HOUSE)]) == 1
    assert capsys.readouterr().out == "HINDSIGHT_HOUSE_GUARD status=DRIFT revision=unknown failed=queue_prefetch,on_memory_write,_apply_retain_policy\n"
    assert gc.main(["x", str(tmp_path / "nothing")]) == 2
    assert capsys.readouterr().out == "HINDSIGHT_HOUSE_GUARD status=FATAL revision=none failed=stock:missing\n"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "hindsight").symlink_to(STOCK_BASE)
    assert gc.main(["x"]) == 0
    assert "status=OK" in capsys.readouterr().out


def test_guard_check_import_failure_and_command_line(tmp_path):
    gc = load_guard_check()
    try:
        gc.load_guard(tmp_path)
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "drift_guard.py" in str(exc)
    proc = subprocess.run([sys.executable, str(BUILD / "tools" / "guard_check.py"), str(STOCK_BASE)], capture_output=True, text=True, check=False,
                          env={**{k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}, "PYTHONPATH": hermes_site(),
                               "HERMES_DISABLE_LAZY_INSTALLS": "1"})
    assert proc.returncode == 0 and json.dumps(proc.stdout.strip()).startswith('"HINDSIGHT_HOUSE_GUARD status=OK')
    assert gc.EXIT == {"OK": 0, "DRIFT": 1}


def test_proxy_forwards_attributes_and_plain_operations_pass_through_unwrapped():
    ex = run_scenario("extra", STOCK_BASE)
    assert ex["proxy_attr"] == 0.0 and ex["proxy_counted"] == 1 and ex["plain_op"] == "FakeClient"


def test_helpers_fall_back_when_hermes_modules_are_missing():
    ex = run_scenario("extra", STOCK_BASE)
    assert ex["home_none"] is True and ex["redact_none"] is True and ex["real_home"] is True and ex["redact"] == "plain words"


def test_stock_tools_only_mode_still_disables_auto_recall():
    assert run_scenario("extra", STOCK_BASE)["tools_mode"] == {"block": "", "calls": 0}


def test_guard_a_provider_that_cannot_be_built_is_fatal_and_flagged():
    init = edited("    def __init__(self):\n", "    def __init__(self):\n        raise RuntimeError('synthetic build failure')\n")
    g = guard("buildfail", init)
    assert g["provider"] is None and g["regs"] == [] and g["flag"]["status"] == "FATAL" and g["flag"]["failed"] == ["build:RuntimeError"]
    assert g["errors"][-1] == "HINDSIGHT_HOUSE_GUARD fatal build:RuntimeError: no provider registered"


def test_post_setup_after_a_cancelled_stock_wizard_leaves_the_config_as_stock_does():
    cancelled = run_scenario("post_setup", STOCK_BASE)["cancelled"]
    assert cancelled == {"hindsight": ["hindsight", "hindsight"], "honcho": ["honcho", "honcho"], "absent": []}


def test_guard_check_is_fatal_for_a_broken_house_folder_and_for_an_unset_home(capsys, tmp_path, monkeypatch):
    gc = load_guard_check()
    assert gc.main(["x", str(STOCK_BASE), str(tmp_path)]) == 2
    assert capsys.readouterr().out == "HINDSIGHT_HOUSE_GUARD status=FATAL revision=none failed=tool:FileNotFoundError\n"
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "hindsight").symlink_to(STOCK_BASE)
    assert gc.main(["x"]) == 2
    assert capsys.readouterr().out == "HINDSIGHT_HOUSE_GUARD status=FATAL revision=none failed=home:unset\n"
