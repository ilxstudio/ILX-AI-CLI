"""Research runner -- multi-pass codebase research using hybrid retrieval + LLM."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.research_runner")


@dataclass
class ResearchResult:
    query:      str
    answer:     str
    files_used: list[str] = field(default_factory=list)
    chunks_used: int = 0
    follow_ups: list[str] = field(default_factory=list)
    error:      str = ""


_RESEARCH_SYSTEM = """\
You are an expert code analyst. You have been given relevant code chunks from a
codebase retrieved by hybrid search. Answer the user's research question with:

1. A clear, specific answer based ONLY on the provided code chunks.
2. File references for every claim (format: `file.py:LINE`).
3. A "Data flow" or "Architecture" note when relevant.
4. Up to 3 follow-up questions the user should ask next.

Output format (Markdown):
## Answer
<your answer with inline `file.py:LINE` references>

## Files Referenced
- file1.py
- file2.py

## Follow-up Questions
- Question 1?
- Question 2?
- Question 3?

If the chunks do not contain enough information, say so clearly — do not hallucinate.
"""


class ResearchRunner:
    """Answers open-ended codebase questions using hybrid retrieval + LLM synthesis."""

    def __init__(self, cfg: "AppConfig") -> None:
        self._cfg = cfg
        self._retriever = None   # lazy init

    def query(self, question: str, working_folder: str = "") -> ResearchResult:
        """Run a research query against the indexed codebase."""
        retriever = self._get_retriever()

        # If a working folder is provided and the index is empty, auto-index it
        if working_folder:
            stats = retriever.stats()
            if stats.file_count == 0:
                _log.info("Auto-indexing %s for research query", working_folder)
                retriever.index_folder(working_folder)

        chunks = retriever.query(question, top_k=10)
        if not chunks:
            return ResearchResult(
                query=question,
                answer="",
                error="No indexed content found. Run /index build first.",
            )

        context = "\n\n".join(
            f"[{c.source}]\n{c.content[:1000]}"
            for c in chunks
            if c.content.strip()
        )
        if not context:
            return ResearchResult(
                query=question,
                answer="",
                error="No indexed content found. Run /index build first.",
            )
        user_msg = f"Research question: {question}\n\nCode context:\n{context}"

        try:
            from codex.app.llm_client import get_llm_client
            client = get_llm_client(self._cfg)
            answer = client.chat(
                messages=[{"role": "user", "content": user_msg}],
                system=_RESEARCH_SYSTEM,
                temperature=0.2,
                max_tokens=2048,
            )
        except Exception as exc:
            _log.error("research LLM call failed: %s", exc)
            return ResearchResult(
                query=question,
                answer="",
                error=f"LLM call failed: {exc}",
            )

        files_used = list(dict.fromkeys(c.source for c in chunks))
        follow_ups = self._extract_follow_ups(answer)

        return ResearchResult(
            query=question,
            answer=answer,
            files_used=files_used,
            chunks_used=len(chunks),
            follow_ups=follow_ups,
        )

    def index_folder(self, folder: str, on_progress: "Callable | None" = None) -> int:
        """Index a folder for future queries."""
        return self._get_retriever().index_folder(folder, on_progress=on_progress)

    def _get_retriever(self):
        if self._retriever is None:
            from app.core.hybrid_retriever import HybridRetriever
            self._retriever = HybridRetriever(self._cfg)
        return self._retriever

    def _extract_follow_ups(self, answer: str) -> list[str]:
        """Extract follow-up questions from the formatted answer."""
        follow_ups: list[str] = []
        in_section = False
        for line in answer.splitlines():
            stripped = line.strip()
            if "Follow-up" in stripped or "follow-up" in stripped:
                in_section = True
                continue
            if in_section and stripped.startswith("#"):
                break
            if in_section and stripped.startswith("-") and stripped.endswith("?"):
                follow_ups.append(stripped[1:].strip())
        return follow_ups[:3]
