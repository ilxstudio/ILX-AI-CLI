"""Cluster 15 — Expanded scaffolding: new /init templates, /scaffold static types,
/template list, and /upgrade.

Tests:
  - test_init_flask          : /init flask creates app.py with "Flask" + .env.example
  - test_init_express        : /init express creates index.js + package.json
  - test_init_nextjs         : /init nextjs creates pages/index.jsx
  - test_init_vue            : /init vue creates src/App.vue
  - test_init_cli_tool       : /init cli-tool creates src/cli/main.py
  - test_init_library        : /init library creates src/{name}/__init__.py with name substituted
  - test_scaffold_dry_run    : --dry-run arg prints [dry-run] message, no files written
  - test_scaffold_precommit  : /scaffold pre-commit writes .pre-commit-config.yaml
  - test_scaffold_compose    : /scaffold compose writes docker-compose.yml with "postgres"
  - test_template_list_all   : cmd_template_list() output contains all 15+ init types
  - test_upgrade_detects_flask: flask project gets flask template comparison
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws(tmp_path: Path):
    """Return a WorkspaceCommands bound to tmp_path."""
    from cli.commands.workspace_cmds import WorkspaceCommands
    from cli.context import ContextManager
    from app.core.config import AppConfig

    cfg = AppConfig()
    cfg.working_folder = str(tmp_path)
    ctx = ContextManager(cfg)
    return WorkspaceCommands(cfg, ctx), cfg


# ---------------------------------------------------------------------------
# /init flask
# ---------------------------------------------------------------------------

def test_init_flask(tmp_path, capsys):
    """/init flask creates app.py with 'Flask' in it and .env.example."""
    ws, _ = _make_ws(tmp_path)
    ws.cmd_init(["flask"])

    app_py = tmp_path / "app.py"
    env_ex = tmp_path / ".env.example"

    assert app_py.exists(), "app.py not created by flask template"
    assert "Flask" in app_py.read_text(encoding="utf-8"), "app.py does not reference Flask"
    assert env_ex.exists(), ".env.example not created by flask template"
    assert "PORT" in env_ex.read_text(encoding="utf-8"), ".env.example missing PORT"

    out = capsys.readouterr().out
    assert "created" in out.lower() or "skip" in out.lower()


# ---------------------------------------------------------------------------
# /init express
# ---------------------------------------------------------------------------

def test_init_express(tmp_path, capsys):
    """/init express creates index.js and package.json."""
    ws, _ = _make_ws(tmp_path)
    ws.cmd_init(["express"])

    index_js = tmp_path / "index.js"
    pkg_json = tmp_path / "package.json"

    assert index_js.exists(), "index.js not created by express template"
    assert "express" in index_js.read_text(encoding="utf-8").lower()
    assert pkg_json.exists(), "package.json not created by express template"
    assert "express" in pkg_json.read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------------------
# /init nextjs
# ---------------------------------------------------------------------------

def test_init_nextjs(tmp_path, capsys):
    """/init nextjs creates pages/index.jsx."""
    ws, _ = _make_ws(tmp_path)
    ws.cmd_init(["nextjs"])

    page = tmp_path / "pages" / "index.jsx"
    assert page.exists(), "pages/index.jsx not created by nextjs template"
    content = page.read_text(encoding="utf-8")
    assert "export default" in content, "pages/index.jsx missing default export"


# ---------------------------------------------------------------------------
# /init vue
# ---------------------------------------------------------------------------

def test_init_vue(tmp_path, capsys):
    """/init vue creates src/App.vue."""
    ws, _ = _make_ws(tmp_path)
    ws.cmd_init(["vue"])

    app_vue = tmp_path / "src" / "App.vue"
    assert app_vue.exists(), "src/App.vue not created by vue template"
    content = app_vue.read_text(encoding="utf-8")
    assert "<template>" in content, "App.vue missing <template>"
    assert "<script" in content, "App.vue missing <script>"


# ---------------------------------------------------------------------------
# /init cli-tool
# ---------------------------------------------------------------------------

def test_init_cli_tool(tmp_path, capsys):
    """/init cli-tool creates src/cli/main.py with a click CLI."""
    ws, _ = _make_ws(tmp_path)
    ws.cmd_init(["cli-tool"])

    main_py = tmp_path / "src" / "cli" / "main.py"
    assert main_py.exists(), "src/cli/main.py not created by cli-tool template"
    content = main_py.read_text(encoding="utf-8")
    assert "click" in content, "src/cli/main.py does not use click"
    assert "def cli" in content or "@click" in content


# ---------------------------------------------------------------------------
# /init library (name substitution)
# ---------------------------------------------------------------------------

def test_init_library(tmp_path, capsys):
    """/init library mylib creates src/mylib/__init__.py with name substituted."""
    ws, _ = _make_ws(tmp_path)
    # Pass "mylib" as the project name argument
    ws.cmd_init(["library", "mylib"])

    init_py = tmp_path / "src" / "mylib" / "__init__.py"
    assert init_py.exists(), "src/mylib/__init__.py not created by library template"
    content = init_py.read_text(encoding="utf-8")
    assert "__version__" in content, "__init__.py missing __version__"

    # core.py should also have 'mylib' substituted in
    core_py = tmp_path / "src" / "mylib" / "core.py"
    assert core_py.exists(), "src/mylib/core.py not created"
    core_content = core_py.read_text(encoding="utf-8")
    # {name} substituted
    assert "mylib" in core_content, "core.py does not contain 'mylib'"


# ---------------------------------------------------------------------------
# /scaffold --dry-run
# ---------------------------------------------------------------------------

def test_scaffold_dry_run(tmp_path, capsys):
    """--dry-run prints [dry-run] message and writes no files."""
    ws, _ = _make_ws(tmp_path)

    # Patch LLM to ensure it's never called
    with patch("codex.app.llm_client.get_llm_client") as mock_llm:
        ws.cmd_scaffold(["route", "users", "--dry-run"])

    mock_llm.assert_not_called()

    out = capsys.readouterr().out
    assert "[dry-run]" in out, f"Expected [dry-run] in output, got: {out!r}"

    # No files should be written
    written = list(tmp_path.rglob("*"))
    written_files = [p for p in written if p.is_file()]
    assert not written_files, f"--dry-run wrote files: {written_files}"


# ---------------------------------------------------------------------------
# /scaffold pre-commit
# ---------------------------------------------------------------------------

def test_scaffold_precommit(tmp_path, capsys):
    """/scaffold pre-commit writes .pre-commit-config.yaml."""
    ws, _ = _make_ws(tmp_path)
    ws.cmd_scaffold(["pre-commit"])

    cfg_yaml = tmp_path / ".pre-commit-config.yaml"
    assert cfg_yaml.exists(), ".pre-commit-config.yaml not created"
    content = cfg_yaml.read_text(encoding="utf-8")
    assert "ruff" in content, ".pre-commit-config.yaml missing ruff hook"
    assert "pre-commit-hooks" in content, ".pre-commit-config.yaml missing pre-commit-hooks"
    assert "trailing-whitespace" in content

    out = capsys.readouterr().out
    assert "created" in out.lower() or ".pre-commit" in out.lower()


# ---------------------------------------------------------------------------
# /scaffold compose
# ---------------------------------------------------------------------------

def test_scaffold_compose(tmp_path, capsys):
    """/scaffold compose writes docker-compose.yml with 'postgres' in it."""
    ws, _ = _make_ws(tmp_path)
    ws.cmd_scaffold(["compose"])

    compose = tmp_path / "docker-compose.yml"
    assert compose.exists(), "docker-compose.yml not created"
    content = compose.read_text(encoding="utf-8")
    assert "postgres" in content, "docker-compose.yml missing postgres service"
    assert "pgdata" in content, "docker-compose.yml missing pgdata volume"
    assert "healthcheck" in content, "docker-compose.yml missing healthcheck"


# ---------------------------------------------------------------------------
# /template list shows all types
# ---------------------------------------------------------------------------

def test_template_list_shows_all(capsys):
    """cmd_template_list() output contains all 15+ init types."""
    from cli.commands.workspace_scaffold import TemplateListCommand, INIT_TEMPLATE_DESCRIPTIONS

    TemplateListCommand().cmd_template_list()
    out = capsys.readouterr().out

    missing = []
    for name in INIT_TEMPLATE_DESCRIPTIONS:
        if name not in out:
            missing.append(name)

    assert not missing, f"Template list output missing types: {missing}"

    # Must show at least 15 types
    count = len(INIT_TEMPLATE_DESCRIPTIONS)
    assert count >= 15, f"Expected >=15 init types, found {count}"

    # Scaffold types also shown
    assert "pre-commit" in out, "pre-commit scaffold type missing from /template list"
    assert "compose" in out, "compose scaffold type missing from /template list"


# ---------------------------------------------------------------------------
# /upgrade detects flask project
# ---------------------------------------------------------------------------

def test_upgrade_detects_flask(tmp_path, capsys):
    """Flask project is correctly detected and upgrade lists missing template files."""
    from cli.commands.workspace_scaffold import UpgradeCommand
    from app.core.config import AppConfig

    cfg = AppConfig()
    cfg.working_folder = str(tmp_path)

    # Write just a requirements.txt referencing flask — minimal flask project
    (tmp_path / "requirements.txt").write_text("flask>=3.0\npython-dotenv\n", encoding="utf-8")

    # Patch input() to always say "n" (decline creating files) to keep tmp_path clean
    with patch("builtins.input", return_value="n"):
        UpgradeCommand(cfg).cmd_upgrade([])

    out = capsys.readouterr().out

    # Should detect "flask" and mention missing files
    assert "flask" in out.lower(), f"Expected 'flask' in upgrade output, got: {out!r}"
    # Should list at least one missing file
    assert "+" in out or "missing" in out.lower() or "app.py" in out.lower(), (
        f"Expected missing-file listing in output: {out!r}"
    )


# ---------------------------------------------------------------------------
# /init svelte (bonus coverage)
# ---------------------------------------------------------------------------

def test_init_svelte(tmp_path, capsys):
    """/init svelte creates src/routes/+page.svelte."""
    ws, _ = _make_ws(tmp_path)
    ws.cmd_init(["svelte"])

    page = tmp_path / "src" / "routes" / "+page.svelte"
    assert page.exists(), "src/routes/+page.svelte not created by svelte template"
    content = page.read_text(encoding="utf-8")
    assert "<main>" in content or "<script>" in content


# ---------------------------------------------------------------------------
# /init electron (bonus coverage)
# ---------------------------------------------------------------------------

def test_init_electron(tmp_path, capsys):
    """/init electron creates main.js with BrowserWindow."""
    ws, _ = _make_ws(tmp_path)
    ws.cmd_init(["electron"])

    main_js = tmp_path / "main.js"
    assert main_js.exists(), "main.js not created by electron template"
    content = main_js.read_text(encoding="utf-8")
    assert "BrowserWindow" in content, "main.js missing BrowserWindow"
    assert "app.whenReady" in content

    preload = tmp_path / "preload.js"
    assert preload.exists(), "preload.js not created by electron template"
    assert "contextBridge" in preload.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# /scaffold env — generates .env.example from .env
# ---------------------------------------------------------------------------

def test_scaffold_env_from_dotenv(tmp_path, capsys):
    """/scaffold env reads .env and generates .env.example with blank values."""
    from cli.commands.workspace_scaffold import ScaffoldExtensions
    from app.core.config import AppConfig

    cfg = AppConfig()
    cfg.working_folder = str(tmp_path)

    (tmp_path / ".env").write_text(
        "PORT=5000\nSECRET_KEY=supersecret\nDATABASE_URL=postgresql://localhost/db\n",
        encoding="utf-8",
    )

    ScaffoldExtensions(cfg).cmd_scaffold_env()

    example = tmp_path / ".env.example"
    assert example.exists(), ".env.example not created"
    content = example.read_text(encoding="utf-8")

    assert "PORT=" in content
    assert "SECRET_KEY=" in content
    assert "DATABASE_URL=" in content
    # Values must be blank
    for line in content.splitlines():
        if "=" in line:
            _key, _, val = line.partition("=")
            assert val == "", f"Expected blank value for {_key!r}, got {val!r}"


# ---------------------------------------------------------------------------
# /scaffold env — detects stack when no .env present
# ---------------------------------------------------------------------------

def test_scaffold_env_detect_stack(tmp_path, capsys):
    """/scaffold env with no .env detects flask stack and emits defaults."""
    from cli.commands.workspace_scaffold import ScaffoldExtensions
    from app.core.config import AppConfig

    cfg = AppConfig()
    cfg.working_folder = str(tmp_path)

    (tmp_path / "requirements.txt").write_text("flask>=3.0\n", encoding="utf-8")
    # No .env file

    ScaffoldExtensions(cfg).cmd_scaffold_env()

    example = tmp_path / ".env.example"
    assert example.exists(), ".env.example not created for detected flask stack"
    content = example.read_text(encoding="utf-8")
    assert "PORT" in content or "SECRET_KEY" in content
