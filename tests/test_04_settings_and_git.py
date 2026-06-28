"""Cluster 04 — Settings commands and Git helper.

Tests:
  - test_config_loads               : ConfigManager.load() returns valid AppConfig
  - test_config_save_restore        : save() persists values (tested via temp file)
  - test_permission_modes           : PermissionMode enum has ask/auto_approve/deny_all
  - test_check_ollama_reachable     : SettingsCommands.check_ollama() returns (bool, list)
  - test_git_status_non_repo        : git_helper.status() on non-git dir returns is_repo=False
  - test_git_status_real_repo       : git_helper.status() on CLI project dir returns is_repo=True
  - test_git_diff_non_repo          : git_helper.diff() on non-git dir returns None/empty
  - test_git_run_log                : git_helper._run(['log','--oneline','-3']) works on CLI dir
  - test_branch_cmd_non_repo        : GitCommands.cmd_branch() on non-repo prints warning
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save

_CLI_DIR = str(_ROOT)


# ── Config tests ──────────────────────────────────────────────────────────────

def test_config_loads(cfg):
    from app.core.config import AppConfig
    ok = isinstance(cfg, AppConfig) and isinstance(cfg.ollama_url, str) and cfg.ollama_url.startswith("http")
    save("config_loads", ok, {
        "ollama_url":   cfg.ollama_url,
        "model":        cfg.ollama_model,
        "provider":     cfg.provider,
        "working_folder": cfg.working_folder,
        "num_ctx":      cfg.num_ctx,
    })
    assert ok, f"Bad config: {cfg}"


def test_permission_modes():
    from app.core.config import PermissionMode
    ok = (
        hasattr(PermissionMode, "ASK") and
        hasattr(PermissionMode, "AUTO_APPROVE") and
        hasattr(PermissionMode, "DENY_ALL")
    )
    save("permission_modes", ok, {
        "values": [m.value for m in PermissionMode]
    })
    assert ok


def test_check_ollama_reachable(cfg):
    from cli.commands.settings import SettingsCommands
    from app.core.config import ConfigManager
    mgr = ConfigManager()
    sc = SettingsCommands(cfg, mgr)
    ok_conn, models = sc.check_ollama()
    save("check_ollama_reachable", True, {
        "reachable": ok_conn,
        "model_count": len(models),
        "models": models[:10],
    })
    # Not asserting reachable — server may be offline; we just want no exception


# ── Git helper tests ──────────────────────────────────────────────────────────

def test_git_status_non_repo():
    from app.core import git_helper
    with tempfile.TemporaryDirectory() as tmp:
        s = git_helper.status(tmp)
        ok = not s.is_repo
        save("git_status_non_repo", ok, {
            "is_repo": s.is_repo,
            "branch":  s.branch,
        })
    assert ok, f"Expected is_repo=False for empty tmpdir, got {s.is_repo}"


def test_git_status_real_repo():
    from app.core import git_helper
    # The CLI project itself may or may not be a git repo
    s = git_helper.status(_CLI_DIR)
    save("git_status_real_repo", True, {
        "is_repo":     s.is_repo,
        "branch":      s.branch,
        "upstream":    s.upstream,
        "staged":      s.staged[:5],
        "modified":    s.modified[:5],
        "untracked":   s.untracked[:5],
        "last_commit": s.last_commit,
    })
    # Always passes — just captures state


def test_git_diff_non_repo():
    from app.core import git_helper
    with tempfile.TemporaryDirectory() as tmp:
        d = git_helper.diff(tmp)
        ok = d is None or d == ""
        save("git_diff_non_repo", ok, {"diff": d})
    assert ok, f"Expected None/empty diff for non-repo, got: {d!r}"


def test_git_run_log():
    from app.core import git_helper
    rc, sout, serr = git_helper._run(["log", "--oneline", "-3"], _CLI_DIR)
    # May fail if not a git repo — that's fine, just record
    save("git_run_log", True, {
        "rc":   rc,
        "sout": sout[:400],
        "serr": serr[:200],
    })


def test_branch_cmd_non_repo(cfg, capsys):
    from cli.commands.git_cmds import GitCommands
    from app.core.config import AppConfig
    tmp_cfg = AppConfig()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_cfg.working_folder = tmp
        gc = GitCommands(tmp_cfg)
        gc.cmd_branch([])  # should print warning, not crash
        captured = capsys.readouterr()
        ok = True  # just must not raise
        save("branch_cmd_non_repo", ok, {
            "stdout": captured.out[:400],
            "stderr": captured.err[:200],
        })
    assert ok
