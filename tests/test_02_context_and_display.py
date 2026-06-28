"""Cluster 02 — Context expansion, display helpers, and session persistence.

Tests:
  - test_ansi_constants          : RESET/BOLD/CYAN etc. are valid ANSI strings
  - test_highlight_code_python   : highlight_code() returns non-empty for Python
  - test_render_chat_response    : render_chat_response() runs without error on fenced code
  - test_print_diff_line_smoke   : print_diff_line() handles +/-/@@ lines
  - test_looks_like_question     : ContextManager correctly classifies questions vs tasks
  - test_expand_at_paths_missing : expand_at_paths() handles missing path gracefully
  - test_expand_at_paths_real    : expand_at_paths() inlines content for real file
  - test_workspace_tree_empty    : workspace_tree() returns empty string for missing workspace
  - test_workspace_tree_real     : workspace_tree() returns file listing for real folder
  - test_session_save_load       : SessionManager.save() then load() round-trips correctly
  - test_session_format_listing  : format_listing() returns formatted string
"""
from __future__ import annotations

import sys
import io
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


# ── Display tests ─────────────────────────────────────────────────────────────

def test_ansi_constants():
    from cli.display import RESET, BOLD, DIM, CYAN, GREEN, YELLOW, RED, BLUE, MAGENTA
    constants = {"RESET": RESET, "BOLD": BOLD, "DIM": DIM, "CYAN": CYAN,
                 "GREEN": GREEN, "YELLOW": YELLOW, "RED": RED, "BLUE": BLUE, "MAGENTA": MAGENTA}
    failures = [k for k, v in constants.items() if not (isinstance(v, str) and "\033[" in v)]
    ok = len(failures) == 0
    save("ansi_constants", ok, {"constants": constants, "failures": failures})
    assert ok, f"Invalid ANSI constants: {failures}"


def test_highlight_code_python():
    from cli.display import highlight_code
    code = "def hello():\n    return 42\n"
    result = highlight_code(code, "python")
    ok = isinstance(result, str) and len(result) > 0
    save("highlight_code_python", ok, {"input_len": len(code), "output_len": len(result)})
    assert ok


def test_render_chat_response(capsys):
    from cli.display import render_chat_response
    text = "Here is some code:\n```python\ndef foo(): pass\n```\nDone."
    try:
        render_chat_response(text)
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("render_chat_response", ok, {"input": text, "error": error})
    assert ok, f"render_chat_response raised: {error}"


def test_print_diff_line_smoke(capsys):
    from cli.display import print_diff_line
    lines = ["+added line", "-removed line", "@@ -1,3 +1,4 @@", "--- a/foo.py", "+++ b/foo.py", " context"]
    try:
        for ln in lines:
            print_diff_line(ln)
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("print_diff_line_smoke", ok, {"lines_tested": lines, "error": error})
    assert ok, f"print_diff_line raised: {error}"


# ── ContextManager tests ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ctx(cfg):
    from cli.context import ContextManager
    return ContextManager(cfg)


def test_looks_like_question(ctx):
    questions = [
        "what does this function do?",
        "how do I install this?",
        "explain the auth flow",
        "is this code correct?",
        "tell me about Python classes",
    ]
    tasks = [
        "add unit tests to auth.py",
        "refactor the database layer",
        "create a REST API endpoint",
        "fix the bug in login.py",
    ]
    q_results = {q: ctx.looks_like_question(q) for q in questions}
    t_results = {t: ctx.looks_like_question(t) for t in tasks}
    q_failures = [q for q, r in q_results.items() if not r]
    t_failures = [t for t, r in t_results.items() if r]
    ok = len(q_failures) == 0 and len(t_failures) == 0
    save("looks_like_question", ok, {
        "question_results": q_results,
        "task_results":     t_results,
        "q_failures":       q_failures,
        "t_failures":       t_failures,
    })
    assert ok, f"Questions misclassified: {q_failures}  Tasks misclassified: {t_failures}"


def test_expand_at_paths_missing(ctx):
    text = "check @/nonexistent/path/xyz.py please"
    expanded, found = ctx.expand_at_paths(text)
    ok = isinstance(expanded, str) and len(expanded) >= len(text)
    save("expand_at_paths_missing", ok, {
        "input":    text,
        "expanded": expanded[:200],
        "found":    found,
    })
    assert ok


def test_expand_at_paths_real(ctx):
    # Use conftest.py itself as a real file that definitely exists.
    # Quote the path so spaces (e.g. "ILX Studio") don't truncate @-expansion.
    test_file = str(Path(__file__).parent / "conftest.py")
    text = f'explain @"{test_file}"'
    expanded, found = ctx.expand_at_paths(text)
    ok = test_file in found and "conftest" in expanded
    save("expand_at_paths_real", ok, {
        "file":     test_file,
        "found":    found,
        "expanded": expanded[:300],
    })
    assert ok, f"Expected {test_file} in found={found}"


def test_workspace_tree_empty(cfg):
    from cli.context import ContextManager
    from app.core.config import AppConfig
    empty_cfg = AppConfig()
    empty_cfg.working_folder = "/nonexistent/path/xyz123"
    ctx_empty = ContextManager(empty_cfg)
    tree = ctx_empty.workspace_tree()
    ok = tree == ""
    save("workspace_tree_empty", ok, {"tree": tree})
    assert ok, f"Expected empty string, got: {tree!r}"


def test_workspace_tree_real(cfg):
    from cli.context import ContextManager
    from app.core.config import AppConfig
    root_cfg = AppConfig()
    root_cfg.working_folder = str(Path(__file__).parent.parent)
    ctx_real = ContextManager(root_cfg)
    tree = ctx_real.workspace_tree()
    ok = isinstance(tree, str) and "main.py" in tree
    save("workspace_tree_real", ok, {"tree_snippet": tree[:400]})
    assert ok, f"Expected main.py in tree, got: {tree[:200]}"


# ── SessionManager tests ──────────────────────────────────────────────────────

def test_session_save_load(cfg):
    from cli.session import SessionManager
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = SessionManager(session_dir=Path(tmp))
        history = [
            {"role": "user",      "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        saved_path = mgr.save(history, cfg)
        ok_save = saved_path is not None and saved_path.exists()
        meta, msgs = mgr.load(saved_path) if ok_save else ({}, [])
        ok_load = (
            len(msgs) == 2
            and msgs[0]["role"] == "user"
            and msgs[1]["content"] == "world"
        )
        ok = ok_save and ok_load
        save("session_save_load", ok, {
            "saved_path": str(saved_path),
            "meta":       meta,
            "msg_count":  len(msgs),
            "ok_save":    ok_save,
            "ok_load":    ok_load,
        })
    assert ok, f"save={ok_save} load={ok_load}"


def test_session_format_listing(cfg):
    from cli.session import SessionManager
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = SessionManager(session_dir=Path(tmp))
        # empty listing
        empty = mgr.format_listing([])
        ok_empty = "No saved sessions" in empty
        # save one and list it
        mgr.save([{"role": "user", "content": "test"}], cfg)
        sessions = mgr.list(5)
        listing = mgr.format_listing(sessions)
        ok_listing = len(sessions) == 1 and "ollama" in listing.lower() or "[1]" in listing
        ok = ok_empty and ok_listing
        save("session_format_listing", ok, {
            "empty_listing": empty,
            "listing":       listing,
            "ok_empty":      ok_empty,
            "ok_listing":    ok_listing,
        })
    assert ok
