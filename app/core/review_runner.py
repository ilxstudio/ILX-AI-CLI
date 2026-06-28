"""Code review engine -- structured multi-pass review using the active LLM."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.review_runner")

# Risk levels
RISK_HIGH = "HIGH"
RISK_MED  = "MED"
RISK_LOW  = "LOW"
RISK_INFO = "INFO"


@dataclass
class ReviewFinding:
    risk:     str   # HIGH | MED | LOW | INFO | MISSING
    file:     str
    line:     int | None
    category: str   # bugs | security | maintainability | missing_tests | perf
    message:  str

    def format(self) -> str:
        loc = f":{self.line}" if self.line else ""
        return f"{self.risk:<8} {self.file}{loc}  -- {self.message}"


@dataclass
class ReviewResult:
    findings:    list[ReviewFinding] = field(default_factory=list)
    summary:     str = ""
    files_reviewed: int = 0
    error:       str = ""

    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == RISK_HIGH)

    def med_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == RISK_MED)

    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.risk in (RISK_LOW, RISK_INFO))


_SYSTEM_PROMPT = """\
You are a senior code reviewer. Analyze the provided code and diff for:
1. Bugs and logic errors (risk: HIGH or MED)
2. Security vulnerabilities: injection, auth bypass, secrets in code (risk: HIGH)
3. Maintainability issues: duplication, complexity, unclear naming (risk: LOW)
4. Missing test coverage for critical paths (risk: MED)
5. Performance issues: N+1 queries, unbounded loops, large allocations (risk: LOW)

For each issue output EXACTLY one line per finding in this format:
RISK:<LEVEL>  FILE:<path>  LINE:<N or none>  CAT:<category>  MSG:<short message>

RISK levels: HIGH | MED | LOW | INFO | MISSING
CAT values: bugs | security | maintainability | missing_tests | perf

After findings, output a one-paragraph SUMMARY: line.
Output NOTHING else — no markdown, no headers, no explanation.
If there are no findings, output: SUMMARY: No significant issues found.
"""

_FINDING_RE = re.compile(
    r"RISK:(?P<risk>\w+)\s+"
    r"FILE:(?P<file>\S+)\s+"
    r"LINE:(?P<line>\S+)\s+"
    r"CAT:(?P<cat>\w+)\s+"
    r"MSG:(?P<msg>.+)",
    re.IGNORECASE,
)


class ReviewRunner:
    """Runs a structured code review against a diff or set of files."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    # ── public API ────────────────────────────────────────────────────────

    def review_diff(self, diff_text: str, context_files: list[str] | None = None) -> ReviewResult:
        """Review a git diff string."""
        if not diff_text.strip():
            return ReviewResult(error="No diff content to review.")
        prompt = self._build_diff_prompt(diff_text, context_files or [])
        return self._run_review(prompt)

    def review_files(self, paths: list[str]) -> ReviewResult:
        """Review one or more specific files."""
        content_parts: list[str] = []
        files_read = 0
        total_chars = 0
        _MAX_TOTAL = 32_768  # hard cap across all files to stay within context
        for p in paths:
            path = Path(p)
            if not path.exists():
                _log.warning("review_files: %s not found", p)
                continue
            if total_chars >= _MAX_TOTAL:
                _log.debug("review_files: context cap reached, skipping %s", p)
                break
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                # per-file cap: 8 KB; never exceed total cap
                chunk = text[:min(8192, _MAX_TOTAL - total_chars)]
                content_parts.append(f"=== {p} ===\n{chunk}")
                total_chars += len(chunk)
                files_read += 1
            except OSError as exc:
                _log.warning("review_files: cannot read %s: %s", p, exc)

        if not content_parts:
            return ReviewResult(error="No readable files found.")

        prompt = (
            "Review the following file(s) for bugs, security issues, "
            "maintainability problems, missing tests, and performance:\n\n"
            + "\n\n".join(content_parts)
        )
        result = self._run_review(prompt)
        result.files_reviewed = files_read
        return result

    def review_security(self, diff_text: str = "", paths: list[str] | None = None) -> ReviewResult:
        """Security-focused pass: secrets, injection, auth bypass only."""
        if diff_text:
            content = f"Git diff:\n{diff_text[:16000]}"
        elif paths:
            parts = []
            for p in paths:
                try:
                    parts.append(f"=== {p} ===\n{Path(p).read_text(encoding='utf-8', errors='replace')[:4096]}")
                except OSError:
                    pass
            content = "\n\n".join(parts) if parts else ""
        else:
            return ReviewResult(error="Provide a diff or file paths.")

        prompt = (
            "Perform a SECURITY-ONLY review. Look exclusively for:\n"
            "- Hardcoded secrets, API keys, passwords\n"
            "- SQL/command/shell injection\n"
            "- Authentication or authorization bypass\n"
            "- Unsafe deserialization\n"
            "- Path traversal\n"
            "- XSS / template injection\n\n"
            + content
        )
        return self._run_review(prompt)

    # ── internal ──────────────────────────────────────────────────────────

    def _build_diff_prompt(self, diff: str, context_files: list[str]) -> str:
        parts = [f"Git diff to review:\n{diff[:16000]}"]
        for p in context_files[:3]:
            try:
                txt = Path(p).read_text(encoding="utf-8", errors="replace")[:4096]
                parts.append(f"\nContext file ({p}):\n{txt}")
            except OSError:
                pass
        return "\n".join(parts)

    def _run_review(self, user_prompt: str) -> ReviewResult:
        try:
            from codex.app.llm_client import get_llm_client
            client = get_llm_client(self._cfg)
            response = client.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system=_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=2048,
            )
        except Exception as exc:
            _log.error("review LLM call failed: %s", exc)
            return ReviewResult(error=f"LLM call failed: {exc}")

        return self._parse_response(response)

    def _parse_response(self, text: str) -> ReviewResult:
        findings: list[ReviewFinding] = []
        summary = ""

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.upper().startswith("SUMMARY:"):
                summary = line[len("SUMMARY:"):].strip()
                continue
            m = _FINDING_RE.match(line)
            if m:
                raw_line = m.group("line").strip()
                lineno: int | None = None
                if raw_line.isdigit():
                    lineno = int(raw_line)
                risk = m.group("risk").upper()
                if risk not in (RISK_HIGH, RISK_MED, RISK_LOW, RISK_INFO, "MISSING"):
                    risk = RISK_INFO
                findings.append(ReviewFinding(
                    risk=risk,
                    file=m.group("file"),
                    line=lineno,
                    category=m.group("cat").lower(),
                    message=m.group("msg").strip(),
                ))

        return ReviewResult(findings=findings, summary=summary)
