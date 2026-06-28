"""Lightweight output helpers that respect --json / --quiet output modes.

Use these for all user-facing output in CLI command files.
"""
from __future__ import annotations
import json as _json
import sys


def out(text: str, *, end: str = "\n") -> None:
    """Print text, suppressed in quiet mode, JSON-encoded in json mode."""
    from cli.rich_display import get_output_mode
    mode = get_output_mode()
    if mode == "quiet":
        return
    if mode == "json":
        sys.stdout.write(_json.dumps({"type": "output", "content": text}) + "\n")
        return
    print(text, end=end)


def out_error(text: str) -> None:
    """Print an error line. Always shown in all modes."""
    from cli.rich_display import get_output_mode
    mode = get_output_mode()
    if mode == "json":
        sys.stdout.write(_json.dumps({"type": "error", "content": text}) + "\n")
        return
    print(text)


def out_status(text: str) -> None:
    """Print a status/progress line. Suppressed in quiet and json modes."""
    from cli.rich_display import get_output_mode
    mode = get_output_mode()
    if mode in ("quiet", "json"):
        return
    print(text)


def out_result(text: str) -> None:
    """Print a final result/response. Always shown."""
    from cli.rich_display import get_output_mode
    mode = get_output_mode()
    if mode == "json":
        sys.stdout.write(_json.dumps({"type": "result", "content": text}) + "\n")
        return
    print(text)
