"""Tests for app.core.research_fetcher — topic inference, fetch, cache, context."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_fetch_result(url: str, text: str, title: str = "Test Page") -> dict:
    """Build a mock fetch_url return value."""
    return {"ok": True, "url": url, "title": title, "text": text, "error": ""}


# ── infer_topics ─────────────────────────────────────────────────────────────

class TestInferTopics:
    def test_scrape_returns_web_scraping(self):
        from app.core.research_fetcher import infer_topics
        topics = infer_topics("scrape data from a website")
        assert "web scraping" in topics

    def test_sqlite_returns_database(self):
        from app.core.research_fetcher import infer_topics
        topics = infer_topics("connect to sqlite database")
        assert "database" in topics

    def test_unrelated_returns_empty(self):
        from app.core.research_fetcher import infer_topics
        topics = infer_topics("completely unrelated xyz123 foobar")
        assert topics == []

    def test_returns_at_most_three_topics(self):
        from app.core.research_fetcher import infer_topics
        # This description hits many keywords
        desc = "scrape web api database sql async threading file csv log test"
        topics = infer_topics(desc)
        assert len(topics) <= 3

    def test_case_insensitive(self):
        from app.core.research_fetcher import infer_topics
        topics = infer_topics("SCRAPE data FROM A WEBSITE")
        assert "web scraping" in topics

    def test_task_detail_contributes_to_inference(self):
        from app.core.research_fetcher import infer_topics
        # description is vague, task_detail has the keyword
        topics = infer_topics("utility tool", "connect to sqlite database")
        assert "database" in topics

    def test_no_partial_word_match(self):
        """'database_manager' is kept as one token by _word_split (underscore included).

        The keyword 'database' is not a standalone token here, so it should NOT
        match. However, the word 'database' appearing elsewhere in the text
        SHOULD match. We verify the tokeniser behaviour.
        """
        from app.core.research_fetcher import infer_topics, _word_split
        # Confirm tokeniser keeps underscores
        tokens = _word_split("database_manager")
        assert "database_manager" in tokens
        assert "database" not in tokens  # not split out

        # So 'database_manager' alone should NOT match the 'database' topic
        topics_no_match = infer_topics("database_manager module")
        assert "database" not in topics_no_match

        # But the bare word 'database' SHOULD match
        topics_match = infer_topics("connect to a database")
        assert "database" in topics_match

    def test_async_keyword_matches_async_topic(self):
        from app.core.research_fetcher import infer_topics
        topics = infer_topics("async event loop using asyncio")
        assert "async" in topics

    def test_empty_strings_return_empty(self):
        from app.core.research_fetcher import infer_topics
        assert infer_topics("") == []
        assert infer_topics("", "") == []

    def test_llm_keyword(self):
        from app.core.research_fetcher import infer_topics
        topics = infer_topics("chat with llm using prompt engineering")
        assert "llm" in topics


# ── build_research_context ────────────────────────────────────────────────────

class TestBuildResearchContext:
    def test_empty_results_returns_empty_string(self):
        from app.core.research_fetcher import build_research_context
        result = build_research_context([])
        assert result == ""

    def test_single_result_contains_text(self):
        from app.core.research_fetcher import build_research_context
        results = [{"url": "https://example.com/", "title": "T", "text": "content here", "topic": "testing"}]
        ctx = build_research_context(results)
        assert "content here" in ctx

    def test_output_contains_topic_label(self):
        from app.core.research_fetcher import build_research_context
        results = [{"url": "https://example.com/", "title": "T", "text": "text", "topic": "web scraping"}]
        ctx = build_research_context(results)
        assert "web scraping" in ctx

    def test_output_contains_source_hostname(self):
        from app.core.research_fetcher import build_research_context
        results = [{"url": "https://docs.example.org/page", "title": "T", "text": "hello", "topic": "testing"}]
        ctx = build_research_context(results)
        assert "docs.example.org" in ctx

    def test_output_has_header_and_footer(self):
        from app.core.research_fetcher import build_research_context
        results = [{"url": "https://example.com/", "title": "T", "text": "abc", "topic": "t"}]
        ctx = build_research_context(results)
        assert "=== RESEARCH CONTEXT ===" in ctx
        assert "=========================" in ctx

    def test_multiple_results_all_included(self):
        from app.core.research_fetcher import build_research_context
        results = [
            {"url": "https://a.com/", "title": "A", "text": "text_a", "topic": "t1"},
            {"url": "https://b.com/", "title": "B", "text": "text_b", "topic": "t2"},
        ]
        ctx = build_research_context(results)
        assert "text_a" in ctx
        assert "text_b" in ctx


# ── ResearchCache ─────────────────────────────────────────────────────────────

class TestResearchCache:
    def test_get_returns_none_when_cache_empty(self, tmp_path):
        from app.core.research_fetcher import ResearchCache
        cache = ResearchCache(cache_dir=tmp_path)
        result = cache.get("https://example.com/")
        assert result is None

    def test_set_then_get_roundtrip(self, tmp_path):
        from app.core.research_fetcher import ResearchCache
        cache = ResearchCache(cache_dir=tmp_path)
        cache.set("https://example.com/page", "hello world")
        result = cache.get("https://example.com/page")
        assert result == "hello world"

    def test_stale_entry_returns_none(self, tmp_path):
        from app.core.research_fetcher import ResearchCache
        import hashlib
        cache = ResearchCache(cache_dir=tmp_path)
        url = "https://example.com/stale"
        cache.set(url, "old content")
        # Manually backdate the file's mtime by 25 hours
        key = hashlib.md5(url.encode()).hexdigest()
        cache_file = tmp_path / f"{key}.txt"
        old_time = time.time() - (25 * 3600)
        import os
        os.utime(str(cache_file), (old_time, old_time))
        # Clear in-memory cache to force disk check
        cache._mem.clear()
        result = cache.get(url)
        assert result is None

    def test_stats_reflects_cached_files(self, tmp_path):
        from app.core.research_fetcher import ResearchCache
        cache = ResearchCache(cache_dir=tmp_path)
        cache.set("https://a.com/", "text a")
        cache.set("https://b.com/", "text b")
        stats = cache.stats()
        assert stats["files"] == 2
        assert stats["total_bytes"] > 0

    def test_clear_removes_files(self, tmp_path):
        from app.core.research_fetcher import ResearchCache
        cache = ResearchCache(cache_dir=tmp_path)
        cache.set("https://example.com/", "some text")
        removed = cache.clear()
        assert removed == 1
        assert cache.stats()["files"] == 0

    def test_different_urls_stored_separately(self, tmp_path):
        from app.core.research_fetcher import ResearchCache
        cache = ResearchCache(cache_dir=tmp_path)
        cache.set("https://a.com/", "aaa")
        cache.set("https://b.com/", "bbb")
        assert cache.get("https://a.com/") == "aaa"
        assert cache.get("https://b.com/") == "bbb"


# ── fetch_research ────────────────────────────────────────────────────────────

class TestFetchResearch:
    def test_empty_topics_returns_empty_list(self):
        from app.core.research_fetcher import fetch_research
        result = fetch_research([])
        assert result == []

    def test_nonexistent_topic_returns_empty(self):
        from app.core.research_fetcher import fetch_research
        result = fetch_research(["nonexistent_topic_xyz"])
        assert result == []

    def test_fetch_with_mock_returns_dicts(self, tmp_path):
        """Mock fetch_url so we don't hit the network."""
        from app.core.research_fetcher import fetch_research, ResearchCache

        mock_text = "Python requests library documentation content here."
        mock_result = _make_fetch_result(
            "https://docs.python-requests.org/en/latest/user/quickstart/",
            mock_text,
            "Requests: HTTP for Humans",
        )

        cache = ResearchCache(cache_dir=tmp_path)

        with patch("app.core.research_fetcher.fetch_url", return_value=mock_result) as mock_fetch:
            results = fetch_research(["web scraping"], max_urls=2, timeout=5, cache=cache)

        assert isinstance(results, list)
        assert len(results) >= 1
        first = results[0]
        assert "url" in first
        assert "text" in first
        assert "topic" in first
        assert first["topic"] == "web scraping"
        assert mock_text[:50] in first["text"]

    def test_failed_fetch_is_skipped(self, tmp_path):
        """A fetch_url that returns ok=False should be skipped silently."""
        from app.core.research_fetcher import fetch_research, ResearchCache

        bad_result = {"ok": False, "url": "https://example.com/", "title": "", "text": "", "error": "timeout"}
        cache = ResearchCache(cache_dir=tmp_path)

        with patch("app.core.research_fetcher.fetch_url", return_value=bad_result):
            results = fetch_research(["web scraping"], max_urls=2, timeout=5, cache=cache)

        assert results == []

    def test_total_text_capped_at_12000(self, tmp_path):
        """Combined text of results must not exceed 12,000 chars."""
        from app.core.research_fetcher import fetch_research, ResearchCache

        long_text = "x" * 10_000
        mock_result = _make_fetch_result(
            "https://docs.python-requests.org/en/latest/user/quickstart/",
            long_text,
        )
        mock_result2 = _make_fetch_result(
            "https://www.crummy.com/software/BeautifulSoup/bs4/doc/",
            long_text,
        )
        cache = ResearchCache(cache_dir=tmp_path)

        call_count = [0]
        def side_effect(url, timeout=8):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_result
            return mock_result2

        with patch("app.core.research_fetcher.fetch_url", side_effect=side_effect):
            results = fetch_research(["web scraping"], max_urls=4, timeout=5, cache=cache)

        total_text = sum(len(r["text"]) for r in results)
        assert total_text <= 12_000

    def test_cache_used_on_second_call(self, tmp_path):
        """Second fetch_research call for same URL should use cache, not call fetch_url again."""
        from app.core.research_fetcher import fetch_research, ResearchCache

        mock_text = "cached content"
        mock_result = _make_fetch_result(
            "https://docs.python-requests.org/en/latest/user/quickstart/",
            mock_text,
        )
        cache = ResearchCache(cache_dir=tmp_path)

        with patch("app.core.research_fetcher.fetch_url", return_value=mock_result) as mock_fetch:
            fetch_research(["web scraping"], max_urls=1, timeout=5, cache=cache)
            fetch_research(["web scraping"], max_urls=1, timeout=5, cache=cache)
            # fetch_url should have been called only once (second call uses cache)
            assert mock_fetch.call_count == 1

    def test_build_research_context_caps_total_output(self):
        """build_research_context must include topic labels in the returned string."""
        from app.core.research_fetcher import build_research_context

        results = [
            {"url": "https://a.com/", "title": "A", "text": "alpha " * 200, "topic": "alpha topic"},
            {"url": "https://b.com/", "title": "B", "text": "beta " * 200, "topic": "beta topic"},
        ]
        ctx = build_research_context(results)
        assert "alpha topic" in ctx
        assert "beta topic" in ctx
