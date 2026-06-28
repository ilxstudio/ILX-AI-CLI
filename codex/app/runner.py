from __future__ import annotations

import os
import queue as _queue
import shlex
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

MAX_OUTPUT = 10_000
_SENTINEL  = object()
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass
class RunResult:
    exit_code: int
    stdout:    str
    stderr:    str
    timed_out: bool = False


def _split_command(command: str) -> list[str]:
    return shlex.split(command, posix=(os.name != "nt"))


def _policy_python(argv: list[str]) -> tuple[bool, str]:
    if len(argv) < 2:
        return False, "python needs a file or '-m module'"
    head = argv[1]
    if head in ("-c", "--command"):
        return False, "python -c (inline code) is not allowed"
    if head == "-m":
        if len(argv) < 3 or not argv[2]:
            return False, "python -m needs a module name"
        return True, ""
    if head.startswith("-") and head not in ("-O", "-OO", "-u", "-X"):
        return False, f"python option {head!r} is not in the agent allowlist"
    return True, ""


def _policy_pytest(argv: list[str]) -> tuple[bool, str]:
    safe_flags = {
        "-v", "-vv", "-q", "-x", "-s", "--tb", "-k", "-m",
        "--maxfail", "--collect-only", "-p", "--no-header", "-ra",
    }
    for tok in argv[1:]:
        if not tok.startswith("-"):
            continue
        head = tok.split("=", 1)[0]
        if head not in safe_flags:
            return False, f"pytest flag {head!r} is not in the agent allowlist"
    return True, ""


def _policy_pip(argv: list[str]) -> tuple[bool, str]:
    if len(argv) < 2:
        return True, ""
    sub = argv[1].lower()
    safe_subs = {"install", "uninstall", "list", "show", "freeze", "check", "config", "--version", "-V"}
    if sub not in safe_subs:
        return False, f"pip subcommand {sub!r} is not in the agent allowlist"
    return True, ""


def _policy_npm(argv: list[str]) -> tuple[bool, str]:
    if len(argv) < 2:
        return True, ""
    sub = argv[1].lower()
    safe_subs = {"test", "run", "run-script", "install", "i", "ci", "list", "ls", "version", "-v", "--version", "audit"}
    if sub not in safe_subs:
        return False, f"npm subcommand {sub!r} is not in the agent allowlist"
    return True, ""


def _policy_node(argv: list[str]) -> tuple[bool, str]:
    if len(argv) < 2:
        return False, "node needs a script file"
    head = argv[1]
    if head in ("-e", "--eval", "-p", "--print"):
        return False, f"node {head} (inline code) is not allowed"
    return True, ""


def _policy_permissive(argv: list[str]) -> tuple[bool, str]:
    return True, ""


def _policy_git(argv: list[str]) -> tuple[bool, str]:
    if len(argv) < 2:
        return True, ""
    blocked = {"push", "remote", "fetch", "clone"}
    sub = argv[1].lower()
    if sub in blocked:
        return False, f"git subcommand {sub!r} is blocked in agent context"
    return True, ""


def _policy_shell(argv: list[str]) -> tuple[bool, str]:
    if len(argv) < 2:
        return False, f"{argv[0]} requires arguments"
    if argv[1] in ("-c", "--command"):
        return False, f"{argv[0]} -c (inline shell) is not allowed"
    return True, ""


_POLICIES: dict[str, Callable[[list[str]], tuple[bool, str]]] = {
    "python":  _policy_python,
    "python3": _policy_python,
    "pytest":  _policy_pytest,
    "pip":     _policy_pip,
    "pip3":    _policy_pip,
    "npm":     _policy_npm,
    "npx":     _policy_permissive,
    "node":    _policy_node,
    "make":    _policy_permissive,
    "cmake":   _policy_permissive,
    "git":     _policy_git,
    "bash":    _policy_shell,
    "sh":      _policy_shell,
    "cargo":   _policy_permissive,
    "rustc":   _policy_permissive,
    "go":      _policy_permissive,
    "java":    _policy_permissive,
    "javac":   _policy_permissive,
    "mvn":     _policy_permissive,
    "gradle":  _policy_permissive,
}


class CommandRunner:
    ALLOWED = set(_POLICIES.keys())

    def __init__(self, cwd: Path):
        self.cwd = cwd

    def run(
        self,
        command:  str,
        timeout:  int = 30,
        on_line:  Callable[[str, str], None] | None = None,
    ) -> RunResult:
        try:
            argv = _split_command(command)
        except ValueError as exc:
            msg = f"Could not parse command: {exc}"
            if on_line:
                on_line("stderr", msg)
            return RunResult(exit_code=1, stdout="", stderr=msg)
        if not argv:
            msg = "Empty command."
            if on_line:
                on_line("stderr", msg)
            return RunResult(exit_code=1, stdout="", stderr=msg)

        first_token = argv[0]
        check_token = (Path(first_token).stem or first_token).lower()
        policy = _POLICIES.get(check_token)
        if policy is None:
            msg = (f"Command '{first_token}' not allowed. "
                   f"Known commands: {sorted(_POLICIES.keys())}")
            if on_line:
                on_line("stderr", msg)
            return RunResult(exit_code=1, stdout="", stderr=msg)

        normalized_argv = [check_token] + list(argv[1:])
        ok, reason = policy(normalized_argv)
        if not ok:
            msg = f"Command rejected by policy: {reason}"
            if on_line:
                on_line("stderr", msg)
            return RunResult(exit_code=1, stdout="", stderr=msg)

        resolved = shutil.which(argv[0])
        if resolved is not None:
            argv[0] = resolved

        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.cwd,
                bufsize=1,
                creationflags=_NO_WINDOW,
            )
            q: _queue.Queue = _queue.Queue()

            def _read(stream, stream_type: str) -> None:
                try:
                    for raw in stream:
                        line = raw.rstrip("\n")
                        if line:
                            q.put((stream_type, line))
                finally:
                    q.put(_SENTINEL)

            t_out = threading.Thread(target=_read, args=(proc.stdout, "stdout"), daemon=True)
            t_err = threading.Thread(target=_read, args=(proc.stderr, "stderr"), daemon=True)
            t_out.start()
            t_err.start()

            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            deadline   = monotonic() + timeout
            timed_out  = False
            done_count = 0

            while done_count < 2:
                remaining = deadline - monotonic()
                if remaining <= 0 and not timed_out:
                    proc.kill()
                    timed_out = True
                try:
                    item = q.get(timeout=0.05)
                except _queue.Empty:
                    continue
                if item is _SENTINEL:
                    done_count += 1
                    continue
                stream_type, line = item
                (stdout_lines if stream_type == "stdout" else stderr_lines).append(line)
                if on_line and not timed_out:
                    on_line(stream_type, line)

            t_out.join(timeout=3)
            t_err.join(timeout=3)
            return_code = proc.wait(timeout=1)

            stdout = "\n".join(stdout_lines)
            stderr = "\n".join(stderr_lines)
            if len(stdout) > MAX_OUTPUT:
                stdout = stdout[-MAX_OUTPUT:]
            if len(stderr) > MAX_OUTPUT:
                stderr = stderr[-MAX_OUTPUT:]

            return RunResult(
                exit_code=return_code if not timed_out else 124,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
            )

        except Exception as exc:
            if on_line:
                on_line("stderr", str(exc))
            return RunResult(exit_code=1, stdout="", stderr=str(exc))
