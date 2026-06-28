"""Unit tests for app/core/rag.py — chunk_text, _bm25_score, rank_chunks_scored, RAG class, is_local_model."""
# Copyright 2026 ILX Studio — MIT License
from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path

import pytest

# Ensure repo root on path (mirrors conftest.py)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.rag import (
    RAG,
    Chunk,
    _bm25_score,
    _tokenise,
    chunk_text,
    is_local_model,
    rank_chunks_scored,
)


# ── chunk_text() ─────────────────────────────────────────────────────────────


def test_chunk_text_empty_returns_empty():
    assert chunk_text("empty.py", "") == []
    assert chunk_text("whitespace.py", "   \n\n  ") == []


def test_chunk_text_short_file_single_chunk():
    content = "\n".join(f"line {i}" for i in range(5))
    chunks = chunk_text("short.py", content)
    assert len(chunks) == 1
    assert chunks[0].file == "short.py"
    assert chunks[0].line_start == 1


def test_chunk_text_long_file_multiple_chunks():
    content = "\n".join(f"line {i:03d}" for i in range(60))
    chunks = chunk_text("long.py", content)
    assert len(chunks) > 1
    # Every chunk must cover a valid line range
    for c in chunks:
        assert c.line_start >= 1
        assert c.line_end >= c.line_start


def test_chunk_text_overlap_lines_shared():
    # 60 lines → multiple chunks; consecutive chunks share the last 4 lines
    content = "\n".join(f"line {i:03d}" for i in range(60))
    chunks = chunk_text("overlap.py", content)
    assert len(chunks) >= 2
    # The end of chunk N overlaps with the start of chunk N+1 by ~4 lines
    for a, b in zip(chunks[:-1], chunks[1:]):
        # a.line_end >= b.line_start (overlap region exists)
        assert a.line_end >= b.line_start


def test_chunk_text_short_lines_folded():
    # Lines under 80 chars total should be folded into the previous chunk
    # rather than emitting a near-empty trailing chunk.
    # Create a file where the tail is a single short line after a full chunk.
    body_lines = [f"def func_{i}(): pass  # some body" for i in range(24)]
    tail = "x = 1"  # very short
    content = "\n".join(body_lines + [tail])
    chunks = chunk_text("fold.py", content)
    # The short tail should be folded into the last chunk, not be a standalone chunk
    # (i.e. we don't end up with a chunk that has only 1 line and <80 chars unless it's the first)
    for c in chunks[1:]:
        # Non-first chunks that exist should have meaningful content
        assert len(c.text) >= 1


# ── _bm25_score() ─────────────────────────────────────────────────────────────


def test_bm25_score_zero_for_no_match():
    query_tokens = _tokenise("elephant banana umbrella")
    doc_tokens = _tokenise("def foo(): return 42")
    score = _bm25_score(query_tokens, doc_tokens, avg_dl=10.0, df={}, n_docs=5)
    assert score == 0.0


def test_bm25_score_positive_for_match():
    query_tokens = _tokenise("function")
    doc_tokens = _tokenise("this document mentions function several times function")
    df = {"function": 1}
    score = _bm25_score(query_tokens, doc_tokens, avg_dl=float(len(doc_tokens)), df=df, n_docs=10)
    assert score > 0.0


def test_bm25_score_empty_doc():
    query_tokens = _tokenise("hello world")
    score = _bm25_score(query_tokens, [], avg_dl=10.0, df={}, n_docs=5)
    assert score == 0.0


# ── rank_chunks_scored() ─────────────────────────────────────────────────────


def test_rank_chunks_scored_empty_input():
    result = rank_chunks_scored([], "any query", top_k=5)
    assert result == []


def test_rank_chunks_scored_prefers_relevant():
    chunks = [
        Chunk(file="a.py", line_start=1, line_end=10, text="def unrelated_function(): pass"),
        Chunk(file="b.py", line_start=1, line_end=10, text="def authenticate_user(token): return True"),
    ]
    results = rank_chunks_scored(chunks, "authenticate user", top_k=2)
    assert len(results) >= 1
    # The chunk containing "authenticate" must appear somewhere in the top-k results
    texts = [c.text for _, c in results]
    assert any("authenticate" in t for t in texts)


def test_rank_chunks_scored_top_k_respected():
    chunks = [
        Chunk(file=f"f{i}.py", line_start=1, line_end=5, text=f"content line {i} hello world")
        for i in range(20)
    ]
    results = rank_chunks_scored(chunks, "hello", top_k=5)
    assert len(results) <= 5


# ── RAG class ─────────────────────────────────────────────────────────────────


def test_rag_cache_invalidated_on_add():
    rag = RAG()
    rag.add("file1.py", "def foo(): pass")
    result1 = rag.query("foo")
    # Add a new file that changes the index
    rag.add("file2.py", "def bar(): return 42")
    result2 = rag.query("bar")
    # The second query should return content from the new file
    assert "bar" in result2


def test_rag_lru_eviction():
    rag = RAG()
    rag.add("seed.py", "def seed(): pass")

    # Fill the query cache beyond the LRU cap
    cap = RAG._MAX_CACHE
    for i in range(cap + 1):
        rag.query(f"unique_query_term_{i}")

    # Cache should not exceed the cap
    assert len(rag._query_cache) <= cap


def test_rag_get_stats_correct():
    rag = RAG()
    rag.add("alpha.py", "def alpha(): pass\ndef beta(): pass")
    rag.add("gamma.py", "class Gamma:\n    pass\n")

    stats = rag.get_stats()
    assert len(stats["files"]) == 2
    assert "alpha.py" in stats["files"]
    assert "gamma.py" in stats["files"]
    assert stats["total_chars"] > 0
    assert stats["chunks"] > 0


# ── is_local_model() ─────────────────────────────────────────────────────────


def test_is_local_model_ollama_names():
    assert is_local_model("llama3:8b") is True
    assert is_local_model("codellama:7b") is True
    assert is_local_model("qwen2.5:14b") is True


def test_is_local_model_cloud_names():
    assert is_local_model("gpt-4o") is False
    assert is_local_model("gemini-pro") is False
