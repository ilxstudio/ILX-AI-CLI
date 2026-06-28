"""Tests for app/core/executor.py — Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import subprocess

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.executor import LocalExecutor, ExecutorEvent, _sanitized_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(working_folder=None, exec_timeout=30):
    cfg = MagicMock()
    cfg.working_folder = str(working_folder) if working_folder else "C:/tmp/ilx_test"
    cfg.exec_timeout = exec_timeout
    return cfg


def _make_perms(granted=True):
    perms = MagicMock()
    perms.request_permission.return_value = granted
    return perms


# ---------------------------------------------------------------------------
# Tests — _sanitized_env
# ---------------------------------------------------------------------------

class TestSanitizedEnv:
    def test_strips_anthropic_prefix(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "secret", "PATH": "/usr/bin"}):
            env = _sanitized_env()
        assert "ANTHROPIC_API_KEY" not in env
        assert "PATH" in env

    def test_strips_openai_prefix(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-xxx", "HOME": "/home/user"}):
            env = _sanitized_env()
        assert "OPENAI_API_KEY" not in env
        assert "HOME" in env

    def test_strips_keys_ending_in_token(self):
        with patch.dict("os.environ", {"MY_ACCESS_TOKEN": "tok123", "USER": "alice"}):
            env = _sanitized_env()
        assert "MY_ACCESS_TOKEN" not in env
        assert "USER" in env

    def test_strips_sensitive_name_password(self):
        with patch.dict("os.environ", {"PASSWORD": "hunter2", "TERM": "xterm"}):
            env = _sanitized_env()
        assert "PASSWORD" not in env

    def test_preserves_normal_vars(self):
        with patch.dict("os.environ", {"MYAPP_DEBUG": "1", "PORT": "8080"}):
            env = _sanitized_env()
        assert "MYAPP_DEBUG" in env
        assert "PORT" in env


# ---------------------------------------------------------------------------
# Tests — LocalExecutor init
# ---------------------------------------------------------------------------

class TestLocalExecutorInit:
    def test_stores_config_and_perms(self, tmp_path):
        cfg = _make_cfg(working_folder=tmp_path)
        perms = _make_perms()
        ex = LocalExecutor(cfg, perms)
        assert ex._config is cfg
        assert ex._perms is perms
        assert ex._cancelled is False

    def test_cancel_sets_flag(self, tmp_path):
        cfg = _make_cfg(working_folder=tmp_path)
        ex = LocalExecutor(cfg, _make_perms())
        ex.cancel()
        assert ex._cancelled is True

    def test_reset_cancel_clears_flag(self, tmp_path):
        cfg = _make_cfg(working_folder=tmp_path)
        ex = LocalExecutor(cfg, _make_perms())
        ex.cancel()
        ex.reset_cancel()
        assert ex._cancelled is False

    def test_working_folder_property(self, tmp_path):
        cfg = _make_cfg(working_folder=tmp_path)
        ex = LocalExecutor(cfg, _make_perms())
        assert ex.working_folder == str(tmp_path)


# ---------------------------------------------------------------------------
# Tests — apply_file_operation
# ---------------------------------------------------------------------------

class TestApplyFileOperation:
    def test_denied_returns_false(self, tmp_path):
        from app.core.permissions import FileOperation
        cfg = _make_cfg(working_folder=tmp_path)
        ex = LocalExecutor(cfg, _make_perms(granted=False))
        op = FileOperation(op_type="write", path=str(tmp_path / "out.txt"), new_content="hello")
        with patch("app.core.executor.log_file_op"):
            result = ex.apply_file_operation(op)
        assert result is False

    def test_write_creates_file(self, tmp_path):
        from app.core.permissions import FileOperation
        cfg = _make_cfg(working_folder=tmp_path)
        ex = LocalExecutor(cfg, _make_perms(granted=True))
        target = tmp_path / "out.txt"
        op = FileOperation(op_type="write", path=str(target), new_content="hello world")
        with patch("app.core.executor.log_file_op"):
            result = ex.apply_file_operation(op)
        assert result is True
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_delete_removes_file(self, tmp_path):
        from app.core.permissions import FileOperation
        cfg = _make_cfg(working_folder=tmp_path)
        ex = LocalExecutor(cfg, _make_perms(granted=True))
        target = tmp_path / "todelete.txt"
        target.write_text("bye", encoding="utf-8")
        op = FileOperation(op_type="delete", path=str(target))
        with patch("app.core.executor.log_file_op"):
            result = ex.apply_file_operation(op)
        assert result is True
        assert not target.exists()


# ---------------------------------------------------------------------------
# Tests — execute() generator
# ---------------------------------------------------------------------------

class TestExecute:
    def test_denied_yields_denied_event(self, tmp_path):
        cfg = _make_cfg(working_folder=tmp_path)
        ex = LocalExecutor(cfg, _make_perms(granted=False))
        with patch("app.core.executor.log_command"):
            events = list(ex.execute(["echo", "hi"]))
        assert any(e.event_type == "denied" for e in events)

    def test_file_not_found_yields_error(self, tmp_path):
        cfg = _make_cfg(working_folder=tmp_path)
        ex = LocalExecutor(cfg, _make_perms(granted=True))
        with patch("app.core.executor.log_command"), \
             patch("app.core.executor._sanitized_env", return_value={}), \
             patch("subprocess.Popen", side_effect=FileNotFoundError("no such file")):
            events = list(ex.execute(["no_such_binary_xyz"]))
        assert any(e.event_type == "error" for e in events)
