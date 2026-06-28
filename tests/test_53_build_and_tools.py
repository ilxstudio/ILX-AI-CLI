"""Tests for build_helper, thread_pool, tool_builder — Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core import build_helper  # noqa: E402
from app.core.tool_builder import ToolBuilder, _safe_filename  # noqa: E402

# ---------------------------------------------------------------------------
# build_helper
# ---------------------------------------------------------------------------

def test_pyinstaller_available_true():
    with patch("shutil.which", return_value="/usr/bin/pyinstaller"):
        assert build_helper.pyinstaller_available() is True


def test_pyinstaller_available_false():
    with patch("shutil.which", return_value=None):
        assert build_helper.pyinstaller_available() is False


def test_build_no_pyinstaller():
    with patch.object(build_helper, "pyinstaller_available", return_value=False):
        ok, msg = build_helper.build("entry.py", "/workspace")
    assert ok is False
    assert "PyInstaller" in msg


def test_build_success(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "entry.exe").write_text("fake")
    mock_proc = MagicMock()
    mock_proc.stdout = iter(["line1\n"])
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0
    with patch.object(build_helper, "pyinstaller_available", return_value=True), \
         patch("subprocess.Popen", return_value=mock_proc):
        ok, msg = build_helper.build("entry.py", str(tmp_path))
    assert ok is True
    assert "Build complete" in msg


def test_build_timeout(tmp_path):
    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="pyinstaller", timeout=600)
    with patch.object(build_helper, "pyinstaller_available", return_value=True), \
         patch("subprocess.Popen", return_value=mock_proc):
        ok, msg = build_helper.build("entry.py", str(tmp_path))
    assert ok is False
    assert "timed out" in msg.lower()


def test_bump_version_no_file(tmp_path):
    assert build_helper.bump_version(str(tmp_path)) is None


def test_bump_version_updates_patch(tmp_path):
    vf = tmp_path / "version.py"
    vf.write_text('VERSION = "1.2.3"\n', encoding="utf-8")
    result = build_helper.bump_version(str(tmp_path))
    assert result == "1.2.4"
    assert "1.2.4" in vf.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# thread_pool
# ---------------------------------------------------------------------------

import app.core.thread_pool as _tp  # noqa: E402


def _fresh():
    _tp._executor = None
    return _tp


def test_thread_pool_init_workers():
    tp = _fresh()
    tp.init(max_workers=4)
    assert tp._executor._max_workers == 4
    tp._executor.shutdown(wait=False)


def test_thread_pool_submit():
    tp = _fresh()
    tp.init(max_workers=2)
    fut = tp.submit(lambda x: x * 3, 7)
    assert fut.result(timeout=5) == 21
    tp._executor.shutdown(wait=False)


def test_thread_pool_map():
    tp = _fresh()
    tp.init(max_workers=2)
    assert list(tp.map(str, [1, 2, 3])) == ["1", "2", "3"]
    tp._executor.shutdown(wait=False)


def test_thread_pool_shutdown_no_hang():
    tp = _fresh()
    tp.init(max_workers=2)
    tp.init(max_workers=1)   # replaces executor, shutting down previous
    tp._executor.shutdown(wait=True)


def test_thread_pool_lazy_init():
    tp = _fresh()
    tp._executor = None
    exe = tp.pool()
    assert exe is not None
    exe.shutdown(wait=False)


# ---------------------------------------------------------------------------
# tool_builder (app.core.tool_builder)
# ---------------------------------------------------------------------------

class _Cfg:
    working_folder = ""


def test_safe_filename_strips_special():
    assert _safe_filename("My Tool!") == "my_tool"


def test_safe_filename_empty_fallback():
    assert _safe_filename("!!!") == "tool"


def test_create_tool_no_workspace():
    result = ToolBuilder(_Cfg()).create_tool("t", "d", "code")
    assert result["ok"] is False
    assert "workspace" in result["error"].lower()


def test_create_tool_permission_denied(tmp_path):
    cfg = _Cfg()
    cfg.working_folder = str(tmp_path)
    result = ToolBuilder(cfg).create_tool("t", "d", "x", permission_callback=lambda *_: False)
    assert result["ok"] is False
    assert "Cancelled" in result["error"]


def test_create_tool_writes_file(tmp_path):
    cfg = _Cfg()
    cfg.working_folder = str(tmp_path)
    result = ToolBuilder(cfg).create_tool("t", "d", "print('hi')", permission_callback=lambda *_: True)
    assert result["ok"] is True
    assert Path(result["path"]).read_text(encoding="utf-8") == "print('hi')"


def test_list_tools_empty():
    assert ToolBuilder(_Cfg()).list_tools() == []


def test_list_tools_finds_files(tmp_path):
    cfg = _Cfg()
    cfg.working_folder = str(tmp_path)
    td = tmp_path / "tools"
    td.mkdir()
    (td / "a.py").write_text("# a")
    (td / "b.py").write_text("# b")
    tools = ToolBuilder(cfg).list_tools()
    assert len(tools) == 2


def test_run_tool_not_found(tmp_path):
    cfg = _Cfg()
    cfg.working_folder = str(tmp_path)
    (tmp_path / "tools").mkdir()
    result = ToolBuilder(cfg).run_tool("nope")
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_generate_tool_no_llm():
    result = ToolBuilder(_Cfg()).generate_tool("do something")
    assert result["ok"] is False
    assert "LLM" in result["error"]
