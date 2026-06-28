"""Analysis dev-tool commands — /complexity, /deadcode, /bandit, /precommit."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from app.core import process_runner

if TYPE_CHECKING:
    from app.core.config import AppConfig


class AnalysisCommands:
    """Handles static-analysis and security slash commands."""

    def __init__(self, cfg: "AppConfig") -> None:
        self.cfg = cfg

    def _wf(self) -> str | None:
        return self.cfg.working_folder or None

    def _require_workspace(self) -> str | None:
        from cli.display import YELLOW, RESET
        wf = self._wf()
        if not wf:
            print(f"{YELLOW}No workspace set. Use /workspace first.{RESET}")
        return wf

    # ── /complexity ───────────────────────────────────────────────────────────

    def cmd_complexity(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, RESET
        wf = self._require_workspace()
        if not wf:
            return
        threshold = 10
        if args:
            try:
                threshold = int(args[0])
            except ValueError:
                pass
        radon = shutil.which("radon")
        if not radon:
            print(f"  {YELLOW}radon not found. Install with: pip install radon{RESET}")
            return
        print(f"  {DIM}Analysing cyclomatic complexity (threshold={threshold})...{RESET}")
        r = process_runner.run(
            [radon, "cc", "-s", "-n", str(threshold), "."],
            cwd=wf, timeout=60,
        )
        if not r.ok and not r.stdout:
            if "Timed out" in r.stderr:
                print(f"  {RED}radon timed out.{RESET}")
            else:
                print(f"  {RED}{r.stderr[:200]}{RESET}")
            return
        out = (r.stdout + r.stderr).strip()
        if not out:
            print(f"  {GREEN}No functions exceed complexity {threshold}.{RESET}")
            return
        print(f"\n{BOLD}Complexity > {threshold} (sorted by score):{RESET}")
        for ln in out.splitlines()[:60]:
            if " - " in ln and any(c in ln for c in ("A", "B", "C", "D", "E", "F")):
                grade = ln.strip().split()[-1] if ln.strip() else "?"
                col = GREEN if grade in ("A", "B") else (YELLOW if grade == "C" else RED)
                print(f"  {col}{ln}{RESET}")
            else:
                print(f"  {DIM}{ln}{RESET}")
        print()

    # ── /deadcode ─────────────────────────────────────────────────────────────

    def cmd_deadcode(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, RESET
        wf = self._require_workspace()
        if not wf:
            return
        vulture = shutil.which("vulture")
        if not vulture:
            print(f"  {YELLOW}vulture not found. Install with: pip install vulture{RESET}")
            return
        min_confidence = args[0] if args else "60"
        print(f"  {DIM}Scanning for dead code (min confidence {min_confidence}%)...{RESET}")
        r = process_runner.run(
            [vulture, ".", f"--min-confidence={min_confidence}"],
            cwd=wf, timeout=60,
        )
        if not r.ok and not r.stdout:
            if "Timed out" in r.stderr:
                print(f"  {RED}vulture timed out.{RESET}")
            else:
                print(f"  {RED}{r.stderr[:200]}{RESET}")
            return
        out = (r.stdout + r.stderr).strip()
        if not out:
            print(f"  {GREEN}No dead code detected.{RESET}")
            return
        lines = out.splitlines()
        print(f"\n{BOLD}Dead code ({len(lines)} findings):{RESET}")
        for ln in lines[:50]:
            print(f"  {YELLOW}{ln}{RESET}")
        if len(lines) > 50:
            print(f"  {DIM}...and {len(lines)-50} more{RESET}")
        print()

    # ── /bandit ───────────────────────────────────────────────────────────────

    def cmd_bandit(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, RESET
        wf = self._require_workspace()
        if not wf:
            return
        bandit = shutil.which("bandit")
        if not bandit:
            print(f"  {YELLOW}bandit not found. Install with: pip install bandit{RESET}")
            return
        path = args[0] if args else "."
        print(f"  {DIM}Running bandit security scan on {path}...{RESET}")
        r = process_runner.run(
            [bandit, "-r", "-q", path],
            cwd=wf, timeout=90,
        )
        if not r.ok and not r.stdout:
            if "Timed out" in r.stderr:
                print(f"  {RED}bandit timed out.{RESET}")
            else:
                print(f"  {RED}{r.stderr[:200]}{RESET}")
            return
        out = (r.stdout + r.stderr).strip()
        lines = out.splitlines()
        if r.returncode == 0:
            print(f"  {GREEN}No security issues found.{RESET}")
            return
        print(f"\n{BOLD}Bandit security findings:{RESET}")
        for ln in lines[:80]:
            if "HIGH" in ln:
                print(f"  {RED}{ln}{RESET}")
            elif "MEDIUM" in ln:
                print(f"  {YELLOW}{ln}{RESET}")
            else:
                print(f"  {DIM}{ln}{RESET}")
        if len(lines) > 80:
            print(f"  {DIM}...and {len(lines)-80} more lines{RESET}")
        print()

    # ── /precommit ────────────────────────────────────────────────────────────

    def cmd_precommit(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, RESET
        wf = self._require_workspace()
        if not wf:
            return
        sub = args[0].lower() if args else "init"
        if sub == "init":
            config_path = Path(wf) / ".pre-commit-config.yaml"
            if config_path.exists():
                print(f"  {YELLOW}.pre-commit-config.yaml already exists.{RESET}")
            else:
                config_path.write_text(
                    "repos:\n"
                    "  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
                    "    rev: v0.4.0\n"
                    "    hooks:\n"
                    "      - id: ruff\n"
                    "        args: [--fix]\n"
                    "      - id: ruff-format\n"
                    "  - repo: https://github.com/pre-commit/mirrors-mypy\n"
                    "    rev: v1.9.0\n"
                    "    hooks:\n"
                    "      - id: mypy\n"
                    "  - repo: https://github.com/PyCQA/bandit\n"
                    "    rev: 1.7.8\n"
                    "    hooks:\n"
                    "      - id: bandit\n"
                    "        args: [-r, -q]\n",
                    encoding="utf-8",
                )
                print(f"  {GREEN}Created .pre-commit-config.yaml{RESET}")
            pc = shutil.which("pre-commit")
            if not pc:
                print(f"  {YELLOW}pre-commit not found. Install: pip install pre-commit{RESET}")
                return
            print(f"  {DIM}Running pre-commit install...{RESET}")
            r = process_runner.run([pc, "install"], cwd=wf, timeout=30)
            if not r.ok and not r.stdout:
                if "Timed out" in r.stderr:
                    print(f"  {RED}pre-commit install timed out.{RESET}")
                else:
                    print(f"  {RED}{r.stderr[:200]}{RESET}")
                return
            out = (r.stdout + r.stderr).strip()
            col = GREEN if r.ok else RED
            for ln in out.splitlines():
                print(f"  {col}{ln}{RESET}")
        elif sub == "run":
            pc = shutil.which("pre-commit")
            if not pc:
                print(f"  {YELLOW}pre-commit not installed.{RESET}")
                return
            print(f"  {DIM}Running pre-commit on all files...{RESET}")
            r = process_runner.run([pc, "run", "--all-files"], cwd=wf, timeout=120)
            if not r.ok and not r.stdout:
                if "Timed out" in r.stderr:
                    print(f"  {RED}pre-commit run timed out.{RESET}")
                else:
                    print(f"  {RED}{r.stderr[:200]}{RESET}")
                return
            out = (r.stdout + r.stderr).strip()
            for ln in out.splitlines()[-30:]:
                print(f"  {ln}")
        else:
            print(f"  {YELLOW}Usage: /precommit init | run{RESET}")
