"""Permission matrix tests — ask, auto, deny modes; profiles; allowlist/denylist; sandbox."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.core.config import AppConfig, PermissionMode
from app.core.permissions import PermissionEngine, FileOperation


def _make_cfg(mode: PermissionMode, **kwargs) -> AppConfig:
    cfg = AppConfig()
    cfg.permission_mode = mode
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


class TestDenyAll:
    @pytest.mark.security
    def test_blocks_execute(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.DENY_ALL))
        op = FileOperation(op_type="execute", path="", command=["ls"])
        assert eng.request_permission(op) is False

    @pytest.mark.security
    def test_blocks_write(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.DENY_ALL))
        op = FileOperation(op_type="modify", path="/tmp/x.py")
        assert eng.request_permission(op) is False

    @pytest.mark.security
    def test_blocks_create(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.DENY_ALL))
        op = FileOperation(op_type="create", path="/tmp/new.py", new_content="x=1")
        assert eng.request_permission(op) is False


class TestAutoApprove:
    def test_allows_execute(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.AUTO_APPROVE))
        op = FileOperation(op_type="execute", path="", command=["pytest"])
        assert eng.request_permission(op) is True

    def test_allows_write(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.AUTO_APPROVE))
        op = FileOperation(op_type="create", path="/tmp/new.py", new_content="x=1")
        assert eng.request_permission(op) is True

    @pytest.mark.security
    def test_denylist_overrides_auto(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.AUTO_APPROVE, command_denylist=["rm"]))
        op = FileOperation(op_type="execute", path="", command=["rm", "-rf", "/"])
        assert eng.request_permission(op) is False


class TestAskMode:
    def test_yes_grants(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.ASK))
        op = FileOperation(op_type="execute", path="", command=["ls"])
        with patch("builtins.input", return_value="y"):
            assert eng.request_permission(op) is True

    def test_no_denies(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.ASK))
        op = FileOperation(op_type="execute", path="", command=["ls"])
        with patch("builtins.input", return_value="n"):
            assert eng.request_permission(op) is False

    def test_empty_denies(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.ASK))
        op = FileOperation(op_type="execute", path="", command=["ls"])
        with patch("builtins.input", return_value=""):
            assert eng.request_permission(op) is False

    def test_eof_denies(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.ASK))
        op = FileOperation(op_type="execute", path="", command=["ls"])
        with patch("builtins.input", side_effect=EOFError):
            assert eng.request_permission(op) is False

    def test_keyboard_interrupt_denies(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.ASK))
        op = FileOperation(op_type="execute", path="", command=["ls"])
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert eng.request_permission(op) is False

    def test_allowlist_bypasses_prompt(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.ASK, command_allowlist=["pytest"]))
        op = FileOperation(op_type="execute", path="", command=["pytest", "--tb=short"])
        # Should not call input() at all — allowlist bypasses ask
        with patch("builtins.input", side_effect=AssertionError("input() should not be called")):
            assert eng.request_permission(op) is True

    def test_allowlist_prefix_match(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.ASK, command_allowlist=["git"]))
        op = FileOperation(op_type="execute", path="", command=["git", "status"])
        with patch("builtins.input", side_effect=AssertionError("input() should not be called")):
            assert eng.request_permission(op) is True


class TestDenylistPriority:
    @pytest.mark.security
    def test_denylist_beats_allowlist(self):
        """Denylist is checked before allowlist — deny wins."""
        cfg = _make_cfg(
            PermissionMode.AUTO_APPROVE,
            command_denylist=["rm"],
            command_allowlist=["rm"],
        )
        eng = PermissionEngine(cfg)
        op = FileOperation(op_type="execute", path="", command=["rm", "file.txt"])
        assert eng.request_permission(op) is False


class TestSandboxMode:
    @pytest.mark.security
    def test_read_only_blocks_execute_under_auto(self):
        cfg = _make_cfg(PermissionMode.AUTO_APPROVE, sandbox_mode="read_only")
        eng = PermissionEngine(cfg)
        op = FileOperation(op_type="execute", path="", command=["python", "script.py"])
        assert eng.request_permission(op) is False

    @pytest.mark.security
    def test_read_only_blocks_execute_under_ask(self):
        cfg = _make_cfg(PermissionMode.ASK, sandbox_mode="read_only")
        eng = PermissionEngine(cfg)
        op = FileOperation(op_type="execute", path="", command=["python", "script.py"])
        # Should be denied by sandbox before reaching the input() prompt
        with patch("builtins.input", side_effect=AssertionError("input() should not be called")):
            assert eng.request_permission(op) is False

    @pytest.mark.security
    def test_workspace_sandbox_passes_through_to_permission(self):
        cfg = _make_cfg(PermissionMode.AUTO_APPROVE, sandbox_mode="workspace")
        eng = PermissionEngine(cfg)
        op = FileOperation(op_type="execute", path="", command=["pytest"])
        assert eng.request_permission(op) is True

    @pytest.mark.security
    def test_disabled_sandbox_allows_auto(self):
        cfg = _make_cfg(PermissionMode.AUTO_APPROVE, sandbox_mode="disabled")
        eng = PermissionEngine(cfg)
        op = FileOperation(op_type="execute", path="", command=["python", "script.py"])
        assert eng.request_permission(op) is True


class TestFileOperations:
    def test_delete_denied_in_deny_all(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.DENY_ALL))
        op = FileOperation(op_type="delete", path="/tmp/x.py")
        assert eng.request_permission(op) is False

    def test_create_with_content_prompts_in_ask(self):
        eng = PermissionEngine(_make_cfg(PermissionMode.ASK))
        op = FileOperation(op_type="create", path="/tmp/new.py", new_content="x = 1\n")
        with patch("builtins.input", return_value="y"):
            assert eng.request_permission(op) is True
