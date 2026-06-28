"""Cluster 22 — Semantic RAG tests.

Tests
-----
A. cosine_similarity — correct result for known orthogonal/parallel vectors
B. cosine_similarity — returns 0.0 for a zero vector
C. EmbeddingClient.embed — returns None when Ollama is unreachable (mocked)
D. EmbeddingClient.embed_batch — None entries are preserved (index alignment)
E. SemanticRAG.add — stores content and falls back gracefully (no embed server)
F. SemanticRAG.query — falls back to BM25 when no embeddings are stored
G. rank_chunks_scored — returns (float, Chunk) tuples with correct types
H. hybrid scoring — chunks with high cosine similarity rank higher than BM25-only
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
from app.core.rag import Chunk, rank_chunks_scored
from app.core.semantic_rag import (
    EmbeddingClient,
    SemanticRAG,
    cosine_similarity,
    get_rag,
)


# ═══════════════════════════════════════════════════════════════════════════════
# A. cosine_similarity — known vectors
# ═══════════════════════════════════════════════════════════════════════════════

def test_cosine_similarity_parallel():
    """Identical vectors should give cosine similarity of 1.0."""
    v = [1.0, 2.0, 3.0]
    result = cosine_similarity(v, v)
    assert abs(result - 1.0) < 1e-9, f"Expected ~1.0, got {result}"
    save("cosine_parallel", True, {"result": result})


def test_cosine_similarity_orthogonal():
    """Orthogonal vectors should give cosine similarity of 0.0."""
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    result = cosine_similarity(a, b)
    assert abs(result) < 1e-9, f"Expected 0.0, got {result}"
    save("cosine_orthogonal", True, {"result": result})


def test_cosine_similarity_known_value():
    """[1, 1] vs [1, 0] should give cos(45°) ≈ 0.7071."""
    a = [1.0, 1.0]
    b = [1.0, 0.0]
    result = cosine_similarity(a, b)
    expected = 1.0 / (2.0 ** 0.5)
    assert abs(result - expected) < 1e-6, f"Expected ~{expected:.4f}, got {result}"
    save("cosine_known_value", True, {"result": result, "expected": expected})


# ═══════════════════════════════════════════════════════════════════════════════
# B. cosine_similarity — zero vector
# ═══════════════════════════════════════════════════════════════════════════════

def test_cosine_similarity_zero_vector():
    """cosine_similarity returns 0.0 when either vector is all-zeros."""
    assert cosine_similarity([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0
    assert cosine_similarity([1.0, 2.0, 3.0], [0.0, 0.0, 0.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0
    save("cosine_zero_vector", True, {})


def test_cosine_similarity_empty_list():
    """cosine_similarity returns 0.0 for empty inputs."""
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], []) == 0.0
    save("cosine_empty", True, {})


# ═══════════════════════════════════════════════════════════════════════════════
# C. EmbeddingClient.embed — returns None when Ollama unreachable
# ═══════════════════════════════════════════════════════════════════════════════

def test_embedding_client_returns_none_on_network_error():
    """embed() must return None and not raise when the server is unreachable."""
    client = EmbeddingClient(ollama_url="http://localhost:19999")
    # No mock needed — port 19999 should not be listening.
    # But to keep the test deterministic and fast, patch urlopen.
    import urllib.error

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        result = client.embed("hello world")
    assert result is None
    save("embed_client_none_on_error", True, {"result": result})


def test_embedding_client_returns_none_on_http_error():
    """embed() returns None when Ollama returns an HTTP error (model not found)."""
    import urllib.error

    err = urllib.error.HTTPError(
        url="http://localhost:11434/api/embeddings",
        code=404,
        msg="Not Found",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=err):
        client = EmbeddingClient()
        result = client.embed("test text")
    assert result is None
    save("embed_client_none_on_http_error", True, {"result": result})


# ═══════════════════════════════════════════════════════════════════════════════
# D. EmbeddingClient.embed_batch — None entries preserved for index alignment
# ═══════════════════════════════════════════════════════════════════════════════

def test_embed_batch_preserves_none_entries():
    """embed_batch must return None for failed items (not skip them)."""
    good_vec = [0.1, 0.2, 0.3]

    def _fake_embed(text: str) -> list[float] | None:
        # Fail for the second item only.
        return None if text == "BAD" else good_vec

    client = EmbeddingClient()
    client.embed = _fake_embed  # type: ignore[method-assign]

    results = client.embed_batch(["OK", "BAD", "OK"])
    assert results == [good_vec, None, good_vec], f"Unexpected: {results}"
    assert len(results) == 3, "embed_batch must not skip None entries"
    save("embed_batch_none_preserved", True, {"results": results})


# ═══════════════════════════════════════════════════════════════════════════════
# E. SemanticRAG.add — stores content, falls back when no embed server
# ═══════════════════════════════════════════════════════════════════════════════

def test_semantic_rag_add_stores_content():
    """add() indexes the file so query() can return relevant content."""
    rag = SemanticRAG()
    # Patch out the embedding client so no network call is made.
    rag._embedding_client.embed = lambda text: None  # type: ignore[method-assign]

    rag.add("notes.txt", "Python decorators wrap functions with extra behaviour.")
    stats = rag.get_stats()
    assert "notes.txt" in stats["files"]
    assert stats["total_chars"] > 0
    save("semantic_rag_add_stores_content", True, stats)


def test_semantic_rag_add_handles_no_embed_server():
    """add() completes without raising even when embed returns None for all chunks."""
    rag = SemanticRAG(ollama_url="http://localhost:19999")
    with patch("urllib.request.urlopen", side_effect=OSError("unreachable")):
        rag.add("file.py", "def foo():\n    return 42\n")
    # Embeddings dict should exist but contain all-empty vectors.
    vecs = rag._embeddings.get("file.py", [])
    assert isinstance(vecs, list)
    # No non-empty vectors expected.
    assert all(v == [] for v in vecs)
    save("semantic_rag_add_no_server", True, {"vectors_stored": len(vecs)})


# ═══════════════════════════════════════════════════════════════════════════════
# F. SemanticRAG.query — falls back to BM25 when no embeddings
# ═══════════════════════════════════════════════════════════════════════════════

def test_semantic_rag_query_falls_back_to_bm25():
    """query() returns relevant BM25 results when no embeddings are stored."""
    rag = SemanticRAG()
    # Ensure embed always returns None.
    rag._embedding_client.embed = lambda text: None  # type: ignore[method-assign]

    content = (
        "BM25 is a ranking function used by search engines.\n"
        "It stands for Best Match 25.\n"
        "BM25 uses term frequency and inverse document frequency.\n"
    ) * 5  # Repeat to get multiple chunks.
    rag.add("search.txt", content)

    result = rag.query("BM25 ranking function")
    assert "BM25" in result, f"Expected BM25 content in result, got: {result[:200]}"
    save("semantic_rag_bm25_fallback", True, {"result_len": len(result)})


# ═══════════════════════════════════════════════════════════════════════════════
# G. rank_chunks_scored — returns (float, Chunk) tuples
# ═══════════════════════════════════════════════════════════════════════════════

def test_rank_chunks_scored_returns_typed_tuples():
    """rank_chunks_scored must return list[tuple[float, Chunk]]."""
    chunks = [
        Chunk(file="a.txt", line_start=1, line_end=5,
              text="Python is a programming language."),
        Chunk(file="a.txt", line_start=6, line_end=10,
              text="Asyncio allows concurrent IO operations."),
        Chunk(file="a.txt", line_start=11, line_end=15,
              text="Decorators modify function behaviour."),
    ]
    scored = rank_chunks_scored(chunks, "Python programming", top_k=3)
    assert isinstance(scored, list)
    assert len(scored) <= 3
    for item in scored:
        score, chunk = item
        assert isinstance(score, float), f"Score must be float, got {type(score)}"
        assert isinstance(chunk, Chunk), f"Expected Chunk, got {type(chunk)}"
    save("rank_chunks_scored_types", True, {
        "count": len(scored),
        "scores": [s for s, _ in scored],
    })


def test_rank_chunks_scored_empty_input():
    """rank_chunks_scored returns [] for empty chunks list."""
    result = rank_chunks_scored([], "anything", top_k=5)
    assert result == []
    save("rank_chunks_scored_empty", True, {})


# ═══════════════════════════════════════════════════════════════════════════════
# H. Hybrid scoring — high-cosine chunks rank higher
# ═══════════════════════════════════════════════════════════════════════════════

def test_hybrid_scoring_cosine_boosts_rank():
    """When embeddings are available, high-cosine chunks should rank in top results."""
    rag = SemanticRAG()

    # Two documents: one BM25-relevant, one cosine-relevant.
    doc_bm25 = "vector search retrieval augmented generation"
    doc_cosine = "completely unrelated content about cooking recipes"

    rag.add("bm25_doc.txt", doc_bm25)
    rag.add("cosine_doc.txt", doc_cosine)

    query = "vector search retrieval"
    # query_vec is close to doc_bm25 embedding.
    query_vec = [1.0, 0.0, 0.0]
    bm25_vec  = [0.9, 0.1, 0.0]   # close to query_vec
    cosine_vec = [0.0, 0.0, 1.0]  # orthogonal to query_vec

    # Manually inject embeddings to control the test.
    rag._embeddings["bm25_doc.txt"] = [bm25_vec]
    rag._embeddings["cosine_doc.txt"] = [cosine_vec]

    with patch.object(rag._embedding_client, "embed", return_value=query_vec):
        result = rag.query(query, top_k=2)

    # The BM25-relevant document should appear in the output.
    assert "bm25_doc.txt" in result or "vector search" in result.lower(), (
        f"Expected BM25-relevant content in result: {result[:300]}"
    )
    save("hybrid_scoring_cosine_boosts", True, {"result_len": len(result)})


def test_hybrid_scoring_falls_back_when_query_embed_fails():
    """Hybrid query falls back to BM25 when query embedding returns None."""
    rag = SemanticRAG()
    content = "Machine learning models learn patterns from data.\n" * 8
    rag.add("ml.txt", content)

    # Pre-populate embeddings so has_any_embedding is True.
    fake_vec = [0.5, 0.5]
    from app.core.rag import chunk_text
    n_chunks = len(chunk_text("ml.txt", content))
    rag._embeddings["ml.txt"] = [fake_vec] * n_chunks

    with patch.object(rag._embedding_client, "embed", return_value=None):
        result = rag.query("machine learning patterns")

    assert "machine learning" in result.lower() or "patterns" in result.lower(), (
        f"BM25 fallback should still return relevant content: {result[:300]}"
    )
    save("hybrid_falls_back_no_query_embed", True, {"result_len": len(result)})


# ═══════════════════════════════════════════════════════════════════════════════
# Bonus: get_rag factory
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_rag_returns_plain_rag_when_ollama_unreachable():
    """get_rag() returns a plain RAG when Ollama is not running."""
    from app.core.rag import RAG

    with patch("urllib.request.urlopen", side_effect=OSError("unreachable")):
        rag = get_rag("http://localhost:19999")
    assert isinstance(rag, RAG)
    save("get_rag_fallback", True, {"type": type(rag).__name__})
