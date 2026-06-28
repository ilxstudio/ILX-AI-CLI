"""Cluster 26 — Robust error handling: error_classifier and enhanced retry.

Tests (all mock-based — no live API calls):
  1.  classify_error(ConnectError)            → TRANSIENT, should_retry=True
  2.  classify_error(HTTP 429)                → RATE_LIMIT, should_retry=True
  3.  classify_error(HTTP 401)                → AUTH, should_retry=False
  4.  classify_error(HTTP 429 + Retry-After)  → retry_after > 0
  5.  classify_error(HTTP 400 + context body) → CONTEXT_LENGTH
  6.  classify_error(HTTP 404 + model body)   → MODEL_NOT_FOUND
  7.  classify_error(HTTP 402)                → QUOTA
  8.  _retry_with_backoff does NOT retry on AUTH errors
  9.  _retry_with_backoff retries on TRANSIENT errors up to max_retries
  10. ClassifiedError.suggestion is non-empty for all ErrorClass variants
  11. classify_error(HTTP 400 + policy body)  → CONTENT_POLICY, should_retry=False
  12. classify_error(TimeoutException)        → TRANSIENT, should_retry=True
  13. crash_db.log_classified_error stores the record
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import httpx

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_http_exc(status: int, body: str = "", headers: dict | None = None) -> httpx.HTTPStatusError:
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

def test_classify_connect_error():
    """ConnectError → TRANSIENT, should_retry=True."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = httpx.ConnectError("Connection refused")
    result = classify_error(exc, provider="ollama")

    assert result.error_class == ErrorClass.TRANSIENT
    assert result.should_retry is True
    assert result.retry_after == 0
    assert result.message
    assert result.suggestion

    save("classify_connect_error", True, {
        "error_class": result.error_class.name,
        "should_retry": result.should_retry,
    })


def test_classify_429_rate_limit():
    """HTTP 429 → RATE_LIMIT, should_retry=True."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(429, "Rate limit exceeded")
    result = classify_error(exc, provider="anthropic")

    assert result.error_class == ErrorClass.RATE_LIMIT
    assert result.should_retry is True
    assert result.message
    assert result.suggestion

    save("classify_429_rate_limit", True, {
        "error_class": result.error_class.name,
        "should_retry": result.should_retry,
    })


def test_classify_401_auth():
    """HTTP 401 → AUTH, should_retry=False."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(401, "Unauthorized")
    result = classify_error(exc, provider="openai")

    assert result.error_class == ErrorClass.AUTH
    assert result.should_retry is False
    assert "apikey" in result.suggestion.lower() or "api key" in result.suggestion.lower()

    save("classify_401_auth", True, {
        "error_class": result.error_class.name,
        "should_retry": result.should_retry,
        "suggestion": result.suggestion,
    })


def test_classify_429_retry_after_header():
    """HTTP 429 with Retry-After header → retry_after > 0."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(429, "Rate limit", headers={"retry-after": "30"})
    result = classify_error(exc, provider="groq")

    assert result.error_class == ErrorClass.RATE_LIMIT
    assert result.retry_after == 30

    save("classify_429_retry_after", True, {
        "retry_after": result.retry_after,
    })


def test_classify_400_context_length():
    """HTTP 400 with context-related body → CONTEXT_LENGTH, should_retry=False."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(400, "context_length exceeded: maximum token limit reached")
    result = classify_error(exc, provider="openai")

    assert result.error_class == ErrorClass.CONTEXT_LENGTH
    assert result.should_retry is False
    assert "compact" in result.suggestion.lower()

    save("classify_400_context_length", True, {
        "error_class": result.error_class.name,
        "should_retry": result.should_retry,
    })


def test_classify_404_model_not_found():
    """HTTP 404 with model in body → MODEL_NOT_FOUND, should_retry=False."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(404, "model 'gpt-5' not found")
    result = classify_error(exc, provider="openai")

    assert result.error_class == ErrorClass.MODEL_NOT_FOUND
    assert result.should_retry is False
    assert "model" in result.suggestion.lower()

    save("classify_404_model_not_found", True, {
        "error_class": result.error_class.name,
        "suggestion": result.suggestion,
    })


def test_classify_402_quota():
    """HTTP 402 → QUOTA, should_retry=False."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(402, "Payment required")
    result = classify_error(exc, provider="anthropic")

    assert result.error_class == ErrorClass.QUOTA
    assert result.should_retry is False
    assert "billing" in result.suggestion.lower() or "dashboard" in result.suggestion.lower()

    save("classify_402_quota", True, {
        "error_class": result.error_class.name,
        "should_retry": result.should_retry,
    })


def test_retry_with_backoff_no_retry_on_auth():
    """Enhanced _retry_with_backoff must NOT retry on AUTH (401) errors."""
    from codex.app.llm_client_base import _retry_with_backoff

    call_count = 0

    def _fn():
        nonlocal call_count
        call_count += 1
        raise _make_http_exc(401, "Unauthorized")

    with pytest.raises(RuntimeError) as exc_info:
        _retry_with_backoff(_fn, max_retries=3, provider="openai")

    # Must have been called exactly once — no retry on AUTH
    assert call_count == 1
    assert "401" in str(exc_info.value) or "auth" in str(exc_info.value).lower() or "api key" in str(exc_info.value).lower()

    save("retry_no_retry_on_auth", True, {
        "call_count": call_count,
        "error": str(exc_info.value)[:200],
    })


def test_retry_with_backoff_retries_on_transient():
    """Enhanced _retry_with_backoff retries ConnectError up to max_retries times."""
    from codex.app.llm_client_base import _retry_with_backoff

    call_count = 0

    def _fn():
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("Connection refused")

    with patch("codex.app.llm_client_base.time.sleep"):
        with pytest.raises(Exception):
            _retry_with_backoff(_fn, max_retries=3, base_delay=0.01, provider="ollama")

    assert call_count == 3  # tried 3 times before giving up

    save("retry_retries_on_transient", True, {
        "call_count": call_count,
    })


def test_all_error_classes_have_non_empty_suggestion():
    """ClassifiedError.suggestion must be non-empty for all ErrorClass members."""
    from app.core.error_classifier import classify_error, ErrorClass

    # Map each ErrorClass to a representative exception
    cases = [
        # TRANSIENT
        httpx.ConnectError("refused"),
        # RATE_LIMIT
        _make_http_exc(429, "rate limit"),
        # AUTH
        _make_http_exc(401, "unauthorized"),
        # QUOTA
        _make_http_exc(402, "payment"),
        # CONTENT_POLICY
        _make_http_exc(400, "content policy violation — safety"),
        # CONTEXT_LENGTH
        _make_http_exc(400, "maximum context length exceeded"),
        # MODEL_NOT_FOUND
        _make_http_exc(404, "model not found"),
        # PERMANENT (generic 500)
        _make_http_exc(500, "internal server error"),
    ]

    missing: list[str] = []
    for exc in cases:
        result = classify_error(exc)
        if not result.suggestion or not result.suggestion.strip():
            missing.append(result.error_class.name)

    assert not missing, f"Missing suggestions for: {missing}"

    save("all_error_classes_have_suggestion", True, {
        "classes_checked": [c.name for c in ErrorClass],
    })


def test_classify_400_content_policy():
    """HTTP 400 with policy/safety body → CONTENT_POLICY, should_retry=False."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = _make_http_exc(400, "Request blocked: content policy violation")
    result = classify_error(exc, provider="anthropic")

    assert result.error_class == ErrorClass.CONTENT_POLICY
    assert result.should_retry is False

    save("classify_400_content_policy", True, {
        "error_class": result.error_class.name,
        "should_retry": result.should_retry,
    })


def test_classify_timeout_exception():
    """TimeoutException → TRANSIENT, should_retry=True."""
    from app.core.error_classifier import classify_error, ErrorClass

    exc = httpx.TimeoutException("Request timed out")
    result = classify_error(exc, provider="groq")

    assert result.error_class == ErrorClass.TRANSIENT
    assert result.should_retry is True

    save("classify_timeout_transient", True, {
        "error_class": result.error_class.name,
    })


def test_log_classified_error_stored_in_db():
    """crash_db.log_classified_error must persist the record to the api_errors table."""
    from app.core.error_classifier import classify_error
    from app.core import crash_db

    # Start with a clean slate for this test
    crash_db.clear_api_errors()

    exc = _make_http_exc(429, "Rate limit exceeded", headers={"retry-after": "5"})
    classified = classify_error(exc, provider="groq")
    crash_db.log_classified_error(classified, context="test_log_classified_error_stored_in_db")

    records = crash_db.list_api_errors(limit=5)
    assert len(records) >= 1, "Expected at least one api_error record after log_classified_error()"

    latest = records[0]
    assert latest["error_class"] == "RATE_LIMIT"
    assert latest["context"] == "test_log_classified_error_stored_in_db"
    assert latest["message"]
    assert latest["suggestion"]

    save("log_classified_error_stored", True, {
        "error_class": latest["error_class"],
        "context": latest["context"],
    })
