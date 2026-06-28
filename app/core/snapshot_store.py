"""Per-session file snapshot store for rollback support.

Automatically captures file content before every agent write.
Snapshots are stored in memory (stack per file) during the session.
On session exit they are discarded — no persistent disk clutter.
A JSON index is written to ~/.ilx_cli/snapshots/<sid>/ for debugging
and cross-process recovery, but the primary source of truth is in-memory.

MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING


@dataclass
class Snapshot:
    path: str       # absolute path to the file
    content: str    # file content at time of snapshot
    ts: str         # ISO-8601 timestamp
    run_id: str = ""  # agent run_id that triggered this write
    label: str = ""   # optional human label


class SnapshotStore:
    """Thread-safe per-session stack of file snapshots.

    Each file gets an independent stack. /rollback pops one entry.
    The stack bottom is always the pre-session original.
    """

    _MAX_PER_FILE = 20  # max snapshots kept per file

    def __init__(self, sid: str = "") -> None:
        self._sid = sid
        self._stacks: dict[str, list[Snapshot]] = {}  # path -> stack (oldest first)
        self._lock = threading.Lock()
        # Optional disk persistence for debugging (non-blocking)
        self._disk_dir: Path | None = None
        if sid:
            self._disk_dir = Path.home() / ".ilx_cli" / "snapshots" / sid

    def save(
        self,
        path: str,
        content: str,
        run_id: str = "",
        label: str = "",
    ) -> Snapshot:
        """Push a snapshot onto the stack for this file.

        Call BEFORE the file write so content is the pre-write state.
        """
        snap = Snapshot(
            path=path,
            content=content,
            ts=datetime.now(timezone.utc).isoformat(),
            run_id=run_id,
            label=label,
        )
        with self._lock:
            stack = self._stacks.setdefault(path, [])
            stack.append(snap)
            # Trim to max
            if len(stack) > self._MAX_PER_FILE:
                self._stacks[path] = stack[-self._MAX_PER_FILE :]
        self._persist_async(path, snap)
        return snap

    def pop(self, path: str) -> Snapshot | None:
        """Pop the most recent snapshot for a file (for rollback).

        Returns None if no snapshots exist for this file.
        Keeps at least 1 snapshot (the original) — never pops the bottom.
        """
        with self._lock:
            stack = self._stacks.get(path, [])
            if len(stack) <= 1:
                # Return the bottom (original) without removing it
                return stack[0] if stack else None
            return stack.pop()

    def peek(self, path: str) -> Snapshot | None:
        """Return the most recent snapshot without removing it."""
        with self._lock:
            stack = self._stacks.get(path, [])
            return stack[-1] if stack else None

    def original(self, path: str) -> Snapshot | None:
        """Return the oldest snapshot (pre-session state)."""
        with self._lock:
            stack = self._stacks.get(path, [])
            return stack[0] if stack else None

    def depth(self, path: str) -> int:
        """Number of snapshots available for a file."""
        with self._lock:
            return len(self._stacks.get(path, []))

    def all_paths(self) -> list[str]:
        """All file paths that have at least one snapshot."""
        with self._lock:
            return [p for p, s in self._stacks.items() if s]

    def clear(self) -> None:
        """Clear all snapshots (called on session exit)."""
        with self._lock:
            self._stacks.clear()
        # Remove disk snapshots directory
        if self._disk_dir and self._disk_dir.exists():
            try:
                import shutil
                shutil.rmtree(self._disk_dir, ignore_errors=True)
            except Exception:
                pass

    def _persist_async(self, path: str, snap: Snapshot) -> None:
        """Write snapshot index entry to disk in a background thread (best-effort)."""
        if not self._disk_dir:
            return

        def _write() -> None:
            try:
                self._disk_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
                import hashlib
                key = hashlib.sha1(path.encode()).hexdigest()[:12]
                index_path = self._disk_dir / f"{key}.jsonl"  # type: ignore[operator]
                entry = (
                    json.dumps(
                        {
                            "path": snap.path,
                            "ts": snap.ts,
                            "run_id": snap.run_id,
                            "label": snap.label,
                            "bytes": len(snap.content.encode()),
                            # content NOT written to disk index (could be large)
                        }
                    )
                    + "\n"
                )
                with open(index_path, "a", encoding="utf-8") as f:
                    f.write(entry)
            except Exception:
                pass

        threading.Thread(target=_write, daemon=True).start()


# ---------------------------------------------------------------------------
# Module-level singleton — initialized by init_snapshot_store()
# ---------------------------------------------------------------------------

_store: SnapshotStore | None = None
_store_lock = threading.Lock()


def init_snapshot_store(sid: str = "") -> SnapshotStore:
    """Initialize the module-level SnapshotStore. Call once at startup."""
    global _store
    with _store_lock:
        _store = SnapshotStore(sid=sid)
    return _store


def get_store() -> SnapshotStore:
    """Return the active SnapshotStore, creating a default one if needed."""
    global _store
    with _store_lock:
        if _store is None:
            _store = SnapshotStore()
        return _store
