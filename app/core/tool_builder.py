"""Dynamic tool builder — create and register Python tool scripts with user permission."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

_log = logging.getLogger("ilx_cli.tool_builder")

import sys as _sys

_PYTHON_EXE = _sys.executable

_TOOL_TEMPLATE = '''\
#!/usr/bin/env python3
"""Tool: {name}

{description}
"""
from __future__ import annotations
import sys


def main(args: list[str]) -> None:
    """Entry point — args are the command-line arguments passed after the tool name."""
    print("Tool '{name}' running with args:", args)
    # TODO: implement tool logic here


if __name__ == "__main__":
    main(sys.argv[1:])
'''


class ToolBuilder:
    """Interactively creates a Python tool file and optionally registers it as an MCP tool."""

    def __init__(self, cfg, llm_client=None) -> None:
        self.cfg = cfg
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_tool(
        self,
        tool_name: str,
        description: str,
        code: str,
        permission_callback=None,
    ) -> dict:
        """Write a Python tool script to workspace/tools/<name>.py after permission check.

        Returns {"ok": bool, "path": str, "error": str}.
        Always asks permission even in AUTO_APPROVE mode (destructive operation).
        """
        tools_dir = self._tools_dir()
        if tools_dir is None:
            return {
                "ok": False,
                "path": "",
                "error": "No workspace set. Use /workspace to configure one.",
            }

        safe_name = _safe_filename(tool_name)
        out_path = tools_dir / f"{safe_name}.py"

        # Always request explicit permission — writing scripts is destructive.
        if permission_callback is not None:
            allowed = permission_callback(
                "create_tool",
                str(out_path),
                f"Write Python tool '{tool_name}' ({len(code)} chars)",
            )
            if not allowed:
                return {"ok": False, "path": str(out_path), "error": "Cancelled by user."}

        try:
            tools_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(code, encoding="utf-8")
            _log.debug("Tool written: %s", out_path)
            return {"ok": True, "path": str(out_path), "error": ""}
        except OSError as exc:
            return {"ok": False, "path": str(out_path), "error": str(exc)}

    def generate_tool(
        self,
        task_description: str,
        permission_callback=None,
    ) -> dict:
        """Ask LLM to write a tool for task_description, then call create_tool().

        Returns {"ok": bool, "path": str, "code": str, "error": str}.
        """
        if self.llm is None:
            return {
                "ok": False,
                "path": "",
                "code": "",
                "error": "No LLM client available for code generation.",
            }

        prompt = (
            f"Write a self-contained Python 3 command-line tool script that does the following:\n\n"
            f"{task_description}\n\n"
            "Requirements:\n"
            "- The script must have a main(args: list[str]) function.\n"
            "- Include if __name__ == '__main__': main(sys.argv[1:]) at the bottom.\n"
            "- Use only Python standard library unless the task absolutely requires third-party packages.\n"
            "- Print results to stdout.\n"
            "- Include a short docstring explaining what the tool does.\n"
            "- Return ONLY the Python code — no markdown fences, no explanation.\n"
        )

        try:
            code = self.llm.chat([{"role": "user", "content": prompt}])
        except Exception as exc:
            return {"ok": False, "path": "", "code": "", "error": f"LLM error: {exc}"}

        # Strip accidental code fences
        import re
        m = re.search(r"```(?:python)?\s*\n(.*?)```", code, re.DOTALL)
        if m:
            code = m.group(1).strip()
        else:
            code = code.strip()

        # Derive a tool name from the description (first 6 words, snake_case)
        words = re.sub(r"[^a-z0-9 ]", "", task_description.lower()).split()[:6]
        tool_name = "_".join(words) or "generated_tool"

        result = self.create_tool(
            tool_name=tool_name,
            description=task_description,
            code=code,
            permission_callback=permission_callback,
        )
        return {**result, "code": code}

    def list_tools(self) -> list[str]:
        """Return paths to all tools in workspace/tools/."""
        tools_dir = self._tools_dir()
        if tools_dir is None or not tools_dir.exists():
            return []
        return sorted(str(p) for p in tools_dir.glob("*.py"))

    def run_tool(
        self,
        tool_name: str,
        args: list[str] | None = None,
        permission_callback=None,
    ) -> dict:
        """Run a tool from workspace/tools/ in a subprocess.

        Returns {"ok": bool, "output": str, "error": str}.
        Asks permission before running.
        """
        tools_dir = self._tools_dir()
        if tools_dir is None:
            return {
                "ok": False,
                "output": "",
                "error": "No workspace set.",
            }

        safe_name = _safe_filename(tool_name)
        script = tools_dir / f"{safe_name}.py"
        if not script.exists():
            return {
                "ok": False,
                "output": "",
                "error": f"Tool not found: {script}",
            }

        run_args = args or []
        cmd_display = f"python {script.name} {' '.join(run_args)}".strip()

        if permission_callback is not None:
            allowed = permission_callback(
                "run_tool",
                str(script),
                cmd_display,
            )
            if not allowed:
                return {"ok": False, "output": "", "error": "Cancelled by user."}

        try:
            python = _resolve_python()
            proc = subprocess.run(
                [python, str(script)] + run_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                cwd=str(tools_dir),
            )
            output = (proc.stdout + proc.stderr).strip()
            return {
                "ok": proc.returncode == 0,
                "output": output[:8000],
                "error": "" if proc.returncode == 0 else f"Exit code {proc.returncode}",
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": "", "error": "Tool timed out after 60 seconds."}
        except Exception as exc:
            return {"ok": False, "output": "", "error": str(exc)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _tools_dir(self) -> Path | None:
        wf = getattr(self.cfg, "working_folder", "") or ""
        if not wf:
            return None
        return Path(wf) / "tools"


def _safe_filename(name: str) -> str:
    """Convert an arbitrary name to a safe Python module filename."""
    import re
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip()).strip("_") or "tool"


def _resolve_python() -> str:
    """Return the project Python executable path, falling back to 'python'."""
    p = Path(_PYTHON_EXE)
    if p.exists():
        return str(p)
    import shutil
    return shutil.which("python") or shutil.which("python3") or "python"
