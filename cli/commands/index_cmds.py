"""Index commands -- /index: build and query persistent repo index."""
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
    """/index command handler."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._retriever = None   # lazy init

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

    # ── subcommands ───────────────────────────────────────────────────────

    def _index_build(self, args: list[str]) -> None:
        """Index the current workspace for semantic + BM25 retrieval."""
        wf = args[0] if args else self._cfg.working_folder
        if not wf or not Path(wf).is_dir():
            out_error(f"  {RED}Invalid workspace: {wf!r}{RESET}")
            out(f"  {DIM}Use /workspace to set one, or pass a path.{RESET}\n")
            return

        out(f"\n{BOLD}Building index for:{RESET} {DIM}{wf}{RESET}")

        # Pre-count source files so the progress bar can show a percentage.
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
        """Show index health: file count, chunk count, DB size."""
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
        """Answer a question about what the index knows."""
        if not args:
            out(f"  {YELLOW}Usage: /index explain <question>{RESET}\n")
            return
        question = " ".join(args)
        from app.core.research_runner import ResearchRunner
        runner = ResearchRunner(self._cfg)
        out(f"\n{BOLD}Searching index:{RESET} {question}\n")
        result = runner.query(question, working_folder=self._cfg.working_folder)
        if result.error:
            out_error(f"  {RED}{result.error}{RESET}\n")
            return
        out(result.answer)
        if result.files_used:
            out(f"\n  {DIM}Sources: {', '.join(result.files_used[:5])}{RESET}")
        out("")

    def _index_clear(self, _args: list[str]) -> None:
        """Clear the in-memory index."""
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

    # ── helpers ───────────────────────────────────────────────────────────

    def _get_retriever(self):
        if self._retriever is None:
            from app.core.hybrid_retriever import HybridRetriever
            self._retriever = HybridRetriever(self._cfg)
        return self._retriever
