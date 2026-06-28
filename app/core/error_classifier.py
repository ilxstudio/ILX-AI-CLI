"""Error classification for LLM API errors — taxonomy and recovery strategies.

Based on production patterns from Anthropic, OpenAI, and Groq APIs.
Classifies errors into: TRANSIENT, RATE_LIMIT, AUTH, QUOTA, CONTENT_POLICY,
CONTEXT_LENGTH, MODEL_NOT_FOUND, PERMANENT.

Each class has a recommended recovery strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class ErrorClass(Enum):
    TRANSIENT       = auto()   # Network/timeout — retry with backoff
    RATE_LIMIT      = auto()   # 429 — wait retry-after, then retry
    AUTH            = auto()   # 401 — don't retry, tell user to check API key
    QUOTA           = auto()   # 402/quota exceeded — don't retry, inform user
    CONTENT_POLICY  = auto()   # 400 content filter — don't retry
    CONTEXT_LENGTH  = auto()   # 400 context too long — compact and retry
    MODEL_NOT_FOUND = auto()   # 404 model — don't retry, suggest alternatives
    PERMANENT       = auto()   # Other 4xx/5xx — don't retry


@dataclass
class ClassifiedError:
    original: Exception
    error_class: ErrorClass
    message: str           # User-friendly message
    should_retry: bool
    retry_after: int       # Seconds (0 = use default backoff)
    suggestion: str        # Actionable advice for the user


def _parse_retry_after(headers: object) -> int:
    """Parse the Retry-After header value (seconds), capped at 120.

    *headers* may be any mapping-like object or None.
    Returns 0 if the header is absent or unparseable.
    """
    if headers is None:
        return 0
    try:
        raw = headers.get("retry-after", "") or headers.get("Retry-After", "")
    except Exception:
        return 0
    if not raw:
        return 0
    try:
        return min(int(float(str(raw))), 120)
    except (ValueError, TypeError):
        return 0


def _body_contains(response: object, *keywords: str) -> bool:
    """Return True if the response body (text) contains any of *keywords* (case-insensitive)."""
    try:
        body = (response.text or "").lower()  # type: ignore[union-attr]
    except Exception:
        body = ""
    return any(kw.lower() in body for kw in keywords)


def classify_error(exc: Exception, provider: str = "") -> ClassifiedError:
    """Classify an LLM API exception into a structured error with recovery advice.

    Covers:
    - httpx connectivity errors  → TRANSIENT
    - HTTP 429                   → RATE_LIMIT (parse Retry-After)
    - HTTP 401                   → AUTH
    - HTTP 402 / quota body      → QUOTA
    - HTTP 400 + content/policy  → CONTENT_POLICY
    - HTTP 400 + context/token   → CONTEXT_LENGTH
    - HTTP 404 + model body      → MODEL_NOT_FOUND
    - All other HTTP errors      → PERMANENT

    Returns a ClassifiedError with all fields populated.
    """
    import httpx

    label = provider or "the API"

    # ── Transient connectivity errors ─────────────────────────────────────────
    _TRANSIENT_TYPES = (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.RemoteProtocolError,
    )
    if isinstance(exc, _TRANSIENT_TYPES):
        return ClassifiedError(
            original=exc,
            error_class=ErrorClass.TRANSIENT,
            message=f"Connection to {label} failed: {exc}",
            should_retry=True,
            retry_after=0,
            suggestion=(
                "Check your network connection and that the server is reachable. "
                "The request will be retried automatically."
            ),
        )

    # ── HTTP status errors ────────────────────────────────────────────────────
    if isinstance(exc, httpx.HTTPStatusError):
        resp = exc.response
        code = resp.status_code

        # 429 — rate limited
        if code == 429:
            wait = _parse_retry_after(resp.headers)
            wait_clause = f" Wait {wait}s before retrying." if wait else ""
            return ClassifiedError(
                original=exc,
                error_class=ErrorClass.RATE_LIMIT,
                message=f"{label} rate limit (HTTP 429).{wait_clause}",
                should_retry=True,
                retry_after=wait,
                suggestion=(
                    f"You have been rate-limited by {label}.{wait_clause} "
                    "Slow down request frequency or upgrade your plan."
                ),
            )

        # 401 — authentication
        if code == 401:
            return ClassifiedError(
                original=exc,
                error_class=ErrorClass.AUTH,
                message=f"{label} authentication failed (HTTP 401). Check your API key.",
                should_retry=False,
                retry_after=0,
                suggestion="Run /apikey set to update your API key.",
            )

        # 402 — payment required, or body mentions quota
        if code == 402 or _body_contains(resp, "quota"):
            return ClassifiedError(
                original=exc,
                error_class=ErrorClass.QUOTA,
                message=f"{label} quota exceeded (HTTP {code}). Add credits to your account.",
                should_retry=False,
                retry_after=0,
                suggestion="Check your billing at provider dashboard.",
            )

        # 400 — bad request; distinguish sub-cases by body
        if code == 400:
            if _body_contains(resp, "content", "policy", "safety"):
                return ClassifiedError(
                    original=exc,
                    error_class=ErrorClass.CONTENT_POLICY,
                    message=(
                        f"{label} rejected the request due to content policy (HTTP 400). "
                        "The message was flagged by the provider's safety filters."
                    ),
                    should_retry=False,
                    retry_after=0,
                    suggestion=(
                        "Rephrase your request to avoid content that triggers safety filters. "
                        "Review the provider's usage policies."
                    ),
                )
            if _body_contains(resp, "context", "token", "length", "maximum"):
                return ClassifiedError(
                    original=exc,
                    error_class=ErrorClass.CONTEXT_LENGTH,
                    message=(
                        f"{label} rejected the request because the context is too long (HTTP 400). "
                        "Reduce the number of messages or file content."
                    ),
                    should_retry=False,
                    retry_after=0,
                    suggestion="Run /compact to reduce context size.",
                )
            # Generic 400
            return ClassifiedError(
                original=exc,
                error_class=ErrorClass.PERMANENT,
                message=f"{label} bad request (HTTP 400): {str(exc)[:200]}",
                should_retry=False,
                retry_after=0,
                suggestion=(
                    "Review the request payload. Run /diag to check system state "
                    "or /help for available commands."
                ),
            )

        # 404 — check if it's a missing model
        if code == 404 and _body_contains(resp, "model"):
            return ClassifiedError(
                original=exc,
                error_class=ErrorClass.MODEL_NOT_FOUND,
                message=(
                    f"{label} could not find the requested model (HTTP 404). "
                    "The model name may be misspelled or not available on this provider."
                ),
                should_retry=False,
                retry_after=0,
                suggestion="Run /model to switch to an available model.",
            )

        # 5xx — server-side transient errors, retry with backoff
        if 500 <= code < 600:
            retry_after = 30 if code == 529 else 10
            return ClassifiedError(
                original=exc,
                error_class=ErrorClass.TRANSIENT,
                message=f"{label} server error (HTTP {code}) — retrying.",
                should_retry=True,
                retry_after=retry_after,
                suggestion=(
                    "The provider is experiencing a transient server-side error. "
                    "The request will be retried automatically."
                ),
            )

        # All other HTTP errors — permanent
        return ClassifiedError(
            original=exc,
            error_class=ErrorClass.PERMANENT,
            message=f"{label} returned HTTP {code}: {str(exc)[:200]}",
            should_retry=False,
            retry_after=0,
            suggestion=(
                "This error is unlikely to resolve on retry. Run /diag to check "
                "system diagnostics or /crashes for recent error history."
            ),
        )

    # ── Fallback — unknown exception type ─────────────────────────────────────
    return ClassifiedError(
        original=exc,
        error_class=ErrorClass.PERMANENT,
        message=f"Unexpected error from {label}: {exc}",
        should_retry=False,
        retry_after=0,
        suggestion=(
            "Run /diag to check system diagnostics or /crashes to view recent errors."
        ),
    )
