"""Pre/Post tool-use hooks — shell-command driven extension points."""
from __future__ import annotations

import fnmatch
import json
import logging
import os
import shlex
import string
from dataclasses import dataclass, field
from pathlib import Path

from app.core import process_runner

_log = logging.getLogger("ilx_cli.hooks")
_CFG_PATH = Path.home() / ".ilx_cli" / "hooks.json"
_DEFAULT_TIMEOUT = 10

KNOWN_EVENTS = {"PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"}

# shared prefix list — other modules can import this instead of duplicating it
_SENSITIVE_ENV_PREFIXES: tuple[str, ...] = (
    "ANTHROPIC_", "OPENAI_", "GROQ_", "GEMINI_", "HUGGINGFACE_", "HF_",
    "AWS_", "AZURE_", "GITHUB_TOKEN", "SENDGRID_", "STRIPE_", "TWILIO_",
    "ILX_KEY", "GOOGLE_", "GCP_", "GCLOUD_", "DOCKER_", "GITLAB_",
    "BITBUCKET_", "DATABASE_", "POSTGRES_", "MYSQL_", "REDIS_", "MAILGUN_",
    "ILX_",
)

# these chars in a hook argument would mean the user is trying to do shell injection
_SHELL_METACHARACTERS = frozenset(";|&`$()<>")

_HOME = Path.home()


@dataclass
class HookResult:
    allowed: bool = True
    reason:  str  = ""
    extra:   dict = field(default_factory=dict)


@dataclass
class _HookSpec:
    event:   str
    match:   dict
    command: str
    timeout: float
    async_:  bool = False


# load and parse hooks.json — invalid entries are skipped rather than crashing
def _load_specs() -> list[_HookSpec]:
    try:
        raw = json.loads(_CFG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        _log.warning("hooks.json: top-level must be an object")
        return []
    out: list[_HookSpec] = []
    for event, items in raw.items():
        if not isinstance(items, list):
            continue
        for entry in items:
            if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
                continue
            out.append(_HookSpec(
                event=event,
                match=entry.get("match", {}) or {},
                command=entry["command"],
                timeout=float(entry.get("timeout", _DEFAULT_TIMEOUT)),
                async_=bool(entry.get("async", False)),
            ))
    return out


def validate_config(text: str | None = None) -> list[str]:
    """Return human-readable errors for hooks.json; empty list = valid."""
    if text is None:
        try:
            text = _CFG_PATH.read_text(encoding="utf-8")
        except OSError:
            return []
    if not text.strip():
        return []
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"JSON parse error: {exc}"]
    errs: list[str] = []
    if not isinstance(raw, dict):
        errs.append("top-level must be an object keyed by event name")
        return errs
    for event, entries in raw.items():
        if event not in KNOWN_EVENTS:
            errs.append(f"unknown event {event!r} (known: {sorted(KNOWN_EVENTS)})")
        if not isinstance(entries, list):
            errs.append(f"{event!r}: must be an array")
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errs.append(f"{event}[{i}]: must be an object")
                continue
            cmd = entry.get("command")
            if not isinstance(cmd, str) or not cmd.strip():
                errs.append(f"{event}[{i}]: 'command' must be a non-empty string")
            if "match" in entry and not isinstance(entry["match"], dict):
                errs.append(f"{event}[{i}]: 'match' must be an object")
            if "timeout" in entry:
                try:
                    t = float(entry["timeout"])
                    if t <= 0 or t > 600:
                        errs.append(f"{event}[{i}]: 'timeout' must be in (0, 600]")
                except (TypeError, ValueError):
                    errs.append(f"{event}[{i}]: 'timeout' must be a number")
    return errs


def _payload_matches(payload: dict, match: dict) -> bool:
    for key, expected in match.items():
        actual = payload.get(key)
        if actual is None:
            return False
        if isinstance(expected, str):
            if not fnmatch.fnmatchcase(str(actual), expected):
                return False
        else:
            if actual != expected:
                return False
    return True


# safe Template substitute — missing keys become empty strings instead of raising
class _SafeFmt(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _expand(cmd: str, payload: dict) -> str:
    try:
        return string.Template(cmd).safe_substitute(_SafeFmt(payload))
    except Exception:
        return cmd


def _sanitized_env() -> dict[str, str]:
    """Return a sanitized copy of ``os.environ`` for hook subprocesses."""
    env: dict[str, str] = {}
    _bad_suffixes = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD")
    for k, v in os.environ.items():
        upper = k.upper()
        if upper.startswith(_SENSITIVE_ENV_PREFIXES):
            continue
        if any(upper.endswith(s) for s in _bad_suffixes):
            continue
        if upper in {"API_KEY", "APIKEY", "PASSWORD", "PASSWD"}:
            continue
        env[k] = v
    return env


def _validate_hook_command(cmd: list[str]) -> tuple[bool, str]:
    """Validate a hook command list before execution.

    Returns ``(True, "")`` if safe, or ``(False, reason)`` if it should be rejected.
    """
    if not cmd:
        return False, "empty command"

    for i, arg in enumerate(cmd):
        bad = _SHELL_METACHARACTERS.intersection(arg)
        if bad:
            chars = "".join(sorted(bad))
            return False, (
                f"argument {i} contains shell metacharacter(s) {chars!r}: {arg!r}"
            )

    executable = cmd[0]
    # bare names like "git" or "python" are fine — only check absolute paths
    if os.sep in executable or (os.altsep and os.altsep in executable):
        exec_path = Path(executable)
        if exec_path.is_absolute():
            try:
                exec_path.relative_to(_HOME)
            except ValueError:
                # not under home — only allow if it's the canonical PATH entry
                import shutil
                if shutil.which(exec_path.name) != str(exec_path):
                    return False, (
                        f"executable is an absolute path outside home directory: {executable!r}"
                    )

    return True, ""


def _run_hook(spec: _HookSpec, payload: dict) -> tuple[int, str]:
    cmd = _expand(spec.command, payload)
    args = shlex.split(cmd)

    valid, reason = _validate_hook_command(args)
    if not valid:
        _log.warning("hook command rejected (security validation failed): %s — %s", spec.command, reason)
        from app.core import audit as _audit
        _audit.log_risk_event(
            kind="hook_rejected",
            detail=f"Hook command rejected — {reason}",
            severity="medium",
            target=cmd[:100],
        )
        return 1, f"hook rejected: {reason}"

    r = process_runner.run(args, timeout=int(spec.timeout), env=_sanitized_env())
    if not r.ok and r.returncode == -1:
        if "Timed out" in r.stderr:
            return 124, f"hook timed out after {spec.timeout}s"
        if "Command not found" in r.stderr:
            return 127, f"hook command not found: {args!r}"
        return 1, r.stderr
    msg = (r.stderr or r.stdout or "").strip()
    return r.returncode, msg


def trigger(event: str, payload: dict | None = None) -> HookResult:
    """Run all hooks for ``event``. First exit-2 blocks; async hooks can't block."""
    import threading
    payload = payload or {}
    for spec in _load_specs():
        if spec.event != event:
            continue
        if not _payload_matches(payload, spec.match):
            continue
        if spec.async_:
            # fire and forget — can't block the main flow
            threading.Thread(
                target=_run_hook, args=(spec, payload), daemon=True,
                name=f"ilx-hook-{event}",
            ).start()
            continue
        rc, msg = _run_hook(spec, payload)
        if rc == 2:
            return HookResult(allowed=False, reason=msg or "blocked by hook")
        if rc != 0:
            _log.warning("hook %r exit %d: %s", spec.command, rc, msg)
    return HookResult(allowed=True)
