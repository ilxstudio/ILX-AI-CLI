"""Persistent project memory — survives session restarts."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("ilx_cli.project_memory")

_MEM_DIR = Path.home() / ".ilx_cli" / "memory"

# schema for the three tables we need — runs at connect time via executescript
_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'note',
    key       TEXT NOT NULL,
    value     TEXT NOT NULL,
    session   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS fixes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    file_path TEXT NOT NULL,
    problem   TEXT NOT NULL,
    solution  TEXT NOT NULL,
    outcome   TEXT NOT NULL DEFAULT 'success',
    session   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS symbols (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'function',
    signature TEXT NOT NULL DEFAULT '',
    updated   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_symbols ON symbols (file_path, name);
CREATE INDEX IF NOT EXISTS ix_facts_key ON facts (key);
CREATE INDEX IF NOT EXISTS ix_fixes_file ON fixes (file_path);
"""


# hash the workspace path so each project gets its own db file
def _db_path(workspace: str) -> Path:
    h = hashlib.sha256(workspace.encode()).hexdigest()[:16]
    return _MEM_DIR / f"{h}.db"


@dataclass
class MemoryFact:
    key:     str
    value:   str
    kind:    str = "note"
    ts:      str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session: str = ""


@dataclass
class FixRecord:
    file_path: str
    problem:   str
    solution:  str
    outcome:   str = "success"
    ts:        str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session:   str = ""


@dataclass
class SymbolRecord:
    file_path: str
    name:      str
    kind:      str = "function"
    signature: str = ""


class ProjectMemory:

    def __init__(self, workspace: str, session_id: str = "") -> None:
        self._workspace = workspace
        self._session = session_id
        _MEM_DIR.mkdir(parents=True, exist_ok=True)
        self._db = _db_path(workspace)
        self._lock = threading.Lock()
        self._connect()

    # ── connection ─────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        self._conn = sqlite3.connect(str(self._db), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # single place for all db writes so we don't sprinkle try/except everywhere
    def _exec(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                cur = self._conn.execute(sql, params)
                self._conn.commit()
                return cur.fetchall() if cur.description else []
            except sqlite3.Error as exc:
                _log.debug("project_memory db error: %s", exc)
                return []

    # ── facts ──────────────────────────────────────────────────────────────────

    def remember(self, key: str, value: str, kind: str = "note") -> None:
        """Store or update a named fact."""
        ts = datetime.now(timezone.utc).isoformat()
        self._exec(
            "INSERT INTO facts (ts, kind, key, value, session) VALUES (?, ?, ?, ?, ?)",
            (ts, kind, key, value, self._session),
        )

    def recall(self, key: str) -> list[MemoryFact]:
        """Return all values stored for a key, newest first."""
        rows = self._exec(
            "SELECT ts, kind, key, value, session FROM facts WHERE key = ? ORDER BY id DESC LIMIT 20",
            (key,),
        )
        return [MemoryFact(r["key"], r["value"], r["kind"], r["ts"], r["session"]) for r in rows]

    def search_facts(self, query: str, limit: int = 10) -> list[MemoryFact]:
        """Full-text search over fact keys and values (case-insensitive LIKE)."""
        pat = f"%{query}%"
        rows = self._exec(
            "SELECT ts, kind, key, value, session FROM facts "
            "WHERE key LIKE ? OR value LIKE ? ORDER BY id DESC LIMIT ?",
            (pat, pat, limit),
        )
        return [MemoryFact(r["key"], r["value"], r["kind"], r["ts"], r["session"]) for r in rows]

    def forget(self, key: str) -> int:
        """Delete all facts with the given key. Returns rows deleted."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM facts WHERE key = ?", (key,))
            self._conn.commit()
            return cur.rowcount

    def all_facts(self, limit: int = 50) -> list[MemoryFact]:
        rows = self._exec(
            "SELECT ts, kind, key, value, session FROM facts ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [MemoryFact(r["key"], r["value"], r["kind"], r["ts"], r["session"]) for r in rows]

    # ── fixes ──────────────────────────────────────────────────────────────────

    def record_fix(self, file_path: str, problem: str, solution: str,
                   outcome: str = "success") -> None:
        ts = datetime.now(timezone.utc).isoformat()
        self._exec(
            "INSERT INTO fixes (ts, file_path, problem, solution, outcome, session) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, file_path, problem, solution, outcome, self._session),
        )

    def recent_fixes(self, file_path: str | None = None, limit: int = 10) -> list[FixRecord]:
        if file_path:
            rows = self._exec(
                "SELECT ts, file_path, problem, solution, outcome, session FROM fixes "
                "WHERE file_path = ? ORDER BY id DESC LIMIT ?",
                (file_path, limit),
            )
        else:
            rows = self._exec(
                "SELECT ts, file_path, problem, solution, outcome, session FROM fixes "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return [FixRecord(r["file_path"], r["problem"], r["solution"], r["outcome"], r["ts"], r["session"]) for r in rows]

    # ── symbols ────────────────────────────────────────────────────────────────

    def index_symbols(self, symbols: list[SymbolRecord]) -> None:
        """Bulk-upsert symbol records."""
        ts = datetime.now(timezone.utc).isoformat()
        with self._lock:
            try:
                self._conn.executemany(
                    "INSERT INTO symbols (file_path, name, kind, signature, updated) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(file_path, name) DO UPDATE SET kind=excluded.kind, "
                    "signature=excluded.signature, updated=excluded.updated",
                    [(s.file_path, s.name, s.kind, s.signature, ts) for s in symbols],
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                _log.debug("symbol upsert error: %s", exc)

    def search_symbols(self, query: str, limit: int = 10) -> list[SymbolRecord]:
        pat = f"%{query}%"
        rows = self._exec(
            "SELECT file_path, name, kind, signature FROM symbols "
            "WHERE name LIKE ? OR signature LIKE ? LIMIT ?",
            (pat, pat, limit),
        )
        return [SymbolRecord(r["file_path"], r["name"], r["kind"], r["signature"]) for r in rows]

    # ── prompt helpers ─────────────────────────────────────────────────────────

    def context_block(self, max_chars: int = 1200) -> str:
        """Return a compact memory summary for injection into the system prompt."""
        facts = self.all_facts(limit=15)
        fixes = self.recent_fixes(limit=5)
        if not facts and not fixes:
            return ""
        lines: list[str] = ["[Project memory]"]
        remaining = max_chars - 20
        for f in facts:
            line = f"  {f.kind}: {f.key} = {f.value[:120]}"
            if remaining - len(line) < 0:
                break
            lines.append(line)
            remaining -= len(line)
        if fixes and remaining > 100:
            lines.append("  Recent fixes:")
            for fx in fixes:
                line = f"    {fx.file_path}: {fx.problem[:60]} → {fx.solution[:60]}"
                if remaining - len(line) < 0:
                    break
                lines.append(line)
                remaining -= len(line)
        lines.append("[End project memory]")
        return "\n".join(lines)

    # ── stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        rows = self._exec("SELECT COUNT(*) AS n FROM facts")
        n_facts = rows[0]["n"] if rows else 0
        rows = self._exec("SELECT COUNT(*) AS n FROM fixes")
        n_fixes = rows[0]["n"] if rows else 0
        rows = self._exec("SELECT COUNT(*) AS n FROM symbols")
        n_symbols = rows[0]["n"] if rows else 0
        size = self._db.stat().st_size if self._db.exists() else 0
        return {
            "facts": n_facts,
            "fixes": n_fixes,
            "symbols": n_symbols,
            "db_bytes": size,
            "db_path": str(self._db),
            "workspace": self._workspace,
        }

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# one instance per workspace path — avoids opening the same db file twice
# ---------------------------------------------------------------------------

_INSTANCES: dict[str, ProjectMemory] = {}
_INST_LOCK = threading.Lock()


def get_memory(workspace: str, session_id: str = "") -> ProjectMemory:
    """Return (or create) the ProjectMemory instance for *workspace*."""
    with _INST_LOCK:
        if workspace not in _INSTANCES:
            _INSTANCES[workspace] = ProjectMemory(workspace, session_id)
        return _INSTANCES[workspace]


def close_all() -> None:
    with _INST_LOCK:
        for mem in _INSTANCES.values():
            mem.close()
        _INSTANCES.clear()
