"""Fix commands -- /fix-tests: run tests, fix failures, repeat."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
from cli.display_compat import out, out_error

_log = logging.getLogger("ilx_cli.fix_cmds")


class FixCommands:
    """/fix-tests command handler."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def cmd_fix_tests(self, args: list[str]) -> None:
        """/fix-tests [--max N] [--only pattern] [--dry-run]"""
        max_attempts = self._cfg.autofix_max_iterations
        only: str | None = None
        dry_run = False

        i = 0
        while i < len(args):
            a = args[i]
            if a == "--max" and i + 1 < len(args):
                try:
                    max_attempts = int(args[i + 1])
                except ValueError:
                    pass
                i += 2
            elif a == "--only" and i + 1 < len(args):
                only = args[i + 1]
                i += 2
            elif a == "--dry-run":
                dry_run = True
                i += 1
            elif a in ("help", "--help"):
                self._fix_help()
                return
            else:
                i += 1

        if dry_run:
            self._dry_run_preview()
            return

        self._run_fix_loop(max_attempts, only)

    # ── subcommands ───────────────────────────────────────────────────────

    def _run_fix_loop(self, max_attempts: int, only: str | None) -> None:
        from app.core.test_fix_loop import TestFixLoop, detect_test_runner

        wf = self._cfg.working_folder
        runner_cmd = detect_test_runner(wf)
        filter_str = f"  filter: {only}" if only else ""

        out(f"\n{BOLD}Test-Fix Loop{RESET}  (max {max_attempts} attempts{filter_str})")
        out(f"  {DIM}Runner: {' '.join(runner_cmd)}{RESET}\n")

        loop = TestFixLoop(self._cfg, max_attempts=max_attempts)

        def on_progress(attempt: int, failures: int, output: str) -> None:
            status = f"{RED}{failures} failing{RESET}" if failures else f"{GREEN}all passing{RESET}"
            out(f"  Attempt {attempt}/{max_attempts} -- {status}")
            if failures:
                failed_lines = [ln for ln in output.splitlines() if ln.startswith("FAILED")][:3]
                for ln in failed_lines:
                    out(f"    {DIM}{ln[:80]}{RESET}")

        result = loop.run(
            working_folder=wf,
            only=only,
            on_progress=on_progress,
        )

        out("")
        self._print_result(result, max_attempts)

    def _dry_run_preview(self) -> None:
        """Show what test runner would be used without running."""
        from app.core.test_fix_loop import detect_test_runner
        wf = self._cfg.working_folder
        cmd = detect_test_runner(wf)
        out(f"\n{BOLD}/fix-tests dry run preview{RESET}")
        out(f"  Workspace:   {DIM}{wf}{RESET}")
        out(f"  Runner:      {CYAN}{' '.join(cmd)}{RESET}")
        out(f"  Max tries:   {self._cfg.autofix_max_iterations}")
        out(f"\n  {DIM}Run without --dry-run to start the fix loop.{RESET}\n")

    def _fix_help(self) -> None:
        out(f"\n{BOLD}/fix-tests{RESET} -- run tests, fix failures with LLM, repeat")
        out(f"  {CYAN}/fix-tests{RESET}               Run tests and fix until all pass")
        out(f"  {CYAN}/fix-tests --max 10{RESET}      Set max fix attempts (default: {self._cfg.autofix_max_iterations})")
        out(f"  {CYAN}/fix-tests --only <pat>{RESET}  Run only tests matching pattern")
        out(f"  {CYAN}/fix-tests --dry-run{RESET}     Show what would run without executing\n")

    # ── display ───────────────────────────────────────────────────────────

    def _print_result(self, result, max_attempts: int) -> None:
        if result.error:
            out_error(f"  {RED}{result.error}{RESET}\n")
            return

        if result.final_pass:
            out(f"  {GREEN}[ok] All tests passing!{RESET}")
        else:
            out(f"  {YELLOW}[!] Tests still failing after {len(result.attempts)} attempt(s).{RESET}")

        if result.attempts:
            out(f"\n  {BOLD}Attempts:{RESET}")
            for a in result.attempts:
                fixed = a.failures_before - a.failures_after
                col = GREEN if fixed > 0 else (YELLOW if fixed == 0 else RED)
                out(
                    f"    [{a.attempt}] {a.failures_before} -> {a.failures_after} failures  "
                    f"{col}({'+' if fixed >= 0 else ''}{fixed} fixed){RESET}  "
                    f"{DIM}{a.patches_applied} patch(es) applied{RESET}"
                )

        if result.total_fixed:
            out(f"\n  {GREEN}Total fixed: {result.total_fixed} test(s){RESET}")

        if result.final_failures:
            out(f"\n  {YELLOW}Still failing:{RESET}")
            for f in result.final_failures[:5]:
                out(f"    {DIM}{f.test_id}  {f.error[:60]}{RESET}")

        out("")
