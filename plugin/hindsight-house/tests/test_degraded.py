"""Tests for degraded.py with a pure-Python stand-in for the stock class (no loader needed)."""

from __future__ import annotations

import json
import logging
import threading
from types import SimpleNamespace

import degraded as dm


def tool_error(message):
    return json.dumps({"error": message})


class Settings:
    def __init__(self, cfg):
        self.exclude_tags = tuple(cfg.get("exclude", ()))


class FakeStock:
    """Shape of the stock class: tool recall goes through self._recall, which returns result objects."""

    marker = "stock"
    results = [SimpleNamespace(text="keep"), SimpleNamespace(text="noise", tags=["relevance:noise"]),
               SimpleNamespace(text="old", tags=["a", "status:superseded"]), SimpleNamespace(text="empty", tags=[])]

    def __init__(self):
        self.writes, self.exclude_seen = [], None
        self._apply_recall_settings({})

    def _apply_recall_settings(self, cfg):
        self.applied = dict(cfg)

    def _recall_disabled(self):
        return False

    def _recall(self, query):
        return list(self.results)

    def on_memory_write(self, action, target, content, metadata=None):
        self.writes.append((action, target, content))
        return "wrote"

    def handle_tool_call(self, tool_name, args, **kwargs):
        if tool_name == "hindsight_recall":
            if not args.get("query"):
                return tool_error("query required")
            return json.dumps({"result": [r.text for r in self._recall(args["query"])]})
        return json.dumps({"result": tool_name})


class BypassStock(FakeStock):
    def handle_tool_call(self, tool_name, args, **kwargs):
        return json.dumps({"result": ["unfiltered"]})


def build(stock=FakeStock):
    return dm.make_degraded_provider(stock, tool_error, Settings)


def test_filter_results_drops_hits_and_keeps_the_rest():
    r = FakeStock.results
    assert [x.text for x in dm.filter_results(r, ["relevance:noise", "status:superseded"])] == ["keep", "empty"]
    assert [x.text for x in dm.filter_results(r, ["status:superseded"])] == ["keep", "noise", "empty"]
    assert dm.filter_results(r, []) is r
    assert dm.filter_results("text", ["x"]) == "text"
    assert [x.text for x in dm.filter_results(tuple(r), ["relevance:noise"])] == ["keep", "old", "empty"]
    assert dm.filter_results([SimpleNamespace(text="a", tags=None)], ["x"])[0].text == "a"


def test_degraded_class_basics():
    cls = build()
    prov = cls()
    assert issubclass(cls, FakeStock) and cls.__name__ == "DegradedProvider"
    assert prov.name == "hindsight-house"
    assert prov._recall_disabled() is True
    assert prov.on_memory_write("add", "memory", "x") is None and prov.writes == []
    assert prov.marker == "stock"


def test_tool_recall_is_filtered_with_the_house_exclusion():
    prov = build()()
    prov._apply_recall_settings({"exclude": ["relevance:noise", "status:superseded"]})
    assert json.loads(prov.handle_tool_call("hindsight_recall", {"query": "q"})) == {"result": ["keep", "empty"]}
    assert prov._house_exclude == ("relevance:noise", "status:superseded")
    assert prov.applied == {"exclude": ["relevance:noise", "status:superseded"]}


def test_default_exclusion_is_empty_and_unfiltered():
    prov = build()()
    assert prov._house_exclude == ()
    assert json.loads(prov.handle_tool_call("hindsight_recall", {"query": "q"}))["result"] == ["keep", "noise", "old", "empty"]


def test_a_tool_call_that_never_reached_the_filter_fails_closed():
    prov = build(BypassStock)()
    assert json.loads(prov.handle_tool_call("hindsight_recall", {"query": "q"})) == {"error": dm.UNAVAILABLE}
    assert json.loads(prov.handle_tool_call("hindsight_retain", {})) == {"result": ["unfiltered"]}


def test_a_stock_error_passes_through_and_the_flag_is_per_call():
    prov = build()()
    assert json.loads(prov.handle_tool_call("hindsight_recall", {})) == {"error": "query required"}
    assert "result" in json.loads(prov.handle_tool_call("hindsight_recall", {"query": "q"}))
    assert json.loads(prov.handle_tool_call("hindsight_retain", {})) == {"result": "hindsight_retain"}
    bypass = build(BypassStock)()
    bypass._recall("q")  # entered once in this thread, then a call that skips the filter must still fail closed
    assert json.loads(bypass.handle_tool_call("hindsight_recall", {"query": "q"}))["error"] == dm.UNAVAILABLE


def test_non_json_output_is_not_an_error():
    class Plain(FakeStock):
        def handle_tool_call(self, tool_name, args, **kwargs):  # type: ignore[override]
            return {"text": "plain text", "none": None}.get(args.get("k"), "[1, 2]")

    prov = build(Plain)()
    assert json.loads(prov.handle_tool_call("hindsight_recall", {})) == {"error": dm.UNAVAILABLE}
    assert json.loads(prov.handle_tool_call("hindsight_recall", {"k": "text"})) == {"error": dm.UNAVAILABLE}
    assert json.loads(prov.handle_tool_call("hindsight_recall", {"k": "none"})) == {"error": dm.UNAVAILABLE}
    assert prov.handle_tool_call("hindsight_retain", {"k": "text"}) == "plain text"


def test_a_drifted_settings_hook_is_logged_and_the_filter_survives(caplog):
    class Broken(FakeStock):
        def _apply_recall_settings(self, cfg):
            if cfg:
                raise TypeError("signature drift")
            self.applied = {}

    prov = build(Broken)()
    with caplog.at_level(logging.ERROR):
        prov._apply_recall_settings({"exclude": ["relevance:noise"]})
    assert prov._house_exclude == ("relevance:noise",)
    assert "HINDSIGHT_HOUSE_GUARD degraded settings failed: TypeError" in caplog.text


def test_the_entered_flag_does_not_cross_threads():
    prov = build(BypassStock)()
    seen = {}

    def other():
        seen["out"] = json.loads(prov.handle_tool_call("hindsight_recall", {"query": "q"}))

    prov._recall("q")
    thread = threading.Thread(target=other)
    thread.start()
    thread.join()
    assert seen["out"] == {"error": dm.UNAVAILABLE}
