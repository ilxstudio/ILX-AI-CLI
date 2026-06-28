from __future__ import annotations
import difflib
import re
from pathlib import Path


def safe_resolve(path: str, working_folder: str) -> str | None:
    try:
        wf     = Path(working_folder).resolve()
        target = (wf / path).resolve()
        target.relative_to(wf)
        return str(target)
    except (ValueError, OSError):
        return None


def compute_diff(old: str, new: str, filename: str = "file") -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3,
    )
    return "".join(diff)


def detect_language(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".py":   "python",
        ".js":   "javascript",
        ".ts":   "typescript",
        ".jsx":  "javascript",
        ".tsx":  "typescript",
        ".sh":   "bash",
        ".bash": "bash",
        ".zsh":  "bash",
        ".json": "json",
        ".md":   "markdown",
        ".html": "html",
        ".css":  "css",
        ".yml":  "yaml",
        ".yaml": "yaml",
        ".toml": "toml",
        ".rs":   "rust",
        ".go":   "go",
        ".c":    "c",
        ".cpp":  "cpp",
        ".java": "java",
    }.get(ext, "text")


def extract_code_block(text: str) -> str | None:
    pattern = r"```(?:python|py)?\n(.*?)```"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1).rstrip()
    m = re.search(r"```\w*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).rstrip()
    return None
