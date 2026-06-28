"""Hybrid retriever -- fuses BM25 keyword + semantic embedding search.

Wraps SemanticRAG (which already does BM25+vector internally) and adds:
- Symbol search via Python AST
- File-tree structural search
- Cross-session persistence via PersistentEmbeddingStore
"""
from __future__ import annotations

import ast
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.hybrid_retriever")


@dataclass
class RetrievedChunk:
    source:  str    # file path or symbol path
    content: str
    score:   float
    kind:    str    # "semantic" | "bm25" | "symbol" | "file_tree"


@dataclass
class IndexStats:
    file_count:   int = 0
    chunk_count:  int = 0
    symbol_count: int = 0
    db_size_kb:   float = 0.0
    index_path:   str = ""


class HybridRetriever:
    """
    Multi-pass retriever combining:
      1. BM25 keyword search (via RAG)
      2. Semantic / vector search (via SemanticRAG)
      3. AST symbol search for Python files
    """

    def __init__(self, cfg: "AppConfig") -> None:
        self._cfg = cfg
        self._semantic = None                     # lazy — avoid heavy import on startup
        self._symbol_index: dict[str, str] = {}  # symbol_name -> file_path

    # ── public API ────────────────────────────────────────────────────────

    def index_folder(self, folder: str, on_progress: "Callable | None" = None) -> int:
        """Index all text files in *folder*. Returns count of files indexed.

        Files are read in parallel (I/O-bound); indexing is serialized per
        file to keep SemanticRAG's embedding state consistent.
        """
        sem = self._get_semantic()   # SemanticRAG IS-A RAG — single shared instance
        folder_path = Path(folder)
        if not folder_path.is_dir():
            return 0

        source_files = list(self._iter_source_files(folder_path))
        if not source_files:
            return 0

        def _read_file(path: Path) -> tuple[str, str]:
            return str(path.relative_to(folder_path)), path.read_text(encoding="utf-8", errors="replace")

        # Phase 1: parallel file reads (pure I/O, thread-safe)
        file_texts: list[tuple[str, str]] = []
        workers = min(8, len(source_files))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_read_file, p): p for p in source_files}
            for fut in as_completed(futs):
                try:
                    rel, text = fut.result()
                    file_texts.append((rel, text))
                except OSError:
                    continue

        # Phase 2: sequential indexing (SemanticRAG.add mutates shared state)
        count = 0
        for rel, text in file_texts:
            sem.add(rel, text)
            path = folder_path / rel
            if path.suffix == ".py":
                self._index_symbols_from_file(str(path), text)
            count += 1
            if on_progress:
                try:
                    on_progress(rel)
                except Exception as exc:
                    _log.debug("on_progress callback error: %s", exc)

        return count

    def index_file(self, path: str) -> bool:
        """Add or refresh a single file in the index."""
        p = Path(path)
        if not p.exists():
            return False
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        self._get_semantic().add(path, text)   # SemanticRAG IS-A RAG — one add() suffices
        if p.suffix == ".py":
            self._index_symbols_from_file(path, text)
        return True

    def remove_file(self, path: str) -> None:
        self._get_semantic().remove(path)

    def query(self, query: str, top_k: int = 8) -> list[RetrievedChunk]:
        """Run all retrieval passes and return deduplicated, ranked results."""
        results: list[RetrievedChunk] = []

        # 1. BM25 — RAG.query returns a rendered string; parse into chunks
        try:
            bm25_text = self._get_rag().query(query, top_k=top_k)
            if bm25_text and bm25_text.strip():
                # Each block starts with "[File: <path>, ...]"
                for block in bm25_text.split("\n\n"):
                    block = block.strip()
                    if not block:
                        continue
                    source = ""
                    if block.startswith("[File:"):
                        header_end = block.index("]")
                        source = block[6:header_end].split(",")[0].strip()
                        content = block[header_end + 1:].strip()
                    else:
                        content = block
                    results.append(RetrievedChunk(
                        source=source,
                        content=content,
                        score=0.6,
                        kind="bm25",
                    ))
        except Exception as exc:
            _log.debug("BM25 retrieve error: %s", exc)

        # 2. Semantic — SemanticRAG.query also returns a string
        try:
            sem_text = self._get_semantic().query(query, top_k=top_k)
            if sem_text and sem_text.strip():
                for block in sem_text.split("\n\n"):
                    block = block.strip()
                    if not block:
                        continue
                    source = ""
                    if block.startswith("[File:"):
                        header_end = block.index("]")
                        source = block[6:header_end].split(",")[0].strip()
                        content = block[header_end + 1:].strip()
                    else:
                        content = block
                    results.append(RetrievedChunk(
                        source=source,
                        content=content,
                        score=0.75,  # slight semantic boost
                        kind="semantic",
                    ))
        except Exception as exc:
            _log.debug("Semantic retrieve error: %s", exc)

        # 3. Symbol search
        try:
            for sym_name, sym_file in self._symbol_index.items():
                if query.lower() in sym_name.lower():
                    results.append(RetrievedChunk(
                        source=sym_file,
                        content=f"Symbol: {sym_name} in {sym_file}",
                        score=0.9,
                        kind="symbol",
                    ))
        except Exception as exc:
            _log.debug("Symbol search error: %s", exc)

        # Deduplicate by (source, content[:64]) keeping highest score
        seen: dict[str, RetrievedChunk] = {}
        for r in results:
            key = f"{r.source}|{r.content[:64]}"
            if key not in seen or r.score > seen[key].score:
                seen[key] = r

        return sorted(seen.values(), key=lambda x: -x.score)[:top_k]

    def stats(self) -> IndexStats:
        """Return current index statistics."""
        sem = self._get_semantic()
        db_path = Path.home() / ".ilx_cli" / "embeddings.db"
        db_kb = db_path.stat().st_size / 1024 if db_path.exists() else 0.0
        rag_files: dict = getattr(sem, "_files", {})
        return IndexStats(
            file_count=len(rag_files),
            chunk_count=sum(len(v) for v in rag_files.values()),
            symbol_count=len(self._symbol_index),
            db_size_kb=db_kb,
            index_path=str(db_path),
        )

    def clear(self) -> None:
        """Clear all in-memory index state."""
        self._get_semantic().clear()
        self._symbol_index.clear()

    # ── private ───────────────────────────────────────────────────────────

    def _get_rag(self):
        # SemanticRAG IS-A RAG — delegate to the shared semantic instance
        # to avoid maintaining two separate BM25 indexes of the same data.
        return self._get_semantic()

    def _get_semantic(self):
        if self._semantic is None:
            from app.core.semantic_rag import SemanticRAG
            self._semantic = SemanticRAG(self._cfg.ollama_url)
        return self._semantic

    def _index_symbols_from_file(self, path: str, text: str) -> None:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._symbol_index[node.name] = path

    def _iter_source_files(self, folder: Path):
        _SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", "dist", "build"}
        _TEXT_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".txt", ".yaml", ".yml",
                      ".toml", ".json", ".sh", ".bash", ".rs", ".go", ".java", ".c", ".cpp", ".h"}
        for p in folder.rglob("*"):
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.is_file() and p.suffix in _TEXT_EXTS and p.stat().st_size < 500_000:
                yield p
