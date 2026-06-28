"""Tests for cli.debug_runner and cli.commands.debug_cmds.
Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── debug_runner unit tests ──────────────────────────────────────────────────

class TestFindPython:

    def test_falls_back_to_sys_executable(self, tmp_path):
        from cli.debug_runner import find_python
        result = find_python(str(tmp_path))
        assert result == sys.executable

    def test_detects_venv_scripts(self, tmp_path):
        from cli.debug_runner import find_python
        scripts = tmp_path / ".venv" / "Scripts"
        scripts.mkdir(parents=True)
        exe = scripts / "python.exe"
        exe.write_text("")
        result = find_python(str(tmp_path))
        assert result == str(exe)

    def test_detects_venv_bin(self, tmp_path):
        from cli.debug_runner import find_python
        if sys.platform == "win32":
            return  # Scripts takes priority on Windows
        bin_dir = tmp_path / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        exe = bin_dir / "python"
        exe.write_text("")
        result = find_python(str(tmp_path))
        assert result == str(exe)


class TestVenvEnv:

    def test_returns_dict_with_virtual_env(self, tmp_path):
        from cli.debug_runner import venv_env
        env = venv_env(str(tmp_path), sys.executable)
        assert "VIRTUAL_ENV" in env
        assert "PATH" in env

    def test_removes_pythonhome(self, tmp_path):
        import os
        with patch.dict(os.environ, {"PYTHONHOME": "/bad/path"}):
            from cli.debug_runner import venv_env
            env = venv_env(str(tmp_path), sys.executable)
        assert "PYTHONHOME" not in env


class TestErrorReport:

    def test_has_error_nonzero_exit(self):
        from cli.debug_runner import ErrorReport
        r = ErrorReport(exit_code=1, stderr_text="", error_lines=[], log_path="", session_id="x", elapsed_s=0.1)
        assert r.has_error is True

    def test_has_error_clean(self):
        from cli.debug_runner import ErrorReport
        r = ErrorReport(exit_code=0, stderr_text="", error_lines=[], log_path="", session_id="x", elapsed_s=0.1)
        assert r.has_error is False

    def test_summary_clean(self):
        from cli.debug_runner import ErrorReport
        r = ErrorReport(exit_code=0, stderr_text="", error_lines=[], log_path="/tmp/x.log", session_id="x", elapsed_s=1.5)
        assert "cleanly" in r.summary()

    def test_summary_with_errors(self):
        from cli.debug_runner import ErrorReport
        r = ErrorReport(
            exit_code=1, stderr_text="bad", error_lines=["TypeError: foo"],
            log_path="/tmp/x.log", session_id="x", elapsed_s=1.0,
        )
        s = r.summary()
        assert "1" in s and ("exit" in s.lower() or "code" in s.lower())
        assert "TypeError" in s


class TestIsErrorLine:

    def test_traceback(self):
        from cli.debug_runner import _is_error_line
        assert _is_error_line("Traceback (most recent call last):")

    def test_error_colon(self):
        from cli.debug_runner import _is_error_line
        assert _is_error_line("ValueError: invalid literal")

    def test_normal_line(self):
        from cli.debug_runner import _is_error_line
        assert not _is_error_line("Hello, World!")


class TestRunInteractive:

    def test_runs_simple_script(self, tmp_path):
        from cli.debug_runner import run_interactive
        script = tmp_path / "hello.py"
        script.write_text('print("hello debug")\n')
        collected: list[tuple] = []
        report = run_interactive(
            script_args=[str(script)],
            workspace=str(tmp_path),
            session_id="test_hello",
            on_output=lambda s, l: collected.append((s, l)),
        )
        assert report.exit_code == 0
        assert any("hello debug" in l for s, l in collected if s == "stdout")

    def test_captures_stderr_on_error(self, tmp_path):
        from cli.debug_runner import run_interactive
        script = tmp_path / "err.py"
        script.write_text('raise ValueError("boom")\n')
        report = run_interactive(
            script_args=[str(script)],
            workspace=str(tmp_path),
            session_id="test_err",
        )
        assert report.exit_code != 0
        assert report.has_error
        assert any("ValueError" in ln for ln in report.error_lines)

    def test_log_file_created(self, tmp_path):
        from cli.debug_runner import _LOG_DIR, run_interactive
        script = tmp_path / "x.py"
        script.write_text("pass\n")
        run_interactive(
            script_args=[str(script)],
            workspace=str(tmp_path),
            session_id="test_log_created",
        )
        assert (_LOG_DIR / "test_log_created.log").exists()

    def test_json_session_written(self, tmp_path):
        from cli.debug_runner import _LOG_DIR, run_interactive
        script = tmp_path / "j.py"
        script.write_text('print("json")\n')
        run_interactive(
            script_args=[str(script)],
            workspace=str(tmp_path),
            session_id="test_json_session",
        )
        jp = _LOG_DIR / "test_json_session.json"
        assert jp.exists()
        data = json.loads(jp.read_text())
        assert data["exit_code"] == 0
        assert any(l["text"] == "json" for l in data["lines"] if l["stream"] == "stdout")

    def test_missing_script_returns_error(self, tmp_path):
        from cli.debug_runner import run_interactive
        report = run_interactive(
            script_args=["nonexistent_script_xyz.py"],
            workspace=str(tmp_path),
            session_id="test_missing",
        )
        assert report.exit_code != 0

    def test_exit_code_captured(self, tmp_path):
        from cli.debug_runner import run_interactive
        script = tmp_path / "code.py"
        script.write_text("import sys; sys.exit(42)\n")
        report = run_interactive(
            script_args=[str(script)],
            workspace=str(tmp_path),
            session_id="test_exitcode",
        )
        assert report.exit_code == 42


class TestListSessions:

    def test_empty_when_no_logs(self, tmp_path):
        from cli.debug_runner import _LOG_DIR, list_sessions
        with patch("cli.debug_runner._LOG_DIR", tmp_path):
            result = list_sessions()
        assert result == []

    def test_returns_sorted_newest_first(self, tmp_path):
        from cli.debug_runner import list_sessions
        with patch("cli.debug_runner._LOG_DIR", tmp_path):
            (tmp_path / "debug_20240101_000000.log").write_text("a")
            (tmp_path / "debug_20240102_000000.log").write_text("b")
            logs = list_sessions()
        assert logs[0].name > logs[1].name


# ── DebugCommands unit tests ─────────────────────────────────────────────────

class TestDebugCommands:

    def _cmds(self, tmp_path):
        from cli.commands.debug_cmds import DebugCommands
        cfg = MagicMock()
        cfg.working_folder = str(tmp_path)
        cfg.ollama_url = "http://localhost:11434"
        cfg.ollama_model = "codellama:7b"
        cfg.provider = "ollama"
        return DebugCommands(cfg)

    def test_no_args_shows_usage(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        cmds.cmd_debug([])
        out = capsys.readouterr().out
        assert "/debug" in out

    def test_logs_subcommand_empty(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        with patch("cli.debug_runner._LOG_DIR", tmp_path / "nodebug"):
            cmds.cmd_debug(["logs"])
        out = capsys.readouterr().out
        assert "no debug" in out.lower() or "session" in out.lower()

    def test_log_subcommand_no_sessions(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        with patch("cli.debug_runner._LOG_DIR", tmp_path / "nodebug"):
            cmds.cmd_debug(["log"])
        out = capsys.readouterr().out
        assert "no debug" in out.lower() or "session" in out.lower() or "found" in out.lower()

    def test_run_simple_script(self, tmp_path, capsys):
        script = tmp_path / "hi.py"
        script.write_text('print("debug output")\n')
        cmds = self._cmds(tmp_path)
        cmds.cmd_debug([str(script)])
        out = capsys.readouterr().out
        assert "debug output" in out or "debug" in out.lower()

    def test_analyze_no_session(self, tmp_path, capsys):
        cmds = self._cmds(tmp_path)
        with patch("cli.debug_runner._LOG_DIR", tmp_path / "nodebug"):
            cmds.cmd_debug(["analyze"])
        out = capsys.readouterr().out
        assert "no debug" in out.lower() or "session" in out.lower() or "run" in out.lower()
