"""Terminal side-by-side diff viewer using Rich.
Renders original vs updated file content in two columns with syntax highlighting.
MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

import difflib
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

# ---------------------------------------------------------------------------
# Availability probe
# ---------------------------------------------------------------------------

try:
    from rich.console import Console as _RichConsole
    from rich.table import Table
    from rich.text import Text
    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DiffRow:
    """Represents one row in the side-by-side diff table."""
    left_num:   int | None   # 1-based line number in original; None = inserted
    left_text:  str | None   # content; None = no left side
    left_kind:  str          # "equal" | "delete" | "empty" | "context_skip"
    right_num:  int | None   # 1-based line number in updated
    right_text: str | None
    right_kind: str          # "equal" | "insert" | "empty" | "context_skip"


# ---------------------------------------------------------------------------
# Diff builder
# ---------------------------------------------------------------------------

def _build_rows(
    old_lines: list[str],
    new_lines: list[str],
    context_lines: int,
) -> list[DiffRow]:
    """Convert SequenceMatcher opcodes into a flat list of DiffRow objects."""
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    opcodes = matcher.get_opcodes()

    raw: list[DiffRow] = []

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k, (ol, nl) in enumerate(zip(old_lines[i1:i2], new_lines[j1:j2])):
                raw.append(DiffRow(
                    left_num=i1 + k + 1,  left_text=ol,
                    left_kind="equal",
                    right_num=j1 + k + 1, right_text=nl,
                    right_kind="equal",
                ))
        elif tag == "replace":
            old_span = old_lines[i1:i2]
            new_span = new_lines[j1:j2]
            for k, ol in enumerate(old_span):
                nl = new_span[k] if k < len(new_span) else None
                raw.append(DiffRow(
                    left_num=i1 + k + 1,  left_text=ol,
                    left_kind="delete",
                    right_num=(j1 + k + 1) if nl is not None else None,
                    right_text=nl,
                    right_kind="insert" if nl is not None else "empty",
                ))
            for k in range(len(old_span), len(new_span)):
                raw.append(DiffRow(
                    left_num=None,  left_text=None,
                    left_kind="empty",
                    right_num=j1 + k + 1, right_text=new_span[k],
                    right_kind="insert",
                ))
        elif tag == "delete":
            for k, ol in enumerate(old_lines[i1:i2]):
                raw.append(DiffRow(
                    left_num=i1 + k + 1,  left_text=ol,
                    left_kind="delete",
                    right_num=None, right_text=None,
                    right_kind="empty",
                ))
        elif tag == "insert":
            for k, nl in enumerate(new_lines[j1:j2]):
                raw.append(DiffRow(
                    left_num=None,  left_text=None,
                    left_kind="empty",
                    right_num=j1 + k + 1, right_text=nl,
                    right_kind="insert",
                ))

    return _collapse_context(raw, context_lines)


def _collapse_context(rows: list[DiffRow], ctx: int) -> list[DiffRow]:
    """Replace long equal runs with a single skip placeholder."""
    n = len(rows)
    keep = [False] * n

    for i, row in enumerate(rows):
        if row.left_kind != "equal" or row.right_kind != "equal":
            for j in range(max(0, i - ctx), min(n, i + ctx + 1)):
                keep[j] = True

    result: list[DiffRow] = []
    i = 0
    while i < n:
        if keep[i]:
            result.append(rows[i])
            i += 1
        else:
            run_start = i
            while i < n and not keep[i]:
                i += 1
            skipped = i - run_start
            if skipped > 0:
                result.append(DiffRow(
                    left_num=None,  left_text=f"... {skipped} unchanged line(s) ...",
                    left_kind="context_skip",
                    right_num=None, right_text=f"... {skipped} unchanged line(s) ...",
                    right_kind="context_skip",
                ))
    return result


# ---------------------------------------------------------------------------
# Rich renderer
# ---------------------------------------------------------------------------

def _num_str(n: int | None, width: int = 4) -> str:
    return str(n).rjust(width) if n is not None else " " * width


def _format_side(num: int | None, text: str | None, kind: str, col_width: int) -> Text:
    """Return a styled Rich Text object for one diff cell."""
    from rich.text import Text

    num_str = _num_str(num)
    raw     = (text or "").rstrip("\n\r")
    # Truncate so it fits in the column
    max_content = max(col_width - 8, 10)
    if len(raw) > max_content:
        raw = raw[:max_content - 1] + "…"

    if kind == "context_skip":
        t = Text(f"  {'':>{4}}   {raw}", style="dim")
        return t

    if kind == "delete":
        prefix = "- "
        t = Text()
        t.append(f"{num_str} ", style="dim red")
        t.append(f"{prefix}{raw}", style="bold red")
    elif kind == "insert":
        prefix = "+ "
        t = Text()
        t.append(f"{num_str} ", style="dim green")
        t.append(f"{prefix}{raw}", style="bold green")
    elif kind == "equal":
        prefix = "  "
        t = Text()
        t.append(f"{num_str} ", style="dim")
        t.append(f"{prefix}{raw}", style="dim")
    else:  # empty
        t = Text(f"{'':>{4}}   ", style="dim")

    return t


def _count_changes(rows: list[DiffRow]) -> int:
    added    = sum(1 for r in rows if r.right_kind == "insert")
    removed  = sum(1 for r in rows if r.left_kind  == "delete")
    return added + removed


def _render_rich(
    original: str,
    updated:  str,
    filename: str,
    context_lines: int,
    width: int,
    console: Console,
) -> None:
    from rich.table import Table
    from rich.text import Text

    old_lines = original.splitlines()
    new_lines = updated.splitlines()
    rows      = _build_rows(old_lines, new_lines, context_lines)
    changes   = _count_changes(rows)

    label    = filename or "diff"
    title    = f"  {label} — {changes} change(s)  "
    col_w    = max((width - 6) // 2, 20)

    table = Table(
        title=title,
        title_style="bold",
        show_header=True,
        header_style="dim",
        box=None,
        padding=(0, 0),
        show_edge=False,
        show_lines=False,
        expand=False,
        width=width,
    )
    table.add_column("ORIGINAL", width=col_w, no_wrap=True)
    table.add_column("│", width=1, no_wrap=True, style="dim")
    table.add_column("UPDATED",  width=col_w, no_wrap=True)

    for row in rows:
        left  = _format_side(row.left_num,  row.left_text,  row.left_kind,  col_w)
        divider = Text("│", style="dim")
        right = _format_side(row.right_num, row.right_text, row.right_kind, col_w)
        table.add_row(left, divider, right)

    console.print(table)


# ---------------------------------------------------------------------------
# Plain-text fallback
# ---------------------------------------------------------------------------

def _plain_diff(original: str, updated: str, filename: str) -> None:
    """Print a simple unified diff with ANSI colors."""
    RED   = "\033[31m"
    GREEN = "\033[32m"
    RESET = "\033[0m"
    DIM   = "\033[2m"
    lines = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3,
    ))
    for line in lines:
        if line.startswith("-"):
            print(f"{RED}{line}{RESET}", end="")
        elif line.startswith("+"):
            print(f"{GREEN}{line}{RESET}", end="")
        else:
            print(f"{DIM}{line}{RESET}", end="")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def show_side_by_side_diff(
    original:      str,
    updated:       str,
    filename:      str = "",
    context_lines: int = 3,
    width:         int | None = None,
    console:       Console | None = None,
) -> None:
    """Render a two-column side-by-side diff in the terminal.

    Parameters
    ----------
    original:
        The before content (full file text).
    updated:
        The after content (full file text).
    filename:
        Display name shown in the header row.
    context_lines:
        How many unchanged lines to show around each changed block.
    width:
        Terminal width override; auto-detected when None.
    console:
        Rich Console to write to; a new one is created when None.
    """
    if not _RICH_AVAILABLE:
        _plain_diff(original, updated, filename)
        return

    if width is None:
        try:
            width = shutil.get_terminal_size((120, 24)).columns
        except Exception:
            width = 120
    width = max(width, 60)

    if console is None:
        console = _RichConsole()

    _render_rich(original, updated, filename, context_lines, width, console)


def show_file_change(
    path:     str,
    original: str,
    updated:  str,
    *,
    console: Console | None = None,
) -> None:
    """Convenience wrapper: show a titled diff for a file operation.

    Parameters
    ----------
    path:
        File path used as the display label.
    original:
        Content before modification.
    updated:
        Content after modification.
    console:
        Rich Console to write to; auto-created when None.
    """
    import os as _os
    filename = _os.path.basename(path) if path else ""
    show_side_by_side_diff(
        original=original,
        updated=updated,
        filename=filename,
        console=console,
    )
