"""house_settings.parse_house_settings. Every key off gives the stock-parity default."""

import logging

import pytest

from house_settings import CutRule, HouseSettings, parse_house_settings

APPLIES = r"\A\s*\[IMPORTANT: Background process proc_[0-9a-f]{8,32} [^\n]{1,160}\n[ \t]*Command:"


def test_empty_and_none_give_defaults():
    expected = HouseSettings()
    assert parse_house_settings({}) == expected
    assert parse_house_settings(None) == expected
    assert expected.exclude_tags == ()
    assert expected.max_results == 0
    assert expected.recall_cron is False
    assert expected.mirror_builtin_memory is False
    assert expected.query_cuts == ()
    assert expected.short_query_chars == 0
    assert expected.short_query_context_chars == 400


def test_non_mapping_config_gives_defaults_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        assert parse_house_settings(["x"]) == HouseSettings()
    assert "config" in caplog.text


def test_exclude_tags_shapes(value, expected):
    assert parse_house_settings({"recall_exclude_tags": value}).exclude_tags == expected

test_exclude_tags_shapes = pytest.mark.parametrize(
    "value, expected",
    [
        ("relevance:noise,status:superseded", ("relevance:noise", "status:superseded")),
        (" a , b ,, a ", ("a", "b")),
        (["a", "b", "a", "", "  "], ("a", "b")),
        (("a", "b"), ("a", "b")),
        ('["a", "b"]', ("a", "b")),
        ('["a", 5, "b"]', ("a", "b")),
        ("[not json", ("[not json",)),
        ("", ()),
        (None, ()),
        ([], ()),
    ],
)(test_exclude_tags_shapes)


def test_exclude_tags_wrong_type_warns(caplog):
    with caplog.at_level(logging.WARNING):
        assert parse_house_settings({"recall_exclude_tags": 5}).exclude_tags == ()
    assert "recall_exclude_tags" in caplog.text


def test_int_keys_accept_numbers(key, field, value, expected):
    assert getattr(parse_house_settings({key: value}), field) == expected

test_int_keys_accept_numbers = pytest.mark.parametrize(
    "value, expected",
    [(3, 3), ("3", 3), (" 7 ", 7), (3.0, 3), (0, 0)],
)(test_int_keys_accept_numbers)
test_int_keys_accept_numbers = pytest.mark.parametrize(
    "key, field",
    [
        ("recall_max_results", "max_results"),
        ("recall_short_query_chars", "short_query_chars"),
        ("recall_short_query_context_chars", "short_query_context_chars"),
    ],
)(test_int_keys_accept_numbers)


def test_int_keys_bad_value_gives_default_and_warns(bad, caplog):
    with caplog.at_level(logging.WARNING):
        got = parse_house_settings({"recall_max_results": bad})
    assert got.max_results == 0
    assert "recall_max_results" in caplog.text

test_int_keys_bad_value_gives_default_and_warns = pytest.mark.parametrize("bad", ["x", "3.5", 3.5, True, False, [], {}, float("nan"), float("inf")])(test_int_keys_bad_value_gives_default_and_warns)


def test_int_keys_empty_gives_default_without_warning(empty, caplog):
    with caplog.at_level(logging.WARNING):
        got = parse_house_settings({"recall_short_query_context_chars": empty})
    assert got.short_query_context_chars == 400
    assert caplog.text == ""

test_int_keys_empty_gives_default_without_warning = pytest.mark.parametrize("empty", [None, ""])(test_int_keys_empty_gives_default_without_warning)


def test_huge_int_string_is_accepted_as_an_int():
    assert parse_house_settings({"recall_max_results": "9" * 30}).max_results == 10**30 - 1


def test_bool_keys(value, expected):
    got = parse_house_settings({"recall_cron": value, "mirror_builtin_memory": value})
    assert got.recall_cron is expected
    assert got.mirror_builtin_memory is expected

test_bool_keys = pytest.mark.parametrize(
    "value, expected",
    [(True, True), (False, False), ("true", True), ("TRUE", True), ("yes", True), ("on", True), ("1", True),
     ("false", False), ("No", False), ("off", False), ("0", False), ("", False), (1, True), (0, False)],
)(test_bool_keys)


def test_bool_keys_bad_value_gives_default_and_warns(bad, caplog):
    with caplog.at_level(logging.WARNING):
        got = parse_house_settings({"recall_cron": bad, "mirror_builtin_memory": bad})
    assert got.recall_cron is False  # default
    assert got.mirror_builtin_memory is False  # default of mirror_builtin_memory
    assert "recall_cron" in caplog.text and "mirror_builtin_memory" in caplog.text

test_bool_keys_bad_value_gives_default_and_warns = pytest.mark.parametrize("bad", ["maybe", 2, [], 1.5])(test_bool_keys_bad_value_gives_default_and_warns)


def test_bool_none_gives_default():
    got = parse_house_settings({"recall_cron": None, "mirror_builtin_memory": None})
    assert (got.recall_cron, got.mirror_builtin_memory) == (False, False)


def test_mirror_default_is_false_and_explicit_true_is_kept():
    assert parse_house_settings({}).mirror_builtin_memory is False
    assert parse_house_settings({"mirror_builtin_memory": True}).mirror_builtin_memory is True


def test_recall_topic_rules_warns_and_is_ignored(caplog):
    with caplog.at_level(logging.WARNING):
        got = parse_house_settings({"recall_topic_rules": [{"keywords": ["x"], "tags": ["t"]}]})
    assert got == HouseSettings()
    assert "recall_topic_rules" in caplog.text


def test_recall_topic_rules_empty_does_not_warn(caplog):
    with caplog.at_level(logging.WARNING):
        parse_house_settings({"recall_topic_rules": ""})
        parse_house_settings({"recall_topic_rules": []})
    assert caplog.text == ""


def _rule(**extra):
    return {"applies_if": APPLIES, "cut_at": "Output:", "window": 400, "min_keep": 40, **extra}


def test_query_cuts_from_a_list():
    got = parse_house_settings({"recall_query_cuts": [_rule()]}).query_cuts
    assert len(got) == 1
    rule = got[0]
    assert isinstance(rule, CutRule)
    assert rule.cut_at == "Output:"
    assert (rule.window, rule.min_keep) == (400, 40)
    assert rule.applies_if.pattern == APPLIES


def test_query_cuts_from_a_json_string():
    import json

    got = parse_house_settings({"recall_query_cuts": json.dumps([_rule(window=300, min_keep=10)])}).query_cuts
    assert [(r.window, r.min_keep) for r in got] == [(300, 10)]


def test_query_cuts_defaults_for_window_and_min_keep():
    entry = {"applies_if": "x", "cut_at": "Output:"}
    rule = parse_house_settings({"recall_query_cuts": [entry]}).query_cuts[0]
    assert (rule.window, rule.min_keep) == (400, 40)


def test_query_cuts_bad_window_falls_back_to_the_default_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        rule = parse_house_settings({"recall_query_cuts": [_rule(window="wide")]}).query_cuts[0]
    assert rule.window == 400
    assert "window" in caplog.text


def test_query_cuts_min_keep_zero_is_kept():
    rule = parse_house_settings({"recall_query_cuts": [_rule(min_keep=0)]}).query_cuts[0]
    assert rule.min_keep == 0


def test_query_cuts_empty(empty):
    assert parse_house_settings({"recall_query_cuts": empty}).query_cuts == ()

test_query_cuts_empty = pytest.mark.parametrize("empty", [None, "", []])(test_query_cuts_empty)


def test_query_cuts_bad_container_warns(bad, caplog):
    with caplog.at_level(logging.WARNING):
        assert parse_house_settings({"recall_query_cuts": bad}).query_cuts == ()
    assert "recall_query_cuts" in caplog.text

test_query_cuts_bad_container_warns = pytest.mark.parametrize("bad", ["not json", "{}", 5, {"applies_if": "x"}])(test_query_cuts_bad_container_warns)


def test_query_cuts_bad_rule_is_dropped_with_a_warning(entry, caplog):
    good = _rule()
    with caplog.at_level(logging.WARNING):
        got = parse_house_settings({"recall_query_cuts": [entry, good]}).query_cuts
    assert len(got) == 1 and got[0].applies_if.pattern == APPLIES
    assert "rule 0" in caplog.text

test_query_cuts_bad_rule_is_dropped_with_a_warning = pytest.mark.parametrize(
    "entry",
    [
        "text",
        5,
        None,
        {},
        {"applies_if": "x"},
        {"cut_at": "Output:"},
        {"applies_if": "", "cut_at": "Output:"},
        {"applies_if": "x", "cut_at": ""},
        {"applies_if": 5, "cut_at": "Output:"},
        {"applies_if": "x", "cut_at": 5},
        {"applies_if": "(unclosed", "cut_at": "Output:"},
        {"applies_if": "x", "cut_at": "Output:", "window": 0},
    ],
)(test_query_cuts_bad_rule_is_dropped_with_a_warning)


def test_pattern_is_never_logged(caplog):
    secret_shaped = "(zz-not-for-logs"
    with caplog.at_level(logging.WARNING):
        parse_house_settings({"recall_query_cuts": [{"applies_if": secret_shaped, "cut_at": "O"}]})
    assert secret_shaped not in caplog.text


def test_bad_value_is_never_logged(caplog):
    with caplog.at_level(logging.WARNING):
        parse_house_settings({"recall_max_results": "zz-not-for-logs"})
    assert "zz-not-for-logs" not in caplog.text


def test_all_keys_together():
    cfg = {
        "recall_exclude_tags": "relevance:noise,status:superseded",
        "recall_max_results": 3,
        "recall_cron": False,
        "mirror_builtin_memory": False,
        "recall_query_cuts": [_rule()],
        "recall_short_query_chars": 60,
        "recall_short_query_context_chars": 300,
        "recall_min_scores": {"final": 0.92},  # a stock key: not a house key, must not disturb the parse
    }
    got = parse_house_settings(cfg)
    assert got.exclude_tags == ("relevance:noise", "status:superseded")
    assert got.max_results == 3
    assert got.recall_cron is False
    assert len(got.query_cuts) == 1
    assert (got.short_query_chars, got.short_query_context_chars) == (60, 300)


def test_the_input_config_is_not_mutated():
    cfg = {"recall_exclude_tags": ["a"], "recall_query_cuts": [_rule()]}
    before = repr(cfg)
    parse_house_settings(cfg)
    assert repr(cfg) == before


def test_result_is_hashable_and_immutable():
    got = parse_house_settings({"recall_exclude_tags": "a"})
    assert isinstance(got.exclude_tags, tuple)
    with pytest.raises(AttributeError):
        got.max_results = 9  # type: ignore[misc]


# recall_cron defaults to false (also before the config tool writes the key)
def test_recall_cron_default_is_false():
    assert HouseSettings().recall_cron is False
    assert parse_house_settings({}).recall_cron is False
    assert parse_house_settings({"recall_cron": True}).recall_cron is True


# a negative integer is a bad value: WARNING with the key name, then the default (module contract)
def test_negative_int_warns_and_gives_the_default(key, field, default, value, caplog):
    with caplog.at_level(logging.WARNING):
        got = parse_house_settings({key: value})
    assert getattr(got, field) == default
    assert key in caplog.text


test_negative_int_warns_and_gives_the_default = pytest.mark.parametrize("value", [-4, "-1"])(
    pytest.mark.parametrize("key, field, default", [
        ("recall_max_results", "max_results", 0),
        ("recall_short_query_chars", "short_query_chars", 0),
        ("recall_short_query_context_chars", "short_query_context_chars", 400),
    ])(test_negative_int_warns_and_gives_the_default))


def test_negative_window_gets_the_default_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        rules = parse_house_settings({"recall_query_cuts": [{"applies_if": "x", "cut_at": "O", "window": -5}]}).query_cuts
    assert [r.window for r in rules] == [400]
    assert "window" in caplog.text


# an applies_if with a quantified group that holds a quantifier (catastrophic backtracking) is refused
def test_nested_quantifier_rule_is_dropped(pattern, caplog):
    with caplog.at_level(logging.WARNING):
        rules = parse_house_settings({"recall_query_cuts": [{"applies_if": pattern, "cut_at": "Output:"}]}).query_cuts
    assert rules == ()
    assert "dropping recall_query_cuts rule 0" in caplog.text


test_nested_quantifier_rule_is_dropped = pytest.mark.parametrize(
    "pattern", ["(a+)+$", r"(\w+\s?)*x", "(x{1,3})+", "(?:a*)*b"])(test_nested_quantifier_rule_is_dropped)


def test_house_pattern_and_plain_groups_are_kept():
    for pattern in (APPLIES, "(?:ab)+", r"(\d+)?x", "a+b*"):
        cuts = parse_house_settings({"recall_query_cuts": [{"applies_if": pattern, "cut_at": "Output:"}]}).query_cuts
        assert len(cuts) == 1, pattern


# window, empty cut string and missing config edge cases
def cuts(window):
    return parse_house_settings(
        {"recall_query_cuts": [{"applies_if": "^N", "cut_at": "Output:", "window": window}]}).query_cuts


def warnings_in(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_window_of_one_keeps_the_rule():
    assert [rule.window for rule in cuts(1)] == [1]


def test_a_window_of_zero_drops_the_rule_with_a_warning(caplog):
    caplog.set_level(logging.WARNING)
    assert cuts(0) == ()
    assert any("dropping recall_query_cuts rule 0" in r.getMessage() for r in caplog.records)


def test_an_empty_cut_string_gives_no_rules_and_no_warning(caplog):
    caplog.set_level(logging.DEBUG)
    assert parse_house_settings({"recall_query_cuts": ""}).query_cuts == ()
    assert warnings_in(caplog) == []


def test_no_config_gives_the_defaults_and_no_warning(caplog):
    caplog.set_level(logging.DEBUG)
    assert parse_house_settings(None) == HouseSettings()
    assert warnings_in(caplog) == []
