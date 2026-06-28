"""Shell completion script generator — /completions command.

Generates bash and zsh completion scripts for the ilx CLI.
Scripts are written to ~/.ilx_cli/completions/ and instructions
are printed so the user knows how to activate them.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig


_BASH_TEMPLATE = """\
# ILX AI CLI — bash tab completion
# Source this file in your ~/.bashrc:
#   source ~/.ilx_cli/completions/ilx.bash

_ilx_completions() {{
    local cur="${{COMP_WORDS[COMP_CWORD]}}"
    local commands="{commands}"
    COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
    return 0
}}

complete -F _ilx_completions ilx
"""

_ZSH_TEMPLATE = """\
#compdef ilx
# ILX AI CLI — zsh tab completion
# Place this file in a directory on your $fpath, e.g.:
#   mkdir -p ~/.zfunc && cp ~/.ilx_cli/completions/ilx.zsh ~/.zfunc/_ilx
#   echo 'fpath=(~/.zfunc $fpath)' >> ~/.zshrc
#   echo 'autoload -Uz compinit && compinit' >> ~/.zshrc

_ilx() {{
    local -a commands
    commands=(
{zsh_commands}
    )
    _describe 'ilx command' commands
}}

_ilx "$@"
"""


def _get_all_commands() -> list[str]:
    """Return all registered slash commands from the registry."""
    try:
        from cli.app import ILXApp  # noqa: F401 — triggers registration side-effects
    except Exception:
        pass
    try:
        # Walk all known command lists from the app's registered handlers.
        # Fall back to a hard-coded set if the registry isn't populated yet.
        import sys
        for mod_name, mod in list(sys.modules.items()):
            if hasattr(mod, "_REGISTRY"):
                reg = mod._REGISTRY
                if hasattr(reg, "all_commands"):
                    cmds = reg.all_commands()
                    if cmds:
                        return cmds
    except Exception:
        pass
    # Static fallback — covers all standard commands
    return sorted([
        "/alias", "/attach", "/benchmark", "/build", "/chat", "/ci",
        "/clear", "/code", "/completions", "/context", "/copy", "/crashes",
        "/deps", "/diff", "/edit", "/env", "/export", "/format", "/git",
        "/help", "/history", "/kill", "/lint", "/logs", "/model", "/perms",
        "/profile", "/provider", "/review", "/route", "/run", "/search",
        "/setup", "/shell", "/stats", "/tasks", "/test", "/timings",
        "/tokens", "/version", "/watch", "/workspace",
    ])


def cmd_completions(args: list[str], cfg: AppConfig) -> None:
    """/completions — generate bash/zsh completion scripts for ilx."""
    from cli.display import BOLD, CYAN, DIM, GREEN, RESET, YELLOW

    save = "--save" not in args or True  # always save; --print to stdout only
    print_only = "--print" in args

    commands = _get_all_commands()
    cmd_str = " ".join(commands)

    # Build zsh command list (one per line, quoted)
    zsh_lines = "\n".join(f"        '{c}:ILX command'" for c in commands)

    bash_script = _BASH_TEMPLATE.format(commands=cmd_str)
    zsh_script  = _ZSH_TEMPLATE.format(zsh_commands=zsh_lines)

    if print_only:
        print(f"\n{BOLD}# --- bash ---{RESET}")
        print(bash_script)
        print(f"\n{BOLD}# --- zsh ---{RESET}")
        print(zsh_script)
        return

    # Write to ~/.ilx_cli/completions/
    comp_dir = Path.home() / ".ilx_cli" / "completions"
    try:
        comp_dir.mkdir(parents=True, exist_ok=True)
        bash_path = comp_dir / "ilx.bash"
        zsh_path  = comp_dir / "ilx.zsh"
        bash_path.write_text(bash_script, encoding="utf-8")
        zsh_path.write_text(zsh_script,  encoding="utf-8")
    except OSError as exc:
        print(f"  {YELLOW}Could not write completion files: {exc}{RESET}")
        return

    print(f"\n{BOLD}Completion scripts generated ({len(commands)} commands){RESET}\n")
    print(f"  {GREEN}bash{RESET}  {DIM}{bash_path}{RESET}")
    print(f"  {GREEN}zsh {RESET}  {DIM}{zsh_path}{RESET}")
    print()
    print(f"  {BOLD}To activate bash completion:{RESET}")
    print(f"  {CYAN}echo 'source {bash_path}' >> ~/.bashrc{RESET}")
    print(f"  {DIM}Then restart your shell or run: source ~/.bashrc{RESET}")
    print()
    print(f"  {BOLD}To activate zsh completion:{RESET}")
    print(f"  {CYAN}mkdir -p ~/.zfunc && cp {zsh_path} ~/.zfunc/_ilx{RESET}")
    print(f"  {CYAN}echo 'fpath=(~/.zfunc $fpath)' >> ~/.zshrc{RESET}")
    print(f"  {CYAN}echo 'autoload -Uz compinit && compinit' >> ~/.zshrc{RESET}")
    print(f"  {DIM}Then restart your shell or run: source ~/.zshrc{RESET}")
    print()
    print(f"  {DIM}Use /completions --print to view scripts without saving.{RESET}")
    print()
