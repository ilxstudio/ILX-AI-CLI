"""Git commands — /git status/diff/commit/log/pull/push/stash/revert/reset/ai-commit
and /branch.
"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display_compat import out, out_error, out_status, out_result

_log = logging.getLogger("ilx_cli.git")

# ---------------------------------------------------------------------------
# Helpers shared across sub-commands
# ---------------------------------------------------------------------------

def _repo_check(wf: str) -> bool:
    """Return True if *wf* is a git repository, print an error and return False otherwise."""
    from app.core import git_helper
    from cli.display import YELLOW, RESET
    if not git_helper.is_git_repo(wf):
        out_error(f"  {YELLOW}Not a git repository: {wf}{RESET}")
        return False
    return True


def _confirm(prompt: str, cfg=None) -> bool:
    """Prompt user for y/N via the permission engine (respects auto_yes/dry_run).

    When *cfg* is provided, delegates to ``permissions.confirm`` for audit
    trail and auto_yes/dry_run support.  Falls back to raw input otherwise.
    """
    if cfg is not None:
        from app.core.permissions import confirm as _perm_confirm
        return _perm_confirm(prompt.strip().rstrip("[y/N] ").rstrip(": ").strip(), cfg)
    try:
        ans = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    return ans in ("y", "yes")


# ---------------------------------------------------------------------------
# Main command class
# ---------------------------------------------------------------------------

class GitCommands:
    """Handles /git and /branch slash commands."""

    def __init__(self, cfg: "AppConfig") -> None:
        self.cfg = cfg

    def _wf(self) -> str | None:
        return self.cfg.working_folder or None

    # ------------------------------------------------------------------
    # /git dispatcher
    # ------------------------------------------------------------------

    def cmd_git(self, args: list[str]) -> None:
        from cli.display import YELLOW, RESET

        wf = self._wf()
        if not wf:
            out_error(f"{YELLOW}No workspace set. Use /workspace to set one first.{RESET}")
            return
        if not args:
            out(
                f"{YELLOW}Usage: /git status | diff | log | commit [-m \"msg\"] | "
                f"pull | push [--force] | stash [pop|list] | "
                f"revert <hash> | reset HEAD <file> | ai-commit{RESET}"
            )
            return

        sub = args[0].lower()

        if sub == "status":
            self._git_status(wf)
        elif sub == "diff":
            self._git_diff(wf, args[1:])
        elif sub == "commit":
            self._git_commit(wf, args[1:])
        elif sub == "log":
            self._git_log(wf, args[1:])
        elif sub == "pull":
            self._git_pull(wf)
        elif sub == "push":
            self._git_push(wf, args[1:])
        elif sub == "stash":
            self._git_stash(wf, args[1:])
        elif sub == "revert":
            self._git_revert(wf, args[1:])
        elif sub == "reset":
            self._git_reset(wf, args[1:])
        elif sub == "ai-commit":
            self._git_ai_commit(wf)
        else:
            out_error(
                f"{YELLOW}Unknown git subcommand '{sub}'. "
                f"Try: status, diff, log, commit, pull, push, stash, "
                f"revert, reset, ai-commit{RESET}"
            )

    # ------------------------------------------------------------------
    # Sub-command implementations
    # ------------------------------------------------------------------

    def _git_status(self, wf: str) -> None:
        from cli.display import BOLD, GREEN, YELLOW, RESET
        from app.core import git_helper

        s = git_helper.status(wf)
        if not s.is_repo:
            out_error(f"  {YELLOW}Not a git repository: {wf}{RESET}")
            return
        out(f"\n{BOLD}Git status — {wf}{RESET}")
        out(f"  Branch:      {s.branch}" + (f"  <-> {s.upstream}" if s.upstream else ""))
        if s.ahead or s.behind:
            out(f"  Sync:        {s.ahead} ahead, {s.behind} behind")
        if s.last_commit:
            out(f"  Last commit: {s.last_commit}")
        for label, paths in [
            ("Staged", s.staged), ("Modified", s.modified),
            ("Untracked", s.untracked), ("Deleted", s.deleted),
        ]:
            if paths:
                extra = f" (+{len(paths)-8} more)" if len(paths) > 8 else ""
                out(f"  {label} ({len(paths)}): {', '.join(paths[:8])}{extra}")
        if not any([s.staged, s.modified, s.untracked, s.deleted]):
            out(f"  {GREEN}Working tree clean{RESET}")
        out("")

    def _git_diff(self, wf: str, extra: list[str]) -> None:
        from cli.display import DIM, RESET
        from app.core import git_helper

        if not _repo_check(wf):
            return
        staged = "--staged" in extra or "--cached" in extra
        d = git_helper.diff(wf, staged=staged)
        if not d:
            out_status(f"  {DIM}No diff (working tree clean){RESET}")
            return
        from cli.display import print_diff_line
        lines = d.splitlines()
        for line in lines[:80]:
            print_diff_line(line)
        if len(lines) > 80:
            out_status(f"  {DIM}... ({len(lines) - 80} more lines){RESET}")
        out("")

    def _git_commit(self, wf: str, args: list[str]) -> None:
        """Stage all tracked changes and commit.

        Usage:
          /git commit -m "message"
          /git commit "message"      (shorthand)
          /git commit                (prompts interactively)
        """
        from cli.display import BOLD, GREEN, RED, YELLOW, DIM, RESET
        from app.core import git_helper

        if not _repo_check(wf):
            return

        # Parse message from args
        msg = ""
        remaining = list(args)
        if remaining and remaining[0] in ("-m", "--message"):
            remaining.pop(0)
        if remaining:
            msg = " ".join(remaining).strip().strip('"').strip("'")

        if not msg:
            # Show changed files first so the user knows what they're committing
            s = git_helper.status(wf)
            files = s.staged + s.modified + s.deleted
            if files:
                out(f"\n{BOLD}Files to be committed:{RESET}")
                for f in files[:20]:
                    out(f"  {DIM}{f}{RESET}")
                if len(files) > 20:
                    out(f"  {DIM}(+{len(files)-20} more){RESET}")
                out("")
            else:
                out(f"  {YELLOW}Nothing to commit — working tree is clean.{RESET}")
                return
            try:
                msg = input("  Commit message: ").strip()
            except (EOFError, KeyboardInterrupt):
                msg = ""

        if not msg:
            out(f"  {YELLOW}Commit cancelled — empty message.{RESET}")
            return

        # Permission gate
        if not _confirm(f"  {YELLOW}Commit all staged/modified changes? [y/N]{RESET} ", self.cfg):
            out_status(f"  {DIM}Commit cancelled.{RESET}")
            return

        ok, commit_out = git_helper.commit(wf, msg, add_all=True)
        if ok:
            first_line = commit_out.splitlines()[0] if commit_out else msg
            out_result(f"  {GREEN}Committed: {first_line}{RESET}")
        else:
            out_error(f"  {RED}Commit failed: {commit_out}{RESET}")

    def _git_log(self, wf: str, args: list[str]) -> None:
        from cli.display import BOLD, YELLOW, DIM, RESET
        from app.core import git_helper

        if not _repo_check(wf):
            return

        # Allow /git log -N
        n = 10
        if args and args[0].lstrip("-").isdigit():
            n = min(50, int(args[0].lstrip("-")))

        rc, sout, _ = git_helper._run(["log", "--oneline", f"-{n}"], wf)
        if rc == 0 and sout:
            out(f"\n{BOLD}Recent commits:{RESET}")
            for line in sout.strip().splitlines():
                out(f"  {line}")
            out("")
        else:
            out(f"  {YELLOW}No log available{RESET}")

    def _git_pull(self, wf: str) -> None:
        from cli.display import GREEN, RED, YELLOW, DIM, RESET
        from app.core import git_helper

        if not _repo_check(wf):
            return

        out_status(f"  {DIM}Pulling from origin…{RESET}")
        ok, pull_out = git_helper.pull(wf)
        if ok:
            text = pull_out or "Already up to date."
            out_result(f"  {GREEN}Pull complete:{RESET} {text}")
            # Surface conflict hints
            if "CONFLICT" in text.upper():
                out(f"  {YELLOW}Conflicts detected — resolve manually then commit.{RESET}")
        else:
            out_error(f"  {RED}Pull failed:{RESET} {pull_out}")
            if "CONFLICT" in pull_out.upper():
                out(f"  {YELLOW}Tip: resolve conflicts, then run /git commit.{RESET}")

    def _git_push(self, wf: str, args: list[str]) -> None:
        from cli.display import GREEN, RED, YELLOW, DIM, RESET
        from app.core import git_helper

        if not _repo_check(wf):
            return

        force = "--force" in args or "-f" in args

        if force:
            # Hard block: require explicit typed confirmation
            out(f"  {YELLOW}WARNING: Force-push will rewrite remote history.{RESET}")
            try:
                ans = input(
                    "  This will force-push. "
                    "Type 'yes' to confirm (anything else cancels): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans != "yes":
                out_status(f"  {DIM}Force-push cancelled.{RESET}")
                return

        out_status(f"  {DIM}Pushing to origin…{RESET}")
        ok, push_out = git_helper.push(wf, force=force)
        if ok:
            out_result(f"  {GREEN}Push complete:{RESET} {push_out or 'Done.'}")
        else:
            out_error(f"  {RED}Push failed:{RESET} {push_out}")

    def _git_stash(self, wf: str, args: list[str]) -> None:
        from cli.display import GREEN, RED, YELLOW, DIM, RESET
        from app.core import git_helper

        if not _repo_check(wf):
            return

        sub = args[0].lower() if args else ""

        if sub not in ("", "pop", "list"):
            out(f"  {YELLOW}Usage: /git stash | /git stash pop | /git stash list{RESET}")
            return

        if sub == "list":
            ok, stash_out = git_helper.stash(wf, "list")
            if ok:
                if stash_out:
                    out("\n  Stash list:\n")
                    for line in stash_out.splitlines():
                        out(f"  {line}")
                    out("")
                else:
                    out_status(f"  {DIM}No stashes.{RESET}")
            else:
                out_error(f"  {RED}Stash list failed:{RESET} {stash_out}")
            return

        if sub == "pop":
            ok, stash_out = git_helper.stash(wf, "pop")
            if ok:
                out_result(f"  {GREEN}Stash popped:{RESET} {stash_out or 'Done.'}")
            else:
                out_error(f"  {RED}Stash pop failed:{RESET} {stash_out}")
            return

        # Default: save stash
        ok, stash_out = git_helper.stash(wf, "")
        if ok:
            out_result(f"  {GREEN}Changes stashed:{RESET} {stash_out or 'Done.'}")
        else:
            out_error(f"  {RED}Stash failed:{RESET} {stash_out}")

    def _git_revert(self, wf: str, args: list[str]) -> None:
        from cli.display import GREEN, RED, YELLOW, DIM, RESET
        from app.core import git_helper

        if not _repo_check(wf):
            return

        if not args:
            out(f"  {YELLOW}Usage: /git revert <commit-hash>{RESET}")
            return

        commit_hash = args[0]

        # Show what will be reverted
        ok, preview = git_helper.show_commit(wf, commit_hash)
        if not ok:
            out_error(f"  {RED}Cannot preview commit '{commit_hash}':{RESET} {preview}")
            return

        out("\n  Will create a revert commit undoing:\n")
        for line in preview.splitlines()[:20]:
            out(f"  {DIM}{line}{RESET}")
        out("")

        if not _confirm(
            f"  {YELLOW}Create a revert commit for {commit_hash}? [y/N]{RESET} ",
            self.cfg,
        ):
            out_status(f"  {DIM}Revert cancelled.{RESET}")
            return

        ok, revert_out = git_helper.revert(wf, commit_hash)
        if ok:
            out_result(f"  {GREEN}Reverted {commit_hash}:{RESET} {revert_out.splitlines()[0] if revert_out else 'Done.'}")
        else:
            out_error(f"  {RED}Revert failed:{RESET} {revert_out}")

    def _git_reset(self, wf: str, args: list[str]) -> None:
        """Safe reset: unstage a specific file only.

        Usage: /git reset HEAD <file>
        /git reset --hard is explicitly blocked.
        """
        from cli.display import GREEN, RED, YELLOW, DIM, RESET
        from app.core import git_helper

        if not _repo_check(wf):
            return

        # Block --hard explicitly
        if "--hard" in args:
            out_error(
                f"  {RED}Blocked:{RESET} /git reset --hard is not supported. "
                f"It permanently discards uncommitted changes and could cause data loss."
            )
            return

        # Normalise: accept "HEAD <file>" or just "<file>"
        remaining = [a for a in args if a not in ("HEAD", "--")]
        if not remaining:
            out(f"  {YELLOW}Usage: /git reset HEAD <file>  — unstage a specific file{RESET}")
            out(f"  {YELLOW}Note:  /git reset --hard is not supported (too destructive).{RESET}")
            return

        filepath = remaining[0]
        ok, reset_out = git_helper.reset_file(wf, filepath)
        if ok:
            out_result(f"  {GREEN}Unstaged:{RESET} {filepath}  {DIM}{reset_out or ''}{RESET}")
        else:
            out_error(f"  {RED}Reset failed:{RESET} {reset_out}")

    def _git_ai_commit(self, wf: str) -> None:
        """Generate a commit message via the LLM from the staged diff, then commit."""
        from cli.display import BOLD, GREEN, RED, YELLOW, DIM, CYAN, RESET
        from app.core import git_helper

        if not _repo_check(wf):
            return

        # Collect staged diff; fall back to full diff if nothing staged
        staged = git_helper.staged_diff(wf)
        if not staged or not staged.strip():
            full = git_helper.diff(wf)
            if not full or not full.strip():
                out(f"  {YELLOW}Nothing to commit — working tree is clean.{RESET}")
                return
            out_status(
                f"  {DIM}No staged changes found; using unstaged diff. "
                f"Stage files with 'git add' for a more focused message.{RESET}"
            )
            diff_text = full
        else:
            diff_text = staged

        # Truncate for LLM context (keep first 400 lines)
        lines = diff_text.splitlines()
        if len(lines) > 400:
            diff_text = "\n".join(lines[:400]) + "\n\n[diff truncated]"

        out_status(f"  {DIM}Generating commit message from diff…{RESET}")

        prompt = (
            "You are an expert software engineer writing git commit messages.\n"
            "Given the following diff, write ONE concise commit message.\n"
            "Rules:\n"
            "- First line: imperative mood, 50 chars max, no period\n"
            "- Optionally add a blank line then a short paragraph of detail (72 chars/line)\n"
            "- No bullet lists, no markdown, no preamble — just the commit message\n\n"
            f"```diff\n{diff_text}\n```\n\n"
            "Commit message:"
        )

        # Call the LLM via the configured provider (same pattern as /scaffold)
        try:
            from codex.app.llm_client import get_llm_client
            import concurrent.futures as _cf
            client = get_llm_client(self.cfg)
            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                fut = _ex.submit(client.chat, [{"role": "user", "content": prompt}])
                message = fut.result(timeout=60).strip()
        except Exception as exc:
            out_error(f"  {RED}LLM call failed:{RESET} {exc}")
            return

        if not message:
            out_error(f"  {RED}LLM returned an empty message.{RESET}")
            return

        # Show the generated message
        out(f"\n  {BOLD}Generated commit message:{RESET}\n")
        for line in message.splitlines():
            out(f"  {CYAN}{line}{RESET}")
        out("")

        try:
            choice = input(
                "  Use this message? [y/N/edit] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "n"

        if choice in ("e", "edit"):
            try:
                edited = input("  Edit message (one line; press Enter to keep): ").strip()
            except (EOFError, KeyboardInterrupt):
                edited = ""
            if edited:
                message = edited
            choice = "y"

        if choice not in ("y", "yes"):
            out_status(f"  {DIM}AI commit cancelled.{RESET}")
            return

        # Permission gate
        if not _confirm(
            f"  {YELLOW}Commit all staged/modified changes with this message? [y/N]{RESET} ",
            self.cfg,
        ):
            out_status(f"  {DIM}Commit cancelled.{RESET}")
            return

        ok, ai_commit_out = git_helper.commit(wf, message, add_all=True)
        if ok:
            first_line = ai_commit_out.splitlines()[0] if ai_commit_out else message
            out_result(f"  {GREEN}Committed: {first_line}{RESET}")
        else:
            out_error(f"  {RED}Commit failed: {ai_commit_out}{RESET}")

    # ------------------------------------------------------------------
    # /diff command (standalone, kept for backward compat)
    # ------------------------------------------------------------------

    def cmd_diff(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, print_diff_line, RESET
        wf = self.cfg.working_folder
        if not wf:
            from cli.display import YELLOW
            out_error(f"  {YELLOW}No workspace set.{RESET}")
            return
        from pathlib import Path
        if not (Path(wf) / ".git").exists():
            from cli.display import YELLOW
            out_error(f"  {YELLOW}Not a git repository: {wf}{RESET}")
            return
        cmd = ["git", "diff", "HEAD"]
        if args:
            cmd += ["--", args[0]]
        import subprocess
        try:
            r = subprocess.run(cmd, cwd=wf, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=15)
            diff_output = r.stdout or r.stderr
            if not diff_output.strip():
                out_status(f"  {DIM}No changes.{RESET}")
                return
            out(f"\n{BOLD}git diff HEAD{' -- ' + args[0] if args else ''}{RESET}")
            for line in diff_output.splitlines()[:200]:
                print_diff_line(line)
            if len(diff_output.splitlines()) > 200:
                out_status(f"  {DIM}(truncated — showing first 200 lines){RESET}")
            out("")
        except subprocess.TimeoutExpired:
            from cli.display import RED
            out_error(f"  {RED}git diff timed out.{RESET}")

    # ------------------------------------------------------------------
    # /branch command
    # ------------------------------------------------------------------

    def cmd_branch(self, args: list[str]) -> None:
        from cli.display import GREEN, RED, YELLOW, CYAN, RESET
        from app.core import git_helper

        wf = self._wf()
        if not wf:
            out_error(f"{YELLOW}No workspace set.{RESET}")
            return

        s = git_helper.status(wf)
        if not s.is_repo:
            out_error(f"{YELLOW}Not a git repository: {wf}{RESET}")
            return

        if args:
            branch_name = args[0]
        else:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            branch_name = f"ilx/task-{ts}"

        rc, sout, serr = git_helper._run(["checkout", "-b", branch_name], wf)
        if rc == 0:
            out_result(f"{GREEN}Created and switched to branch:{RESET} {CYAN}{branch_name}{RESET}")
        else:
            out_error(f"{RED}Branch creation failed:{RESET} {serr.strip() or sout.strip()}")
