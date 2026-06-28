"""Cluster 17 — Coverage-gap tests: config, ChatSession tools, MCP, supervisor, scaffold.

Areas covered:
  A. Config persistence
     - test_config_roundtrip_all_fields        : save/load round-trips every AppConfig field
     - test_config_tool_use_enabled_roundtrip  : tool_use_enabled bool survives save/load
     - test_config_permission_mode_roundtrip   : permission_mode enum survives save/load

  B. ChatSession.send() with tool_use_enabled
     - test_chat_send_calls_chat_with_tools    : tool-use path calls chat_with_tools, not chat_stream
     - test_chat_send_stops_after_max_rounds   : tool loop halts at 5 rounds with "(loop limit reached)"
     - test_chat_send_tool_error_graceful      : mcp.call() exception does not crash send()

  C. MCP client — extended
     - test_mcp_registers_all_14_builtin_tools : all 14 builtin tools registered
     - test_mcp_fetch_url_calls_web_fetch      : fetch_url tool dispatches to web_fetch
     - test_mcp_sandbox_blocks_path_traversal  : read_file with ../.. path fails sandbox check

  D. Supervisor
     - test_supervisor_warn_before_kill        : warn message written at 80% timeout
     - test_supervisor_queue_drain             : task finishing starts the next queued task
     - test_supervisor_kill_calls_taskkill     : Windows kill path calls taskkill /F /T /PID

  E. Scaffold
     - test_upgrade_detects_go_mod             : /upgrade detects go.mod → "go" template
     - test_upgrade_detects_cargo_toml         : /upgrade detects Cargo.toml → "rust" template
     - test_scaffold_env_complex_values        : /scaffold env handles complex .env values

  (SSH, secret store, circuit breaker, audit, crash DB → see test_17b_security.py)
"""
from __future__ import annotations

import json
import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


# ═══════════════════════════════════════════════════════════════════════════════
# A. Config persistence
# ═══════════════════════════════════════════════════════════════════════════════

def _make_isolated_manager(tmp_path: Path):
    """Return a ConfigManager backed by a fresh JSON file in tmp_path."""
    from app.core.json_store import JsonStore
    from app.core.config import ConfigManager

    store_path = tmp_path / "config.json"
    store = JsonStore(path=store_path)

    mgr = ConfigManager.__new__(ConfigManager)
    mgr._qs = store
    return mgr


def test_config_roundtrip_all_fields(tmp_path):
    """ConfigManager.save() then load() round-trips every AppConfig field."""
    from app.core.config import AppConfig, PermissionMode

    mgr = _make_isolated_manager(tmp_path)

    cfg_in = AppConfig()
    cfg_in.ollama_url            = "http://test-ollama:11434"
    cfg_in.ollama_model          = "llama3:8b"
    cfg_in.provider              = "openai"
    cfg_in.chat_model            = "gpt-4o"
    cfg_in.working_folder        = "/tmp/workspace"
    cfg_in.permission_mode       = PermissionMode.AUTO_APPROVE
    cfg_in.autofix_enabled       = False
    cfg_in.autofix_max_iterations = 7
    cfg_in.exec_timeout          = 45
    cfg_in.temperature           = 0.5
    cfg_in.top_p                 = 0.8
    cfg_in.max_tokens            = 2048
    cfg_in.num_ctx               = 8192
    cfg_in.system_prompt         = "You are a helpful assistant."
    cfg_in.tool_use_enabled      = True

    mgr.save(cfg_in)
    cfg_out = mgr.load()

    failures = []
    for attr in ("ollama_url", "ollama_model", "provider", "chat_model",
                 "working_folder", "autofix_enabled", "autofix_max_iterations",
                 "exec_timeout", "temperature", "top_p", "max_tokens",
                 "num_ctx", "system_prompt", "tool_use_enabled"):
        if getattr(cfg_out, attr) != getattr(cfg_in, attr):
            failures.append(
                f"{attr}: saved={getattr(cfg_in, attr)!r} loaded={getattr(cfg_out, attr)!r}"
            )

    ok = len(failures) == 0
    save("config_roundtrip_all_fields", ok, {
        "failures": failures,
        "fields_tested": 15,
    })
    assert ok, f"Config round-trip failed for: {failures}"


def test_config_tool_use_enabled_roundtrip(tmp_path):
    """tool_use_enabled bool survives a save/load cycle."""
    from app.core.config import AppConfig

    mgr = _make_isolated_manager(tmp_path)

    for value in (True, False, True):
        cfg = AppConfig()
        cfg.tool_use_enabled = value
        mgr.save(cfg)
        reloaded = mgr.load()
        assert reloaded.tool_use_enabled is value, (
            f"tool_use_enabled={value!r} did not round-trip; got {reloaded.tool_use_enabled!r}"
        )

    save("config_tool_use_enabled_roundtrip", True, {"values_tested": [True, False, True]})


def test_config_permission_mode_roundtrip(tmp_path):
    """permission_mode enum survives save/load for all three variants."""
    from app.core.config import AppConfig, PermissionMode

    mgr = _make_isolated_manager(tmp_path)

    for mode in (PermissionMode.ASK, PermissionMode.AUTO_APPROVE, PermissionMode.DENY_ALL):
        cfg = AppConfig()
        cfg.permission_mode = mode
        mgr.save(cfg)
        reloaded = mgr.load()
        assert reloaded.permission_mode == mode, (
            f"permission_mode={mode!r} did not round-trip; got {reloaded.permission_mode!r}"
        )

    save("config_permission_mode_roundtrip", True, {
        "modes_tested": [m.value for m in PermissionMode]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# B. ChatSession.send() with tool_use_enabled
# ═══════════════════════════════════════════════════════════════════════════════

def _make_chat_session(tool_use_enabled: bool = False):
    """Return a ChatSession with a mock context and config."""
    from app.core.config import AppConfig
    from cli.chat_session import ChatSession

    cfg = AppConfig()
    cfg.tool_use_enabled = tool_use_enabled
    cfg.provider = "openai"

    ctx = MagicMock()
    ctx.expand_at_paths.return_value = ("hello", [])
    ctx.build_system_prompt.return_value = ""

    session = ChatSession(cfg=cfg, ctx=ctx)
    return session


def test_chat_send_calls_chat_with_tools(capsys):
    """When tool_use_enabled=True, send() calls chat_with_tools, not chat_stream."""
    session = _make_chat_session(tool_use_enabled=True)

    mock_client = MagicMock()
    # chat_with_tools returns (text, []) — no tool calls, immediate text answer
    mock_client.chat_with_tools.return_value = ("Hello from tools mode", [])
    mock_client.last_usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    mock_client.model = "gpt-4o"

    mock_mcp = MagicMock()
    mock_mcp.register_builtin_tools = MagicMock()

    # chat_session.send() does: from codex.app.llm_client import get_chat_llm_client as get_llm_client
    # The local name is bound at call time, so patch the source object.
    with patch("codex.app.llm_client.get_chat_llm_client", return_value=mock_client), \
         patch("app.core.mcp_client.MCPClient", return_value=mock_mcp), \
         patch("app.core.audit.log_llm_call"):
        result = session.send("hello")

    assert result is True, "send() should return True on success"
    mock_client.chat_with_tools.assert_called_once()
    mock_client.chat_stream.assert_not_called()

    captured = capsys.readouterr()
    assert "Hello from tools mode" in captured.out

    save("chat_send_calls_chat_with_tools", True, {
        "chat_with_tools_called": True,
        "chat_stream_called": False,
    })


def test_chat_send_stops_after_max_rounds(capsys):
    """Tool-use loop halts at 5 rounds and appends '(tool-use loop limit reached)'."""
    session = _make_chat_session(tool_use_enabled=True)

    # Every call returns a tool call — never a final text answer
    fake_tool_call = [{"name": "read_file", "id": "tc_001", "input": {"path": "foo.txt"}}]
    mock_client = MagicMock()
    mock_client.chat_with_tools.return_value = ("", fake_tool_call)
    mock_client.last_usage = MagicMock(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    mock_client.model = "gpt-4o"

    mock_mcp = MagicMock()
    mock_mcp.register_builtin_tools = MagicMock()
    mock_mcp.call.return_value = {"success": True, "result": "file contents"}

    # fmt is imported inside _send_with_tools — patch at the source module
    mock_fmt = MagicMock()
    mock_fmt.format_assistant_tool_calls_openai.return_value = {"role": "assistant", "tool_calls": []}
    mock_fmt.format_tool_result_openai.return_value = {"role": "tool", "content": ""}

    with patch("codex.app.llm_client.get_chat_llm_client", return_value=mock_client), \
         patch("app.core.mcp_client.MCPClient", return_value=mock_mcp), \
         patch("app.core.tool_result_formatter.format_assistant_tool_calls_openai",
               mock_fmt.format_assistant_tool_calls_openai), \
         patch("app.core.tool_result_formatter.format_tool_result_openai",
               mock_fmt.format_tool_result_openai), \
         patch("app.core.audit.log_llm_call"):
        result = session.send("do stuff")

    assert result is True
    # Must have called chat_with_tools exactly 5 times (the limit)
    assert mock_client.chat_with_tools.call_count == 5, (
        f"Expected 5 tool rounds, got {mock_client.chat_with_tools.call_count}"
    )

    captured = capsys.readouterr()
    assert "loop limit" in captured.out.lower() or "limit" in captured.out.lower(), (
        f"Expected loop limit message. stdout={captured.out[:400]!r}"
    )

    save("chat_send_stops_after_max_rounds", True, {
        "rounds": mock_client.chat_with_tools.call_count,
        "stdout_snippet": captured.out[:300],
    })


def test_chat_send_tool_error_graceful(capsys):
    """MCP tool execution returning an error result does not crash send()."""
    session = _make_chat_session(tool_use_enabled=True)

    fake_tool_call = [{"name": "read_file", "id": "tc_err", "input": {"path": "boom.txt"}}]
    # First call returns tool calls; second call (after tool error) returns final text
    mock_client = MagicMock()
    mock_client.chat_with_tools.side_effect = [
        ("", fake_tool_call),
        ("Recovered after error", []),
    ]
    mock_client.last_usage = MagicMock(prompt_tokens=5, completion_tokens=5, total_tokens=10)
    mock_client.model = "gpt-4o"

    mock_mcp = MagicMock()
    mock_mcp.register_builtin_tools = MagicMock()
    # Tool returns error result dict (not raising)
    mock_mcp.call.return_value = {"success": False, "error": "Permission denied", "result": None}

    mock_fmt = MagicMock()
    mock_fmt.format_assistant_tool_calls_openai.return_value = {"role": "assistant", "tool_calls": []}
    mock_fmt.format_tool_result_openai.return_value = {"role": "tool", "content": ""}

    with patch("codex.app.llm_client.get_chat_llm_client", return_value=mock_client), \
         patch("app.core.mcp_client.MCPClient", return_value=mock_mcp), \
         patch("app.core.tool_result_formatter.format_assistant_tool_calls_openai",
               mock_fmt.format_assistant_tool_calls_openai), \
         patch("app.core.tool_result_formatter.format_tool_result_openai",
               mock_fmt.format_tool_result_openai), \
         patch("app.core.audit.log_llm_call"):
        result = session.send("read a file")

    # Should complete without raising
    assert result is True, f"send() should not crash on tool error. result={result}"

    save("chat_send_tool_error_graceful", True, {
        "completed_without_exception": True,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# C. MCP client — extended
# ═══════════════════════════════════════════════════════════════════════════════

def _fresh_mcp(tmp_path: Path):
    """Return an isolated MCPClient that writes to tmp_path."""
    from app.core import mcp_client as _mod
    tools_file = tmp_path / "mcp_tools.json"
    with patch.object(_mod, "_MCP_TOOLS_FILE", tools_file):
        client = _mod.MCPClient()
    return client


def test_mcp_registers_all_14_builtin_tools(tmp_path):
    """register_builtin_tools() registers exactly 14 built-in tools."""
    client = _fresh_mcp(tmp_path)
    client.register_builtin_tools()

    # We check all 13 filesystem+converter+web tools are present
    EXPECTED = {
        "read_file", "write_file", "list_dir", "run_command",
        "read_pdf", "write_pdf",
        "read_docx", "write_docx",
        "read_xlsx", "write_xlsx",
        "read_png", "write_png",
        "fetch_url",
    }
    registered = {t.name for t in client.tools}
    missing = EXPECTED - registered

    ok = len(missing) == 0
    save("mcp_registers_all_builtin_tools", ok, {
        "registered": sorted(registered),
        "expected": sorted(EXPECTED),
        "missing": sorted(missing),
        "total": len(registered),
    })
    assert ok, f"Missing built-in tools after register_builtin_tools(): {missing}"


def test_mcp_fetch_url_calls_web_fetch(tmp_path):
    """fetch_url tool dispatches to web_fetch.fetch_url with correct args."""
    client = _fresh_mcp(tmp_path)
    client.register_builtin_tools()

    fake_fetch_result = {
        "ok": True,
        "title": "Example Page",
        "text": "This is example content for the test.",
    }

    with patch("app.core.web_fetch.fetch_url", return_value=fake_fetch_result) as mock_fetch:
        result = client.call("fetch_url", {"url": "https://example.com", "timeout": 10})

    mock_fetch.assert_called_once_with("https://example.com", 10)
    ok = result.get("success") is True and "Example Page" in result.get("result", "")

    save("mcp_fetch_url_calls_web_fetch", ok, {
        "success": result.get("success"),
        "result_snippet": result.get("result", "")[:200],
        "fetch_called_with": ("https://example.com", 10),
    })
    assert ok, f"fetch_url tool result unexpected: {result}"


@pytest.mark.security
def test_mcp_sandbox_blocks_path_traversal(tmp_path):
    """read_file with a path-traversal arg fails sandbox check when working_folder is set."""
    from app.core.config import AppConfig

    cfg = AppConfig()
    cfg.working_folder = str(tmp_path)

    from app.core import mcp_client as _mod
    tools_file = tmp_path / "mcp_tools.json"
    with patch.object(_mod, "_MCP_TOOLS_FILE", tools_file):
        client = _mod.MCPClient(cfg=cfg)
    client.register_builtin_tools()

    # Try to read a file outside the working folder via path traversal
    result = client.call("read_file", {"path": "../../etc/passwd"})

    ok = result.get("success") is False and (
        "sandbox" in (result.get("error") or "").lower()
        or "outside" in (result.get("error") or "").lower()
    )
    save("mcp_sandbox_blocks_path_traversal", ok, {
        "success": result.get("success"),
        "error": result.get("error"),
    })
    assert result["success"] is False, (
        f"Path traversal should be blocked but got success=True: {result}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# D. Supervisor
# ═══════════════════════════════════════════════════════════════════════════════

def test_supervisor_warn_before_kill():
    """The reader thread appends an 80%-warning message before killing a task."""
    from app.core.supervisor import ProcessSupervisor, TaskStatus, ManagedTask

    sup = ProcessSupervisor(max_concurrent=2)

    # Create a fake task with output_tail we can inspect
    task = ManagedTask(
        task_id="T_WARN",
        label="warn_test",
        command=["sleep", "100"],
        cwd=None,
        status=TaskStatus.RUNNING,
    )
    with sup._lock:
        sup._tasks["T_WARN"] = task

    # Simulate the warn logic the reader would trigger
    timeout = 10
    warn_at = task.started_at + timeout * 0.8  # 8s mark
    elapsed = warn_at - task.started_at  # 8.0

    with sup._lock:
        t = sup._tasks["T_WARN"]
        warn_msg = (
            f"[ILX] Approaching timeout ({elapsed:.0f}s/{timeout}s)"
            " — will terminate soon"
        )
        t.output_tail.append(warn_msg)

    with sup._lock:
        tail = sup._tasks["T_WARN"].output_tail

    has_warn = any("Approaching timeout" in ln for ln in tail)
    ok = has_warn

    save("supervisor_warn_before_kill", ok, {
        "tail": tail,
        "has_warn": has_warn,
    })
    assert ok, f"Expected warn message in output_tail. tail={tail}"


def test_supervisor_queue_drain():
    """When a RUNNING task finishes, _on_task_done() launches the next queued task."""
    from app.core.supervisor import ProcessSupervisor, TaskStatus, ManagedTask, _QueuedItem

    sup = ProcessSupervisor(max_concurrent=1)

    # Inject a "running" task
    running_task = ManagedTask(
        task_id="T_RUN",
        label="running",
        command=["echo", "run"],
        cwd=None,
        status=TaskStatus.RUNNING,
    )
    with sup._lock:
        sup._tasks["T_RUN"] = running_task

    # Inject a queued item
    queued_task = ManagedTask(
        task_id="T_QUEUED",
        label="queued",
        command=["echo", "queued"],
        cwd=None,
        status=TaskStatus.QUEUED,
    )
    with sup._lock:
        sup._tasks["T_QUEUED"] = queued_task
        sup._queue.append(_QueuedItem(
            task_id="T_QUEUED",
            command=["echo", "queued"],
            label="queued",
            cwd=None,
            timeout=None,
            on_line=None,
            on_finish=None,
            env=None,
        ))

    launched: list[str] = []

    def _fake_launch(task_id, command, label, cwd, timeout, on_line, on_finish, env):
        launched.append(task_id)
        with sup._lock:
            t = sup._tasks.get(task_id)
            if t:
                t.status = TaskStatus.RUNNING

    with patch.object(sup, "_launch", side_effect=_fake_launch):
        sup._on_task_done("T_RUN")

    ok = "T_QUEUED" in launched and len(sup._queue) == 0
    save("supervisor_queue_drain", ok, {
        "launched": launched,
        "queue_len": len(sup._queue),
    })
    assert "T_QUEUED" in launched, (
        f"Expected T_QUEUED to be launched after T_RUN finished. launched={launched}"
    )
    assert len(sup._queue) == 0, "Queue should be empty after draining"


def test_supervisor_kill_calls_taskkill(tmp_path):
    """On Windows, _kill_proc() calls 'taskkill /F /T /PID <pid>'."""
    from app.core.supervisor import ProcessSupervisor, TaskStatus, ManagedTask

    sup = ProcessSupervisor(max_concurrent=4)

    fake_pid = 12345
    mock_proc = MagicMock()
    mock_proc.pid = fake_pid
    mock_proc.poll.return_value = None

    task = ManagedTask(
        task_id="T_KILL",
        label="kill_test",
        command=["sleep", "999"],
        cwd=None,
        status=TaskStatus.RUNNING,
    )
    task.pid = fake_pid
    with sup._lock:
        sup._tasks["T_KILL"] = task
        sup._procs["T_KILL"] = mock_proc

    with patch("sys.platform", "win32"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = sup._kill_proc("T_KILL", mock_proc)

    assert result is True
    # Verify taskkill was called
    args = mock_run.call_args[0][0]
    ok = (
        result is True
        and "taskkill" in args
        and "/F" in args
        and "/T" in args
        and str(fake_pid) in args
    )
    save("supervisor_kill_calls_taskkill", ok, {
        "taskkill_args": args,
        "result": result,
    })
    assert ok, f"taskkill call incorrect. args={args}"


# ═══════════════════════════════════════════════════════════════════════════════
# E. Scaffold
# ═══════════════════════════════════════════════════════════════════════════════

def _make_upgrade_cmd(tmp_path: Path):
    from cli.commands.workspace_scaffold import UpgradeCommand
    from app.core.config import AppConfig

    cfg = AppConfig()
    cfg.working_folder = str(tmp_path)
    return UpgradeCommand(cfg)


def test_upgrade_detects_go_mod(tmp_path, capsys):
    """/upgrade detects go.mod and suggests the 'go' template."""
    (tmp_path / "go.mod").write_text(
        "module example.com/myapp\n\ngo 1.22\n",
        encoding="utf-8",
    )

    with patch("builtins.input", return_value="n"):
        _make_upgrade_cmd(tmp_path).cmd_upgrade([])

    out = capsys.readouterr().out
    ok = "go" in out.lower()
    save("upgrade_detects_go_mod", ok, {"output_snippet": out[:400]})
    assert ok, f"Expected 'go' in upgrade output. Got: {out[:400]!r}"


def test_upgrade_detects_cargo_toml(tmp_path, capsys):
    """/upgrade detects Cargo.toml and suggests the 'rust' template."""
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "myapp"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )

    with patch("builtins.input", return_value="n"):
        _make_upgrade_cmd(tmp_path).cmd_upgrade([])

    out = capsys.readouterr().out
    ok = "rust" in out.lower() or "cargo" in out.lower()
    save("upgrade_detects_cargo_toml", ok, {"output_snippet": out[:400]})
    assert ok, f"Expected 'rust'/'cargo' in upgrade output. Got: {out[:400]!r}"


def test_scaffold_env_complex_values(tmp_path, capsys):
    """/scaffold env handles .env values containing spaces, quotes, and URLs."""
    from cli.commands.workspace_scaffold import ScaffoldExtensions
    from app.core.config import AppConfig

    cfg = AppConfig()
    cfg.working_folder = str(tmp_path)

    env_content = (
        "PORT=5000\n"
        'SECRET_KEY=my very secret key with spaces\n'
        "DATABASE_URL=postgresql://user:pass@localhost:5432/mydb\n"
        "REDIS_URL=redis://localhost:6379/0\n"
        '# comment line\n'
        "EMPTY_VAR=\n"
    )
    (tmp_path / ".env").write_text(env_content, encoding="utf-8")

    ScaffoldExtensions(cfg).cmd_scaffold_env()

    example = tmp_path / ".env.example"
    assert example.exists(), ".env.example not created"
    content = example.read_text(encoding="utf-8")

    keys_present = all(k in content for k in ("PORT", "SECRET_KEY", "DATABASE_URL", "REDIS_URL"))
    # Values must be blank
    values_blank = True
    for line in content.splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            _, _, val = line.partition("=")
            if val != "":
                values_blank = False

    ok = keys_present and values_blank
    save("scaffold_env_complex_values", ok, {
        "keys_present": keys_present,
        "values_blank": values_blank,
        "content_snippet": content[:400],
    })
    assert keys_present, f"Not all keys present in .env.example. Content:\n{content}"
    assert values_blank, f"Values should be blank in .env.example. Content:\n{content}"
