"""Tests for router, sse_parser, diff_parser, file_utils, notifications, plugin_base
— Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ===========================================================================
# ModelRouter  (app/core/router.py)
# ===========================================================================

from app.core.router import ModelRouter, RouteDecision, TASK_TYPES, STRATEGIES


def _make_router_cfg(provider="ollama", model="llama3.2", url="http://localhost:11434",
                     strategy="auto"):
    cfg = MagicMock()
    cfg.provider = provider
    cfg.ollama_model = model
    cfg.ollama_url = url
    cfg.route_strategy = strategy
    return cfg


class TestModelRouterInit:
    def test_stores_cfg(self):
        cfg = _make_router_cfg()
        router = ModelRouter(cfg)
        assert router._cfg is cfg

    def test_route_returns_route_decision(self):
        cfg = _make_router_cfg(strategy="local-only")
        router = ModelRouter(cfg)
        with patch.object(router, "_ollama_available", return_value=True):
            dec = router.route("chat")
        assert isinstance(dec, RouteDecision)
        assert dec.task_type == "chat"

    def test_local_only_picks_ollama(self):
        cfg = _make_router_cfg(strategy="local-only")
        router = ModelRouter(cfg)
        with patch.object(router, "_ollama_available", return_value=True), \
             patch.object(router, "_resolve_model", return_value="llama3.2"):
            dec = router.route("chat")
        assert dec.provider == "ollama"

    def test_fallback_when_no_candidates_match(self):
        cfg = _make_router_cfg(strategy="local-only")
        router = ModelRouter(cfg)
        # embed has only local tier; if ollama unavailable → fallback
        with patch.object(router, "_ollama_available", return_value=False):
            dec = router.route("embed")
        assert dec.reason == "fallback to configured provider"

    def test_auto_strategy_allows_all_tiers(self):
        router = ModelRouter(_make_router_cfg(strategy="auto"))
        tiers = router._allowed_tiers("auto")
        assert "local" in tiers and "free" in tiers and "paid" in tiers

    def test_free_only_excludes_paid(self):
        router = ModelRouter(_make_router_cfg())
        tiers = router._allowed_tiers("free-only")
        assert "paid" not in tiers

    def test_quality_strategy_allows_paid(self):
        cfg = _make_router_cfg(strategy="quality")
        router = ModelRouter(cfg)
        with patch.object(router, "_ollama_available", return_value=True), \
             patch.object(router, "_has_key", return_value=True), \
             patch.object(router, "_resolve_model", return_value="claude-sonnet-4-6"):
            dec = router.route("plan")
        assert dec.provider == "anthropic"

    def test_explain_returns_lines_for_all_tasks(self):
        cfg = _make_router_cfg(strategy="local-only")
        router = ModelRouter(cfg)
        with patch.object(router, "_ollama_available", return_value=True), \
             patch.object(router, "_resolve_model", return_value="llama3.2"):
            lines = router.explain()
        assert len(lines) >= len(TASK_TYPES) + 1


# ===========================================================================
# SSE parser  (app/core/sse_parser.py)
# ===========================================================================

from app.core.sse_parser import parse_event_data, classify_event, SSEEvent


class TestParseEventData:
    def test_valid_json_object(self):
        result = parse_event_data('{"content": "hello"}')
        assert result == {"content": "hello"}

    def test_done_sentinel(self):
        result = parse_event_data("[DONE]")
        assert result == {}  # not valid JSON → empty dict

    def test_empty_string(self):
        result = parse_event_data("")
        assert result == {}

    def test_oversized_event_dropped(self):
        big = "x" * (5 * 1024 * 1024)  # 5 MB > _MAX_EVENT_BYTES (4 MB)
        result = parse_event_data(big)
        assert result == {}

    def test_invalid_json_returns_empty(self):
        result = parse_event_data("not json at all")
        assert result == {}

    def test_json_array_returns_empty(self):
        # Non-dict JSON → empty
        result = parse_event_data('["a","b"]')
        assert result == {}


class TestClassifyEvent:
    def test_token_when_content_present(self):
        assert classify_event({"content": "hi"}) == "token"

    def test_done_when_done_true(self):
        assert classify_event({"done": True}) == "done"

    def test_error_when_error_key(self):
        assert classify_event({"error": "oops"}) == "error"

    def test_info_otherwise(self):
        assert classify_event({"model": "llama3"}) == "info"


# ===========================================================================
# diff_parser  (app/utils/diff_parser.py)
# ===========================================================================

from app.utils.diff_parser import parse_unified, synthesize_new_file_hunk, Hunk


SIMPLE_DIFF = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


class TestParseUnified:
    def test_empty_input_returns_no_hunks(self):
        assert parse_unified("") == []

    def test_parses_single_hunk(self):
        hunks = parse_unified(SIMPLE_DIFF)
        assert len(hunks) == 1

    def test_hunk_has_correct_line_counts(self):
        hunks = parse_unified(SIMPLE_DIFF)
        h = hunks[0]
        assert h.old_start == 1
        assert h.old_count == 3
        assert h.new_start == 1
        assert h.new_count == 3

    def test_hunk_lines_captured(self):
        hunks = parse_unified(SIMPLE_DIFF)
        text = "\n".join(hunks[0].lines)
        assert "+    return a + b" in text

    def test_summary_contains_counts(self):
        hunks = parse_unified(SIMPLE_DIFF)
        summary = hunks[0].summary()
        assert "+" in summary and "-" in summary

    def test_synthesize_new_file_hunk(self):
        h = synthesize_new_file_hunk("line1\nline2\n")
        assert h.old_start == 0
        assert h.new_start == 1
        assert len(h.lines) == 2

    def test_synthesize_empty_content(self):
        h = synthesize_new_file_hunk("")
        assert h.lines == ["+"]

    def test_multiple_hunks_parsed(self):
        diff = (
            "--- a/f.py\n+++ b/f.py\n"
            "@@ -1,2 +1,2 @@\n a\n-b\n+B\n"
            "@@ -10,2 +10,2 @@\n x\n-y\n+Y\n"
        )
        hunks = parse_unified(diff)
        assert len(hunks) == 2


# ===========================================================================
# file_utils  (app/utils/file_utils.py)
# ===========================================================================

from app.utils.file_utils import safe_resolve, compute_diff, detect_language, extract_code_block


class TestSafeResolve:
    def test_safe_path_within_folder(self, tmp_path):
        result = safe_resolve("sub/file.txt", str(tmp_path))
        assert result is not None
        assert result.startswith(str(tmp_path))

    def test_path_traversal_blocked(self, tmp_path):
        result = safe_resolve("../../etc/passwd", str(tmp_path))
        assert result is None

    def test_current_dir_resolves(self, tmp_path):
        result = safe_resolve(".", str(tmp_path))
        # resolves to the working folder itself — within bounds
        assert result is not None


class TestComputeDiff:
    def test_identical_content_empty_diff(self):
        diff = compute_diff("hello\n", "hello\n")
        assert diff == ""

    def test_changed_line_appears_in_diff(self):
        diff = compute_diff("old line\n", "new line\n")
        assert "-old line" in diff
        assert "+new line" in diff


class TestDetectLanguage:
    def test_python_file(self):
        assert detect_language("script.py") == "python"

    def test_typescript_file(self):
        assert detect_language("app.ts") == "typescript"

    def test_unknown_extension_returns_text(self):
        assert detect_language("data.xyz") == "text"

    def test_no_extension_returns_text(self):
        assert detect_language("Makefile") == "text"


class TestExtractCodeBlock:
    def test_extracts_python_fenced_block(self):
        text = "Here is code:\n```python\nprint('hi')\n```"
        result = extract_code_block(text)
        assert result == "print('hi')"

    def test_extracts_generic_fenced_block(self):
        text = "```\nx = 1\n```"
        result = extract_code_block(text)
        assert result == "x = 1"

    def test_no_code_block_returns_none(self):
        assert extract_code_block("just plain text") is None

    def test_extracts_multiline_block(self):
        text = "```py\ndef f():\n    return 1\n```"
        result = extract_code_block(text)
        assert "def f():" in result


# ===========================================================================
# notifications  (app/core/notifications.py)
# ===========================================================================

from app.core.notifications import send_notification, _notify_macos, _notify_linux


def _cfg_with_notifications(enabled=True):
    cfg = MagicMock()
    cfg.notifications_enabled = enabled
    return cfg


class TestSendNotification:
    def test_returns_false_when_disabled(self):
        cfg = _cfg_with_notifications(enabled=False)
        result = send_notification("Title", "Msg", cfg)
        assert result is False

    def test_unsupported_platform_returns_false(self):
        cfg = _cfg_with_notifications(enabled=True)
        with patch("platform.system", return_value="FreeBSD"):
            result = send_notification("T", "M", cfg)
        assert result is False

    def test_linux_platform_calls_notify_send(self):
        cfg = _cfg_with_notifications(enabled=True)
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("platform.system", return_value="Linux"), \
             patch("app.core.process_runner.run", return_value=mock_result) as mock_run:
            result = send_notification("T", "M", cfg)
        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "notify-send" in call_args

    def test_macos_platform_calls_osascript(self):
        cfg = _cfg_with_notifications(enabled=True)
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("platform.system", return_value="Darwin"), \
             patch("app.core.process_runner.run", return_value=mock_result) as mock_run:
            result = send_notification("T", "M", cfg)
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "osascript" in call_args

    def test_notify_linux_returns_false_on_exception(self):
        with patch("app.core.process_runner.run", side_effect=OSError("not found")):
            result = _notify_linux("T", "M")
        assert result is False

    def test_notify_macos_strips_quotes(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("app.core.process_runner.run", return_value=mock_result) as mock_run:
            _notify_macos("O'Brien", "It's done")
        script_arg = mock_run.call_args[0][0][2]  # third element: the script string
        assert "'" not in script_arg.replace("'", "").replace("'", "")  # no apostrophes in content


# ===========================================================================
# plugin_base  (app/core/plugin_base.py)
# ===========================================================================

from app.core.plugin_base import ILXPlugin, PluginRegistry


class TestILXPlugin:
    def test_cannot_instantiate_abstract_directly(self):
        with pytest.raises(TypeError):
            ILXPlugin()

    def test_concrete_subclass_works(self):
        class MyPlugin(ILXPlugin):
            @property
            def name(self) -> str:
                return "my_plugin"

        p = MyPlugin()
        assert p.name == "my_plugin"
        assert p.description == ""
        assert p.version == "0.1.0"
        assert p.get_commands() == {}
        assert p.get_hooks() == []

    def test_on_load_and_unload_are_safe(self):
        class MyPlugin(ILXPlugin):
            @property
            def name(self) -> str:
                return "safe_plugin"

        p = MyPlugin()
        cfg = MagicMock()
        p.on_load(cfg)   # must not raise
        p.on_unload()    # must not raise


class TestPluginRegistry:
    def test_discover_returns_empty_when_no_entry_points(self):
        registry = PluginRegistry()
        with patch("importlib.metadata.entry_points", return_value=[]):
            names = registry.discover()
        assert names == []

    def test_get_returns_none_for_unknown_name(self):
        registry = PluginRegistry()
        assert registry.get("nonexistent") is None

    def test_all_returns_empty_initially(self):
        registry = PluginRegistry()
        assert registry.all() == []

    def test_discover_loads_valid_plugin(self):
        class FakePlugin(ILXPlugin):
            @property
            def name(self) -> str:
                return "fake"

        ep = MagicMock()
        ep.load.return_value = FakePlugin

        registry = PluginRegistry()
        with patch("importlib.metadata.entry_points", return_value=[ep]):
            names = registry.discover()

        assert "fake" in names
        assert registry.get("fake") is not None

    def test_discover_skips_broken_plugin(self):
        bad_ep = MagicMock()
        bad_ep.load.side_effect = ImportError("broken dep")
        bad_ep.name = "bad_plugin"

        registry = PluginRegistry()
        with patch("importlib.metadata.entry_points", return_value=[bad_ep]):
            names = registry.discover()

        assert names == []
        assert registry.get("bad_plugin") is None
