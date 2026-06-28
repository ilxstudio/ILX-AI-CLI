"""Operation timing profiler — /timings command.

Records named timing samples and displays them as a summary table
with min / max / avg statistics. Useful for identifying slow operations.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

# Module-level ring buffer — holds the last 200 samples
_TIMINGS: list[tuple[str, float]] = []
_MAX_STORED = 200


def record_timing(label: str, elapsed_ms: float) -> None:
    """Record a timing sample (elapsed time in milliseconds)."""
    global _TIMINGS
    _TIMINGS.append((label, elapsed_ms))
    if len(_TIMINGS) > _MAX_STORED:
        _TIMINGS = _TIMINGS[-_MAX_STORED:]


def reset_timings() -> None:
    """Clear all recorded timings."""
    global _TIMINGS
    _TIMINGS = []


def cmd_timings(args: list[str], cfg: AppConfig) -> None:
    """/timings — display a table of the last 20 recorded operation timings."""
    from cli.display import BOLD, DIM, GREEN, RED, RESET, YELLOW

    if args and args[0].lower() == "reset":
        reset_timings()
        print(f"  {GREEN}Timing records cleared.{RESET}")
        return

    if not _TIMINGS:
        print(f"\n  {DIM}No timings recorded yet.{RESET}")
        print(f"  {DIM}Timings are collected automatically during operations.{RESET}\n")
        return

    display = _TIMINGS[-20:]  # most recent 20

    # Group by label for stats
    from collections import defaultdict
    groups: dict[str, list[float]] = defaultdict(list)
    for label, ms in _TIMINGS:
        groups[label].append(ms)

    # Header
    print(f"\n{BOLD}Operation Timings (last {len(display)} of {len(_TIMINGS)} recorded){RESET}\n")
    col_w = 32
    print(f"  {'Operation':<{col_w}}  {'ms':>8}  {'status'}")
    print(f"  {'-' * col_w}  {'--------':>8}  {'------'}")

    for label, ms in display:
        if ms < 200:
            col = GREEN
            status = "fast"
        elif ms < 1000:
            col = YELLOW
            status = "ok"
        else:
            col = RED
            status = "slow"
        label_s = label[:col_w]
        print(f"  {col}{label_s:<{col_w}}{RESET}  {ms:>8.1f}  {DIM}{status}{RESET}")

    # Summary stats per operation label
    print(f"\n{BOLD}Summary (all {len(_TIMINGS)} samples){RESET}\n")
    print(f"  {'Operation':<{col_w}}  {'count':>5}  {'min':>8}  {'avg':>8}  {'max':>8}")
    print(f"  {'-' * col_w}  {'-----':>5}  {'--------':>8}  {'--------':>8}  {'--------':>8}")

    for label in sorted(groups):
        samples = groups[label]
        mn  = min(samples)
        avg = sum(samples) / len(samples)
        mx  = max(samples)
        col = GREEN if mx < 200 else (YELLOW if mx < 1000 else RED)
        label_s = label[:col_w]
        print(
            f"  {col}{label_s:<{col_w}}{RESET}"
            f"  {len(samples):>5}"
            f"  {mn:>8.1f}"
            f"  {avg:>8.1f}"
            f"  {mx:>8.1f}"
        )

    print(f"\n  {DIM}Use /timings reset to clear all records.{RESET}\n")
