"""Cluster 06 — Workspace commands and project rules.

Tests:
  - test_cmd_add_no_path       : /add with no args prints pinned list (empty)
  - test_cmd_add_real_path     : /add <real_file> pins context block
  - test_cmd_drop_removes      : /drop removes matching pinned entry
  - test_cmd_init_python       : /init python creates expected files in tmp dir
  - test_cmd_init_node         : /init node creates package.json in tmp dir
  - test_cmd_init_unknown      : /init badtemplate prints error, no crash
  - test_project_rules_empty   : project_rules.load() on dir without .ilx_rules returns is_empty
  - test_project_rules_reads   : project_rules.load() reads .ilx_rules.md content
  - test_build_helper_version  : bump_version() increments patch in a temp version file
  - test_diag_export           : cmd_diag() exports a ZIP to temp location
"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


@pytest.fixture(scope="module")
def ctx(cfg):
    from cli.context import ContextManager
    return ContextManager(cfg)


# ── /add and /drop ────────────────────────────────────────────────────────────

def test_cmd_add_no_path(cfg, ctx, capsys):
    from cli.commands.workspace_cmds import WorkspaceCommands
    ws = WorkspaceCommands(cfg, ctx)
    pinned: list[dict] = []
    ws.cmd_add("", pinned)
    captured = capsys.readouterr()
    ok = len(pinned) == 0 and ("No pinned" in captured.out or "pinned" in captured.out.lower())
    save("cmd_add_no_path", ok, {"stdout": captured.out[:300], "pinned_count": len(pinned)})
    assert ok


def test_cmd_add_real_path(cfg, ctx):
    from cli.commands.workspace_cmds import WorkspaceCommands
    ws = WorkspaceCommands(cfg, ctx)
    pinned: list[dict] = []
    real_file = str(Path(__file__).parent / "conftest.py")
    ws.cmd_add(real_file, pinned)
    ok = len(pinned) == 1 and "conftest" in pinned[0]["content"].lower()
    save("cmd_add_real_path", ok, {
        "file":          real_file,
        "pinned_count":  len(pinned),
        "content_snippet": pinned[0]["content"][:200] if pinned else "",
    })
    assert ok, f"Expected 1 pinned entry with conftest content. pinned={len(pinned)}"


def test_cmd_drop_removes(cfg, ctx):
    from cli.commands.workspace_cmds import WorkspaceCommands
    ws = WorkspaceCommands(cfg, ctx)
    pinned = [
        {"role": "user", "content": "[Pinned context: foo/bar.py]\nsome content"},
        {"role": "user", "content": "[Pinned context: baz/qux.py]\nother content"},
    ]
    ws.cmd_drop(["bar"], pinned)
    ok = len(pinned) == 1 and "baz" in pinned[0]["content"]
    save("cmd_drop_removes", ok, {
        "remaining_count": len(pinned),
        "remaining_content": pinned[0]["content"][:100] if pinned else "",
    })
    assert ok, f"Expected 1 remaining entry. Got {len(pinned)}: {pinned}"


# ── /init ─────────────────────────────────────────────────────────────────────

def test_cmd_init_python(cfg, ctx):
    from cli.commands.workspace_cmds import WorkspaceCommands
    from app.core.config import AppConfig
    with tempfile.TemporaryDirectory() as tmp:
        tmp_cfg = AppConfig()
        tmp_cfg.working_folder = tmp
        ws = WorkspaceCommands(tmp_cfg, ctx)
        ws.cmd_init(["python"])
        expected = [".ilx_rules.md", ".gitignore", "pyproject.toml", "src/__init__.py", "tests/__init__.py"]
        missing = [f for f in expected if not (Path(tmp) / f).exists()]
        ok = len(missing) == 0
        save("cmd_init_python", ok, {
            "workspace": tmp,
            "missing":   missing,
            "created":   [str(p.relative_to(tmp)) for p in Path(tmp).rglob("*") if p.is_file()],
        })
    assert ok, f"Missing files after /init python: {missing}"


def test_cmd_init_node(cfg, ctx):
    from cli.commands.workspace_cmds import WorkspaceCommands
    from app.core.config import AppConfig
    with tempfile.TemporaryDirectory() as tmp:
        tmp_cfg = AppConfig()
        tmp_cfg.working_folder = tmp
        ws = WorkspaceCommands(tmp_cfg, ctx)
        ws.cmd_init(["node"])
        pkg = Path(tmp) / "package.json"
        ok = pkg.exists() and "myproject" in pkg.read_text(encoding="utf-8")
        save("cmd_init_node", ok, {
            "package_json_exists": pkg.exists(),
            "content": pkg.read_text(encoding="utf-8")[:200] if pkg.exists() else "",
        })
    assert ok


def test_cmd_init_unknown(cfg, ctx, capsys):
    from cli.commands.workspace_cmds import WorkspaceCommands
    from app.core.config import AppConfig
    with tempfile.TemporaryDirectory() as tmp:
        tmp_cfg = AppConfig()
        tmp_cfg.working_folder = tmp
        ws = WorkspaceCommands(tmp_cfg, ctx)
        try:
            ws.cmd_init(["badtemplate"])
            ok = True
            error = None
        except Exception as exc:
            ok = False
            error = str(exc)
        captured = capsys.readouterr()
        save("cmd_init_unknown", ok, {
            "stdout": captured.out[:300],
            "error":  error,
        })
    assert ok, f"cmd_init unknown template raised: {error}"


# ── project_rules ─────────────────────────────────────────────────────────────

def test_project_rules_empty():
    from app.core import project_rules
    with tempfile.TemporaryDirectory() as tmp:
        r = project_rules.load(tmp)
        ok = r.is_empty
        save("project_rules_empty", ok, {"is_empty": r.is_empty, "text": r.text[:100]})
    assert ok, f"Expected is_empty=True for dir with no rules file. Got: {r.is_empty}"


def test_project_rules_reads():
    from app.core import project_rules
    with tempfile.TemporaryDirectory() as tmp:
        rules_file = Path(tmp) / ".ilx_rules.md"
        rules_file.write_text("# Rules\nAlways write tests.\n", encoding="utf-8")
        r = project_rules.load(tmp)
        ok = not r.is_empty and "write tests" in r.text.lower()
        save("project_rules_reads", ok, {
            "is_empty": r.is_empty,
            "text":     r.text[:300],
            "sources":  r.sources,
        })
    assert ok, f"Expected rules content. is_empty={r.is_empty} text={r.text[:100]}"


# ── build_helper ──────────────────────────────────────────────────────────────

def test_build_helper_version():
    from app.core import build_helper
    with tempfile.TemporaryDirectory() as tmp:
        # Create a fake version file
        ver_file = Path(tmp) / "app" / "version.py"
        ver_file.parent.mkdir(parents=True, exist_ok=True)
        ver_file.write_text('VERSION = "1.2.3"\n', encoding="utf-8")
        new_ver = build_helper.bump_version(tmp)
        ok = new_ver == "1.2.4"
        content = ver_file.read_text(encoding="utf-8")
        save("build_helper_version", ok, {
            "new_ver":  new_ver,
            "content":  content,
        })
    assert ok, f"Expected '1.2.4', got {new_ver!r}"


# ── /diag ─────────────────────────────────────────────────────────────────────

def test_diag_export(cfg, ctx):
    from cli.commands.workspace_cmds import WorkspaceCommands
    from app.core.diagnostics import export, default_export_filename
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / default_export_filename()
        try:
            result = export(out_path)
            ok = result.exists() and zipfile.is_zipfile(str(result))
            names = []
            if ok:
                with zipfile.ZipFile(str(result)) as zf:
                    names = zf.namelist()
            error = None
        except Exception as exc:
            ok = False
            names = []
            error = str(exc)
        save("diag_export", ok, {
            "zip_path": str(out_path),
            "zip_contents": names,
            "error": error,
        })
    assert ok, f"Diag export failed: {error}"
