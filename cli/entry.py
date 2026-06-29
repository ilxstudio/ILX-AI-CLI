"""Installed entry point for the ilx command."""
from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(name)s  %(message)s",
)


def _configure_runtime() -> None:
    cpu = os.cpu_count() or 2
    workers = min(32, cpu * 4)
    import app.core.thread_pool as _tp
    _tp.init(workers)

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(  # type: ignore[attr-defined]
                ctypes.windll.kernel32.GetCurrentProcess(),  # type: ignore[attr-defined]
                0x00000080,
            )
        except Exception:
            pass


def _install_crash_hooks() -> None:
    import threading
    import traceback

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            from app.core import crash_db
            crash_db.record(f"unhandled:{exc_type.__name__}", -1, tb_str)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _thread_excepthook(args):
        if args.exc_type in (KeyboardInterrupt, SystemExit):
            return
        tb_str = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
        try:
            from app.core import crash_db
            crash_db.record(f"thread:{args.exc_type.__name__}", -1, tb_str)
        except Exception:
            pass

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def main() -> None:
    if "--help" in sys.argv or "-h" in sys.argv:
        print("ILX AI CLI — Free, local-first AI developer assistant")
        print()
        print("Usage: ilx [OPTIONS]")
        print()
        print("Options:")
        print("  --help, -h          Show this help message and exit")
        print("  --version           Print version and exit")
        print("  --chat TEXT         Send a single message and exit (non-interactive)")
        print("  --file PATH         Load a file into context for --chat")
        print("  --yes               Auto-approve all permission prompts")
        print("  --quiet             Suppress all non-essential output")
        print("  --json              Output responses as JSON")
        print("  --no-color          Disable ANSI color output")
        print("  --dry-run           Show what would be done without executing")
        print("  --autofix           Auto-run test-fix loop after each /code task")
        print("  --no-autofix        Disable auto test-fix (overrides config)")
        print()
        print("Interactive mode (no arguments): start the REPL, then type /help for commands.")
        print()
        print("Examples:")
        print("  ilx                          Start interactive session")
        print("  ilx --chat 'explain main.py' --file main.py")
        print("  ilx --yes --json --chat 'list functions in app.py'")
        sys.exit(0)

    if "--version" in sys.argv:
        from app.version import __version__
        print(f"ILX AI CLI v{__version__}")
        sys.exit(0)

    from app.core.audit import init_session as _init_session
    _sid = _init_session()

    import atexit
    from app.core.snapshot_store import init_snapshot_store, get_store as _get_snap_store
    init_snapshot_store(sid=_sid)
    atexit.register(lambda: _get_snap_store().clear())

    _install_crash_hooks()
    _configure_runtime()

    from app.core.config import ConfigManager
    from cli.oneshot import parse_argv, run_pipe_mode, run_argv_chat, run_argv_code

    mgr = ConfigManager()
    cfg = mgr.load()

    if not sys.stdin.isatty():
        mode, prompt = parse_argv(cfg)
        if not prompt:
            run_pipe_mode(cfg)
            return

    mode, prompt = parse_argv(cfg)
    if prompt:
        if mode == "chat":
            run_argv_chat(prompt, cfg)
        else:
            run_argv_code(prompt, cfg)
        return

    from cli.app import ILXApp
    ILXApp().run()
