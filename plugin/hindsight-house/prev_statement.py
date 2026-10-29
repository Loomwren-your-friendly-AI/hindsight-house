"""Previous assistant statement for the short-query context: a read-only lookup in state.db.

Port of the earlier ``_previous_assistant_statement``. Standard library only, no import-time work.
The database is opened read-only through a file: URI, the SQL takes the session id as a bound parameter, and the
busy wait is 0.2 s. Fail open: any failure returns "" and the caller sends the query as it is. The caller must
scrub the returned text (Hermes' egress redaction) before it goes anywhere (see recall_policy.compose_short_query).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__.rpartition(".")[0] or __name__)  # same rule as stock settings.py

BUSY_TIMEOUT_S = 0.2  # the earlier helper waited 0.25 s

_SQL = (
    "SELECT content FROM messages "
    "WHERE session_id = ? AND role = 'assistant' AND active = 1 "
    "AND _compressed_summary = 0 AND COALESCE(display_kind, '') <> 'failed_turn' "
    "AND content IS NOT NULL AND TRIM(content, ' ' || char(9, 10, 11, 12, 13)) <> '' "  # a blank row after trimming is skipped
    "ORDER BY id DESC LIMIT 1"
)


def previous_assistant_statement(hermes_home: Any, session_id: Any, timeout: float = BUSY_TIMEOUT_S) -> str:
    """The newest usable assistant message of *session_id* in ``<hermes_home>/state.db``, or "".

    Usable = role assistant, active, not a compression summary, not a failed turn, not empty or blank.
    Never writes: the connection is read-only. Never raises for a missing file, a locked or broken database or a
    schema that differs.
    """
    if not (isinstance(session_id, str) and session_id and hermes_home):
        return ""
    try:
        home = Path(hermes_home)
        if not home.is_absolute():  # a relative or empty Path would read a state.db in the working folder
            return ""
        db_path = (home / "state.db").resolve()
        if not db_path.is_file():  # mode=ro would fail too; this keeps the log quiet for a fresh install
            return ""
        uri = f"{db_path.as_uri()}?mode=ro"  # as_uri() percent-encodes a path that holds ? or #
        with closing(sqlite3.connect(uri, uri=True, timeout=timeout)) as con:
            row = con.execute(_SQL, (session_id,)).fetchone()
    except Exception as exc:  # fail open, whatever the cause
        logger.debug("Recall: previous assistant statement unavailable (%s)", type(exc).__name__)
        return ""
    return row[0] if row and isinstance(row[0], str) else ""
