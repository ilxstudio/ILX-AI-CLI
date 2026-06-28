"""Crash history database — records /run process crashes to SQLite.

Each entry stores: timestamp, exit_code, traceback snippet, command, and a
signature hash (for grouping repeated crashes by call site).

Also stores classified LLM API errors (from error_classifier) in a separate
``api_errors`` table for display via /errors.
"""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

_DB_PATH = Path.home() / ".ilx_cli" / "crashes.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS crashes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    command   TEXT NOT NULL,
    exit_code INTEGER NOT NULL,
    sig       TEXT NOT NULL,
    tb        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sig ON crashes(sig);
CREATE INDEX IF NOT EXISTS idx_ts  ON crashes(ts);
CREATE TABLE IF NOT EXISTS api_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    error_class TEXT NOT NULL,
    message     TEXT NOT NULL,
    suggestion  TEXT NOT NULL,
    context     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ae_ts    ON api_errors(ts);
CREATE INDEX IF NOT EXISTS idx_ae_class ON api_errors(error_class);
"""


@contextmanager
def _conn():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH))
    try:
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _signature(tb: str) -> str:
    """Hash the first 3 non-empty traceback lines as a crash group key."""
    lines = [ln.strip() for ln in tb.splitlines() if ln.strip()][:3]
    return hashlib.sha1("\n".join(lines).encode()).hexdigest()[:12]


def record(command: str, exit_code: int, stderr_tail: str) -> None:
    """Record a crash. *stderr_tail* is the last ~2 KB of stderr."""
    ts  = datetime.now(UTC).isoformat()
    sig = _signature(stderr_tail)
    with _conn() as con:
        con.execute(
            "INSERT INTO crashes(ts, command, exit_code, sig, tb) VALUES (?,?,?,?,?)",
            (ts, command, exit_code, sig, stderr_tail[:4096]),
        )


def list_crashes(limit: int = 20) -> list[dict]:
    """Return the most recent crashes."""
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT id, ts, command, exit_code, sig, tb FROM crashes "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r[0], "ts": r[1], "command": r[2],
             "exit_code": r[3], "sig": r[4], "tb": r[5]}
            for r in rows
        ]
    except sqlite3.Error:
        return []


def group_summary() -> list[dict]:
    """Return crash counts grouped by signature."""
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT sig, command, COUNT(*) as cnt, MIN(ts) as first, MAX(ts) as last "
                "FROM crashes GROUP BY sig ORDER BY cnt DESC LIMIT 20"
            ).fetchall()
        return [
            {"sig": r[0], "command": r[1], "count": r[2],
             "first": r[3], "last": r[4]}
            for r in rows
        ]
    except sqlite3.Error:
        return []


def clear_crashes() -> int:
    """Delete all crash records. Returns count deleted."""
    try:
        with _conn() as con:
            cur = con.execute("DELETE FROM crashes")
            return cur.rowcount
    except sqlite3.Error:
        return 0


# ── Classified API-error tracking ─────────────────────────────────────────────

def log_classified_error(classified: object, context: str = "") -> None:
    """Store a ClassifiedError to the ``api_errors`` table.

    *classified* is a ``ClassifiedError`` instance from
    ``app.core.error_classifier``.  Accepts ``object`` type hint to avoid a
    circular import at module load time.
    """
    try:
        ts          = datetime.now(UTC).isoformat()
        error_class = classified.error_class.name          # type: ignore[union-attr]
        message     = classified.message                   # type: ignore[union-attr]
        suggestion  = classified.suggestion                # type: ignore[union-attr]
        with _conn() as con:
            con.execute(
                "INSERT INTO api_errors(ts, error_class, message, suggestion, context) "
                "VALUES (?,?,?,?,?)",
                (ts, error_class, message[:2048], suggestion[:1024], context[:512]),
            )
    except Exception:
        pass  # Never let error logging crash the caller


def list_api_errors(limit: int = 50) -> list[dict]:
    """Return recent classified API errors, newest first."""
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT id, ts, error_class, message, suggestion, context "
                "FROM api_errors ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0], "ts": r[1], "error_class": r[2],
                "message": r[3], "suggestion": r[4], "context": r[5],
            }
            for r in rows
        ]
    except sqlite3.Error:
        return []


def api_error_stats() -> list[dict]:
    """Return counts of classified API errors grouped by error_class."""
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT error_class, COUNT(*) as cnt, MAX(ts) as last "
                "FROM api_errors GROUP BY error_class ORDER BY cnt DESC"
            ).fetchall()
        return [{"error_class": r[0], "count": r[1], "last": r[2]} for r in rows]
    except sqlite3.Error:
        return []


def clear_api_errors() -> int:
    """Delete all classified API error records. Returns count deleted."""
    try:
        with _conn() as con:
            cur = con.execute("DELETE FROM api_errors")
            return cur.rowcount
    except sqlite3.Error:
        return 0
