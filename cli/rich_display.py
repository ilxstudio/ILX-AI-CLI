"""Rich TUI display layer — syntax highlighting, progress bars, diff panels.

Requires: pip install rich>=13.0
Falls back gracefully to plain ANSI output when rich is not installed.
"""
from __future__ import annotations

import contextlib
import json as _json
import sys
import threading
from typing import Generator

# ── Module-level rich-enable flag ─────────────────────────────────────────────
# Can be toggled at runtime by /rich on|off without reimporting.
_rich_enabled: bool = True

# ── Output mode ───────────────────────────────────────────────────────────────
# "ansi"  — default: rich/ANSI rendering (existing behaviour)
# "json"  — emit newline-delimited JSON to stdout; no ANSI codes
# "quiet" — only print_ai_response emits output; everything else is a no-op
_output_mode: str = "ansi"
_output_mode_lock = threading.Lock()


def set_output_mode(mode: str) -> None:
    """Set the global output mode to 'ansi', 'json', or 'quiet'."""
    global _output_mode
    if mode in ("ansi", "json", "quiet"):
        with _output_mode_lock:
            _output_mode = mode


def get_output_mode() -> str:
    """Return the current output mode."""
    with _output_mode_lock:
        return _output_mode


def _emit_json(**fields) -> None:
    """Write a single JSON line to stdout."""
    sys.stdout.write(_json.dumps(fields) + "\n")
    sys.stdout.flush()


def is_rich_available() -> bool:
    """Return True if the ``rich`` package is importable."""
    try:
        import rich  # noqa: F401
        return True
    except ImportError:
        return False


def _use_rich() -> bool:
    """Return True when rich is both installed and enabled by the user flag."""
    return _rich_enabled and is_rich_available()


# ── Markdown detection ────────────────────────────────────────────────────────

def _looks_like_markdown(text: str) -> bool:
    """Heuristic: text is markdown if it contains common markdown markers."""
    markers = ("## ", "**", "```", "|---|", "# ", "* ", "- [")
    return any(m in text for m in markers)


# ── Public API ────────────────────────────────────────────────────────────────

def print_markdown(text: str) -> None:
    """Render *text* as Markdown inside a dim Panel, or fall back to plain print."""
    if _output_mode == "json":
        _emit_json(type="markdown", content=text)
        return
    if _output_mode == "quiet":
        return
    if _use_rich():
        try:
            from rich.console import Console
            from rich.markdown import Markdown
            from rich.panel import Panel

            console = Console()
            console.print(Panel(Markdown(text), border_style="dim"))
            return
        except Exception:
            pass
    print(text)


def print_code(code: str, language: str = "python") -> None:
    """Render *code* with Monokai syntax highlighting and line numbers, or plain print."""
    if _output_mode == "json":
        _emit_json(type="code", content=code, language=language)
        return
    if _output_mode == "quiet":
        return
    if _use_rich():
        try:
            from rich.console import Console
            from rich.syntax import Syntax

            console = Console()
            console.print(Syntax(code, language, theme="monokai", line_numbers=True))
            return
        except Exception:
            pass
    print(code)


def print_diff(diff_text: str) -> None:
    """Render a unified diff with syntax highlighting (Rich or ANSI fallback)."""
    if _output_mode == "json":
        _emit_json(type="diff", content=diff_text)
        return
    if _output_mode == "quiet":
        return
    if _use_rich():
        try:
            from rich.console import Console
            from rich.syntax import Syntax

            console = Console()
            console.print(Syntax(diff_text, "diff", theme="monokai"))
            return
        except Exception:
            pass

    # Plain ANSI fallback
    _GREEN  = "\033[32m"
    _RED    = "\033[31m"
    _CYAN   = "\033[36m"
    _BOLD   = "\033[1m"
    _DIM    = "\033[2m"
    _RESET  = "\033[0m"

    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            print(f"{_BOLD}{line}{_RESET}")
        elif line.startswith("+"):
            print(f"{_GREEN}{line}{_RESET}")
        elif line.startswith("-"):
            print(f"{_RED}{line}{_RESET}")
        elif line.startswith("@@"):
            print(f"{_CYAN}{line}{_RESET}")
        else:
            print(f"{_DIM}{line}{_RESET}")


def print_ai_response(text: str, provider: str = "", model: str = "") -> None:
    """Print an AI response, auto-detecting markdown and adding a dim header.

    When rich is available and the text looks like markdown, it is rendered
    inside a Panel using ``rich.markdown.Markdown``.  Otherwise the text is
    printed with existing ANSI colours.
    """
    if _output_mode == "json":
        _emit_json(type="response", content=text, provider=provider, model=model)
        return
    if _output_mode == "quiet":
        print(text)
        return

    _DIM   = "\033[2m"
    _RESET = "\033[0m"
    _CYAN  = "\033[36m"

    header = ""
    if provider or model:
        parts = [p for p in (provider, model) if p]
        header = f"{_DIM}{_CYAN}{'  '.join(parts)}{_RESET}\n"

    if _use_rich() and _looks_like_markdown(text):
        try:
            from rich.console import Console
            from rich.markdown import Markdown
            from rich.panel import Panel

            if header:
                sys.stdout.write(header)
                sys.stdout.flush()
            console = Console()
            console.print(Panel(Markdown(text), border_style="dim"))
            return
        except Exception:
            pass

    # Plain ANSI fallback
    if header:
        sys.stdout.write(header)
    print(text)


def print_table(
    headers: list[str],
    rows: list[list[str]],
    title: str = "",
) -> None:
    """Render a table with Rich, or fall back to plain ``str.ljust`` layout."""
    if _output_mode == "json":
        _emit_json(type="table", content=title, headers=headers, rows=rows)
        return
    if _output_mode == "quiet":
        return
    if _use_rich():
        try:
            from rich.console import Console
            from rich.table import Table

            table = Table(title=title or None, show_header=True, header_style="bold cyan")
            for h in headers:
                table.add_column(h)
            for row in rows:
                table.add_row(*[str(c) for c in row])
            console = Console()
            console.print(table)
            return
        except Exception:
            pass

    # Plain tabulated fallback
    col_widths = [
        max(len(str(h)), *(len(str(r[i])) for r in rows) if rows else (0,))
        for i, h in enumerate(headers)
    ]
    if title:
        print(f"\n{title}")
    header_line = "  ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print("  ".join(str(row[i] if i < len(row) else "").ljust(col_widths[i])
                         for i in range(len(headers))))


@contextlib.contextmanager
def progress_spinner(description: str) -> Generator:
    """Context manager that shows a spinner during a long operation.

    Yields a ``rich.progress.Progress`` instance when rich is available,
    otherwise yields the plain ``app.core.spinner.Spinner`` instance.
    """
    if _output_mode == "json":
        _emit_json(type="status", content=description, event="start")
        try:
            yield None
        finally:
            _emit_json(type="status", content=description, event="end")
        return
    if _output_mode == "quiet":
        yield None
        return
    if _use_rich():
        try:
            from rich.progress import Progress, SpinnerColumn, TextColumn

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress:
                progress.add_task(description=description, total=None)
                yield progress
            return
        except Exception:
            pass

    # Fallback to the app's built-in spinner
    try:
        from app.core.spinner import Spinner
        spinner = Spinner(description)
        spinner.start()
        try:
            yield spinner
        finally:
            spinner.stop()
    except ImportError:
        # Last-resort no-op
        yield None


# ── Rich enable/disable state ─────────────────────────────────────────────────

def set_rich_enabled(enabled: bool) -> None:
    """Toggle rich rendering on or off at runtime."""
    global _rich_enabled
    _rich_enabled = enabled


def get_rich_enabled() -> bool:
    """Return the current runtime enable flag."""
    return _rich_enabled
