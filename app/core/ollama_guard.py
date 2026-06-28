"""Ollama connection guard — exponential backoff and circuit breaker.

Usage:
    from app.core.ollama_guard import with_backoff, circuit

    result = with_backoff(lambda: httpx.get(url, timeout=5))
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

_log = logging.getLogger("ilx_cli.ollama_guard")
_T = TypeVar("_T")

# ── Circuit breaker state ─────────────────────────────────────────────────────

_FAILURE_THRESHOLD = 3      # consecutive failures before opening
_RECOVERY_TIMEOUT  = 60.0   # seconds before probing again
_BACKOFF_BASE      = 1.0    # initial retry delay in seconds
_BACKOFF_MAX       = 30.0   # cap on retry delay
_MAX_RETRIES       = 5

_lock         = threading.Lock()
_failures     = 0
_opened_at: float | None = None
_state        = "closed"   # "closed" | "open" | "half-open"


def _record_success() -> None:
    global _failures, _state, _opened_at
    with _lock:
        _failures   = 0
        _state      = "closed"
        _opened_at  = None


def _record_failure() -> None:
    global _failures, _state, _opened_at
    with _lock:
        _failures += 1
        if _failures >= _FAILURE_THRESHOLD and _state == "closed":
            _state     = "open"
            _opened_at = time.monotonic()
            _log.warning("Circuit OPEN after %d consecutive failures", _failures)


def _is_open() -> bool:
    global _state, _opened_at
    with _lock:
        if _state == "closed":
            return False
        if _state == "open":
            assert _opened_at is not None
            if time.monotonic() - _opened_at >= _RECOVERY_TIMEOUT:
                _state = "half-open"
                _log.info("Circuit HALF-OPEN — probing Ollama")
                return False   # allow one probe
            return True
        return False  # half-open: allow probe


def circuit_state() -> str:
    with _lock:
        return _state


def with_backoff(fn: Callable[[], _T], label: str = "Ollama request") -> _T:
    """Call *fn* with exponential backoff. Respects the circuit breaker.

    Raises the last exception if all retries are exhausted.
    """
    if _is_open():
        raise RuntimeError(
            f"Circuit breaker OPEN — Ollama unreachable. "
            f"Retry in {_RECOVERY_TIMEOUT:.0f}s or use /healthcheck."
        )

    delay = _BACKOFF_BASE
    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result = fn()
            _record_success()
            return result
        except Exception as exc:
            last_exc = exc
            _record_failure()
            if attempt < _MAX_RETRIES:
                jitter = delay * 0.1 * (attempt % 3)
                sleep_for = min(delay + jitter, _BACKOFF_MAX)
                _log.debug("%s attempt %d/%d failed (%s) — retrying in %.1fs",
                           label, attempt, _MAX_RETRIES, exc, sleep_for)
                time.sleep(sleep_for)
                delay = min(delay * 2, _BACKOFF_MAX)
            else:
                _log.error("%s failed after %d attempts: %s", label, _MAX_RETRIES, exc)

    raise last_exc
