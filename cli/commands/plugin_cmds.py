# MIT License 2026 ILX Studio
"""Plugin listing command — /plugins."""
from __future__ import annotations

import json as _json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RESET
from cli.display_compat import out


def cmd_plugins(args: list[str], cfg: AppConfig) -> None:
    """/plugins — list all loaded plugins (name, version, description, commands)."""
    from app.core.plugin_base import PluginRegistry

    registry = PluginRegistry()
    registry.discover()
    plugins = registry.all()

    want_json = "--json" in args

    if not plugins:
        if want_json:
            sys.stdout.write(_json.dumps({"plugins": [], "count": 0}) + "\n")
        else:
            out(f"\n  {DIM}No plugins loaded.{RESET}")
            out(f"\n  To install a plugin, add it to the {CYAN}ilx_ai.plugins{RESET} entry-point group:")
            out(f"  {DIM}[project.entry-points.\"ilx_ai.plugins\"]")
            out(f"  my_plugin = \"my_package:MyPlugin\"{RESET}\n")
        return

    if want_json:
        payload = [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "commands": list(p.get_commands().keys()),
            }
            for p in plugins
        ]
        sys.stdout.write(_json.dumps({"plugins": payload, "count": len(payload)}) + "\n")
        return

    out(f"\n{BOLD}Loaded plugins ({len(plugins)}){RESET}")
    for p in plugins:
        cmds = list(p.get_commands().keys())
        cmd_str = (", ".join(f"/{c}" for c in cmds)) if cmds else DIM + "(no commands)" + RESET
        out(f"  {GREEN}{p.name}{RESET}  v{p.version}  — {p.description or '(no description)'}")
        if cmds:
            out(f"    {DIM}Commands: {cmd_str}{RESET}")
    out("")
