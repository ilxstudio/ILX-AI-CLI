"""Lightweight conversation-file RAG for Ollama / local models.

Why local models only?
----------------------
Cloud models (Claude 1M, Gemini 2M, GPT-5 200k+) have enough context
window that whole-file injection is fine and *higher quality* than RAG —
the model can see relationships across the entire document.  Ollama-
hosted models top out at 4–32k tokens; injecting a 200 KB document
truncates the model's actual reasoning room and tends to push the user's
question off the front of the prompt.

So: when the active model is local, we run a small in-process retrieval
pass over the attached files and inject only the top-K most relevant
chunks instead of the whole content.  For cloud models we leave the
caller's existing whole-file path alone.

Design choices
--------------
- **No embeddings**.  Real embedding-based retrieval would mean either
  shipping a model with the desktop (50–500 MB) or relying on a portal
  ``/api/embed`` round-trip (latency + offline failure).  BM25 over
  whitespace tokens is simpler, deterministic, has no dependencies, and
  is the right tool for "find passages that mention these words" — which
  is what most attachment-aware chats actually want.
- **Per-call chunking**.  We rebuild the index every time prepare runs.
  Conversations rarely have hundreds of files; the work is millisecond-
  scale and avoids stale-cache bugs.
- **Citations preserved**.  Each emitted chunk is prefixed with
  ``[File: name, lines a-b]`` so the model can quote them back to the
  user with provenance.

Public API
----------
- :func:`is_local_model(name)` — heuristic; True for Ollama-style ids.
- :func:`build_rag_context(files, query, *, max_chars)` — returns the
  formatted ``file_context`` string ready for ``stream_chat``.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass

_log = logging.getLogger("ilx_cli.rag")

# Chunk targets.  Tuned for 8 KB cumulative budget (typical Ollama
# 4k-token window with room for the user's prompt + system prompt).
_CHUNK_LINES_TARGET = 24
_CHUNK_LINES_OVERLAP = 4
_MIN_CHUNK_CHARS = 80


# Cloud model id prefixes / substrings — anything matching one of these
# is **not** routed through RAG.  Conservative: when unsure, treat the
# model as cloud and keep whole-file behaviour.
_CLOUD_MARKERS = (
    "claude", "gpt-", "gpt4", "gpt5", "gemini", "groq", "anthropic",
    "openai", "o3", "o4", "o5", "deepseek-cloud",
)


def is_local_model(name: str) -> bool:
    """Best-effort 'is this an Ollama / local model?' check.

    Returns True when no cloud markers are detected — defaulting to local
    so Ollama-tagged ids without obvious naming still take the RAG path.
    """
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
    """Break a file into ~24-line chunks with 4-line overlap.

    Lines under :data:`_MIN_CHUNK_CHARS` worth of content get folded
    into the next chunk so we don't ship near-empty fragments.
    """
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


def rank_chunks_scored(
    chunks: list[Chunk], query: str, *, top_k: int
) -> list[tuple[float, Chunk]]:
    """Return up to ``top_k`` (score, chunk) pairs sorted by descending BM25 score.

    Scores are raw BM25 values.  Returns zero-scored pairs when the query is
    empty or no term matches — never an empty list (unless ``chunks`` is empty).
    """
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
    scored = [
        (_bm25_score(q_tokens, d, avg_dl, df, len(docs)), c)
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
    """Produce a ready-to-inject ``file_context`` string from ``files``.

    ``files`` is ``[(filename, content), ...]``.  The result uses
    ``[File: name, lines a-b]`` headers followed by the chunk body.

    Total output size is capped at ``max_chars`` (default 8 KB) so we
    don't blow past the local model's context regardless of how many
    chunks BM25 scored highly.
    """
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
    """Stateful in-process RAG index over (filename, content) pairs.

    Supports incremental add/remove so that /add and /drop commands can
    keep the index in sync with the pinned-file list.

    Public API
    ----------
    - ``add(filename, content)``       — index a file (replaces if already present)
    - ``remove(filename)``             — remove a file from the index
    - ``query(text, *, top_k, max_chars)`` — retrieve relevant chunks
    - ``get_stats()``                  — return index statistics dict
    """

    _MAX_FILES: int = 500

    def __init__(self) -> None:
        self._files: dict[str, str] = {}   # filename → content
        self._query_cache: dict[str, str] = {}   # cache_key → rendered result
        self._cache_version: int = 0             # bumped on every add/remove

    # ── Mutation ─────────────────────────────────────────────────────────────

    def add(self, filename: str, content: str) -> None:
        """Index (or re-index) a file."""
        self._files[filename] = content
        self._cache_version += 1
        self._query_cache.clear()
        _log.debug("RAG: added %s (%d chars)", filename, len(content))
        # Evict oldest file if cap exceeded (FIFO — dict preserves insertion order)
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
        # Also try a substring match (drop by path suffix)
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
        """Return BM25-ranked chunks relevant to *text*.

        Results are cached per (version, top_k, max_chars, text) key.
        The cache is invalidated whenever add(), remove(), or clear() is called.
        """
        cache_key = f"{self._cache_version}:{top_k}:{max_chars}:{text}"
        if cache_key in self._query_cache:
            _log.debug("RAG: query cache hit (version %d)", self._cache_version)
            return self._query_cache[cache_key]
        files = list(self._files.items())
        result = build_rag_context(files, text, max_chars=max_chars, top_k=top_k)
        self._query_cache[cache_key] = result
        return result

    # ── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return index statistics.

        Keys
        ----
        ``chunks``      — total number of chunks across all indexed files
        ``files``       — list of indexed filenames
        ``total_chars`` — total character count of all indexed content
        """
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
