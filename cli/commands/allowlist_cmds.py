"""Allowlist/denylist commands — /allow and /deny for command auto-approval."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display_compat import out, out_error
from cli.display import BOLD, DIM, GREEN, YELLOW, RED, CYAN, RESET

_log = logging.getLogger("ilx_cli.allowlist_cmds")


class AllowlistCommands:
    """/allow and /deny command handlers."""

    def __init__(self, cfg: "AppConfig") -> None:
        self._cfg = cfg

    def cmd_allow(self, args: list[str]) -> None:
        """/allow command <name>  — auto-approve a command without asking"""
        if not args or args[0] in ("list", ""):
            self._show_lists()
            return
        if args[0] == "help":
            self._allow_help()
            return
        if args[0] == "command" and len(args) >= 2:
            cmd_name = args[1].strip()
            self._add_to_allowlist(cmd_name)
        elif args[0] not in ("list", "help") and len(args) >= 1:
            # shorthand: /allow pytest
            cmd_name = " ".join(args).strip()
            self._add_to_allowlist(cmd_name)
        else:
            self._allow_help()

    def cmd_deny(self, args: list[str]) -> None:
        """/deny command <name>  — always block a command"""
        if not args or args[0] in ("list", ""):
            self._show_lists()
            return
        if args[0] == "help":
            self._allow_help()
            return
        if args[0] == "command" and len(args) >= 2:
            cmd_name = args[1].strip()
            self._add_to_denylist(cmd_name)
        elif args[0] not in ("list", "help") and len(args) >= 1:
            cmd_name = " ".join(args).strip()
            self._add_to_denylist(cmd_name)
        else:
            self._allow_help()

    def cmd_allowlist(self, args: list[str]) -> None:
        """/allowlist [list|clear|remove <cmd>]"""
        sub = args[0].lower() if args else "list"
        if sub == "list":
            self._show_lists()
        elif sub == "clear":
            self._cfg.command_allowlist = []
            self._cfg.command_denylist = []
            self._save()
            out(f"  {GREEN}Allowlist and denylist cleared.{RESET}\n")
        elif sub == "remove" and len(args) >= 2:
            cmd_name = " ".join(args[1:])
            removed = False
            if cmd_name in self._cfg.command_allowlist:
                self._cfg.command_allowlist.remove(cmd_name)
                removed = True
            if cmd_name in self._cfg.command_denylist:
                self._cfg.command_denylist.remove(cmd_name)
                removed = True
            if removed:
                self._save()
                out(f"  {GREEN}Removed '{cmd_name}' from lists.{RESET}\n")
            else:
                out(f"  {YELLOW}'{cmd_name}' not found in any list.{RESET}\n")
        else:
            self._show_lists()

    # ── internals ─────────────────────────────────────────────────────────

    def _add_to_allowlist(self, cmd_name: str) -> None:
        al = self._cfg.command_allowlist
        dl = self._cfg.command_denylist
        if cmd_name in dl:
            dl.remove(cmd_name)
            out(f"  {YELLOW}Removed '{cmd_name}' from denylist.{RESET}")
        if cmd_name not in al:
            al.append(cmd_name)
            self._save()
            out(f"  {GREEN}'{cmd_name}' added to allowlist — will auto-approve without prompting.{RESET}\n")
        else:
            out(f"  {DIM}'{cmd_name}' is already in the allowlist.{RESET}\n")

    def _add_to_denylist(self, cmd_name: str) -> None:
        al = self._cfg.command_allowlist
        dl = self._cfg.command_denylist
        if cmd_name in al:
            al.remove(cmd_name)
            out(f"  {YELLOW}Removed '{cmd_name}' from allowlist.{RESET}")
        if cmd_name not in dl:
            dl.append(cmd_name)
            self._save()
            out(f"  {RED}'{cmd_name}' added to denylist — will always block.{RESET}\n")
        else:
            out(f"  {DIM}'{cmd_name}' is already in the denylist.{RESET}\n")

    def _show_lists(self) -> None:
        al = self._cfg.command_allowlist
        dl = self._cfg.command_denylist
        out(f"\n{BOLD}Command Allowlist / Denylist{RESET}")
        out(f"\n  {GREEN}Allowlist{RESET} — auto-approved commands:")
        if al:
            for cmd in al:
                out(f"    {GREEN}✓{RESET} {cmd}")
        else:
            out(f"    {DIM}(empty){RESET}")
        out(f"\n  {RED}Denylist{RESET} — always-blocked commands:")
        if dl:
            for cmd in dl:
                out(f"    {RED}✗{RESET} {cmd}")
        else:
            out(f"    {DIM}(empty){RESET}")
        out(f"\n  {CYAN}/allow <command>{RESET}    Add to allowlist")
        out(f"  {CYAN}/deny <command>{RESET}     Add to denylist")
        out(f"  {CYAN}/allowlist remove <cmd>{RESET}  Remove from list")
        out(f"  {CYAN}/allowlist clear{RESET}    Clear both lists\n")

    def _allow_help(self) -> None:
        out(f"\n{BOLD}/allow and /deny{RESET} — command auto-approval rules")
        out(f"  {CYAN}/allow pytest{RESET}           Auto-approve 'pytest' without asking")
        out(f"  {CYAN}/allow npm test{RESET}         Auto-approve 'npm test'")
        out(f"  {CYAN}/deny rm{RESET}               Always block 'rm'")
        out(f"  {CYAN}/deny git push{RESET}          Always block 'git push'")
        out(f"  {CYAN}/allowlist{RESET}              Show current lists")
        out(f"  {CYAN}/allowlist remove pytest{RESET} Remove from list\n")

    def _save(self) -> None:
        try:
            from app.core.config import ConfigManager
            ConfigManager().save(self._cfg)
        except Exception as exc:
            _log.warning("Could not persist allowlist: %s", exc)
