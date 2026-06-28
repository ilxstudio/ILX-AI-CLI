from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass
class AttemptRecord:
    attempt:       int
    files_written: list[str]
    command:       str | None
    exit_code:     int | None
    error_snippet: str | None
    outcome:       Literal["success", "failed", "parse_error", "validation_error", "timeout", "empty_response", "syntax_error"]


class AgentMemory:
    def __init__(self, max_history: int = 5) -> None:
        self._records: list[AttemptRecord] = []
        self.max_history = max_history

    def add(self, record: AttemptRecord) -> None:
        self._records.append(record)

    def last(self) -> AttemptRecord | None:
        return self._records[-1] if self._records else None

    def count(self) -> int:
        return len(self._records)

    def summary_for_prompt(self) -> str:
        if not self._records:
            return "No previous attempts."
        recent = self._records[-self.max_history:]
        lines: list[str] = []
        for rec in recent:
            files_str = "[" + ", ".join(rec.files_written) + "]" if rec.files_written else "[]"
            cmd_str   = f"ran '{rec.command}'" if rec.command else "no cmd"
            exit_str  = f"exit {rec.exit_code}" if rec.exit_code is not None else ""
            err_str   = ""
            if rec.error_snippet:
                snippet = rec.error_snippet[:50].replace("\n", " ")
                err_str = f" — {snippet}"
            parts = [f"Attempt {rec.attempt}:", f"wrote {files_str},", cmd_str]
            if exit_str:
                parts.append(exit_str)
            parts.append(f"({rec.outcome}){err_str}")
            lines.append(" ".join(parts))
        return "\n".join(lines)
