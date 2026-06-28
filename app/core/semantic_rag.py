"""Semantic RAG using sqlite-vec for vector similarity search.

Falls back to BM25 (app/core/rag.py) when sqlite-vec is not installed
or when embeddings are unavailable (no local embedding model).

Embedding strategy:
  1. Try sqlite-vec + a local /api/embed Ollama endpoint
  2. Fall back to BM25 when either is unavailable

Design: hybrid retrieval — BM25 scores + cosine similarity averaged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from app.core.rag import (
    RAG,
    Chunk,
    _render_chunks,
    chunk_text,
    rank_chunks_scored,
)

_log = logging.getLogger("ilx_cli.semantic_rag")

# ── Persistent embedding store ───────────────────────────────────────────────

_DB_PATH = Path.home() / ".ilx_cli" / "embeddings.db"


class PersistentEmbeddingStore:
    """SQLite-backed store for cross-session embedding persistence.

    Keyed by (filename, content_hash) so stale embeddings for changed files
    are transparently replaced.  ``self._embeddings`` in :class:`SemanticRAG`
    remains the in-session cache for fast lookups; this store handles persistence.
    """

    def __init__(self, path: Path = _DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                filename     TEXT    NOT NULL,
                content_hash TEXT    NOT NULL,
                chunk_idx    INTEGER NOT NULL,
                vector       TEXT    NOT NULL,
                PRIMARY KEY (filename, chunk_idx)
            )
        """)
        self._db.commit()

    def get_vectors(
        self, filename: str, content_hash: str
    ) -> list[list[float]] | None:
        """Return stored vectors when *content_hash* matches, else ``None``."""
        rows = self._db.execute(
            "SELECT vector FROM embeddings"
            " WHERE filename=? AND content_hash=? ORDER BY chunk_idx",
            (filename, content_hash),
        ).fetchall()
        if not rows:
            return None
        return [json.loads(r[0]) for r in rows]

    def put_vectors(
        self, filename: str, content_hash: str, vectors: list[list[float]]
    ) -> None:
        """Persist *vectors* for *filename*, replacing any prior entry."""
        self._db.execute("DELETE FROM embeddings WHERE filename=?", (filename,))
        for i, v in enumerate(vectors):
            self._db.execute(
                "INSERT INTO embeddings VALUES (?,?,?,?)",
                (filename, content_hash, i, json.dumps(v)),
            )
        self._db.commit()

    def delete(self, filename: str) -> None:
        """Remove all stored embeddings for *filename*."""
        self._db.execute("DELETE FROM embeddings WHERE filename=?", (filename,))
        self._db.commit()

    def close(self) -> None:
        self._db.close()


# ── Cosine similarity ────────────────────────────────────────────────────────


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors.

    Uses numpy when available (3–15× faster via BLAS SIMD), falls back to
    map(operator.mul) which is ~3× faster than zip+generator expression.
    Returns 0.0 on empty, mismatched-length, or all-zero vectors.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        import numpy as _np
        av = _np.array(a, dtype=_np.float32)
        bv = _np.array(b, dtype=_np.float32)
        dot = float(_np.dot(av, bv))
        norm_a = float(_np.linalg.norm(av))
        norm_b = float(_np.linalg.norm(bv))
    except ImportError:
        import operator as _op
        dot = sum(map(_op.mul, a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Embedding client ─────────────────────────────────────────────────────────


class EmbeddingClient:
    """Thin wrapper around Ollama's ``/api/embeddings`` endpoint.

    Uses only stdlib (``urllib.request``) so there are no extra dependencies.
    All errors are caught and surfaced as ``None`` return values so callers can
    fall back gracefully.
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        timeout: int = 10,
    ) -> None:
        self._url = ollama_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    # ── Single embed ────────────────────────────────────────────────────────

    def embed(self, text: str) -> list[float] | None:
        """Return the embedding vector for *text*, or ``None`` on any error.

        POSTs to ``{ollama_url}/api/embeddings`` with
        ``{"model": model, "prompt": text}``.
        """
        endpoint = f"{self._url}/api/embeddings"
        payload = json.dumps({"model": self._model, "prompt": text}).encode()
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read())
            return body.get("embedding")
        except Exception as exc:
            _log.debug("EmbeddingClient.embed failed: %s", exc)
            return None

    # ── Batch embed ─────────────────────────────────────────────────────────

    def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed all texts in a single batch request (Ollama /api/embed).

        Falls back to serial per-text calls when the batch endpoint is
        unavailable (older Ollama builds). Index alignment is always preserved
        — failed chunks are represented as ``None``.
        """
        if not texts:
            return []
        endpoint = f"{self._url}/api/embed"
        payload = json.dumps({"model": self._model, "input": texts}).encode()
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout * len(texts)) as resp:
                body = json.loads(resp.read())
            embeddings = body.get("embeddings", [])
            if len(embeddings) == len(texts):
                return [e if e else None for e in embeddings]
        except Exception as exc:
            _log.debug("embed_batch batch endpoint failed, falling back to serial: %s", exc)
        # Fallback: serial calls (pre-Ollama-0.1.25 or error)
        return [self.embed(t) for t in texts]

    # ── Availability check ───────────────────────────────────────────────────

    def ping(self) -> bool:
        """Return True if the Ollama server is reachable (GET /api/tags)."""
        try:
            req = urllib.request.Request(
                f"{self._url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self._timeout):
                pass
            return True
        except Exception:
            return False


# ── SemanticRAG ──────────────────────────────────────────────────────────────


class SemanticRAG(RAG):
    """Hybrid BM25 + cosine-similarity RAG.

    Extends :class:`~app.core.rag.RAG` with optional embedding-based re-ranking.
    When the Ollama embedding endpoint is unavailable the class degrades
    transparently to pure BM25 (parent behaviour).

    Hybrid score formula
    --------------------
    ``combined = 0.6 * bm25_norm + 0.4 * cosine``

    BM25 scores are min-max normalised across the candidate set before
    combining so both signals live on [0, 1].
    """

    _BM25_WEIGHT = 0.6
    _COSINE_WEIGHT = 0.4

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        embed_model: str = "nomic-embed-text",
    ) -> None:
        super().__init__()
        self._embedding_client = EmbeddingClient(
            ollama_url=ollama_url, model=embed_model
        )
        # filename → list of per-chunk embedding vectors (parallel to chunk list)
        self._embeddings: dict[str, list[list[float]]] = {}
        # Cross-session persistence layer
        self._store = PersistentEmbeddingStore()

    # ── Mutation overrides ───────────────────────────────────────────────────

    def add(self, filename: str, content: str) -> None:
        """Index a file and pre-compute chunk embeddings when possible.

        Checks the persistent store first; skips the embedding call when the
        file content has not changed since the last session.
        """
        super().add(filename, content)
        chunks = chunk_text(filename, content)
        if not chunks:
            self._embeddings.pop(filename, None)
            return

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        cached = self._store.get_vectors(filename, content_hash)
        if cached is not None:
            self._embeddings[filename] = cached
            _log.debug(
                "SemanticRAG: loaded %d cached chunk vectors for %s",
                len(cached),
                filename,
            )
            return

        vectors = self._embedding_client.embed_batch(
            [c.text for c in chunks]
        )
        # Only store embeddings for chunks that succeeded; use empty list for
        # chunks whose embedding returned None so the per-chunk index aligns.
        new_vectors: list[list[float]] = []
        for v in vectors:
            new_vectors.append(v if v is not None else [])
        self._embeddings[filename] = new_vectors
        self._store.put_vectors(filename, content_hash, new_vectors)
        _log.debug(
            "SemanticRAG: embedded %d/%d chunks for %s",
            sum(1 for v in new_vectors if v),
            len(new_vectors),
            filename,
        )

    def remove(self, filename: str) -> bool:
        """Remove a file and its stored embeddings (in-session and persistent)."""
        result = super().remove(filename)
        self._store.delete(filename)
        self._embeddings.pop(filename, None)
        # Parent may have matched by fuzzy key — sweep any remaining keys that
        # are no longer in _files.
        stale = [k for k in self._embeddings if k not in self._files]
        for k in stale:
            self._store.delete(k)
            del self._embeddings[k]
        return result

    # ── Query override ───────────────────────────────────────────────────────

    def query(
        self,
        text: str,
        *,
        top_k: int = 6,
        max_chars: int = 8_000,
    ) -> str:
        """Hybrid retrieval: BM25 + cosine similarity.

        Falls back to pure BM25 when:
        - No embeddings have been stored yet.
        - The query cannot be embedded (server unreachable, model missing).
        """
        files = list(self._files.items())
        if not files:
            return ""

        # Build full chunk list (needed for BM25 and cosine).
        all_chunks: list[Chunk] = []
        chunk_vecs: list[list[float]] = []  # parallel to all_chunks
        for name, content in files:
            if not isinstance(name, str) or not isinstance(content, str):
                continue
            file_chunks = chunk_text(name, content)
            stored_vecs = self._embeddings.get(name, [])
            for i, c in enumerate(file_chunks):
                all_chunks.append(c)
                vec = stored_vecs[i] if i < len(stored_vecs) else []
                chunk_vecs.append(vec)

        if not all_chunks:
            return ""

        # Check whether we have usable embeddings at all.
        has_any_embedding = any(v for v in chunk_vecs)
        if not has_any_embedding:
            # Pure BM25 fallback.
            return super().query(text, top_k=top_k, max_chars=max_chars)

        # Embed the query.
        query_vec = self._embedding_client.embed(text)
        if query_vec is None:
            _log.debug("SemanticRAG: query embedding failed — using BM25 fallback")
            return super().query(text, top_k=top_k, max_chars=max_chars)

        # BM25 scores.
        bm25_pairs = rank_chunks_scored(all_chunks, text, top_k=len(all_chunks))
        # Build a lookup: chunk id → bm25 score.
        bm25_by_id: dict[int, float] = {}
        for score, chunk in bm25_pairs:
            bm25_by_id[id(chunk)] = score

        # Normalise BM25 scores to [0, 1].
        raw_scores = [bm25_by_id.get(id(c), 0.0) for c in all_chunks]
        max_bm25 = max(raw_scores) if raw_scores else 0.0
        min_bm25 = min(raw_scores) if raw_scores else 0.0
        span = max_bm25 - min_bm25

        def _norm_bm25(s: float) -> float:
            if span == 0.0:
                return 0.0
            return (s - min_bm25) / span

        # Combine scores.
        combined: list[tuple[float, Chunk]] = []
        for chunk, vec, raw in zip(all_chunks, chunk_vecs, raw_scores):
            cosine = cosine_similarity(query_vec, vec) if vec else 0.0
            score = self._BM25_WEIGHT * _norm_bm25(raw) + self._COSINE_WEIGHT * cosine
            combined.append((score, chunk))

        combined.sort(key=lambda x: x[0], reverse=True)
        top_chunks = [c for _, c in combined[:top_k]]
        return _render_chunks(top_chunks, max_chars=max_chars)


# ── Factory ──────────────────────────────────────────────────────────────────


def get_rag(ollama_url: str = "http://localhost:11434") -> SemanticRAG | RAG:
    """Return a :class:`SemanticRAG` when Ollama is reachable, else :class:`RAG`.

    The ping check is a lightweight GET to ``/api/tags`` (no model load).
    If it fails for any reason (server down, timeout, etc.) we return the
    plain BM25 :class:`RAG` so callers are never blocked on startup.
    """
    try:
        client = EmbeddingClient(ollama_url=ollama_url)
        if client.ping():
            _log.debug("SemanticRAG: Ollama reachable — using semantic RAG")
            return SemanticRAG(ollama_url=ollama_url)
    except Exception as exc:
        _log.debug("get_rag: ping failed (%s) — falling back to BM25 RAG", exc)
    _log.debug("SemanticRAG: Ollama unreachable — using BM25 RAG")
    return RAG()
