"""Unit tests for app.core.git_helper — all subprocess calls mocked.

Uses ``unittest.mock.patch`` on ``app.core.process_runner.run`` so no real
git process is spawned.  Each test constructs a ``ProcessResult`` that mimics
what the underlying git command would return.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.process_runner import ProcessResult


def _ok(stdout: str = "", stderr: str = "") -> ProcessResult:
    """Construct a successful ProcessResult."""
    return ProcessResult(returncode=0, stdout=stdout, stderr=stderr, ok=True)


def _fail(stderr: str = "", returncode: int = 1) -> ProcessResult:
    """Construct a failed ProcessResult."""
    return ProcessResult(returncode=returncode, stdout="", stderr=stderr, ok=False)


# git_helper._run calls process_runner.run(["git", *args], cwd=..., timeout=...)
# We patch process_runner.run at the source so git_helper's _run picks it up.
_PATCH_TARGET = "app.core.process_runner.run"


# ---------------------------------------------------------------------------
# is_git_repo
# ---------------------------------------------------------------------------

def test_is_git_repo_true(tmp_path):
    """Mocked 'git rev-parse --is-inside-work-tree' returning 'true' → True."""
    from app.core import git_helper

    with patch(_PATCH_TARGET, return_value=_ok("true\n")) as mock_run:
        result = git_helper.is_git_repo(str(tmp_path))

    assert result is True


def test_is_git_repo_false(tmp_path):
    """Mocked process returning ok=False → is_git_repo returns False."""
    from app.core import git_helper

    with patch(_PATCH_TARGET, return_value=_fail("not a git repo", returncode=128)):
        result = git_helper.is_git_repo(str(tmp_path))

    assert result is False


def test_is_git_repo_nonexistent_dir():
    """Passing a non-existent directory → False without calling git."""
    from app.core import git_helper

    with patch(_PATCH_TARGET) as mock_run:
        result = git_helper.is_git_repo("/nonexistent/path/xyz")

    assert result is False
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# current_branch
# ---------------------------------------------------------------------------

def test_current_branch(tmp_path):
    """Mocked 'git branch --show-current' stdout='main\\n' → returns 'main'."""
    from app.core import git_helper

    with patch(_PATCH_TARGET, return_value=_ok("main\n")):
        result = git_helper.current_branch(str(tmp_path))

    assert result == "main"


def test_current_branch_detached(tmp_path):
    """Detached HEAD — branch --show-current returns empty string."""
    from app.core import git_helper

    with patch(_PATCH_TARGET, return_value=_ok("\n")):
        result = git_helper.current_branch(str(tmp_path))

    # Empty string is acceptable for a detached HEAD state
    assert result == ""


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

def test_diff_returns_string(tmp_path):
    """Mocked diff stdout → diff() returns that string."""
    from app.core import git_helper

    fake_diff = "diff --git a/foo.py b/foo.py\n+added line\n"
    with patch(_PATCH_TARGET, return_value=_ok(fake_diff)):
        result = git_helper.diff(str(tmp_path))

    assert isinstance(result, str)
    assert "added line" in result


def test_diff_empty_on_failure(tmp_path):
    """Failed git diff → diff() returns empty string."""
    from app.core import git_helper

    with patch(_PATCH_TARGET, return_value=_fail("fatal: not a repository")):
        result = git_helper.diff(str(tmp_path))

    assert result == ""


# ---------------------------------------------------------------------------
# status (via ambient_context indirectly tested in test 9-10)
# ---------------------------------------------------------------------------

def test_get_status_clean(tmp_path):
    """Clean working tree → status returns GitStatus with empty lists."""
    from app.core import git_helper

    # Two git calls: rev-parse, status --porcelain=v2, log -1
    porcelain_output = "# branch.head main\n# branch.upstream origin/main\n# branch.ab +0 -0\n"

    call_count = 0
    def _side_effect(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if "rev-parse" in cmd:
            return _ok("true\n")
        if "status" in cmd:
            return _ok(porcelain_output)
        if "log" in cmd:
            return _ok("abc1234 Initial commit\n")
        return _ok()

    with patch(_PATCH_TARGET, side_effect=_side_effect):
        s = git_helper.status(str(tmp_path))

    assert s.is_repo is True
    assert s.branch == "main"
    assert s.staged == []
    assert s.modified == []
    assert s.untracked == []


def test_get_status_modified(tmp_path):
    """Porcelain output with a modified file → status.modified is populated."""
    from app.core import git_helper

    # Line format: "1 .M N... 100644 100644 100644 <sha> <sha> file.py"
    porcelain_output = (
        "# branch.head feature\n"
        "# branch.ab +1 -0\n"
        "1 .M N... 100644 100644 100644 aaa bbb app/foo.py\n"
    )

    def _side_effect(cmd, **kwargs):
        if "rev-parse" in cmd:
            return _ok("true\n")
        if "status" in cmd:
            return _ok(porcelain_output)
        if "log" in cmd:
            return _ok("abc1234 Fix bug\n")
        return _ok()

    with patch(_PATCH_TARGET, side_effect=_side_effect):
        s = git_helper.status(str(tmp_path))

    assert "app/foo.py" in s.modified


# ---------------------------------------------------------------------------
# ambient_context
# ---------------------------------------------------------------------------

def test_ambient_context_non_git_dir():
    """Non-existent directory → ambient_context returns empty string."""
    from app.core import git_helper

    result = git_helper.ambient_context("/nonexistent/path/xyz")
    assert result == ""


def test_ambient_context_git_dir(tmp_path):
    """Git repo → ambient_context returns non-empty string containing branch info."""
    from app.core import git_helper

    porcelain_output = "# branch.head main\n# branch.ab +0 -0\n"

    def _side_effect(cmd, **kwargs):
        if "rev-parse" in cmd:
            return _ok("true\n")
        if "status" in cmd:
            return _ok(porcelain_output)
        if "log" in cmd:
            return _ok("deadbeef Add tests\n")
        return _ok()

    with patch(_PATCH_TARGET, side_effect=_side_effect):
        result = git_helper.ambient_context(str(tmp_path))

    assert result != ""
    assert "main" in result
    assert "Git ambient context" in result


# ---------------------------------------------------------------------------
# recent commits (via status last_commit)
# ---------------------------------------------------------------------------

def test_recent_commits_last_commit(tmp_path):
    """Mocked 'git log -1' stdout → status.last_commit is populated."""
    from app.core import git_helper

    porcelain_output = "# branch.head main\n# branch.ab +0 -0\n"

    def _side_effect(cmd, **kwargs):
        if "rev-parse" in cmd:
            return _ok("true\n")
        if "status" in cmd:
            return _ok(porcelain_output)
        if "log" in cmd:
            return _ok("c0ffee1 Implement feature X\n")
        return _ok()

    with patch(_PATCH_TARGET, side_effect=_side_effect):
        s = git_helper.status(str(tmp_path))

    assert "c0ffee1" in s.last_commit
    assert "Implement feature X" in s.last_commit
