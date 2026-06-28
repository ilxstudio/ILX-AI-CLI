"""Tests for app.core.project_memory — persistent SQLite memory store.
Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class TestProjectMemory:

    def _mem(self, tmp_path: Path):
        from app.core.project_memory import ProjectMemory
        return ProjectMemory(str(tmp_path), session_id="test-sess")

    def test_remember_and_recall(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.remember("author", "ILX Studio", kind="note")
        facts = mem.recall("author")
        assert facts
        assert facts[0].value == "ILX Studio"
        assert facts[0].key == "author"

    def test_all_facts_empty(self, tmp_path):
        mem = self._mem(tmp_path)
        assert mem.all_facts() == []

    def test_search_facts(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.remember("lang", "Python 3.12")
        mem.remember("framework", "pytest")
        hits = mem.search_facts("Python")
        assert any(f.key == "lang" for f in hits)

    def test_forget(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.remember("temp", "delete me")
        n = mem.forget("temp")
        assert n >= 1
        assert mem.recall("temp") == []

    def test_forget_unknown_key(self, tmp_path):
        mem = self._mem(tmp_path)
        assert mem.forget("nonexistent") == 0

    def test_record_fix_and_recall(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.record_fix("app/core/foo.py", "import error", "added missing import", "success")
        fixes = mem.recent_fixes()
        assert fixes
        assert fixes[0].file_path == "app/core/foo.py"
        assert fixes[0].outcome == "success"

    def test_recent_fixes_by_file(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.record_fix("a.py", "bug A", "fix A")
        mem.record_fix("b.py", "bug B", "fix B")
        fixes = mem.recent_fixes(file_path="a.py")
        assert all(f.file_path == "a.py" for f in fixes)

    def test_index_and_search_symbols(self, tmp_path):
        from app.core.project_memory import SymbolRecord
        mem = self._mem(tmp_path)
        syms = [
            SymbolRecord("main.py", "run_server", "function", "def run_server(port: int)"),
            SymbolRecord("main.py", "AppConfig", "class", "class AppConfig:"),
        ]
        mem.index_symbols(syms)
        results = mem.search_symbols("run_server")
        assert results
        assert results[0].name == "run_server"

    def test_symbol_upsert(self, tmp_path):
        from app.core.project_memory import SymbolRecord
        mem = self._mem(tmp_path)
        mem.index_symbols([SymbolRecord("a.py", "foo", "function", "def foo():")])
        mem.index_symbols([SymbolRecord("a.py", "foo", "function", "def foo(x: int):")])
        results = mem.search_symbols("foo")
        assert len(results) == 1
        assert results[0].signature == "def foo(x: int):"

    def test_context_block_empty(self, tmp_path):
        mem = self._mem(tmp_path)
        assert mem.context_block() == ""

    def test_context_block_non_empty(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.remember("convention", "use snake_case")
        block = mem.context_block()
        assert "[Project memory]" in block
        assert "convention" in block
        assert "[End project memory]" in block

    def test_stats(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.remember("k", "v")
        mem.record_fix("x.py", "p", "s")
        s = mem.stats()
        assert s["facts"] >= 1
        assert s["fixes"] >= 1
        assert "db_path" in s

    def test_close(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.close()

    def test_multiple_facts_same_key(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.remember("note", "first")
        mem.remember("note", "second")
        facts = mem.recall("note")
        assert len(facts) >= 2


class TestGetMemorySingleton:

    def test_get_memory_returns_instance(self, tmp_path):
        from app.core.project_memory import get_memory
        m = get_memory(str(tmp_path))
        assert m is not None

    def test_get_memory_same_workspace_same_instance(self, tmp_path):
        from app.core.project_memory import _INSTANCES
        key = str(tmp_path / "singleton_test")
        _INSTANCES.pop(key, None)
        from app.core.project_memory import get_memory
        m1 = get_memory(key)
        m2 = get_memory(key)
        assert m1 is m2
        _INSTANCES.pop(key, None)


class TestRouteEngine:

    def _cfg(self, provider="ollama", strategy="auto"):
        from unittest.mock import MagicMock
        cfg = MagicMock()
        cfg.provider = provider
        cfg.route_strategy = strategy
        return cfg

    def test_auto_returns_configured_provider(self):
        from app.core.route_engine import resolve_provider
        assert resolve_provider(self._cfg("anthropic", "auto")) == "anthropic"

    def test_free_only_forces_ollama(self):
        from app.core.route_engine import resolve_provider
        assert resolve_provider(self._cfg("anthropic", "free-only")) == "ollama"

    def test_local_only_forces_ollama(self):
        from app.core.route_engine import resolve_provider
        assert resolve_provider(self._cfg("openai", "local-only")) == "ollama"

    def test_is_free_tier_ollama(self):
        from app.core.route_engine import is_free_tier
        assert is_free_tier(self._cfg("ollama", "auto")) is True

    def test_is_free_tier_cloud(self):
        from app.core.route_engine import is_free_tier
        assert is_free_tier(self._cfg("anthropic", "auto")) is False

    def test_free_tier_label_local(self):
        from app.core.route_engine import free_tier_label
        label = free_tier_label(self._cfg("ollama", "auto"))
        assert "free" in label.lower() or "ollama" in label.lower()

    def test_strategy_description(self):
        from app.core.route_engine import strategy_description
        assert "cost" in strategy_description("free-only").lower()
        assert "cloud" in strategy_description("quality").lower()
        assert "default" in strategy_description("auto").lower()

    def test_quality_falls_back_to_ollama_without_keys(self):
        from unittest.mock import patch
        from app.core.route_engine import resolve_provider
        cfg = self._cfg("anthropic", "quality")
        with patch("app.core.route_engine._has_key", return_value=False):
            assert resolve_provider(cfg) == "ollama"


class TestMemoryCommands:

    def _cmds(self, tmp_path):
        from unittest.mock import MagicMock
        from cli.commands.memory_cmds import MemoryCommands
        cfg = MagicMock()
        cfg.working_folder = str(tmp_path)
        return MemoryCommands(cfg)

    def test_cmd_memory_stats(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        cmds.cmd_memory(["stats"])
        out = capsys.readouterr().out
        assert "stats" in out.lower() or "facts" in out.lower() or "memory" in out.lower()

    def test_cmd_memory_show_empty(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        cmds.cmd_memory(["show"])
        out = capsys.readouterr().out
        assert "no facts" in out.lower() or "empty" in out.lower() or "memory" in out.lower()

    def test_cmd_memory_add_and_show(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        cmds.cmd_memory(["add", "lang", "Python"])
        capsys.readouterr()
        cmds.cmd_memory(["show"])
        out = capsys.readouterr().out
        assert "lang" in out

    def test_cmd_memory_forget(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        cmds.cmd_memory(["add", "removeme", "gone"])
        cmds.cmd_memory(["forget", "removeme"])
        out = capsys.readouterr().out
        assert "deleted" in out.lower() or "1" in out

    def test_cmd_memory_fixes_empty(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        cmds.cmd_memory(["fixes"])
        out = capsys.readouterr().out
        assert "fix" in out.lower() or "no fix" in out.lower() or "record" in out.lower()

    def test_cmd_memory_search(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        cmds.cmd_memory(["add", "searchable", "find this value"])
        capsys.readouterr()
        cmds.cmd_memory(["search", "find"])
        out = capsys.readouterr().out
        assert "searchable" in out or "find" in out
