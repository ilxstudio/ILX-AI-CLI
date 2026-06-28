"""User tool registry — persists tool metadata across sessions."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

REGISTRY_PATH = Path.home() / ".ilx_cli" / "user_tools_registry.json"

RESERVED_COMMANDS = {
    # All built-in ILX commands — collision detection
    "chat", "code", "add", "drop", "context", "paste", "clear", "undo", "compact",
    "history", "resume", "session", "model", "provider", "params", "status",
    "temperature", "top_p", "max_tokens", "numctx", "healthcheck",
    "workspace", "rules", "init", "perms", "branch", "readme",
    "git", "diff", "run", "test", "lint", "ci", "watch", "format",
    "profile", "build", "deps", "env", "stats", "complexity", "deadcode",
    "bandit", "precommit", "metrics", "crashes", "tasks", "kill", "attach",
    "logs", "scaffold", "mcp", "diag", "help", "quit", "fetch", "convert",
    "tool", "ssh",
}


@dataclass
class UserTool:
    """Metadata for a single user-created tool."""

    name: str           # the command name (without /)
    description: str    # one-line description shown in /help
    path: str           # absolute path to the .py file
    enabled: bool = True
    version: int = 1    # incremented on each update
    created_at: str = ""
    last_run: str = ""
    generation_attempts: int = 1  # how many Reflexion attempts it took to generate


class UserToolRegistry:
    """Manages the persistent registry of user-created tools.

    Backed by ~/.ilx_cli/user_tools_registry.json.  All mutations call
    save() immediately so the registry is always consistent on disk.
    """

    def __init__(self, registry_path: Path = REGISTRY_PATH) -> None:
        self._path = registry_path
        self._tools: dict[str, UserTool] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load registry from disk.  Silent on parse errors (starts empty)."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for entry in data:
                t = UserTool(**entry)
                self._tools[t.name] = t
        except Exception:
            pass

    def save(self) -> None:
        """Persist registry to disk, creating parent dirs as needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entries = [asdict(t) for t in self._tools.values()]
        self._path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def check_name(self, name: str) -> tuple[bool, str]:
        """Validate a proposed tool name.

        Returns (valid, error_message).  Empty error string means valid.
        """
        name = name.lower().strip()
        if not re.match(r'^[a-z][a-z0-9_-]{1,29}$', name):
            return (
                False,
                "Name must be 2-30 chars, start with a letter, use only a-z 0-9 _ -",
            )
        if name in RESERVED_COMMANDS:
            return False, f"'/{name}' is a built-in command — choose a different name"
        if name in self._tools:
            return False, f"'/{name}' already exists — use /tool update {name} to modify it"
        return True, ""

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, tool: UserTool) -> None:
        """Add or replace a tool entry and persist immediately."""
        self._tools[tool.name] = tool
        self.save()

    def unregister(self, name: str) -> bool:
        """Remove a tool by name.  Returns True if it existed."""
        if name in self._tools:
            del self._tools[name]
            self.save()
            return True
        return False

    def get(self, name: str) -> UserTool | None:
        """Return the UserTool for *name*, or None if not found."""
        return self._tools.get(name)

    def update_last_run(self, name: str, timestamp: str) -> None:
        """Record the last-run timestamp for a tool and persist."""
        tool = self._tools.get(name)
        if tool is not None:
            tool.last_run = timestamp
            self.save()

    def bump_version(self, name: str) -> int:
        """Increment the version counter for *name*.  Returns new version."""
        tool = self._tools.get(name)
        if tool is None:
            return 0
        tool.version += 1
        self.save()
        return tool.version

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Enable or disable a tool.  Returns True if the tool exists."""
        tool = self._tools.get(name)
        if tool is None:
            return False
        tool.enabled = enabled
        self.save()
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_tools(self) -> list[UserTool]:
        """Return all enabled tools, sorted by name."""
        return sorted(
            (t for t in self._tools.values() if t.enabled),
            key=lambda t: t.name,
        )

    def all_tools(self) -> list[UserTool]:
        """Return all tools (enabled and disabled), sorted by name."""
        return sorted(self._tools.values(), key=lambda t: t.name)

    def is_user_command(self, name: str) -> bool:
        """Return True when *name* is a registered, enabled user tool."""
        return name in self._tools and self._tools[name].enabled

    def search(self, query: str) -> list[UserTool]:
        """Return tools whose name or description contains any query keyword.

        Keyword matching is case-insensitive.  Each word in *query* is tested
        independently; a tool matches if *any* keyword appears in its name or
        description.  Results are sorted by name.

        Example::

            registry.search("web scraper")
            # Returns tools whose name/description mentions "web" or "scraper"
        """
        keywords = [kw.lower() for kw in query.split() if kw.strip()]
        if not keywords:
            return self.all_tools()

        matches: list[UserTool] = []
        for tool in self._tools.values():
            haystack = (tool.name + " " + tool.description).lower()
            if any(kw in haystack for kw in keywords):
                matches.append(tool)

        return sorted(matches, key=lambda t: t.name)


# Module-level singleton — import and use directly
registry = UserToolRegistry()
