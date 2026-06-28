"""Review commands -- /review: structured code review using the active LLM."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display_compat import out, out_error
from cli.display import BOLD, DIM, GREEN, YELLOW, RED, CYAN, MAGENTA, RESET

_log = logging.getLogger("ilx_cli.review_cmds")

_RISK_COLOR = {
    "HIGH":    RED,
    "MED":     YELLOW,
    "LOW":     DIM,
    "INFO":    DIM,
    "MISSING": CYAN,
}


class ReviewCommands:
    """/review command handler."""

    def __init__(self, cfg: "AppConfig") -> None:
        self._cfg = cfg

    def cmd_review(self, args: list[str]) -> None:
        """/review [staged|pr|security|<file>]"""
        sub = args[0].lower() if args else ""

        if not sub or sub == "help":
            self._review_help()
        elif sub == "staged":
            self._review_diff(staged=True)
        elif sub == "security":
            self._review_security(args[1:])
        elif sub == "pr":
            self._review_pr(args[1:])
        else:
            # Treat as a file path
            self._review_files(args)

    # ── subcommands ───────────────────────────────────────────────────────

    def _review_diff(self, staged: bool = False) -> None:
        """Review uncommitted (or staged) changes."""
        from app.core import process_runner as _pr
        from app.core.review_runner import ReviewRunner

        diff_args = ["git", "diff"]
        if staged:
            diff_args.append("--staged")

        out(f"\n{BOLD}Running code review on {'staged ' if staged else 'uncommitted '}changes...{RESET}")
        r = _pr.run(diff_args, cwd=self._cfg.working_folder, timeout=10)
        if not r.ok or not r.stdout.strip():
            if staged:
                out(f"  {DIM}No staged changes found. Use /git diff --staged to check.{RESET}\n")
            else:
                out(f"  {DIM}No uncommitted changes found.{RESET}\n")
            return

        runner = ReviewRunner(self._cfg)
        result = runner.review_diff(r.stdout)
        self._print_result(result)

    def _review_files(self, paths: list[str]) -> None:
        """Review specific file(s)."""
        from app.core.review_runner import ReviewRunner

        # Resolve relative to working folder
        wf = Path(self._cfg.working_folder) if self._cfg.working_folder else Path.cwd()
        resolved = []
        for p in paths:
            full = Path(p) if Path(p).is_absolute() else wf / p
            resolved.append(str(full))

        out(f"\n{BOLD}Reviewing {len(resolved)} file(s)...{RESET}")
        runner = ReviewRunner(self._cfg)
        result = runner.review_files(resolved)
        self._print_result(result)

    def _review_security(self, paths: list[str]) -> None:
        """Security-focused review pass."""
        from app.core.review_runner import ReviewRunner
        from app.core import process_runner as _pr

        out(f"\n{BOLD}Security review...{RESET}")
        runner = ReviewRunner(self._cfg)

        if paths:
            wf = Path(self._cfg.working_folder) if self._cfg.working_folder else Path.cwd()
            resolved = [str(wf / p) if not Path(p).is_absolute() else p for p in paths]
            result = runner.review_security(paths=resolved)
        else:
            r = _pr.run(["git", "diff"], cwd=self._cfg.working_folder, timeout=10)
            diff = r.stdout if r.ok else ""
            result = runner.review_security(diff_text=diff)

        self._print_result(result, security_mode=True)

    def _review_pr(self, args: list[str]) -> None:
        """Review a GitHub PR (requires gh CLI)."""
        from app.core import process_runner as _pr
        from app.core.review_runner import ReviewRunner

        pr_num = args[0] if args else ""
        if not pr_num:
            out(f"  {YELLOW}Usage: /review pr <number>{RESET}\n")
            return

        out(f"\n{BOLD}Fetching PR #{pr_num} diff...{RESET}")
        r = _pr.run(["gh", "pr", "diff", pr_num], cwd=self._cfg.working_folder, timeout=30)
        if not r.ok:
            out_error(f"  {RED}gh pr diff failed: {r.stderr[:200]}{RESET}")
            out(f"  {DIM}Make sure gh CLI is installed and authenticated.{RESET}\n")
            return

        runner = ReviewRunner(self._cfg)
        result = runner.review_diff(r.stdout)
        out(f"  {DIM}PR #{pr_num} diff ({len(r.stdout)} chars){RESET}")
        self._print_result(result)

    def _review_help(self) -> None:
        out(f"\n{BOLD}/review{RESET} -- structured AI code review")
        out(f"  {CYAN}/review{RESET}               Review all uncommitted changes")
        out(f"  {CYAN}/review staged{RESET}         Review only staged changes")
        out(f"  {CYAN}/review security{RESET}       Security-focused pass (secrets, injection, auth)")
        out(f"  {CYAN}/review security <file>{RESET} Security review a specific file")
        out(f"  {CYAN}/review pr <N>{RESET}         Review a GitHub PR by number (needs gh CLI)")
        out(f"  {CYAN}/review <file>{RESET}         Review a specific file\n")

    # ── display ───────────────────────────────────────────────────────────

    def _print_result(self, result, security_mode: bool = False) -> None:
        if result.error:
            out_error(f"  {RED}Review error: {result.error}{RESET}\n")
            return

        if not result.findings:
            out(f"  {GREEN}[ok]{RESET} No significant issues found.\n")
            if result.summary:
                out(f"  {DIM}{result.summary}{RESET}\n")
            return

        # Group by category
        by_cat: dict[str, list] = {}
        for f in result.findings:
            by_cat.setdefault(f.category, []).append(f)

        out("")
        for cat, findings in sorted(by_cat.items()):
            out(f"  {BOLD}{cat.upper().replace('_',' ')}{RESET}")
            for f in findings:
                col = _RISK_COLOR.get(f.risk, DIM)
                loc = f":{f.line}" if f.line else ""
                out(f"    {col}{f.risk:<8}{RESET} {CYAN}{f.file}{loc}{RESET}  {f.message}")
            out("")

        # Summary line
        h = result.high_count()
        m = result.med_count()
        low_count = result.low_count()
        parts = []
        if h:
            parts.append(f"{RED}{h} HIGH{RESET}")
        if m:
            parts.append(f"{YELLOW}{m} MED{RESET}")
        if low_count:
            parts.append(f"{DIM}{low_count} LOW{RESET}")
        out(f"  Findings: {', '.join(parts) if parts else 'none'}")

        if result.summary:
            out(f"\n  {DIM}Summary: {result.summary}{RESET}")
        out("")
