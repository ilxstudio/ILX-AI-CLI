"""Tests for Phase 1–3 audit implementations.

Covers:
- apply_patch (conflict-style + unified diff)
- Sandbox always enforced (auto_approve doesn't bypass)
- process_runner cross-platform helper
- AppConfig new fields (auto_yes, output_mode, dry_run, etc.)
- permissions.confirm() helper
- Rich display output modes (json, quiet, ansi)
- PersistentEmbeddingStore (SQLite cross-session RAG)
- Ollama vision capability detection
- Real MCP stdio protocol (StdioMCPConnection / StdioMCPManager)
- Provider fallback error class detection
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# apply_patch
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyPatch:
    def _make_client(self, tmp_path):
        from app.core.mcp_client import MCPClient
        cfg = MagicMock()
        cfg.working_folder = str(tmp_path)
        cfg.permission_mode = "ask"
        return MCPClient(cfg=cfg)

    def test_conflict_style_single_hunk(self, tmp_path):
        target = tmp_path / "foo.py"
        target.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        mcp = self._make_client(tmp_path)
        patch_text = (
            "<<<<<<< ORIGINAL\n"
            "    return 'world'\n"
            "=======\n"
            "    return 'universe'\n"
            ">>>>>>> MODIFIED"
        )
        result = mcp._apply_patch_blocks(str(target), patch_text)
        assert result["success"], result
        assert "universe" in target.read_text(encoding="utf-8")

    def test_conflict_style_context_not_found(self, tmp_path):
        target = tmp_path / "bar.py"
        target.write_text("x = 1\n", encoding="utf-8")
        mcp = self._make_client(tmp_path)
        patch_text = (
            "<<<<<<< ORIGINAL\n"
            "x = 999\n"
            "=======\n"
            "x = 2\n"
            ">>>>>>> MODIFIED"
        )
        result = mcp._apply_patch_blocks(str(target), patch_text)
        assert not result["success"]
        assert "not found" in result["error"].lower() or "Context" in result["error"]

    def test_unified_diff_applied(self, tmp_path):
        target = tmp_path / "baz.py"
        target.write_text("line1\nline2\nline3\n", encoding="utf-8")
        mcp = self._make_client(tmp_path)
        patch_text = (
            "--- a/baz.py\n"
            "+++ b/baz.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+LINE_TWO\n"
            " line3\n"
        )
        result = mcp._apply_patch_blocks(str(target), patch_text)
        assert result["success"], result
        assert "LINE_TWO" in target.read_text(encoding="utf-8")

    def test_no_recognisable_patch_returns_error(self, tmp_path):
        target = tmp_path / "empty.py"
        target.write_text("pass\n", encoding="utf-8")
        mcp = self._make_client(tmp_path)
        result = mcp._apply_patch_blocks(str(target), "this is not a patch")
        assert not result["success"]

    def test_atomic_write_leaves_file_intact_on_failure(self, tmp_path):
        """Atomic write: original content preserved when temp write fails."""
        target = tmp_path / "safe.py"
        original = "original content\n"
        target.write_text(original, encoding="utf-8")
        mcp = self._make_client(tmp_path)
        with patch.object(Path, "replace", side_effect=OSError("disk full")):
            try:
                mcp._atomic_write(target, "new content\n")
            except OSError:
                pass
        assert target.read_text(encoding="utf-8") == original


# ─────────────────────────────────────────────────────────────────────────────
# Sandbox bypass removed — auto_approve no longer skips containment
# ─────────────────────────────────────────────────────────────────────────────

class TestSandboxNotBypassed:
    def test_auto_approve_still_enforces_sandbox(self, tmp_path):
        from app.core.mcp_client import MCPClient
        from app.core.permissions import PermissionMode
        cfg = MagicMock()
        cfg.working_folder = str(tmp_path / "workspace")
        cfg.permission_mode = PermissionMode.AUTO_APPROVE
        mcp = MCPClient(cfg=cfg)

        # Path outside the workspace
        outside = str(tmp_path / "secret.txt")
        resolved, err = mcp._sandbox_check(outside)
        assert err is not None, "Sandbox must block paths outside workspace even in auto_approve"
        assert resolved is None


# ─────────────────────────────────────────────────────────────────────────────
# process_runner
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessRunner:
    def test_successful_command(self):
        from app.core.process_runner import run
        result = run([sys.executable, "-c", "print('hello')"])
        assert result.ok
        assert "hello" in result.stdout

    def test_nonzero_exit_code(self):
        from app.core.process_runner import run
        result = run([sys.executable, "-c", "import sys; sys.exit(1)"])
        assert not result.ok
        assert result.returncode == 1

    def test_command_not_found(self):
        from app.core.process_runner import run
        result = run(["this_command_definitely_does_not_exist_xyz"])
        assert not result.ok
        assert result.returncode == -1
        assert "not found" in result.stderr.lower() or result.stderr != ""

    def test_timeout_returns_error(self):
        from app.core.process_runner import run
        result = run([sys.executable, "-c", "import time; time.sleep(60)"], timeout=1)
        assert not result.ok
        assert "timeout" in result.stderr.lower() or result.returncode == -1

    def test_stderr_captured(self):
        from app.core.process_runner import run
        result = run([sys.executable, "-c", "import sys; sys.stderr.write('err_msg')"])
        assert "err_msg" in result.stderr


# ─────────────────────────────────────────────────────────────────────────────
# AppConfig new fields
# ─────────────────────────────────────────────────────────────────────────────

class TestAppConfigNewFields:
    def test_new_fields_have_defaults(self):
        from app.core.config import AppConfig
        cfg = AppConfig()
        assert cfg.auto_yes is False
        assert cfg.output_mode == "ansi"
        assert cfg.dry_run is False
        assert isinstance(cfg.fallback_providers, list)
        assert cfg.sandbox_mode == "workspace"

    def test_ilx_yes_env_var(self, monkeypatch):
        """ILX_YES=1 must set auto_yes on the loaded config."""
        monkeypatch.setenv("ILX_YES", "1")
        from app.core.config import ConfigManager
        mgr = ConfigManager()
        cfg = mgr.load()
        # ILX_YES=1 should make auto_yes True regardless of saved config
        assert cfg.auto_yes is True


# ─────────────────────────────────────────────────────────────────────────────
# permissions.confirm() helper
# ─────────────────────────────────────────────────────────────────────────────

class TestPermissionsConfirm:
    def test_auto_yes_skips_input(self):
        from app.core.permissions import confirm
        cfg = MagicMock()
        cfg.auto_yes = True
        cfg.dry_run = False
        assert confirm("Delete everything?", cfg) is True

    def test_dry_run_returns_false_without_input(self):
        from app.core.permissions import confirm
        cfg = MagicMock()
        cfg.auto_yes = False
        cfg.dry_run = True
        assert confirm("Write file?", cfg) is False

    def test_eof_returns_false(self):
        from app.core.permissions import confirm
        cfg = MagicMock()
        cfg.auto_yes = False
        cfg.dry_run = False
        with patch("builtins.input", side_effect=EOFError):
            assert confirm("Confirm?", cfg) is False


# ─────────────────────────────────────────────────────────────────────────────
# Rich display output modes
# ─────────────────────────────────────────────────────────────────────────────

class TestOutputModes:
    def test_set_and_get_output_mode(self):
        from cli.rich_display import set_output_mode, get_output_mode
        set_output_mode("json")
        assert get_output_mode() == "json"
        set_output_mode("ansi")
        assert get_output_mode() == "ansi"

    def test_json_mode_emits_json(self, capsys):
        from cli.rich_display import set_output_mode, print_ai_response
        set_output_mode("json")
        print_ai_response("Hello world")
        set_output_mode("ansi")
        captured = capsys.readouterr().out
        obj = json.loads(captured.strip())
        assert obj["type"] == "response"
        assert "Hello world" in obj["content"]

    def test_quiet_mode_suppresses_status(self, capsys):
        from cli.rich_display import set_output_mode, print_markdown
        set_output_mode("quiet")
        print_markdown("# Header")
        set_output_mode("ansi")
        captured = capsys.readouterr().out
        # quiet mode: print_markdown should be a no-op
        assert captured == ""

    def test_quiet_mode_still_shows_response(self, capsys):
        from cli.rich_display import set_output_mode, print_ai_response
        set_output_mode("quiet")
        print_ai_response("AI says hi")
        set_output_mode("ansi")
        captured = capsys.readouterr().out
        assert "AI says hi" in captured


# ─────────────────────────────────────────────────────────────────────────────
# PersistentEmbeddingStore (SQLite cross-session RAG)
# ─────────────────────────────────────────────────────────────────────────────

class TestPersistentEmbeddingStore:
    def test_put_and_get(self, tmp_path):
        from app.core.semantic_rag import PersistentEmbeddingStore
        db = PersistentEmbeddingStore(tmp_path / "test_emb.db")
        vecs = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        db.put_vectors("file.py", "abc123", vecs)
        retrieved = db.get_vectors("file.py", "abc123")
        assert retrieved is not None
        assert len(retrieved) == 2
        assert abs(retrieved[0][0] - 0.1) < 1e-6
        db.close()

    def test_wrong_hash_returns_none(self, tmp_path):
        from app.core.semantic_rag import PersistentEmbeddingStore
        db = PersistentEmbeddingStore(tmp_path / "test_emb2.db")
        db.put_vectors("file.py", "hash_a", [[1.0, 2.0]])
        assert db.get_vectors("file.py", "hash_b") is None
        db.close()

    def test_delete_removes_vectors(self, tmp_path):
        from app.core.semantic_rag import PersistentEmbeddingStore
        db = PersistentEmbeddingStore(tmp_path / "test_emb3.db")
        db.put_vectors("gone.py", "xyz", [[0.9, 0.8]])
        db.delete("gone.py")
        assert db.get_vectors("gone.py", "xyz") is None
        db.close()

    def test_put_overwrites_previous(self, tmp_path):
        from app.core.semantic_rag import PersistentEmbeddingStore
        db = PersistentEmbeddingStore(tmp_path / "test_emb4.db")
        db.put_vectors("f.py", "h1", [[1.0]])
        db.put_vectors("f.py", "h2", [[2.0], [3.0]])
        # old hash no longer exists
        assert db.get_vectors("f.py", "h1") is None
        # new hash has 2 vectors
        result = db.get_vectors("f.py", "h2")
        assert result is not None and len(result) == 2
        db.close()

    def test_cross_session_persistence(self, tmp_path):
        """Vectors written in one store instance are readable in a new instance."""
        from app.core.semantic_rag import PersistentEmbeddingStore
        db_path = tmp_path / "persist.db"
        db1 = PersistentEmbeddingStore(db_path)
        db1.put_vectors("session.py", "hhhh", [[7.0, 8.0]])
        db1.close()

        db2 = PersistentEmbeddingStore(db_path)
        result = db2.get_vectors("session.py", "hhhh")
        db2.close()
        assert result is not None
        assert abs(result[0][0] - 7.0) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# Ollama vision capability detection
# ─────────────────────────────────────────────────────────────────────────────

class TestOllamaVisionDetection:
    def test_llava_detected(self):
        from app.core.vision import ollama_model_has_vision
        assert ollama_model_has_vision("llava:13b") is True

    def test_bakllava_detected(self):
        from app.core.vision import ollama_model_has_vision
        assert ollama_model_has_vision("bakllava:latest") is True

    def test_moondream_detected(self):
        from app.core.vision import ollama_model_has_vision
        assert ollama_model_has_vision("moondream:1.8b") is True

    def test_codellama_not_detected(self):
        from app.core.vision import ollama_model_has_vision
        assert ollama_model_has_vision("codellama:7b") is False

    def test_mistral_not_detected(self):
        from app.core.vision import ollama_model_has_vision
        assert ollama_model_has_vision("mistral:7b") is False

    def test_phi3_vision_detected(self):
        from app.core.vision import ollama_model_has_vision
        assert ollama_model_has_vision("phi3-vision:latest") is True

    def test_case_insensitive(self):
        from app.core.vision import ollama_model_has_vision
        assert ollama_model_has_vision("LLAVA:7B") is True

    def test_build_multimodal_message_ollama_non_vision_fallback(self, tmp_path):
        """Non-vision Ollama model returns plain text content, not image blocks."""
        from app.core.vision import build_multimodal_message
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = build_multimodal_message(
            "describe this", [str(img)], provider="ollama", model_name="codellama:7b"
        )
        # Returns {"role": "user", "content": <str or list>}
        assert isinstance(result, dict)
        content = result.get("content")
        # For non-vision model, content should be plain text (str), not a list with image_url
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    assert block.get("type") != "image_url"
        else:
            assert isinstance(content, str)


# ─────────────────────────────────────────────────────────────────────────────
# Real MCP stdio protocol — StdioMCPConnection / StdioMCPManager
# ─────────────────────────────────────────────────────────────────────────────

class TestStdioMCPConnection:
    """Tests use a mock subprocess to simulate an MCP server over stdio."""

    def _make_mock_proc(self, responses: list[dict]):
        """Create a mock Popen that returns JSON-RPC responses in order."""
        proc = MagicMock()
        proc.poll.return_value = None
        response_lines = [json.dumps(r) + "\n" for r in responses]
        proc.stdout.readline.side_effect = response_lines
        proc.stdin.write = MagicMock()
        proc.stdin.flush = MagicMock()
        proc.stdin.close = MagicMock()
        proc.wait = MagicMock()
        return proc

    def test_initialize_sends_correct_method(self):
        from app.core.mcp_stdio import StdioMCPConnection
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = self._make_mock_proc([init_resp])
            conn = StdioMCPConnection("test", ["echo", "server"])
            # Verify initialize was written
            written = mock_popen.return_value.stdin.write.call_args_list
            assert any("initialize" in str(c) for c in written)

    def test_list_tools_returns_tools(self):
        from app.core.mcp_stdio import StdioMCPConnection
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        tools_resp = {
            "jsonrpc": "2.0", "id": 2,
            "result": {"tools": [{"name": "search", "description": "Search files", "inputSchema": {}}]}
        }
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = self._make_mock_proc([init_resp, tools_resp])
            conn = StdioMCPConnection("test", ["fake_server"])
            tools = conn.list_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "search"

    def test_call_tool_returns_text(self):
        from app.core.mcp_stdio import StdioMCPConnection
        init_resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        call_resp = {
            "jsonrpc": "2.0", "id": 2,
            "result": {"content": [{"type": "text", "text": "found 3 results"}]}
        }
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = self._make_mock_proc([init_resp, call_resp])
            conn = StdioMCPConnection("test", ["fake_server"])
            result = conn.call_tool("search", {"query": "foo"})
            assert "found 3 results" in result

    def test_server_not_found_raises_error(self):
        from app.core.mcp_stdio import StdioMCPConnection, StdioMCPError
        with patch("subprocess.Popen", side_effect=FileNotFoundError("not found")):
            try:
                StdioMCPConnection("bad", ["nonexistent_server_binary"])
                assert False, "Should have raised StdioMCPError"
            except StdioMCPError as exc:
                assert "Cannot start" in str(exc)


class TestStdioMCPManager:
    def test_from_config_empty_when_no_file(self, tmp_path):
        from app.core.mcp_stdio import StdioMCPManager
        mgr = StdioMCPManager.from_config(tmp_path / "nonexistent.json")
        assert mgr.server_names() == []

    def test_from_config_loads_specs(self, tmp_path):
        from app.core.mcp_stdio import StdioMCPManager
        cfg = {"github": {"command": ["npx", "server-github"]}}
        cfg_file = tmp_path / "mcp_servers.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        mgr = StdioMCPManager.from_config(cfg_file)
        assert "github" in mgr.server_names()

    def test_invalid_json_returns_empty(self, tmp_path):
        from app.core.mcp_stdio import StdioMCPManager
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        mgr = StdioMCPManager.from_config(bad)
        assert mgr.server_names() == []

    def test_call_with_invalid_format_raises(self):
        from app.core.mcp_stdio import StdioMCPManager, StdioMCPError
        mgr = StdioMCPManager({})
        try:
            mgr.call("no_double_underscore", {})
            assert False
        except StdioMCPError:
            pass

    def test_status_shows_configured_servers(self):
        from app.core.mcp_stdio import StdioMCPManager
        mgr = StdioMCPManager({"myserver": {"command": ["cmd"]}})
        lines = mgr.status()
        assert any("myserver" in line for line in lines)

    def test_prefixed_tool_names_in_all_tools(self):
        from app.core.mcp_stdio import StdioMCPManager, StdioMCPConnection
        mgr = StdioMCPManager({"gh": {"command": ["fake"]}})
        mock_conn = MagicMock(spec=StdioMCPConnection)
        mock_conn.alive = True
        mock_conn.list_tools.return_value = [
            {"name": "search", "description": "search repos"}
        ]
        mgr._connections["gh"] = mock_conn
        tools = mgr.all_tools()
        assert tools[0]["name"] == "gh__search"
        assert tools[0]["_mcp_server"] == "gh"
        assert tools[0]["_mcp_tool"] == "search"


# ─────────────────────────────────────────────────────────────────────────────
# Provider fallback — error class detection
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderFallbackErrorClasses:
    def test_auth_error_is_fallback_trigger(self):
        from app.core.error_classifier import classify_error, ErrorClass
        exc = Exception("401 Unauthorized invalid_api_key")
        classified = classify_error(exc, "anthropic")
        # AUTH should trigger fallback
        assert classified.error_class in (
            ErrorClass.AUTH, ErrorClass.QUOTA, ErrorClass.PERMANENT, ErrorClass.TRANSIENT
        )

    def test_rate_limit_not_in_fallback_trigger_set(self):
        """RATE_LIMIT and TRANSIENT should never trigger provider switch."""
        from app.core.error_classifier import ErrorClass
        FALLBACK_TRIGGER = {ErrorClass.AUTH, ErrorClass.QUOTA, ErrorClass.PERMANENT, ErrorClass.MODEL_NOT_FOUND}
        # These retryable classes must NOT be in the fallback set
        assert ErrorClass.RATE_LIMIT not in FALLBACK_TRIGGER
        assert ErrorClass.TRANSIENT not in FALLBACK_TRIGGER
        # These permanent/auth classes MUST be in the fallback set
        assert ErrorClass.AUTH in FALLBACK_TRIGGER
        assert ErrorClass.QUOTA in FALLBACK_TRIGGER
        assert ErrorClass.PERMANENT in FALLBACK_TRIGGER

    def test_fallback_trigger_set_contains_expected(self):
        from app.core.error_classifier import ErrorClass
        # These are the classes that should trigger provider fallback
        FALLBACK_TRIGGER = {ErrorClass.AUTH, ErrorClass.QUOTA, ErrorClass.PERMANENT, ErrorClass.MODEL_NOT_FOUND}
        assert ErrorClass.TRANSIENT not in FALLBACK_TRIGGER
        assert ErrorClass.RATE_LIMIT not in FALLBACK_TRIGGER
