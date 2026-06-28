"""ILX AI CLI — entry point.

Startup sequence:
1. Set process priority and thread-pool size based on available CPU cores.
2. Delegate to oneshot mode (pipe / argv) or the interactive REPL.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(name)s  %(message)s",
)


def _configure_runtime() -> None:
    """Tune the runtime for multi-core use without starving the OS."""
    import concurrent.futures
    cpu = os.cpu_count() or 2
    # Thread pool: I/O bound work (LLM streaming, file reads, watchers)
    # Use min(32, cpu * 4) — same formula as Python 3.8+ default but explicit.
    workers = min(32, cpu * 4)
    # Set as the default executor on the running loop if asyncio is available,
    # and also expose as a module-level pool for synchronous callers.
    import app.core.thread_pool as _tp
    _tp.init(workers)

    # On Windows, set HIGH_PRIORITY_CLASS so the REPL thread stays responsive
    # when user code saturates the CPU via subprocesses.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(  # type: ignore[attr-defined]
                ctypes.windll.kernel32.GetCurrentProcess(),  # type: ignore[attr-defined]
                0x00000080,  # HIGH_PRIORITY_CLASS
            )
        except Exception:
            pass  # non-fatal — works without elevation on most systems


def _install_crash_hooks() -> None:
    """Route unhandled Python exceptions and thread crashes to crash_db."""
    import sys
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
    import sys as _sys

    # Apply --json flag early so output mode is set before any config or display
    # code runs.  rich_display holds the authoritative output-mode state.
    if "--json" in _sys.argv:
        try:
            from cli.rich_display import set_output_mode
            set_output_mode("json")
        except Exception:
            pass

    if "--help" in _sys.argv or "-h" in _sys.argv:
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
        print()
        print("Interactive mode (no arguments): start the REPL, then type /help for commands.")
        print()
        print("Examples:")
        print("  ilx                          Start interactive session")
        print("  ilx --chat 'explain main.py' --file main.py")
        print("  ilx --yes --json --chat 'list functions in app.py'")
        _sys.exit(0)
    if "--version" in _sys.argv:
        from app.version import __version__
        print(f"ILX AI CLI v{__version__}")
        _sys.exit(0)
    _install_crash_hooks()
    _configure_runtime()

    from app.core.config import ConfigManager
    from cli.oneshot import parse_argv, run_pipe_mode, run_argv_chat, run_argv_code

    mgr = ConfigManager()
    cfg = mgr.load()

    # Propagate --json flag to cfg so downstream components can read cfg.output_mode
    if "--json" in sys.argv and hasattr(cfg, "output_mode"):
        cfg.output_mode = "json"

    if not sys.stdin.isatty():
        mode, prompt = parse_argv()
        if not prompt:
            run_pipe_mode(cfg)
            return

    mode, prompt = parse_argv()
    if prompt:
        if mode == "chat":
            run_argv_chat(prompt, cfg)
        else:
            run_argv_code(prompt, cfg)
        return

    from cli.app import ILXApp
    ILXApp().run()


if __name__ == "__main__":
    main()
