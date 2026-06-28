"""Lightweight workspace symbol map — ported from ILX AI GUI.

Builds compact function/class signature blocks for system-prompt injection.
Uses Python stdlib ``ast`` for .py files, regex for JS/TS/Go/Rust/Java/etc.
Cache lives at ``<workspace>/.ilx_cli/repo_map.json``.
"""
from __future__ import annotations

import ast
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import time

_log = logging.getLogger("ilx_cli.repo_map")

_IGNORED_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".next", ".nuxt", "dist", "build", "out",
    ".idea", ".vscode", ".vs", ".cache", ".mypy_cache", ".pytest_cache",
    ".ilx_cli", ".ilx_ai", ".tox", "target", ".gradle", "vendor",
    "x64", "x86", "Debug", "Release", "obj", "bin", ".ilxbuild",
}
_IGNORED_SUFFIXES = {
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
    ".zip", ".tar", ".gz", ".7z", ".whl",
    ".mp3", ".mp4", ".wav", ".ogg", ".mov",
    ".sqlite", ".db", ".lock",
}
_INDEXED_SUFFIXES = {
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx",
    ".go", ".rs",
    ".java", ".kt",
    ".rb", ".php",
    ".cs", ".cpp", ".c", ".h", ".hpp",
}
MAX_FILE_BYTES   = 256 * 1024
MAX_FILES        = 1500
PROMPT_BUDGET_KB = 8


@dataclass
class FileEntry:
    rel_path: str
    mtime:    float
    size:     int
    symbols:  list[str] = field(default_factory=list)
    imports:  list[str] = field(default_factory=list)


def _python_symbols(src: str) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return [], []
    syms: list[str] = []
    imps: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            syms.append(_py_func_signature(node))
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(_py_short(b) for b in node.bases)
            head = f"class {node.name}({bases})" if bases else f"class {node.name}"
            syms.append(head)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    syms.append("  " + _py_func_signature(child))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imps.append("import " + alias.name + (f" as {alias.asname}" if alias.asname else ""))
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * (node.level or 0)) + (node.module or "")
            names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
            imps.append(f"from {mod} import {names}")
    return syms, imps


def _py_short(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return getattr(node, "id", "?")


def _py_func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args: list[str] = []
    a = node.args
    pos = list(a.posonlyargs) + list(a.args)
    defaults = list(a.defaults)
    pad = len(pos) - len(defaults)
    for i, p in enumerate(pos):
        s = p.arg
        if p.annotation is not None:
            s += f": {_py_short(p.annotation)}"
        if i >= pad:
            s += "=" + _py_short(defaults[i - pad])
        args.append(s)
    if a.vararg:
        args.append("*" + a.vararg.arg)
    for k, kw in zip(a.kwonlyargs, a.kw_defaults):
        s = k.arg
        if k.annotation is not None:
            s += f": {_py_short(k.annotation)}"
        if kw is not None:
            s += "=" + _py_short(kw)
        args.append(s)
    if a.kwarg:
        args.append("**" + a.kwarg.arg)
    head = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    sig = f"{head}{node.name}({', '.join(args)})"
    if node.returns is not None:
        sig += f" -> {_py_short(node.returns)}"
    return sig


_PATTERNS = {
    "js":   re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(function|class|const|let|var)\s+(\w+)", re.M),
    "ts":   re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?(function|class|interface|type|const|enum)\s+(\w+)", re.M),
    "go":   re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", re.M),
    "rust": re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\(", re.M),
    "java": re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:abstract\s+)?(?:class|interface)\s+(\w+)", re.M),
    "ruby": re.compile(r"^\s*(?:def|class|module)\s+(\w+)", re.M),
    "php":  re.compile(r"^\s*(?:public\s+|private\s+|protected\s+)?function\s+(\w+)", re.M),
    "cs":   re.compile(r"^\s*(?:public|private|protected|internal|static|abstract|override|virtual|async)?\s*(?:class|interface|struct|enum|void|\w+)\s+(\w+)\s*[\(\{]", re.M),
    "cpp":  re.compile(r"^\s*(?:\w[\w:*&<> ]+\s+)?(\w+)\s*\(", re.M),
}


def _generic_symbols(src: str, suffix: str) -> list[str]:
    lang = {
        ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
        ".ts": "ts", ".tsx": "ts",
        ".go": "go", ".rs": "rust",
        ".java": "java", ".kt": "java",
        ".rb": "ruby", ".php": "php",
        ".cs": "cs",
        ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp",
        ".c": "cpp", ".h": "cpp", ".hpp": "cpp",
    }.get(suffix)
    if lang is None or lang not in _PATTERNS:
        return []
    out: list[str] = []
    for m in _PATTERNS[lang].finditer(src):
        out.append(m.group(0).strip()[:120])
        if len(out) >= 80:
            break
    return out


def _index_file(path: Path) -> tuple[list[str], list[str], bool]:
    suffix = path.suffix.lower()
    if suffix not in _INDEXED_SUFFIXES:
        return [], [], False
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return [], [], True
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], [], False
    if suffix in (".py", ".pyi"):
        syms, imps = _python_symbols(text)
        return syms, imps, False
    return _generic_symbols(text, suffix), [], False


class RepoMap:
    """Lazy, mtime-invalidated symbol index for a workspace."""

    TTL_SECONDS = 300

    def __init__(self, workspace: str):
        self._workspace = Path(workspace).resolve()
        self._cache_dir = self._workspace / ".ilx_cli"
        self._cache_path = self._cache_dir / "repo_map.json"
        self._entries: dict[str, FileEntry] = {}
        self._loaded = False
        self._last_full_build: float = 0.0
        self._skipped_oversized: list[str] = []

    def _load_cache(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for rel, data in raw.items():
            try:
                self._entries[rel] = FileEntry(**data)
            except TypeError:
                continue

    def _save_cache(self) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps({k: asdict(v) for k, v in self._entries.items()}, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            _log.debug("repo_map: cache write failed: %s", exc)

    def build(self, *, force: bool = False) -> dict[str, FileEntry]:
        self._load_cache()
        if not force and (time() - self._last_full_build) > self.TTL_SECONDS:
            force = True
        seen: set[str] = set()
        count = 0
        skipped: list[str] = []

        # Separate cache hits from files that need (re)indexing.
        to_index: list[tuple[str, Path, float, int]] = []  # (rel, path, mtime, size)

        for path in self._iter_files():
            if count >= MAX_FILES:
                break
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = str(path.relative_to(self._workspace)).replace("\\", "/")
            seen.add(rel)
            cached = self._entries.get(rel)
            if (
                not force
                and cached is not None
                and cached.mtime == stat.st_mtime
                and cached.size == stat.st_size
            ):
                count += 1
                if cached.size > MAX_FILE_BYTES and not cached.symbols:
                    skipped.append(rel)
                continue
            to_index.append((rel, path, stat.st_mtime, stat.st_size))
            count += 1

        # Parallel indexing of stale/new files using a thread pool.
        # _index_file is read-only and stateless — safe to parallelize.
        if to_index:
            workers = min(8, len(to_index))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {
                    pool.submit(_index_file, p): (rel, p, mtime, size)
                    for rel, p, mtime, size in to_index
                }
                for fut in as_completed(futs):
                    rel, _path, mtime, size = futs[fut]
                    try:
                        symbols, imports, oversized = fut.result()
                    except Exception as exc:
                        _log.debug("repo_map: index error for %s: %s", rel, exc)
                        symbols, imports, oversized = [], [], False
                    if oversized:
                        skipped.append(rel)
                    self._entries[rel] = FileEntry(
                        rel_path=rel, mtime=mtime, size=size,
                        symbols=symbols, imports=imports,
                    )

        for rel in list(self._entries):
            if rel not in seen:
                self._entries.pop(rel, None)

        self._skipped_oversized = skipped
        self._last_full_build = time()
        self._save_cache()
        return self._entries

    def _iter_files(self):
        if not self._workspace.is_dir():
            return
        stack: list[Path] = [self._workspace]
        while stack:
            cur = stack.pop()
            try:
                children = list(cur.iterdir())
            except OSError:
                continue
            for child in children:
                name = child.name
                if child.is_dir():
                    if name in _IGNORED_DIRS or name.startswith("."):
                        continue
                    stack.append(child)
                    continue
                if child.is_file():
                    if child.suffix.lower() in _IGNORED_SUFFIXES:
                        continue
                    yield child

    def to_prompt_block(self, *, budget_kb: int = PROMPT_BUDGET_KB,
                        include_imports: bool = True) -> str:
        if not self._entries:
            return ""
        budget_bytes = budget_kb * 1024
        items = sorted(self._entries.values(), key=lambda e: e.rel_path)
        lines: list[str] = ["[Workspace map — function/class signatures]"]
        used = len(lines[0]) + 1
        truncated = False
        for entry in items:
            if not entry.symbols:
                continue
            block = [f"\n{entry.rel_path}"]
            block.extend(f"  {s}" for s in entry.symbols)
            chunk = "\n".join(block)
            if used + len(chunk) > budget_bytes:
                truncated = True
                break
            lines.append(chunk)
            used += len(chunk) + 1
        if truncated:
            lines.append(f"\n[…workspace map truncated at {budget_kb} KB]")
        if self._skipped_oversized:
            preview = ", ".join(self._skipped_oversized[:5])
            extra = f" (+{len(self._skipped_oversized) - 5} more)" if len(self._skipped_oversized) > 5 else ""
            lines.append(f"\n[index: skipped {len(self._skipped_oversized)} file(s) >{MAX_FILE_BYTES // 1024} KB: {preview}{extra}]")
        if include_imports:
            graph_lines: list[str] = []
            for entry in items:
                if not entry.imports or not entry.rel_path.endswith(".py"):
                    continue
                local_imps: list[str] = []
                for imp in entry.imports:
                    target = _resolve_local_import(imp, entry.rel_path, self._entries)
                    if target:
                        local_imps.append(target)
                if local_imps:
                    graph_lines.append(f"  {entry.rel_path} -> {', '.join(sorted(set(local_imps)))}")
            if graph_lines:
                lines.append("\n[Local import graph]")
                lines.extend(graph_lines[:60])
        return "\n".join(lines).strip()


def _resolve_local_import(imp_line: str, current_rel: str,
                           entries: dict[str, FileEntry]) -> str | None:
    parts = imp_line.split()
    if not parts:
        return None
    if parts[0] == "import" and len(parts) >= 2:
        mod = parts[1].split(".")[0]
    elif parts[0] == "from" and len(parts) >= 4:
        mod_full = parts[1].lstrip(".")
        mod = mod_full.split(".")[0]
    else:
        return None
    if not mod:
        return None
    for cand in (f"{mod}.py", f"{mod}/__init__.py", f"{mod}/main.py"):
        for rel in entries:
            if rel == cand or rel.endswith("/" + cand):
                if rel != current_rel:
                    return rel
    return None
