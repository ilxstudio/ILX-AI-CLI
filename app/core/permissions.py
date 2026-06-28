"""Console-friendly permission engine — replaces the Qt dialog version."""
from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass

from app.core import audit
from app.core.config import PermissionMode
from app.utils.file_utils import compute_diff

_log = logging.getLogger("ilx_cli.permissions")


def _check_command_lists(cmd_str: str, cfg) -> str | None:
    """Return 'allow' or 'deny' if command matches a list entry, else None."""
    if not cmd_str:
        return None
    try:
        parts = shlex.split(cmd_str)
        base = parts[0] if parts else cmd_str
    except ValueError:
        tokens = cmd_str.split()
        base = tokens[0] if tokens else cmd_str

    denylist = getattr(cfg, "command_denylist", [])
    for denied in denylist:
        if base == denied or cmd_str.startswith(denied):
            return "deny"

    allowlist = getattr(cfg, "command_allowlist", [])
    for allowed in allowlist:
        if base == allowed or cmd_str.startswith(allowed):
            return "allow"

    return None


@dataclass
class FileOperation:
    op_type:     str           # "create" | "modify" | "delete" | "execute"
    path:        str           # absolute resolved path
    old_content: str | None = None
    new_content: str | None = None
    diff:        str | None = None
    command:     list[str] | None = None


class PermissionEngine:
    def __init__(self, config):
        self._config = config

    def _apply_profile(self, kind: str) -> str | None:
        """Return 'allow', 'deny', or None (defer to mode) based on active profile."""
        try:
            from cli.commands.perm_cmds import PROFILES
            profile_name = getattr(self._config, "permission_profile", "coding")
            info = PROFILES.get(profile_name)
            if info is None:
                return None
            category_map = {
                "read":    "reads",
                "write":   "writes",
                "execute": "commands",
                "network": "network",
                "command": "commands",
            }
            cat = category_map.get(kind.lower(), "reads")
            behavior = info.get(cat, "ask")
            if behavior == "auto":
                return "allow"
            if behavior == "deny":
                return "deny"
            return None  # "ask" — defer to mode
        except Exception:
            return None

    def _warn_sandbox_escape(self, target: str) -> None:
        """Log a warning if a command target may access paths outside the workspace."""
        wf = getattr(self._config, "working_folder", "")
        if wf and target and not target.startswith(wf):
            _log.warning(
                "sandbox: permitted command may access paths outside workspace '%s': %s",
                wf, target[:80],
            )

    def request_permission(self, operation: FileOperation) -> bool:
        mode = self._config.permission_mode
        kind = operation.op_type if operation.op_type in (
            "create", "modify", "delete", "execute"
        ) else "write"
        if kind in ("create", "modify"):
            kind = "write"
        target = (
            " ".join(operation.command) if operation.command else operation.path
        )
        mode_label = mode.value if hasattr(mode, "value") else str(mode)

        # Allowlist / denylist check for execute-kind operations
        if kind in ("execute", "command") or operation.command:
            list_decision = _check_command_lists(target, self._config)
            if list_decision == "deny":
                audit.log_permission_decision(
                    kind=kind, target=target, decision="denied",
                    mode=mode_label, source="permission_engine", detail="denylist",
                )
                return False
            if list_decision == "allow":
                audit.log_permission_decision(
                    kind=kind, target=target, decision="allowed",
                    mode=mode_label, source="permission_engine", detail="allowlist",
                )
                return True

        # Sandbox mode enforcement
        if kind in ("execute", "command") or operation.command:
            sandbox = getattr(self._config, "sandbox_mode", "workspace")
            if sandbox == "read_only":
                audit.log_permission_decision(
                    kind=kind, target=target, decision="denied",
                    mode=mode_label, source="permission_engine", detail="sandbox_read_only",
                )
                return False
            # "workspace" and "disabled" fall through to normal permission flow

        # Profile-aware decision — takes priority over raw mode
        profile_decision = self._apply_profile(kind)
        if profile_decision == "allow":
            audit.log_permission_decision(
                kind=kind, target=target, decision="allowed",
                mode=mode_label, source="permission_engine", detail="profile_auto",
            )
            return True
        if profile_decision == "deny":
            audit.log_permission_decision(
                kind=kind, target=target, decision="denied",
                mode=mode_label, source="permission_engine", detail="profile_deny",
            )
            return False

        if mode == PermissionMode.DENY_ALL:
            audit.log_permission_decision(
                kind=kind, target=target, decision="denied",
                mode=mode_label, source="permission_engine", detail="deny_all",
            )
            return False

        if mode == PermissionMode.AUTO_APPROVE:
            audit.log_permission_decision(
                kind=kind, target=target, decision="allowed",
                mode=mode_label, source="permission_engine", detail="auto_approve",
            )
            if kind in ("execute", "command") or operation.command:
                self._warn_sandbox_escape(target)
            return True

        # ASK mode — prompt on console
        if operation.command:
            prompt_msg = f"\n[PERMISSION] Run command: {' '.join(operation.command)}\nAllow? [y/N] "
        else:
            diff_preview = ""
            if operation.new_content is not None and operation.old_content is not None:
                diff_preview = compute_diff(
                    operation.old_content, operation.new_content, operation.path
                )
            elif operation.new_content is not None:
                lines = operation.new_content.splitlines()[:10]
                diff_preview = "\n".join(f"+ {l}" for l in lines)
                if len(operation.new_content.splitlines()) > 10:
                    diff_preview += f"\n... ({len(operation.new_content.splitlines()) - 10} more lines)"
            prompt_msg = f"\n[PERMISSION] {kind.upper()}: {target}"
            if diff_preview:
                print(diff_preview)
            prompt_msg += "\nAllow? [y/N] "

        try:
            answer = input(prompt_msg).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        granted = answer in ("y", "yes")
        audit.log_permission_decision(
            kind=kind, target=target,
            decision="allowed" if granted else "denied",
            mode=mode_label, source="permission_engine", detail="console_ask",
        )
        return granted


def confirm(prompt: str, cfg) -> bool:
    """Use instead of bare input() everywhere. Respects auto_yes and dry_run."""
    if getattr(cfg, "auto_yes", False):
        return True
    if getattr(cfg, "dry_run", False):
        print(f"[dry-run] Would prompt: {prompt}")
        return False
    try:
        return input(f"{prompt} [y/N]: ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt, OSError):
        return False
