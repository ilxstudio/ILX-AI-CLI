"""Helper utilities for ILXApp — readline setup, alias store, and input reader.

Split from cli/app.py to keep that file under 700 lines.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger("ilx_cli.app_helpers")


# ---------------------------------------------------------------------------
# Readline / prompt_toolkit setup — graceful degradation
# ---------------------------------------------------------------------------

def setup_readline(commands: list[str]) -> None:
    """Configure readline or pyreadline3 for history + tab completion."""
    try:
        import readline  # type: ignore  # Unix only
    except ImportError:
        try:
            import pyreadline3 as readline  # type: ignore  # Windows fallback
        except ImportError:
            return  # No history support available — silent fallback

    # History file
    history_file = Path.home() / ".ilx_cli" / "history"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        readline.read_history_file(str(history_file))
    except (FileNotFoundError, OSError):
        pass
    readline.set_history_length(500)

    import atexit
    atexit.register(lambda: _save_history(readline, history_file))

    # Tab completion for slash commands
    def _completer(text: str, state: int) -> str | None:
        options = [c for c in commands if c.startswith(text)]
        return options[state] if state < len(options) else None

    readline.set_completer(_completer)
    readline.parse_and_bind(
        "tab: complete" if hasattr(readline, "parse_and_bind") else ""
    )


def _save_history(readline, history_file: Path) -> None:
    try:
        readline.write_history_file(str(history_file))
    except (OSError, AttributeError):
        pass


def read_input(prompt: str) -> str:
    """Read a line of input with backslash-continuation support."""
    try:
        line = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    if not line:
        return ""
    if line.endswith("\\"):
        parts = [line.rstrip("\\")]
        limit = 200
        while len(parts) < limit:
            try:
                cont = input("... ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not cont:
                break
            parts.append(cont)
        return "\n".join(parts)
    return line


# ---------------------------------------------------------------------------
# Alias store — persists to ~/.ilx_cli/aliases.json
# ---------------------------------------------------------------------------

class AliasStore:
    """Simple JSON-backed alias registry."""

    def __init__(self) -> None:
        self._path = Path.home() / ".ilx_cli" / "aliases.json"
        self._aliases: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._aliases, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def get(self, name: str) -> str | None:
        return self._aliases.get(name)

    def set(self, name: str, command: str) -> None:
        self._aliases[name] = command
        self._save()

    def remove(self, name: str) -> bool:
        if name in self._aliases:
            del self._aliases[name]
            self._save()
            return True
        return False

    def all(self) -> dict[str, str]:
        return dict(self._aliases)
