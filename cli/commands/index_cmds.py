"""Index commands — /index: build and query the persistent repo index."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
from cli.display_compat import out, out_error

_log = logging.getLogger("ilx_cli.index_cmds")


class IndexCommands:

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._retriever = None  # lazy init — only create when actually needed

    def cmd_index(self, args: list[str]) -> None:
        """/index [build|status|explain|clear|help]"""
        sub = args[0].lower() if args else "status"
        rest = args[1:]

        dispatch = {
            "build":   self._index_build,
            "status":  self._index_status,
            "explain": self._index_explain,
            "clear":   self._index_clear,
            "help":    self._index_help,
        }
        fn = dispatch.get(sub, self._index_help)
        fn(rest)

    def _index_build(self, args: list[str]) -> None:
        wf = args[0] if args else self._cfg.working_folder
        if not wf or not Path(wf).is_dir():
            out_error(f"  {RED}Invalid workspace: {wf!r}{RESET}")
            out(f"  {DIM}Use /workspace to set one, or pass a path.{RESET}\n")
            return

        out(f"\n{BOLD}Building index for:{RESET} {DIM}{wf}{RESET}")

        # count source files up front so the progress bar can show a real percentage
        _source_exts = {".py", ".js", ".ts", ".md", ".txt", ".json", ".yaml", ".yml",
                        ".toml", ".cfg", ".ini", ".html", ".css", ".rs", ".go", ".java", ".c", ".cpp"}
        _total = sum(
            1 for p in Path(wf).rglob("*")
            if p.is_file() and p.suffix.lower() in _source_exts
            and ".git" not in p.parts
        )
        _current = 0
        _bar_len = 30

        def _progress(rel_path: str) -> None:
            nonlocal _current
            _current += 1
            pct = int(_current / max(_total, 1) * 100)
            filled = int(_bar_len * _current / max(_total, 1))
            bar = "█" * filled + "░" * (_bar_len - filled)
            name = Path(rel_path).name[:30]
            sys.stdout.write(f"\r  [{bar}] {pct:3d}% — {name:<30}")
            sys.stdout.flush()

        retriever = self._get_retriever()
        count = retriever.index_folder(wf, on_progress=_progress)
        sys.stdout.write("\n")
        sys.stdout.flush()
        out(f"  {GREEN}[ok]{RESET} Indexed {count} file(s).\n")

    def _index_status(self, _args: list[str]) -> None:
        retriever = self._get_retriever()
        stats = retriever.stats()

        out(f"\n{BOLD}Index Status{RESET}")
        if stats.file_count == 0:
            out(f"  {YELLOW}[!]{RESET} Index is empty.  Run: {CYAN}/index build{RESET}")
        else:
            out(f"  {GREEN}[ok]{RESET} Files indexed:  {stats.file_count}")
            out(f"       Chunks:         {stats.chunk_count}")
            out(f"       Symbols:        {stats.symbol_count}")
            out(f"       DB size:        {stats.db_size_kb:.1f} KB")
            out(f"       DB path:        {DIM}{stats.index_path}{RESET}")
        out("")

    def _index_explain(self, args: list[str]) -> None:
        """Show scored chunks for a query, or fall back to LLM synthesis if the index is empty."""
        if not args:
            out(f"  {YELLOW}Usage: /index explain <query>{RESET}\n")
            return
        query = " ".join(args)
        retriever = self._get_retriever()
        out(f"\n{BOLD}Index query:{RESET} {query}\n")

        # try direct chunk retrieval first — more transparent, shows scores
        sem = retriever._get_semantic()
        if sem is not None and getattr(sem, "_files", {}):
            from app.core.rag import chunk_text, rank_chunks_scored

            files = list(sem._files.items())
            all_chunks = []
            for name, content in files:
                if isinstance(name, str) and isinstance(content, str):
                    all_chunks.extend(chunk_text(name, content))

            if all_chunks:
                scored = rank_chunks_scored(all_chunks, query, top_k=8)
                if scored:
                    out(f"  {DIM}Top {len(scored)} result(s):{RESET}\n")
                    for score, chunk in scored:
                        preview = chunk.text[:200].replace("\n", " ").strip()
                        if len(chunk.text) > 200:
                            preview += "..."
                        out(f"  {GREEN}[score {score:.3f}]{RESET}  {CYAN}{chunk.file}{RESET}  "
                            f"lines {chunk.line_start}–{chunk.line_end}")
                        out(f"    {DIM}{preview}{RESET}\n")
                    out("")
                    return
                out(f"  {DIM}No matching chunks found.{RESET}\n")
                out("")
                return

        # index is empty — fall back to LLM-synthesised answer
        from app.core.research_runner import ResearchRunner
        runner = ResearchRunner(self._cfg)
        result = runner.query(query, working_folder=self._cfg.working_folder)
        if result.error:
            out_error(f"  {RED}{result.error}{RESET}\n")
            return
        out(result.answer)
        if result.files_used:
            out(f"\n  {DIM}Sources: {', '.join(result.files_used[:5])}{RESET}")
        out("")

    def _index_clear(self, _args: list[str]) -> None:
        retriever = self._get_retriever()
        retriever.clear()
        out(f"  {GREEN}[ok]{RESET} Index cleared.\n")

    def _index_help(self, _args: list[str]) -> None:
        out(f"\n{BOLD}/index{RESET} -- persistent repo index for semantic search")
        out(f"  {CYAN}/index build{RESET}              Index the current workspace")
        out(f"  {CYAN}/index build <path>{RESET}        Index a specific folder")
        out(f"  {CYAN}/index status{RESET}              Show index health")
        out(f"  {CYAN}/index explain <question>{RESET}  Search the index with a question")
        out(f"  {CYAN}/index clear{RESET}               Clear the in-memory index\n")

    def _get_retriever(self):
        if self._retriever is None:
            from app.core.hybrid_retriever import HybridRetriever
            self._retriever = HybridRetriever(self._cfg)
        return self._retriever


def cmd_rag(args: list[str], cfg) -> None:
    """/rag — tune RAG similarity thresholds."""
    from app.core.config import ConfigManager

    sub = args[0].lower() if args else "status"

    if sub == "status":
        bm25_w    = getattr(cfg, "rag_bm25_weight",     0.6)
        sem_w     = getattr(cfg, "rag_semantic_weight",  0.75)
        out(f"\n{BOLD}RAG Thresholds{RESET}")
        out(f"  BM25 weight    : {GREEN}{bm25_w:.2f}{RESET}")
        out(f"  Semantic weight: {GREEN}{sem_w:.2f}{RESET}\n")
        return

    if sub in ("bm25", "semantic") and len(args) >= 2:
        try:
            value = float(args[1])
        except ValueError:
            out_error(f"  {RED}Invalid value {args[1]!r} — must be a float between 0.0 and 1.0{RESET}\n")
            return
        if not 0.0 <= value <= 1.0:
            out_error(f"  {RED}Value must be between 0.0 and 1.0, got {value}{RESET}\n")
            return
        if sub == "bm25":
            cfg.rag_bm25_weight = value
            out(f"  {GREEN}[ok]{RESET} BM25 weight set to {value:.2f}\n")
        else:
            cfg.rag_semantic_weight = value
            out(f"  {GREEN}[ok]{RESET} Semantic weight set to {value:.2f}\n")
        ConfigManager().save(cfg)
        return

    out(f"\n{BOLD}/rag{RESET} — tune RAG similarity thresholds")
    out(f"  {CYAN}/rag bm25 <0.0-1.0>{RESET}      Set BM25 score threshold")
    out(f"  {CYAN}/rag semantic <0.0-1.0>{RESET}  Set semantic similarity threshold")
    out(f"  {CYAN}/rag status{RESET}               Show current weights\n")


def cmd_symbol(query: str, cfg) -> None:
    """/symbol <query> — search the symbol index for matching names."""
    wf = cfg.working_folder
    index_path = Path(wf) / ".project_index" if wf else None
    if not wf or (index_path is not None and not index_path.exists()):
        if not wf:
            out(f"  {YELLOW}[!]{RESET} No workspace set. Run {CYAN}/workspace <path>{RESET} then {CYAN}/index build{RESET}.\n")
            return

    query = query.strip()
    if not query:
        out(f"  {YELLOW}Usage: /symbol <name>{RESET}\n")
        return

    from app.core.hybrid_retriever import HybridRetriever
    retriever = HybridRetriever(cfg)

    # go straight to the internal symbol dict — faster than a full text search
    symbol_index: dict[str, str] = retriever._symbol_index  # type: ignore[attr-defined]

    if not symbol_index:
        out(f"  {YELLOW}[!]{RESET} Symbol index is empty. Run {CYAN}/index build{RESET} first.\n")
        return

    q_lower = query.lower()
    matches = [
        (name, path)
        for name, path in symbol_index.items()
        if q_lower in name.lower()
    ]

    if not matches:
        out(f"  {DIM}No symbols matching {query!r}.{RESET}\n")
        return

    out(f"\n{BOLD}Symbols matching {query!r}:{RESET}")
    for name, path in sorted(matches, key=lambda x: x[0].lower()):
        # infer language kind from file extension for quick visual scanning
        suffix = Path(path).suffix.lower()
        if suffix == ".py":
            kind = "py"
        elif suffix in {".ts", ".tsx"}:
            kind = "ts"
        elif suffix in {".js", ".jsx"}:
            kind = "js"
        else:
            kind = suffix.lstrip(".") or "?"
        out(f"  {CYAN}{kind:<6}{RESET}  {GREEN}{name:<40}{RESET}  {DIM}{path}{RESET}")
    out("")
