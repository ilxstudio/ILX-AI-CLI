"""Centralised subprocess helper — fixes Windows handle issues."""
from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass

# keys that should never reach a child process — API keys, secrets, tokens
_SENSITIVE_ENV_PREFIXES = (
    "ANTHROPIC_", "OPENAI_", "GROQ_", "GEMINI_", "HUGGINGFACE_", "HF_",
    "AWS_", "AZURE_", "GITHUB_TOKEN", "SENDGRID_", "STRIPE_", "TWILIO_",
    "ILX_KEY",
)

# non-secret keys that are always safe to pass through
_SAFE_ENV_KEYS = {
    "PATH", "PYTHONPATH", "SYSTEMROOT", "COMSPEC", "HOME", "USERPROFILE",
    "USERNAME", "LANG", "TZ", "TERM", "COLORTERM", "COLUMNS", "LINES",
    "VIRTUAL_ENV", "CONDA_PREFIX", "JAVA_HOME", "NODE_PATH",
}


def _sanitized_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with sensitive variables removed."""
    _bad_suffixes = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD")
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        upper = k.upper()
        if upper in _SAFE_ENV_KEYS:
            env[k] = v
            continue
        if upper.startswith(_SENSITIVE_ENV_PREFIXES):
            continue
        if any(upper.endswith(s) for s in _bad_suffixes):
            continue
        env[k] = v
    return env


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
    env: dict[str, str] | None = None,
    inherit_env: bool = False,
) -> ProcessResult:
    """Run *cmd* as a subprocess and return a :class:`ProcessResult`."""
    if env is None:
        child_env: dict[str, str] | None = None if inherit_env else _sanitized_env()
    else:
        child_env = env

    kwargs: dict[str, object] = {
        "cwd": cwd,
        "timeout": timeout,
        "env": child_env,
    }

    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
        kwargs["encoding"] = "utf-8"
        kwargs["errors"] = "replace"

    if platform.system() == "Windows":
        # no special creation flags — avoids WinError 6/50 when CREATE_NO_WINDOW
        # or STARTF_USESHOWWINDOW are combined with PIPE stdio in headless contexts
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
