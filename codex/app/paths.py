from __future__ import annotations

from pathlib import Path


class AppPaths:
    def __init__(self, project_name: str, base_dir: Path | None = None):
        if base_dir is None:
            base_dir = Path.home() / ".ilx_ai_cli"
        self.root           = base_dir
        self.workspace_root = self.root / "workspaces"
        self.workspace      = self.workspace_root / project_name
        self.logs           = self.root / "logs" / "agent_runs" / project_name
        self.prompts        = Path(__file__).resolve().parents[2] / "prompts"
        self.project_index  = self.workspace / ".project_index"

        self.workspace.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.project_index.mkdir(parents=True, exist_ok=True)
