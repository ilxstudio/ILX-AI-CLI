"""Cluster 08 — MCPClient and /scaffold command.

Tests:
  - test_mcp_client_init           : MCPClient() loads without error, tools is a list
  - test_mcp_register_builtin_tools: register_builtin_tools() adds expected tools
  - test_mcp_call_read_file        : call("read_file", {...}) returns success=True and content
  - test_mcp_call_list_dir         : call("list_dir", {"path": "."}) returns success=True
  - test_mcp_call_run_command      : call("run_command", {"command": "echo hello"}) returns "hello"
  - test_mcp_call_unknown_tool     : call("nonexistent", {}) returns success=False
  - test_mcp_permission_denied     : permission_cb returning False → success=False, "Denied by user"
  - test_mcp_parse_tool_call       : parse_tool_call(...) extracts tool name and args
  - test_mcp_save_reload           : save_tools() + new MCPClient() re-reads persisted tools
  - test_scaffold_via_llm          : cmd_scaffold(["model", "User"]) writes a file; real LLM call
  - test_init_template_react       : cmd_init(["react"]) creates package.json and src/App.jsx
  - test_init_template_fastapi     : cmd_init(["fastapi"]) creates main.py and tests/test_main.py
  - test_init_template_django      : cmd_init(["django"]) creates manage.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


# ── helpers ───────────────────────────────────────────────────────────────────

def _fresh_mcp(tools_file: Path | None = None):
    """Return a fresh MCPClient whose backing file is isolated to `tools_file`."""
    from app.core import mcp_client as _mod
    if tools_file is None:
        # Point to a non-existent file so no pre-existing state leaks in
        tools_file = Path(tempfile.mkdtemp()) / ".ilx_cli" / "mcp_tools.json"
    with patch.object(_mod, "_MCP_TOOLS_FILE", tools_file):
        client = _mod.MCPClient()
    # Carry the patched path so callers can re-use it for save/reload
    client._test_tools_file = tools_file
    return client, tools_file


# ── MCPClient basic init ───────────────────────────────────────────────────────

def test_mcp_client_init():
    """MCPClient() loads without error and exposes a list via .tools."""
    from app.core.mcp_client import MCPClient
    try:
        client = MCPClient()
        ok = isinstance(client.tools, list)
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    save("mcp_client_init", ok, {
        "tool_count": len(client.tools) if ok else 0,
        "error": error,
    })
    assert ok, f"MCPClient() raised: {error}"


# ── register_builtin_tools ─────────────────────────────────────────────────────

def test_mcp_register_builtin_tools():
    """register_builtin_tools() adds read_file, write_file, list_dir, run_command."""
    client, _ = _fresh_mcp()
    client.register_builtin_tools()
    names = {t.name for t in client.tools}
    expected = {"read_file", "write_file", "list_dir", "run_command"}
    ok = expected.issubset(names)
    save("mcp_register_builtin_tools", ok, {
        "registered": sorted(names),
        "expected": sorted(expected),
        "missing": sorted(expected - names),
    })
    assert ok, f"Missing tools after register_builtin_tools(): {expected - names}"


# ── call("read_file") ──────────────────────────────────────────────────────────

def test_mcp_call_read_file():
    """register builtins, call read_file on a real file, verify success and content."""
    client, _ = _fresh_mcp()
    client.register_builtin_tools()

    # Use conftest.py as the real file — we know it exists
    real_file = str(Path(__file__).parent / "conftest.py")
    result = client.call("read_file", {"path": real_file})

    ok = (
        result.get("success") is True
        and isinstance(result.get("result"), str)
        and len(result["result"]) > 0
    )
    save("mcp_call_read_file", ok, {
        "success": result.get("success"),
        "content_len": len(result.get("result") or ""),
        "error": result.get("error"),
        "snippet": (result.get("result") or "")[:200],
    })
    assert ok, f"read_file failed: {result}"


# ── call("list_dir") ──────────────────────────────────────────────────────────

def test_mcp_call_list_dir():
    """call list_dir on the project tests/ dir, verify non-empty result."""
    client, _ = _fresh_mcp()
    client.register_builtin_tools()

    tests_dir = str(Path(__file__).parent)
    result = client.call("list_dir", {"path": tests_dir})

    ok = (
        result.get("success") is True
        and isinstance(result.get("result"), str)
        and len(result.get("result", "").strip()) > 0
    )
    save("mcp_call_list_dir", ok, {
        "success": result.get("success"),
        "result_snippet": (result.get("result") or "")[:300],
        "error": result.get("error"),
    })
    assert ok, f"list_dir failed: {result}"


# ── call("run_command") ────────────────────────────────────────────────────────

def test_mcp_call_run_command():
    """call run_command with 'echo hello', verify success=True and 'hello' in result."""
    client, _ = _fresh_mcp()
    client.register_builtin_tools()

    # Pass as a list so shlex.split path-with-spaces issues are avoided.
    # run_command builtin now accepts list directly when shell=False.
    result = client.call(
        "run_command",
        {"command": [sys.executable, "-c", "print('hello')"]},
    )

    ok = (
        result.get("success") is True
        and "hello" in (result.get("result") or "").lower()
    )
    save("mcp_call_run_command", ok, {
        "success": result.get("success"),
        "result": (result.get("result") or "")[:200],
        "error": result.get("error"),
    })
    assert ok, f"run_command failed: {result}"


# ── call unknown tool ──────────────────────────────────────────────────────────

def test_mcp_call_unknown_tool():
    """call("nonexistent", {}) returns success=False."""
    client, _ = _fresh_mcp()
    client.register_builtin_tools()

    result = client.call("nonexistent_tool_xyz", {})
    ok = result.get("success") is False
    save("mcp_call_unknown_tool", ok, {
        "success": result.get("success"),
        "error": result.get("error"),
    })
    assert ok, f"Expected success=False for unknown tool. Got: {result}"


# ── permission_cb denied ───────────────────────────────────────────────────────

def test_mcp_permission_denied():
    """permission_cb returning False gives success=False, error='Denied by user'."""
    client, _ = _fresh_mcp()
    client.register_builtin_tools()

    def deny_all(action, tool_name, params_str):
        return False

    result = client.call("read_file", {"path": "/tmp/whatever"}, permission_cb=deny_all)
    ok = (
        result.get("success") is False
        and "denied" in (result.get("error") or "").lower()
    )
    save("mcp_permission_denied", ok, {
        "success": result.get("success"),
        "error": result.get("error"),
    })
    assert ok, f"Expected denied result. Got: {result}"


# ── parse_tool_call ────────────────────────────────────────────────────────────

def test_mcp_parse_tool_call():
    """parse_tool_call extracts tool name and args from a JSON tool-call string."""
    client, _ = _fresh_mcp()

    raw = '{"tool": "read_file", "args": {"path": "/tmp/x"}}'
    result = client.parse_tool_call(raw)

    ok = (
        result is not None
        and result[0] == "read_file"
        and result[1] == {"path": "/tmp/x"}
    )
    save("mcp_parse_tool_call", ok, {
        "input": raw,
        "parsed": result,
    })
    assert ok, f"parse_tool_call returned unexpected result: {result!r}"


# ── save_tools / reload ────────────────────────────────────────────────────────

def test_mcp_save_reload():
    """register builtins, save_tools(), create a new MCPClient, verify tools reloaded."""
    from app.core import mcp_client as _mod

    with tempfile.TemporaryDirectory() as tmpdir:
        tools_file = Path(tmpdir) / "mcp_tools.json"

        # First client: register builtins and save
        with patch.object(_mod, "_MCP_TOOLS_FILE", tools_file):
            c1 = _mod.MCPClient()
            c1.register_builtin_tools()
            c1.save_tools()

        # Verify file was written
        assert tools_file.exists(), "save_tools() did not create the tools file"
        saved_specs = json.loads(tools_file.read_text(encoding="utf-8"))

        # Second client: should pick up the saved tools
        with patch.object(_mod, "_MCP_TOOLS_FILE", tools_file):
            c2 = _mod.MCPClient()

        names2 = {t.name for t in c2.tools}
        expected = {"read_file", "write_file", "list_dir", "run_command"}
        ok = expected.issubset(names2)

        save("mcp_save_reload", ok, {
            "saved_count": len(saved_specs),
            "reloaded_names": sorted(names2),
            "missing": sorted(expected - names2),
        })
    assert ok, f"After reload, missing tools: {expected - names2}"


# ── /scaffold via real LLM ─────────────────────────────────────────────────────

def test_scaffold_via_llm(cfg, tmp_path, capsys):
    """cmd_scaffold(["model", "User"]) makes a real Ollama call and writes models/user.py."""
    from cli.commands.workspace_cmds import WorkspaceCommands
    from cli.context import ContextManager
    from app.core.config import AppConfig

    tmp_cfg = AppConfig()
    tmp_cfg.working_folder = str(tmp_path)
    # Copy LLM settings from the session cfg
    tmp_cfg.ollama_url   = cfg.ollama_url
    tmp_cfg.ollama_model = cfg.ollama_model

    ctx = ContextManager(tmp_cfg)
    ws  = WorkspaceCommands(tmp_cfg, ctx)

    # Monkeypatch input() so it always answers "y" (write the file)
    with patch("builtins.input", return_value="y"):
        try:
            ws.cmd_scaffold(["model", "User"])
            ok = True
            error = None
        except Exception as exc:
            ok = False
            error = str(exc)

    captured = capsys.readouterr()

    # The file should have been written to models/user.py
    out_file = tmp_path / "models" / "user.py"
    file_created = out_file.exists()
    code_snippet = out_file.read_text(encoding="utf-8")[:500] if file_created else ""

    result_ok = ok and file_created
    save("scaffold_via_llm", result_ok, {
        "ok": ok,
        "file_created": file_created,
        "output_path": str(out_file),
        "code_snippet": code_snippet,
        "stdout": captured.out[:600],
        "error": error,
        "llm_response_in_stdout": len(captured.out) > 0,
    })
    assert result_ok, (
        f"scaffold failed: ok={ok} file_created={file_created} "
        f"error={error} stdout={captured.out[:300]!r}"
    )


# ── /init react ───────────────────────────────────────────────────────────────

def test_init_template_react(cfg, tmp_path, capsys):
    """cmd_init(["react"]) creates package.json and src/App.jsx."""
    from cli.commands.workspace_cmds import WorkspaceCommands
    from cli.context import ContextManager
    from app.core.config import AppConfig

    tmp_cfg = AppConfig()
    tmp_cfg.working_folder = str(tmp_path)
    ctx = ContextManager(tmp_cfg)
    ws  = WorkspaceCommands(tmp_cfg, ctx)

    try:
        ws.cmd_init(["react"])
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)

    pkg   = tmp_path / "package.json"
    app   = tmp_path / "src" / "App.jsx"
    pkg_ok = pkg.exists()
    app_ok = app.exists()
    result_ok = ok and pkg_ok and app_ok

    captured = capsys.readouterr()
    save("init_template_react", result_ok, {
        "package_json": pkg_ok,
        "src_app_jsx": app_ok,
        "stdout": captured.out[:400],
        "error": error,
        "created_files": [
            str(p.relative_to(tmp_path))
            for p in tmp_path.rglob("*")
            if p.is_file()
        ],
    })
    assert result_ok, (
        f"react template missing files. "
        f"package.json={pkg_ok} src/App.jsx={app_ok} error={error}"
    )


# ── /init fastapi ─────────────────────────────────────────────────────────────

def test_init_template_fastapi(cfg, tmp_path, capsys):
    """cmd_init(["fastapi"]) creates main.py and tests/test_main.py."""
    from cli.commands.workspace_cmds import WorkspaceCommands
    from cli.context import ContextManager
    from app.core.config import AppConfig

    tmp_cfg = AppConfig()
    tmp_cfg.working_folder = str(tmp_path)
    ctx = ContextManager(tmp_cfg)
    ws  = WorkspaceCommands(tmp_cfg, ctx)

    try:
        ws.cmd_init(["fastapi"])
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)

    main_py  = tmp_path / "main.py"
    test_py  = tmp_path / "tests" / "test_main.py"
    main_ok  = main_py.exists()
    test_ok  = test_py.exists()
    result_ok = ok and main_ok and test_ok

    captured = capsys.readouterr()
    save("init_template_fastapi", result_ok, {
        "main_py": main_ok,
        "tests_test_main_py": test_ok,
        "stdout": captured.out[:400],
        "error": error,
        "created_files": [
            str(p.relative_to(tmp_path))
            for p in tmp_path.rglob("*")
            if p.is_file()
        ],
    })
    assert result_ok, (
        f"fastapi template missing files. "
        f"main.py={main_ok} tests/test_main.py={test_ok} error={error}"
    )


# ── /init django ──────────────────────────────────────────────────────────────

def test_init_template_django(cfg, tmp_path, capsys):
    """cmd_init(["django"]) creates manage.py."""
    from cli.commands.workspace_cmds import WorkspaceCommands
    from cli.context import ContextManager
    from app.core.config import AppConfig

    tmp_cfg = AppConfig()
    tmp_cfg.working_folder = str(tmp_path)
    ctx = ContextManager(tmp_cfg)
    ws  = WorkspaceCommands(tmp_cfg, ctx)

    try:
        ws.cmd_init(["django"])
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)

    manage_py = tmp_path / "manage.py"
    manage_ok = manage_py.exists()
    result_ok = ok and manage_ok

    captured = capsys.readouterr()
    save("init_template_django", result_ok, {
        "manage_py": manage_ok,
        "stdout": captured.out[:400],
        "error": error,
        "created_files": [
            str(p.relative_to(tmp_path))
            for p in tmp_path.rglob("*")
            if p.is_file()
        ],
    })
    assert result_ok, (
        f"django template missing files. "
        f"manage.py={manage_ok} error={error}"
    )
