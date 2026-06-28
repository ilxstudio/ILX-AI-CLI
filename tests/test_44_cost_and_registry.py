# Copyright 2026 ILX Studio — MIT License
"""Tests for CostTracker and model_registry (if present)."""
from __future__ import annotations

import pytest
from app.core.cost_tracker import CostTracker


# ---------------------------------------------------------------------------
# CostTracker tests
# ---------------------------------------------------------------------------

def test_cost_tracker_estimate_zero_tokens():
    ct = CostTracker()
    cost = ct.estimate("anthropic", "claude-sonnet", 0, 0)
    assert cost == 0.0


def test_cost_tracker_anthropic_pricing():
    ct = CostTracker()
    # claude-sonnet: $3.00 input / $15.00 output per million tokens
    # 1000 input + 500 output = (1000*3 + 500*15) / 1_000_000 = 0.0105
    cost = ct.estimate("anthropic", "claude-sonnet", 1000, 500)
    assert abs(cost - 0.0105) / 0.0105 < 0.01  # within 1%


def test_cost_tracker_unknown_model_default():
    ct = CostTracker()
    # Unknown provider — should fall back to (0.0, 0.0) default
    cost = ct.estimate("unknown_provider", "mystery-model-x", 10000, 5000)
    assert cost >= 0.0  # must not raise; result is zero or default


def test_cost_tracker_format_cost_small():
    ct = CostTracker()
    result = ct.format_cost(0.005)
    assert result == "<$0.01"


def test_cost_tracker_format_cost_large():
    ct = CostTracker()
    result = ct.format_cost(1.2345)
    assert result.startswith("$")
    assert "1.2345" in result


def test_cost_tracker_session_accumulation():
    ct = CostTracker()
    ct.add("anthropic", "claude-sonnet", 1000, 200)
    ct.add("anthropic", "claude-sonnet", 2000, 400)
    summary = ct.session_summary()
    assert summary["prompt_tokens"] == 3000
    assert summary["completion_tokens"] == 600
    assert summary["total_usd"] > 0.0


def test_cost_tracker_reset():
    ct = CostTracker()
    ct.add("anthropic", "claude-sonnet", 5000, 1000)
    ct.reset()
    summary = ct.session_summary()
    assert summary["total_usd"] == 0.0
    assert summary["prompt_tokens"] == 0
    assert summary["completion_tokens"] == 0


# ---------------------------------------------------------------------------
# model_registry tests — skipped gracefully if module does not exist yet
# ---------------------------------------------------------------------------

def _import_registry():
    try:
        import app.core.model_registry as mr
        return mr
    except ImportError:
        return None


@pytest.fixture(scope="module")
def registry():
    mr = _import_registry()
    if mr is None:
        pytest.skip("model_registry not yet created")
    return mr


def test_model_registry_known_model(registry):
    caps = registry.get_capabilities("gpt-4o")
    assert caps.context_window == 128000


def test_model_registry_unknown_model_default(registry):
    caps = registry.get_capabilities("unknown-xyz")
    assert caps is not None  # should return a default, not raise


def test_model_registry_supports_vision(registry):
    assert registry.supports_vision("gpt-4o") is True
    assert registry.supports_vision("codellama:7b") is False


def test_model_registry_context_window(registry):
    assert registry.get_context_window("gemini-1.5-pro-latest") >= 1_000_000


def test_model_registry_prefix_match(registry):
    caps = registry.get_capabilities("claude-sonnet-4-6-20251022")
    assert caps is not None
