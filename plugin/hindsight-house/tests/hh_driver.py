# pyright: basic, reportMissingImports=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportCallIssue=false, reportArgumentType=false
"""Scenario driver for the provider tests. Run under the Hermes interpreter through ``python3 -I -c``.

The tests start it with the exact form: python3 -I -c "import sys; sys.path.insert(0,'<HINDSIGHT_HOUSE_TEST_HERMES_AGENT_DIR>');
import hermes_bootstrap; ..." and read the one JSON line it prints. It uses the REAL loader in a scratch HERMES_HOME.
It never calls the hermes command and never touches an installed plugin or a profile. Fixtures are synthetic text.
Environment: HH_SCENARIO, HH_STOCK (stock folder or empty), HH_HOUSE (house source folder), HH_SCRATCH_ROOT (the folder the test helper made),
HH_SITE, HH_COV_FILE (optional; then HINDSIGHT_HOUSE_TEST_COVERAGE_SITE names the folder that holds the coverage package).
"""

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

HOME = Path(os.environ["HERMES_HOME"])
SCRATCH = Path(os.environ["HH_SCRATCH_ROOT"])  # HERMES_HOME must sit under the folder that the test helper made
assert HOME.resolve().is_relative_to(SCRATCH.resolve()) and os.environ.get("HERMES_DISABLE_LAZY_INSTALLS") == "1"
COV = None
if os.environ.get("HH_COV_FILE"):  # branch coverage of the house files, written next to the test run
    _cov_site = os.environ.get("HINDSIGHT_HOUSE_TEST_COVERAGE_SITE")
    assert _cov_site, "HINDSIGHT_HOUSE_TEST_COVERAGE_SITE is not set: it names the folder that holds the coverage package"
    sys.path.append(_cov_site)
    import coverage

    COV = coverage.Coverage(data_file=os.environ["HH_COV_FILE"], branch=True, include=["*/plugins/hindsight-house/*"])
    COV.start()

SCENARIO, STOCK, HOUSE = os.environ["HH_SCENARIO"], os.environ.get("HH_STOCK", ""), Path(os.environ["HH_HOUSE"])
if (HOME / "plugins").exists():
    shutil.rmtree(HOME / "plugins")
(HOME / "plugins").mkdir(parents=True)
(HOME / "state.db").unlink(missing_ok=True)
shutil.rmtree(HOME / "hindsight-house", ignore_errors=True)
if STOCK:
    shutil.copytree(STOCK, HOME / "plugins/hindsight", ignore=shutil.ignore_patterns("tests", "docs", "__pycache__", "*.lock"))
shutil.copytree(HOUSE, HOME / "plugins/hindsight-house", ignore=shutil.ignore_patterns("tests", "__pycache__", ".git", "*.pyc"))
(HOME / "config.yaml").write_text("memory:\n  provider: hindsight\n", encoding="utf-8")

for _site in os.environ.get("HH_SITE", "").split(":"):  # the Hermes environment holds hindsight_client
    if _site:
        sys.path.append(_site)

import plugins.memory as pm  # noqa: E402

RECORDS: list = []
CALLS: list = []
REGS: list = []
EXCLUDE = "relevance:noise,status:superseded"
CFG = {"recall_exclude_tags": EXCLUDE, "recall_max_results": 3, "recall_prompt_preamble": "SYNTH PREAMBLE"}
NOTICE = "[IMPORTANT: Background process proc_a1b2c3d4e5f6 exited (exit code 0).\nCommand: echo synthetic\nOutput:\nsynthetic output line\n"
CUT = {"applies_if": r"\A\s*\[IMPORTANT: Background process proc_[0-9a-f]{8,32} [^\n]{1,160}\n[ \t]*Command:",
       "cut_at": "Output:", "window": 400, "min_keep": 40}


class Capture(logging.Handler):
    def emit(self, record):
        RECORDS.append((record.levelname, record.getMessage()))


logging.getLogger().addHandler(Capture())
logging.getLogger().setLevel(logging.DEBUG)
_real_reg = pm._ProviderCollector.register_memory_provider


def counted(self, provider):
    REGS.append(type(provider).__name__)
    return _real_reg(self, provider)


pm._ProviderCollector.register_memory_provider = counted


class FakeClient:
    def __init__(self, delay=0.0, fail_first=None, tags=None):
        self.delay, self.fail_first, self.tags = delay, fail_first, tags or {}

    async def arecall(self, **kw):
        if self.fail_first:
            msg, self.fail_first = self.fail_first, None
            raise ConnectionError(msg)
        await asyncio.sleep(self.delay)
        CALLS.append((threading.current_thread().name, kw))
        return SimpleNamespace(results=[SimpleNamespace(text="m%d" % i, tags=self.tags.get(i, []), score=0.99) for i in range(5)])

    async def aclose(self):
        return None


def make(client, cfg=None, **attrs):
    prov = pm.load_memory_provider("hindsight-house", register_skills=False)
    if prov is None:
        raise RuntimeError("load failed: %r" % RECORDS[-12:])
    prov._get_client = lambda: client
    if cfg is not None:
        prov._apply_recall_settings(cfg)
        prov._apply_retain_policy(cfg)
    for key, value in attrs.items():
        setattr(prov, key, value)
    return prov


AUTO = {"_recall_sync": True, "_memory_mode": "hybrid", "_auto_recall": True}


def tool(prov, query="q"):
    return json.loads(prov.handle_tool_call("hindsight_recall", {"query": query}))


def bullets(block):
    return sum(1 for line in block.splitlines() if line.startswith("- "))


def kw():
    return CALLS[-1][1]


def context():
    stock_mod = pm.import_provider_module("hindsight")
    facts = {}
    out = tool(make(FakeClient(), CFG))
    facts["t1"] = {"preamble": out["result"].startswith("SYNTH PREAMBLE"), "lines": len([x for x in out["result"].splitlines() if x[:1].isdigit()]),
                   "tag_groups": kw().get("tag_groups"), "has_tags": "tags" in kw(), "thread": CALLS[-1][0]}
    block = make(FakeClient(), CFG, **AUTO).prefetch("q", session_id="s")
    facts["t2"] = {"bullets": bullets(block), "tag_groups": "tag_groups" in kw()}
    prov = make(FakeClient(), CFG, _recall_sync=False, _memory_mode="hybrid", _auto_recall=True, _prefetch_waits_for_retain=False)
    prov.queue_prefetch("q", session_id="s")
    prov._prefetch_thread.join(5)
    block = prov.prefetch("q2", session_id="s")
    facts["t3"] = {"bullets": bullets(block), "thread": CALLS[-1][0], "tag_groups": "tag_groups" in kw()}
    CALLS.clear()
    prov = make(FakeClient(delay=0.3), CFG, **AUTO)
    box = {}
    worker = threading.Thread(target=lambda: box.update(auto=prov.prefetch("auto-q", session_id="s")))
    worker.start()
    time.sleep(0.05)
    box["tool"] = tool(prov, "tool-q")["result"]
    worker.join(5)
    facts["t4"] = {"auto_bullets": bullets(box["auto"]), "tool_lines": len([x for x in box["tool"].splitlines() if x[:1].isdigit()]),
                   "all_tag_groups": all("tag_groups" in c[1] for c in CALLS), "n": len(CALLS)}
    prov = make(FakeClient(), CFG, **AUTO)
    cls = type(prov).__mro__[1]
    orig = cls._recall
    cls._recall = lambda self, q: stock_mod._run_sync(self._get_client().arecall(bank_id="b", query=q)).results
    RECORDS.clear()
    try:
        bad = tool(prov)
        auto = prov.prefetch("q", session_id="s")
    finally:
        cls._recall = orig
    facts["t5"] = {"tool": bad, "auto": auto, "logged": [m for lvl, m in RECORDS if lvl == "ERROR" and "HINDSIGHT_HOUSE_GUARD recall-bypass" in m]}
    flaky = FakeClient(fail_first="daemon " + stock_mod._RETRIABLE_CONNECTION_MARKERS[0])
    CALLS.clear()
    out = tool(make(flaky, CFG, _mode="local_embedded"))
    facts["t6"] = {"ok": "result" in out, "calls": len(CALLS), "tag_groups": "tag_groups" in kw()}
    tool(make(FakeClient(), {**CFG, "recall_tags": "inc"}))
    facts["inclusion"] = {"tag_groups": kw().get("tag_groups"), "has_tags": "tags" in kw()}
    CALLS.clear()
    prov = make(FakeClient(), {**CFG, "recall_query_cuts": [CUT]}, **AUTO)
    prov.prefetch(NOTICE, session_id="s")
    facts["cut"] = {"query": kw()["query"], "tool_query": (tool(prov, NOTICE), kw()["query"])[1] == NOTICE}
    con = sqlite3.connect(HOME / "state.db")
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, active INTEGER, _compressed_summary INTEGER, display_kind TEXT)")
    con.execute("INSERT INTO messages (session_id, role, content, active, _compressed_summary) VALUES ('s1','assistant','SYNTH earlier statement about the plan',1,0)")
    con.commit()
    con.close()
    short = {**CFG, "recall_short_query_chars": 20, "recall_short_query_context_chars": 200}
    queries = {}
    for label, cfg, query, sid in (("on", short, "yes", "s1"), ("long", short, "x" * 30, "s1"), ("nosid", short, "yes", ""), ("off", CFG, "yes", "s1")):
        make(FakeClient(), cfg, **AUTO).prefetch(query, session_id=sid)
        queries[label] = kw()["query"]
    facts["short"] = queries
    cron = {}
    for label, cfg in (("default", CFG), ("on", {**CFG, "recall_cron": True})):
        CALLS.clear()
        block = make(FakeClient(), cfg, _agent_context="cron", **AUTO).prefetch("q", session_id="s")
        cron[label] = {"bullets": bullets(block), "calls": len(CALLS)}
    facts["cron"] = cron
    return facts


def writes(cls_or_inst, cfg=None):
    queued = []
    inst = cls_or_inst
    inst._enqueue_retain = queued.append
    inst._build_retain_kwargs = lambda *a, **k: {}
    inst.on_memory_write("add", "memory", "synthetic note")
    return len(queued)


def switches():
    stock = pm.import_provider_module("hindsight").HindsightMemoryProvider
    facts = {}
    for label, cfg in (("empty", {}), ("explicit_off", {"recall_exclude_tags": "", "recall_max_results": 0, "mirror_builtin_memory": False,
                                                    "recall_query_cuts": [], "recall_short_query_chars": 0, "recall_cron": True})):
        runs = []
        for cls in (None, "house"):
            CALLS.clear()
            if cls is None:
                prov = stock()
                prov._get_client = lambda: FakeClient()
                prov._apply_recall_settings(cfg)
                for k, v in AUTO.items():
                    setattr(prov, k, v)
            else:
                prov = make(FakeClient(), cfg, **AUTO)
            tool_out = prov.handle_tool_call("hindsight_recall", {"query": NOTICE})
            block = prov.prefetch(NOTICE, session_id="s1")
            runs.append({"tool": tool_out, "auto": block, "kwargs": [c[1] for c in CALLS]})
        facts[label] = {"same": runs[0] == runs[1], "n_calls": len(runs[1]["kwargs"]), "has_filter": any("tag_groups" in k for k in runs[1]["kwargs"])}
    facts["writes"] = {"stock": writes(stock()), "house_default": writes(make(FakeClient())),
                       "house_on": writes(make(FakeClient(), {"mirror_builtin_memory": True}))}
    house = type(make(FakeClient()))
    facts["handlers"] = {"recall_is_house": house._TOOL_HANDLERS["hindsight_recall"][1].__qualname__.startswith("_build_house_class"),
                         "others_same": all(house._TOOL_HANDLERS[k] is stock._TOOL_HANDLERS[k] for k in ("hindsight_retain", "hindsight_reflect")),
                         "stock_untouched": stock._TOOL_HANDLERS["hindsight_recall"][1].__qualname__.startswith("HindsightMemoryProvider")}
    schema = make(FakeClient()).get_config_schema()
    facts["schema"] = {"keys": [e["key"] for e in schema][-7:], "stock_n": len(stock().get_config_schema()), "n": len(schema)}
    return facts


def guard():
    flag = HOME / "hindsight-house" / "guard_state.json"
    prov = pm.load_memory_provider("hindsight-house", register_skills=False)
    facts = {"provider": None if prov is None else type(prov).__name__, "regs": list(REGS),
             "flag": json.loads(flag.read_text()) if flag.exists() else None,
             "errors": [m for lvl, m in RECORDS if lvl == "ERROR" and "HINDSIGHT_HOUSE_GUARD" in m]}
    if prov is not None:
        facts["name"] = prov.name
        client = FakeClient(tags={1: ["relevance:noise"], 3: ["status:superseded"]})
        prov._get_client = lambda: client
        prov._apply_recall_settings(CFG)
        for k, v in AUTO.items():
            setattr(prov, k, v)
        facts["tool"] = tool(prov)
        facts["auto"] = prov.prefetch("q", session_id="s")
        facts["recall_disabled"] = prov._recall_disabled()
        facts["mirror"] = writes(prov)
    return facts


def cancelled_wizard(setup_mod):
    """The REAL stock run_setup, cancelled at its first prompt: the config must stay as stock leaves it."""
    import yaml

    real_select, out = setup_mod._select, {}
    setup_mod._select = lambda *args, **kwargs: None
    try:
        for before in ("hindsight", "honcho"):
            (HOME / "config.yaml").write_text("memory:\n  provider: %s\n" % before, encoding="utf-8")
            prov = make(FakeClient())
            prov._config = {}
            config = {"memory": {"provider": before}}
            prov.post_setup(str(HOME), config)
            out[before] = [config["memory"].get("provider"), yaml.safe_load((HOME / "config.yaml").read_text(encoding="utf-8"))["memory"]["provider"]]
        prov = make(FakeClient())
        prov._config = {}
        config = {"memory": {}}
        prov.post_setup(str(HOME), config)
        out["absent"] = sorted(config["memory"])
    finally:
        setup_mod._select = real_select
    return out


def post_setup():
    stock_mod = pm.import_provider_module("hindsight")
    setup_mod = sys.modules[stock_mod.__name__ + ".setup"]
    src = Path(setup_mod.__file__).read_text(encoding="utf-8")
    import re
    import yaml
    from hermes_cli.config import save_config

    def wizard(provider, hermes_home, config):  # the stock wizard's last config steps, no prompts
        config["memory"]["provider"] = "hindsight"
        save_config(config)

    cancelled = cancelled_wizard(setup_mod)
    setup_mod.run_setup = wizard
    facts = {"stock_sets_hindsight": bool(re.search(r'\["provider"\]\s*=\s*"hindsight"', src))}
    facts["cancelled"] = cancelled
    prov = make(FakeClient())
    config = {"memory": {"provider": "hindsight"}}
    prov.post_setup(str(HOME), config)
    facts["config_dict"] = config["memory"]["provider"]
    facts["config_yaml"] = yaml.safe_load((HOME / "config.yaml").read_text(encoding="utf-8"))["memory"]["provider"]
    stock_mod.HindsightMemoryProvider().post_setup(str(HOME), config)
    facts["stock_alone_yaml"] = yaml.safe_load((HOME / "config.yaml").read_text(encoding="utf-8"))["memory"]["provider"]
    return facts


def loader():
    prov = pm.load_memory_provider("hindsight-house", register_skills=False)
    mods = sorted(k for k in sys.modules if "hindsight-house__source_" in k and k.count(".") == 1)
    stock = pm.import_provider_module("hindsight")
    return {"names": [n for n in pm.list_memory_provider_names() if "hindsight" in n], "name": prov.name, "regs": list(REGS), "isinstance_stock": isinstance(prov, stock.HindsightMemoryProvider),
            "house_modules": len(mods), "module_prefix": mods[0].split("__source_")[0], "siblings": sorted(k.rsplit(".", 1)[1] for k in sys.modules if k.startswith(mods[0] + ".")),
            "tools": sorted(s["name"] for s in prov.get_tool_schemas()), "stock_same_object": pm.import_provider_module("hindsight") is stock}


def extra():
    async def kind(self):
        return type(self).__name__

    FakeClient.kind = kind
    prov = make(FakeClient(), CFG, **AUTO)
    hmod = sys.modules[type(prov).__module__]
    proxy = hmod._RecallClientProxy(FakeClient(), [], dict)
    asyncio.run(proxy.arecall(query="q"))
    facts = {"proxy_attr": proxy.delay, "proxy_counted": len(proxy._counter), "plain_op": prov._run_hindsight_operation(lambda c: c.kind())}
    saved = {k: sys.modules.get(k) for k in ("hermes_constants", "agent.memory_manager")}
    sys.modules["hermes_constants"] = sys.modules["agent.memory_manager"] = None
    try:
        facts["home_none"], facts["redact_none"] = hmod._home() is None, hmod._redactor() is None
    finally:
        for key, value in saved.items():
            sys.modules.pop(key, None) if value is None else sys.modules.__setitem__(key, value)
    facts["real_home"], facts["redact"] = str(hmod._home()) == str(HOME), hmod._redactor()("plain words")
    CALLS.clear()
    tools_mode = make(FakeClient(), CFG, _recall_sync=True, _memory_mode="tools", _auto_recall=True)
    facts["tools_mode"] = {"block": tools_mode.prefetch("q", session_id="s"), "calls": len(CALLS)}
    return facts


def stress():
    """8 threads x 10 mixed auto and tool recalls on ONE provider with jittered client latency, so the loop
    thread interleaves the proxies; then a failing client on both paths must leave the thread-local clean."""
    import random

    rng = random.Random(7)

    class Jitter(FakeClient):
        async def arecall(self, **kw):
            await asyncio.sleep(rng.random() * 0.02)
            return await FakeClient.arecall(self, **kw)

    class Boom(FakeClient):
        async def arecall(self, **kw):
            raise ValueError("synthetic failure")

    CALLS.clear()
    prov = make(Jitter(), CFG, **AUTO)
    hmod = sys.modules[type(prov).__module__]
    out, errors = [], []

    def state():
        return repr((getattr(hmod._CTX, "recall", None), getattr(hmod._CTX, "origin", None)))

    def worker(i):
        try:
            for j in range(10):
                if (i + j) % 2:
                    out.append(("auto", bullets(prov.prefetch("auto-%d-%d" % (i, j), session_id="s"))))
                else:
                    lines = tool(prov, "tool-%d-%d" % (i, j))["result"].splitlines()
                    out.append(("tool", len([x for x in lines if x[:1].isdigit()])))
            out.append(("ctx", state()))
        except Exception as exc:
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    facts = {"auto": sorted({n for k, n in out if k == "auto"}), "tool": sorted({n for k, n in out if k == "tool"}),
             "ctx": sorted({v for k, v in out if k == "ctx"}), "errors": errors, "calls": len(CALLS),
             "all_tag_groups": all("tag_groups" in c[1] for c in CALLS), "loop_threads": sorted({c[0] for c in CALLS})}
    bad = make(Boom(), CFG, **AUTO)
    failed_tool, failed_auto, after = tool(bad), bad.prefetch("q", session_id="s"), state()
    bad._get_client = lambda: FakeClient()
    plain = bad._run_hindsight_operation(lambda c: asyncio.sleep(0, result=type(c).__name__))
    again = len([x for x in tool(bad)["result"].splitlines() if x[:1].isdigit()])
    facts["after_failure"] = {"tool_error": "error" in failed_tool, "auto": failed_auto, "ctx": after, "plain": plain, "again": again}
    return facts


try:
    result = {"context": context, "extra": extra, "switches": switches, "guard": guard, "post_setup": post_setup, "loader": loader,
              "stress": stress}[SCENARIO]()
finally:
    if COV is not None:
        COV.stop()
        COV.save()
print("HH_RESULT " + json.dumps(result, default=str))
