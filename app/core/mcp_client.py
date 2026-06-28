"""MCP (Model Context Protocol) client — tool registration and invocation.

This module implements a lightweight MCP client that:
1. Loads tool definitions from ~/.ilx_cli/mcp_tools.json
2. Builds tool-use prompts for models that support function calling
3. Parses and dispatches tool_call results from LLM responses
4. Executes approved tools via subprocess or Python call
5. Returns tool results back to the LLM conversation

MCP tools.json format:
  [
    {
      "name": "read_file",
      "description": "Read a file from the filesystem",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "Absolute path to the file"}
        },
        "required": ["path"]
      },
      "executor": "builtin"   // "builtin" | "subprocess" | "http"
    }
  ]
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.utils.file_utils import safe_resolve
from app.core import file_converter, process_runner
from app.core.web_fetch import _check_ssrf as _web_check_ssrf

_log = logging.getLogger("ilx_cli.mcp")

_MCP_TOOLS_FILE = Path.home() / ".ilx_cli" / "mcp_tools.json"
_MCP_SERVERS_FILE = Path.home() / ".ilx_cli" / "mcp_servers.json"


class MCPTool:
    """A single MCP tool definition."""

    def __init__(self, spec: dict) -> None:
        self.name:        str  = spec["name"]
        self.description: str  = spec.get("description", "")
        self.parameters:  dict = spec.get("parameters", {"type": "object", "properties": {}})
        self.executor:    str  = spec.get("executor", "builtin")
        self.command:     list[str] = spec.get("command", [])
        self.url:         str  = spec.get("url", "")
        self._spec = spec

    def to_prompt_fragment(self) -> str:
        """Return a human-readable description for injection into system prompt."""
        params = ", ".join(self.parameters.get("properties", {}).keys())
        return f"  - {self.name}({params}): {self.description}"


class MCPClient:
    """Manages MCP tool registration, listing, and invocation."""

    def __init__(self, cfg=None) -> None:
        self._cfg = cfg
        self._tools: dict[str, MCPTool] = {}
        self._load()

    def _load(self) -> None:
        if not _MCP_TOOLS_FILE.exists():
            return
        try:
            specs = json.loads(_MCP_TOOLS_FILE.read_text(encoding="utf-8"))
            for spec in specs:
                t = MCPTool(spec)
                self._tools[t.name] = t
            _log.debug("Loaded %d MCP tools", len(self._tools))
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            _log.warning("Failed to load MCP tools: %s", exc)

    def reload(self) -> int:
        """Reload tools from disk. Returns count."""
        self._tools.clear()
        self._load()
        return len(self._tools)

    @property
    def tools(self) -> list[MCPTool]:
        return list(self._tools.values())

    def get(self, name: str) -> MCPTool | None:
        return self._tools.get(name)

    def to_system_prompt_block(self) -> str:
        """Return a system prompt block listing all available tools."""
        if not self._tools:
            return ""
        lines = ["You have access to the following MCP tools. Call them by responding with:"]
        lines.append('{"tool": "<name>", "args": {<params>}}')
        lines.append("")
        lines.append("Available tools:")
        for t in self._tools.values():
            lines.append(t.to_prompt_fragment())
        lines.append("")
        lines.append("After a tool call, the result will be provided and you should continue.")
        return "\n".join(lines)

    def call(self, name: str, args: dict, permission_cb=None) -> dict:
        """Invoke a tool by name. Returns {success, result, error}."""
        tool = self._tools.get(name)
        if tool is None:
            return {"success": False, "error": f"Unknown tool: {name}", "result": None}

        if permission_cb is not None:
            params_str = json.dumps(args, ensure_ascii=False)[:200]
            if not permission_cb("mcp_tool", name, params_str):
                return {"success": False, "error": "Denied by user", "result": None}

        if tool.executor == "builtin":
            return self._call_builtin(tool, args)
        if tool.executor == "subprocess":
            return self._call_subprocess(tool, args)
        if tool.executor == "http":
            return self._call_http(tool, args)
        return {"success": False, "error": f"Unknown executor: {tool.executor}", "result": None}

    # ------------------------------------------------------------------
    # Sandbox helpers
    # ------------------------------------------------------------------

    def _auto_approve(self) -> bool:
        """Return True when the user has AUTO_APPROVE permission mode set."""
        if self._cfg is not None:
            return getattr(self._cfg, "permission_mode", "ask") == "auto"
        import os
        return os.environ.get("ILX_AUTO_APPROVE", "").lower() in ("1", "true", "yes")

    def _sandbox_check(self, raw_path: str) -> tuple[str | None, dict | None]:
        """Resolve *raw_path* against the working folder sandbox.

        Returns (resolved_str, None) on success, or (None, error_dict) on violation.
        When no working folder is set the path is allowed through unchanged.
        """
        wf = getattr(self._cfg, "working_folder", None) if self._cfg else None
        if not wf:
            return raw_path, None
        # auto_approve reduces prompting but sandbox containment is always enforced
        resolved = safe_resolve(raw_path, wf)
        if resolved is None:
            return None, {
                "success": False,
                "error": "Path outside working folder (sandbox violation)",
                "result": None,
            }
        return resolved, None

    # ------------------------------------------------------------------
    # Built-in tool dispatch
    # ------------------------------------------------------------------

    def _call_builtin(self, tool: MCPTool, args: dict) -> dict:
        """Execute built-in tools (filesystem, run_command, file converters)."""
        name = tool.name
        try:
            # ── Sandboxed filesystem tools ──────────────────────────────
            if name == "read_file":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                path = Path(resolved)
                if not path.exists():
                    return {"success": False, "error": f"File not found: {path}", "result": None}
                content = path.read_text(encoding="utf-8", errors="replace")
                return {"success": True, "result": content[:8000], "error": None}

            if name == "write_file":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                path = Path(resolved)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(args.get("content", ""), encoding="utf-8")
                return {"success": True, "result": f"Written: {path}", "error": None}

            if name == "list_dir":
                raw = args.get("path", ".")
                resolved, err = self._sandbox_check(raw)
                if err:
                    return err
                path = Path(resolved)
                entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
                return {"success": True, "result": "\n".join(entries[:100]), "error": None}

            if name == "run_command":
                cmd  = args.get("command", "")
                cwd  = args.get("cwd", None)
                import shlex as _shlex
                cmd_parts = _shlex.split(cmd) if isinstance(cmd, str) else cmd
                r = process_runner.run(cmd_parts, cwd=cwd, timeout=30)
                out = (r.stdout + r.stderr).strip()
                return {"success": r.ok, "result": out[:4000], "error": None}

            # ── File-converter tools ────────────────────────────────────
            # Each converter passes its path through _sandbox_check() so that
            # user-supplied paths cannot escape the working folder (path traversal fix).
            if name == "read_pdf":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                res = file_converter.read_pdf(resolved)
                return {"success": res["ok"], "result": res.get("text", ""),
                        "pages": res.get("pages", 0), "error": res.get("error", "")}

            if name == "write_pdf":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                res = file_converter.write_pdf(resolved, args.get("text", ""))
                return {"success": res["ok"], "result": resolved if res["ok"] else None,
                        "error": res.get("error", "")}

            if name == "read_docx":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                res = file_converter.read_docx(resolved)
                return {"success": res["ok"], "result": res.get("text", ""),
                        "error": res.get("error", "")}

            if name == "write_docx":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                res = file_converter.write_docx(resolved, args.get("text", ""))
                return {"success": res["ok"], "result": resolved if res["ok"] else None,
                        "error": res.get("error", "")}

            if name == "read_xlsx":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                res = file_converter.read_xlsx(resolved)
                return {"success": res["ok"], "result": res.get("text", ""),
                        "sheets": res.get("sheets", {}), "error": res.get("error", "")}

            if name == "write_xlsx":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                res = file_converter.write_xlsx(resolved, args.get("data", []))
                return {"success": res["ok"], "result": resolved if res["ok"] else None,
                        "error": res.get("error", "")}

            if name == "read_png":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                res = file_converter.read_png(resolved)
                return {"success": res["ok"], "result": res.get("text", ""),
                        "width": res.get("width", 0), "height": res.get("height", 0),
                        "mode": res.get("mode", ""), "error": res.get("error", "")}

            if name == "write_png":
                resolved, err = self._sandbox_check(args["path"])
                if err:
                    return err
                res = file_converter.write_png(
                    resolved,
                    args.get("width", 800),
                    args.get("height", 600),
                )
                return {"success": res["ok"], "result": resolved if res["ok"] else None,
                        "error": res.get("error", "")}

            if name == "apply_patch":
                path = args.get("path", "")
                patch_text = args.get("patch", "")
                resolved, err = self._sandbox_check(path)
                if err:
                    return err
                result = self._apply_patch_blocks(resolved, patch_text)
                return result

            if name == "fetch_url":
                from app.core import web_fetch
                url = args.get("url", "")
                fetch_timeout = int(args.get("timeout", 15))
                res = web_fetch.fetch_url(url, fetch_timeout)
                if res.get("ok"):
                    body = f"Title: {res['title']}\n\n{res['text']}"
                    return {"success": True, "result": body[:8000], "error": None}
                return {"success": False, "error": res.get("error", "Unknown error"), "result": None}

            return {"success": False, "error": f"No builtin handler for '{name}'", "result": None}

        except Exception as exc:
            return {"success": False, "error": str(exc), "result": None}

    def _apply_patch_blocks(self, path: str, patch_text: str) -> dict:
        """Apply conflict-style or unified-diff patch to *path*. Returns result dict."""
        import re
        from app.core import audit as _audit

        target = Path(path)
        if not target.exists():
            return {"success": False, "error": f"File not found: {path}", "result": None}

        try:
            original = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"success": False, "error": f"Cannot read file: {exc}", "result": None}

        # ── Strategy 1: conflict-style <<<<<<< / ======= / >>>>>>> blocks ──
        BLOCK_RE = re.compile(
            r"<<<<<<< ORIGINAL\r?\n(.*?)\r?\n=======\r?\n(.*?)\r?\n>>>>>>> MODIFIED",
            re.DOTALL,
        )
        blocks = BLOCK_RE.findall(patch_text)
        if blocks:
            patched = original
            applied = 0
            for old_chunk, new_chunk in blocks:
                if old_chunk in patched:
                    patched = patched.replace(old_chunk, new_chunk, 1)
                    applied += 1
                else:
                    return {
                        "success": False,
                        "error": (
                            f"Context not found in {path} for block:\n"
                            f"{old_chunk[:120]!r}..."
                        ),
                        "result": None,
                    }
            self._atomic_write(target, patched)
            _audit.log_file_op("modify", path, allowed=True,
                                bytes_written=len(patched.encode("utf-8")))
            return {"success": True,
                    "result": f"Patched {path}: {applied} hunk(s) applied",
                    "error": None}

        # ── Strategy 2: unified diff (--- / +++ / @@ ... @@) ───────────────
        if "--- " in patch_text and "+++ " in patch_text and "@@" in patch_text:
            orig_lines = original.splitlines(keepends=True)
            patch_lines = patch_text.splitlines(keepends=True)
            result_lines = self._apply_unified_diff(orig_lines, patch_lines)
            if result_lines is None:
                return {
                    "success": False,
                    "error": f"Unified diff context not found in {path}",
                    "result": None,
                }
            patched = "".join(result_lines)
            self._atomic_write(target, patched)
            _audit.log_file_op("modify", path, allowed=True,
                                bytes_written=len(patched.encode("utf-8")))
            return {"success": True,
                    "result": f"Patched {path}: unified diff applied",
                    "error": None}

        return {
            "success": False,
            "error": (
                "patch_text does not contain recognisable patch blocks. "
                "Use <<<<<<< ORIGINAL / ======= / >>>>>>> MODIFIED "
                "or standard unified diff format."
            ),
            "result": None,
        }

    def _atomic_write(self, target: Path, content: str) -> None:
        """Write *content* to *target* atomically via a temp-file rename."""
        import os, tempfile
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".ilx_patch_tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            Path(tmp).replace(target)
        except Exception:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _apply_unified_diff(
        self, orig_lines: list[str], patch_lines: list[str]
    ) -> list[str] | None:
        """Apply unified diff hunks to *orig_lines*; returns patched list or None on mismatch."""
        import re

        result = list(orig_lines)
        offset = 0  # cumulative line-count shift from previous hunks

        hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
        i = 0
        while i < len(patch_lines):
            m = hunk_re.match(patch_lines[i])
            if not m:
                i += 1
                continue
            orig_start = int(m.group(1)) - 1  # 0-based
            i += 1
            hunk: list[str] = []
            while i < len(patch_lines) and not hunk_re.match(patch_lines[i]):
                if not patch_lines[i].startswith(("--- ", "+++ ")):
                    hunk.append(patch_lines[i])
                i += 1
            pos = orig_start + offset
            new_block: list[str] = []
            for h_line in hunk:
                if h_line.startswith(" "):        # context — must match
                    if pos >= len(result) or result[pos].rstrip("\r\n") != h_line[1:].rstrip("\r\n"):
                        return None
                    new_block.append(result[pos]); pos += 1
                elif h_line.startswith("-"):      # removal — must match
                    if pos >= len(result) or result[pos].rstrip("\r\n") != h_line[1:].rstrip("\r\n"):
                        return None
                    pos += 1
                elif h_line.startswith("+"):      # addition
                    add = h_line[1:]
                    new_block.append(add if add.endswith("\n") else add + "\n")
            hunk_start = orig_start + offset
            result[hunk_start:pos] = new_block
            offset += len(new_block) - (pos - hunk_start)
        return result

    def _call_subprocess(self, tool: MCPTool, args: dict) -> dict:
        if not tool.command:
            return {"success": False, "error": "No command defined for tool", "result": None}
        cmd = [str(c).format(**args) for c in tool.command]
        try:
            r = process_runner.run(cmd, timeout=30)
            out = (r.stdout + r.stderr).strip()
            return {"success": r.ok, "result": out[:4000], "error": None}
        except Exception as exc:
            return {"success": False, "error": str(exc), "result": None}

    def _call_http(self, tool: MCPTool, args: dict) -> dict:
        if not tool.url:
            return {"success": False, "error": "No URL defined for tool", "result": None}
        # SSRF guard: use the same robust DNS-based check as web_fetch.fetch_url().
        # The old inline regex was bypassable via hex/octal IPs and didn't cover the
        # cloud metadata range (169.254.x.x).  _web_check_ssrf() resolves the hostname
        # via DNS and inspects each resolved IP, so it is not bypassable.
        from urllib.parse import urlparse as _urlparse
        url = tool.url
        parsed = _urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"success": False, "error": f"Rejected non-HTTP/S scheme: '{parsed.scheme}'",
                    "result": None}
        hostname = parsed.hostname or ""
        if not hostname:
            return {"success": False, "error": "No hostname in tool URL", "result": None}
        ssrf_err = _web_check_ssrf(hostname)
        if ssrf_err:
            return {
                "success": False,
                "error": (
                    f"{ssrf_err}. "
                    "Set ILX_ALLOW_LOCAL_HTTP=1 to allow local/private URLs."
                ),
                "result": None,
            }
        import time
        import httpx
        last_error = None
        for attempt in range(3):
            try:
                r = httpx.post(tool.url, json=args, timeout=15.0)
                if r.status_code >= 500 and attempt < 2:
                    _log.warning(
                        "HTTP tool %s returned %d, retrying (%d/3)",
                        tool.name, r.status_code, attempt + 1,
                    )
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return {"success": True, "result": r.text[:4000], "error": None}
            except httpx.ConnectError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
            except Exception as exc:
                return {"success": False, "error": str(exc), "result": None}
        return {
            "success": False,
            "error": f"HTTP tool failed after 3 attempts: {last_error}",
            "result": None,
        }

    def parse_tool_call(self, text: str) -> tuple[str, dict] | None:
        """Detect and parse a tool call in LLM response text.
        Returns (tool_name, args) or None if no tool call found.
        """
        import re
        # Match bare JSON object with "tool" key, possibly in a code block
        patterns = [
            r'```(?:json)?\s*\n(\{"tool"[^`]+)\n```',
            r'(\{"tool"\s*:\s*"[^"]+"\s*,\s*"args"\s*:\s*\{[^}]*\}\s*\})',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(1))
                    if "tool" in obj:
                        return obj["tool"], obj.get("args", {})
                except json.JSONDecodeError:
                    pass
        return None

    def register_builtin_tools(self) -> None:
        """Register the standard built-in tools if not already in tools dict."""
        _s = "string"
        _int = "integer"
        _arr = "array"
        builtins = [
            # ── Core filesystem ──────────────────────────────────────────
            {
                "name": "read_file",
                "description": "Read a text file from the filesystem",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": _s, "description": "Path to the file"}},
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write text content to a file (creates parent dirs)",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":    {"type": _s, "description": "Destination path"},
                        "content": {"type": _s, "description": "Text to write"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "list_dir",
                "description": "List entries in a directory",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": _s, "description": "Directory path"}},
                },
            },
            {
                "name": "run_command",
                "description": "Run a shell command in the workspace",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": _s, "description": "Shell command to execute"},
                        "cwd":     {"type": _s, "description": "Working directory (optional)"},
                    },
                    "required": ["command"],
                },
            },
            # ── File converters — read ───────────────────────────────────
            {
                "name": "read_pdf",
                "description": "Extract text from a PDF file (requires pypdf)",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": _s, "description": "Path to the PDF file"}},
                    "required": ["path"],
                },
            },
            {
                "name": "read_docx",
                "description": "Extract text from a .docx Word document (requires python-docx)",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": _s, "description": "Path to the .docx file"}},
                    "required": ["path"],
                },
            },
            {
                "name": "read_xlsx",
                "description": "Read an Excel .xlsx spreadsheet as text/data (requires openpyxl)",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": _s, "description": "Path to the .xlsx file"}},
                    "required": ["path"],
                },
            },
            {
                "name": "read_png",
                "description": "Read metadata (dimensions, mode) from a PNG image (requires Pillow)",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": _s, "description": "Path to the PNG file"}},
                    "required": ["path"],
                },
            },
            # ── File converters — write ──────────────────────────────────
            {
                "name": "write_pdf",
                "description": "Write plain text to a PDF file (requires reportlab)",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": _s, "description": "Destination .pdf path"},
                        "text": {"type": _s, "description": "Plain text content"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_docx",
                "description": "Write plain text paragraphs to a .docx Word document (requires python-docx)",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": _s, "description": "Destination .docx path"},
                        "text": {"type": _s, "description": "Plain text content (newline-separated paragraphs)"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_xlsx",
                "description": "Write a 2D list to an Excel .xlsx file as Sheet1 (requires openpyxl)",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": _s,   "description": "Destination .xlsx path"},
                        "data": {"type": _arr, "description": "2D array of rows (list of lists)"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_png",
                "description": "Create a solid-color PNG image (requires Pillow)",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":   {"type": _s,   "description": "Destination .png path"},
                        "width":  {"type": _int, "description": "Image width in pixels (default 800)"},
                        "height": {"type": _int, "description": "Image height in pixels (default 600)"},
                    },
                    "required": ["path"],
                },
            },
            # ── Web fetch ────────────────────────────────────────────────
            {
                "name": "fetch_url",
                "description": "Fetch a URL and return readable text extracted from the HTML page",
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url":     {"type": _s,   "description": "HTTP/HTTPS URL to fetch (required)"},
                        "timeout": {"type": _int, "description": "Request timeout in seconds (default 15)"},
                    },
                    "required": ["url"],
                },
            },
            # ── Patch ────────────────────────────────────────────────────
            {
                "name": "apply_patch",
                "description": (
                    "Apply a patch to a file. Accepts conflict-style "
                    "<<<<<<< ORIGINAL / ======= / >>>>>>> MODIFIED blocks "
                    "or standard unified diff format."
                ),
                "executor": "builtin",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":  {"type": _s, "description": "Path to the file to patch"},
                        "patch": {"type": _s, "description": "Patch content (conflict-style or unified diff)"},
                    },
                    "required": ["path", "patch"],
                },
            },
        ]
        for spec in builtins:
            if spec["name"] not in self._tools:
                self._tools[spec["name"]] = MCPTool(spec)

    def save_tools(self) -> None:
        """Persist current tool definitions to disk."""
        _MCP_TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        specs = [t._spec for t in self._tools.values()]
        _MCP_TOOLS_FILE.write_text(json.dumps(specs, indent=2), encoding="utf-8")

    def status_lines(self) -> list[str]:
        """Return human-readable status for /mcp status."""
        if not self._tools:
            return ["  No MCP tools registered.",
                    f"  Config file: {_MCP_TOOLS_FILE}"]
        lines = [f"  {len(self._tools)} tool(s) registered:"]
        for t in self._tools.values():
            lines.append(f"    {t.name} [{t.executor}] — {t.description[:60]}")
        lines.append(f"  Config: {_MCP_TOOLS_FILE}")
        return lines
