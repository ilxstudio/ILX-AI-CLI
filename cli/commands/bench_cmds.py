"""Benchmark commands — /benchmark runs coding tasks and scores the current model."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
from cli.display_compat import out, out_error

_log = logging.getLogger("ilx_cli.bench_cmds")


def _score_bar(score: int, width: int = 20) -> str:
    """Return a colored progress bar for a 0–100 score."""
    filled = int(score / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    if score >= 75:
        color = GREEN
    elif score >= 50:
        color = YELLOW
    else:
        color = RED
    return f"{color}{bar}{RESET}"


def _task_score_bar(score: int, max_score: int = 10, width: int = 10) -> str:
    filled = int(score / max_score * width)
    bar = "█" * filled + "░" * (width - filled)
    color = GREEN if score >= 7 else YELLOW if score >= 5 else RED
    return f"{color}{bar}{RESET}"


class BenchCommands:
    """/benchmark command handler."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def cmd_benchmark(self, args: list[str]) -> None:
        """/benchmark [--quick] [--json]"""
        json_mode = "--json" in args

        provider = self._cfg.provider
        model = self._cfg.ollama_model

        if provider not in ("ollama", "meta"):
            out(f"\n{YELLOW}Note:{RESET} Benchmark currently supports Ollama only.")
            out(f"  Current provider: {CYAN}{provider}{RESET}")
            out(f"  Switch with: {CYAN}/route local-only{RESET} then retry.\n")
            return

        out(f"\n{BOLD}ILX AI Benchmark{RESET}")
        out(f"  Model:    {CYAN}{model}{RESET}")
        out(f"  Provider: {CYAN}{provider}{RESET}")
        out(f"  Running {6} coding tasks...\n")

        def _progress(name, idx, total):
            pct = int((idx / total) * 100)
            bar = "▓" * (idx) + "░" * (total - idx)
            out(f"  [{bar}] {idx}/{total}  {DIM}{name}{RESET}", end="\r")

        from app.core.benchmark import BenchmarkRunner
        runner = BenchmarkRunner(self._cfg, on_progress=_progress)

        try:
            result = runner.run()
        except Exception as exc:
            out_error(f"\n  {RED}Benchmark failed: {exc}{RESET}\n")
            return

        out("")  # clear progress line
        out(f"\n{BOLD}Results — {model}{RESET}")
        out(f"  {'─' * 50}")

        for tr in result.task_results:
            task_def = next((t for t in runner.TASKS if t["name"] == tr.name), {})
            desc = task_def.get("desc", tr.name)
            bar = _task_score_bar(tr.score)
            status = f"{GREEN}✓{RESET}" if tr.passed else f"{RED}✗{RESET}"
            latency = f"{tr.latency_ms}ms"
            out(f"  {status} {desc:<35} {bar}  {tr.score}/10  {DIM}{latency}{RESET}")

        out(f"  {'─' * 50}")

        overall_bar = _score_bar(result.overall_score)
        out(f"\n  {BOLD}Overall score:{RESET}  {overall_bar}  {BOLD}{result.overall_score}/100{RESET}")
        out(f"  Duration:       {result.duration_s:.1f}s\n")

        if result.best_for:
            out(f"  {GREEN}Best for:{RESET}  {', '.join(result.best_for)}")
        if result.weak_for:
            out(f"  {YELLOW}Weak for:{RESET}  {', '.join(result.weak_for)}")
        out(f"\n  {DIM}{result.suggestion}{RESET}\n")

        if json_mode:
            import json
            data = {
                "model": result.model,
                "provider": result.provider,
                "overall_score": result.overall_score,
                "tasks": [
                    {"name": t.name, "score": t.score, "passed": t.passed,
                     "latency_ms": t.latency_ms}
                    for t in result.task_results
                ],
                "best_for": result.best_for,
                "weak_for": result.weak_for,
                "suggestion": result.suggestion,
            }
            out(json.dumps(data, indent=2))
