from __future__ import annotations
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_LOG_PATH = Path.home() / ".ilx_cli" / "logs" / "audit.log"
_MAX_BYTES = 5 * 1024 * 1024
_MAX_KEEP  = 5

_logger = logging.getLogger("ilx_cli.audit")

# Field names (exact or substring) whose string values must never appear in logs.
# Checked case-insensitively so "API_KEY", "api_key", "ApiKey" all match.
_SECRET_FIELD_SUBSTRINGS = (
    "api_key", "apikey", "api_token", "access_token",
    "secret", "password", "passwd", "credential",
    "private_key", "access_key", "auth_token",
)


_SECRET_VALUE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{35}"),
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
)


def _redact(value: str) -> str:
    """Replace known secret patterns in *value* with ``[REDACTED]``."""
    for pattern in _SECRET_VALUE_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def _redact_fields(fields: dict) -> dict:
    """Return a copy of *fields* with secret-shaped string values replaced.

    Any field whose name contains a known secret keyword is replaced with
    '<redacted>' so that API keys, passwords, and tokens are never written
    to the on-disk audit log.
    """
    safe: dict = {}
    for k, v in fields.items():
        k_lower = k.lower()
        if isinstance(v, str) and v and any(sub in k_lower for sub in _SECRET_FIELD_SUBSTRINGS):
            safe[k] = "<redacted>"
        elif isinstance(v, str):
            safe[k] = _redact(v)
        else:
            safe[k] = v
    return safe


def _rotate_if_needed() -> None:
    try:
        if not _LOG_PATH.exists():
            return
        if _LOG_PATH.stat().st_size < _MAX_BYTES:
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rotated = _LOG_PATH.with_suffix(f".log.{ts}")
        _LOG_PATH.rename(rotated)
        siblings = sorted(_LOG_PATH.parent.glob("audit.log.*"))
        for old in siblings[:-_MAX_KEEP]:
            try:
                old.unlink()
            except OSError as exc:
                _logger.debug("audit: failed to unlink rotated log %s: %s", old, exc)
    except OSError as exc:
        _logger.debug("audit: rotate skipped: %s", exc)


def log_event(event_type: str, **fields: Any) -> None:
    record = {
        "ts":    datetime.now(timezone.utc).isoformat(),
        "pid":   os.getpid(),
        "event": event_type,
    }
    # Redact secret-shaped fields before writing; never log raw API keys or passwords.
    safe_fields = _redact_fields(fields)
    for k, v in safe_fields.items():
        try:
            json.dumps(v)
            record[k] = v
        except (TypeError, ValueError):
            record[k] = repr(v)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _LOCK:
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed()
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as exc:
            _logger.debug("audit log write failed: %s", exc)


def log_command(command: list[str], cwd: str, allowed: bool,
                duration_ms: float = 0.0, exit_code: int | None = None) -> None:
    log_event("command_exec", command=command, cwd=cwd, allowed=allowed,
              duration_ms=round(duration_ms, 1), exit_code=exit_code)


def log_file_op(op_type: str, path: str, allowed: bool, bytes_written: int = 0,
                duration_ms: float = 0.0) -> None:
    log_event("file_op", op_type=op_type, path=path, allowed=allowed,
              bytes=bytes_written, duration_ms=round(duration_ms, 1))


def log_permission_change(mode: str) -> None:
    log_event("permission_mode_changed", mode=mode)


def log_permission_decision(*, kind: str, target: str, decision: str,
                             mode: str, source: str, detail: str = "") -> None:
    log_event("permission_decision", kind=kind, target=target,
              decision=decision, mode=mode, source=source, detail=detail)


def log_egress(*, url: str, method: str, status: int | None = None,
               bytes_in: int = 0, bytes_out: int = 0,
               duration_ms: float = 0.0, model: str = "") -> None:
    log_event("egress", url=url, method=method, status=status,
              bytes_in=bytes_in, bytes_out=bytes_out,
              duration_ms=round(duration_ms, 1), model=model)


def log_llm_call(
    model: str,
    prompt_tokens: int,
    response_tokens: int,
    latency_ms: float,
    provider: str = "ollama",
    error: str | None = None,
) -> None:
    """Record a completed LLM call with timing and token counts."""
    log_event(
        "llm_call",
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        response_tokens=response_tokens,
        total_tokens=prompt_tokens + response_tokens,
        latency_ms=round(latency_ms, 1),
        error=error,
    )
