"""Sandbox commands — /sandbox [status|workspace|read-only|off]."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RESET, YELLOW
from cli.display_compat import out

_log = logging.getLogger("ilx_cli.sandbox_cmds")

SANDBOX_MODES = {
    "workspace": "Writes/reads contained to working_folder only",
    "read-only": "No writes anywhere — reads outside workspace allowed",
    "off":       "No sandbox — DANGEROUS, use only with --i-understand",
}


class SandboxCommands:
    """/sandbox command handler."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def cmd_sandbox(self, args: list[str]) -> None:
        """/sandbox [status|workspace|read-only|off --i-understand]"""
        sub = args[0].lower() if args else "status"
        dispatch = {
            "status":    self._sandbox_status,
            "workspace": lambda _: self._set_mode("workspace"),
            "read-only": lambda _: self._set_mode("read-only"),
            "off":       self._sandbox_off,
            "help":      self._sandbox_help,
        }
        fn = dispatch.get(sub, self._sandbox_help)
        fn(args[1:] if len(args) > 1 else [])

    # ── subcommands ───────────────────────────────────────────────────────

    def _sandbox_status(self, _args: list[str]) -> None:
        mode = getattr(self._cfg, "sandbox_mode", "workspace")
        wf = self._cfg.working_folder or "(not set)"
        out(f"\n{BOLD}Sandbox Status{RESET}")
        out(f"  Mode:             {CYAN}{mode}{RESET}")
        out(f"  Description:      {DIM}{SANDBOX_MODES.get(mode, mode)}{RESET}")
        out(f"  Working folder:   {DIM}{wf}{RESET}")
        out("")
        for m, desc in SANDBOX_MODES.items():
            marker = f"{GREEN}▶{RESET}" if m == mode else " "
            out(f"  {marker} {CYAN}{m:<14}{RESET} {DIM}{desc}{RESET}")
        out(
            f"\n  Change: {CYAN}/sandbox workspace{RESET}"
            f"  |  {CYAN}/sandbox read-only{RESET}"
            f"  |  {CYAN}/sandbox off --i-understand{RESET}\n"
        )

    def _set_mode(self, mode: str) -> None:
        self._cfg.sandbox_mode = mode
        try:
            from app.core.config import ConfigManager
            ConfigManager().save(self._cfg)
        except Exception as exc:
            _log.warning("Could not persist sandbox mode: %s", exc)
        try:
            from app.core.audit import log_event
            log_event("sandbox_mode_changed", mode=mode)
        except Exception:
            pass
        out(f"  {GREEN}Sandbox mode set to '{mode}'.{RESET}")
        out(f"  {DIM}{SANDBOX_MODES.get(mode, mode)}{RESET}\n")

    def _sandbox_off(self, args: list[str]) -> None:
        if "--i-understand" not in args:
            out(f"\n  {YELLOW}Warning:{RESET} Disabling the sandbox removes all path containment.")
            out("  The AI can read and write anywhere on your filesystem.")
            out(f"  To confirm: {CYAN}/sandbox off --i-understand{RESET}\n")
            return
        self._set_mode("disabled")
        out(f"  {YELLOW}Sandbox disabled. The AI has full filesystem access.{RESET}")
        out(f"  Re-enable: {CYAN}/sandbox workspace{RESET}\n")

    def _sandbox_help(self, _args: list[str]) -> None:
        out(f"\n{BOLD}/sandbox{RESET} — control filesystem access boundaries")
        out(f"  {CYAN}/sandbox status{RESET}                  Show current mode")
        out(f"  {CYAN}/sandbox workspace{RESET}               Contain all writes to working_folder (default)")
        out(f"  {CYAN}/sandbox read-only{RESET}               No writes anywhere")
        out(f"  {CYAN}/sandbox off --i-understand{RESET}      Disable sandbox (requires explicit consent)\n")
