"""Thin wrapper around the ``git`` CLI for read-only ambient context.

No pygit2/GitPython dependency — just subprocess with timeouts.
Write operations (commit, push, stash, revert, reset) are gated by the caller.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.core import process_runner

_log = logging.getLogger("ilx_cli.git")
_TIMEOUT = 5


@dataclass
class GitStatus:
    is_repo:     bool       = False
    branch:      str        = ""
    upstream:    str        = ""
    ahead:       int        = 0
    behind:      int        = 0
    staged:      list[str]  = field(default_factory=list)
    modified:    list[str]  = field(default_factory=list)
    untracked:   list[str]  = field(default_factory=list)
    deleted:     list[str]  = field(default_factory=list)
    last_commit: str        = ""
    error:       str        = ""


def _run(args: list[str], cwd: str, timeout: int = _TIMEOUT) -> tuple[int, str, str]:
    r = process_runner.run(["git", *args], cwd=cwd, timeout=timeout)
    if not r.ok and r.returncode == -1:
        # Map process_runner error messages to legacy return codes
        if "Command not found" in r.stderr:
            return 127, "", "git not installed"
        if "Timed out" in r.stderr:
            return 124, "", f"git {args[0] if args else ''} timed out"
        return 1, r.stdout, r.stderr
    return r.returncode, r.stdout, r.stderr


def is_git_repo(working_folder: str) -> bool:
    """Return True if *working_folder* is inside a git repository."""
    if not working_folder or not Path(working_folder).is_dir():
        return False
    rc, sout, _ = _run(["rev-parse", "--is-inside-work-tree"], working_folder)
    return rc == 0 and sout.strip() == "true"


def status(working_folder: str) -> GitStatus:
    """Return a snapshot of the workspace git state. Never raises."""
    out = GitStatus()
    if not working_folder or not Path(working_folder).is_dir():
        return out

    rc, sout, _ = _run(["rev-parse", "--is-inside-work-tree"], working_folder)
    if rc != 0 or sout.strip() != "true":
        if rc == 127:
            out.error = "git not installed"
        return out
    out.is_repo = True

    rc, sout, _ = _run(["status", "--porcelain=v2", "--branch"], working_folder)
    if rc != 0:
        out.error = "status failed"
        return out

    for line in sout.splitlines():
        if line.startswith("# branch.head "):
            out.branch = line[len("# branch.head "):].strip()
        elif line.startswith("# branch.upstream "):
            out.upstream = line[len("# branch.upstream "):].strip()
        elif line.startswith("# branch.ab "):
            parts = line[len("# branch.ab "):].split()
            for p in parts:
                if p.startswith("+"):
                    try: out.ahead = int(p[1:])
                    except ValueError: pass
                elif p.startswith("-"):
                    try: out.behind = int(p[1:])
                    except ValueError: pass
        elif line.startswith("1 ") or line.startswith("2 "):
            parts = line.split(" ", 8)
            if len(parts) < 9:
                continue
            xy = parts[1]
            path = parts[-1]
            if xy[0] != ".":
                out.staged.append(path)
            if xy[1] == "M":
                out.modified.append(path)
            elif xy[1] == "D":
                out.deleted.append(path)
        elif line.startswith("? "):
            out.untracked.append(line[2:])

    rc, sout, _ = _run(["log", "-1", "--pretty=format:%h %s"], working_folder)
    if rc == 0 and sout.strip():
        out.last_commit = sout.strip().splitlines()[0][:120]
    return out


def diff(working_folder: str, *, staged: bool = False, max_lines: int = 800) -> str:
    """Return workspace diff (truncated). Empty string if not a repo."""
    if not working_folder:
        return ""
    args = ["diff", "--no-color"]
    if staged:
        args.append("--staged")
    rc, sout, _ = _run(args, working_folder)
    if rc != 0:
        return ""
    lines = sout.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [
            "",
            f"… diff truncated at {max_lines} lines ({len(sout.splitlines()) - max_lines} more not shown)",
        ]
    return "\n".join(lines)


def ambient_context(working_folder: str) -> str:
    """Compact one-block summary of repo state for prompt injection.

    Returns "" if the workspace isn't a git repo.
    """
    s = status(working_folder)
    if not s.is_repo:
        return ""
    parts: list[str] = ["[Git ambient context]"]
    head = f"branch: {s.branch}"
    if s.upstream:
        head += f"  ↔ {s.upstream}"
        if s.ahead or s.behind:
            head += f"  ({s.ahead} ahead, {s.behind} behind)"
    parts.append(head)
    if s.last_commit:
        parts.append(f"last commit: {s.last_commit}")

    def _fmt(label: str, paths: list[str], cap: int = 12) -> str | None:
        if not paths:
            return None
        suffix = f" (+{len(paths) - cap} more)" if len(paths) > cap else ""
        return f"{label} ({len(paths)}): " + ", ".join(paths[:cap]) + suffix

    for line in (
        _fmt("staged",    s.staged),
        _fmt("modified",  s.modified),
        _fmt("untracked", s.untracked),
        _fmt("deleted",   s.deleted),
    ):
        if line:
            parts.append(line)
    if all(not lst for lst in (s.staged, s.modified, s.untracked, s.deleted)):
        parts.append("working tree: clean")
    return "\n".join(parts)


def commit(working_folder: str, message: str, *, add_all: bool = False) -> tuple[bool, str]:
    """Stage (optionally) and create a commit. Returns (ok, output_or_error)."""
    if not message.strip():
        return False, "commit message cannot be empty"
    if add_all:
        rc, _, err = _run(["add", "-A"], working_folder, timeout=10)
        if rc != 0:
            return False, err.strip() or "git add failed"
    rc, sout, serr = _run(["commit", "-m", message], working_folder, timeout=10)
    if rc != 0:
        return False, (serr or sout).strip() or "git commit failed"
    return True, sout.strip()


def pull(folder: str, remote: str = "origin") -> tuple[bool, str]:
    """Run git pull in *folder*. Returns (success, output)."""
    rc, sout, serr = _run(["pull", remote], folder, timeout=30)
    out = sout.strip() or serr.strip()
    return rc == 0, out


def push(
    folder: str,
    remote: str = "origin",
    branch: str = "",
    *,
    force: bool = False,
) -> tuple[bool, str]:
    """Run git push in *folder*. Returns (success, output).

    force=True adds --force-with-lease (safer than --force).
    The caller is responsible for confirming with the user before passing force=True.
    """
    cmd = ["push", remote]
    if branch:
        cmd.append(branch)
    if force:
        cmd.append("--force-with-lease")
    rc, sout, serr = _run(cmd, folder, timeout=30)
    out = sout.strip() or serr.strip()
    return rc == 0, out


def stash(folder: str, sub: str = "") -> tuple[bool, str]:
    """Run git stash [pop|list] in *folder*. Returns (success, output).

    sub: "" = stash, "pop" = stash pop, "list" = stash list
    """
    if sub == "pop":
        cmd = ["stash", "pop"]
    elif sub == "list":
        cmd = ["stash", "list"]
    else:
        cmd = ["stash"]
    rc, sout, serr = _run(cmd, folder, timeout=15)
    out = sout.strip() or serr.strip()
    return rc == 0, out


def revert(folder: str, commit_hash: str) -> tuple[bool, str]:
    """Create a revert commit for *commit_hash*. Returns (success, output)."""
    rc, sout, serr = _run(
        ["revert", "--no-edit", commit_hash], folder, timeout=15
    )
    out = sout.strip() or serr.strip()
    return rc == 0, out


def show_commit(folder: str, commit_hash: str) -> tuple[bool, str]:
    """Return a short summary of *commit_hash* for preview. Returns (ok, text)."""
    rc, sout, serr = _run(
        ["show", "--stat", "--no-patch", commit_hash], folder, timeout=10
    )
    if rc != 0:
        return False, (serr or sout).strip()
    return True, sout.strip()


def reset_file(folder: str, filepath: str) -> tuple[bool, str]:
    """Unstage a specific file (git reset HEAD <file>). Returns (success, output)."""
    rc, sout, serr = _run(["reset", "HEAD", "--", filepath], folder, timeout=10)
    out = sout.strip() or serr.strip()
    return rc == 0, out


def staged_diff(folder: str, max_lines: int = 800) -> str:
    """Return the staged diff text (for ai-commit). Empty string on failure."""
    return diff(folder, staged=True, max_lines=max_lines)


def current_branch(working_folder: str) -> str:
    rc, sout, _ = _run(["branch", "--show-current"], working_folder)
    return sout.strip() if rc == 0 else ""
