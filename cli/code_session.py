"""CodeSession — wraps CodingAgent for the interactive code-agent mode."""
from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig
    from cli.context import ContextManager

_log = logging.getLogger("ilx_cli.code")


class CodeSession:
    """Handles one code-agent task dispatch."""

    def __init__(self, cfg: AppConfig, ctx: ContextManager) -> None:
        self.cfg = cfg
        self.ctx = ctx

    def run_task(self, task: str) -> bool:
        """Run the code-agent on task. Returns True on success."""
        from app.core import git_helper
        from app.core.config import PermissionMode
        from cli.diff_viewer import show_file_change
        from cli.display import (
            DIM,
            GREEN,
            RED,
            RESET,
            YELLOW,
            print_diff_line,
            print_hr,
        )
        from codex.app.controller import CodingAgent
        from codex.app.llm_client import get_llm_client

        cfg = self.cfg

        if not cfg.working_folder:
            print(f"{YELLOW}No workspace set. Use /workspace to set a working folder first.{RESET}")
            return False

        if self.ctx.looks_like_question(task):
            print(
                f"\n{YELLOW}That looks like a question, not a coding task.{RESET}\n"
                f"{DIM}Code-agent mode creates/edits files — use /chat for questions.{RESET}\n"
            )
            try:
                ans = input("  Run code-agent anyway? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans not in ("y", "yes"):
                return False

        client = get_llm_client(cfg)

        def _status(msg: str) -> None:
            print(f"  {DIM}{msg}{RESET}")

        def _output(stream: str, text: str) -> None:
            if stream == "diff":
                print_diff_line(text)
                return
            col    = GREEN if stream == "stdout" else (RED if stream == "stderr" else YELLOW)
            prefix = {"stdout": "out", "stderr": "err", "file": "file", "command": "run"}.get(stream, stream)
            print(f"  {col}[{prefix}]{RESET} {text}")

        def _permission(kind: str, target: str, detail: str) -> bool:
            if cfg.permission_mode == PermissionMode.AUTO_APPROVE:
                return True
            if cfg.permission_mode == PermissionMode.DENY_ALL:
                print(f"  {RED}[denied]{RESET} {kind}: {target}")
                return False
            print(f"\n  {YELLOW}[permission]{RESET} {kind.upper()}: {target}")
            if detail:
                print(f"  {DIM}{detail}{RESET}")
            try:
                ans = input("  Allow? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            return ans in ("y", "yes")

        is_git = git_helper.status(cfg.working_folder).is_repo

        agent = CodingAgent(
            llm_client=client,
            on_status=_status,
            on_output=_output,
            permission_callback=_permission,
            max_attempts=cfg.autofix_max_iterations,
            run_timeout=cfg.exec_timeout,
            auto_commit=False,
            on_diff=lambda path, old, new: show_file_change(path, old, new),
        )

        print_hr()
        try:
            result = agent.run(task=task, working_folder=cfg.working_folder)
        except Exception as exc:
            from app.core.error_classifier import classify_error
            classified = classify_error(exc, getattr(cfg, 'provider', ''))
            print(f"\n  {RED}Agent error: {classified.message}{RESET}")
            print(f"  {YELLOW}Suggestion: {classified.suggestion}{RESET}")
            print_hr()
            return False
        print_hr()

        if result.success:
            print(f"{GREEN}Done in {result.attempts} attempt(s).{RESET}")
            if result.files_written:
                print(f"Files written: {', '.join(result.files_written)}")
            if result.final_output:
                print(f"\n{result.final_output}")
            if getattr(cfg, "autofix_enabled", False):
                self._run_autofix()
            if is_git and result.files_written:
                try:
                    ans = input(f"\n  {DIM}Commit these changes to git? [y/N] {RESET}").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    ans = "n"
                if ans in ("y", "yes"):
                    commit_msg = f"ilx: {task[:60]}"
                    ok, out = git_helper.commit(cfg.working_folder, commit_msg, add_all=True)
                    if ok:
                        print(f"  {GREEN}Committed: {out.splitlines()[0] if out else commit_msg}{RESET}")
                    else:
                        print(f"  {YELLOW}Commit failed: {out}{RESET}")
        else:
            print(f"{RED}Failed after {result.attempts} attempt(s).{RESET}")
            if result.final_error:
                print(f"Error: {result.final_error}")
        print()
        return result.success

    def run_streaming_mode(self, task: str) -> bool:
        """Run the code-agent in streaming mode, printing tokens as they arrive.

        Status updates are shown as ANSI in-place progress lines using ``\\r``.
        Returns True on success.
        """
        from app.core import git_helper
        from app.core.config import PermissionMode
        from cli.diff_viewer import show_file_change
        from cli.display import (
            DIM,
            GREEN,
            RED,
            RESET,
            YELLOW,
            print_hr,
        )
        from codex.app.controller import CodingAgent
        from codex.app.llm_client import get_llm_client

        cfg = self.cfg

        if not cfg.working_folder:
            print(f"{YELLOW}No workspace set. Use /workspace to set a working folder first.{RESET}")
            return False

        if self.ctx.looks_like_question(task):
            print(
                f"\n{YELLOW}That looks like a question, not a coding task.{RESET}\n"
                f"{DIM}Code-agent mode creates/edits files — use /chat for questions.{RESET}\n"
            )
            try:
                ans = input("  Run code-agent anyway? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans not in ("y", "yes"):
                return False

        client = get_llm_client(cfg)
        _step = [0]

        def _on_chunk(text: str) -> None:
            # Print tokens inline without a newline so they stream visually
            sys.stdout.write(text)
            sys.stdout.flush()

        def _on_tool(name: str, args: dict) -> None:
            # End any in-progress token stream line, then show tool call
            sys.stdout.write("\n")
            sys.stdout.flush()
            detail = args.get("path") or args.get("command") or ""
            print(f"  {DIM}[tool] {name}{(' — ' + detail) if detail else ''}{RESET}")

        def _on_status(msg: str) -> None:
            _step[0] += 1
            # Overwrite the current terminal line with the status update
            sys.stdout.write(f"\r  {DIM}[step {_step[0]}] {msg}{RESET}    ")
            sys.stdout.flush()

        def _permission(kind: str, target: str, detail: str) -> bool:
            sys.stdout.write("\n")
            sys.stdout.flush()
            if cfg.permission_mode == PermissionMode.AUTO_APPROVE:
                return True
            if cfg.permission_mode == PermissionMode.DENY_ALL:
                print(f"  {RED}[denied]{RESET} {kind}: {target}")
                return False
            print(f"\n  {YELLOW}[permission]{RESET} {kind.upper()}: {target}")
            if detail:
                print(f"  {DIM}{detail}{RESET}")
            try:
                ans = input("  Allow? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            return ans in ("y", "yes")

        is_git = git_helper.status(cfg.working_folder).is_repo

        agent = CodingAgent(
            llm_client=client,
            on_output=None,
            permission_callback=_permission,
            max_attempts=cfg.autofix_max_iterations,
            run_timeout=cfg.exec_timeout,
            auto_commit=False,
            on_diff=lambda path, old, new: show_file_change(path, old, new),
        )

        print_hr()
        result = agent.run_streaming(
            task=task,
            working_folder=cfg.working_folder,
            on_chunk=_on_chunk,
            on_tool=_on_tool,
            on_status=_on_status,
        )
        # Ensure we end on a fresh line after streaming output
        sys.stdout.write("\n")
        sys.stdout.flush()
        print_hr()

        if result.success:
            print(f"{GREEN}Done in {result.attempts} attempt(s).{RESET}")
            if result.files_written:
                print(f"Files written: {', '.join(result.files_written)}")
            if result.final_output:
                print(f"\n{result.final_output}")
            if getattr(cfg, "autofix_enabled", False):
                self._run_autofix()
            if is_git and result.files_written:
                try:
                    ans = input(f"\n  {DIM}Commit these changes to git? [y/N] {RESET}").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    ans = "n"
                if ans in ("y", "yes"):
                    commit_msg = f"ilx: {task[:60]}"
                    ok, out = git_helper.commit(cfg.working_folder, commit_msg, add_all=True)
                    if ok:
                        print(f"  {GREEN}Committed: {out.splitlines()[0] if out else commit_msg}{RESET}")
                    else:
                        print(f"  {YELLOW}Commit failed: {out}{RESET}")
        else:
            print(f"{RED}Failed after {result.attempts} attempt(s).{RESET}")
            if result.final_error:
                print(f"Error: {result.final_error}")
        print()
        return result.success

    def _run_autofix(self) -> None:
        """Run the test-fix loop after a successful code task."""
        from cli.display import DIM, GREEN, RESET, YELLOW
        from app.core.test_fix_loop import TestFixLoop, detect_test_runner

        cfg = self.cfg
        wf = cfg.working_folder
        if not wf:
            return

        runner = detect_test_runner(wf)
        print(f"\n{DIM}Auto test-fix: running {runner[0]}...{RESET}")

        def _on_progress(attempt: int, failures_before: int, output: str) -> None:
            print(f"  {DIM}[attempt {attempt}] {failures_before} failure(s)...{RESET}")

        loop = TestFixLoop(
            cfg=cfg,
            max_attempts=getattr(cfg, "autofix_max_iterations", 5),
        )
        result = loop.run(
            working_folder=wf,
            runner=runner,
            on_progress=_on_progress,
        )
        if result.final_pass:
            print(f"  {GREEN}All tests pass.{RESET}")
        else:
            iterations = len(result.attempts)
            print(f"  {YELLOW}Tests still failing after {iterations} iteration(s).{RESET}")
