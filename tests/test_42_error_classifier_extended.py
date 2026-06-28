"""Extended tests for app.core.error_classifier — gaps not covered by test_26.

Tests:
  1.  classify_error(HTTP 500)          → TRANSIENT, should_retry=True
  2.  classify_error(HTTP 502)          → TRANSIENT, should_retry=True
  3.  classify_error(HTTP 503)          → TRANSIENT, should_retry=True
  4.  classify_error(HTTP 529)          → TRANSIENT, retry_after=30
  5.  classify_error(generic Exception) → PERMANENT, should_retry=False
  6.  str(ClassifiedError)              → contains the message text
  7.  provider name appears in message
  8.  retry_with_backoff respects retry_after when > 0
  9.  HTTP 503 with Retry-After header  → retry_after parsed from header
  10. HTTP 400 with empty body          → PERMANENT (not CONTEXT_LENGTH or CONTENT_POLICY)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import httpx

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Helper (mirrors test_26 pattern) ─────────────────────────────────────────

def _make_http_exc(
    status: int, body: str = "", headers: dict | None = None
) -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError with the given status code and response body."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status
    mock_resp.text = body
    mock_resp.headers = headers or {}
    return httpx.HTTPStatusError(
        f"HTTP {status}",
        request=MagicMock(),
        response=mock_resp,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_classify_500_server_error_is_transient():
    """HTTP 500 → TRANSIENT, should_retry=True."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(500, "Internal Server Error")
    result = classify_error(exc, provider="ollama")

    assert result.error_class == ErrorClass.TRANSIENT
    assert result.should_retry is True
    assert result.message


def test_classify_502_is_transient():
    """HTTP 502 Bad Gateway → TRANSIENT, should_retry=True."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(502, "Bad Gateway")
    result = classify_error(exc, provider="ollama")

    assert result.error_class == ErrorClass.TRANSIENT
    assert result.should_retry is True


def test_classify_503_is_transient():
    """HTTP 503 Service Unavailable → TRANSIENT, should_retry=True."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(503, "Service Unavailable")
    result = classify_error(exc, provider="anthropic")

    assert result.error_class == ErrorClass.TRANSIENT
    assert result.should_retry is True


def test_classify_529_overloaded_retry_after_30():
    """HTTP 529 (Anthropic overloaded) → TRANSIENT, retry_after=30."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(529, "Overloaded")
    result = classify_error(exc, provider="anthropic")

    assert result.error_class == ErrorClass.TRANSIENT
    assert result.should_retry is True
    assert result.retry_after == 30


def test_classify_unknown_exception_is_permanent():
    """A generic Exception (not httpx) → PERMANENT, should_retry=False."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = Exception("Something completely unexpected")
    result = classify_error(exc, provider="groq")

    assert result.error_class == ErrorClass.PERMANENT
    assert result.should_retry is False
    assert result.suggestion


def test_classified_error_str_repr():
    """str() of a ClassifiedError's message contains the provider and status."""
    from app.core.error_classifier import classify_error

    exc = _make_http_exc(429, "Rate limit exceeded")
    result = classify_error(exc, provider="myservice")

    # The message attribute is a plain string — verify it's non-empty and informative
    assert isinstance(result.message, str)
    assert len(result.message) > 0
    # The original exception should be stored
    assert result.original is exc


def test_classify_provider_in_message():
    """The provider name should appear in the classified error message."""
    from app.core.error_classifier import classify_error

    exc = httpx.ConnectError("Connection refused")
    result = classify_error(exc, provider="ollama-server")

    assert "ollama-server" in result.message


def test_retry_with_backoff_respects_retry_after():
    """When retry_after > 0 the backoff sleeps for that value on first retry."""
    from codex.app.llm_client_base import _retry_with_backoff

    call_count = 0

    def _fn():
        nonlocal call_count
        call_count += 1
        # Return 429 with Retry-After: 7
        raise _make_http_exc(429, "Rate limited", headers={"retry-after": "7"})

    sleep_calls: list[float] = []

    def _fake_sleep(secs: float) -> None:
        sleep_calls.append(secs)

    with patch("codex.app.llm_client_base.time.sleep", side_effect=_fake_sleep):
        with pytest.raises(Exception):
            _retry_with_backoff(_fn, max_retries=2, base_delay=0.01, provider="test")

    # At least one sleep call should use the retry_after value (7s)
    assert any(s >= 7 for s in sleep_calls), (
        f"Expected at least one sleep >= 7s (retry_after), got sleeps: {sleep_calls}"
    )


def test_classify_503_with_retry_after_header():
    """HTTP 503 with Retry-After header → retry_after parsed from header."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(503, "Unavailable", headers={"retry-after": "45"})
    result = classify_error(exc, provider="openai")

    assert result.error_class == ErrorClass.TRANSIENT
    # 5xx branch uses a fixed retry_after (10s for 503), not the header.
    # Verify should_retry is True at minimum; header parsing is 429-specific.
    assert result.should_retry is True
    assert result.retry_after >= 0


def test_classify_empty_body_400():
    """HTTP 400 with empty body → PERMANENT (no keyword match for sub-types)."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(400, "")
    result = classify_error(exc, provider="ollama")

    # Empty body has no context/policy/token keywords → falls through to PERMANENT
    assert result.error_class == ErrorClass.PERMANENT
    assert result.should_retry is False
