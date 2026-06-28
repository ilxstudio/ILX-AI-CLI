"""Dev tool commands — /run, /test, /lint, /format, /ci, /build, /deps, /stats, /env, /crashes, /kill, /logs, /watch, /profile, /attach."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig


_log = logging.getLogger("ilx_cli.devtools")

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "x64", "x86", "Debug", "Release", ".vs", ".ilxbuild",
    "obj", "bin", ".project_index",
}


from cli.commands.dev_tools_quality import DevToolsQualityMixin
from cli.commands.dev_tools_extra import DevToolsExtraCommands


class DevToolsCommands(DevToolsQualityMixin):
    """Handles all developer-tool slash commands."""

    def __init__(self, cfg: "AppConfig") -> None:
        self.cfg = cfg
        self._extra = DevToolsExtraCommands(cfg)

    def _wf(self) -> str | None:
        return self.cfg.working_folder or None

    def _require_workspace(self) -> str | None:
        from cli.display import YELLOW, RESET
        wf = self._wf()
        if not wf:
            print(f"{YELLOW}No workspace set. Use /workspace first.{RESET}")
        return wf

    # ── Delegated to DevToolsExtraCommands ───────────────────────────────────

    def cmd_watch(self, args: list[str]) -> None:
        self._extra.cmd_watch(args)

    def cmd_profile(self, args: list[str]) -> None:
        self._extra.cmd_profile(args)

    def cmd_attach(self, args: list[str]) -> None:
        self._extra.cmd_attach(args)

    # ── /run ─────────────────────────────────────────────────────────────────

    def cmd_run(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, RESET
        from app.core.supervisor import supervisor
        wf = self._require_workspace()
        if not wf:
            return
        run_args = args if args else ["python", "main.py"]
        run_cmd  = " ".join(run_args)
        timeout  = self.cfg.exec_timeout or 60
        print(f"{DIM}Running: {run_cmd}  (timeout {timeout}s)  — tracked by supervisor{RESET}")

        def _on_line(line: str) -> None:
            print(f"  {DIM}|{RESET} {line}")

        task = supervisor.spawn_blocking(
            command=run_args,
            label=run_cmd,
            cwd=wf,
            timeout=timeout,
            on_line=_on_line,
        )
        from app.core.supervisor import TaskStatus
        col = GREEN if task.status == TaskStatus.COMPLETED else (
              YELLOW if task.status in (TaskStatus.KILLED, TaskStatus.TIMEOUT) else RED)
        print(f"  {col}[{task.status.value}  exit={task.exit_code}  {task.elapsed:.1f}s]{RESET}")

    # ── /kill ─────────────────────────────────────────────────────────────────

    def cmd_kill(self, args: list[str] | None = None) -> None:
        from cli.display import GREEN, YELLOW, RESET
        from app.core.supervisor import supervisor
        task_id = args[0].upper() if args else None
        ok = supervisor.kill(task_id)
        if ok:
            print(f"  {GREEN}Task killed.{RESET}")
        else:
            label = f"task {task_id}" if task_id else "any running task"
            print(f"  {YELLOW}No running {label} found.{RESET}")

    # ── /test ─────────────────────────────────────────────────────────────────

    def cmd_test(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RED, BOLD, YELLOW, RESET
        from app.core import process_runner
        wf = self._require_workspace()
        if not wf:
            return
        pytest_bin = shutil.which("pytest") or shutil.which("py.test")
        if not pytest_bin:
            print(f"{YELLOW}pytest not found. Install with: pip install pytest{RESET}")
            return

        # Detect --cov flag
        use_cov = "--cov" in args
        filtered_args = [a for a in args if a != "--cov"]
        cmd = [pytest_bin, "-v", "--tb=short"]
        import os as _os
        cov_threshold = _os.environ.get("ILX_COV_THRESHOLD", "")
        if use_cov:
            cmd += ["--cov", "--cov-report=term-missing"]
            if cov_threshold:
                cmd += [f"--cov-fail-under={cov_threshold}"]
            print(f"{DIM}Running pytest with coverage in {wf}...{RESET}")
        else:
            print(f"{DIM}Running pytest in {wf}...{RESET}")
        cmd += filtered_args

        r = process_runner.run(cmd, cwd=wf, timeout=180)
        if r.returncode == -1 and "Timed out" in r.stderr:
            print(f"{RED}Test run timed out after 180s.{RESET}")
            return
        for line in r.stdout.splitlines():
            if "PASSED" in line:
                print(f"  {GREEN}{line}{RESET}")
            elif "FAILED" in line or "ERROR" in line:
                print(f"  {RED}{line}{RESET}")
            elif line.startswith("="):
                print(f"  {BOLD}{line}{RESET}")
            elif "TOTAL" in line and "%" in line:
                print(f"  {BOLD}{line}{RESET}")
            else:
                print(f"  {line}")
        if r.stderr:
            print(f"  {DIM}{r.stderr[:500]}{RESET}")
        col = GREEN if r.ok else RED
        print(f"  {col}[exit {r.returncode}]{RESET}")

    # ── /lint ─────────────────────────────────────────────────────────────────

    def cmd_lint(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, BOLD, RESET
        from app.core import process_runner
        wf = self._require_workspace()
        if not wf:
            return

        fix_mode    = "fix" in args
        tool_filter = next((a for a in args if a not in ("fix",)), None)
        if tool_filter:
            tool_filter = tool_filter.lower()

        if fix_mode:
            print(f"  {BOLD}Auto-fix mode{RESET} — changes will be written to disk.")

        def _run_linter(name: str, check_cmd: list[str], fix_cmd: list[str]) -> None:
            bin_ = shutil.which(name)
            if not bin_:
                print(f"  {YELLOW}{name} not found — install with: pip install {name}{RESET}")
                return
            cmd = fix_cmd if fix_mode else check_cmd
            label = f"{name} (fix)" if fix_mode else name
            print(f"  {DIM}Running {label}...{RESET}")
            r = process_runner.run(cmd, cwd=wf, timeout=60)
            if r.returncode == -1 and "Timed out" in r.stderr:
                print(f"  {RED}{name} timed out.{RESET}")
                return
            out = (r.stdout + r.stderr).strip()
            for ln in out.splitlines()[:60]:
                print(f"    {ln}")
            col = GREEN if r.ok else (YELLOW if fix_mode else RED)
            print(f"  {col}[{label} exit {r.returncode}]{RESET}")

        if tool_filter in (None, "ruff"):
            _run_linter("ruff",
                        check_cmd=["ruff", "check", "."],
                        fix_cmd=["ruff", "check", "--fix", "."])
        if tool_filter in (None, "black"):
            _run_linter("black",
                        check_cmd=["black", "--check", "."],
                        fix_cmd=["black", "."])
        if tool_filter in (None, "mypy") and not fix_mode:
            _run_linter("mypy",
                        check_cmd=["mypy", "."],
                        fix_cmd=["mypy", "."])

    # ── /format ───────────────────────────────────────────────────────────────

    def cmd_format(self) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, RESET
        from app.core import process_runner
        wf = self._require_workspace()
        if not wf:
            return
        ran_any = False
        for tool, cmd in [
            ("ruff",  ["ruff", "format", "."]),
            ("black", ["black", "."]),
        ]:
            bin_ = shutil.which(tool)
            if not bin_:
                continue
            ran_any = True
            print(f"  {DIM}Running {tool} format...{RESET}")
            r = process_runner.run(cmd, cwd=wf, timeout=60)
            if r.returncode == -1 and "Timed out" in r.stderr:
                print(f"  {RED}{tool} timed out.{RESET}")
                continue
            out = (r.stdout + r.stderr).strip()
            for ln in out.splitlines()[:30]:
                print(f"    {ln}")
            col = GREEN if r.ok else RED
            print(f"  {col}[{tool} exit {r.returncode}]{RESET}")
        if not ran_any:
            print(f"  {YELLOW}No formatter found. Install ruff or black: pip install ruff black{RESET}")

    # ── /build ────────────────────────────────────────────────────────────────

    def cmd_build(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, RESET
        from app.core import build_helper
        wf = self._require_workspace()
        if not wf:
            return
        entry   = args[0] if args else "main.py"
        onefile = "--folder" not in args
        if not (Path(wf) / entry).exists():
            print(f"{RED}Entry point not found: {entry}{RESET}")
            return
        if not build_helper.pyinstaller_available():
            print(f"{YELLOW}PyInstaller not found.{RESET}")
            ans = input("  Install it now? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                return
            print(f"{DIM}Installing PyInstaller...{RESET}")
            ok, out = build_helper.install_pyinstaller()
            if not ok:
                print(f"{RED}Install failed: {out}{RESET}")
                return
            print(f"{GREEN}Installed.{RESET}")
        new_ver = build_helper.bump_version(wf)
        if new_ver:
            print(f"  {DIM}Version bumped to {new_ver}{RESET}")
        mode_str = "onefile" if onefile else "onedir"
        print(f"{DIM}Building {entry} ({mode_str})...{RESET}")

        def _out(line: str) -> None:
            if "ERROR" in line or "error" in line.lower():
                print(f"  {RED}{line}{RESET}")
            elif "WARNING" in line:
                print(f"  {YELLOW}{line}{RESET}")
            elif line.strip():
                print(f"  {DIM}{line}{RESET}")

        success, summary = build_helper.build(entry, wf, onefile=onefile, on_output=_out)
        print(f"\n{GREEN if success else RED}{summary}{RESET}")

    # ── /deps ─────────────────────────────────────────────────────────────────

    def cmd_deps(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, RESET
        from app.core import process_runner
        wf = self._wf()
        pip = shutil.which("pip") or shutil.which("pip3")
        if not pip:
            print(f"{RED}pip not found in PATH.{RESET}")
            return
        if not args:
            print(f"{DIM}Running pip list...{RESET}")
            r = process_runner.run([pip, "list"], timeout=15)
            if r.ok:
                print(r.stdout[:3000])
            else:
                print(f"{RED}pip list failed: {r.stderr}{RESET}")
            return
        sub = args[0].lower()
        if sub == "install":
            pkgs = args[1:]
            if not pkgs and wf:
                req = Path(wf) / "requirements.txt"
                if req.exists():
                    pkgs = ["-r", str(req)]
                    print(f"{DIM}Installing from requirements.txt...{RESET}")
            if not pkgs:
                print(f"{YELLOW}Usage: /deps install <package>{RESET}")
                return
            r = process_runner.run([pip, "install"] + pkgs, timeout=120)
            if r.returncode == -1 and "Timed out" in r.stderr:
                print(f"{RED}pip install timed out.{RESET}")
                return
            print((r.stdout + r.stderr)[:2000])
            col = GREEN if r.ok else RED
            print(f"{col}[exit {r.returncode}]{RESET}")
        elif sub == "outdated":
            r = process_runner.run([pip, "list", "--outdated"], timeout=30)
            if r.ok:
                print(r.stdout[:3000] or f"{GREEN}All packages up to date.{RESET}")
            else:
                print(f"{RED}pip outdated failed: {r.stderr}{RESET}")
        else:
            print(f"{YELLOW}Usage: /deps  |  /deps install <pkg>  |  /deps outdated{RESET}")

    # ── /stats ────────────────────────────────────────────────────────────────

    def cmd_stats(self, args: list[str] | None = None) -> None:
        from cli.display import BOLD, DIM, GREEN, YELLOW, RESET
        wf = self._require_workspace()
        if not wf:
            return
        root = Path(wf)
        py_files = [
            p for p in root.rglob("*.py")
            if not any(d in _SKIP_DIRS for d in p.relative_to(root).parts)
        ]
        total_lines = 0
        total_bytes = 0
        total_funcs = 0
        largest = ("", 0)
        warn: list[tuple[str, int]] = []

        for pf in py_files:
            try:
                txt = pf.read_text(encoding="utf-8", errors="replace")
                lc  = txt.count("\n")
                fc  = txt.count("\ndef ") + (1 if txt.startswith("def ") else 0)
                total_lines += lc
                total_bytes += len(txt.encode("utf-8"))
                total_funcs += fc
                if lc > largest[1]:
                    largest = (str(pf.relative_to(root)), lc)
                if lc > 700:
                    warn.append((pf.relative_to(root).as_posix(), lc))
            except OSError:
                pass

        avg_fn_len = (total_lines // total_funcs) if total_funcs else 0

        print(f"\n{BOLD}Codebase stats — {wf}{RESET}")
        print(f"  Python files  : {len(py_files)}")
        print(f"  Total lines   : {total_lines:,}")
        print(f"  Total size    : {total_bytes / 1024:.1f} KB")
        print(f"  Functions     : {total_funcs}  (avg ~{avg_fn_len} lines each)")
        if largest[0]:
            print(f"  Largest file  : {largest[0]}  ({largest[1]:,} lines)")
        if warn:
            print(f"  {YELLOW}Files > 700 lines (consider splitting):{RESET}")
            for wf2, wl in sorted(warn, key=lambda x: -x[1])[:5]:
                print(f"    {YELLOW}* {wf2}  ({wl:,} lines){RESET}")
        else:
            print(f"  {GREEN}All files within 700-line limit.{RESET}")
        if args and "--json" in args:
            import json
            payload = {
                "python_files": len(py_files),
                "total_lines": total_lines,
                "total_bytes": total_bytes,
                "total_functions": total_funcs,
                "avg_function_lines": avg_fn_len,
                "largest_file": {"path": largest[0], "lines": largest[1]},
                "files_over_700": [{"path": p, "lines": l} for p, l in warn],
            }
            print(json.dumps(payload, indent=2))
        print()

    # ── /tasks ────────────────────────────────────────────────────────────────

    def cmd_tasks(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET
        from app.core.supervisor import supervisor, TaskStatus
        sub = args[0].lower() if args else "list"

        if sub == "list":
            tasks = supervisor.all_tasks(20)
            if not tasks:
                print(f"  {DIM}No tasks recorded yet.  Tasks appear when you use /run.{RESET}")
                return
            print(f"\n{BOLD}Task Registry (most recent first):{RESET}")
            for t in tasks:
                if t.status == TaskStatus.RUNNING:
                    col = CYAN
                elif t.status == TaskStatus.COMPLETED:
                    col = GREEN
                elif t.status in (TaskStatus.KILLED, TaskStatus.TIMEOUT):
                    col = YELLOW
                else:
                    col = RED
                pid_s  = f"  PID {t.pid}" if t.pid else ""
                code_s = f"  exit={t.exit_code}" if t.exit_code is not None else ""
                print(f"  {col}[{t.task_id}]{RESET} {t.status.value:<10}  "
                      f"{t.elapsed:.1f}s{pid_s}{code_s}  {DIM}{t.label}{RESET}")
            running = supervisor.running_tasks()
            if running:
                print(f"\n  {YELLOW}{len(running)} task(s) still running.  Use /kill [TASK_ID] to stop.{RESET}")
            print()

        elif sub == "tail" and len(args) >= 2:
            task_id = args[1].upper()
            lines = supervisor.tail(task_id, 30)
            if not lines:
                print(f"  {YELLOW}No output for task {task_id}.{RESET}")
            else:
                print(f"\n{BOLD}Output tail — {task_id}:{RESET}")
                for ln in lines:
                    print(f"  {DIM}{ln}{RESET}")
                print()

        elif sub == "killall":
            n = supervisor.kill_all()
            print(f"  {GREEN if n else YELLOW}Killed {n} running task(s).{RESET}")

        else:
            print(f"{YELLOW}Usage: /tasks  |  /tasks tail <TASK_ID>  |  /tasks killall{RESET}")

    # ── /ci ───────────────────────────────────────────────────────────────────

    def cmd_ci(self, args: list[str]) -> None:
        """Run the full local CI pipeline: ruff, mypy, pytest --cov, bandit."""
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, RESET
        from app.core import process_runner
        wf = self._require_workspace()
        if not wf:
            return
        results: list[tuple[str, bool, str]] = []

        def _run_step(name: str, cmd: list[str], timeout: int = 60) -> bool:
            bin_ = shutil.which(cmd[0])
            if not bin_:
                results.append((name, False, f"{cmd[0]} not found"))
                print(f"  {YELLOW}SKIP{RESET}  {name}  ({cmd[0]} not installed)")
                return False
            print(f"  {DIM}Running {name}...{RESET}")
            r = process_runner.run(cmd, cwd=wf, timeout=timeout)
            if r.returncode == -1 and "Timed out" in r.stderr:
                results.append((name, False, f"timed out after {timeout}s"))
                print(f"  {RED}TIMEOUT{RESET}  {name}")
                return False
            out = (r.stdout + r.stderr).strip()
            summary = out.splitlines()[-1][:80] if out else "(no output)"
            results.append((name, r.ok, summary))
            col = GREEN if r.ok else RED
            print(f"  {col}{'PASS' if r.ok else 'FAIL'}{RESET}  {name}  {DIM}{summary}{RESET}")
            if not r.ok:
                for ln in out.splitlines()[-10:]:
                    print(f"       {DIM}{ln}{RESET}")
            return r.ok

        print(f"\n{BOLD}CI Pipeline — {wf}{RESET}\n")
        _run_step("ruff check",    ["ruff", "check", "."])
        _run_step("black check",   ["black", "--check", "."])
        _run_step("mypy",          ["mypy", "."], timeout=120)
        _run_step("pytest --cov",  ["pytest", "--tb=short", "-q", "--cov", "--cov-report=term-missing"], timeout=180)
        _run_step("bandit",        ["bandit", "-r", "-q", "."], timeout=60)

        passed = sum(1 for _, ok, _ in results if ok)
        total  = len(results)
        col    = GREEN if passed == total else (YELLOW if passed > 0 else RED)
        print(f"\n{col}{BOLD}{passed}/{total} steps passed{RESET}\n")

    # ── /env ──────────────────────────────────────────────────────────────────

    def cmd_env(self) -> None:
        from cli.display import BOLD, CYAN, DIM, RED, RESET
        wf = self._require_workspace()
        if not wf:
            return
        env_path = Path(wf) / ".env"
        if not env_path.exists():
            print(f"  {DIM}No .env file found at {env_path}{RESET}")
            return
        print(f"\n{BOLD}.env — {env_path}{RESET}")
        try:
            for ln in env_path.read_text(encoding="utf-8").splitlines():
                ls = ln.strip()
                if not ls or ls.startswith("#"):
                    print(f"  {DIM}{ln}{RESET}")
                elif "=" in ls:
                    k, _, v = ls.partition("=")
                    k = k.removeprefix("export ").strip()
                    masked = v if len(v) <= 4 else v[:2] + "*" * (len(v) - 4) + v[-2:]
                    print(f"  {CYAN}{k}{RESET}={masked}")
                else:
                    print(f"  {ln}")
        except OSError as exc:
            print(f"  {RED}Could not read .env: {exc}{RESET}")
        print()

    # ── /logs ─────────────────────────────────────────────────────────────────

    def cmd_logs(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, CYAN, YELLOW, RED, RESET
        n = 50
        if args:
            try:
                n = int(args[0])
            except ValueError:
                pass
        log_path = Path.home() / ".ilx_cli" / "logs" / "audit.log"
        if not log_path.exists():
            print(f"  {DIM}No audit log found at {log_path}{RESET}")
            print(f"  {DIM}The log is created automatically when the CLI runs.{RESET}")
            return
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail  = lines[-n:]
            print(f"\n{BOLD}Audit log (last {len(tail)} lines) — {log_path}{RESET}")
            for ln in tail:
                if '"level": "ERROR"' in ln or '"ERROR"' in ln:
                    print(f"  {RED}{ln[:200]}{RESET}")
                elif '"level": "WARN"' in ln or '"WARN"' in ln:
                    print(f"  {YELLOW}{ln[:200]}{RESET}")
                else:
                    print(f"  {DIM}{ln[:200]}{RESET}")
            print()
        except OSError as exc:
            print(f"  {RED}Could not read log: {exc}{RESET}")

    # ── /crashes ──────────────────────────────────────────────────────────────

    def cmd_crashes(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, RESET
        from app.core import crash_db
        sub = args[0].lower() if args else "list"
        if sub == "clear":
            n = crash_db.clear_crashes()
            print(f"{GREEN}Cleared {n} crash record(s).{RESET}")
        elif sub == "summary":
            groups = crash_db.group_summary()
            if not groups:
                print(f"  {DIM}No crash records yet.{RESET}")
            else:
                print(f"\n{BOLD}Crash groups (by signature):{RESET}")
                for g in groups:
                    print(f"  {RED}x{g['count']}{RESET}  {g['command']}  "
                          f"sig={g['sig']}  last={g['last'][:16]}")
                print()
        else:
            crashes = crash_db.list_crashes(20)
            if not crashes:
                print(f"  {DIM}No crash records yet.{RESET}")
            else:
                print(f"\n{BOLD}Recent crashes (last 20):{RESET}")
                for c in crashes:
                    ts = c["ts"][:16].replace("T", " ")
                    print(f"  {RED}#{c['id']}{RESET}  {ts}  [{c['exit_code']}]  {c['command']}")
                    for tl in c["tb"].splitlines()[-3:]:
                        print(f"      {DIM}{tl}{RESET}")
                print(f"  {DIM}Use /crashes summary or /crashes clear{RESET}\n")
