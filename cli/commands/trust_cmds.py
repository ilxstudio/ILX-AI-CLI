"""Trust commands -- /free shows privacy/trust status to skeptical users."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display_compat import out, out_error, out_status
from cli.display import BOLD, DIM, GREEN, YELLOW, RED, CYAN, RESET

_log = logging.getLogger("ilx_cli.trust_cmds")

_AUDIT_LOG = Path.home() / ".ilx_cli" / "logs" / "audit.log"

_OK  = "[ok]"
_NO  = "[no]"


class TrustCommands:
    """/free command handler."""

    def __init__(self, cfg: "AppConfig") -> None:
        self._cfg = cfg

    def cmd_free(self, args: list[str]) -> None:
        """/free [status|calls|export]"""
        sub = args[0].lower() if args else "status"
        dispatch = {
            "status":  self._free_status,
            "calls":   self._free_calls,
            "export":  self._free_export,
        }
        fn = dispatch.get(sub, self._free_status)
        fn(args[1:] if len(args) > 1 else [])

    # -- subcommands ----------------------------------------------------------

    def _free_status(self, _args: list[str]) -> None:
        cfg = self._cfg
        provider = cfg.provider
        has_key = self._has_api_key(provider)
        strategy = getattr(cfg, "route_strategy", "auto")

        out(f"\n{BOLD}ILX AI -- Privacy & Trust{RESET}")
        out(f"  {GREEN}{_OK}{RESET} {BOLD}No telemetry{RESET}           Zero usage data sent to ILX Studio")
        out(f"  {GREEN}{_OK}{RESET} {BOLD}No subscription{RESET}        Free forever -- no account required")
        out(f"  {GREEN}{_OK}{RESET} {BOLD}No vendor lock-in{RESET}      All config in ~/.ilx_cli -- portable")
        out(f"  {GREEN}{_OK}{RESET} {BOLD}Local models{RESET}            Ollama supported -- fully offline")
        out(f"  {GREEN}{_OK}{RESET} {BOLD}BYO keys optional{RESET}      Cloud APIs only if you configure them")
        out(f"  {GREEN}{_OK}{RESET} {BOLD}Open source{RESET}             MIT License -- audit the code yourself")
        out("")
        out(f"{BOLD}Current session:{RESET}")
        out(f"  Provider:         {CYAN}{provider}{RESET}")
        if has_key:
            out(f"  Cloud key loaded: {GREEN}yes{RESET}")
        else:
            out(f"  Cloud key loaded: {DIM}no{RESET}")
        out(f"  Route strategy:   {CYAN}{strategy}{RESET}")
        out(f"  Sandbox mode:     {CYAN}{getattr(cfg, 'sandbox_mode', 'workspace')}{RESET}")
        pmode = cfg.permission_mode.value if hasattr(cfg.permission_mode, "value") else cfg.permission_mode
        out(f"  Permission mode:  {CYAN}{pmode}{RESET}")
        out("")
        # Network calls this session from audit log
        calls = self._count_session_calls()
        out(f"{BOLD}Network calls this session:{RESET}")
        if calls:
            for event_type, count in calls.items():
                out(f"  {CYAN}{event_type:<16}{RESET} {count} call(s)")
        else:
            out(f"  {DIM}No network calls recorded yet{RESET}")
        out("")
        out(f"{BOLD}Audit log:{RESET}  {DIM}{_AUDIT_LOG}{RESET}")
        out(f"  Use {CYAN}/free calls{RESET} to see recent network calls in detail.")
        out(f"  Use {CYAN}/free export{RESET} to export a full session audit.\n")

    def _free_calls(self, _args: list[str]) -> None:
        """Show recent network calls from the audit log."""
        records = self._load_recent_records(limit=50)
        network_records = [
            r for r in records
            if r.get("event") in ("llm_call", "egress", "mcp_call")
        ]
        out(f"\n{BOLD}Recent network calls:{RESET}")
        if not network_records:
            out(f"  {DIM}No network calls in recent audit log.{RESET}\n")
            return
        for r in network_records[-20:]:
            event = r.get("event", "?")
            ts = r.get("ts", "")[:19]
            if event == "llm_call":
                provider = r.get("provider", "?")
                model = r.get("model", "?")
                tokens = r.get("total_tokens", 0)
                out(f"  {DIM}{ts}{RESET}  {CYAN}llm_call{RESET}   {provider}/{model}  {tokens} tokens")
            elif event == "egress":
                url = r.get("url", "?")[:60]
                method = r.get("method", "GET")
                status = r.get("status", "?")
                out(f"  {DIM}{ts}{RESET}  {CYAN}egress{RESET}     {method} {url}  [{status}]")
            elif event == "mcp_call":
                tool = r.get("tool", "?")
                out(f"  {DIM}{ts}{RESET}  {CYAN}mcp_call{RESET}   {tool}")
        out("")

    def _free_export(self, _args: list[str]) -> None:
        """Export current session audit log to stdout as JSON."""
        records = self._load_recent_records(limit=500)
        out(json.dumps(records, indent=2))

    # -- helpers --------------------------------------------------------------

    def _has_api_key(self, provider: str) -> bool:
        try:
            import keyring
            key = keyring.get_password("ilx_ai_cli", f"{provider}_api_key")
            return bool(key)
        except Exception:
            return False

    def _count_session_calls(self) -> dict[str, int]:
        records = self._load_recent_records(limit=200)
        counts: dict[str, int] = {}
        for r in records:
            e = r.get("event", "")
            if e in ("llm_call", "egress", "mcp_call"):
                counts[e] = counts.get(e, 0) + 1
        return counts

    def _load_recent_records(self, limit: int = 100) -> list[dict]:
        if not _AUDIT_LOG.exists():
            return []
        try:
            lines = _AUDIT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            records = []
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return records
        except OSError as exc:
            _log.debug("Cannot read audit log: %s", exc)
            return []
