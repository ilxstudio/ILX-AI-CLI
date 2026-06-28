"""Session persistence — save/load/list JSONL conversation sessions."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.session")
_SESSION_DIR = Path.home() / ".ilx_cli" / "sessions"


class SessionManager:
    """Manages JSONL conversation session files in ~/.ilx_cli/sessions/."""

    def __init__(self, session_dir: Path | None = None) -> None:
        self._dir = session_dir or _SESSION_DIR

    def save(self, history: list[dict], cfg: "AppConfig", title: str = "") -> Path | None:
        """Persist history to a timestamped JSONL file. Returns path or None on error."""
        if not history:
            return None
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = self._dir / f"{ts}.jsonl"
            with out.open("w", encoding="utf-8") as f:
                meta = {
                    "_meta":     True,
                    "workspace": cfg.working_folder,
                    "model":     cfg.ollama_model,
                    "provider":  cfg.provider,
                    "ts":        datetime.now().isoformat(),
                    "title":     title,
                }
                f.write(json.dumps(meta) + "\n")
                for msg in history:
                    f.write(json.dumps(msg) + "\n")
            return out
        except OSError as exc:
            _log.warning("could not save session: %s", exc)
            return None

    def list(self, n: int = 10) -> list[Path]:
        """Return the n most-recently-modified session files."""
        try:
            files = sorted(
                self._dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            return files[:n]
        except OSError:
            return []

    def load(self, path: Path) -> tuple[dict, list[dict]]:
        """Load a session file. Returns (meta, messages)."""
        meta: dict = {}
        messages: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("_meta"):
                    meta = obj
                else:
                    messages.append(obj)
        except OSError as exc:
            _log.warning("could not load session %s: %s", path, exc)
        return meta, messages

    def set_title(self, path: Path, title: str) -> None:
        """Update the title field in the first line of a session file."""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                return
            meta = json.loads(lines[0])
            meta["title"] = title
            lines[0] = json.dumps(meta)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass

    def export_markdown(self, history: list[dict], cfg: "AppConfig",
                        path: Path | None = None) -> Path | None:
        """Export current conversation history to a Markdown file.

        If *path* is None, writes to ``~/Desktop/ilx_export_<ts>.md``.
        Returns the written path on success, None on error.
        """
        if not history:
            return None
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if path is None:
            desktop = Path.home() / "Desktop"
            desktop.mkdir(parents=True, exist_ok=True)
            path = desktop / f"ilx_export_{ts}.md"
        try:
            lines: list[str] = [
                f"# ILX AI CLI — Conversation Export\n",
                f"**Exported:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
                f"**Provider:** {cfg.provider}  **Model:** {cfg.ollama_model}  ",
                f"**Workspace:** {cfg.working_folder}\n",
                "---\n",
            ]
            for msg in history:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if role == "system":
                    lines.append(f"> **[System]** {content}\n")
                elif role == "user":
                    lines.append(f"## You\n\n{content}\n")
                elif role == "assistant":
                    lines.append(f"## ILX AI\n\n{content}\n")
                lines.append("---\n")
            path.write_text("\n".join(lines), encoding="utf-8")
            return path
        except OSError as exc:
            _log.warning("export_markdown failed: %s", exc)
            return None

    def format_listing(self, sessions: list[Path]) -> str:
        """Return a formatted string listing sessions for display."""
        if not sessions:
            return f"  No saved sessions in {self._dir}"
        lines = [""]
        for i, sf in enumerate(sessions, 1):
            meta, msgs = self.load(sf)
            ws    = meta.get("workspace", "?")
            model = meta.get("model", "?")
            prov  = meta.get("provider", "ollama")
            ts_raw = meta.get("ts", sf.stem)
            title  = meta.get("title", "")
            try:
                ts_str = datetime.fromisoformat(ts_raw).strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts_str = sf.stem
            title_part = f"  \"{title}\"" if title else ""
            lines.append(
                f"  [{i}] {ts_str}  {prov}/{model}  workspace={ws}"
                f"  ({len(msgs)} messages){title_part}"
            )
        return "\n".join(lines)
