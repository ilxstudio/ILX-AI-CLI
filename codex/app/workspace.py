from __future__ import annotations

import shutil
from pathlib import Path


class WorkspaceManager:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def safe_path(self, relative_path: str) -> Path:
        resolved = (self.workspace / relative_path).resolve()
        try:
            resolved.relative_to(self.workspace)
        except ValueError:
            raise ValueError(
                f"Path traversal blocked: '{relative_path}' resolves outside workspace"
            )
        return resolved

    def write_file(self, path: str, content: str) -> None:
        target = self.safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read_file(self, path: str) -> str:
        target = self.safe_path(path)
        if not target.exists():
            raise FileNotFoundError(f"File not found in workspace: '{path}'")
        return target.read_text(encoding="utf-8")

    def delete_file(self, path: str) -> None:
        target = self.safe_path(path)
        if target.exists():
            target.unlink()

    def list_files(self, pattern: str = "**/*") -> list[str]:
        results: list[str] = []
        for p in self.workspace.glob(pattern):
            if not p.is_file():
                continue
            rel = p.relative_to(self.workspace)
            if ".project_index" in rel.parts:
                continue
            results.append(rel.as_posix())
        return results

    def snapshot(self, name: str) -> None:
        dest = self.workspace.parent / name
        if dest.exists():
            try:
                shutil.rmtree(dest)
            except OSError as exc:
                raise RuntimeError(f"Cannot remove existing snapshot {dest}: {exc}") from exc
        try:
            shutil.copytree(self.workspace, dest)
        except OSError as exc:
            raise RuntimeError(f"Cannot create snapshot {dest}: {exc}") from exc
