"""recall_policy. Ports the cases of two earlier test files for the exclusion tags and the scoping.

The originals drove the stock provider through an earlier patched plugin; the pure functions take the kwargs stock
builds, so each case is restated as input kwargs and expected output kwargs. Topic scoping is not built, so the topic cases are not ported.
"""

import copy
import logging
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

import recall_policy as rp
from house_settings import HouseSettings, parse_house_settings


def compose(*args, **kwargs):
    """compose_short_query with an identity redaction step (no redact callable means no context)."""
    kwargs.setdefault("redact", str)
    return rp.compose_short_query(*args, **kwargs)

AT = chr(64)  # built at run time: a literal at-sign next to a name is a hazard in a tool call
ORIGINS = [rp.ORIGIN_AUTO, rp.ORIGIN_TOOL]


def pol(**kw):
    return HouseSettings(**kw)


def base(**extra):
    """The kwargs stock 1.2.3 builds for one recall (the keys other than the tag filter)."""
    return {"query": "q", "budget": "mid", "max_tokens": 4096, "types": ["observation"], **extra}


# -- rewrite_kwargs: port of test_recall_exclude_tags.py ----------------------------------------


def test_unset_is_identical_to_stock(origin):
    """Port of test_recall_exclude_tags_unset_is_byte_identical_to_before."""
    kwargs = base()
    out = rp.rewrite_kwargs(kwargs, pol(), origin)
    assert out is kwargs
    assert "tag_groups" not in out and "tags" not in out

test_unset_is_identical_to_stock = pytest.mark.parametrize("origin", ORIGINS)(test_unset_is_identical_to_stock)


def test_exclusion_alone_builds_a_not_group(origin):
    """Port of test_recall_exclude_tags_alone_builds_not_tag_group (also covers the auto and tool path)."""
    out = rp.rewrite_kwargs(base(), pol(exclude_tags=("noise", "junk")), origin)
    assert "tags" not in out
    assert out["tag_groups"] == [{"not": {"tags": ["noise", "junk"]}}]

test_exclusion_alone_builds_a_not_group = pytest.mark.parametrize("origin", ORIGINS)(test_exclusion_alone_builds_a_not_group)


def test_exclusion_combines_with_inclusion(origin):
    """Port of test_recall_exclude_tags_combines_with_recall_tags (the 422 rule): tags and tags_match are gone."""
    out = rp.rewrite_kwargs(base(tags=["project:x"], tags_match="any"), pol(exclude_tags=("noise",)), origin)
    assert "tags" not in out and "tags_match" not in out
    assert out["tag_groups"] == [{"tags": ["project:x"], "match": "any"}, {"not": {"tags": ["noise"]}}]

test_exclusion_combines_with_inclusion = pytest.mark.parametrize("origin", ORIGINS)(test_exclusion_combines_with_inclusion)


def test_the_inclusion_match_mode_is_kept():
    out = rp.rewrite_kwargs(base(tags=["a", "b"], tags_match="all"), pol(exclude_tags=("n",)), rp.ORIGIN_AUTO)
    assert out["tag_groups"][0] == {"tags": ["a", "b"], "match": "all"}


def test_the_inclusion_match_mode_defaults_to_any():
    out = rp.rewrite_kwargs(base(tags=["a"]), pol(exclude_tags=("n",)), rp.ORIGIN_TOOL)
    assert out["tag_groups"][0] == {"tags": ["a"], "match": "any"}


def test_tags_and_tag_groups_never_both_present():
    """Port of test_recall_tags_and_tag_groups_never_both_present: the four combinations that matter."""
    cases = [
        (base(), pol()),
        (base(tags=["project:x"], tags_match="any"), pol()),
        (base(), pol(exclude_tags=("noise",))),
        (base(tags=["project:x"], tags_match="any"), pol(exclude_tags=("noise",))),
    ]
    for kwargs, policy in cases:
        for origin in ORIGINS:
            out = rp.rewrite_kwargs(kwargs, policy, origin)
            assert not ("tags" in out and "tag_groups" in out), (kwargs, policy)


def test_inclusion_without_exclusion_keeps_the_stock_shape():
    """Port of test_recall_tags_alone_is_normalized_to_a_list, as far as the pure function can show it: a
    normalised inclusion list with no exclusion goes out as stock built it (the normalising is stock's)."""
    kwargs = base(tags=["project:x", "project:y"], tags_match="any")
    out = rp.rewrite_kwargs(kwargs, pol(), rp.ORIGIN_AUTO)
    assert out["tags"] == ["project:x", "project:y"] and out["tags_match"] == "any"
    assert "tag_groups" not in out


def test_the_input_is_never_mutated():
    kwargs = base(tags=["a"], tags_match="any")
    before = copy.deepcopy(kwargs)
    rp.rewrite_kwargs(kwargs, pol(exclude_tags=("n",)), rp.ORIGIN_AUTO)
    assert kwargs == before


def test_other_keys_survive_the_rewrite():
    out = rp.rewrite_kwargs(base(min_scores={"final": 0.9}), pol(exclude_tags=("n",)), rp.ORIGIN_TOOL)
    assert out["min_scores"] == {"final": 0.9}
    assert out["query"] == "q" and out["types"] == ["observation"] and out["max_tokens"] == 4096


def test_exclusion_list_is_a_fresh_list_not_the_policy_tuple():
    policy = pol(exclude_tags=("a", "b"))
    out = rp.rewrite_kwargs(base(), policy, rp.ORIGIN_AUTO)
    assert out["tag_groups"][0]["not"]["tags"] == ["a", "b"]
    assert isinstance(out["tag_groups"][0]["not"]["tags"], list)


# -- rewrite_kwargs: port of test_recall_scoping.py, tag-shape cases (min_scores is stock's own key) ----------


def test_min_scores_does_not_change_the_tag_filter_shape(tags, exclude, expected):
    def shape(out):
        return {k: v for k, v in out.items() if k in ("tags", "tags_match", "tag_groups")}

    plain = base(**({"tags": tags, "tags_match": "any"} if tags else {}))
    scored = {**plain, "min_scores": {"final": 0.2}}
    policy = pol(exclude_tags=exclude)
    assert shape(rp.rewrite_kwargs(plain, policy, rp.ORIGIN_AUTO)) == expected
    out = rp.rewrite_kwargs(scored, policy, rp.ORIGIN_AUTO)
    assert shape(out) == expected
    assert out["min_scores"] == {"final": 0.2}

test_min_scores_does_not_change_the_tag_filter_shape = pytest.mark.parametrize(
    "tags, exclude, expected",
    [
        ([], (), {}),
        (["a", "b"], (), {"tags": ["a", "b"], "tags_match": "any"}),
        ([], ("noise",), {"tag_groups": [{"not": {"tags": ["noise"]}}]}),
        (["a"], ("noise",), {"tag_groups": [{"tags": ["a"], "match": "any"}, {"not": {"tags": ["noise"]}}]}),
    ],
)(test_min_scores_does_not_change_the_tag_filter_shape)


def test_no_min_scores_key_is_added():
    out = rp.rewrite_kwargs(base(), pol(exclude_tags=("n",)), rp.ORIGIN_AUTO)
    assert "min_scores" not in out


# -- rewrite_kwargs: a tag_groups list built by stock is kept, and odd inputs ------------------------


def test_existing_tag_groups_are_kept():
    existing = [{"tags": ["topic:x"], "match": "any"}]
    out = rp.rewrite_kwargs(base(tag_groups=existing), pol(exclude_tags=("n",)), rp.ORIGIN_AUTO)
    assert out["tag_groups"] == [{"tags": ["topic:x"], "match": "any"}, {"not": {"tags": ["n"]}}]
    assert existing == [{"tags": ["topic:x"], "match": "any"}]  # the stock list itself is not extended


def test_existing_groups_inclusion_and_exclusion_in_order():
    kwargs = base(tag_groups=[{"tags": ["g"], "match": "any"}], tags=["a"], tags_match="all")
    out = rp.rewrite_kwargs(kwargs, pol(exclude_tags=("n",)), rp.ORIGIN_TOOL)
    assert out["tag_groups"] == [
        {"tags": ["g"], "match": "any"},
        {"tags": ["a"], "match": "all"},
        {"not": {"tags": ["n"]}},
    ]
    assert "tags" not in out and "tags_match" not in out


def test_existing_tag_groups_without_exclusion_are_untouched():
    kwargs = base(tag_groups=[{"tags": ["g"]}])
    assert rp.rewrite_kwargs(kwargs, pol(), rp.ORIGIN_AUTO) is kwargs


def test_odd_inclusion_shapes(tags, expected):
    out = rp.rewrite_kwargs(base(tags=tags, tags_match="any"), pol(exclude_tags=("n",)), rp.ORIGIN_AUTO)
    groups = out["tag_groups"]
    if expected is None:
        assert groups == [{"not": {"tags": ["n"]}}]
    else:
        assert groups[0] == {"tags": expected, "match": "any"}

test_odd_inclusion_shapes = pytest.mark.parametrize("tags, expected", [("solo", ["solo"]), (("a", "b"), ["a", "b"]), (None, None), (5, None), ([], None)])(test_odd_inclusion_shapes)


def test_policy_without_the_attribute_is_stock_parity():
    kwargs = base(tags=["a"])
    assert rp.rewrite_kwargs(kwargs, SimpleNamespace(), rp.ORIGIN_AUTO) is kwargs
    assert rp.rewrite_kwargs(kwargs, SimpleNamespace(exclude_tags=None), rp.ORIGIN_AUTO) is kwargs


tag_names = st.text(alphabet="abcxyz:_", min_size=1, max_size=6)


def check_never_both(tags, exclude, match, origin):
    kwargs = base(**({"tags": tags, "tags_match": match} if tags else {}))
    out = rp.rewrite_kwargs(kwargs, pol(exclude_tags=tuple(exclude)), origin)
    assert not ("tags" in out and "tag_groups" in out)
    if exclude:
        assert out["tag_groups"][-1] == {"not": {"tags": list(exclude)}}
        assert "tags_match" not in out
    else:
        assert out == kwargs


test_never_both_property = given(
    st.lists(tag_names, max_size=3),
    st.lists(tag_names, max_size=3),
    st.sampled_from(["any", "all", "any_strict"]),
    st.sampled_from(ORIGINS),
)(check_never_both)


# -- cap_results ----------------------------------------------------------------------------------


def test_cap_applies_on_the_auto_path():
    assert rp.cap_results([1, 2, 3, 4, 5], pol(max_results=3), rp.ORIGIN_AUTO) == [1, 2, 3]


def test_cap_never_applies_on_the_tool_path():
    items = [1, 2, 3, 4, 5]
    assert rp.cap_results(items, pol(max_results=3), rp.ORIGIN_TOOL) is items


def test_no_cap_is_unchanged(cap):
    items = [1, 2, 3]
    assert rp.cap_results(items, SimpleNamespace(max_results=cap), rp.ORIGIN_AUTO) is items

test_no_cap_is_unchanged = pytest.mark.parametrize("cap", [0, -1, None])(test_no_cap_is_unchanged)


def test_cap_larger_than_the_list_keeps_everything():
    assert rp.cap_results([1, 2], pol(max_results=9), rp.ORIGIN_AUTO) == [1, 2]


def test_cap_of_exactly_the_length():
    assert rp.cap_results([1, 2, 3], pol(max_results=3), rp.ORIGIN_AUTO) == [1, 2, 3]


def test_cap_one_and_empty_list():
    assert rp.cap_results([7, 8], pol(max_results=1), rp.ORIGIN_AUTO) == [7]
    assert rp.cap_results([], pol(max_results=3), rp.ORIGIN_AUTO) == []


def test_unknown_origin_is_not_capped():
    items = [1, 2, 3]
    assert rp.cap_results(items, pol(max_results=1), "other") is items


def test_policy_without_max_results_is_not_capped():
    items = [1, 2]
    assert rp.cap_results(items, SimpleNamespace(), rp.ORIGIN_AUTO) is items


def test_the_cap_comes_from_parsed_settings():
    policy = parse_house_settings({"recall_max_results": "2"})
    assert rp.cap_results(["a", "b", "c"], policy, rp.ORIGIN_AUTO) == ["a", "b"]


# -- compose_short_query --------------------------------------------------------------------------

SQ = pol(short_query_chars=60, short_query_context_chars=400)
FILL = ("lorem ipsum. " * 40).strip()  # spaces and dots break any 60-character base64 run


def shaped(tail, query):
    return rp.CTX_HEADER + tail + rp.CTX_SEP + query


def test_short_query_gets_the_context():
    assert compose("Yes please", "I can restart the service now.", SQ) == shaped(
        "I can restart the service now.", "Yes please"
    )


def test_only_the_tail_of_a_long_statement_is_used():
    prev = "x" * 1000 + " END OF STATEMENT"
    out = compose("ok", prev, pol(short_query_chars=60, short_query_context_chars=20))
    assert out == shaped(prev[-20:], "ok")


def test_long_query_is_unchanged():
    query = "q" * 60
    assert compose(query, "statement", SQ) is query
    assert compose("q" * 59, "statement", SQ) != "q" * 59


def test_length_uses_the_stripped_query():
    query = "  " + "q" * 58 + "  "  # 62 raw characters, 58 stripped: still short
    assert compose(query, "statement", SQ).startswith(rp.CTX_HEADER)


def test_rule_off_is_unchanged(policy):
    assert compose("ok", "statement", policy) == "ok"

test_rule_off_is_unchanged = pytest.mark.parametrize(
    "policy",
    [pol(), pol(short_query_chars=0, short_query_context_chars=400), pol(short_query_chars=60, short_query_context_chars=0)],
)(test_rule_off_is_unchanged)


def test_unusable_query_is_returned_as_is(query):
    assert compose(query, "statement", SQ) is query

test_unusable_query_is_returned_as_is = pytest.mark.parametrize("query", ["", "   ", None, 5, b"ok"])(test_unusable_query_is_returned_as_is)


def test_no_usable_statement_is_unchanged(prev):
    assert compose("ok", prev, SQ) == "ok"

test_no_usable_statement_is_unchanged = pytest.mark.parametrize("prev", ["", "   \n ", None, 5, "\x00\x01\x02"])(test_no_usable_statement_is_unchanged)


def test_control_characters_are_dropped_and_ends_stripped():
    out = compose("ok", "  hello\x00 wor\x1fld\x7f  ", SQ)
    assert out == shaped("hello world", "ok")


def test_newlines_and_tabs_inside_the_statement_survive():
    out = compose("ok", "line one\nline\ttwo", SQ)
    assert out == shaped("line one\nline\ttwo", "ok")


def test_room_limits_the_context_and_never_cuts_the_query():
    query = "ok"
    room = 100
    budget = len(rp.CTX_HEADER) + len(rp.CTX_SEP) + len(query) + room
    prev = FILL
    out = compose(query, prev, SQ, max_input_chars=budget)
    assert out == shaped(FILL[-room:], query)
    assert len(out) == budget


def test_room_larger_than_the_setting_keeps_the_setting():
    out = compose("ok", FILL, pol(short_query_chars=60, short_query_context_chars=30), 5000)
    assert out == shaped(FILL[-30:], "ok")


def test_a_negative_bound_leaves_no_room():
    assert compose("ok", FILL, SQ, max_input_chars=-5) == "ok"


def test_room_below_the_minimum_adds_nothing():
    query = "ok"
    budget = len(rp.CTX_HEADER) + len(rp.CTX_SEP) + len(query) + rp.MIN_ROOM - 1
    assert compose(query, FILL, SQ, max_input_chars=budget) == query


def test_room_exactly_the_minimum_adds_context():
    query = "ok"
    budget = len(rp.CTX_HEADER) + len(rp.CTX_SEP) + len(query) + rp.MIN_ROOM
    out = compose(query, FILL, SQ, max_input_chars=budget)
    assert out == shaped(FILL[-rp.MIN_ROOM:], query)


def test_no_bound_means_no_room_check(bound):
    out = compose("ok", FILL, SQ, max_input_chars=bound)
    assert out == shaped(FILL[-400:], "ok")

test_no_bound_means_no_room_check = pytest.mark.parametrize("bound", [0, None])(test_no_bound_means_no_room_check)


# -- credential cue -------------------------------------------------------------------------------

PEM_LINE = "-----" + "BEGIN " + "RSA " + "KEY" + "-----"
URL_USERINFO = "https://" + "someone" + ":" + "hunter2" + AT + "host.example/path"


def test_credential_cue_classes(text, cls):
    cue = rp.credential_cue(text)
    assert cue is not None and cue[0] == cls

test_credential_cue_classes = pytest.mark.parametrize(
    "text, cls",
    [
        ("my Password is", "word"),
        ("the passwd file", "word"),
        ("a passphrase here", "word"),
        ("the API key is", "word"),
        ("api_key", "word"),
        ("api-key", "word"),
        ("apikey", "word"),
        ("a private key", "word"),
        ("private_key", "word"),
        ("use a Bearer header", "word"),
        ("the credentials", "word"),
        ("your otp is 123456 now", "code"),
        ("your one-time code 12345678", "code"),
        ("verification: 654321", "code"),
        ("2fa 111222", "code"),
        ("123456 is your otp", "code"),
        ("987654 one time", "code"),
        ("A" * 64, "base64"),
        ("ab/+=" * 13, "base64"),
        ("intro\n" + PEM_LINE + "\nbody", "pem"),
        ("-----END PGP BLOCK-----", "pem"),
        ("connect to " + URL_USERINFO, "url"),
    ],
)(test_credential_cue_classes)


def test_credential_cue_negatives(text):
    assert rp.credential_cue(text) is None

test_credential_cue_negatives = pytest.mark.parametrize(
    "text",
    [
        "",
        "I can restart the service now.",
        "the code is 123456",  # the bare word code is not a cue
        "otp 12345",  # five digits
        "otp 123456789",  # nine digits
        "otp " + "x" * 50 + " 123456",  # digits more than 40 characters away
        "A" * 59,
        "https://host.example/path",
        "see the begin of the key chapter",  # not at a line start
        "ids 1234567 and 7654321",
    ],
)(test_credential_cue_negatives)


def test_cue_returns_the_first_matching_entry():
    assert rp.credential_cue("password and bearer") == ("word", "password")


def test_cue_with_an_empty_tuple_is_off():
    assert rp.credential_cue("password", ()) is None


def test_cue_accepts_custom_entries():
    assert rp.credential_cue("Hello", (("x", "hello"),)) == ("x", "hello")


def test_cue_blocks_the_context(prev):
    assert compose("ok", prev, SQ) == "ok"

test_cue_blocks_the_context = pytest.mark.parametrize(
    "prev",
    ["the password is hidden", "token otp 123456", "A" * 80, PEM_LINE, "see " + URL_USERINFO],
)(test_cue_blocks_the_context)


def test_cue_class_is_logged_but_never_the_text(caplog):
    with caplog.at_level(logging.DEBUG):
        compose("ok", "the password is zz-secret-zz", SQ)
    assert caplog.messages == ["Recall: short-query context skipped (credential cue: word)"]
    assert "zz-secret-zz" not in caplog.text
    assert "password" not in caplog.text.replace("credential cue", "")


def test_cue_just_before_the_cut_still_blocks():
    """The lookback: a cue word that sits right before the tail that would be sent must block."""
    ctx = 20
    prev = "password" + "." * 10 + "y" * ctx  # 'password' ends 10 characters before the tail
    assert compose("ok", prev, pol(short_query_chars=60, short_query_context_chars=ctx)) == "ok"


def test_cue_far_before_the_cut_does_not_block():
    ctx = 20
    prev = "password" + "." * 200 + "y" * ctx
    out = compose("ok", prev, pol(short_query_chars=60, short_query_context_chars=ctx))
    assert out == shaped("y" * ctx, "ok")


def test_cue_at_the_edge_of_the_lookback():
    ctx = 20
    window = ctx + rp.CUE_LOOKBACK
    inside = "password" + "." * (window - 8)  # starts exactly at the window edge
    outside = "z" + inside
    policy = pol(short_query_chars=60, short_query_context_chars=ctx)
    assert len(inside) == window
    assert compose("ok", inside, policy) == "ok"
    assert compose("ok", outside, policy) == "ok"  # the cue still sits inside the window
    longer = "password" + "." * (window - 7)  # the cue starts one character before the window
    assert compose("ok", longer, policy).startswith(rp.CTX_HEADER)


def test_missing_policy_attributes_turn_the_rule_off():
    assert compose("ok", FILL, SimpleNamespace()) == "ok"
    assert compose("ok", FILL, SimpleNamespace(short_query_chars=60)) == "ok"
    assert compose("ok", FILL, SimpleNamespace(short_query_context_chars=400)) == "ok"


def test_a_context_of_one_character():
    policy = pol(short_query_chars=60, short_query_context_chars=1)
    assert compose("ok", "abc", policy) == shaped("c", "ok")


def test_a_short_query_limit_of_one_changes_nothing():
    policy = pol(short_query_chars=1, short_query_context_chars=400)
    assert compose("ok", "abc", policy) == "ok"


def test_stock_tag_groups_do_not_leak_when_the_exclusion_is_empty_tuple():
    kwargs = base(tag_groups=[{"tags": ["g"]}])
    assert rp.rewrite_kwargs(kwargs, pol(exclude_tags=()), rp.ORIGIN_AUTO) is kwargs


# compose_short_query scrubs the statement itself; no redact callable, or a failing one, adds no context
def test_no_redact_callable_adds_no_context():
    query = "Yes please"
    assert rp.compose_short_query(query, "I can restart the service now.", SQ) is query


def test_redact_is_applied_before_the_statement_is_sent():
    out = rp.compose_short_query("yes", "the token TOKEN9 is set", SQ, 0, redact=lambda s: s.replace("TOKEN9", "[R]"))
    assert "[R]" in out and "TOKEN9" not in out
    assert out.endswith(rp.CTX_SEP + "yes")


def test_a_failing_redact_sends_the_query_and_logs_the_class_only(caplog):
    def boom(text):
        raise ValueError("zz-not-for-logs")

    with caplog.at_level(logging.DEBUG):
        assert rp.compose_short_query("yes", "statement", SQ, 0, redact=boom) == "yes"
    assert "ValueError" in caplog.text and "zz-not-for-logs" not in caplog.text


def test_a_redact_that_returns_no_text_sends_the_query():
    assert rp.compose_short_query("yes", "statement", SQ, 0, redact=lambda s: None) == "yes"
