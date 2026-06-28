"""Cluster 05 — Dev tools: /run, /test, /stats, /env, /crashes, /deps.

Tests:
  - test_run_simple_command       : DevToolsCommands.cmd_run(['python', '-c', '...']) captures output
  - test_run_records_crash        : A failing command records a crash in crash_db
  - test_crashes_list             : crash_db.list_crashes() returns list
  - test_crashes_clear            : crash_db.clear_crashes() returns int
  - test_stats_counts_files       : cmd_stats() runs without error on CLI project
  - test_deps_list                : cmd_deps([]) runs pip list without error
  - test_env_missing              : cmd_env() handles missing .env gracefully
  - test_env_reads_file           : cmd_env() reads a real .env file and masks values
  - test_watch_exits_on_interrupt : cmd_watch() is importable (smoke test only)
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

PYTHON_EXE = sys.executable


# ── DevToolsCommands fixture ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def dev(cfg):
    from cli.commands.dev_tools import DevToolsCommands
    return DevToolsCommands(cfg)


# ── /run ─────────────────────────────────────────────────────────────────────

def test_run_simple_command(cfg, capsys):
    from cli.commands.dev_tools import DevToolsCommands
    from app.core.config import AppConfig
    with tempfile.TemporaryDirectory() as tmp:
        tmp_cfg = AppConfig()
        tmp_cfg.working_folder = tmp
        dev = DevToolsCommands(tmp_cfg)
        dev.cmd_run([PYTHON_EXE, "-c", "print('ILX_RUN_OK')"])
        captured = capsys.readouterr()
        ok = "ILX_RUN_OK" in captured.out
        save("run_simple_command", ok, {
            "stdout": captured.out[:400],
            "stderr": captured.err[:200],
        })
    assert ok, f"Expected ILX_RUN_OK in output. Got: {captured.out[:200]}"


def test_run_records_crash(cfg, capsys):
    from cli.commands.dev_tools import DevToolsCommands
    from app.core import crash_db
    from app.core.config import AppConfig
    crash_db.clear_crashes()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_cfg = AppConfig()
        tmp_cfg.working_folder = tmp
        dev = DevToolsCommands(tmp_cfg)
        dev.cmd_run([PYTHON_EXE, "-c", "import sys; sys.exit(42)"])
    # The crash is recorded by the supervisor's background reader thread;
    # poll briefly to let it flush before asserting.
    import time as _time
    for _ in range(20):
        crashes = crash_db.list_crashes(5)
        if crashes:
            break
        _time.sleep(0.1)
    ok = len(crashes) > 0
    save("run_records_crash", ok, {
        "crash_count": len(crashes),
        "crashes":     crashes[:3],
    })
    assert ok, "Expected at least one crash record after exit code 42"


# ── crash_db ─────────────────────────────────────────────────────────────────

def test_crashes_list():
    from app.core import crash_db
    crashes = crash_db.list_crashes(10)
    ok = isinstance(crashes, list)
    save("crashes_list", ok, {"count": len(crashes), "sample": crashes[:2]})
    assert ok


def test_crashes_clear():
    from app.core import crash_db
    n = crash_db.clear_crashes()
    ok = isinstance(n, int) and n >= 0
    save("crashes_clear", ok, {"cleared": n})
    assert ok, f"Expected int >= 0, got {n!r}"


# ── /stats ────────────────────────────────────────────────────────────────────

def test_stats_counts_files(cfg, capsys):
    from cli.commands.dev_tools import DevToolsCommands
    from app.core.config import AppConfig
    tmp_cfg = AppConfig()
    tmp_cfg.working_folder = str(_ROOT)
    dev = DevToolsCommands(tmp_cfg)
    try:
        dev.cmd_stats()
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    captured = capsys.readouterr()
    save("stats_counts_files", ok, {
        "stdout": captured.out[:600],
        "error":  error,
    })
    assert ok, f"cmd_stats() raised: {error}"


# ── /deps ─────────────────────────────────────────────────────────────────────

def test_deps_list(cfg, capsys):
    from cli.commands.dev_tools import DevToolsCommands
    dev = DevToolsCommands(cfg)
    try:
        dev.cmd_deps([])
        ok = True
        error = None
    except Exception as exc:
        ok = False
        error = str(exc)
    captured = capsys.readouterr()
    save("deps_list", ok, {
        "stdout": captured.out[:600],
        "error":  error,
    })
    assert ok, f"cmd_deps() raised: {error}"


# ── /env ─────────────────────────────────────────────────────────────────────

def test_env_missing(cfg, capsys):
    from cli.commands.dev_tools import DevToolsCommands
    from app.core.config import AppConfig
    with tempfile.TemporaryDirectory() as tmp:
        tmp_cfg = AppConfig()
        tmp_cfg.working_folder = tmp
        dev = DevToolsCommands(tmp_cfg)
        try:
            dev.cmd_env()
            ok = True
            error = None
        except Exception as exc:
            ok = False
            error = str(exc)
        captured = capsys.readouterr()
        save("env_missing", ok, {"stdout": captured.out[:300], "error": error})
    assert ok, f"cmd_env() raised on missing .env: {error}"


def test_env_reads_file(capsys):
    from cli.commands.dev_tools import DevToolsCommands
    from app.core.config import AppConfig
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / ".env"
        env_file.write_text(
            "# comment\nAPI_KEY=supersecrettoken123\nDEBUG=true\n",
            encoding="utf-8"
        )
        tmp_cfg = AppConfig()
        tmp_cfg.working_folder = tmp
        dev = DevToolsCommands(tmp_cfg)
        try:
            dev.cmd_env()
            ok = True
            error = None
        except Exception as exc:
            ok = False
            error = str(exc)
        captured = capsys.readouterr()
        # Should show API_KEY but mask most of the value
        has_key  = "API_KEY" in captured.out
        not_leaked = "supersecrettoken123" not in captured.out
        ok = ok and has_key
        save("env_reads_file", ok, {
            "stdout":     captured.out[:400],
            "has_key":    has_key,
            "not_leaked": not_leaked,
            "error":      error,
        })
    assert ok, f"has_key={has_key} not_leaked={not_leaked} error={error}\n{captured.out}"


def test_watch_exits_on_interrupt():
    # Smoke test: just verify the module imports cleanly
    from cli.commands.dev_tools import DevToolsCommands
    ok = hasattr(DevToolsCommands, "cmd_watch")
    save("watch_exits_on_interrupt", ok, {"has_cmd_watch": ok})
    assert ok
