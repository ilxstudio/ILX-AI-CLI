"""Tool schema definitions — converts ILX tool definitions to each provider's wire format."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict  # JSON Schema object

    def to_anthropic(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def to_openai(self) -> dict:  # also used by Groq and Ollama
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_gemini(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


BUILTIN_TOOL_DEFS: list[ToolDef] = [
    ToolDef(
        name="read_file",
        description=(
            "Read the complete contents of a file. Use this before editing to understand "
            "current state. Returns the file text."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"}
            },
            "required": ["path"],
        },
    ),
    ToolDef(
        name="write_file",
        description=(
            "Write or overwrite a file with new content. Always read_file first to avoid "
            "losing existing content. The path must be absolute or relative to the working folder."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    ),
    ToolDef(
        name="list_dir",
        description=(
            "List files and subdirectories in a directory. Use to understand project structure "
            "before making changes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: '.')"},
            },
            "required": [],
        },
    ),
    ToolDef(
        name="run_command",
        description=(
            "Execute a shell command and return stdout+stderr. Use for tests, builds, linting. "
            "Timeout is 30s by default."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command arguments",
                },
            },
            "required": ["command"],
        },
    ),
    ToolDef(
        name="fetch_url",
        description=(
            "Fetch a webpage and return its text content. Use to look up documentation, APIs, "
            "or check URLs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch (http/https only)"},
            },
            "required": ["url"],
        },
    ),
    ToolDef(
        name="apply_patch",
        description=(
            "Apply a unified diff patch to a file. Safer than write_file for targeted edits "
            "— only changes the specified lines."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "patch": {
                    "type": "string",
                    "description": "Unified diff format: --- a/file +++ b/file @@ ... lines",
                },
            },
            "required": ["path", "patch"],
        },
    ),
]
