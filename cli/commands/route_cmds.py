"""Route commands — /route [strategy|status|explain|reset]."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET
from cli.display_compat import out, out_error

_log = logging.getLogger("ilx_cli.route_cmds")

STRATEGY_DESCRIPTIONS = {
    "auto":       "ILX picks best available model per task (local → free → paid)",
    "free-only":  "Local Ollama + free-tier cloud only — never charges paid API",
    "local-only": "Ollama only — fully offline, no network calls to cloud",
    "quality":    "Always use highest-capability configured provider",
}


class RouteCommands:
    """/route command handler."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def cmd_route(self, args: list[str]) -> None:
        """/route [auto|free-only|local-only|quality|status|explain|reset]"""
        sub = args[0].lower() if args else "status"
        dispatch = {
            "status":     self._route_status,
            "explain":    self._route_explain,
            "reset":      self._route_reset,
            "auto":       lambda _: self._set_strategy("auto"),
            "free-only":  lambda _: self._set_strategy("free-only"),
            "local-only": lambda _: self._set_strategy("local-only"),
            "quality":    lambda _: self._set_strategy("quality"),
            "help":       self._route_help,
        }
        fn = dispatch.get(sub, self._route_help)
        fn(args[1:] if len(args) > 1 else [])

    # ── subcommands ───────────────────────────────────────────────────────

    def _route_status(self, _args: list[str]) -> None:
        from app.core.router import STRATEGIES
        strategy = getattr(self._cfg, "route_strategy", "auto")
        out(f"\n{BOLD}Model Routing Status{RESET}")
        out(f"  Current strategy:  {CYAN}{strategy}{RESET}")
        out(f"  Description:       {DIM}{STRATEGY_DESCRIPTIONS.get(strategy, '')}{RESET}")
        out("\n  Available strategies:")
        for s in STRATEGIES:
            marker = f"  {GREEN}▶{RESET}" if s == strategy else "   "
            out(f"{marker} {CYAN}{s:<14}{RESET} {DIM}{STRATEGY_DESCRIPTIONS[s]}{RESET}")
        out(f"\n  Use {BOLD}/route <strategy>{RESET} to change.\n")

    def _route_explain(self, _args: list[str]) -> None:
        from app.core.router import ModelRouter
        router = ModelRouter(self._cfg)
        out(f"\n{BOLD}Routing Table{RESET} — what model runs each task type:")
        for line in router.explain():
            out(line)
        out("")

    def _set_strategy(self, strategy: str) -> None:
        from app.core.config import ConfigManager
        from app.core.router import STRATEGIES
        if strategy not in STRATEGIES:
            out_error(f"{RED}Unknown strategy '{strategy}'. Valid: {', '.join(STRATEGIES)}{RESET}")
            return
        self._cfg.route_strategy = strategy
        try:
            ConfigManager().save(self._cfg)
        except Exception as exc:
            _log.warning("Could not persist route strategy: %s", exc)
        out(f"  {GREEN}Route strategy set to '{strategy}'.{RESET}")
        out(f"  {DIM}{STRATEGY_DESCRIPTIONS[strategy]}{RESET}\n")

    def _route_reset(self, _args: list[str]) -> None:
        self._set_strategy("auto")

    def _route_help(self, _args: list[str]) -> None:
        out(f"\n{BOLD}/route{RESET} — configure model routing strategy")
        out(f"  {CYAN}/route status{RESET}        Show current strategy and all options")
        out(f"  {CYAN}/route explain{RESET}       Show which model runs each task type")
        out(f"  {CYAN}/route auto{RESET}          Best available: local → free → paid")
        out(f"  {CYAN}/route free-only{RESET}     Local Ollama + free-tier cloud only")
        out(f"  {CYAN}/route local-only{RESET}    Ollama only — fully offline")
        out(f"  {CYAN}/route quality{RESET}       Highest-capability available provider")
        out(f"  {CYAN}/route reset{RESET}         Reset to 'auto'\n")
