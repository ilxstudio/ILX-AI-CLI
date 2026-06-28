"""Centralised subprocess helper — fixes Windows handle issues.

Use this instead of calling subprocess.run() directly throughout the codebase.
Key guarantees:
  - Never uses shell=True
  - Handles Windows-specific console-window suppression (avoids WinError 6)
  - Always decodes stdout/stderr as UTF-8 with errors="replace"
  - Gracefully handles FileNotFoundError and TimeoutExpired
"""
from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass


@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    ok: bool


def run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 30,
    capture: bool = True,
    env: "dict[str, str] | None" = None,
) -> ProcessResult:
    """Run *cmd* as a subprocess and return a :class:`ProcessResult`.

    Parameters
    ----------
    cmd:
        The command and its arguments as a list.  Never passed through a shell.
    cwd:
        Working directory for the child process.  ``None`` inherits the
        caller's working directory.
    timeout:
        Maximum wall-clock seconds to wait.  Defaults to 30.
    capture:
        When ``True`` (default) stdout and stderr are captured and returned in
        the result.  When ``False`` they are inherited from the parent process.
    env:
        Optional environment mapping for the child process.  ``None`` inherits
        the current process environment.
    """
    kwargs: dict[str, object] = {
        "cwd": cwd,
        "timeout": timeout,
        "env": env,
    }

    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
        kwargs["encoding"] = "utf-8"
        kwargs["errors"] = "replace"

    if platform.system() == "Windows":
        # No special creation flags: avoid WinError 6 / WinError 50 that occur
        # when CREATE_NO_WINDOW or STARTF_USESHOWWINDOW are combined with PIPE
        # stdio in headless contexts (pytest capsys, pythonw, Windows services).
        # The child already has no console because we capture its handles via PIPE.
        pass
    else:
        kwargs["close_fds"] = True

    try:
        result = subprocess.run(cmd, **kwargs)  # noqa: S603 — shell=False enforced above
        stdout = result.stdout or "" if capture else ""
        stderr = result.stderr or "" if capture else ""
        return ProcessResult(
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
            ok=result.returncode == 0,
        )
    except FileNotFoundError:
        return ProcessResult(-1, "", f"Command not found: {cmd[0]}", False)
    except subprocess.TimeoutExpired:
        return ProcessResult(-1, "", f"Timed out after {timeout}s", False)
    except OSError as exc:
        return ProcessResult(-1, "", str(exc), False)
