"""MCP protocol primitives — tool definitions and message parsing.

This module contains the data-layer and message-framing helpers for MCP:
- MCPTool: dataclass-style wrapper around a single tool specification
- parse_tool_call: detect and parse a tool call embedded in LLM response text
- BUILTIN_TOOL_SPECS: canonical list of built-in tool definitions

The runtime client logic (execution, sandbox, HTTP dispatch) lives in mcp_client.py.
"""
from __future__ import annotations

import json
import re


class MCPTool:
    """A single MCP tool definition.

    Wraps the raw JSON spec from mcp_tools.json and exposes typed attributes.
    """

    def __init__(self, spec: dict) -> None:
        self.name:        str       = spec["name"]
        self.description: str       = spec.get("description", "")
        self.parameters:  dict      = spec.get("parameters", {"type": "object", "properties": {}})
        self.executor:    str       = spec.get("executor", "builtin")
        self.command:     list[str] = spec.get("command", [])
        self.url:         str       = spec.get("url", "")
        self._spec = spec

    def to_prompt_fragment(self) -> str:
        """Return a human-readable description for injection into system prompt."""
        params = ", ".join(self.parameters.get("properties", {}).keys())
        return f"  - {self.name}({params}): {self.description}"


def parse_tool_call(text: str) -> tuple[str, dict] | None:
    """Detect and parse a tool call in LLM response text.

    Looks for a JSON object with a ``"tool"`` key, either bare or inside a
    fenced code block.

    Returns ``(tool_name, args)`` or ``None`` if no tool call is detected.
    """
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


# ---------------------------------------------------------------------------
# Canonical built-in tool specs
# These are registered by MCPClient.register_builtin_tools().
# ---------------------------------------------------------------------------

_S   = "string"
_INT = "integer"
_ARR = "array"

BUILTIN_TOOL_SPECS: list[dict] = [
    # ── Core filesystem ──────────────────────────────────────────────────────
    {
        "name": "read_file",
        "description": "Read a text file from the filesystem",
        "executor": "builtin",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": _S, "description": "Path to the file"}},
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
                "path":    {"type": _S, "description": "Destination path"},
                "content": {"type": _S, "description": "Text to write"},
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
            "properties": {"path": {"type": _S, "description": "Directory path"}},
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the workspace",
        "executor": "builtin",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": _S, "description": "Shell command to execute"},
                "cwd":     {"type": _S, "description": "Working directory (optional)"},
            },
            "required": ["command"],
        },
    },
    # ── File converters — read ───────────────────────────────────────────────
    {
        "name": "read_pdf",
        "description": "Extract text from a PDF file (requires pypdf)",
        "executor": "builtin",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": _S, "description": "Path to the PDF file"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_docx",
        "description": "Extract text from a .docx Word document (requires python-docx)",
        "executor": "builtin",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": _S, "description": "Path to the .docx file"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_xlsx",
        "description": "Read an Excel .xlsx spreadsheet as text/data (requires openpyxl)",
        "executor": "builtin",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": _S, "description": "Path to the .xlsx file"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_png",
        "description": "Read metadata (dimensions, mode) from a PNG image (requires Pillow)",
        "executor": "builtin",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": _S, "description": "Path to the PNG file"}},
            "required": ["path"],
        },
    },
    # ── File converters — write ──────────────────────────────────────────────
    {
        "name": "write_pdf",
        "description": "Write plain text to a PDF file (requires reportlab)",
        "executor": "builtin",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": _S, "description": "Destination .pdf path"},
                "text": {"type": _S, "description": "Plain text content"},
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
                "path": {"type": _S, "description": "Destination .docx path"},
                "text": {"type": _S, "description": "Plain text content (newline-separated paragraphs)"},
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
                "path": {"type": _S,   "description": "Destination .xlsx path"},
                "data": {"type": _ARR, "description": "2D array of rows (list of lists)"},
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
                "path":   {"type": _S,   "description": "Destination .png path"},
                "width":  {"type": _INT, "description": "Image width in pixels (default 800)"},
                "height": {"type": _INT, "description": "Image height in pixels (default 600)"},
            },
            "required": ["path"],
        },
    },
    # ── Web fetch ────────────────────────────────────────────────────────────
    {
        "name": "fetch_url",
        "description": "Fetch a URL and return readable text extracted from the HTML page",
        "executor": "builtin",
        "parameters": {
            "type": "object",
            "properties": {
                "url":     {"type": _S,   "description": "HTTP/HTTPS URL to fetch (required)"},
                "timeout": {"type": _INT, "description": "Request timeout in seconds (default 15)"},
            },
            "required": ["url"],
        },
    },
    # ── Patch ────────────────────────────────────────────────────────────────
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
                "path":  {"type": _S, "description": "Path to the file to patch"},
                "patch": {"type": _S, "description": "Patch content (conflict-style or unified diff)"},
            },
            "required": ["path", "patch"],
        },
    },
]
