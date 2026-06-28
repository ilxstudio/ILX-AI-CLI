"""Permission profile commands — /permission [profile|status|list|help]."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
from cli.display_compat import out, out_error

_log = logging.getLogger("ilx_cli.perm_cmds")

# Re-export from the canonical location so existing imports still work.
from app.core.permission_profiles import PROFILES, VALID_PROFILES  # noqa: E402


class PermCommands:
    """/permission command handler."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def cmd_permission(self, args: list[str]) -> None:
        """/permission [safe|coding|review|ci|locked|status|list|help]"""
        sub = args[0].lower() if args else "status"
        if sub in VALID_PROFILES:
            self._set_profile(sub)
            return
        dispatch = {
            "status":  self._perm_status,
            "list":    self._perm_list,
            "help":    self._perm_help,
        }
        fn = dispatch.get(sub, self._perm_help)
        fn(args[1:] if len(args) > 1 else [])

    # ── subcommands ───────────────────────────────────────────────────────

    def _set_profile(self, profile: str) -> None:
        if profile not in PROFILES:
            out_error(f"{RED}Unknown profile '{profile}'. Valid: {', '.join(VALID_PROFILES)}{RESET}")
            return
        self._cfg.permission_profile = profile
        info = PROFILES[profile]
        # Map profile to underlying PermissionMode for the existing engine
        from app.core.config import PermissionMode
        if profile == "locked":
            self._cfg.permission_mode = PermissionMode.DENY_ALL
        elif profile == "ci":
            self._cfg.permission_mode = PermissionMode.AUTO_APPROVE
        else:
            self._cfg.permission_mode = PermissionMode.ASK
        try:
            from app.core.config import ConfigManager
            ConfigManager().save(self._cfg)
        except Exception as exc:
            _log.warning("Could not persist permission profile: %s", exc)
        try:
            from app.core.audit import log_permission_change
            log_permission_change(self._cfg.permission_mode)
        except Exception:
            pass
        out(f"\n  {GREEN}Permission profile set to '{profile}'.{RESET}")
        out(f"  {DIM}{info['desc']}{RESET}")
        out(f"\n  {'Reads':<12} {self._badge(info['reads'])}")
        out(f"  {'Writes':<12} {self._badge(info['writes'])}")
        out(f"  {'Commands':<12} {self._badge(info['commands'])}")
        out(f"  {'Network':<12} {self._badge(info['network'])}\n")

    def _perm_status(self, _args: list[str]) -> None:
        profile = getattr(self._cfg, "permission_profile", "coding")
        info = PROFILES.get(profile, PROFILES["coding"])
        mode = self._cfg.permission_mode
        out(f"\n{BOLD}Permission Profile: {CYAN}{profile}{RESET}")
        out(f"  {DIM}{info['desc']}{RESET}")
        out(f"  Underlying mode:  {CYAN}{mode.value if hasattr(mode, 'value') else mode}{RESET}\n")
        out(f"  {'Category':<14} {'Behavior'}")
        out(f"  {'─' * 30}")
        for cat in ("reads", "writes", "commands", "network"):
            out(f"  {cat:<14} {self._badge(info[cat])}")
        out(f"\n  Change with: {CYAN}/permission <profile>{RESET}")
        out(f"  List options: {CYAN}/permission list{RESET}\n")

    def _perm_list(self, _args: list[str]) -> None:
        current = getattr(self._cfg, "permission_profile", "coding")
        out(f"\n{BOLD}Permission Profiles:{RESET}\n")
        for name, info in PROFILES.items():
            marker = f"{GREEN}▶{RESET}" if name == current else " "
            out(f"  {marker} {CYAN}{name:<10}{RESET} {DIM}{info['desc']}{RESET}")
            out(f"      reads={info['reads']}  writes={info['writes']}  commands={info['commands']}  network={info['network']}")
        out(f"\n  Use: {CYAN}/permission <name>{RESET} to switch\n")

    def _perm_help(self, _args: list[str]) -> None:
        out(f"\n{BOLD}/permission{RESET} — named permission profiles")
        out(f"  {CYAN}/permission status{RESET}      Show current profile and behavior")
        out(f"  {CYAN}/permission list{RESET}        List all profiles")
        out(f"  {CYAN}/permission safe{RESET}        Ask before everything")
        out(f"  {CYAN}/permission coding{RESET}      Auto-read, ask-write, ask-command (default)")
        out(f"  {CYAN}/permission review{RESET}      Read-only — no writes or commands")
        out(f"  {CYAN}/permission ci{RESET}          CI mode — auto-approve all tool use")
        out(f"  {CYAN}/permission locked{RESET}      No tool use — chat only\n")

    @staticmethod
    def _badge(behavior: str) -> str:
        if behavior == "auto":
            return f"{GREEN}auto  {RESET} {DIM}(allowed without asking){RESET}"
        if behavior == "ask":
            return f"{YELLOW}ask   {RESET} {DIM}(prompt before each action){RESET}"
        if behavior == "deny":
            return f"{RED}deny  {RESET} {DIM}(always blocked){RESET}"
        return behavior
