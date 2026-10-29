"""notice_cut. Synthetic fixtures with the shape of the packet notices; no real text of any person.

Shape: line 1 "[IMPORTANT: Background process proc_<hex> <state> (exit code N...)." / line 2 "Command: ..." /
line 3 "Output:" / output lines / a gateway-style trailer. Property tests are in the hypothesis section below.
"""

import itertools
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import notice_cut as nc
from house_settings import CutRule, parse_house_settings

APPLIES = r"\A\s*\[IMPORTANT: Background process proc_[0-9a-f]{8,32} [^\n]{1,160}\n[ \t]*Command:"
HOUSE_RULE = {"applies_if": APPLIES, "cut_at": "Output:", "window": 400, "min_keep": 40}
HOUSE = parse_house_settings({"recall_query_cuts": [HOUSE_RULE]}).query_cuts
RULE = HOUSE[0]

STATES = ["completed", "failed", "was killed", "finished"]
COMMANDS = [
    "python3 build.py --all",
    "sh -c 'sleep 30 && echo done'",
    "pytest -q tests/test_unit.py",
    "rsync -a /srv/data/ /srv/backup/",
]
CODES = [0, 1, 2, 137]


def notice(proc="deadbeef12", state="completed", code=0, command="make all", body="line a\nline b\n", trailer=""):
    return (
        f"[IMPORTANT: Background process proc_{proc} {state} (exit code {code}).\n"
        f"Command: {command}\nOutput:\n{body}{trailer}"
    )


def head_of(text):
    return "\n".join(text.split("\n")[:2])


FIXTURES = [
    notice(proc="%08x" % (0xA1B2C3D4 + i * 977), state=s, code=c, command=cmd, body="x" * (i * 37) + "\ndone\n")
    for i, (s, c, cmd) in enumerate(itertools.product(STATES, CODES, COMMANDS))
][:32]


def test_there_are_32_distinct_fixtures():
    assert len(set(FIXTURES)) == 32


def test_every_fixture_matches_and_keeps_exactly_lines_one_and_two(text):
    assert RULE.applies_if.search(text[: RULE.window])
    out = nc.cut_query(text, HOUSE)
    assert out == head_of(text)
    assert out.count("\n") == 1
    assert text.startswith(out)
    assert len(out) < len(text)

test_every_fixture_matches_and_keeps_exactly_lines_one_and_two = pytest.mark.parametrize("text", FIXTURES)(test_every_fixture_matches_and_keeps_exactly_lines_one_and_two)


def test_output_inside_the_command_line_is_not_a_cut():
    text = notice(command="echo Output: here and Output: there")
    out = nc.cut_query(text, HOUSE)
    assert out == head_of(text)
    assert "Output: there" in out


def test_gateway_trailer_goes_with_the_body():
    text = notice(body="result\n", trailer="[gateway] delivered via telegram\n")
    assert "gateway" not in nc.cut_query(text, HOUSE)


def test_first_line_start_marker_wins():
    text = notice(body="first\nOutput:\nsecond\n")
    assert nc.cut_query(text, HOUSE) == head_of(text)


def test_ordinary_text_is_unchanged():
    for text in ["", "Yes please", "Output:\nonly output", "Command: ls\nOutput:\nx" * 3]:
        assert nc.cut_query(text, HOUSE) is text


def test_no_rules_is_unchanged():
    text = notice()
    assert nc.cut_query(text, ()) is text
    assert nc.cut_query(text, []) is text


def test_non_text_is_returned_as_is(value):
    assert nc.cut_query(value, HOUSE) is value

test_non_text_is_returned_as_is = pytest.mark.parametrize("value", [None, 5, b"bytes", ["a"]])(test_non_text_is_returned_as_is)


# -- the line-start rule ------------------------------------------------------------------------


def plain_rule(cut_at="Output:", applies=r"\Ahead", window=100, min_keep=1):
    return CutRule(re.compile(applies), cut_at, window, min_keep)


def test_marker_after_each_line_start_character(sep):
    text = "head line" + sep + "Output: body"
    assert nc.cut_query(text, [plain_rule()]) == "head line"

test_marker_after_each_line_start_character = pytest.mark.parametrize("sep", ["\n", "\r", "\u2028", "\u2029", "\r\n"])(test_marker_after_each_line_start_character)


def test_marker_after_any_other_character_is_not_a_hit(before):
    text = "head line" + before + "Output: body"
    assert nc.cut_query(text, [plain_rule()]) is text

test_marker_after_any_other_character_is_not_a_hit = pytest.mark.parametrize("before", [" ", "\t", "x", ":", "\x0b", "\x0c", "\x85", "\u00a0"])(test_marker_after_any_other_character_is_not_a_hit)


def test_marker_after_a_space_then_a_real_one_later():
    text = "head line Output: not here\nOutput: here\nrest"
    assert nc.cut_query(text, [plain_rule()]) == "head line Output: not here"


def test_marker_at_index_zero_keeps_nothing_and_is_refused():
    text = "head Output:\nOutput:\n"  # a second hit, but the first line-start hit is at index 13 here
    assert nc.cut_query(text, [plain_rule(applies=r"\Ahead")]) == "head Output:"
    only = "Output: x"
    assert nc.cut_query(only, [plain_rule(applies="Output", min_keep=0)]) is only


def test_trailing_whitespace_of_the_kept_part_is_stripped():
    text = "head line  \t \n\n  \nOutput: body"
    assert nc.cut_query(text, [plain_rule()]) == "head line"


def test_leading_whitespace_is_kept():
    text = "  head line\nOutput: body"
    assert nc.cut_query(text, [plain_rule(applies=r"\A\s*head")]) == "  head line"


def test_the_marker_is_a_literal_not_a_pattern():
    text = "head a.b\nOutput (x)\nrest\nOutput(x)\nmore"
    assert nc.cut_query(text, [plain_rule(cut_at="Output(x)")]) == "head a.b\nOutput (x)\nrest"
    assert nc.cut_query("head\naXb\nrest", [plain_rule(cut_at="a.b")]) == "head\naXb\nrest"


def test_a_marker_longer_than_the_text_tail():
    assert nc.cut_query("head\nOut", [plain_rule(cut_at="Output:")]) == "head\nOut"


def test_empty_marker_is_skipped():
    text = "head line\nbody"
    assert nc.cut_query(text, [plain_rule(cut_at="")]) is text


# -- window and min_keep boundaries ---------------------------------------------------------------


def test_window_edge_the_pattern_must_end_inside_the_window():
    text = "head" + "." * 10 + "\nOutput: x"
    rule = plain_rule(applies=r"\Ahead\.{10}", window=14)
    assert nc.cut_query(text, [rule]) == "head" + "." * 10
    short = plain_rule(applies=r"\Ahead\.{10}", window=13)
    assert nc.cut_query(text, [short]) is text


def test_window_does_not_limit_where_the_marker_may_sit():
    text = "head\n" + "pad\n" * 500 + "Output: x"
    out = nc.cut_query(text, [plain_rule(window=10)])
    assert out == text[: len(text) - len("Output: x")].rstrip()


def test_min_keep_boundary():
    text = "abcde\nOutput: x"
    assert nc.cut_query(text, [plain_rule(applies="abc", min_keep=5)]) == "abcde"
    assert nc.cut_query(text, [plain_rule(applies="abc", min_keep=6)]) is text


def test_min_keep_counts_the_stripped_part():
    text = "abc  \n\nOutput: x"
    assert nc.cut_query(text, [plain_rule(applies="abc", min_keep=3)]) == "abc"
    assert nc.cut_query(text, [plain_rule(applies="abc", min_keep=4)]) is text


def test_min_keep_zero_still_refuses_an_empty_cut():
    text = "\n\nOutput: x"
    assert nc.cut_query(text, [plain_rule(applies=r"\A\s*", min_keep=0)]) is text


# -- several rules --------------------------------------------------------------------------------


def test_the_first_rule_that_cuts_wins():
    text = "head one\nMARK1 a\nMARK2 b"
    first, second = plain_rule(cut_at="MARK1"), plain_rule(cut_at="MARK2")
    assert nc.cut_query(text, [first, second]) == "head one"
    assert nc.cut_query(text, [second, first]) == "head one\nMARK1 a"


def test_a_rule_that_does_not_apply_is_skipped():
    text = "head one\nMARK1 a"
    skip = plain_rule(applies=r"\Anomatch")
    assert nc.cut_query(text, [skip, plain_rule(cut_at="MARK1")]) == "head one"


def test_a_rule_that_applies_but_finds_no_marker_falls_to_the_next():
    text = "head one\nMARK2 b"
    assert nc.cut_query(text, [plain_rule(cut_at="MARK1"), plain_rule(cut_at="MARK2")]) == "head one"


def test_a_rule_that_cuts_too_short_falls_to_the_next():
    text = "head\nMARK1 a\nlonger head part\nMARK2 b"
    tight = plain_rule(cut_at="MARK1", min_keep=50)
    assert nc.cut_query(text, [tight, plain_rule(cut_at="MARK2", min_keep=5)]) == "head\nMARK1 a\nlonger head part"


def test_rules_may_be_any_iterable():
    text = "head one\nMARK1 a"
    assert nc.cut_query(text, iter([plain_rule(cut_at="MARK1")])) == "head one"


# -- hypothesis: never raises, prefix of the input, min_keep holds --------------------

FRAGMENTS = [
    "Output:", "\n", "\r", "\u2028", "\u2029", " ", "\t", "Command:", "abc", "x" * 30, "Output: ", "output:",
    "[IMPORTANT: Background process proc_deadbeef12 completed (exit code 0).", "\r\n", "\u0085", "é", chr(0x1F4A5),
]
texts = st.one_of(
    st.text(max_size=300),
    st.lists(st.sampled_from(FRAGMENTS), max_size=30).map("".join),
    st.lists(st.sampled_from(FRAGMENTS), max_size=12).map(lambda parts: notice_head() + "".join(parts)),
)
rules_strategy = st.builds(
    lambda pattern, marker, window, keep: CutRule(re.compile(pattern), marker, window, keep),
    st.sampled_from([APPLIES, r"\A", r"IMPORTANT", r"Command", r"zzz"]),
    st.sampled_from(["Output:", "\n", "x", "Command:", "é", "\u2028"]),
    st.integers(min_value=1, max_value=500),
    st.integers(min_value=0, max_value=120),
)


def notice_head():
    return "[IMPORTANT: Background process proc_deadbeef12 completed (exit code 0).\nCommand: make all\n"


def check_house_rule(text):
    out = nc.cut_query(text, HOUSE)
    assert isinstance(out, str)
    assert text.startswith(out)
    assert out == text or len(out) >= RULE.min_keep
    assert out == text or out == out.rstrip()
    assert out == text or nc._line_start_hit(out, "Output:") < 0
    assert nc.cut_query(out, HOUSE) == out  # idempotent


def check_any_rules(text, rules):
    out = nc.cut_query(text, rules)
    assert text.startswith(out)
    assert out == text or (out and any(len(out) >= r.min_keep for r in rules))
    assert len(out) <= len(text)


def check_single_rule(text, rule):
    out = nc.cut_query(text, [rule])
    assert text.startswith(out)
    assert out == text or (out and len(out) >= rule.min_keep and out == out.rstrip())
    if out != text:
        assert rule.applies_if.search(text[: rule.window])
        assert nc._line_start_hit(out, rule.cut_at) < 0


test_house_rule_properties = settings(max_examples=400, deadline=None)(given(texts)(check_house_rule))
test_any_rules_properties = settings(max_examples=400, deadline=None)(
    given(texts, st.lists(rules_strategy, max_size=3))(check_any_rules)
)
test_single_rule_properties = settings(max_examples=400, deadline=None)(given(texts, rules_strategy)(check_single_rule))


def test_line_start_hit_values():
    assert nc._line_start_hit("Output: x", "Output:") == 0
    assert nc._line_start_hit("xOutput:", "Output:") == -1
    assert nc._line_start_hit("a\nOutput:", "Output:") == 2
    assert nc._line_start_hit("", "Output:") == -1
    assert nc._line_start_hit("head", "Output:") == -1


def test_first_line_start_hit_wins_after_a_near_miss():
    text = "head a Output: x\nOutput: y\nOutput: z"
    assert nc._line_start_hit(text, "Output:") == 17
    assert nc.cut_query(text, [plain_rule()]) == "head a Output: x"


def test_a_hit_right_after_a_near_miss_is_found():
    text = "head x\n\n\nbody"
    assert nc._line_start_hit(text, "\n\n") == 7
    assert nc.cut_query(text, [plain_rule(cut_at="\n\n")]) == "head x"

