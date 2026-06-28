"""Tests for codex.app.controller (CodingAgent) and codex.app.runner (CommandRunner)
— Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch, MagicMock
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Shared context manager to patch all heavy CodingAgent collaborators
# ---------------------------------------------------------------------------

@contextmanager
def _agent_patches(tmp_path: Path, llm_client, run_id: str = "run-001"):
    """Patch every collaborator CodingAgent constructs inside run()."""
    with (
        patch("codex.app.controller.AppPaths") as mock_paths_cls,
        patch("codex.app.controller.WorkspaceManager") as mock_ws_cls,
        patch("codex.app.controller.CommandRunner"),
        patch("codex.app.controller.AgentLogger"),
        patch("codex.app.controller.ProjectChunker") as mock_chunker_cls,
        patch("codex.app.controller.PromptBuilder") as mock_pb_cls,
        patch("codex.app.controller.generate_run_id", return_value=run_id),
        patch("codex.app.controller._project_rules", None),
        patch("codex.app.controller._hooks", None),
        patch("codex.app.controller._git_helper", None),
    ):
        mp = MagicMock()
        mp.workspace = tmp_path
        mp.project_index = tmp_path / ".project_index"
        mp.logs = tmp_path / "logs"
        mp.prompts = tmp_path / "prompts"
        mock_paths_cls.return_value = mp

        mc = MagicMock()
        mc.get_file_tree.return_value = ""
        mc.get_file_contents.return_value = ""
        mc.find_chunk_for_error.return_value = ""
        mock_chunker_cls.return_value = mc

        mpb = MagicMock()
        mpb.build_initial.return_value = "prompt"
        mpb.build_repair.return_value = "repair"
        mock_pb_cls.return_value = mpb

        mws = MagicMock()
        mws.read_file.return_value = ""
        mock_ws_cls.return_value = mws

        yield


def _good_response() -> str:
    return json.dumps({
        "summary": "done",
        "files": [{"path": "out.py", "action": "replace", "content": "x = 1\n"}],
        "command_to_run": "",
    })


def _make_agent(llm_client, **kwargs):
    from codex.app.controller import CodingAgent
    return CodingAgent(llm_client=llm_client, **kwargs)


# ---------------------------------------------------------------------------
# CodingAgent tests
# ---------------------------------------------------------------------------

class TestCodingAgent:

    def test_instantiation_stores_client_and_defaults(self) -> None:
        """CodingAgent stores the llm_client and applies sensible defaults."""
        mock_llm = MagicMock()
        agent = _make_agent(mock_llm, max_attempts=3)
        assert agent.llm_client is mock_llm
        assert agent.max_attempts == 3
        assert agent.run_timeout == 30
        assert agent.auto_commit is False

    def test_run_returns_agent_result(self, tmp_path: Path) -> None:
        """run() always returns an AgentResult with a run_id."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _good_response()
        with _agent_patches(tmp_path, mock_llm):
            result = _make_agent(mock_llm, max_attempts=1).run("task", working_folder=str(tmp_path))
        from codex.app.controller import AgentResult
        assert isinstance(result, AgentResult)
        assert result.run_id == "run-001"

    def test_run_exhausts_max_attempts(self, tmp_path: Path) -> None:
        """run() exhausts max_attempts when llm always returns bad JSON."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "NOT JSON AT ALL"
        with _agent_patches(tmp_path, mock_llm):
            result = _make_agent(mock_llm, max_attempts=2).run("task", working_folder=str(tmp_path))
        from codex.app.controller import AgentResult
        assert isinstance(result, AgentResult)
        assert result.attempts <= 3

    def test_run_aborts_returns_agent_result(self, tmp_path: Path) -> None:
        """run() always returns AgentResult even on auth error."""
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("401 Unauthorized")
        with _agent_patches(tmp_path, mock_llm):
            result = _make_agent(mock_llm, max_attempts=2).run("task", working_folder=str(tmp_path))
        from codex.app.controller import AgentResult
        assert isinstance(result, AgentResult)
        assert result.success is False

    def test_emit_calls_on_status(self) -> None:
        """_emit() invokes the on_status callback with the message."""
        statuses: list[str] = []
        agent = _make_agent(MagicMock(), on_status=statuses.append)
        agent._emit("hello")
        assert "hello" in statuses

    def test_emit_output_calls_on_output(self) -> None:
        """_emit_output() invokes the on_output callback."""
        outputs: list[tuple] = []
        agent = _make_agent(MagicMock(), on_output=lambda t, v: outputs.append((t, v)))
        agent._emit_output("stdout", "hi")
        assert ("stdout", "hi") in outputs

    def test_emit_swallows_callback_exception(self) -> None:
        """_emit() swallows any exception raised by on_status."""
        agent = _make_agent(MagicMock(), on_status=lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
        agent._emit("test")  # must not propagate

    def test_maybe_commit_skipped_when_disabled(self) -> None:
        """_maybe_commit returns '' when auto_commit is False."""
        agent = _make_agent(MagicMock(), auto_commit=False)
        assert agent._maybe_commit("", ["a.py"], "summary") == ""

    def test_classify_exit_code_helpers(self) -> None:
        """_classify_exit_code handles timed_out flag and known/unknown codes."""
        from codex.app.controller import _classify_exit_code
        assert _classify_exit_code(0, timed_out=True) == "timed out"
        assert _classify_exit_code(1, timed_out=False) == "generic error"
        assert _classify_exit_code(999, timed_out=False) == ""


# ---------------------------------------------------------------------------
# CommandRunner tests
# ---------------------------------------------------------------------------

class TestCommandRunner:

    def test_init_stores_cwd(self, tmp_path: Path) -> None:
        from codex.app.runner import CommandRunner
        assert CommandRunner(tmp_path).cwd == tmp_path

    def test_empty_command_returns_error(self, tmp_path: Path) -> None:
        from codex.app.runner import CommandRunner
        result = CommandRunner(tmp_path).run("")
        assert result.exit_code == 1
        assert "Empty command" in result.stderr

    def test_disallowed_command_rejected(self, tmp_path: Path) -> None:
        from codex.app.runner import CommandRunner
        result = CommandRunner(tmp_path).run("curl http://example.com")
        assert result.exit_code == 1
        assert "not allowed" in result.stderr

    def test_python_inline_code_rejected(self, tmp_path: Path) -> None:
        from codex.app.runner import CommandRunner
        result = CommandRunner(tmp_path).run("python -c 'import os'")
        assert result.exit_code == 1
        assert "not allowed" in result.stderr

    def test_git_push_blocked_by_policy(self, tmp_path: Path) -> None:
        from codex.app.runner import CommandRunner
        result = CommandRunner(tmp_path).run("git push origin main")
        assert result.exit_code == 1
        assert "blocked" in result.stderr

    def test_on_line_callback_receives_stderr_on_rejection(self, tmp_path: Path) -> None:
        from codex.app.runner import CommandRunner
        collected: list[tuple] = []
        CommandRunner(tmp_path).run("rm -rf /", on_line=lambda t, v: collected.append((t, v)))
        assert any(t == "stderr" for t, _ in collected)
