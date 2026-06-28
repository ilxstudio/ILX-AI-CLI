# MIT License 2026 ILX Studio
"""Prompt template commands — /template list|add|remove|show|use."""
from __future__ import annotations

import re
import string
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
from cli.display_compat import out, out_error

_TEMPLATES_DIR = Path.home() / ".ilx_cli" / "templates"
_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{2,30}$")


def _ensure_dir() -> Path:
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return _TEMPLATES_DIR


def _template_path(name: str) -> Path:
    return _TEMPLATES_DIR / f"{name}.txt"


def _valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


def cmd_template(args: list[str], cfg: AppConfig) -> None:
    """/template list|add <name> <text>|remove <name>|show <name>|use <name> [var=val ...]"""
    sub = args[0].lower() if args else "list"
    rest = args[1:]

    dispatch = {
        "list":   _tpl_list,
        "add":    _tpl_add,
        "remove": _tpl_remove,
        "show":   _tpl_show,
        "use":    _tpl_use,
        "help":   _tpl_help,
    }
    fn = dispatch.get(sub, _tpl_help)
    fn(rest)


# ── subcommands ────────────────────────────────────────────────────────────────

def _tpl_list(_args: list[str]) -> None:
    d = _ensure_dir()
    files = sorted(d.glob("*.txt"))
    if not files:
        out(f"  {YELLOW}No templates saved.{RESET}  Add one: {CYAN}/template add <name> <text>{RESET}\n")
        return
    out(f"\n{BOLD}Saved templates:{RESET}")
    for f in files:
        name = f.stem
        try:
            first_line = f.read_text(encoding="utf-8").splitlines()[0][:72]
        except OSError:
            first_line = "(unreadable)"
        out(f"  {CYAN}{name:<20}{RESET} {DIM}{first_line}{RESET}")
    out("")


def _tpl_add(args: list[str]) -> None:
    if len(args) < 2:
        out(f"  {YELLOW}Usage: /template add <name> <text>{RESET}\n")
        return
    name, *text_parts = args
    if not _valid_name(name):
        out_error(f"  {RED}Invalid name '{name}'. Use 2-30 alphanumeric/underscore chars.{RESET}\n")
        return
    text = " ".join(text_parts)
    d = _ensure_dir()
    _template_path(name).write_text(text, encoding="utf-8")
    out(f"  {GREEN}[ok]{RESET} Template '{name}' saved.\n")


def _tpl_remove(args: list[str]) -> None:
    if not args:
        out(f"  {YELLOW}Usage: /template remove <name>{RESET}\n")
        return
    name = args[0]
    p = _template_path(name)
    if not p.exists():
        out_error(f"  {RED}Template '{name}' not found.{RESET}\n")
        return
    p.unlink()
    out(f"  {GREEN}[ok]{RESET} Template '{name}' removed.\n")


def _tpl_show(args: list[str]) -> None:
    if not args:
        out(f"  {YELLOW}Usage: /template show <name>{RESET}\n")
        return
    name = args[0]
    p = _template_path(name)
    if not p.exists():
        out_error(f"  {RED}Template '{name}' not found.{RESET}\n")
        return
    out(f"\n{BOLD}Template: {name}{RESET}")
    out(p.read_text(encoding="utf-8"))
    out("")


def _tpl_use(args: list[str]) -> None:
    """Use a template, substituting $var / ${var} placeholders with var=val pairs."""
    if not args:
        out(f"  {YELLOW}Usage: /template use <name> [var=val ...]{RESET}\n")
        return
    name = args[0]
    p = _template_path(name)
    if not p.exists():
        out_error(f"  {RED}Template '{name}' not found.{RESET}\n")
        return
    # Parse var=val pairs
    subs: dict[str, str] = {}
    for token in args[1:]:
        if "=" in token:
            k, _, v = token.partition("=")
            subs[k.strip()] = v.strip()
    raw = p.read_text(encoding="utf-8")
    result = string.Template(raw).safe_substitute(subs)
    out(f"\n{result}\n")


def _tpl_help(_args: list[str]) -> None:
    out(f"\n{BOLD}/template{RESET} -- manage reusable prompt templates")
    out(f"  {CYAN}/template list{RESET}                    List all saved templates")
    out(f"  {CYAN}/template add <name> <text>{RESET}        Save a new template")
    out(f"  {CYAN}/template remove <name>{RESET}            Delete a template")
    out(f"  {CYAN}/template show <name>{RESET}              Display template content")
    out(f"  {CYAN}/template use <name> [var=val]{RESET}     Render template with substitutions")
    out(f"\n  {DIM}Variables use $var or ${{var}} syntax (Python string.Template).{RESET}\n")
