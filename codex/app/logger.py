from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class LogEntry:
    timestamp: str
    attempt:   int
    event:     str
    payload:   dict[str, Any]


class AgentLogger:
    def __init__(self, log_dir: Path, run_id: str):
        self.log_dir  = log_dir
        self.run_id   = run_id
        self.log_file = log_dir / f"{run_id}.jsonl"
        self._attempt = 0

    def set_attempt(self, n: int) -> None:
        self._attempt = n

    def log(self, event: str, payload: dict[str, Any] | None = None) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            attempt=self._attempt,
            event=event,
            payload=payload or {},
        )
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")


def generate_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
