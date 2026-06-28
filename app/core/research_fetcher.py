"""Research fetcher — retrieves technical papers and documentation to enrich
tool-building context with current best practices.

Fetches are SSRF-safe (routed through web_fetch._check_ssrf).
Results are injected into the RAG context before LLM code generation.
"""
from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from pathlib import Path

from app.core.web_fetch import fetch_url as fetch_url  # SSRF-safe; re-exported for mocking

_log = logging.getLogger("ilx_cli.research_fetcher")

# ── In-flight request deduplication ─────────────────────────────────────────
# When multiple threads request the same URL simultaneously, only one performs
# the network fetch.  Others wait on an Event and then read from cache.

_in_flight: dict[str, threading.Event] = {}
_in_flight_lock = threading.Lock()

# ── Topic → URL mapping ──────────────────────────────────────────────────────

RESEARCH_SOURCES: dict[str, list[str]] = {
    "web scraping": [
        "https://docs.python-requests.org/en/latest/user/quickstart/",
        "https://www.crummy.com/software/BeautifulSoup/bs4/doc/",
    ],
    "http api": [
        "https://docs.python-requests.org/en/latest/user/advanced/",
        "https://www.rfc-editor.org/rfc/rfc7231",
    ],
    "database": [
        "https://docs.python.org/3/library/sqlite3.html",
    ],
    "async": [
        "https://docs.python.org/3/library/asyncio.html",
    ],
    "data processing": [
        "https://docs.python.org/3/library/csv.html",
        "https://docs.python.org/3/library/json.html",
    ],
    "file operations": [
        "https://docs.python.org/3/library/pathlib.html",
    ],
    "testing": [
        "https://docs.pytest.org/en/stable/how-to/",
    ],
    "machine learning": [
        "https://scikit-learn.org/stable/getting_started.html",
    ],
    "llm": [
        "https://docs.anthropic.com/en/docs/about-claude/models/overview",
        "https://platform.openai.com/docs/guides/text-generation",
    ],
    "cli tool": [
        "https://docs.python.org/3/library/argparse.html",
        "https://click.palletsprojects.com/en/8.x/api/",
    ],
    "security": [
        "https://owasp.org/www-project-top-ten/",
        "https://docs.python.org/3/library/secrets.html",
    ],
    "concurrency": [
        "https://docs.python.org/3/library/concurrent.futures.html",
        "https://docs.python.org/3/library/threading.html",
    ],
    "logging": [
        "https://docs.python.org/3/library/logging.html",
        "https://docs.python.org/3/howto/logging.html",
    ],
    "data validation": [
        "https://docs.pydantic.dev/latest/",
    ],
    "git": [
        "https://git-scm.com/docs/git",
    ],
    "docker": [
        "https://docs.docker.com/develop/develop-images/dockerfile_best-practices/",
        "https://docs.docker.com/compose/compose-file/",
    ],
    "kubernetes": [
        "https://kubernetes.io/docs/concepts/workloads/pods/",
    ],
    "container security": [
        "https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html",
    ],
}

# ── Keyword → topic aliases for matching ────────────────────────────────────
# Each entry maps one or more trigger words to a topic key in RESEARCH_SOURCES.
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "web scraping":    ["scrape", "scraping", "crawl", "crawling", "beautifulsoup", "soup", "html"],
    "http api":        ["http", "api", "rest", "requests", "endpoint", "fetch", "url", "web"],
    "database":        ["database", "db", "sqlite", "sql", "postgres", "mysql", "orm"],
    "async":           ["async", "await", "asyncio", "coroutine", "event loop", "aiohttp"],
    "data processing": ["csv", "json", "parse", "parsing", "dataframe", "pandas", "data"],
    "file operations": ["file", "files", "path", "pathlib", "directory", "folder", "read", "write"],
    "testing":         ["test", "tests", "testing", "pytest", "unittest", "mock", "fixture"],
    "machine learning": ["ml", "model", "train", "sklearn", "scikit", "neural", "classification",
                         "regression", "clustering"],
    "llm":             ["llm", "gpt", "claude", "anthropic", "openai", "language model", "prompt",
                        "embedding", "inference"],
    "cli tool":        ["cli", "command line", "argparse", "click", "terminal", "argument", "flag"],
    "security":        ["security", "auth", "authentication", "password", "secret", "encrypt",
                        "hash", "token", "owasp"],
    "concurrency":     ["thread", "threading", "concurrent", "parallel", "pool", "worker", "process"],
    "logging":         ["log", "logging", "logger", "debug", "info", "warning", "error", "trace"],
    "data validation": ["validate", "validation", "pydantic", "schema", "type check"],
    "git":              ["git", "commit", "branch", "merge", "repository", "repo"],
    "docker":           ["docker", "dockerfile", "container", "image", "compose", "dockerize"],
    "kubernetes":       ["kubernetes", "k8s", "pod", "deployment", "helm", "kubectl"],
    "container security": ["container security", "docker security", "image scan"],
}


# ── Public functions ─────────────────────────────────────────────────────────

def infer_topics(description: str, task_detail: str = "") -> list[str]:
    """Infer relevant research topics from description and task text.

    Performs case-insensitive word-level matching against known topic keywords.
    Returns at most 3 topic keys from RESEARCH_SOURCES, in match order.

    Example
    -------
    >>> infer_topics("scrape prices from a website")
    ['web scraping', 'http api']
    """
    combined = (description + " " + task_detail).lower()
    # Split on non-alphanumeric to get individual words/tokens
    tokens: set[str] = set(_word_split(combined))
    # Also keep the full string for multi-word keyword matching
    full_text = " " + combined + " "

    matched: list[str] = []
    seen: set[str] = set()

    for topic, keywords in _TOPIC_KEYWORDS.items():
        if topic in seen:
            continue
        for kw in keywords:
            if " " in kw:
                # Multi-word keyword — substring match with word boundaries
                if f" {kw} " in full_text or f" {kw}," in full_text or f" {kw}." in full_text:
                    matched.append(topic)
                    seen.add(topic)
                    break
            else:
                # Single word — exact word match (avoids partial matches)
                if kw in tokens:
                    matched.append(topic)
                    seen.add(topic)
                    break

        if len(matched) >= 3:
            break

    return matched


def fetch_research(
    topics: list[str],
    *,
    max_urls: int = 4,
    timeout: int = 8,
    cache: ResearchCache | None = None,
) -> list[dict]:
    """Fetch documentation pages for the given topics.

    For each topic, fetches up to ``ceil(max_urls / len(topics))`` URLs from
    RESEARCH_SOURCES.  Uses the SSRF-safe ``fetch_url`` from web_fetch.

    Parameters
    ----------
    topics:   List of topic keys (must exist in RESEARCH_SOURCES).
    max_urls: Maximum total URLs fetched across all topics.
    timeout:  Per-request timeout in seconds.
    cache:    Optional ResearchCache; when provided, avoids re-fetching.

    Returns
    -------
    List of dicts: ``{"url": str, "title": str, "text": str, "topic": str}``.
    Total text across all results is capped at 12,000 chars (trimmed equally).
    """
    if not topics:
        return []

    urls_per_topic = math.ceil(max_urls / len(topics))
    results: list[dict] = []

    for topic in topics:
        topic_urls = RESEARCH_SOURCES.get(topic, [])
        fetched_for_topic = 0
        for url in topic_urls:
            if fetched_for_topic >= urls_per_topic:
                break
            if len(results) >= max_urls:
                break

            # Try cache first
            cached_text = cache.get(url) if cache else None
            if cached_text is not None:
                from urllib.parse import urlparse
                hostname = urlparse(url).hostname or url
                results.append({
                    "url":   url,
                    "title": hostname,
                    "text":  cached_text,
                    "topic": topic,
                })
                fetched_for_topic += 1
                continue

            # Live fetch — deduplicated across concurrent callers for the same URL
            event: threading.Event | None = None
            with _in_flight_lock:
                if url in _in_flight:
                    # Another thread is already fetching this URL — wait for it
                    wait_event = _in_flight[url]
                else:
                    # Claim this URL for ourselves
                    event = threading.Event()
                    _in_flight[url] = event

            if event is None:
                # We were not the fetcher — wait for the other thread then re-check cache
                wait_event.wait(timeout=60.0)
                cached_text = cache.get(url) if cache else None
                if cached_text is not None:
                    from urllib.parse import urlparse
                    hostname = urlparse(url).hostname or url
                    results.append({
                        "url":   url,
                        "title": hostname,
                        "text":  cached_text,
                        "topic": topic,
                    })
                    fetched_for_topic += 1
                continue

            try:
                result = fetch_url(url, timeout=timeout)
            except Exception as exc:
                _log.debug("fetch_research: error fetching %s: %s", url, exc)
                with _in_flight_lock:
                    _in_flight.pop(url, None)
                event.set()
                continue

            if not result.get("ok") or not result.get("text", "").strip():
                _log.debug(
                    "fetch_research: skipped %s (ok=%s, text_len=%d)",
                    url, result.get("ok"), len(result.get("text", "")),
                )
                with _in_flight_lock:
                    _in_flight.pop(url, None)
                event.set()
                continue

            text = result["text"]
            title = result.get("title") or ""
            if not title:
                from urllib.parse import urlparse
                title = urlparse(url).hostname or url

            if cache:
                cache.set(url, text)

            with _in_flight_lock:
                _in_flight.pop(url, None)
            event.set()

            results.append({
                "url":   url,
                "title": title,
                "text":  text,
                "topic": topic,
            })
            fetched_for_topic += 1

    # Cap total text at 12,000 chars spread equally across results
    _cap_text(results, total_cap=12_000)
    return results


def build_research_context(research_results: list[dict]) -> str:
    """Format fetched research results into a structured LLM prompt block.

    Returns an empty string when ``research_results`` is empty.

    Output format::

        === RESEARCH CONTEXT ===
        The following documentation and best practices were retrieved ...

        [Topic: web scraping — Source: docs.python-requests.org]
        ... text ...

        =========================
    """
    if not research_results:
        return ""

    lines: list[str] = [
        "=== RESEARCH CONTEXT ===",
        "The following documentation and best practices were retrieved to help "
        "generate high-quality code.",
        "",
    ]

    for entry in research_results:
        from urllib.parse import urlparse
        hostname = urlparse(entry["url"]).hostname or entry["url"]
        topic = entry.get("topic", "general")
        text = entry.get("text", "").strip()
        lines.append(f"[Topic: {topic} — Source: {hostname}]")
        if text:
            lines.append(text)
        lines.append("")

    lines.append("=========================")
    return "\n".join(lines)


# ── ResearchCache ─────────────────────────────────────────────────────────────

class ResearchCache:
    """Simple in-memory + disk cache for fetched research pages.

    Cache files are stored as ``{md5(url)}.txt`` in *cache_dir*.
    Entries older than 24 hours are considered stale and re-fetched.
    """

    _TTL_SECONDS = 86_400  # 24 hours

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._dir: Path = (
            cache_dir if cache_dir is not None
            else Path.home() / ".ilx_cli" / "research_cache"
        )
        self._mem: dict[str, str] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, url: str) -> str | None:
        """Return cached text for *url* if present and < 24 hours old."""
        # Check in-memory cache first (no TTL for within-session hits)
        if url in self._mem:
            return self._mem[url]

        path = self._cache_path(url)
        if not path.exists():
            return None

        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return None

        if age > self._TTL_SECONDS:
            _log.debug("ResearchCache: stale entry for %s (age=%.0fs)", url, age)
            return None

        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None

        self._mem[url] = text
        return text

    def set(self, url: str, text: str) -> None:
        """Save *text* to the cache for *url*."""
        self._mem[url] = text
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(url).write_text(text, encoding="utf-8")
        except OSError as exc:
            _log.debug("ResearchCache: could not write cache for %s: %s", url, exc)

    def stats(self) -> dict:
        """Return cache statistics: file count, total size in bytes."""
        if not self._dir.exists():
            return {"files": 0, "total_bytes": 0}
        files = list(self._dir.glob("*.txt"))
        total = sum(f.stat().st_size for f in files if f.is_file())
        return {"files": len(files), "total_bytes": total}

    def clear(self) -> int:
        """Delete all cached files. Returns the number of files removed."""
        if not self._dir.exists():
            return 0
        removed = 0
        for f in self._dir.glob("*.txt"):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
        self._mem.clear()
        return removed

    # ── Private ───────────────────────────────────────────────────────────────

    def _cache_path(self, url: str) -> Path:
        key = hashlib.md5(url.encode()).hexdigest()
        return self._dir / f"{key}.txt"


# ── Module-level singleton cache ─────────────────────────────────────────────

_default_cache = ResearchCache()


def get_default_cache() -> ResearchCache:
    """Return the module-level ResearchCache singleton."""
    return _default_cache


# ── Internal helpers ─────────────────────────────────────────────────────────

def _word_split(text: str) -> list[str]:
    """Split text into lowercase word tokens (alphanumeric + underscore)."""
    import re
    return re.findall(r"[a-z0-9_]+", text.lower())


def _cap_text(results: list[dict], total_cap: int) -> None:
    """Trim result texts in-place so their combined length <= total_cap."""
    if not results:
        return
    total = sum(len(r.get("text", "")) for r in results)
    if total <= total_cap:
        return
    per_entry = total_cap // len(results)
    for r in results:
        if len(r.get("text", "")) > per_entry:
            r["text"] = r["text"][:per_entry]
