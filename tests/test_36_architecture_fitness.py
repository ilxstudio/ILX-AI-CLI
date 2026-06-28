"""Architectural boundary tests.

These tests verify structural rules without executing any production code.
They read file contents as text and apply heuristic checks, so they run
quickly and have no external dependencies.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# Root of the project — two levels up from this file (tests/)
_ROOT = Path(__file__).resolve().parent.parent

_CLI_DIR     = _ROOT / "cli"
_CORE_DIR    = _ROOT / "app" / "core"
_CODEX_DIR   = _ROOT / "codex" / "app"

# Files that are explicitly allowed to call subprocess.run / subprocess.Popen
# directly because they ARE the process-management layer or have documented
# reasons for direct subprocess use.
_SUBPROCESS_ALLOWED: frozenset[Path] = frozenset({
    _ROOT / "app" / "core" / "process_runner.py",
    _ROOT / "app" / "core" / "supervisor.py",
    # build_helper, mcp_stdio, executor, ssh_client, tool_builder, and
    # user_tools use Popen for specialised I/O — included here so the
    # test documents rather than blocks existing patterns.
    _ROOT / "app" / "core" / "build_helper.py",
    _ROOT / "app" / "core" / "executor.py",
    _ROOT / "app" / "core" / "mcp_stdio.py",
    _ROOT / "app" / "core" / "ssh_client.py",
    _ROOT / "app" / "core" / "tool_builder.py",
    _ROOT / "app" / "core" / "user_tools" / "runner.py",
    _ROOT / "app" / "core" / "user_tools" / "validator.py",
    _ROOT / "cli" / "commands" / "docker_cmds.py",
    _ROOT / "cli" / "commands" / "git_cmds.py",
    _ROOT / "cli" / "commands" / "workspace_cmds.py",
    # codex/app/runner.py uses Popen for streaming tool execution
    _ROOT / "codex" / "app" / "runner.py",
})

# Files whose cli/ imports are intentional deferred/conditional imports.
# app/core/permissions.py imports cli.commands.perm_cmds at runtime inside
# a try/except block to access profile definitions — a controlled exception
# to the layering rule that should not propagate further.
_CLI_IMPORT_ALLOWED: frozenset[Path] = frozenset({
    _ROOT / "app" / "core" / "permissions.py",
})

# Patterns that indicate a hardcoded absolute path in source code
_HARDCODED_PATH_RE = re.compile(
    r"""(?x)
    ['"](
        C:\\\\             # Windows drive letter (escaped in raw string)
        | C:/
        | /home/[a-z]
        | /root/
        | /Users/[A-Za-z]
    )""",
)


def _py_files(directory: Path) -> list[Path]:
    """Return all .py files under *directory* (excludes __pycache__)."""
    return [
        p for p in directory.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Rule 1 — No UI imports in app/core/ or codex/app/
# ---------------------------------------------------------------------------

class TestNoCLIImportsInCore:
    """app/core/ and codex/app/ must not import from cli/."""

    _CLI_IMPORT_RE = re.compile(r"^\s*(import|from)\s+cli[\. ]", re.MULTILINE)

    def _violating_files(self, directory: Path) -> list[str]:
        violations: list[str] = []
        for path in _py_files(directory):
            if path in _CLI_IMPORT_ALLOWED:
                continue
            if self._CLI_IMPORT_RE.search(_source(path)):
                violations.append(str(path.relative_to(_ROOT)))
        return violations

    def test_core_has_no_cli_imports(self):
        violations = self._violating_files(_CORE_DIR)
        assert violations == [], (
            "app/core/ modules must not import from cli/. Violations:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_codex_has_no_cli_imports(self):
        violations = self._violating_files(_CODEX_DIR)
        assert violations == [], (
            "codex/app/ modules must not import from cli/. Violations:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# Rule 2 — No direct subprocess calls outside the approved set
# ---------------------------------------------------------------------------

class TestSubprocessCallsGated:
    """Only approved modules may call subprocess.run or subprocess.Popen directly."""

    _SUBPROCESS_RE = re.compile(r"\bsubprocess\.(run|Popen)\s*\(")

    def test_no_unapproved_subprocess_calls(self):
        violations: list[str] = []
        for directory in (_CORE_DIR, _CODEX_DIR, _CLI_DIR):
            for path in _py_files(directory):
                if path in _SUBPROCESS_ALLOWED:
                    continue
                if self._SUBPROCESS_RE.search(_source(path)):
                    violations.append(str(path.relative_to(_ROOT)))
        assert violations == [], (
            "Direct subprocess.run/Popen calls found outside approved modules:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# Rule 3 — No hardcoded absolute paths in production code
# ---------------------------------------------------------------------------

class TestNoHardcodedPaths:
    """Production code must not contain hardcoded OS-specific paths."""

    def test_no_hardcoded_paths_in_core(self):
        violations: list[str] = []
        for path in _py_files(_CORE_DIR):
            src = _source(path)
            if _HARDCODED_PATH_RE.search(src):
                violations.append(str(path.relative_to(_ROOT)))
        assert violations == [], (
            "Hardcoded absolute paths found in app/core/. Use Path.home(), "
            "sys.executable, or AppConfig instead. Violations:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_no_hardcoded_paths_in_codex(self):
        violations: list[str] = []
        for path in _py_files(_CODEX_DIR):
            src = _source(path)
            if _HARDCODED_PATH_RE.search(src):
                violations.append(str(path.relative_to(_ROOT)))
        assert violations == [], (
            "Hardcoded absolute paths found in codex/app/. Use Path.home(), "
            "sys.executable, or AppConfig instead. Violations:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_no_hardcoded_paths_in_cli(self):
        violations: list[str] = []
        for path in _py_files(_CLI_DIR):
            src = _source(path)
            if _HARDCODED_PATH_RE.search(src):
                violations.append(str(path.relative_to(_ROOT)))
        assert violations == [], (
            "Hardcoded absolute paths found in cli/. Use Path.home(), "
            "sys.executable, or AppConfig instead. Violations:\n"
            + "\n".join(f"  {v}" for v in violations)
        )
