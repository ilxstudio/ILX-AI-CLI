"""Project-level rules — ported from ILX AI GUI.

Equivalent to AGENTS.md / .cursorrules / project-rules convention.
Rules files are prepended to the system prompt for every chat/code turn.

Resolution order (all matched files are concatenated):
  1. <working_folder>/.ilx_rules.md    — project-scoped (commit with repo)
  2. <working_folder>/.ilx_rules.local.md — personal (gitignore this)
  3. ~/.ilx_cli/rules.md               — user-global
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("ilx_cli.rules")
MAX_BYTES = 32 * 1024
_USER_GLOBAL = Path.home() / ".ilx_cli" / "rules.md"


@dataclass
class LoadedRules:
    sources: list[str] = field(default_factory=list)
    text:    str       = ""

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def _read_capped(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _log.warning("could not read rules %s: %s", path, exc)
        return None
    if len(raw.encode("utf-8")) > MAX_BYTES:
        b = raw.encode("utf-8")[:MAX_BYTES]
        raw = b.decode("utf-8", errors="ignore")
        _log.info("rules file %s truncated to %d bytes", path, len(b))
    return raw


def _resolve_imports(text: str, base_dir: Path, depth: int = 0) -> str:
    """Inline any ``@path`` lines (one level deep)."""
    if depth > 1:
        return text
    out_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("@") and " " not in stripped[1:].strip():
            ref = stripped[1:].strip()
            try:
                target = (base_dir / ref).resolve()
                if target.is_file():
                    inner = _read_capped(target)
                    if inner is not None:
                        out_lines.append(_resolve_imports(inner, target.parent, depth + 1))
                        continue
            except (OSError, ValueError) as exc:
                _log.debug("rules import %s failed: %s", ref, exc)
        out_lines.append(line)
    return "\n".join(out_lines)


def load(working_folder: str | None) -> LoadedRules:
    """Walk the rules-file precedence order and return merged content."""
    out = LoadedRules()
    candidates: list[Path] = []
    if working_folder:
        wf = Path(working_folder)
        candidates.append(wf / ".ilx_rules.md")
        candidates.append(wf / ".ilx_rules.local.md")
    candidates.append(_USER_GLOBAL)

    chunks: list[str] = []
    for path in candidates:
        body = _read_capped(path)
        if body is None:
            continue
        body = _resolve_imports(body, path.parent).strip()
        if not body:
            continue
        out.sources.append(str(path))
        chunks.append(f"### From {path.name}\n{body}")

    if chunks:
        out.text = "\n\n".join(chunks)
    return out


def system_prompt_prefix(working_folder: str | None) -> str:
    """Return the block to prepend to a system prompt, or '' if no rules."""
    rules = load(working_folder)
    if rules.is_empty:
        return ""
    return (
        "[Project rules — these are non-negotiable and apply to every "
        "response in this workspace]\n\n"
        + rules.text
        + "\n\n[End project rules]\n\n"
    )
