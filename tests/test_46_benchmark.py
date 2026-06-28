"""Tests for app/core/benchmark.py — Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.benchmark import BenchmarkRunner, BenchmarkResult, TaskResult


def _make_cfg(provider="ollama", model="llama3.2", chat_model="", url="http://localhost:11434"):
    cfg = MagicMock()
    cfg.provider = provider
    cfg.ollama_model = model
    cfg.ollama_url = url
    cfg.chat_model = chat_model
    return cfg


# ---------------------------------------------------------------------------
# Init + _chat_model
# ---------------------------------------------------------------------------

class TestBenchmarkRunnerInit:
    def test_stores_cfg(self):
        cfg = _make_cfg()
        runner = BenchmarkRunner(cfg)
        assert runner._cfg is cfg

    def test_on_progress_stored_and_defaults_none(self):
        cfg = _make_cfg()
        assert BenchmarkRunner(cfg)._on_progress is None
        cb = MagicMock()
        assert BenchmarkRunner(cfg, on_progress=cb)._on_progress is cb

    def test_tasks_list_nonempty(self):
        assert len(BenchmarkRunner.TASKS) >= 6

    def test_chat_model_priority(self):
        assert BenchmarkRunner(_make_cfg(chat_model="gpt-4o"))._chat_model() == "gpt-4o"
        assert BenchmarkRunner(_make_cfg(chat_model="", model="mistral"))._chat_model() == "mistral"
        assert BenchmarkRunner(_make_cfg(chat_model="", model=""))._chat_model() == "default"


# ---------------------------------------------------------------------------
# _query_model — ollama / meta / unknown
# ---------------------------------------------------------------------------

class TestQueryModelOllama:
    def _resp(self, text: str):
        r = MagicMock()
        r.json.return_value = {"response": text}
        r.raise_for_status = MagicMock()
        return r

    def test_ollama_returns_response_text(self):
        runner = BenchmarkRunner(_make_cfg(provider="ollama"))
        with patch("httpx.post", return_value=self._resp("return a + b")) as mp:
            result = runner._query_model("fix it")
        assert result == "return a + b"
        mp.assert_called_once()

    def test_meta_provider_uses_ollama_path(self):
        runner = BenchmarkRunner(_make_cfg(provider="meta"))
        with patch("httpx.post", return_value=self._resp("def add(a,b): return a+b")):
            assert "add" in runner._query_model("fix it")

    def test_unknown_provider_raises(self):
        runner = BenchmarkRunner(_make_cfg(provider="unknown_xyz"))
        with pytest.raises(NotImplementedError, match="unknown_xyz"):
            with patch("httpx.post"):
                runner._query_model("test")


# ---------------------------------------------------------------------------
# _query_anthropic
# ---------------------------------------------------------------------------

class TestQueryAnthropic:
    def _resp(self, text: str):
        r = MagicMock()
        r.json.return_value = {"content": [{"text": text}]}
        r.raise_for_status = MagicMock()
        return r

    def test_raises_without_api_key(self):
        runner = BenchmarkRunner(_make_cfg(provider="anthropic"))
        with patch("app.core.secret_store.get_api_key", return_value=None):
            with pytest.raises(RuntimeError, match="No Anthropic API key"):
                runner._query_anthropic("hello")

    def test_returns_text_with_valid_key(self):
        runner = BenchmarkRunner(_make_cfg(provider="anthropic", chat_model="claude-sonnet-4-6"))
        with patch("app.core.secret_store.get_api_key", return_value="sk-test"), \
             patch("httpx.post", return_value=self._resp("fixed code here")):
            assert runner._query_anthropic("fix bug") == "fixed code here"

    def test_returns_empty_when_content_list_empty(self):
        runner = BenchmarkRunner(_make_cfg(provider="anthropic", chat_model="claude-sonnet-4-6"))
        r = MagicMock()
        r.json.return_value = {"content": []}
        r.raise_for_status = MagicMock()
        with patch("app.core.secret_store.get_api_key", return_value="sk-test"), \
             patch("httpx.post", return_value=r):
            assert runner._query_anthropic("fix bug") == ""


# ---------------------------------------------------------------------------
# _compute_score + _make_suggestion
# ---------------------------------------------------------------------------

class TestScoreAndSuggestion:
    def _runner(self):
        return BenchmarkRunner(_make_cfg())

    def _results(self, score_each):
        return [TaskResult(name=t["name"], score=score_each, passed=score_each > 5)
                for t in BenchmarkRunner.TASKS]

    def test_all_perfect_gives_100(self):
        assert self._runner()._compute_score(self._results(10)) == 100

    def test_all_zero_gives_0(self):
        assert self._runner()._compute_score(self._results(0)) == 0

    def test_mixed_scores_in_range(self):
        score = self._runner()._compute_score(self._results(5))
        assert 0 < score < 100

    def test_suggestion_excellent(self):
        r = BenchmarkResult(overall_score=90, model="m")
        s = self._runner()._make_suggestion(r)
        assert "production-ready" in s or "Excellent" in s

    def test_suggestion_low(self):
        r = BenchmarkResult(overall_score=30, model="m")
        s = self._runner()._make_suggestion(r)
        assert "struggles" in s or "larger model" in s


# ---------------------------------------------------------------------------
# run() end-to-end
# ---------------------------------------------------------------------------

class TestRunBenchmark:
    def test_run_returns_populated_result(self):
        cfg = _make_cfg()
        runner = BenchmarkRunner(cfg)
        with patch.object(runner, "_query_model", return_value="return a + b"):
            result = runner.run()
        assert isinstance(result, BenchmarkResult)
        assert result.model == cfg.ollama_model
        assert result.provider == cfg.provider
        assert len(result.task_results) == len(BenchmarkRunner.TASKS)
        assert 0 <= result.overall_score <= 100
        assert result.duration_s >= 0

    def test_run_calls_on_progress_for_each_task(self):
        cb = MagicMock()
        runner = BenchmarkRunner(_make_cfg(), on_progress=cb)
        with patch.object(runner, "_query_model", return_value="output"):
            runner.run()
        assert cb.call_count == len(BenchmarkRunner.TASKS)

    def test_run_exception_gives_score_zero(self):
        runner = BenchmarkRunner(_make_cfg())
        with patch.object(runner, "_query_model", side_effect=RuntimeError("down")):
            result = runner.run()
        assert all(tr.score == 0 and not tr.passed for tr in result.task_results)
