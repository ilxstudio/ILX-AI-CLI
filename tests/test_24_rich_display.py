"""Cluster 24 — Rich TUI display layer.

Tests that every public function in cli.rich_display works without raising,
regardless of whether the ``rich`` package is installed.

Tests:
  - test_is_rich_available        : is_rich_available() returns a bool (no crash)
  - test_print_markdown           : print_markdown("# Hello") does not raise
  - test_print_code               : print_code("x = 1", "python") does not raise
  - test_print_diff_no_rich       : print_diff("+added\\n-removed") works without rich
  - test_print_diff_with_rich     : print_diff works (any env)
  - test_print_table              : print_table with headers+rows does not raise
  - test_print_ai_response_plain  : print_ai_response("plain text") does not raise
  - test_print_ai_response_markdown: print_ai_response("## Header\\n**bold**") does not raise
  - test_progress_spinner         : context manager does not raise
  - test_looks_like_markdown      : _looks_like_markdown heuristic is correct
  - test_set_get_rich_enabled     : set/get enable flag round-trips
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


# ── helpers ───────────────────────────────────────────────────────────────────

def _import_rd():
    """Import cli.rich_display, skipping tests if module is missing."""
    import importlib
    return importlib.import_module("cli.rich_display")


# ── tests ─────────────────────────────────────────────────────────────────────

def test_is_rich_available():
    rd = _import_rd()
    result = rd.is_rich_available()
    ok = isinstance(result, bool)
    save("rich_is_rich_available", ok, {"result": result})
    assert ok, "is_rich_available() must return a bool"


def test_print_markdown(capsys):
    rd = _import_rd()
    try:
        rd.print_markdown("# Hello\n\nThis is **bold**.")
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("rich_print_markdown", ok, {"error": error})
    assert ok, f"print_markdown raised: {error}"


def test_print_code(capsys):
    rd = _import_rd()
    try:
        rd.print_code("x = 1\ny = x + 2\n", "python")
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("rich_print_code", ok, {"error": error})
    assert ok, f"print_code raised: {error}"


def test_print_diff_no_rich(capsys, monkeypatch):
    """Force plain-ANSI fallback by temporarily disabling rich."""
    rd = _import_rd()
    monkeypatch.setattr(rd, "_rich_enabled", False)
    try:
        rd.print_diff("+added line\n-removed line\n@@ -1 +1 @@\n context\n")
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("rich_print_diff_no_rich", ok, {"error": error})
    assert ok, f"print_diff (no-rich fallback) raised: {error}"


def test_print_diff_with_rich(capsys):
    rd = _import_rd()
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n"
        " def main():\n"
        "-    pass\n"
        "+    print('hello')\n"
    )
    try:
        rd.print_diff(diff)
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("rich_print_diff_with_rich", ok, {"error": error})
    assert ok, f"print_diff raised: {error}"


def test_print_table(capsys):
    rd = _import_rd()
    headers = ["Name", "Value", "Status"]
    rows = [
        ["alpha", "1", "OK"],
        ["beta",  "2", "WARN"],
    ]
    try:
        rd.print_table(headers, rows, title="Test Table")
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("rich_print_table", ok, {"error": error})
    assert ok, f"print_table raised: {error}"


def test_print_ai_response_plain(capsys):
    rd = _import_rd()
    try:
        rd.print_ai_response("This is plain text with no markdown.", "ollama", "codellama:7b")
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("rich_print_ai_response_plain", ok, {"error": error})
    assert ok, f"print_ai_response (plain) raised: {error}"


def test_print_ai_response_markdown(capsys):
    rd = _import_rd()
    md_text = (
        "## Results\n\n"
        "Here are the **key** findings:\n\n"
        "```python\nx = 42\n```\n"
    )
    try:
        rd.print_ai_response(md_text, "anthropic", "claude-sonnet-4")
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("rich_print_ai_response_markdown", ok, {"error": error})
    assert ok, f"print_ai_response (markdown) raised: {error}"


def test_progress_spinner():
    rd = _import_rd()
    try:
        with rd.progress_spinner("Working on it") as spinner:
            # Spinner may be None, a rich Progress, or a Spinner — all are valid.
            _ = spinner
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("rich_progress_spinner", ok, {"error": error})
    assert ok, f"progress_spinner context manager raised: {error}"


def test_looks_like_markdown():
    rd = _import_rd()
    # These should be detected as markdown
    md_cases = [
        "## Section\n\nSome text",
        "This is **bold** text",
        "```python\nx = 1\n```",
        "| col | col |\n|---|---|",
        "# Title",
        "- [ ] todo item",
        "* bullet",
    ]
    # These should NOT be detected as markdown
    plain_cases = [
        "Hello world",
        "Error: file not found",
        "1 + 1 = 2",
        "just a normal sentence here",
    ]
    md_ok   = all(rd._looks_like_markdown(t) for t in md_cases)
    plain_ok = not any(rd._looks_like_markdown(t) for t in plain_cases)
    ok = md_ok and plain_ok
    save("rich_looks_like_markdown", ok, {
        "md_ok": md_ok,
        "plain_ok": plain_ok,
    })
    assert md_ok,   "Some markdown cases were not detected"
    assert plain_ok, "Some plain-text cases were falsely detected as markdown"


def test_set_get_rich_enabled():
    rd = _import_rd()
    original = rd.get_rich_enabled()
    try:
        rd.set_rich_enabled(False)
        assert rd.get_rich_enabled() is False
        rd.set_rich_enabled(True)
        assert rd.get_rich_enabled() is True
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    finally:
        rd.set_rich_enabled(original)  # restore
    save("rich_set_get_enabled", ok, {"error": error})
    assert ok, f"set/get_rich_enabled raised: {error}"
