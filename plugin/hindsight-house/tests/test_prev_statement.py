"""prev_statement against a synthetic state.db built in tmp_path (schema inferred from the SQL columns; no real
state.db is ever opened or copied)."""

import hashlib
import logging
import sqlite3
import time
from pathlib import Path

import pytest

import prev_statement as ps

SCHEMA = (
    "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, "
    "active INTEGER DEFAULT 1, _compressed_summary INTEGER DEFAULT 0, display_kind TEXT)"
)


def make_db(home, rows, schema=SCHEMA):
    home.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(home / "state.db")
    con.execute(schema)
    for row in rows:
        con.execute(
            "INSERT INTO messages (session_id, role, content, active, _compressed_summary, display_kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row.get("s", "S1"), row.get("role", "assistant"), row.get("content", "text"), row.get("active", 1),
             row.get("summary", 0), row.get("kind")),
        )
    con.commit()
    con.close()
    return home / "state.db"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_newest_usable_assistant_row_wins(tmp_path):
    make_db(tmp_path, [{"content": "old"}, {"content": "newer"}, {"content": "newest"}])
    assert ps.previous_assistant_statement(tmp_path, "S1") == "newest"


def test_rows_are_returned_as_stored_not_stripped(tmp_path):
    make_db(tmp_path, [{"content": "  padded  \n"}])
    assert ps.previous_assistant_statement(tmp_path, "S1") == "  padded  \n"


def test_unusable_newer_rows_are_skipped(tmp_path, skipped):
    make_db(tmp_path, [{"content": "usable"}, {"content": "newer but unusable", **skipped}])
    assert ps.previous_assistant_statement(tmp_path, "S1") == "usable"

test_unusable_newer_rows_are_skipped = pytest.mark.parametrize(
    "skipped",
    [
        {"role": "user"},
        {"role": "tool"},
        {"role": "system"},
        {"active": 0},
        {"summary": 1},
        {"kind": "failed_turn"},
        {"content": None},
        {"content": ""},
        {"content": "      "},
        {"s": "OTHER"},
    ],
)(test_unusable_newer_rows_are_skipped)


def test_blank_text_with_newline_or_tab_is_skipped_by_the_sql(tmp_path):
    """TRIM() strips space, tab, LF, VT, FF and CR, so a blank row no longer hides an older one.
    The earlier helper returned the blank row here (its TRIM stripped spaces only); this one differs on purpose."""
    make_db(tmp_path, [{"content": "usable"}, {"content": "  \n\t "}])
    assert ps.previous_assistant_statement(tmp_path, "S1") == "usable"


def test_only_unusable_rows_give_empty(tmp_path):
    make_db(tmp_path, [{"role": "user"}, {"active": 0}, {"content": " "}])
    assert ps.previous_assistant_statement(tmp_path, "S1") == ""


def test_another_display_kind_is_usable(tmp_path):
    make_db(tmp_path, [{"content": "shown", "kind": "normal"}])
    assert ps.previous_assistant_statement(tmp_path, "S1") == "shown"


def test_sessions_are_separate(tmp_path):
    make_db(tmp_path, [{"s": "S1", "content": "one"}, {"s": "S2", "content": "two"}])
    assert ps.previous_assistant_statement(tmp_path, "S1") == "one"
    assert ps.previous_assistant_statement(tmp_path, "S2") == "two"
    assert ps.previous_assistant_statement(tmp_path, "S3") == ""


def test_bad_session_id_gives_empty(tmp_path, session_id):
    make_db(tmp_path, [{"content": "text"}])
    assert ps.previous_assistant_statement(tmp_path, session_id) == ""

test_bad_session_id_gives_empty = pytest.mark.parametrize("session_id", ["", None, 5, b"S1", ["S1"]])(test_bad_session_id_gives_empty)


def test_no_home_gives_empty(home):
    assert ps.previous_assistant_statement(home, "S1") == ""

test_no_home_gives_empty = pytest.mark.parametrize("home", ["", None])(test_no_home_gives_empty)


def test_missing_file_gives_empty_and_creates_nothing(tmp_path):
    assert ps.previous_assistant_statement(tmp_path, "S1") == ""
    assert list(tmp_path.iterdir()) == []


def test_missing_home_directory_gives_empty(tmp_path):
    assert ps.previous_assistant_statement(tmp_path / "nope", "S1") == ""


def test_a_directory_named_state_db_gives_empty(tmp_path):
    (tmp_path / "state.db").mkdir()
    assert ps.previous_assistant_statement(tmp_path, "S1") == ""


def test_not_a_database_gives_empty(tmp_path):
    (tmp_path / "state.db").write_bytes(b"this is not sqlite" * 50)
    assert ps.previous_assistant_statement(tmp_path, "S1") == ""


def test_empty_database_file_gives_empty(tmp_path):
    (tmp_path / "state.db").write_bytes(b"")
    assert ps.previous_assistant_statement(tmp_path, "S1") == ""


def test_schema_without_the_columns_gives_empty_and_logs_the_class_only(tmp_path, caplog):
    make_db(tmp_path, [], schema="CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT)")
    with caplog.at_level(logging.DEBUG):
        assert ps.previous_assistant_statement(tmp_path, "S1") == ""
    assert "OperationalError" in caplog.text


def test_no_messages_table_gives_empty(tmp_path):
    make_db(tmp_path, [], schema="CREATE TABLE other (x INTEGER)")
    assert ps.previous_assistant_statement(tmp_path, "S1") == ""


def test_the_database_is_never_written(tmp_path):
    path = make_db(tmp_path, [{"content": "text"}])
    before = digest(path)
    stat = path.stat()
    ps.previous_assistant_statement(tmp_path, "S1")
    ps.previous_assistant_statement(tmp_path, "nothing")
    assert digest(path) == before
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.db"]


def test_a_read_only_directory_still_reads(tmp_path):
    path = make_db(tmp_path, [{"content": "text"}])
    tmp_path.chmod(0o500)
    try:
        assert ps.previous_assistant_statement(tmp_path, "S1") == "text"
    finally:
        tmp_path.chmod(0o700)
    assert path.exists()


def test_special_characters_in_the_path_are_encoded(tmp_path, name):
    home = tmp_path / name
    make_db(home, [{"content": "found"}])
    assert ps.previous_assistant_statement(home, "S1") == "found"

test_special_characters_in_the_path_are_encoded = pytest.mark.parametrize("name", ["with space", "q?mark", "hash#tag", "per%cent", "uni\u00e9"])(test_special_characters_in_the_path_are_encoded)


def test_a_query_in_the_path_is_not_taken_as_an_option(tmp_path):
    """A '?' in the directory name must not be read as the start of the URI query (mode=ro stays in force)."""
    home = tmp_path / "x?mode=rwc"
    make_db(home, [{"content": "found"}])
    assert ps.previous_assistant_statement(home, "S1") == "found"


def test_the_session_id_is_a_bound_parameter(tmp_path, hostile):
    path = make_db(tmp_path, [{"s": "S1", "content": "secret-ish"}, {"s": "S2", "content": "other"}])
    before = digest(path)
    assert ps.previous_assistant_statement(tmp_path, hostile) == ""
    assert digest(path) == before
    assert ps.previous_assistant_statement(tmp_path, "S1") == "secret-ish"

test_the_session_id_is_a_bound_parameter = pytest.mark.parametrize(
    "hostile",
    ["S1' OR '1'='1", "S1'; DROP TABLE messages; --", "' UNION SELECT 'x' --", 'S1" OR "1"="1', "%", "S1\x00", "S%"],
)(test_the_session_id_is_a_bound_parameter)


def test_a_session_id_that_looks_like_sql_matches_only_itself(tmp_path):
    odd = "S1' OR '1'='1"
    make_db(tmp_path, [{"s": odd, "content": "odd"}, {"s": "S1", "content": "plain"}])
    assert ps.previous_assistant_statement(tmp_path, odd) == "odd"


def test_a_locked_database_fails_open_within_the_timeout(tmp_path):
    path = make_db(tmp_path, [{"content": "text"}])
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        started = time.monotonic()
        assert ps.previous_assistant_statement(tmp_path, "S1") == ""
        assert time.monotonic() - started < 2.0
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert ps.previous_assistant_statement(tmp_path, "S1") == "text"


def test_the_timeout_is_passed_to_the_connection(tmp_path, monkeypatch):
    make_db(tmp_path, [{"content": "text"}])
    seen = {}
    real = sqlite3.connect

    def spy(*args, **kwargs):
        seen.update(kwargs)
        seen["uri_text"] = args[0]
        return real(*args, **kwargs)

    monkeypatch.setattr(ps.sqlite3, "connect", spy)
    ps.previous_assistant_statement(tmp_path, "S1")
    assert seen["timeout"] == 0.2 == ps.BUSY_TIMEOUT_S
    assert seen["uri"] is True
    assert seen["uri_text"].startswith("file:///") and seen["uri_text"].endswith("/state.db?mode=ro")
    seen.clear()
    ps.previous_assistant_statement(tmp_path, "S1", timeout=1.5)
    assert seen["timeout"] == 1.5


def test_the_connection_is_closed(tmp_path, monkeypatch):
    make_db(tmp_path, [{"content": "text"}])
    closed = []
    real = sqlite3.connect

    class Wrapper:
        def __init__(self, con):
            self.con = con

        def execute(self, *args):
            return self.con.execute(*args)

        def close(self):
            closed.append(True)
            self.con.close()

    monkeypatch.setattr(ps.sqlite3, "connect", lambda *a, **k: Wrapper(real(*a, **k)))
    assert ps.previous_assistant_statement(tmp_path, "S1") == "text"
    assert closed == [True]


def test_a_failing_query_still_closes_the_connection(tmp_path, monkeypatch):
    make_db(tmp_path, [{"content": "text"}])
    closed = []

    class Broken:
        def execute(self, *args):
            raise sqlite3.OperationalError("boom")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(ps.sqlite3, "connect", lambda *a, **k: Broken())
    assert ps.previous_assistant_statement(tmp_path, "S1") == ""
    assert closed == [True]


def test_a_non_text_content_value_gives_empty(tmp_path):
    path = make_db(tmp_path, [])
    con = sqlite3.connect(path)
    con.execute("INSERT INTO messages (session_id, role, content) VALUES ('S1', 'assistant', x'00ff41')")
    con.commit()
    con.close()
    assert ps.previous_assistant_statement(tmp_path, "S1") == ""


def test_a_failure_logs_only_the_exception_class(tmp_path, caplog):
    (tmp_path / "state.db").write_bytes(b"x" * 200)
    with caplog.at_level(logging.DEBUG):
        ps.previous_assistant_statement(tmp_path, "S-secret-id")
    assert "S-secret-id" not in caplog.text
    assert "DatabaseError" in caplog.text


def test_a_str_path_works_like_a_path(tmp_path):
    make_db(tmp_path, [{"content": "text"}])
    assert ps.previous_assistant_statement(str(tmp_path), "S1") == "text"


# a row that is blank after tab, LF, VT, FF or CR no longer hides an older usable row
def make_blank_rows_db(path, contents):
    con = sqlite3.connect(path / "state.db")
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, "
                "content TEXT, active INTEGER DEFAULT 1, _compressed_summary INTEGER DEFAULT 0, display_kind TEXT)")
    con.executemany("INSERT INTO messages (session_id, role, content) VALUES ('S1', 'assistant', ?)",
                    [(c,) for c in contents])
    con.commit()
    con.close()


def test_blank_rows_of_any_ascii_whitespace_are_skipped(tmp_path, blank):
    make_blank_rows_db(tmp_path, ["usable", blank])
    assert ps.previous_assistant_statement(tmp_path, "S1") == "usable"


test_blank_rows_of_any_ascii_whitespace_are_skipped = pytest.mark.parametrize(
    "blank", ["\r", "\x0b\x0c", " \t\n\r ", "\n"])(test_blank_rows_of_any_ascii_whitespace_are_skipped)


def test_text_with_surrounding_newlines_is_still_returned_as_stored(tmp_path):
    make_blank_rows_db(tmp_path, ["older", "\nnewest\n"])
    assert ps.previous_assistant_statement(tmp_path, "S1") == "\nnewest\n"


# a relative home never reads the working folder; an int session id does not match a text id
def make_one_row_db(home, session="S1", content="text"):
    home.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(home / "state.db")
    con.execute(SCHEMA)
    con.execute("INSERT INTO messages (session_id, role, content) VALUES (?, 'assistant', ?)", (session, content))
    con.commit()
    con.close()


def test_a_relative_home_never_reads_the_working_folder(tmp_path, monkeypatch, home):
    make_one_row_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert ps.previous_assistant_statement(home, "S1") == ""


test_a_relative_home_never_reads_the_working_folder = pytest.mark.parametrize(
    "home", [Path(""), Path("."), ".", "./", ""])(test_a_relative_home_never_reads_the_working_folder)


def test_an_absolute_home_still_reads(tmp_path, monkeypatch):
    make_one_row_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert ps.previous_assistant_statement(tmp_path, "S1") == "text"
    assert ps.previous_assistant_statement(str(tmp_path), "S1") == "text"


def test_an_int_session_id_does_not_match_a_text_id(tmp_path):
    make_one_row_db(tmp_path, session="5")
    assert ps.previous_assistant_statement(tmp_path, "5") == "text"
    assert ps.previous_assistant_statement(tmp_path, 5) == ""
