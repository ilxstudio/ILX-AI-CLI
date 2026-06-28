"""Command registry — maps slash commands to handler callables.

Supports exact-match lookup and unique-prefix abbreviation.
E.g. '/rev' resolves to '/review' when no other command starts with 'rev'.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

_log = logging.getLogger("ilx_cli.command_registry")


class CommandRegistry:
    """Maps slash commands to callables with prefix-match abbreviation support."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[list[str]], bool | None]] = {}

    def register(self, name: str, handler: Callable[[list[str]], bool | None]) -> None:
        """Register *handler* for the exact command *name* (include the leading slash)."""
        self._handlers[name.lower()] = handler

    def register_many(
        self,
        names: list[str],
        handler: Callable[[list[str]], bool | None],
    ) -> None:
        """Register *handler* for every name in *names*."""
        for name in names:
            self.register(name, handler)

    def lookup(self, cmd: str) -> Callable[[list[str]], bool | None] | None:
        """Return the handler for *cmd*, or None if not found / ambiguous.

        Resolution order:
        1. Exact match (fast path).
        2. Unique prefix match — only resolves if exactly one registered command
           starts with *cmd*.  Ambiguous prefixes return None.
        """
        cmd_lower = cmd.lower()
        if cmd_lower in self._handlers:
            return self._handlers[cmd_lower]
        matches = [k for k in self._handlers if k.startswith(cmd_lower)]
        if len(matches) == 1:
            _log.debug("prefix expand: '%s' → '%s'", cmd, matches[0])
            return self._handlers[matches[0]]
        if len(matches) > 1:
            _log.debug("ambiguous prefix '%s' matches: %s", cmd, matches)
        return None

    def all_commands(self) -> list[str]:
        """Return sorted list of all registered command names."""
        return sorted(self._handlers.keys())
