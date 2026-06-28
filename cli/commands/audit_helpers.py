"""Audit helper functions — file analysis utilities used by AuditCommands."""
from __future__ import annotations

import re
from pathlib import Path


def count_loc(root: Path) -> tuple[int, int]:
    """Return (total_lines, code_lines) for all .py files under *root*."""
    total = 0
    code = 0
    for p in root.rglob("*.py"):
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                total += 1
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    code += 1
        except OSError:
            pass
    return total, code


def files_over_limit(root: Path, limit: int = 700) -> list[tuple[Path, int]]:
    """Return list of (path, line_count) for .py files exceeding *limit* lines."""
    results: list[tuple[Path, int]] = []
    for p in root.rglob("*.py"):
        try:
            count = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
            if count > limit:
                results.append((p, count))
        except OSError:
            pass
    return sorted(results, key=lambda x: -x[1])


def count_markers(root: Path) -> dict[str, int]:
    """Count TODO/FIXME/HACK/XXX comment markers in .py files."""
    counts: dict[str, int] = {"TODO": 0, "FIXME": 0, "HACK": 0, "XXX": 0}
    pattern = re.compile(r"#.*\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
    for p in root.rglob("*.py"):
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                m = pattern.search(line)
                if m:
                    key = m.group(1).upper()
                    counts[key] = counts.get(key, 0) + 1
        except OSError:
            pass
    return counts


def grep_secrets(root: Path) -> list[str]:
    """Grep for potential hardcoded secrets in .py files.

    Returns a list of 'file:lineno: snippet' strings (up to 30).
    Ignores comment lines and obvious test/mock values.
    """
    pattern = re.compile(
        r'(?i)(password|passwd|api_key|apikey|secret|token)\s*=\s*["\'][^"\']{4,}["\']'
    )
    ignore = re.compile(
        r"(?i)(test|mock|example|sample|dummy|fake|placeholder|hunter2|changeme|todo)"
    )
    hits: list[str] = []
    for p in root.rglob("*.py"):
        try:
            for lineno, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if line.strip().startswith("#"):
                    continue
                if pattern.search(line) and not ignore.search(line):
                    try:
                        rel = str(p.relative_to(root))
                    except ValueError:
                        rel = str(p)
                    hits.append(f"{rel}:{lineno}: {line.strip()[:80]}")
        except OSError:
            pass
        if len(hits) >= 30:
            break
    return hits


def grep_shell_true(root: Path) -> list[str]:
    """Find subprocess calls with shell=True."""
    pattern = re.compile(r"subprocess\.\w+\(.*shell\s*=\s*True")
    hits: list[str] = []
    for p in root.rglob("*.py"):
        try:
            for lineno, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if pattern.search(line):
                    try:
                        rel = str(p.relative_to(root))
                    except ValueError:
                        rel = str(p)
                    hits.append(f"{rel}:{lineno}: {line.strip()[:80]}")
        except OSError:
            pass
    return hits[:20]


def grep_eval_exec(root: Path) -> list[str]:
    """Find eval( or exec( on non-constant (non-string-literal) arguments."""
    pattern = re.compile(r"\b(eval|exec)\s*\((?!\s*[\"'])")
    hits: list[str] = []
    for p in root.rglob("*.py"):
        try:
            for lineno, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if line.strip().startswith("#"):
                    continue
                if pattern.search(line):
                    try:
                        rel = str(p.relative_to(root))
                    except ValueError:
                        rel = str(p)
                    hits.append(f"{rel}:{lineno}: {line.strip()[:80]}")
        except OSError:
            pass
    return hits[:20]


def inventory_ilx_features() -> str:
    """Scan the ILX AI CLI codebase and return a feature-inventory string.

    Used to prime the LLM prompt in /audit compare.
    """
    root = Path(__file__).resolve().parent.parent.parent  # repo root

    # Count dispatch entries in app.py
    app_py = root / "cli" / "app.py"
    command_count = 0
    commands_found: list[str] = []
    if app_py.exists():
        for line in app_py.read_text(encoding="utf-8", errors="replace").splitlines():
            if re.match(r'\s*elif cmd == "/\w+', line):
                command_count += 1
                m = re.search(r'"/(\w+)"', line)
                if m:
                    commands_found.append("/" + m.group(1))

    # Providers from llm_client_ext.py
    providers: list[str] = []
    llm_ext = root / "codex" / "app" / "llm_client_ext.py"
    if llm_ext.exists():
        for line in llm_ext.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r'provider == ["\'](\w+)["\']', line)
            if m:
                p = m.group(1)
                if p not in providers:
                    providers.append(p)

    # Scaffold templates
    templates: list[str] = []
    ws_cmds = root / "cli" / "commands" / "workspace_cmds.py"
    if ws_cmds.exists():
        for line in ws_cmds.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r'"(\w[\w-]*)"\s*:', line)
            if m and len(m.group(1)) > 2:
                t = m.group(1)
                if t not in templates and t not in ("id", "rev", "args"):
                    templates.append(t)

    # Key capabilities detected by file existence
    cap_map = {
        "tool_use": "cli/chat_session.py",
        "rag / BM25 search": "app/core/rag.py",
        "session management": "cli/session.py",
        "crash_db": "app/core/crash_db.py",
        "circuit_breaker": "app/core/ollama_guard.py",
        "supervisor / process queue": "app/core/supervisor.py",
        "MCP tool protocol": "app/core/mcp_client.py",
        "audit log": "app/core/audit.py",
        "web fetch / SSRF guard": "app/core/web_fetch.py",
        "user-defined tools": "app/core/user_tools/registry.py",
        "multi-provider LLM": "codex/app/llm_client_ext.py",
        "SSH tunneling": "app/core/ssh_client.py",
        "cost tracking": "app/core/cost_tracker.py",
        "secret store / keyring": "app/core/secret_store.py",
    }
    capabilities = [cap for cap, rel in cap_map.items() if (root / rel).exists()]

    # MCP tool names
    mcp_tools: list[str] = []
    mcp_py = root / "app" / "core" / "mcp_client.py"
    if mcp_py.exists():
        for line in mcp_py.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.search(r'name=["\'](\w+)["\']', line)
            if m and m.group(1) not in mcp_tools:
                mcp_tools.append(m.group(1))

    lines = [
        "## ILX AI CLI — Feature Inventory",
        "",
        f"**Slash commands implemented:** {command_count}",
        f"  {', '.join(commands_found[:40])}{'...' if len(commands_found) > 40 else ''}",
        "",
        f"**LLM Providers:** {', '.join(providers) or 'ollama (local)'}",
        "",
        f"**Scaffold templates:** {', '.join(templates[:20])}",
        "",
        f"**MCP built-in tools:** {', '.join(mcp_tools[:20])}",
        "",
        "**Core capabilities:**",
    ]
    for cap in capabilities:
        lines.append(f"  - {cap}")
    lines += [
        "",
        "**Key differentiators:**",
        "  - Fully local-first: works entirely offline with Ollama",
        "  - Multi-provider: ollama, anthropic, openai, groq, gemini, meta",
        "  - Process supervisor with queue, timeouts, graceful kill",
        "  - BM25 RAG for codebase context",
        "  - MCP tool protocol for extensibility",
        "  - Circuit breaker for Ollama resilience",
        "  - User-definable dynamic Python tools",
        "  - Audit log, crash DB, diagnostics",
        "  - SSH tunneling built-in",
        "  - Competitive /audit compare command",
    ]
    return "\n".join(lines)
