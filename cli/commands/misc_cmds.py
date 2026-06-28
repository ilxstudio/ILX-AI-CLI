"""Miscellaneous command helpers — /version, /export, /alias, /copy.

These are thin wrappers kept out of cli/app.py to stay under the 700-line
limit; they take all the state they need as arguments rather than living as
ILXApp methods.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig


def cmd_version(cfg: "AppConfig") -> None:
    """Show ILX AI CLI version, Python info, platform, and active provider/model."""
    import sys
    import platform
    from cli.display import BOLD, CYAN, DIM, RESET, GREEN
    from app.version import VERSION

    print(f"\n{BOLD}ILX AI CLI{RESET}  {CYAN}v{VERSION}{RESET}")
    print(f"  {DIM}Python     {RESET}{sys.version.split()[0]}  ({sys.executable})")
    print(f"  {DIM}Platform   {RESET}{platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  {DIM}Provider   {RESET}{GREEN}{cfg.provider}{RESET}")
    print(f"  {DIM}Model      {RESET}{cfg.ollama_model}")
    if cfg.chat_model:
        print(f"  {DIM}Chat model {RESET}{cfg.chat_model}")
    print()


def cmd_export(cfg: "AppConfig", history: list[dict], args: list[str]) -> None:
    """Export current conversation history to a Markdown file."""
    from datetime import datetime
    from cli.display import DIM, GREEN, YELLOW, RESET

    if not history:
        print(f"  {YELLOW}Nothing to export — conversation history is empty.{RESET}")
        return

    date_str  = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args:
        out_path = Path(args[0])
    else:
        workspace = cfg.working_folder or str(Path.home() / "Documents")
        out_path = Path(workspace) / f"ilx_session_{timestamp}.md"

    lines: list[str] = [f"# ILX AI Session — {date_str}\n"]
    role_map = {"user": "You", "assistant": "ILX AI", "system": "System"}
    for msg in history:
        role    = msg.get("role", "unknown")
        label   = role_map.get(role, role.title())
        content = msg.get("content", "").strip()
        lines.append(f"## {label}\n\n{content}\n")

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  {GREEN}Exported {len(history)} messages to:{RESET}  {DIM}{out_path}{RESET}")
    except OSError as exc:
        print(f"  {YELLOW}Export failed: {exc}{RESET}")


def cmd_alias(alias_store, args: list[str]) -> None:
    """/alias [list | <name> <command> | remove <name>]"""
    from cli.display import BOLD, CYAN, DIM, GREEN, YELLOW, RESET

    if not args or args[0].lower() == "list":
        aliases = alias_store.all()
        if not aliases:
            print(f"  {DIM}No aliases defined. Use /alias <name> <command> to add one.{RESET}")
        else:
            print(f"\n{BOLD}Aliases:{RESET}")
            for name, cmd in sorted(aliases.items()):
                print(f"  {CYAN}/{name}{RESET}  →  {DIM}{cmd}{RESET}")
            print()
        return

    if args[0].lower() == "remove" and len(args) >= 2:
        name = args[1].lstrip("/")
        if alias_store.remove(name):
            print(f"  {GREEN}Alias '/{name}' removed.{RESET}")
        else:
            print(f"  {YELLOW}No alias named '/{name}'.{RESET}")
        return

    if len(args) >= 2:
        name    = args[0].lstrip("/")
        command = " ".join(args[1:])
        if not command.startswith("/"):
            command = "/" + command
        alias_store.set(name, command)
        print(f"  {GREEN}Alias set:{RESET}  {CYAN}/{name}{RESET}  →  {DIM}{command}{RESET}")
        return

    print(f"  {YELLOW}Usage: /alias list | /alias <name> <command> | /alias remove <name>{RESET}")


def cmd_copy(history: list[dict]) -> None:
    """Copy the last AI response to the clipboard."""
    from cli.display import DIM, GREEN, YELLOW, RESET

    last_ai = next(
        (m["content"] for m in reversed(history) if m.get("role") == "assistant"),
        None,
    )
    if not last_ai:
        print(f"  {YELLOW}No AI response in history to copy.{RESET}")
        return
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(last_ai)
        preview = last_ai[:80].replace("\n", " ")
        print(
            f"  {GREEN}Copied to clipboard.{RESET}  {DIM}{preview}{'…' if len(last_ai) > 80 else ''}{RESET}"
        )
    except ImportError:
        print(
            f"  {YELLOW}pyperclip not installed — run: pip install pyperclip{RESET}\n"
            f"  {DIM}Last response ({len(last_ai)} chars):{RESET}\n{last_ai}"
        )
    except Exception as exc:
        print(f"  {YELLOW}Could not copy to clipboard: {exc}{RESET}")
