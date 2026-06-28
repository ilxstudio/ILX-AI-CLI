"""Tests for user_tools.builder and user_tools.runner — Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _FakeCfg:
    working_folder = ""
    autofix_enabled = False


def _cfg_with_wf(tmp_path: Path) -> _FakeCfg:
    cfg = _FakeCfg()
    cfg.working_folder = str(tmp_path)
    return cfg


# ---------------------------------------------------------------------------
# UserToolBuilder (app.core.user_tools.builder.ToolBuilder)
# ---------------------------------------------------------------------------

from app.core.user_tools.builder import ToolBuilder as UserToolBuilder  # noqa: E402
from app.core.user_tools.registry import UserToolRegistry  # noqa: E402


def _make_registry(tmp_path: Path) -> UserToolRegistry:
    return UserToolRegistry(registry_path=tmp_path / "registry.json")


def test_user_tool_builder_init(tmp_path):
    reg = _make_registry(tmp_path)
    cfg = _cfg_with_wf(tmp_path)
    builder = UserToolBuilder(cfg, tool_registry=reg)
    assert builder._tools_dir == tmp_path / "user_tools"
    assert builder.llm is None


def test_user_tool_builder_tools_dir_home_fallback():
    """When working_folder is empty the tools dir falls back to ~/.ilx_cli/user_tools."""
    reg = MagicMock()
    builder = UserToolBuilder(_FakeCfg(), tool_registry=reg)
    assert builder._tools_dir == Path.home() / ".ilx_cli" / "user_tools"


def test_generate_code_no_llm_returns_template(tmp_path):
    reg = _make_registry(tmp_path)
    builder = UserToolBuilder(_cfg_with_wf(tmp_path), tool_registry=reg)
    code = builder.generate_code("greet", "Says hello", "Print greeting")
    assert "def main" in code
    assert "greet" in code


def test_generate_code_llm_strips_fences(tmp_path):
    reg = _make_registry(tmp_path)
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "```python\nprint('hello')\n```"
    builder = UserToolBuilder(_cfg_with_wf(tmp_path), llm_client=mock_llm, tool_registry=reg)
    code = builder.generate_code("greet", "Says hello", "Print greeting")
    assert code == "print('hello')"


def test_generate_code_llm_fallback_on_exception(tmp_path):
    reg = _make_registry(tmp_path)
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("network error")
    builder = UserToolBuilder(_cfg_with_wf(tmp_path), llm_client=mock_llm, tool_registry=reg)
    code = builder.generate_code("greet", "Says hello", "Print greeting")
    # Should fall back to template
    assert "def main" in code


def test_create_tool_writes_to_disk(tmp_path):
    reg = _make_registry(tmp_path)
    builder = UserToolBuilder(_cfg_with_wf(tmp_path), tool_registry=reg)
    result = builder.create_tool("mytool", "A tool", "print('hi')")
    assert result["ok"] is True
    assert Path(result["path"]).exists()
    assert Path(result["path"]).read_text(encoding="utf-8") == "print('hi')"


def test_create_tool_permission_denied(tmp_path):
    reg = _make_registry(tmp_path)
    builder = UserToolBuilder(_cfg_with_wf(tmp_path), tool_registry=reg)
    result = builder.create_tool(
        "mytool", "A tool", "print('hi')",
        permission_callback=lambda *_: False,
    )
    assert result["ok"] is False
    assert "Permission denied" in result["error"]


def test_create_tool_oserror_returns_error(tmp_path):
    reg = _make_registry(tmp_path)
    builder = UserToolBuilder(_cfg_with_wf(tmp_path), tool_registry=reg)
    with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        result = builder.create_tool("bad", "oops", "x = 1")
    assert result["ok"] is False
    assert "disk full" in result["error"]


def test_build_and_register_reserved_name(tmp_path):
    reg = _make_registry(tmp_path)
    builder = UserToolBuilder(_cfg_with_wf(tmp_path), tool_registry=reg)
    result = builder.build_and_register("chat", "desc", "task", validate=False)
    assert result["ok"] is False
    assert result["error"]


def test_tools_dir_property(tmp_path):
    reg = _make_registry(tmp_path)
    builder = UserToolBuilder(_cfg_with_wf(tmp_path), tool_registry=reg)
    assert builder.tools_dir() == tmp_path / "user_tools"


# ---------------------------------------------------------------------------
# UserToolRunner (app.core.user_tools.runner.ToolRunner)
# ---------------------------------------------------------------------------

from app.core.user_tools.runner import ToolRunner  # noqa: E402


def test_tool_runner_init():
    runner = ToolRunner()
    assert isinstance(runner, ToolRunner)


def test_run_sync_missing_file(tmp_path):
    runner = ToolRunner()
    result = runner.run_sync(tmp_path / "no_such_tool.py")
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_run_sync_success(tmp_path):
    script = tmp_path / "ok_tool.py"
    script.write_text("print('done')\n", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.stdout = "done\n"
    mock_proc.stderr = ""
    mock_proc.returncode = 0

    with patch("subprocess.run", return_value=mock_proc):
        result = ToolRunner().run_sync(script)
    assert result["ok"] is True
    assert result["exit_code"] == 0


def test_run_sync_timeout(tmp_path):
    script = tmp_path / "slow_tool.py"
    script.write_text("import time; time.sleep(999)\n", encoding="utf-8")

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=1)):
        result = ToolRunner().run_sync(script, timeout=1)
    assert result["ok"] is False
    assert "timed out" in result["error"].lower()


def test_run_sync_nonzero_exit_code(tmp_path):
    script = tmp_path / "fail_tool.py"
    script.write_text("raise SystemExit(2)\n", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = "error text"
    mock_proc.returncode = 2

    with patch("subprocess.run", return_value=mock_proc):
        result = ToolRunner().run_sync(script)
    assert result["ok"] is False
    assert result["exit_code"] == 2


def test_run_sync_output_captured(tmp_path):
    script = tmp_path / "output_tool.py"
    script.write_text("print('hello world')\n", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.stdout = "hello world\n"
    mock_proc.stderr = ""
    mock_proc.returncode = 0

    with patch("subprocess.run", return_value=mock_proc):
        result = ToolRunner().run_sync(script)
    assert "hello world" in result["output"]


def test_run_async_returns_thread(tmp_path):
    script = tmp_path / "async_tool.py"
    script.write_text("print('async')\n", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.stdout.__iter__ = MagicMock(return_value=iter(["async\n"]))
    mock_proc.wait.return_value = 0
    mock_proc.returncode = 0

    with patch("subprocess.Popen", return_value=mock_proc):
        t = ToolRunner().run_async(script, timeout=5)
    t.join(timeout=3)
    assert not t.is_alive()
