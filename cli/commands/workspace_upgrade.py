"""Upgrade command — /upgrade detects project type and offers to add missing template files."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.scaffold")


class UpgradeCommand:
    """Detects project type and offers to add missing template files."""

    # Map (indicator file, content substring) → init template key
    _DETECTORS: list[tuple[str, str, str]] = [
        ("requirements.txt", "flask",   "flask"),
        ("requirements.txt", "fastapi", "fastapi"),
        ("requirements.txt", "django",  "django"),
        ("pyproject.toml",   "flask",   "flask"),
        ("pyproject.toml",   "fastapi", "fastapi"),
        ("pyproject.toml",   "django",  "django"),
        ("pyproject.toml",   "",        "cli-tool"),
        ("requirements.txt", "",        "python"),
        ("package.json",     "next",    "nextjs"),
        ("package.json",     "vue",     "vue"),
        ("package.json",     "svelte",  "svelte"),
        ("package.json",     "electron","electron"),
        ("package.json",     "react",   "react"),
        ("package.json",     "",        "node"),
        ("Cargo.toml",       "",        "rust"),
        ("go.mod",           "",        "go"),
    ]

    def __init__(self, cfg: "AppConfig") -> None:
        self.cfg = cfg

    def cmd_upgrade(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, YELLOW, CYAN, RESET

        # Late-import so EXTRA_INIT_TEMPLATES and workspace _INIT_TEMPLATES are merged
        from cli.commands.workspace_cmds import _INIT_TEMPLATES

        wf = self.cfg.working_folder
        if not wf:
            print(f"{YELLOW}No workspace set. Use /workspace first.{RESET}")
            return
        root = Path(wf)

        detected = self._detect_type(root)
        if detected is None:
            print(f"  {YELLOW}Cannot detect project type from workspace files.{RESET}")
            print(f"  {DIM}Looking for: requirements.txt, pyproject.toml, package.json, Cargo.toml, go.mod{RESET}")
            return

        tpl = _INIT_TEMPLATES.get(detected, {})
        if not tpl:
            print(f"  {YELLOW}No template data for detected type '{detected}'.{RESET}")
            return

        print(f"\n{BOLD}Detected project type:{RESET} {CYAN}{detected}{RESET}")
        missing: list[tuple[str, str]] = []
        for rel, content in tpl.items():
            dest = root / rel
            if not dest.exists():
                missing.append((rel, content))

        if not missing:
            print(f"  {GREEN}All template files already present — nothing to add.{RESET}")
            return

        print(f"\n{BOLD}Missing template files ({len(missing)}):{RESET}")
        for rel, _ in missing:
            print(f"  {YELLOW}+{RESET} {rel}")
        print()

        for rel, content in missing:
            dest = root / rel
            try:
                ans = input(f"  {CYAN}Create '{rel}'? [y/N/all] {RESET}").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {DIM}Upgrade cancelled.{RESET}")
                return
            if ans == "all":
                # Create this and all remaining
                for r2, c2 in missing[missing.index((rel, content)):]:
                    d2 = root / r2
                    if not d2.exists():
                        d2.parent.mkdir(parents=True, exist_ok=True)
                        d2.write_text(c2, encoding="utf-8")
                        print(f"  {GREEN}created:{RESET} {r2}")
                break
            elif ans in ("y", "yes"):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                print(f"  {GREEN}created:{RESET} {rel}")
            else:
                print(f"  {DIM}skipped:{RESET} {rel}")

    def _detect_type(self, root: Path) -> str | None:
        """Return the best-matching init template key for the workspace."""
        for filename, substring, template_key in self._DETECTORS:
            indicator = root / filename
            if not indicator.exists():
                continue
            if substring:
                try:
                    text = indicator.read_text(encoding="utf-8", errors="replace").lower()
                except OSError:
                    continue
                if substring not in text:
                    continue
            return template_key
        return None
