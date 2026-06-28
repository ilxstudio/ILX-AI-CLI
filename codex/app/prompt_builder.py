from __future__ import annotations

from pathlib import Path

RESPONSE_SCHEMA = """{
  "summary": "what you did",
  "files": [
    {
      "path": "relative/path/to/file.py",
      "action": "replace",
      "content": "full file content here"
    }
  ],
  "command_to_run": null
}"""

# Hardcoded fallbacks — used when the prompts/ directory is missing or mislocated.
# Keep in sync with prompts/initial_prompt.txt and prompts/repair_prompt.txt.
_FALLBACK_INITIAL = """You are an expert software engineer working inside a local code workspace.

TASK:
{task}

WORKSPACE FILE TREE:
{file_tree}

{file_contents}

RULES:
{rules}

YOUR RESPONSE MUST BE A SINGLE VALID JSON OBJECT — nothing else.
No markdown fences. No prose before or after. The JSON must be parseable with json.loads().

Use this exact schema:
{schema}

Actions: "replace" (overwrite entire file), "append" (add to end), "delete" (remove file).
Always write COMPLETE file content — never use ellipsis or "rest unchanged".
"""

_FALLBACK_REPAIR = """You are an expert software engineer. A previous attempt to complete a coding task failed.

TASK:
{task}

ERROR FROM PREVIOUS ATTEMPT:
{error}

RELEVANT CODE CHUNK (if any):
{chunk}

PREVIOUS ATTEMPTS SUMMARY:
{previous_attempts}

RULES:
{rules}

Analyze the error carefully and fix it. YOUR RESPONSE MUST BE A SINGLE VALID JSON OBJECT.
No markdown fences. No prose. Parseable with json.loads().

Use this exact schema:
{schema}

Always write COMPLETE file content — never use ellipsis or "rest unchanged".
"""


class PromptBuilder:
    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir

    def build_initial(
        self,
        task:          str,
        file_tree:     str = "",
        file_contents: str = "",
        rules:         str = "",
    ) -> str:
        template = self._load("initial_prompt.txt", _FALLBACK_INITIAL)
        return (
            template
            .replace("{task}",          task)
            .replace("{file_tree}",     file_tree or "(empty workspace — create files as needed)")
            .replace("{file_contents}", file_contents)
            .replace("{rules}",         rules)
            .replace("{schema}",        RESPONSE_SCHEMA)
        )

    def build_repair(
        self,
        task:              str,
        error:             str,
        chunk:             str,
        previous_attempts: str,
        rules:             str = "",
    ) -> str:
        template = self._load("repair_prompt.txt", _FALLBACK_REPAIR)
        return (
            template
            .replace("{task}",              task)
            .replace("{error}",             error)
            .replace("{chunk}",             chunk)
            .replace("{previous_attempts}", previous_attempts)
            .replace("{rules}",             rules)
            .replace("{schema}",            RESPONSE_SCHEMA)
        )

    def _load(self, filename: str, fallback: str) -> str:
        path = self.prompts_dir / filename
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            pass
        return fallback
