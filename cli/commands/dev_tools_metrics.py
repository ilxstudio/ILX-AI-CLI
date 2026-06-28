"""Metrics command — /metrics: aggregate usage stats from audit log."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig


class MetricsCommands:
    """Provides the /metrics command for aggregate usage reporting."""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def cmd_metrics(self) -> None:
        """Parse audit log and display aggregate usage metrics."""
        from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET
        log_path = Path.home() / ".ilx_cli" / "logs" / "audit.log"
        if not log_path.exists():
            print(f"  {DIM}No audit log found. Metrics are collected as you use the CLI.{RESET}")
            return
        commands: dict[str, int] = {}
        llm_calls: list[dict] = []
        errors = 0
        try:
            for ln in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not ln.strip():
                    continue
                try:
                    ev = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                evt = ev.get("event", "")
                if evt == "command":
                    cmd_name = ev.get("command", "unknown")
                    commands[cmd_name] = commands.get(cmd_name, 0) + 1
                elif evt == "llm_call":
                    llm_calls.append(ev)
                if ev.get("level") == "ERROR" or ev.get("error"):
                    errors += 1
        except OSError as exc:
            print(f"  {RED}Could not read audit log: {exc}{RESET}")
            return

        print(f"\n{BOLD}Usage Metrics{RESET}")
        print(f"  {CYAN}Total commands  {RESET}  {sum(commands.values())}")
        if commands:
            top = sorted(commands.items(), key=lambda x: -x[1])[:5]
            print(f"  {CYAN}Top commands    {RESET}  {', '.join(f'{c}({n})' for c, n in top)}")
        print(f"  {CYAN}LLM calls       {RESET}  {len(llm_calls)}")
        if llm_calls:
            latencies = [c.get("latency_ms", 0) for c in llm_calls if c.get("latency_ms")]
            if latencies:
                avg_lat = sum(latencies) / len(latencies)
                p95_lat = (
                    sorted(latencies)[int(len(latencies) * 0.95)]
                    if len(latencies) > 1
                    else latencies[0]
                )
                print(f"  {CYAN}Avg latency     {RESET}  {avg_lat:.0f}ms")
                print(f"  {CYAN}p95 latency     {RESET}  {p95_lat:.0f}ms")
            total_tok = sum(c.get("total_tokens", 0) for c in llm_calls)
            print(f"  {CYAN}Total tokens    {RESET}  {total_tok:,}")
        col = RED if errors > 0 else GREEN
        print(f"  {col}Errors          {RESET}  {errors}")
        print()
