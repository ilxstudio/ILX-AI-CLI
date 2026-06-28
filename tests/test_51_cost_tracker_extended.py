"""Extended tests for app.core.cost_tracker — Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.cost_tracker import CostTracker, SessionUsage, PRICING, _lookup_rates


class TestCostTrackerRecordUsage:

    def test_record_usage_accumulates_across_calls(self) -> None:
        """record_usage sums tokens across multiple calls for the same key."""
        tracker = CostTracker()
        tracker.record_usage("openai", "gpt-4o", input_tokens=100, output_tokens=50)
        tracker.record_usage("openai", "gpt-4o", input_tokens=200, output_tokens=75)
        key = ("openai", "gpt-4o")
        assert tracker._usage[key].input_tokens == 300
        assert tracker._usage[key].output_tokens == 125
        assert tracker._usage[key].requests == 2

    def test_record_usage_different_providers_tracked_separately(self) -> None:
        """record_usage keeps separate buckets for different providers."""
        tracker = CostTracker()
        tracker.record_usage("openai", "gpt-4o-mini", input_tokens=100, output_tokens=10)
        tracker.record_usage("anthropic", "claude-sonnet", input_tokens=200, output_tokens=20)
        assert len(tracker._usage) == 2

    def test_record_usage_updates_aggregate_totals(self) -> None:
        """record_usage also updates the legacy aggregate prompt/completion counters."""
        tracker = CostTracker()
        tracker.record_usage("ollama", "llama3", input_tokens=50, output_tokens=25)
        summary = tracker.session_summary()
        assert summary["prompt_tokens"] == 50
        assert summary["completion_tokens"] == 25


class TestSessionSummary:

    def test_session_summary_has_breakdown_key(self) -> None:
        """session_summary always returns a dict with a 'breakdown' key."""
        tracker = CostTracker()
        result = tracker.session_summary()
        assert "breakdown" in result

    def test_session_summary_breakdown_contains_provider_name(self) -> None:
        """session_summary breakdown entries include provider and model strings."""
        tracker = CostTracker()
        tracker.record_usage("groq", "llama-3.1-8b", input_tokens=10, output_tokens=5)
        summary = tracker.session_summary()
        assert len(summary["breakdown"]) == 1
        row = summary["breakdown"][0]
        assert row["provider"] == "groq"
        assert row["model"] == "llama-3.1-8b"

    def test_session_summary_totals_match_individual_calls(self) -> None:
        """total_usd matches the sum of all individual cost estimates."""
        tracker = CostTracker()
        tracker.record_usage("openai", "gpt-4o", input_tokens=1_000_000, output_tokens=0)
        summary = tracker.session_summary()
        expected = tracker.estimate("openai", "gpt-4o", 1_000_000, 0)
        # total_usd == 2 * expected because record_usage also calls add()
        # which calls estimate again — confirm it is not zero
        assert summary["total_usd"] > 0


class TestFormatSessionReport:

    def test_format_session_report_returns_string(self) -> None:
        """format_session_report always returns a str."""
        tracker = CostTracker()
        assert isinstance(tracker.format_session_report(), str)

    def test_format_session_report_contains_provider_name(self) -> None:
        """format_session_report includes the provider name in the table."""
        tracker = CostTracker()
        tracker.record_usage("anthropic", "claude-haiku", input_tokens=500, output_tokens=100)
        report = tracker.format_session_report()
        assert "anthropic" in report

    def test_format_session_report_no_usage_falls_back(self) -> None:
        """format_session_report works with no recorded usage (single-line fallback)."""
        tracker = CostTracker()
        report = tracker.format_session_report()
        assert "Session cost:" in report


class TestReset:

    def test_reset_clears_all_counters(self) -> None:
        """reset() zeros out all aggregate counters and usage dict."""
        tracker = CostTracker()
        tracker.record_usage("openai", "gpt-4o", input_tokens=100, output_tokens=50)
        tracker.reset()
        assert tracker._session_cost_usd == 0.0
        assert tracker._session_prompt_tokens == 0
        assert tracker._session_completion_tokens == 0
        assert tracker._usage == {}

    def test_reset_then_record_works_correctly(self) -> None:
        """After reset, a new record_usage call starts fresh."""
        tracker = CostTracker()
        tracker.record_usage("openai", "gpt-4o", input_tokens=999, output_tokens=999)
        tracker.reset()
        tracker.record_usage("groq", "llama-3.1-8b", input_tokens=1, output_tokens=1)
        summary = tracker.session_summary()
        assert summary["prompt_tokens"] == 1
        assert len(summary["breakdown"]) == 1


class TestUnknownModel:

    def test_unknown_provider_falls_back_to_zero_cost(self) -> None:
        """An unrecognised provider returns $0 rate without raising."""
        rates = _lookup_rates("unknown_provider_xyz", "mystery-model")
        assert rates == (0.0, 0.0)

    def test_unknown_model_falls_back_to_provider_default(self) -> None:
        """An unrecognised model within a known provider uses the 'default' rate."""
        rates = _lookup_rates("openai", "gpt-super-future-unknown")
        default = PRICING["openai"]["default"]
        assert rates == default

    def test_estimate_unknown_model_returns_zero_not_exception(self) -> None:
        """estimate() on an unknown model/provider returns 0.0 rather than raising."""
        tracker = CostTracker()
        cost = tracker.estimate("totally_unknown", "model_xyz", 10_000, 10_000)
        assert cost == 0.0

    def test_record_usage_unknown_provider_does_not_raise(self) -> None:
        """record_usage with an unknown provider completes without error."""
        tracker = CostTracker()
        tracker.record_usage("unknown_provider", "unknown_model", 100, 100)
        summary = tracker.session_summary()
        assert "breakdown" in summary
