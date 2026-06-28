from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ChunkRecord:
    file:     str
    chunk_id: str
    lines:    str
    summary:  str


@dataclass
class FileSummary:
    file:       str
    line_count: int
    preview:    str


class ProjectChunker:
    CHUNK_SIZE     = 60
    CONTEXT_RADIUS = 30
    SKIP_DIRS      = {".project_index", "__pycache__", ".git", "node_modules"}
    TEXT_EXTENSIONS = {
        ".py", ".pyi", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
        ".json", ".jsonc", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".env",
        ".txt", ".md", ".rst", ".csv", ".xml", ".html", ".htm", ".css",
        ".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx",
        ".cs", ".java", ".go", ".rs", ".swift", ".kt", ".rb", ".php",
        ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
        ".sql", ".makefile", ".cmake",
        ".idl", ".xaml", ".axaml", ".props", ".targets", ".manifest",
        ".vcxproj", ".csproj", ".sln",
    }

    def __init__(self, workspace: Path, index_dir: Path) -> None:
        self.workspace = workspace
        self.index_dir = index_dir
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def index_workspace(self) -> None:
        file_tree:      list[str]  = []
        file_summaries: list[dict] = []
        chunk_summaries: list[dict] = []

        for abs_path in self._walk():
            rel = abs_path.relative_to(self.workspace).as_posix()
            file_tree.append(rel)
            lines = self._read_lines(rel)
            non_empty = [l.rstrip() for l in lines if l.strip()]
            preview   = " | ".join(non_empty[:5])
            file_summaries.append(asdict(FileSummary(
                file=rel, line_count=len(lines), preview=preview,
            )))
            chunk_count = max(1, (len(lines) + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE)
            for chunk_idx in range(chunk_count):
                start = chunk_idx * self.CHUNK_SIZE
                end   = min(start + self.CHUNK_SIZE, len(lines))
                chunk_lines     = lines[start:end]
                first_non_empty = next((l.rstrip() for l in chunk_lines if l.strip()), "")
                chunk_summaries.append(asdict(ChunkRecord(
                    file=rel, chunk_id=f"{rel}:{chunk_idx + 1}",
                    lines=f"{start + 1}-{end}", summary=first_non_empty,
                )))

        self._write_json("file_tree.json",     file_tree)
        self._write_json("file_summaries.json", file_summaries)
        self._write_json("chunk_summaries.json", chunk_summaries)

    def get_chunk(self, file: str, start_line: int, end_line: int) -> str:
        lines = self._read_lines(file)
        if not lines:
            return ""
        lo    = max(0, start_line - 1)
        hi    = min(len(lines), end_line)
        width = len(str(hi))
        parts: list[str] = []
        for i, line in enumerate(lines[lo:hi], start=lo + 1):
            parts.append(f"{i:{width}} | {line.rstrip()}")
        return "\n".join(parts)

    def find_chunk_for_error(self, traceback_str: str) -> str:
        pattern = re.compile(r'File "([^"]+)", line (\d+)')
        matches = pattern.findall(traceback_str)
        if not matches:
            return ""
        raw_path, line_str = matches[-1]
        error_line = int(line_str)
        abs_path = Path(raw_path)
        if abs_path.is_absolute():
            try:
                rel = abs_path.relative_to(self.workspace).as_posix()
            except ValueError:
                return ""
        else:
            rel = abs_path.as_posix()
        start = max(1, error_line - self.CONTEXT_RADIUS)
        end   = error_line + self.CONTEXT_RADIUS
        return self.get_chunk(rel, start, end)

    def get_file_tree(self) -> str:
        tree_path = self.index_dir / "file_tree.json"
        if not tree_path.exists():
            self.index_workspace()
        data: list[str] = json.loads(tree_path.read_text(encoding="utf-8"))
        return "\n".join(data)

    def get_file_contents(
        self,
        max_lines_per_file: int = 200,
        max_total_chars:    int = 6000,
    ) -> str:
        parts: list[str] = []
        total = 0
        for abs_path in self._walk():
            if total >= max_total_chars:
                parts.append("... (remaining files omitted — workspace snapshot too large)")
                break
            rel   = abs_path.relative_to(self.workspace).as_posix()
            lines = self._read_lines(rel)
            if not lines:
                continue
            content = "".join(lines[:max_lines_per_file])
            if len(lines) > max_lines_per_file:
                content += f"\n... ({len(lines) - max_lines_per_file} more lines truncated)"
            entry = f"=== {rel} ===\n{content}"
            total += len(entry)
            parts.append(entry)
        if not parts:
            return ""
        return "Current file contents:\n\n" + "\n\n".join(parts)

    def _walk(self):
        for path in sorted(self.workspace.rglob("*")):
            if path.is_dir():
                continue
            if any(part in self.SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in self.TEXT_EXTENSIONS:
                continue
            yield path

    def _read_lines(self, rel_path: str) -> list[str]:
        abs_path = self.workspace / rel_path
        if not abs_path.exists():
            return []
        try:
            return abs_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except Exception:
            return []

    def _write_json(self, filename: str, data: object) -> None:
        out = self.index_dir / filename
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
