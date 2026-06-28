"""Dev tool extra commands — /watch, /profile, /attach (background/blocking operations)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "x64", "x86", "Debug", "Release", ".vs", ".ilxbuild",
    "obj", "bin", ".project_index",
}


class DevToolsExtraCommands:
    """Handles /watch, /profile, and /attach commands."""

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

    # ── /watch ────────────────────────────────────────────────────────────────

    def cmd_watch(self, args: list[str]) -> None:
        from cli.display import CYAN, DIM, GREEN, RED, YELLOW, RESET
        import time
        wf = self._require_workspace()
        if not wf:
            return
        pytest_bin = shutil.which("pytest")
        if not pytest_bin:
            print(f"{YELLOW}pytest not found — install with /deps install pytest{RESET}")
            return

        # Parse --glob <pattern> from args, default to "*.py"
        glob_pattern = "*.py"
        if "--glob" in args:
            idx = args.index("--glob")
            if idx + 1 < len(args):
                glob_pattern = args[idx + 1]

        root = Path(wf)

        def _mtimes() -> dict[str, float]:
            mt: dict[str, float] = {}
            for p in root.rglob(glob_pattern):
                if not any(d in _SKIP_DIRS for d in p.relative_to(root).parts):
                    try:
                        mt[str(p)] = p.stat().st_mtime
                    except OSError:
                        pass
            return mt

        print(f"{DIM}Watching {wf} [{glob_pattern}] for changes (Ctrl+C to stop)...{RESET}")
        prev = _mtimes()
        try:
            while True:
                time.sleep(1.5)
                cur = _mtimes()
                changed = [f for f, t in cur.items() if prev.get(f) != t or f not in prev]
                if changed:
                    print(f"  {CYAN}Changed:{RESET} {', '.join(Path(f).name for f in changed[:3])}")
                    prev = cur
                    from app.core import process_runner
                    r = process_runner.run(
                        [pytest_bin, "--tb=short", "-q"], cwd=wf, timeout=120,
                    )
                    out = (r.stdout + r.stderr).strip()
                    for ln in out.splitlines()[-15:]:
                        if "passed" in ln or "PASSED" in ln:
                            print(f"  {GREEN}{ln}{RESET}")
                        elif "failed" in ln or "error" in ln.lower():
                            print(f"  {RED}{ln}{RESET}")
                        else:
                            print(f"  {ln}")
        except KeyboardInterrupt:
            print(f"\n{DIM}Watch stopped.{RESET}")

    # ── /profile ──────────────────────────────────────────────────────────────

    def cmd_profile(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, RED, RESET
        import io
        import pstats
        wf = self._require_workspace()
        if not wf:
            return
        target = args if args else ["python", "main.py"]
        prof_out    = Path(wf) / "_ilx_profile.prof"
        prof_script = Path(wf) / "_ilx_profile_runner.py"
        print(f"{DIM}Profiling: {' '.join(target)} (up to 20s)...{RESET}")
        code = (
            f"import cProfile, sys\n"
            f"sys.argv = {target!r}\n"
            f"cProfile.run(open({str(target[-1])!r}).read(), {str(prof_out)!r})\n"
        )
        try:
            prof_script.write_text(code, encoding="utf-8")
            from app.core import process_runner
            process_runner.run(["python", str(prof_script)], cwd=wf, timeout=20)
            if prof_out.exists():
                sio = io.StringIO()
                ps = pstats.Stats(str(prof_out), stream=sio)
                ps.sort_stats("cumulative")
                ps.print_stats(25)
                print(f"\n{BOLD}Top 25 functions by cumulative time:{RESET}")
                for ln in sio.getvalue().splitlines()[5:30]:
                    print(f"  {ln}")
                prof_out.unlink(missing_ok=True)
            else:
                print(f"{RED}Profile run produced no output.{RESET}")
        except Exception as exc:
            print(f"{RED}Profile error: {exc}{RESET}")
        finally:
            prof_script.unlink(missing_ok=True)

    # ── /attach ───────────────────────────────────────────────────────────────

    def cmd_attach(self, args: list[str]) -> None:
        """Tail live output of a running background task. Press Ctrl+C to detach."""
        from cli.display import BOLD, DIM, CYAN, YELLOW, RED, GREEN, RESET
        from app.core.supervisor import supervisor, TaskStatus
        import time as _time
        if not args:
            running = supervisor.running_tasks()
            if not running:
                print(f"  {YELLOW}No running tasks. Use /tasks to see all tasks.{RESET}")
                return
            task = running[-1]
            task_id = task.task_id
        else:
            task_id = args[0].upper()
        task = supervisor.get(task_id)
        if task is None:
            print(f"  {YELLOW}Task {task_id} not found.{RESET}")
            return
        print(f"\n{BOLD}Attached to {task_id} — {task.label}{RESET}  {DIM}(Ctrl+C to detach){RESET}")
        # Show existing tail first
        tail = supervisor.tail(task_id, 20)
        for ln in tail:
            print(f"  {DIM}{ln}{RESET}")
        seen = len(task.output_tail)
        try:
            while True:
                current = supervisor.get(task_id)
                if current is None:
                    break
                new_lines = current.output_tail[seen:]
                for ln in new_lines:
                    print(f"  {ln}")
                seen = len(current.output_tail)
                if current.status != TaskStatus.RUNNING:
                    col = GREEN if current.status.value == "completed" else RED
                    print(f"\n  {col}Task {task_id} finished: {current.status.value}  exit={current.exit_code}{RESET}")
                    break
                _time.sleep(0.3)
        except KeyboardInterrupt:
            print(f"\n  {DIM}Detached from {task_id}.{RESET}")
