"""Cluster 12 — Self-improvement / user tools system.

Tests:
  test_registry_name_validation         — check_name() accepts valid, rejects reserved/invalid
  test_registry_collision_detection     — check_name() rejects names conflicting with built-ins
  test_registry_register_and_list       — register a UserTool, list_tools() returns it
  test_registry_unregister              — unregister removes from list
  test_registry_persistence             — save() + new registry load() roundtrips correctly
  test_registry_is_user_command         — is_user_command() returns True for registered tool
  test_validator_syntax_ok              — ToolValidator on valid Python passes syntax check
  test_validator_syntax_error           — ToolValidator on broken Python fails with error
  test_validator_healthcheck_support    — tool with --ilx-healthcheck flag passes smoke test
  test_builder_generate_template        — ToolBuilder.generate_code() with no LLM returns template
  test_builder_create_tool_approved     — create_tool() with approving callback writes file
  test_builder_create_tool_denied       — create_tool() with denying callback does not write file
  test_runner_run_sync_hello            — ToolRunner.run_sync() on a simple hello script
  test_runner_run_async_streams_output  — run_async() streams output via on_output callback
  test_user_tools_cmd_list_empty        — UserToolsCommands.cmd_tool(["list"]) prints no-tools msg
  test_user_tools_cmd_list_with_tool    — after registering, cmd_tool(["list"]) shows the tool
  test_user_tools_is_user_command       — is_user_command() delegates to registry correctly
  test_full_lifecycle                   — create → validate → register → run → unregister cycle
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save  # noqa: E402

import sys as _sys; PYTHON_EXE = _sys.executable

# ── Guard imports — modules may not exist yet ─────────────────────────────────
try:
    from app.core.user_tools.registry import UserToolRegistry, UserTool, RESERVED_COMMANDS
    HAS_REGISTRY = True
except (ImportError, ModuleNotFoundError):
    HAS_REGISTRY = False
    UserToolRegistry = UserTool = None  # type: ignore
    RESERVED_COMMANDS = set()           # type: ignore

try:
    from app.core.user_tools.validator import ToolValidator
    HAS_VALIDATOR = True
except (ImportError, ModuleNotFoundError):
    HAS_VALIDATOR = False
    ToolValidator = None  # type: ignore

try:
    from app.core.user_tools.runner import ToolRunner
    HAS_RUNNER = True
except (ImportError, ModuleNotFoundError):
    HAS_RUNNER = False
    ToolRunner = None  # type: ignore

try:
    from app.core.user_tools.builder import ToolBuilder
    HAS_BUILDER = True
except (ImportError, ModuleNotFoundError):
    HAS_BUILDER = False
    ToolBuilder = None  # type: ignore

try:
    from cli.commands.user_tools_cmds import UserToolsCommands
    HAS_CMDS = True
except (ImportError, ModuleNotFoundError):
    HAS_CMDS = False
    UserToolsCommands = None  # type: ignore

# ── Skip marks ────────────────────────────────────────────────────────────────
_SKIP_REG = pytest.mark.skipif(not HAS_REGISTRY,  reason="app.core.user_tools.registry not found")
_SKIP_VAL = pytest.mark.skipif(not HAS_VALIDATOR, reason="app.core.user_tools.validator not found")
_SKIP_RUN = pytest.mark.skipif(not HAS_RUNNER,    reason="app.core.user_tools.runner not found")
_SKIP_BLD = pytest.mark.skipif(not HAS_BUILDER,   reason="app.core.user_tools.builder not found")
_SKIP_CMD = pytest.mark.skipif(not HAS_CMDS,      reason="cli.commands.user_tools_cmds not found")
_SKIP_ALL = pytest.mark.skipif(
    not (HAS_REGISTRY and HAS_VALIDATOR and HAS_RUNNER and HAS_BUILDER),
    reason="one or more user_tools modules not found",
)

# ── Minimal healthcheck-aware tool script ─────────────────────────────────────
_HC_SCRIPT = (
    "import sys, os\n"
    "def main():\n"
    "    if os.environ.get('ILX_TOOL_VALIDATE') == '1':\n"
    "        sys.exit(0)\n"
    "    if '--ilx-healthcheck' in sys.argv:\n"
    "        print('OK: hc_tool health check passed')\n"
    "        sys.exit(0)\n"
    "    print('Hello from hc_tool')\n"
    "if __name__ == '__main__':\n"
    "    main()\n"
)


def _result_ok(r) -> bool:
    if isinstance(r, dict):
        return bool(r.get("ok", False))
    return bool(getattr(r, "ok", False))


def _result_output(r) -> str:
    if isinstance(r, dict):
        return r.get("output", "")
    return getattr(r, "output", "")


def _tool_names(reg) -> list[str]:
    return [t.name for t in reg.list_tools()]


def _check_ok(result) -> bool:
    if hasattr(result, "ok"):
        return bool(result.ok)
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result)


# =============================================================================
# 1. Registry — name validation
# =============================================================================
@_SKIP_REG
def test_registry_name_validation(tmp_path, cfg):
    reg = UserToolRegistry(registry_path=tmp_path / "registry.json")
    valid   = ["my_tool", "tool1", "alpha_beta", "stockmarket"]
    invalid = ["", "123tool", "tool name", "tool!"]

    accept = [(n, _check_ok(reg.check_name(n))) for n in valid]
    reject = [(n, _check_ok(reg.check_name(n))) for n in invalid]

    ok = all(v for _, v in accept) and all(not v for _, v in reject)
    save("registry_name_validation", ok, {"valid": accept, "invalid": reject})
    assert all(v for _, v in accept),  f"Valid names rejected: {[x for x in accept if not x[1]]}"
    assert all(not v for _, v in reject), f"Invalid names accepted: {[x for x in reject if x[1]]}"


# =============================================================================
# 2. Registry — collision detection
# =============================================================================
@_SKIP_REG
def test_registry_collision_detection(tmp_path, cfg):
    if not RESERVED_COMMANDS:
        pytest.skip("RESERVED_COMMANDS is empty")
    reg = UserToolRegistry(registry_path=tmp_path / "registry.json")
    tested = [(n, _check_ok(reg.check_name(n))) for n in list(RESERVED_COMMANDS)[:3]]
    ok = all(not v for _, v in tested)
    save("registry_collision_detection", ok, {"results": tested})
    assert ok, f"Reserved names should be rejected: {tested}"


# =============================================================================
# 3. Registry — register and list
# =============================================================================
@_SKIP_REG
def test_registry_register_and_list(tmp_path, cfg):
    reg = UserToolRegistry(registry_path=tmp_path / "registry.json")
    reg.register(UserTool(name="list_test_tool", description="test", path=str(tmp_path / "t.py")))
    names = _tool_names(reg)
    ok = "list_test_tool" in names
    save("registry_register_and_list", ok, {"names": names})
    assert ok, f"Expected 'list_test_tool' in {names}"


# =============================================================================
# 4. Registry — unregister
# =============================================================================
@_SKIP_REG
def test_registry_unregister(tmp_path, cfg):
    reg = UserToolRegistry(registry_path=tmp_path / "registry.json")
    reg.register(UserTool(name="remove_me", description="temp", path=str(tmp_path / "r.py")))
    assert "remove_me" in _tool_names(reg), "Pre-condition: must be registered first"
    reg.unregister("remove_me")
    after = _tool_names(reg)
    ok = "remove_me" not in after
    save("registry_unregister", ok, {"after": after})
    assert ok, f"'remove_me' should be gone after unregister(). After: {after}"


# =============================================================================
# 5. Registry — persistence
# =============================================================================
@_SKIP_REG
def test_registry_persistence(tmp_path, cfg):
    reg_file = tmp_path / "registry.json"
    reg1 = UserToolRegistry(registry_path=reg_file)
    reg1.register(UserTool(name="persist_tool", description="persisted", path=str(tmp_path / "p.py")))
    reg1.save()

    reg2 = UserToolRegistry(registry_path=reg_file)
    names = _tool_names(reg2)
    ok = "persist_tool" in names
    save("registry_persistence", ok, {"file": str(reg_file), "names": names})
    assert reg_file.exists(), f"Registry file missing at {reg_file}"
    assert ok, f"Reloaded registry should contain 'persist_tool'. Got: {names}"


# =============================================================================
# 6. Registry — is_user_command
# =============================================================================
@_SKIP_REG
def test_registry_is_user_command(tmp_path, cfg):
    reg = UserToolRegistry(registry_path=tmp_path / "registry.json")
    reg.register(UserTool(name="known_cmd", description="cmd", path=str(tmp_path / "k.py")))
    is_known   = reg.is_user_command("known_cmd")
    is_unknown = reg.is_user_command("no_such_cmd_xyz")
    ok = is_known and not is_unknown
    save("registry_is_user_command", ok, {"is_known": is_known, "is_unknown": is_unknown})
    assert is_known,      "is_user_command('known_cmd') should return True"
    assert not is_unknown, "is_user_command('no_such_cmd_xyz') should return False"


# =============================================================================
# 7. Validator — valid Python passes
# =============================================================================
@_SKIP_VAL
def test_validator_syntax_ok(tmp_path, cfg):
    script = tmp_path / "good.py"
    script.write_text(
        "def main():\n    print('hi')\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    result = ToolValidator().validate(str(script))
    ok = _check_ok(result)
    save("validator_syntax_ok", ok, {"ok": ok, "errors": getattr(result, "errors", [])})
    assert ok, f"Valid Python should pass validator. Errors: {getattr(result, 'errors', result)}"


# =============================================================================
# 8. Validator — syntax error fails
# =============================================================================
@_SKIP_VAL
def test_validator_syntax_error(tmp_path, cfg):
    script = tmp_path / "bad.py"
    script.write_text("def main(\n    print('oops')\n", encoding="utf-8")
    result = ToolValidator().validate(str(script))
    ok_field = _check_ok(result)
    save("validator_syntax_error", not ok_field, {"ok": ok_field, "errors": getattr(result, "errors", [])})
    assert not ok_field, "Broken Python should return ok=False from validator"


# =============================================================================
# 9. Validator — healthcheck support
# =============================================================================
@_SKIP_VAL
def test_validator_healthcheck_support(tmp_path, cfg):
    script = tmp_path / "hc_tool.py"
    script.write_text(_HC_SCRIPT, encoding="utf-8")
    result = ToolValidator().validate(str(script))
    ok = _check_ok(result)
    save("validator_healthcheck_support", ok, {
        "ok": ok,
        "errors": getattr(result, "errors", []),
        "warnings": getattr(result, "warnings", []),
    })
    assert ok, f"Healthcheck tool should pass validator. Errors: {getattr(result, 'errors', result)}"


# =============================================================================
# 10. Builder — generate_code returns template (no LLM)
# =============================================================================
@_SKIP_BLD
def test_builder_generate_template(tmp_path, cfg):
    # ToolBuilder(cfg, llm_client=None) — cfg must have working_folder
    from app.core.config import AppConfig
    test_cfg = AppConfig()
    test_cfg.working_folder = str(tmp_path)
    test_cfg.ollama_url     = cfg.ollama_url
    test_cfg.ollama_model   = cfg.ollama_model

    builder = ToolBuilder(test_cfg, llm_client=None)
    code = builder.generate_code("mytest", "test tool", "do nothing")
    has_main = "def main" in code
    has_hc   = "ilx-healthcheck" in code
    ok = has_main and has_hc
    save("builder_generate_template", ok, {
        "has_main": has_main, "has_hc": has_hc, "snippet": code[:200],
    })
    assert has_main, f"Template missing 'def main'. Got:\n{code[:300]}"
    assert has_hc,   f"Template missing 'ilx-healthcheck'. Got:\n{code[:300]}"


# =============================================================================
# 11. Builder — create_tool approved
# =============================================================================
@_SKIP_BLD
def test_builder_create_tool_approved(tmp_path, cfg):
    from app.core.config import AppConfig
    test_cfg = AppConfig()
    test_cfg.working_folder = str(tmp_path)

    builder = ToolBuilder(test_cfg, llm_client=None)
    code    = builder.generate_code("approved_tool", "prints approved", "print approved")
    result  = builder.create_tool(
        name="approved_tool",
        description="prints approved",
        code=code,
        permission_callback=lambda *_: True,
    )
    ok_field = _result_ok(result)
    # Tool lands in <working_folder>/user_tools/<name>.py
    tool_path = builder.tools_dir() / "approved_tool.py"
    file_exists = tool_path.exists()
    ok = ok_field and file_exists
    save("builder_create_tool_approved", ok, {
        "ok": ok_field, "file_exists": file_exists, "path": str(tool_path),
    })
    assert ok_field,   f"create_tool() should return ok=True when approved. Got: {result}"
    assert file_exists, f"Tool file not found at {tool_path}"


# =============================================================================
# 12. Builder — create_tool denied
# =============================================================================
@_SKIP_BLD
def test_builder_create_tool_denied(tmp_path, cfg):
    from app.core.config import AppConfig
    test_cfg = AppConfig()
    test_cfg.working_folder = str(tmp_path)

    builder = ToolBuilder(test_cfg, llm_client=None)
    code    = builder.generate_code("denied_tool", "not created", "print denied")
    result  = builder.create_tool(
        name="denied_tool",
        description="not created",
        code=code,
        permission_callback=lambda *_: False,
    )
    ok_field = _result_ok(result)
    tool_path = builder.tools_dir() / "denied_tool.py"
    file_exists = tool_path.exists()
    passed = not ok_field and not file_exists
    save("builder_create_tool_denied", passed, {
        "ok": ok_field, "file_exists": file_exists,
    })
    assert not ok_field,   f"create_tool() should return ok=False when denied. Got: {result}"
    assert not file_exists, f"Tool file should NOT be written when denied. Found: {tool_path}"


# =============================================================================
# 13. Runner — run_sync hello
# =============================================================================
@_SKIP_RUN
def test_runner_run_sync_hello(tmp_path, cfg):
    script = tmp_path / "hello_tool.py"
    script.write_text("print('hello_from_tool')\n", encoding="utf-8")
    result  = ToolRunner().run_sync(str(script))
    ok_field = _result_ok(result)
    output   = _result_output(result)
    has_msg  = "hello_from_tool" in output
    ok = ok_field and has_msg
    save("runner_run_sync_hello", ok, {
        "ok": ok_field, "output": output[:200], "has_msg": has_msg,
    })
    assert ok_field, f"run_sync() should return ok=True. Got: {result}"
    assert has_msg,  f"Expected 'hello_from_tool' in output. Got: {output[:200]!r}"


# =============================================================================
# 14. Runner — run_async streams output
# =============================================================================
@_SKIP_RUN
def test_runner_run_async_streams_output(tmp_path, cfg):
    script = tmp_path / "three_lines.py"
    script.write_text(
        "print('line_one')\nprint('line_two')\nprint('line_three')\n",
        encoding="utf-8",
    )
    collected: list[str] = []
    handle = ToolRunner().run_async(str(script), on_output=collected.append)
    if isinstance(handle, threading.Thread):
        handle.join(timeout=15)
    elif hasattr(handle, "join"):
        handle.join(timeout=15)

    combined = "\n".join(collected)
    ok = all(kw in combined for kw in ("line_one", "line_two", "line_three"))
    save("runner_run_async_streams_output", ok, {"collected": collected})
    assert "line_one"   in combined, f"Missing 'line_one'. collected={collected}"
    assert "line_two"   in combined, f"Missing 'line_two'. collected={collected}"
    assert "line_three" in combined, f"Missing 'line_three'. collected={collected}"


# =============================================================================
# 15. UserToolsCommands — list empty
# =============================================================================
@_SKIP_CMD
def test_user_tools_cmd_list_empty(tmp_path, cfg, capsys):
    # UserToolsCommands uses the module-level registry singleton internally.
    # Patch it to use a fresh empty registry for isolation.
    from app.core.user_tools import registry as _reg_mod
    orig = _reg_mod.registry
    try:
        _reg_mod.registry = UserToolRegistry(registry_path=tmp_path / "registry_empty.json")
        cmds = UserToolsCommands(cfg=cfg)
        cmds.cmd_tool(["list"])
        out = capsys.readouterr().out.lower()
        keywords = ("no tool", "no user tool", "empty", "none yet", "0 tool", "create")
        ok = any(kw in out for kw in keywords)
        save("user_tools_cmd_list_empty", ok, {"output": out[:300]})
        assert ok, f"Expected empty-list message. Got: {out[:300]!r}"
    finally:
        _reg_mod.registry = orig


# =============================================================================
# 16. UserToolsCommands — list with tool
# =============================================================================
@_SKIP_CMD
def test_user_tools_cmd_list_with_tool(tmp_path, cfg, capsys):
    reg = UserToolRegistry(registry_path=tmp_path / "registry_with.json")
    reg.register(UserTool(name="visible_tool", description="shown", path=str(tmp_path / "v.py")))
    cmds = UserToolsCommands(cfg=cfg)
    cmds._registry = reg  # inject isolated registry directly
    cmds.cmd_tool(["list"])
    out = capsys.readouterr().out
    ok = "visible_tool" in out
    save("user_tools_cmd_list_with_tool", ok, {"output": out[:300]})
    assert ok, f"Expected 'visible_tool' in output. Got: {out[:300]!r}"


# =============================================================================
# 17. UserToolsCommands — is_user_command delegates
# =============================================================================
@_SKIP_CMD
def test_user_tools_is_user_command(tmp_path, cfg):
    reg = UserToolRegistry(registry_path=tmp_path / "registry_delegate.json")
    reg.register(UserTool(name="delegate_tool", description="delegate", path=str(tmp_path / "d.py")))
    cmds = UserToolsCommands(cfg=cfg)
    cmds._registry = reg  # inject isolated registry
    is_known   = cmds.is_user_command("delegate_tool")
    is_unknown = cmds.is_user_command("not_a_real_tool_xyz")
    ok = is_known and not is_unknown
    save("user_tools_is_user_command", ok, {"is_known": is_known, "is_unknown": is_unknown})
    assert is_known,      "is_user_command('delegate_tool') should return True"
    assert not is_unknown, "is_user_command('not_a_real_tool_xyz') should return False"


# =============================================================================
# 18. Full lifecycle
# =============================================================================
@_SKIP_ALL
def test_full_lifecycle(tmp_path, cfg):
    """End-to-end: generate code → validate → register → run → unregister."""
    from app.core.config import AppConfig

    # 1. Isolated registry
    registry = UserToolRegistry(registry_path=tmp_path / "registry.json")

    # 2. Builder with tmp workspace
    test_cfg = AppConfig()
    test_cfg.working_folder = str(tmp_path)
    test_cfg.ollama_url     = cfg.ollama_url
    test_cfg.ollama_model   = cfg.ollama_model
    builder = ToolBuilder(test_cfg, llm_client=None)

    # 3. Generate code (template, no LLM)
    code = builder.generate_code("testcycle", "lifecycle test tool", "print a message")
    assert "def main" in code, f"Generated code missing 'def main'. Snippet:\n{code[:300]}"

    # 4. Write file via create_tool with approval
    create_result = builder.create_tool(
        name="testcycle",
        description="lifecycle test tool",
        code=code,
        permission_callback=lambda *_: True,
    )
    assert _result_ok(create_result), f"create_tool() failed. Result: {create_result}"

    tool_path = builder.tools_dir() / "testcycle.py"
    assert tool_path.exists(), f"Tool file not found at {tool_path}"

    # 5. Validate
    val_result = ToolValidator().validate(str(tool_path))
    assert _check_ok(val_result), (
        f"Generated tool failed validation. Errors: {getattr(val_result, 'errors', val_result)}"
    )

    # 6. Register
    registry.register(UserTool(
        name="testcycle",
        description="lifecycle test",
        path=str(tool_path),
    ))

    # 7. is_user_command True
    assert registry.is_user_command("testcycle"), (
        "is_user_command('testcycle') should be True after registering"
    )

    # 8. Run
    run_result = ToolRunner().run_sync(str(tool_path))
    assert _result_ok(run_result), f"ToolRunner.run_sync() failed. Result: {run_result}"

    # 9. Unregister
    registry.unregister("testcycle")

    # 10. is_user_command False
    assert not registry.is_user_command("testcycle"), (
        "is_user_command('testcycle') should be False after unregistering"
    )

    save("full_lifecycle", True, {
        "tool_path": str(tool_path),
        "code_snippet": code[:200],
        "run_output": _result_output(run_result)[:100],
    })
