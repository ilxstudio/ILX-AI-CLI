"""Rollback commands — /rollback and /checkpoint.

/rollback <file>       Restore file to its pre-write snapshot (pop the stack)
/rollback list         Show all files with available snapshots this session
/rollback diff <file>  Show what changed without restoring
/rollback all          Restore all modified files (with confirmation)

MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.core.snapshot_store import get_store
from cli.display import DIM, GREEN, RED, RESET, YELLOW
from cli.display_compat import out_error

if TYPE_CHECKING:
    from app.core.config import AppConfig


# ---------------------------------------------------------------------------
# Path resolution helper
# ---------------------------------------------------------------------------

def _resolve_path(arg: str, cfg: AppConfig) -> str | None:
    """Try absolute, then relative to working_folder. Return None if not found."""
    p = Path(arg)
    if p.is_absolute() and p.exists():
        return str(p)
    wf = Path(getattr(cfg, "working_folder", ".") or ".")
    candidate = wf / arg
    if candidate.exists():
        return str(candidate)
    # Try matching just the filename against known snapshot paths
    store = get_store()
    arg_name = Path(arg).name
    for snap_path in store.all_paths():
        if Path(snap_path).name == arg_name:
            return snap_path
    return None


# ---------------------------------------------------------------------------
# Internal rollback logic (shared between single-file and all-files)
# ---------------------------------------------------------------------------

def _do_rollback_file(path: str) -> bool:
    """Pop snapshot and write it back to disk. Returns True on success."""
    store = get_store()
    snap = store.pop(path)
    if snap is None:
        out_error(
            f"No snapshot available for this file. "
            f"Run /rollback list to see available snapshots."
        )
        return False

    try:
        current_content = Path(path).read_text(encoding="utf-8")
    except OSError:
        current_content = ""

    # Show diff: current → snapshot (what will be restored)
    try:
        from cli.diff_viewer import show_file_change
        show_file_change(path, current_content, snap.content)
    except Exception:
        pass

    Path(path).write_text(snap.content, encoding="utf-8")

    remaining = store.depth(path)
    ts_short = snap.ts[11:19] if len(snap.ts) >= 19 else snap.ts
    extra = f"  ({remaining} more snapshot{'s' if remaining != 1 else ''} available)"
    print(
        f"\n  {GREEN}Restored to snapshot from {ts_short}{RESET}{DIM}{extra}{RESET}"
    )

    # Audit log
    try:
        from app.core.audit import log_file_op
        log_file_op("rollback", path, allowed=True)
    except Exception:
        pass

    return True


# ---------------------------------------------------------------------------
# /rollback command
# ---------------------------------------------------------------------------

def cmd_rollback(args: str | list[str], cfg: AppConfig) -> None:
    """/rollback [list | diff <file> | all | <file>]"""
    # Normalise — caller may pass a list or a raw string
    if isinstance(args, list):
        tokens = args
    else:
        tokens = args.split() if args else []

    sub = tokens[0].lower() if tokens else "list"

    # ── /rollback list ───────────────────────────────────────────────────────
    if sub == "list":
        store = get_store()
        paths = store.all_paths()
        if not paths:
            print(
                f"  {DIM}No rollback snapshots this session. "
                f"Run a code-agent task first.{RESET}"
            )
            return
        print(f"\n  {GREEN}Files with rollback snapshots this session:{RESET}\n")
        for p in sorted(paths):
            depth = store.depth(p)
            orig = store.original(p)
            ts_short = orig.ts[11:19] if orig and len(orig.ts) >= 19 else "?"
            snap_word = "snapshot" if depth == 1 else "snapshots"
            print(
                f"  {DIM}▸{RESET} {p:<55}"
                f"  {depth} {snap_word}  {DIM}(earliest: {ts_short}){RESET}"
            )
        print(
            f"\n  {DIM}Run /rollback <file> to restore the previous version.{RESET}\n"
        )
        return

    # ── /rollback diff <file> ────────────────────────────────────────────────
    if sub == "diff":
        if len(tokens) < 2:
            out_error("Usage: /rollback diff <file>")
            return
        file_arg = " ".join(tokens[1:])
        path = _resolve_path(file_arg, cfg)
        if path is None:
            out_error(
                f"Cannot find '{file_arg}'. "
                f"Run /rollback list to see files with snapshots."
            )
            return
        store = get_store()
        snap = store.peek(path)
        if snap is None:
            out_error(
                f"No snapshot available for '{file_arg}'. "
                f"Run /rollback list to see available snapshots."
            )
            return
        try:
            current_content = Path(path).read_text(encoding="utf-8")
        except OSError:
            current_content = ""
        try:
            from cli.diff_viewer import show_file_change
            show_file_change(path, snap.content, current_content)
        except Exception as exc:
            out_error(f"Diff failed: {exc}")
        return

    # ── /rollback all ────────────────────────────────────────────────────────
    if sub == "all":
        store = get_store()
        paths = store.all_paths()
        if not paths:
            print(f"  {YELLOW}No snapshots available this session.{RESET}")
            return
        print(f"\n  {YELLOW}The following {len(paths)} file(s) will be restored:{RESET}")
        for p in sorted(paths):
            print(f"    {DIM}▸{RESET} {p}")
        try:
            ans = input(
                f"\n  Restore all {len(paths)} file(s)? [y/N]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans not in ("y", "yes"):
            print(f"  {DIM}Cancelled.{RESET}")
            return
        restored = 0
        for p in sorted(paths):
            if _do_rollback_file(p):
                restored += 1
        print(f"\n  {GREEN}Restored {restored}/{len(paths)} file(s).{RESET}\n")
        return

    # ── /rollback <file> ─────────────────────────────────────────────────────
    file_arg = " ".join(tokens)
    path = _resolve_path(file_arg, cfg)
    if path is None:
        out_error(
            f"Cannot find '{file_arg}'. "
            f"Run /rollback list to see files with snapshots, "
            f"or check that the file exists."
        )
        return
    print(f"\n  {GREEN}Rolling back:{RESET} {path}")
    _do_rollback_file(path)


# ---------------------------------------------------------------------------
# /checkpoint command
# ---------------------------------------------------------------------------

def cmd_checkpoint(args: str | list[str], cfg: AppConfig) -> None:
    """/checkpoint [name]  — snapshot current state of all tracked files."""
    if isinstance(args, list):
        name = " ".join(args).strip() or "checkpoint"
    else:
        name = args.strip() or "checkpoint"

    store = get_store()
    tracked = store.all_paths()

    if not tracked:
        print(
            f"  {YELLOW}No files tracked yet. "
            f"Run a code-agent task first, then checkpoint.{RESET}"
        )
        return

    saved: list[str] = []
    for p in tracked:
        try:
            content = Path(p).read_text(encoding="utf-8")
            store.save(path=p, content=content, run_id="", label=name)
            saved.append(Path(p).name)
        except OSError:
            pass

    if saved:
        files_str = ", ".join(saved[:5])
        if len(saved) > 5:
            files_str += f", … (+{len(saved) - 5} more)"
        print(
            f"\n  {GREEN}Checkpoint saved:{RESET} {DIM}\"{name}\"{RESET}\n"
            f"  {DIM}Captured {len(saved)} file(s): {files_str}{RESET}\n"
        )
    else:
        out_error("No files could be read for checkpoint.")
