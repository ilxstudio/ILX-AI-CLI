"""Context management — @path expansion, workspace tree, system prompt assembly."""
from __future__ import annotations

import functools
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig
    from app.core.hybrid_retriever import HybridRetriever

_TEXT_EXTS = {
    ".py", ".pyi", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".json", ".jsonc", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".env",
    ".txt", ".md", ".rst", ".csv", ".xml", ".html", ".htm", ".css",
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx",
    ".cs", ".java", ".go", ".rs", ".swift", ".kt", ".rb", ".php",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".sql", ".dockerfile", ".makefile", ".cmake",
    ".idl", ".xaml", ".axaml", ".props", ".targets", ".manifest",
    ".vcxproj", ".csproj", ".sln",
}

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "x64", "x86", "Debug", "Release", ".vs", ".ilxbuild",
    "obj", "bin", ".project_index", ".pytest_cache", ".mypy_cache",
    ".tox", "dist", "build", ".eggs", "*.egg-info",
}

_MAX_FILE_CHARS  = 8_000
_MAX_TOTAL_CHARS = 40_000

@functools.lru_cache(maxsize=256)
def _cached_token_estimate(length: int, prefix_hash: int) -> int:
    """Cached inner computation for estimate_tokens."""
    return max(1, length // 4)


def estimate_tokens(text: str) -> int:
    """Rough token estimate: characters // 4 (≈ 1 token per 4 chars for English).

    Caches on (len, hash-of-first-100-chars) to avoid hashing huge strings while
    still skipping redundant arithmetic for repeated identical inputs.
    """
    return _cached_token_estimate(len(text), hash(text[:100]))


_AT_PATH_RE     = re.compile(r'@"([^"]+)"|@\'([^\']+)\'|@(\S+)')
_QUOTED_PATH_RE = re.compile(r'"((?:[A-Za-z]:[/\\]|/)[^"]+)"')
_QUESTION_RE    = re.compile(
    r"^\s*(what|who|where|when|why|how|is |are |can you (tell|explain|describe)|"
    r"could you|do you|does |did |explain |describe |tell me|show me what|"
    r"what'?s\b|help me understand)",
    re.IGNORECASE,
)


class ContextManager:
    """Builds and injects file/workspace context into prompts."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._repo_map = None
        self._repo_map_block: str = ""        # cached result updated in background
        self._repo_map_lock = threading.Lock()
        self._hybrid: HybridRetriever | None = None  # injected via set_index()
        self._refresh_repo_map()

    def set_index(self, retriever: HybridRetriever) -> None:
        """Inject a HybridRetriever so build_system_prompt() can include project symbols."""
        self._hybrid = retriever

    def set_workspace(self, workspace: str) -> None:
        self._cfg.working_folder = workspace
        self._refresh_repo_map()

    def _refresh_repo_map(self) -> None:
        wf = self._cfg.working_folder
        if wf and Path(wf).is_dir():
            try:
                from app.core.repo_map import RepoMap
                self._repo_map = RepoMap(wf)
                self._schedule_repo_map_rebuild()
            except Exception:
                self._repo_map = None
        else:
            self._repo_map = None

    def _schedule_repo_map_rebuild(self) -> None:
        """Rebuild the repo map in a daemon background thread."""
        def _build() -> None:
            if self._repo_map is None:
                return
            if not Path(self._cfg.working_folder).exists():
                return
            try:
                self._repo_map.build()
                block = self._repo_map.to_prompt_block()
                with self._repo_map_lock:
                    self._repo_map_block = block
            except Exception as exc:
                import logging
                logging.getLogger("ilx_cli.context").debug("repo map bg build error: %s", exc)
        t = threading.Thread(target=_build, daemon=True, name="repo-map-build")
        t.start()

    def read_path(self, path: Path, label: str | None = None) -> str:
        if not path.exists():
            return f"[Context: path not found: {path}]"
        if path.is_file():
            return self._read_file(path, label)
        return self._read_directory(path, label)

    def _read_file(self, path: Path, label: str | None) -> str:
        if path.suffix.lower() not in _TEXT_EXTS:
            return f"[Context: {path.name} — binary/unknown file, skipped]"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"[Context: could not read {path}: {exc}]"
        name = label or str(path)
        if len(text) > _MAX_FILE_CHARS:
            from app.core.rag import build_rag_context
            rag = build_rag_context([(path.name, text)], query="", max_chars=_MAX_FILE_CHARS)
            return f"=== {name} (RAG-extracted chunks) ===\n{rag}"
        return f"=== {name} ===\n{text}"

    def _read_directory(self, path: Path, label: str | None) -> str:
        parts: list[str] = []
        tree_lines: list[str] = []
        file_tuples: list[tuple[str, str]] = []
        total = 0

        for p in sorted(path.rglob("*")):
            if p.is_dir():
                continue
            if any(part in SKIP_DIRS for part in p.relative_to(path).parts):
                continue
            rel = p.relative_to(path).as_posix()
            tree_lines.append(f"  {rel}")
            if p.suffix.lower() not in _TEXT_EXTS:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            file_tuples.append((rel, text))
            total += len(text)

        header = f"[Directory: {label or str(path)}]\nFile tree:\n" + "\n".join(tree_lines)

        if total > _MAX_TOTAL_CHARS:
            from app.core.rag import build_rag_context
            rag = build_rag_context(file_tuples, query="", max_chars=_MAX_TOTAL_CHARS)
            body = f"(RAG-extracted chunks from {len(file_tuples)} files)\n\n{rag}"
        else:
            for rel, text in file_tuples:
                if len(text) > _MAX_FILE_CHARS:
                    text = text[:_MAX_FILE_CHARS] + f"\n... ({len(text) - _MAX_FILE_CHARS} chars truncated)"
                parts.append(f"=== {rel} ===\n{text}")
            body = "\n\n".join(parts) if parts else "(no readable text files found)"

        return header + "\n\nFile contents:\n\n" + body

    def expand_image_paths(self, text: str) -> list[str]:
        """Return absolute paths for @image references found in *text*.

        Only paths whose extension is in SUPPORTED_EXTENSIONS (vision module)
        are returned.  Non-image @paths are ignored.  This is a read-only
        scan — the text is not modified.
        """
        from app.core.vision import extract_image_paths
        return extract_image_paths(text)

    def expand_at_paths(self, text: str) -> tuple[str, list[str]]:
        """Expand @path and quoted-absolute-path references inline."""
        found: list[str] = []
        already: set[str] = set()

        def _inject(raw: str, original_token: str) -> str:
            p = Path(raw).expanduser()
            key = str(p)
            if key in already:
                return original_token
            already.add(key)
            found.append(key)
            ctx = self.read_path(p)
            return f"{original_token}\n\n[Attached context for {raw}]\n{ctx}\n"

        def _replace_at(m: re.Match) -> str:
            raw = m.group(1) or m.group(2) or m.group(3)
            return _inject(raw, m.group(0))

        text = _AT_PATH_RE.sub(_replace_at, text)

        def _replace_quoted(m: re.Match) -> str:
            raw = m.group(1)
            try:
                if Path(raw).expanduser().exists():
                    return _inject(raw, m.group(0))
            except Exception:
                pass
            return m.group(0)

        text = _QUOTED_PATH_RE.sub(_replace_quoted, text)
        return text, found

    def workspace_tree(self, max_chars: int = 2000) -> str:
        root = Path(self._cfg.working_folder) if self._cfg.working_folder else None
        if not root or not root.is_dir():
            return ""
        lines: list[str] = []
        # Sort by depth first (shallow files before nested), then by name so
        # root-level files (e.g. main.py, README.md) always appear at the top.
        all_paths = [
            p for p in root.rglob("*")
            if not p.is_dir()
            and not any(part in SKIP_DIRS for part in p.relative_to(root).parts)
        ]
        all_paths.sort(key=lambda p: (len(p.relative_to(root).parts), p.name.lower()))
        for p in all_paths:
            lines.append("  " + p.relative_to(root).as_posix())
            if len("\n".join(lines)) > max_chars:
                lines.append("  ... (truncated)")
                break
        if not lines:
            return ""
        return f"Workspace ({self._cfg.working_folder}):\n" + "\n".join(lines)

    def build_system_prompt(self, pinned: list[dict] | None = None) -> str:
        cfg = self._cfg
        base = cfg.system_prompt or (
            "You are ILX AI, a helpful assistant specialized in software development. "
            "Be concise and accurate. When showing code, use fenced code blocks."
        )

        try:
            from app.core import project_rules
            rules_prefix = project_rules.system_prompt_prefix(cfg.working_folder)
            if rules_prefix:
                base = rules_prefix + base
        except Exception:
            pass

        ws_tree = self.workspace_tree()
        if ws_tree:
            base += (
                "\n\nThe user's current workspace contains these files "
                "(they can reference them with @path for full content):\n" + ws_tree
            )

        if self._repo_map is not None:
            with self._repo_map_lock:
                map_block = self._repo_map_block
            if map_block:
                base += "\n\n" + map_block
            # Trigger a background refresh for the next call
            self._schedule_repo_map_rebuild()

        # Inject project symbols from HybridRetriever when index exists
        if self._hybrid is not None:
            try:
                index_path = Path(self._cfg.working_folder) / ".project_index" if self._cfg.working_folder else None
                if index_path is None or index_path.exists():
                    symbols_ctx = self._hybrid.query("", top_k=5, max_chars=1500)
                    if symbols_ctx:
                        base += "\n\n[Project symbols]\n" + symbols_ctx
            except Exception as exc:
                import logging as _logging
                _logging.getLogger("ilx_cli.context").debug("hybrid retriever query error: %s", exc)

        try:
            from app.core import git_helper
            git_ctx = git_helper.ambient_context(cfg.working_folder)
            if git_ctx:
                base += "\n\n" + git_ctx
        except Exception:
            pass

        # ── Pinned-file injection — strategy differs by provider ──────────────
        # Cloud models (Anthropic, OpenAI, Groq, Gemini) have large context
        # windows: inject full content of pinned files directly.
        # Ollama/local models: rely on RAG-chunked content already embedded in
        # the pinned messages themselves (built by cmd_add → read_path).
        if pinned:
            is_cloud = getattr(cfg, "provider", "ollama") != "ollama"
            if is_cloud:
                pin_blocks: list[str] = []
                for p in pinned:
                    content = p.get("content", "")
                    if content:
                        pin_blocks.append(content)
                if pin_blocks:
                    base += (
                        "\n\n[Pinned files — full content injected for context]\n"
                        + "\n\n".join(pin_blocks)
                    )
            # For Ollama the pinned messages are passed as conversation turns
            # (prepended to all_msgs in send()), so no extra injection needed.

        return base

    def describe_current(self, history: list[dict], pinned: list[dict],
                         rag=None) -> None:
        """Print a summary of what's currently in the LLM context window."""
        from cli.display import BOLD, CYAN, DIM, GREEN, RESET, YELLOW
        print(f"\n{BOLD}Context Window Stats:{RESET}")

        # System prompt
        sp = self.build_system_prompt()
        sp_tokens = estimate_tokens(sp)
        print(f"  {CYAN}System prompt  {RESET}  ~{sp_tokens:>6} tokens  ({len(sp)} chars)")

        # Conversation history
        hist_tokens = estimate_tokens(
            " ".join(m.get("content", "") for m in history)
        )
        print(
            f"  {CYAN}Chat history   {RESET}  ~{hist_tokens:>6} tokens"
            f"  ({len(history)} messages)"
        )

        # Pinned context
        if pinned:
            pin_chars = sum(len(p.get("content", "")) for p in pinned)
            pin_tokens = estimate_tokens(" ".join(p.get("content", "") for p in pinned))
            print(
                f"  {CYAN}Pinned files   {RESET}  ~{pin_tokens:>6} tokens"
                f"  ({len(pinned)} entr{'y' if len(pinned)==1 else 'ies'}"
                f", {pin_chars} chars)"
            )
        else:
            print(f"  {DIM}Pinned files      none{RESET}")
            pin_tokens = 0

        # RAG index stats (if available)
        if rag is not None:
            try:
                stats = rag.get_stats()
                n_chunks = stats.get("chunks", 0)
                n_files  = len(stats.get("files", []))
                tot_ch   = stats.get("total_chars", 0)
                print(
                    f"  {CYAN}RAG index      {RESET}  "
                    f"{n_chunks} chunks  ({n_files} file(s), {tot_ch} chars indexed)"
                )
            except Exception:
                pass
        else:
            print(f"  {DIM}RAG index         not available{RESET}")

        # Total estimate vs context window
        total = sp_tokens + hist_tokens + pin_tokens
        num_ctx = getattr(self._cfg, "num_ctx", 4096)
        pct = int(total / num_ctx * 100) if num_ctx else 0
        col = GREEN if pct < 70 else (YELLOW if pct < 90 else "\033[31m")
        bar_filled = int(pct / 5)   # 20-char bar
        bar = "#" * bar_filled + "-" * (20 - bar_filled)
        print(
            f"\n  {col}Total  ~{total} tokens  [{bar}]  {pct}%"
            f"  of num_ctx={num_ctx}{RESET}"
        )
        if pct >= 95:
            print(f"  {YELLOW}Context near limit — run /compact to free space.{RESET}")
        elif pct >= 80:
            print(f"  {DIM}Approaching limit — consider /compact to free space.{RESET}")
        print()

    @staticmethod
    def looks_like_question(text: str) -> bool:
        t = text.strip()
        if t.endswith("?"):
            return True
        return bool(_QUESTION_RE.match(t))
