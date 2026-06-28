"""Cluster 19 — Session cost tracker and rate-limit handling.

Tests (all mock-based — no live API keys required):
  - test_pricing_lookup_anthropic_sonnet : correct per-token price for claude-sonnet-4-6
  - test_pricing_lookup_groq_llama       : correct price for llama-3.3-70b-versatile
  - test_pricing_ollama_is_free          : ollama cost is 0.0
  - test_cost_tracker_accumulates        : add() twice, session_summary() shows sum
  - test_cost_format_tiny                : format_cost(0.000001) returns "<$0.01"
  - test_cost_format_normal              : format_cost(1.2345) returns "$1.2345"
  - test_rate_limit_429_anthropic        : mock 429 response, verify user-friendly error
  - test_rate_limit_429_openai           : same for OpenAI
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_429_response(retry_after: str | None = None):
    """Build a mock httpx.Response with status 429."""
    import httpx
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 429
    mock_resp.text = "Rate limit exceeded"
    headers = {}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    mock_resp.headers = headers
    return mock_resp


# ── CostTracker — pricing lookup ──────────────────────────────────────────────

def test_pricing_lookup_anthropic_sonnet():
    """claude-sonnet-4-6 should map to the claude-sonnet price tier."""
    from app.core.cost_tracker import CostTracker
    t = CostTracker()
    # claude-sonnet prefix: $3.00 input / $15.00 output per million
    cost = t.estimate("anthropic", "claude-sonnet-4-6",
                      prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert abs(cost - 18.00) < 0.001, f"Expected $18.00, got ${cost}"
    save("pricing_lookup_anthropic_sonnet", True, {"cost_usd": cost})


def test_pricing_lookup_groq_llama():
    """llama-3.3-70b-versatile should map to the llama-3.3-70b price tier."""
    from app.core.cost_tracker import CostTracker
    t = CostTracker()
    # llama-3.3-70b: $0.59 input / $0.79 output per million
    cost = t.estimate("groq", "llama-3.3-70b-versatile",
                      prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert abs(cost - 1.38) < 0.001, f"Expected $1.38, got ${cost}"
    save("pricing_lookup_groq_llama", True, {"cost_usd": cost})


def test_pricing_ollama_is_free():
    """Ollama calls must always return 0.0 cost."""
    from app.core.cost_tracker import CostTracker
    t = CostTracker()
    cost = t.estimate("ollama", "llama3.2:latest",
                      prompt_tokens=50_000, completion_tokens=20_000)
    assert cost == 0.0
    save("pricing_ollama_is_free", True, {"cost_usd": cost})


# ── CostTracker — accumulation ────────────────────────────────────────────────

def test_cost_tracker_accumulates():
    """add() twice must accumulate totals in session_summary()."""
    from app.core.cost_tracker import CostTracker
    t = CostTracker()
    # First call: anthropic claude-sonnet, 100 prompt + 50 completion
    cost1 = t.add("anthropic", "claude-sonnet-4-6",
                  prompt_tokens=100, completion_tokens=50)
    # Second call: openai gpt-4o, 200 prompt + 80 completion
    cost2 = t.add("openai", "gpt-4o",
                  prompt_tokens=200, completion_tokens=80)

    summary = t.session_summary()
    assert summary["prompt_tokens"] == 300
    assert summary["completion_tokens"] == 130
    assert abs(summary["total_usd"] - (cost1 + cost2)) < 1e-9
    assert summary["total_usd"] > 0.0
    save("cost_tracker_accumulates", True, summary)


# ── CostTracker — format_cost ─────────────────────────────────────────────────

def test_cost_format_tiny():
    """Tiny amounts below $0.01 should format as '<$0.01'."""
    from app.core.cost_tracker import CostTracker
    t = CostTracker()
    result = t.format_cost(0.000001)
    assert result == "<$0.01", f"Got: {result!r}"
    save("cost_format_tiny", True, {"formatted": result})


def test_cost_format_normal():
    """Normal amounts should format as '$X.XXXX'."""
    from app.core.cost_tracker import CostTracker
    t = CostTracker()
    result = t.format_cost(1.2345)
    assert result == "$1.2345", f"Got: {result!r}"
    save("cost_format_normal", True, {"formatted": result})


# ── Rate-limit handling — Anthropic ──────────────────────────────────────────

def test_rate_limit_429_anthropic(capsys):
    """AnthropicClient must print a friendly message and raise RuntimeError on 429."""
    import httpx
    from codex.app.llm_client import AnthropicClient, _handle_rate_limit

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="test-key")
    mock_resp = _make_429_response(retry_after="5")

    exc = httpx.HTTPStatusError(
        "429 rate limit",
        request=MagicMock(),
        response=mock_resp,
    )

    # Patch time.sleep so the test doesn't actually wait 5 seconds
    # _handle_rate_limit lives in llm_client_base; patch there so the mock is effective
    with patch("codex.app.llm_client_base.time.sleep") as mock_sleep:
        with pytest.raises(RuntimeError) as exc_info:
            _handle_rate_limit(exc, "Anthropic")

    err_msg = str(exc_info.value)
    assert "Anthropic" in err_msg
    assert "429" in err_msg or "rate limit" in err_msg.lower()

    # Verify it printed the user-facing line
    captured = capsys.readouterr()
    assert "Rate limited by Anthropic" in captured.out
    assert "5s" in captured.out

    # Verify it slept the retry-after duration
    mock_sleep.assert_called_once_with(5)
    save("rate_limit_429_anthropic", True, {"error": err_msg})


def test_rate_limit_429_openai(capsys):
    """OpenAIClient generate() must raise RuntimeError with friendly message on 429."""
    import httpx
    from codex.app.llm_client import OpenAIClient

    client = OpenAIClient(model="gpt-4o", api_key="test-key")
    mock_resp = _make_429_response(retry_after="10")

    exc = httpx.HTTPStatusError(
        "429 rate limit",
        request=MagicMock(),
        response=mock_resp,
    )

    # Patch httpx.post to raise the 429 error
    # _handle_rate_limit (called on 429) lives in llm_client_base; patch there
    with patch("httpx.post", side_effect=exc):
        with patch("codex.app.llm_client_base.time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError) as exc_info:
                client.generate("hello")

    err_msg = str(exc_info.value)
    assert "OpenAI" in err_msg
    assert "rate limit" in err_msg.lower() or "429" in err_msg

    captured = capsys.readouterr()
    assert "Rate limited by OpenAI" in captured.out
    assert "10s" in captured.out

    mock_sleep.assert_called_once_with(10)
    save("rate_limit_429_openai", True, {"error": err_msg})
