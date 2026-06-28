"""Lightweight conversation-file RAG for Ollama / local models."""
from __future__ import annotations

import logging
import math
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass

from app.core.thread_pool import pool as _pool

_log = logging.getLogger("ilx_cli.rag")

# chunk size tuned for an ~8KB budget — leaves room for the prompt and system context
_CHUNK_LINES_TARGET = 24
_CHUNK_LINES_OVERLAP = 4
_MIN_CHUNK_CHARS = 80

# anything matching one of these is a cloud model — skip RAG and send whole files instead
_CLOUD_MARKERS = (
    "claude", "gpt-", "gpt4", "gpt5", "gemini", "groq", "anthropic",
    "openai", "o3", "o4", "o5", "deepseek-cloud",
)


def is_local_model(name: str) -> bool:
    """Best-effort check for whether the model is local (Ollama) vs cloud."""
    if not name:
        return False
    lower = name.lower()
    return not any(marker in lower for marker in _CLOUD_MARKERS)


# ── Chunking ────────────────────────────────────────────────────────
@dataclass
class Chunk:
    file:        str
    line_start:  int   # 1-indexed, inclusive
    line_end:    int   # 1-indexed, inclusive
    text:        str

    def header(self) -> str:
        return f"[File: {self.file}, lines {self.line_start}-{self.line_end}]"


def chunk_text(filename: str, content: str) -> list[Chunk]:
    """Break a file into ~24-line chunks with 4-line overlap."""
    if not content.strip():
        return []
    lines = content.splitlines()
    if not lines:
        return []
    out: list[Chunk] = []
    i = 0
    n = len(lines)
    while i < n:
        end = min(i + _CHUNK_LINES_TARGET, n)
        body = "\n".join(lines[i:end]).rstrip()
        # fold tiny chunks into the previous one to avoid shipping near-empty fragments
        if len(body) >= _MIN_CHUNK_CHARS or i == 0 or not out:
            out.append(Chunk(
                file       = filename,
                line_start = i + 1,
                line_end   = end,
                text       = body,
            ))
        else:
            prev = out[-1]
            prev.text     = prev.text + "\n" + body
            prev.line_end = end
        if end >= n:
            break
        i = end - _CHUNK_LINES_OVERLAP
    return out


# ── BM25 ────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


def _tokenise(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _bm25_score(
    query_tokens: list[str],
    doc_tokens:   list[str],
    avg_dl:       float,
    df:           dict[str, int],
    n_docs:       int,
    k1:           float = 1.5,
    b:            float = 0.75,
) -> float:
    if not doc_tokens:
        return 0.0
    counts = Counter(doc_tokens)
    dl = len(doc_tokens)
    score = 0.0
    for q in set(query_tokens):
        f = counts.get(q, 0)
        if f == 0:
            continue
        idf = math.log(1 + (n_docs - df.get(q, 0) + 0.5) / (df.get(q, 0) + 0.5))
        denom = f + k1 * (1 - b + b * dl / max(avg_dl, 1.0))
        score += idf * (f * (k1 + 1) / denom)
    return score


# above this threshold it's worth paying the thread-dispatch overhead
_PARALLEL_CHUNK_THRESHOLD = 50


def rank_chunks_scored(
    chunks: list[Chunk], query: str, *, top_k: int
) -> list[tuple[float, Chunk]]:
    """Return up to ``top_k`` (score, chunk) pairs sorted by descending BM25 score."""
    if not chunks:
        return []
    if not query.strip():
        return [(0.0, c) for c in chunks[:top_k]]
    docs = [_tokenise(c.text) for c in chunks]
    avg_dl = sum(len(d) for d in docs) / max(len(docs), 1)
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    q_tokens = _tokenise(query)
    n_docs = len(docs)

    if n_docs > _PARALLEL_CHUNK_THRESHOLD:
        # large doc sets get scored in parallel to keep things snappy
        def _score_pair(pair: tuple[list[str], Chunk]) -> tuple[float, Chunk]:
            d, c = pair
            return (_bm25_score(q_tokens, d, avg_dl, df, n_docs), c)

        scored = list(_pool().map(_score_pair, zip(docs, chunks)))
    else:
        scored = [
            (_bm25_score(q_tokens, d, avg_dl, df, n_docs), c)
            for d, c in zip(docs, chunks)
        ]

    scored.sort(key=lambda x: x[0], reverse=True)
    nonzero = [(s, c) for s, c in scored if s > 0]
    if nonzero:
        return nonzero[:top_k]
    return scored[:top_k]


def rank_chunks(chunks: list[Chunk], query: str, *, top_k: int) -> list[Chunk]:
    """Return up to ``top_k`` chunks sorted by descending BM25 score."""
    return [c for _, c in rank_chunks_scored(chunks, query, top_k=top_k)]


# ── Public composition ──────────────────────────────────────────────
def build_rag_context(
    files: list[tuple[str, str]],
    query: str,
    *,
    max_chars: int = 8_000,
    top_k:     int = 6,
) -> str:
    """Produce a ready-to-inject ``file_context`` string from ``files``."""
    if not files:
        return ""
    all_chunks: list[Chunk] = []
    for name, content in files:
        if not isinstance(name, str) or not isinstance(content, str):
            continue
        all_chunks.extend(chunk_text(name, content))
    if not all_chunks:
        return ""
    ranked = rank_chunks(all_chunks, query, top_k=top_k)
    return _render_chunks(ranked, max_chars=max_chars)


def _render_chunks(chunks: list[Chunk], *, max_chars: int) -> str:
    parts: list[str] = []
    used = 0
    for c in chunks:
        block = f"{c.header()}\n{c.text}\n"
        cost = len(block)
        if used + cost > max_chars and parts:
            break
        parts.append(block)
        used += cost
    return "\n".join(parts).rstrip()


# ── Stateful RAG index ───────────────────────────────────────────────────────

class RAG:
    """Stateful in-process RAG index over (filename, content) pairs."""

    _MAX_FILES: int = 500
    _MAX_CACHE: int = 128  # LRU cap — prevents unbounded growth in long sessions

    def __init__(self) -> None:
        self._files: dict[str, str] = {}              # filename → content
        self._query_cache: OrderedDict[str, str] = OrderedDict()  # LRU cache
        self._cache_version: int = 0                  # bumped on every add/remove

    # ── Mutation ─────────────────────────────────────────────────────────────

    def add(self, filename: str, content: str) -> None:
        """Index (or re-index) a file."""
        self._files[filename] = content
        self._cache_version += 1
        self._query_cache.clear()  # type: ignore[attr-defined]
        _log.debug("RAG: added %s (%d chars)", filename, len(content))
        # evict oldest file when we hit the cap — dict preserves insertion order so FIFO is easy
        if len(self._files) > self._MAX_FILES:
            oldest_key = next(iter(self._files))
            del self._files[oldest_key]
            _log.debug("rag: evicted '%s' (file cap %d reached)", oldest_key, self._MAX_FILES)

    def remove(self, filename: str) -> bool:
        """Remove a file from the index. Returns True if it was present."""
        if filename in self._files:
            del self._files[filename]
            self._cache_version += 1
            self._query_cache.clear()
            _log.debug("RAG: removed %s", filename)
            return True
        # also try a substring match so /drop works with partial paths
        for key in list(self._files):
            if filename in key or key in filename:
                del self._files[key]
                self._cache_version += 1
                self._query_cache.clear()
                _log.debug("RAG: removed %s (fuzzy match → %s)", filename, key)
                return True
        return False

    def clear(self) -> None:
        """Remove all indexed files and reset the index."""
        self._files.clear()
        self._query_cache.clear()
        self._cache_version += 1

    # ── Query ────────────────────────────────────────────────────────────────

    def query(self, text: str, *, top_k: int = 6, max_chars: int = 8_000) -> str:
        """Return BM25-ranked chunks relevant to *text*."""
        # cache key includes version so stale results can't leak after add/remove
        cache_key = f"{self._cache_version}:{top_k}:{max_chars}:{text}"
        if cache_key in self._query_cache:
            self._query_cache.move_to_end(cache_key)
            _log.debug("RAG: query cache hit (version %d)", self._cache_version)
            return self._query_cache[cache_key]
        files = list(self._files.items())
        result = build_rag_context(files, text, max_chars=max_chars, top_k=top_k)
        self._query_cache[cache_key] = result
        self._query_cache.move_to_end(cache_key)
        if len(self._query_cache) > self._MAX_CACHE:
            self._query_cache.popitem(last=False)
        return result

    # ── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return index statistics."""
        all_chunks: list[Chunk] = []
        total_chars = 0
        for name, content in self._files.items():
            all_chunks.extend(chunk_text(name, content))
            total_chars += len(content)
        return {
            "chunks":      len(all_chunks),
            "files":       list(self._files.keys()),
            "total_chars": total_chars,
        }
