"""Hybrid retriever — fuses BM25 keyword + semantic embedding search."""
from __future__ import annotations

import ast
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.hybrid_retriever")

# fallback thresholds when cfg values aren't available
_BM25_SCORE_DEFAULT     = 0.6
_SEMANTIC_SCORE_DEFAULT = 0.75

# per-language regex patterns for pulling out function/class/interface names
_LANG_SYMBOL_RE: dict[str, re.Pattern] = {
    ".js": re.compile(
        r"(?:^|\n)\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"
        r"|(?:^|\n)\s*(?:export\s+)?class\s+(\w+)",
        re.MULTILINE,
    ),
    ".ts": re.compile(
        r"(?:^|\n)\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"
        r"|(?:^|\n)\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)"
        r"|(?:^|\n)\s*(?:export\s+)?interface\s+(\w+)",
        re.MULTILINE,
    ),
    ".jsx": re.compile(
        r"(?:^|\n)\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"
        r"|(?:^|\n)\s*(?:export\s+)?class\s+(\w+)",
        re.MULTILINE,
    ),
    ".tsx": re.compile(
        r"(?:^|\n)\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"
        r"|(?:^|\n)\s*(?:export\s+)?class\s+(\w+)"
        r"|(?:^|\n)\s*(?:export\s+)?interface\s+(\w+)",
        re.MULTILINE,
    ),
    ".go": re.compile(
        r"(?:^|\n)func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\("
        r"|(?:^|\n)type\s+(\w+)\s+struct",
        re.MULTILINE,
    ),
    ".rs": re.compile(
        r"(?:^|\n)\s*(?:pub\s+)?fn\s+(\w+)\s*[<(]"
        r"|(?:^|\n)\s*(?:pub\s+)?struct\s+(\w+)"
        r"|(?:^|\n)\s*(?:pub\s+)?enum\s+(\w+)",
        re.MULTILINE,
    ),
    ".java": re.compile(
        r"(?:^|\n)\s*(?:public|private|protected|static|\s)*\s+(?:\w+)\s+(\w+)\s*\("
        r"|(?:^|\n)\s*(?:public\s+)?class\s+(\w+)",
        re.MULTILINE,
    ),
}


def _extract_symbols_by_language(path: str, text: str) -> list[str]:
    """Return symbol names found in *text* using language-specific regex."""
    suffix = Path(path).suffix.lower()
    pattern = _LANG_SYMBOL_RE.get(suffix)
    if pattern is None:
        return []
    symbols: list[str] = []
    for m in pattern.finditer(text):
        # only one group fires per match in the alternations — grab the first non-None one
        name = next((g for g in m.groups() if g), None)
        if name:
            symbols.append(name)
    return symbols


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


def _parse_rag_blocks(text: str, default_score: float, kind: str) -> list[RetrievedChunk]:
    """Parse RAG output text into RetrievedChunk objects."""
    results: list[RetrievedChunk] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        source = ""
        content = block
        if block.startswith("[File:"):
            try:
                header_end = block.index("]")
                header_inner = block[6:header_end]  # everything after "[File:"
                source = header_inner.split(",")[0].strip()
                content = block[header_end + 1:].strip()
            except (ValueError, IndexError):
                # malformed header — treat the whole block as content
                _log.debug("hybrid_retriever: skipping malformed chunk header in block: %r", block[:80])
                source = ""
                content = block
        if content:
            results.append(RetrievedChunk(
                source=source,
                content=content,
                score=default_score,
                kind=kind,
            ))
    return results


def _parse_line_range(block_text: str) -> tuple[str, int] | None:
    """Extract (file, line_start) from a '[File: path, lines a-b]' header."""
    if not block_text.startswith("[File:"):
        return None
    try:
        header_end = block_text.index("]")
        header_inner = block_text[6:header_end]
        parts = header_inner.split(",")
        file_part = parts[0].strip()
        if len(parts) >= 2:
            lines_part = parts[1].strip()
            tokens = lines_part.split()
            if len(tokens) >= 2:
                range_token = tokens[1]  # "a-b"
                line_start = int(range_token.split("-")[0])
                return (file_part, line_start)
        return (file_part, 0)
    except (ValueError, IndexError):
        return None


class HybridRetriever:

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._semantic = None                       # lazy — avoid heavy import on startup
        self._symbol_index: dict[str, str] = {}    # symbol_name -> file_path
        self._mtime_cache: dict[str, float] = {}   # str(path) -> last known mtime
        # guard against MagicMock / non-numeric values in tests
        try:
            self._bm25_score = float(cfg.rag_bm25_weight)
        except (AttributeError, TypeError, ValueError):
            self._bm25_score = _BM25_SCORE_DEFAULT
        try:
            self._semantic_score = float(cfg.rag_semantic_weight)
        except (AttributeError, TypeError, ValueError):
            self._semantic_score = _SEMANTIC_SCORE_DEFAULT

    # ── public API ────────────────────────────────────────────────────────

    def index_folder(self, folder: str, on_progress: Callable | None = None) -> int:
        """Index all text files in *folder*. Returns count of files indexed."""
        sem = self._get_semantic()
        if sem is None:
            # no embeddings available — fall back to plain BM25
            from app.core.rag import RAG
            sem = RAG()
            self._semantic = sem
        folder_path = Path(folder)
        if not folder_path.is_dir():
            return 0

        source_files = list(self._iter_source_files(folder_path))
        if not source_files:
            return 0

        def _read_file(path: Path) -> tuple[str, str]:
            return str(path.relative_to(folder_path)), path.read_text(encoding="utf-8", errors="replace")

        # phase 1: parallel reads — pure I/O, safe to do concurrently
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

        # phase 2: sequential indexing — SemanticRAG.add mutates shared state
        count = 0
        for rel, text in file_texts:
            sem.add(rel, text)
            path = folder_path / rel
            self._index_symbols_from_file(str(path), text)
            self._update_mtime(str(path))
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
        sem = self._get_semantic()
        if sem is None:
            return False
        sem.add(path, text)
        self._index_symbols_from_file(path, text)
        self._update_mtime(path)
        return True

    def refresh_changed_files(self, folder: str) -> int:
        """Reindex only files that changed since last index. Returns files refreshed."""
        folder_path = Path(folder)
        if not folder_path.is_dir():
            return 0

        current_paths: set[str] = set()
        refreshed = 0

        for p in self._iter_source_files(folder_path):
            key = str(p)
            current_paths.add(key)
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if key not in self._mtime_cache or self._mtime_cache[key] != mtime:
                if self.index_file(key):
                    refreshed += 1

        # clean up stale cache entries for files deleted from disk
        stale = [k for k in self._mtime_cache if k not in current_paths]
        for key in stale:
            self.remove_file(key)
            del self._mtime_cache[key]
            refreshed += 1

        return refreshed

    def remove_file(self, path: str) -> None:
        sem = self._get_semantic()
        if sem is not None:
            sem.remove(path)

    def query(self, query: str, top_k: int = 8, max_chars: int = 8_000) -> str:
        """Run all retrieval passes and return a formatted context string."""
        results: list[RetrievedChunk] = []

        sem = self._get_semantic()

        # pass 1: BM25 — SemanticRAG.query handles this internally
        if sem is not None:
            try:
                bm25_text = sem.query(query, top_k=top_k, max_chars=max_chars)
                if bm25_text and bm25_text.strip():
                    results.extend(_parse_rag_blocks(bm25_text, self._bm25_score, "bm25"))
            except Exception as exc:
                _log.debug("BM25 retrieve error: %s", exc)

        # pass 2: semantic/vector search
        if sem is not None:
            try:
                sem_text = sem.query(query, top_k=top_k, max_chars=max_chars)
                if sem_text and sem_text.strip():
                    results.extend(_parse_rag_blocks(sem_text, self._semantic_score, "semantic"))
            except Exception as exc:
                _log.debug("Semantic retrieve error: %s", exc)

        # pass 3: symbol name search — quick substring match on indexed names
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

        # deduplicate by (file, line_start) — keep the higher-scored version for duplicates
        dedup: dict[str, RetrievedChunk] = {}
        for r in results:
            line_key = _parse_line_range(
                f"[File: {r.source}, {r.content[:40]}]" if r.source else r.content
            )
            if line_key is not None:
                key = f"{line_key[0]}:{line_key[1]}"
            else:
                key = f"{r.source}|{r.content[:64]}"
            if key not in dedup or r.score > dedup[key].score:
                dedup[key] = r

        ranked = sorted(dedup.values(), key=lambda x: -x.score)[:top_k]

        # render as plain text blocks for injection into the system prompt
        parts: list[str] = []
        used = 0
        for r in ranked:
            if r.source:
                block = f"[File: {r.source}]\n{r.content}\n"
            else:
                block = r.content + "\n"
            if used + len(block) > max_chars and parts:
                break
            parts.append(block)
            used += len(block)
        return "\n".join(parts).rstrip()

    def stats(self) -> IndexStats:
        """Return current index statistics."""
        sem = self._get_semantic()
        db_path = Path.home() / ".ilx_cli" / "embeddings.db"
        db_kb = db_path.stat().st_size / 1024 if db_path.exists() else 0.0
        rag_files: dict = getattr(sem, "_files", {}) if sem is not None else {}
        return IndexStats(
            file_count=len(rag_files),
            chunk_count=sum(len(v) for v in rag_files.values()),
            symbol_count=len(self._symbol_index),
            db_size_kb=db_kb,
            index_path=str(db_path),
        )

    def clear(self) -> None:
        """Clear all in-memory index state."""
        sem = self._get_semantic()
        if sem is not None:
            sem.clear()
        self._symbol_index.clear()

    # ── private ───────────────────────────────────────────────────────────

    def _get_semantic(self):
        # lazy init so we don't pay the import cost until someone actually queries
        if self._semantic is None:
            try:
                from app.core.semantic_rag import SemanticRAG
                self._semantic = SemanticRAG(self._cfg.ollama_url)
            except Exception as exc:
                _log.warning(
                    "hybrid_retriever: SemanticRAG init failed (%s) — "
                    "falling back to BM25-only mode",
                    exc,
                )
                self._semantic = None
        return self._semantic

    def _update_mtime(self, path: str) -> None:
        try:
            self._mtime_cache[path] = Path(path).stat().st_mtime
        except OSError:
            pass

    def _index_symbols_from_file(self, path: str, text: str) -> None:
        suffix = Path(path).suffix.lower()
        if suffix == ".py":
            # use the AST for Python — more accurate than regex
            try:
                tree = ast.parse(text)
            except SyntaxError:
                return
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self._symbol_index[node.name] = path
        elif suffix in _LANG_SYMBOL_RE:
            for sym in _extract_symbols_by_language(path, text):
                self._symbol_index[sym] = path

    def _iter_source_files(self, folder: Path):
        _SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", "dist", "build"}
        _TEXT_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".txt", ".yaml", ".yml",
                      ".toml", ".json", ".sh", ".bash", ".rs", ".go", ".java", ".c", ".cpp", ".h"}
        for p in folder.rglob("*"):
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.is_file() and p.suffix in _TEXT_EXTS and p.stat().st_size < 500_000:
                yield p
