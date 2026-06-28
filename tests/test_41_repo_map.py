"""Unit tests for app/core/repo_map.py."""
# Copyright 2026 ILX Studio — MIT License
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.repo_map import RepoMap, _python_symbols, _generic_symbols


# ── 1. RepoMap.__init__ sets root ─────────────────────────────────────────────


def test_repo_map_init_sets_root(tmp_path: Path):
    rm = RepoMap(str(tmp_path))
    assert rm._workspace == tmp_path.resolve()


# ── 2. _python_symbols() extracts names from .py source ───────────────────────


def test_repo_map_python_symbols():
    src = (
        "class MyClass:\n"
        "    def method(self): pass\n"
        "\n"
        "def standalone(x, y): return x + y\n"
    )
    syms, imps = _python_symbols(src)
    sym_text = " ".join(syms)
    assert "MyClass" in sym_text
    assert "standalone" in sym_text


# ── 3. _generic_symbols() returns non-empty list for JS source ────────────────


def test_repo_map_generic_symbols():
    js_src = (
        "function greet(name) {\n"
        "    return 'Hello ' + name;\n"
        "}\n"
        "const PI = 3.14;\n"
    )
    result = _generic_symbols(js_src, ".js")
    assert len(result) > 0


# ── 4. build() populates _entries for .py files ───────────────────────────────


def test_repo_map_build_indexes_files(tmp_path: Path):
    (tmp_path / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("from utils import helper\ndef run(): helper()\n", encoding="utf-8")

    rm = RepoMap(str(tmp_path))
    entries = rm.build()

    rel_keys = set(entries.keys())
    assert any("utils.py" in k for k in rel_keys)
    assert any("main.py" in k for k in rel_keys)


# ── 5. to_prompt_block() on empty index returns empty string ──────────────────


def test_repo_map_to_prompt_block_empty(tmp_path: Path):
    rm = RepoMap(str(tmp_path))
    # Don't call build() — _entries stays empty
    block = rm.to_prompt_block()
    assert block == ""


# ── 6. to_prompt_block() on populated index includes file names ───────────────


def test_repo_map_to_prompt_block_nonempty(tmp_path: Path):
    (tmp_path / "api.py").write_text("def handle_request(req): pass\n", encoding="utf-8")

    rm = RepoMap(str(tmp_path))
    rm.build()
    block = rm.to_prompt_block()

    assert "api.py" in block
    assert "handle_request" in block


# ── 7. build() twice without changes — second call uses cache ────────────────


def test_repo_map_mtime_cache_hit(tmp_path: Path):
    (tmp_path / "mod.py").write_text("class Mod: pass\n", encoding="utf-8")

    rm = RepoMap(str(tmp_path))
    entries1 = rm.build(force=True)

    # Second call without file changes — should not error and return same keys
    entries2 = rm.build(force=False)
    assert set(entries1.keys()) == set(entries2.keys())


# ── 8. build() skips .git dir contents ───────────────────────────────────────


def test_repo_map_skips_hidden_dirs(tmp_path: Path):
    # Create a .git dir with a Python-like file inside
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config.py").write_text("def git_internal(): pass\n", encoding="utf-8")

    # Also create a real source file
    (tmp_path / "app.py").write_text("def real_function(): pass\n", encoding="utf-8")

    rm = RepoMap(str(tmp_path))
    entries = rm.build()

    # .git internals must not be indexed
    for key in entries:
        assert ".git" not in key

    # The real file should be indexed
    assert any("app.py" in k for k in entries)
