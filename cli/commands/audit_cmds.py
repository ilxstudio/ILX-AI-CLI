"""Audit commands — /audit for code quality, security, and competitive analysis."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from app.core import process_runner
from cli.display_compat import out, out_error, out_result, out_status

if TYPE_CHECKING:
    from app.core.config import AppConfig

PYTHON_EXE = sys.executable

# All file-analysis helpers live in audit_helpers to keep this file under 700 lines.
from cli.commands.audit_helpers import (
    count_loc,
    count_markers,
    files_over_limit,
    grep_eval_exec,
    grep_secrets,
    grep_shell_true,
    inventory_ilx_features,
)
from cli.commands.audit_log_cmds import (
    audit_diff,
    audit_explain,
    audit_export,
    audit_replay,
)


class AuditCommands:
    """Handles /audit slash commands."""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def _wf(self) -> str | None:
        return self.cfg.working_folder or None

    def _require_workspace(self) -> str | None:
        from cli.display import RESET, YELLOW
        wf = self._wf()
        if not wf:
            out_error(f"{YELLOW}No workspace set. Use /workspace first.{RESET}")
        return wf

    # ── dispatch ─────────────────────────────────────────────────────────────

    def cmd_audit(self, args: list[str]) -> None:
        """Dispatch /audit subcommands."""
        sub = args[0].lower() if args else "full"
        rest = args[1:]

        dispatch = {
            "full":     self._audit_full,
            "security": self._audit_security,
            "quality":  self._audit_quality,
            "deps":     self._audit_deps,
            "compare":  self._audit_compare,
            "replay":   self._audit_replay,
            "explain":  self._audit_explain,
            "export":   self._audit_export,
            "diff":     self._audit_diff,
            "help":     self._audit_help,
        }
        fn = dispatch.get(sub, self._audit_help)
        fn(rest)

    # ── /audit full ──────────────────────────────────────────────────────────

    def _audit_full(self, args: list[str]) -> None:
        from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
        wf = self._require_workspace()
        if not wf:
            return

        out(f"\n{BOLD}{CYAN}ILX AI CLI — Full Workspace Audit{RESET}")
        out_status(f"  {DIM}Workspace: {wf}{RESET}\n")

        scores: dict[str, int | None] = {}

        out(f"{BOLD}[1/3] Security Scan{RESET}")
        scores["security"] = self._run_security(wf)

        out(f"\n{BOLD}[2/3] Code Quality{RESET}")
        scores["quality"] = self._run_quality(wf)

        out(f"\n{BOLD}[3/3] Dependency Health{RESET}")
        scores["deps"] = self._run_deps(wf)

        out(f"\n{BOLD}{'─'*50}{RESET}")
        out(f"{BOLD}Audit Summary:{RESET}")
        for name, score in scores.items():
            if score is None:
                label, col = "N/A  (no data)", DIM
            elif score >= 80:
                label, col = f"{score}/100  PASS", GREEN
            elif score >= 55:
                label, col = f"{score}/100  WARN", YELLOW
            else:
                label, col = f"{score}/100  FAIL", RED
            out_result(f"  {name.ljust(12)} {col}{label}{RESET}")
        out_result("")

    # ── /audit security ───────────────────────────────────────────────────────

    def _audit_security(self, args: list[str]) -> None:
        from cli.display import BOLD, CYAN, DIM, RESET
        wf = self._require_workspace()
        if not wf:
            return
        out(f"\n{BOLD}{CYAN}Security Audit{RESET}  {DIM}({wf}){RESET}\n")
        self._run_security(wf)

    def _run_security(self, wf: str) -> int:
        """Run security checks; return score 0-100."""
        from cli.display import BOLD, DIM, GREEN, RED, RESET, YELLOW

        root = Path(wf)
        deductions = 0

        # 1. Hardcoded secrets
        secrets = grep_secrets(root)
        if secrets:
            print(f"  {RED}[FAIL]{RESET} Potential hardcoded secrets ({len(secrets)} hits):")
            for hit in secrets[:10]:
                print(f"    {DIM}{hit}{RESET}")
            if len(secrets) > 10:
                print(f"    {DIM}...and {len(secrets)-10} more{RESET}")
            deductions += min(40, len(secrets) * 8)
        else:
            print(f"  {GREEN}[PASS]{RESET} No hardcoded secrets detected")

        # 2. shell=True
        shell_hits = grep_shell_true(root)
        if shell_hits:
            print(f"  {YELLOW}[WARN]{RESET} subprocess shell=True usage ({len(shell_hits)} hits):")
            for hit in shell_hits[:5]:
                print(f"    {DIM}{hit}{RESET}")
            deductions += min(20, len(shell_hits) * 5)
        else:
            print(f"  {GREEN}[PASS]{RESET} No shell=True subprocess calls")

        # 3. eval/exec on dynamic strings
        eval_hits = grep_eval_exec(root)
        if eval_hits:
            print(f"  {YELLOW}[WARN]{RESET} eval()/exec() on non-literal args ({len(eval_hits)} hits):")
            for hit in eval_hits[:5]:
                print(f"    {DIM}{hit}{RESET}")
            deductions += min(20, len(eval_hits) * 5)
        else:
            print(f"  {GREEN}[PASS]{RESET} No dynamic eval/exec detected")

        # 4. bandit (optional)
        bandit = shutil.which("bandit")
        if bandit:
            print(f"  {DIM}Running bandit...{RESET}", end="", flush=True)
            r = process_runner.run(
                [bandit, "-r", "-q", "--severity-level", "medium", "."],
                cwd=wf, timeout=90,
            )
            if not r.ok and r.returncode == -1:
                print(f"\r  {YELLOW}[SKIP]{RESET} bandit timed out" if "Timed out" in r.stderr
                      else f"\r  {YELLOW}[SKIP]{RESET} bandit error: {r.stderr[:100]}")
            else:
                proc_out = (r.stdout + r.stderr).strip()
                if r.ok:
                    print(f"\r  {GREEN}[PASS]{RESET} bandit: no medium/high issues")
                else:
                    high = proc_out.count("Severity: High")
                    med  = proc_out.count("Severity: Medium")
                    print(f"\r  {YELLOW}[WARN]{RESET} bandit: {high} high, {med} medium issues")
                    deductions += min(25, high * 10 + med * 3)
                    for ln in proc_out.splitlines()[:15]:
                        if any(k in ln for k in ("Severity", "Issue", "Location")):
                            print(f"    {DIM}{ln}{RESET}")
        else:
            print(f"  {DIM}[SKIP]{RESET} bandit not installed (pip install bandit)")

        # 5. pip-audit (optional)
        pip_audit = shutil.which("pip-audit")
        if pip_audit:
            print(f"  {DIM}Running pip-audit...{RESET}", end="", flush=True)
            r = process_runner.run([pip_audit, "-q"], cwd=wf, timeout=60)
            if not r.ok and r.returncode == -1:
                print(f"\r  {YELLOW}[SKIP]{RESET} pip-audit timed out" if "Timed out" in r.stderr
                      else f"\r  {YELLOW}[SKIP]{RESET} pip-audit error: {r.stderr[:100]}")
            else:
                proc_out = (r.stdout + r.stderr).strip()
                if r.ok:
                    print(f"\r  {GREEN}[PASS]{RESET} pip-audit: no vulnerabilities")
                else:
                    vuln_lines = [l for l in proc_out.splitlines() if "CVE" in l or "vuln" in l.lower()]
                    print(f"\r  {RED}[FAIL]{RESET} pip-audit: {len(vuln_lines)} vulnerability finding(s)")
                    for ln in vuln_lines[:8]:
                        print(f"    {DIM}{ln}{RESET}")
                    deductions += min(30, len(vuln_lines) * 5)
        else:
            print(f"  {DIM}[SKIP]{RESET} pip-audit not installed (pip install pip-audit)")

        score = max(0, 100 - deductions)
        col = GREEN if score >= 80 else (YELLOW if score >= 55 else RED)
        out_result(f"\n  {BOLD}Security score: {col}{score}/100{RESET}\n")
        return score

    # ── /audit quality ────────────────────────────────────────────────────────

    def _audit_quality(self, args: list[str]) -> None:
        from cli.display import BOLD, CYAN, DIM, RESET
        wf = self._require_workspace()
        if not wf:
            return
        out(f"\n{BOLD}{CYAN}Code Quality Audit{RESET}  {DIM}({wf}){RESET}\n")
        self._run_quality(wf)

    def _run_quality(self, wf: str) -> int:
        """Run code-quality checks; return score 0-100."""
        from cli.display import BOLD, DIM, GREEN, RED, RESET, YELLOW

        root = Path(wf)
        deductions = 0

        # 1. LOC
        total, code = count_loc(root)
        print(f"  {DIM}Lines of code:{RESET} {code:,} code  /  {total:,} total")

        # 2. Files over 700 lines
        over_limit = files_over_limit(root)
        if over_limit:
            print(f"  {YELLOW}[WARN]{RESET} {len(over_limit)} file(s) exceed 700 lines (project rule):")
            for p, n in over_limit[:5]:
                try:
                    rel = str(p.relative_to(root))
                except ValueError:
                    rel = str(p)
                print(f"    {DIM}{rel}  ({n} lines){RESET}")
            deductions += min(20, len(over_limit) * 5)
        else:
            print(f"  {GREEN}[PASS]{RESET} All files within 700-line limit")

        # 3. TODO/FIXME/HACK/XXX markers
        markers = count_markers(root)
        total_markers = sum(markers.values())
        if total_markers > 20:
            print(f"  {YELLOW}[WARN]{RESET} {total_markers} unresolved markers: {markers}")
            deductions += min(10, total_markers // 5)
        elif total_markers > 0:
            print(f"  {DIM}[INFO]{RESET} {total_markers} markers: {markers}")
        else:
            print(f"  {GREEN}[PASS]{RESET} No TODO/FIXME/HACK/XXX markers")

        # 4. radon complexity (optional)
        radon = shutil.which("radon")
        if radon:
            print(f"  {DIM}Running radon (cyclomatic complexity)...{RESET}", end="", flush=True)
            r = process_runner.run([radon, "cc", "-a", "-s", "."], cwd=wf, timeout=60)
            if not r.ok and r.returncode == -1:
                print(f"\r  {YELLOW}[SKIP]{RESET} radon timed out" if "Timed out" in r.stderr
                      else f"\r  {YELLOW}[SKIP]{RESET} radon error: {r.stderr[:100]}")
            else:
                proc_out = (r.stdout + r.stderr).strip()
                lines_out = proc_out.splitlines()
                avg_line = next((l for l in lines_out if "Average complexity" in l), "")
                print(f"\r  {DIM}radon:{RESET} {avg_line.strip() or 'no average reported'}")
                high_complex = sum(
                    1 for l in lines_out if " D " in l or " E " in l or " F " in l
                )
                if high_complex > 0:
                    print(f"  {YELLOW}[WARN]{RESET} {high_complex} function(s) with complexity D/E/F")
                    deductions += min(15, high_complex * 3)
                    complex_lines = [l for l in lines_out if any(g in l for g in (" D ", " E ", " F "))]
                    for ln in complex_lines[:5]:
                        print(f"    {DIM}{ln.strip()}{RESET}")
                else:
                    print(f"  {GREEN}[PASS]{RESET} No high-complexity functions (D/E/F)")
        else:
            print(f"  {DIM}[SKIP]{RESET} radon not installed (pip install radon)")

        # 5. ruff (optional)
        ruff = shutil.which("ruff")
        if ruff:
            print(f"  {DIM}Running ruff...{RESET}", end="", flush=True)
            r = process_runner.run(
                [ruff, "check", "--output-format=concise", "."],
                cwd=wf, timeout=60,
            )
            if not r.ok and r.returncode == -1:
                print(f"\r  {YELLOW}[SKIP]{RESET} ruff timed out" if "Timed out" in r.stderr
                      else f"\r  {YELLOW}[SKIP]{RESET} ruff error: {r.stderr[:100]}")
            else:
                proc_out = (r.stdout + r.stderr).strip()
                violation_lines = [l for l in proc_out.splitlines() if l.strip() and "Found" not in l]
                count = len(violation_lines)
                if count == 0:
                    print(f"\r  {GREEN}[PASS]{RESET} ruff: no violations")
                else:
                    print(f"\r  {YELLOW}[WARN]{RESET} ruff: {count} violation(s)")
                    for ln in violation_lines[:8]:
                        print(f"    {DIM}{ln}{RESET}")
                    if count > 8:
                        print(f"    {DIM}...and {count-8} more{RESET}")
                    deductions += min(15, count // 2)
        else:
            print(f"  {DIM}[SKIP]{RESET} ruff not installed (pip install ruff)")

        score = max(0, 100 - deductions)
        col = GREEN if score >= 80 else (YELLOW if score >= 55 else RED)
        out_result(f"\n  {BOLD}Quality score: {col}{score}/100{RESET}\n")
        return score

    # ── /audit deps ───────────────────────────────────────────────────────────

    def _audit_deps(self, args: list[str]) -> None:
        from cli.display import BOLD, CYAN, DIM, RESET
        wf = self._require_workspace()
        if not wf:
            return
        out(f"\n{BOLD}{CYAN}Dependency Health Audit{RESET}  {DIM}({wf}){RESET}\n")
        self._run_deps(wf)

    def _run_deps(self, wf: str) -> int:
        """Run dependency health checks; return score 0-100."""
        import re as _re

        from cli.display import BOLD, DIM, GREEN, RED, RESET, YELLOW

        root = Path(wf)
        deductions = 0

        req_file: Path | None = None
        for candidate in ("requirements.txt", "requirements-dev.txt", "pyproject.toml"):
            cand = root / candidate
            if cand.exists():
                req_file = cand
                break

        if req_file is None:
            print(f"  {DIM}[INFO]{RESET} No requirements.txt or pyproject.toml found")
            print(f"  {DIM}Dependency audit skipped — no requirement file detected.{RESET}")
            return 100

        print(f"  {DIM}Using:{RESET} {req_file.name}")

        # Offline known-bad version checks
        KNOWN_BAD = [
            ("requests",   "<", (2, 28, 0), "CVE-2023-32681"),
            ("urllib3",    "<", (1, 26, 5), "CVE-2021-33503"),
            ("pillow",     "<", (9, 3,  0), "CVE-2022-45199"),
            ("setuptools", "<", (65, 5, 1), "CVE-2022-40897"),
        ]
        req_text = req_file.read_text(encoding="utf-8", errors="replace")
        for pkg, _op, min_ver, cve in KNOWN_BAD:
            m = _re.search(rf"{_re.escape(pkg)}\s*==?\s*([\d.]+)", req_text, _re.IGNORECASE)
            if m:
                try:
                    raw = tuple(int(x) for x in m.group(1).split(".")[:3])
                    parts = raw + (0,) * (3 - len(raw))
                    if parts < min_ver:
                        ver_str = ".".join(str(x) for x in min_ver)
                        print(
                            f"  {RED}[VULN]{RESET} {pkg}=={m.group(1)} below "
                            f"{ver_str}+ ({cve})"
                        )
                        deductions += 20
                except ValueError:
                    pass

        # pip-audit (optional)
        pip_audit = shutil.which("pip-audit")
        if pip_audit:
            print(f"  {DIM}Running pip-audit on {req_file.name}...{RESET}", end="", flush=True)
            cmd = [pip_audit, "-q"]
            if req_file.name == "requirements.txt":
                cmd += ["-r", str(req_file)]
            r = process_runner.run(cmd, cwd=wf, timeout=90)
            if not r.ok and r.returncode == -1:
                print(f"\r  {YELLOW}[SKIP]{RESET} pip-audit timed out" if "Timed out" in r.stderr
                      else f"\r  {YELLOW}[SKIP]{RESET} pip-audit error: {r.stderr[:100]}")
            else:
                proc_out = (r.stdout + r.stderr).strip()
                if r.ok:
                    print(f"\r  {GREEN}[PASS]{RESET} pip-audit: no known vulnerabilities")
                else:
                    vuln_lines = [l for l in proc_out.splitlines() if l.strip()]
                    print(f"\r  {RED}[FAIL]{RESET} pip-audit: {len(vuln_lines)} finding(s)")
                    for ln in vuln_lines[:10]:
                        print(f"    {DIM}{ln}{RESET}")
                    deductions += min(40, len(vuln_lines) * 5)
        else:
            print(f"  {DIM}[SKIP]{RESET} pip-audit not installed (pip install pip-audit)")

        # Outdated packages
        print(f"  {DIM}Checking for outdated packages...{RESET}", end="", flush=True)
        r = process_runner.run(
            [PYTHON_EXE, "-m", "pip", "list", "--outdated", "--format=columns"],
            timeout=60,
        )
        if not r.ok and r.returncode == -1:
            print(f"\r  {YELLOW}[SKIP]{RESET} pip list --outdated timed out" if "Timed out" in r.stderr
                  else f"\r  {YELLOW}[SKIP]{RESET} pip list error: {r.stderr[:100]}")
        else:
            proc_out = (r.stdout + r.stderr).strip()
            pkg_lines = [
                l for l in proc_out.splitlines()
                if l.strip() and not l.startswith("Package") and not l.startswith("---")
            ]
            if pkg_lines:
                print(f"\r  {YELLOW}[INFO]{RESET} {len(pkg_lines)} outdated package(s):")
                for ln in pkg_lines[:8]:
                    print(f"    {DIM}{ln}{RESET}")
                if len(pkg_lines) > 8:
                    print(f"    {DIM}...and {len(pkg_lines)-8} more{RESET}")
                deductions += min(10, len(pkg_lines) // 3)
            else:
                print(f"\r  {GREEN}[PASS]{RESET} All packages up to date")

        score = max(0, 100 - deductions)
        col = GREEN if score >= 80 else (YELLOW if score >= 55 else RED)
        out_result(f"\n  {BOLD}Dependency score: {col}{score}/100{RESET}\n")
        return score

    # ── /audit compare ────────────────────────────────────────────────────────

    def _audit_compare(self, args: list[str]) -> None:
        from app.core.web_fetch import fetch_url
        from cli.display import BOLD, DIM, GREEN, RED, RESET, YELLOW

        target_tool = args[0] if args else None

        out(f"\n{BOLD}ILX AI CLI — Competitive Analysis{RESET}")
        if target_tool:
            out_status(f"  {DIM}Comparing against: {target_tool}{RESET}\n")
        else:
            out_status(f"  {DIM}Researching industry tools...{RESET}\n")

        research_urls: dict[str, str] = {
            "Claude Code":        "https://docs.anthropic.com/en/docs/claude-code/overview",
            "Aider":              "https://aider.chat/docs/features.html",
            "GitHub Copilot CLI": "https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-in-the-command-line",
        }

        if target_tool:
            filtered = {k: v for k, v in research_urls.items()
                        if target_tool.lower() in k.lower()}
            if filtered:
                research_urls = filtered
            else:
                out(f"  {YELLOW}Tool '{target_tool}' not in default list; fetching all.{RESET}")

        fetched_data: dict[str, str] = {}
        for tool_name, url in research_urls.items():
            out_status(f"  {DIM}Fetching {tool_name}...{RESET}")
            result = fetch_url(url, timeout=20)
            if result["ok"]:
                fetched_data[tool_name] = result["text"][:3000]
                out_status(f"  {GREEN}[OK]{RESET} {tool_name:<30} {DIM}{url[:60]}{RESET}")
            else:
                fetched_data[tool_name] = f"[Could not fetch: {result['error']}]"
                out_status(f"  {YELLOW}[~]{RESET}  {tool_name:<30} {DIM}using cached knowledge{RESET}")

        out_status(f"\n  {DIM}Inventorying ILX AI CLI features...{RESET}")
        ilx_features = inventory_ilx_features()

        try:
            from codex.app.llm_client_ext import get_llm_client
        except ImportError:
            out_error(f"  {RED}LLM client not available.{RESET}")
            return

        client = get_llm_client(self.cfg)

        competitor_context = "\n\n".join(
            f"## {name}\nSource: {research_urls.get(name, 'N/A')}\n\n{text}"
            for name, text in fetched_data.items()
        )

        prompt = self._build_compare_prompt(ilx_features, competitor_context)

        out_status(f"  {DIM}Analyzing with {client.model}...{RESET}")
        from app.core.spinner import Spinner
        spinner = Spinner("Generating competitive analysis")
        spinner.start()

        try:
            report = client.chat([{"role": "user", "content": prompt}])
            spinner.stop(clear=True)
        except Exception as exc:
            spinner.stop(clear=True)
            out_error(f"  {RED}Analysis failed: {exc}{RESET}")
            return

        out_result("\n" + report)
        self._offer_save(report)

    @staticmethod
    def _build_compare_prompt(ilx_features: str, competitor_context: str) -> str:
        return (
            "You are an expert AI developer tools analyst. "
            "Compare ILX AI CLI against industry-standard tools.\n\n"
            f"{ilx_features}\n\n"
            "## Competitor Information (from their documentation)\n"
            f"{competitor_context}\n\n"
            "Produce a competitive analysis with:\n"
            "1. A scoring table (0-100%) across these 12 categories for ILX AI CLI "
            "AND each competitor:\n"
            "   - Core LLM Integration\n"
            "   - Code Generation & Agent\n"
            "   - Developer Workflow\n"
            "   - Security & Safety\n"
            "   - Context & RAG\n"
            "   - Process Management\n"
            "   - Project Scaffolding\n"
            "   - Session & UX\n"
            "   - Observability\n"
            "   - Self-Improvement / Extensibility\n"
            "   - Function Calling / Tool Use\n"
            "   - Error Handling & Resilience\n"
            "2. Overall weighted score for each tool\n"
            "3. Top 3 things ILX AI CLI does BETTER than competitors\n"
            "4. Top 3 things ILX AI CLI still lacks vs competitors\n"
            "5. Recommended next improvements (prioritized)\n\n"
            "Format as clean markdown with tables. Be objective and critical."
        )

    def _offer_save(self, report: str) -> None:
        from cli.display import GREEN, RESET
        wf = self._wf()
        save_dir = Path(wf) if wf else Path.home() / "Documents"
        save_path = save_dir / "ilx_audit_compare.md"
        try:
            ans = input(f"\n  Save report to {save_path.name}? [y/N] ").strip().lower()
            if ans in ("y", "yes"):
                save_path.write_text(report, encoding="utf-8")
                out_result(f"  {GREEN}Saved to: {save_path}{RESET}")
        except (EOFError, KeyboardInterrupt):
            pass

    # ── /audit replay ─────────────────────────────────────────────────────────

    def _audit_replay(self, args: list[str]) -> None:
        audit_replay(args)

    # ── /audit explain ────────────────────────────────────────────────────────

    def _audit_explain(self, args: list[str]) -> None:
        audit_explain(args, self.cfg)

    # ── /audit export ─────────────────────────────────────────────────────────

    def _audit_export(self, args: list[str]) -> None:
        audit_export(args)

    # ── /audit diff ───────────────────────────────────────────────────────────

    def _audit_diff(self, args: list[str]) -> None:
        audit_diff()

    # ── /audit help ───────────────────────────────────────────────────────────

    def _audit_help(self, args: list[str]) -> None:
        from cli.display import BOLD, CYAN, DIM, RESET
        out(f"""
{BOLD}/audit{RESET} [subcommand]

  {CYAN}full{RESET}                    Run all audit checks on the current workspace
  {CYAN}security{RESET}                Security scan (secrets, shell=True, eval/exec, CVEs)
  {CYAN}quality{RESET}                 Code quality metrics (complexity, line limits, style)
  {CYAN}deps{RESET}                    Dependency vulnerability check (pip-audit + offline CVEs)
  {CYAN}compare{RESET}                 Compare ILX AI CLI to industry tools via web + LLM
  {CYAN}compare <tool>{RESET}          Compare to a specific tool (e.g. /audit compare aider)
  {CYAN}replay [N|today]{RESET}        Replay recent session actions from the audit log
  {CYAN}explain [N]{RESET}             AI summary of what happened this session
  {CYAN}export [file|--csv]{RESET}     Export audit log to JSON or CSV
  {CYAN}diff{RESET}                    Show files changed this session

  {DIM}Examples:{RESET}
    /audit
    /audit security
    /audit quality
    /audit deps
    /audit compare
    /audit compare aider
    /audit replay
    /audit replay today
    /audit replay 100
    /audit explain
    /audit explain 50
    /audit export
    /audit export session.json
    /audit export --csv
    /audit diff
""")
