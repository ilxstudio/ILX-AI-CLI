"""CLI integration tests -- end-to-end command verification in a virtual environment.

Each test exercises a CLI command handler directly (no LLM required) using:
- A temporary workspace (tmp_path fixture)
- Captured stdout (capsys)
- Mocked LLM client where an LLM call would occur
- Assertions on actual output content and return values

This suite is designed to catch regressions in command dispatch, output format,
and argument parsing across every major /command in the application.
"""
from __future__ import annotations

import json
import sys
import textwrap
import time
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path, **overrides):
    """Build a real AppConfig pointing at tmp_path as workspace."""
    from app.core.config import AppConfig, PermissionMode
    cfg = AppConfig()
    cfg.working_folder = str(tmp_path)
    cfg.provider = "ollama"
    cfg.ollama_url = "http://localhost:11434"
    cfg.ollama_model = "codellama:7b"
    cfg.autofix_max_iterations = overrides.get("autofix_max_iterations", 3)
    cfg.permission_mode = PermissionMode.AUTO_APPROVE
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _fake_llm(response: str = "ok") -> MagicMock:
    client = MagicMock()
    client.chat.return_value = response
    return client


def _capture(fn, *args, **kwargs):
    """Call fn(*args, **kwargs) and return (stdout_str, return_value)."""
    buf = StringIO()
    import builtins
    orig_print = builtins.print
    lines = []

    def _print(*a, **kw):
        end = kw.get("end", "\n")
        lines.append("".join(str(x) for x in a) + end)
        orig_print(*a, **kw)

    builtins.print = _print
    try:
        rv = fn(*args, **kwargs)
    finally:
        builtins.print = orig_print
    return "".join(lines), rv


# ===========================================================================
# /review command
# ===========================================================================

class TestReviewCmdIntegration:
    def test_review_help_output(self, tmp_path, capsys):
        from cli.commands.review_cmds import ReviewCommands
        cfg = _make_cfg(tmp_path)
        cmd = ReviewCommands(cfg)
        cmd.cmd_review([])
        out = capsys.readouterr().out
        assert "/review" in out
        assert "staged" in out
        assert "security" in out

    def test_review_staged_no_changes(self, tmp_path, capsys):
        from cli.commands.review_cmds import ReviewCommands
        from app.core.process_runner import ProcessResult
        cfg = _make_cfg(tmp_path)
        cmd = ReviewCommands(cfg)
        with patch("app.core.process_runner.run", return_value=ProcessResult(0, "", "", True)):
            cmd.cmd_review(["staged"])
        out = capsys.readouterr().out
        assert "No staged changes" in out or "No uncommitted" in out

    def test_review_files_nonexistent(self, tmp_path, capsys):
        from cli.commands.review_cmds import ReviewCommands
        cfg = _make_cfg(tmp_path)
        cmd = ReviewCommands(cfg)
        with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm("SUMMARY: None")):
            cmd.cmd_review([str(tmp_path / "does_not_exist.py")])
        out = capsys.readouterr().out
        assert "error" in out.lower() or "No readable" in out

    def test_review_existing_file(self, tmp_path, capsys):
        from cli.commands.review_cmds import ReviewCommands
        src = tmp_path / "sample.py"
        src.write_text("def foo(): pass\n", encoding="utf-8")
        cfg = _make_cfg(tmp_path)
        cmd = ReviewCommands(cfg)
        llm_resp = (
            "RISK:LOW  FILE:sample.py  LINE:1  CAT:maintainability  MSG:Missing docstring\n"
            "SUMMARY: Minor style issue."
        )
        with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm(llm_resp)):
            cmd.cmd_review([str(src)])
        out = capsys.readouterr().out
        assert "LOW" in out or "sample.py" in out or "maintainability" in out.lower()

    def test_review_security_subcommand(self, tmp_path, capsys):
        from cli.commands.review_cmds import ReviewCommands
        from app.core.process_runner import ProcessResult
        cfg = _make_cfg(tmp_path)
        cmd = ReviewCommands(cfg)
        diff = "diff --git a/x.py b/x.py\n+password = 'hunter2'\n"
        pr = ProcessResult(0, diff, "", True)
        with patch("app.core.process_runner.run", return_value=pr):
            with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm(
                "RISK:HIGH  FILE:x.py  LINE:1  CAT:security  MSG:Hardcoded password\nSUMMARY: Fix it."
            )):
                cmd.cmd_review(["security"])
        out = capsys.readouterr().out
        assert "Security" in out or "security" in out or "HIGH" in out

    def test_review_pr_missing_number(self, tmp_path, capsys):
        from cli.commands.review_cmds import ReviewCommands
        cfg = _make_cfg(tmp_path)
        cmd = ReviewCommands(cfg)
        cmd.cmd_review(["pr"])
        out = capsys.readouterr().out
        assert "Usage" in out or "usage" in out or "number" in out


# ===========================================================================
# /fix-tests command
# ===========================================================================

class TestFixTestsCmdIntegration:
    def test_fix_help(self, tmp_path, capsys):
        from cli.commands.fix_cmds import FixCommands
        cfg = _make_cfg(tmp_path)
        cmd = FixCommands(cfg)
        cmd.cmd_fix_tests(["--help"])
        out = capsys.readouterr().out
        assert "/fix-tests" in out
        assert "--max" in out

    def test_dry_run_shows_runner(self, tmp_path, capsys):
        from cli.commands.fix_cmds import FixCommands
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n", encoding="utf-8")
        cfg = _make_cfg(tmp_path)
        cmd = FixCommands(cfg)
        cmd.cmd_fix_tests(["--dry-run"])
        out = capsys.readouterr().out
        assert "dry run" in out.lower()
        assert "pytest" in out.lower() or "Runner" in out

    def test_max_arg_parsed(self, tmp_path, capsys):
        from cli.commands.fix_cmds import FixCommands
        from app.core.test_fix_loop import TestFixResult
        cfg = _make_cfg(tmp_path)
        cmd = FixCommands(cfg)
        mock_result = TestFixResult(final_pass=True, total_fixed=0)
        with patch("app.core.test_fix_loop.TestFixLoop.run", return_value=mock_result):
            with patch("app.core.process_runner.run"):
                cmd.cmd_fix_tests(["--max", "7"])
        out = capsys.readouterr().out
        assert "7" in out

    def test_only_arg_passed(self, tmp_path, capsys):
        from cli.commands.fix_cmds import FixCommands
        from app.core.test_fix_loop import TestFixResult
        cfg = _make_cfg(tmp_path)
        cmd = FixCommands(cfg)
        mock_result = TestFixResult(final_pass=True)
        with patch("app.core.test_fix_loop.TestFixLoop.run", return_value=mock_result) as mock_run:
            cmd.cmd_fix_tests(["--only", "test_auth"])
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("only") == "test_auth"

    def test_final_pass_output(self, tmp_path, capsys):
        from cli.commands.fix_cmds import FixCommands
        from app.core.test_fix_loop import TestFixResult
        cfg = _make_cfg(tmp_path)
        cmd = FixCommands(cfg)
        mock_result = TestFixResult(final_pass=True, total_fixed=3)
        with patch("app.core.test_fix_loop.TestFixLoop.run", return_value=mock_result):
            cmd.cmd_fix_tests([])
        out = capsys.readouterr().out
        assert "passing" in out.lower() or "ok" in out.lower()

    def test_still_failing_output(self, tmp_path, capsys):
        from cli.commands.fix_cmds import FixCommands
        from app.core.test_fix_loop import TestFixResult, TestFailure, FixAttempt
        cfg = _make_cfg(tmp_path)
        cmd = FixCommands(cfg)
        failure = TestFailure(test_id="tests/t.py::test_x", file="tests/t.py",
                              line=5, error="AssertionError", traceback="...")
        attempt = FixAttempt(attempt=1, failures_before=1, failures_after=1, patches_applied=0)
        mock_result = TestFixResult(
            final_pass=False,
            final_failures=[failure],
            attempts=[attempt],
        )
        with patch("app.core.test_fix_loop.TestFixLoop.run", return_value=mock_result):
            cmd.cmd_fix_tests([])
        out = capsys.readouterr().out
        assert "failing" in out.lower() or "still" in out.lower()


# ===========================================================================
# /index command
# ===========================================================================

class TestIndexCmdIntegration:
    def test_index_help(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        cmd.cmd_index(["help"])
        out = capsys.readouterr().out
        assert "/index" in out
        assert "build" in out
        assert "explain" in out

    def test_index_status_empty(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        # Mock retriever so no actual RAG init
        mock_stats = MagicMock()
        mock_stats.file_count = 0
        mock_retriever = MagicMock()
        mock_retriever.stats.return_value = mock_stats
        cmd._retriever = mock_retriever
        cmd.cmd_index(["status"])
        out = capsys.readouterr().out
        assert "empty" in out.lower() or "Index" in out

    def test_index_status_populated(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        mock_stats = MagicMock()
        mock_stats.file_count = 12
        mock_stats.chunk_count = 45
        mock_stats.symbol_count = 8
        mock_stats.db_size_kb = 128.4
        mock_stats.index_path = "/tmp/embeddings.db"
        mock_retriever = MagicMock()
        mock_retriever.stats.return_value = mock_stats
        cmd._retriever = mock_retriever
        cmd.cmd_index(["status"])
        out = capsys.readouterr().out
        assert "12" in out
        assert "45" in out

    def test_index_build_invalid_path(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        cmd.cmd_index(["build", "/nonexistent/path/xyz"])
        out = capsys.readouterr().out
        assert "Invalid" in out or "invalid" in out

    def test_index_build_counts_files(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        # Create some source files
        (tmp_path / "a.py").write_text("def foo(): pass\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("def bar(): pass\n", encoding="utf-8")
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        mock_retriever = MagicMock()
        mock_retriever.index_folder.return_value = 2
        cmd._retriever = mock_retriever
        cmd.cmd_index(["build"])
        out = capsys.readouterr().out
        assert "2" in out
        mock_retriever.index_folder.assert_called_once()

    def test_index_clear(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        mock_retriever = MagicMock()
        cmd._retriever = mock_retriever
        cmd.cmd_index(["clear"])
        out = capsys.readouterr().out
        assert "cleared" in out.lower() or "ok" in out.lower()
        mock_retriever.clear.assert_called_once()

    def test_index_explain_no_args(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        cmd.cmd_index(["explain"])
        out = capsys.readouterr().out
        assert "Usage" in out or "usage" in out

    def test_index_explain_with_question(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        from app.core.research_runner import ResearchResult
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        mock_result = ResearchResult(
            query="how does auth work",
            answer="## Answer\nAuth uses JWT tokens.\n\n## Files Referenced\n- auth.py",
            files_used=["auth.py"],
            chunks_used=3,
        )
        with patch("app.core.research_runner.ResearchRunner.query", return_value=mock_result):
            cmd.cmd_index(["explain", "how", "does", "auth", "work"])
        out = capsys.readouterr().out
        assert "JWT" in out or "Answer" in out or "auth.py" in out

    def test_index_explain_error(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        from app.core.research_runner import ResearchResult
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        mock_result = ResearchResult(
            query="what is foo",
            answer="",
            error="No indexed content found. Run /index build first.",
        )
        with patch("app.core.research_runner.ResearchRunner.query", return_value=mock_result):
            cmd.cmd_index(["explain", "what", "is", "foo"])
        out = capsys.readouterr().out
        assert "No indexed" in out or "error" in out.lower()

    def test_index_default_shows_status(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg(tmp_path)
        cmd = IndexCommands(cfg)
        mock_stats = MagicMock()
        mock_stats.file_count = 0
        mock_retriever = MagicMock()
        mock_retriever.stats.return_value = mock_stats
        cmd._retriever = mock_retriever
        cmd.cmd_index([])  # no sub → status
        out = capsys.readouterr().out
        assert "Index" in out or "index" in out


# ===========================================================================
# /plan command
# ===========================================================================

class TestPlanCmdIntegration:
    def _make_plan_session(self, tmp_path):
        from cli.plan_session import PlanSession
        cfg = _make_cfg(tmp_path)
        ctx = MagicMock()
        return PlanSession(cfg, ctx)

    def test_plan_help(self, tmp_path, capsys):
        ps = self._make_plan_session(tmp_path)
        ps.cmd_plan([], chat_history=[])
        out = capsys.readouterr().out
        assert "/plan" in out

    def test_plan_status_no_active(self, tmp_path, capsys):
        ps = self._make_plan_session(tmp_path)
        ps.cmd_plan(["status"], chat_history=[])
        out = capsys.readouterr().out
        assert "No active plan" in out

    def test_plan_cancel_nothing(self, tmp_path, capsys):
        ps = self._make_plan_session(tmp_path)
        ps.cmd_plan(["cancel"], chat_history=[])
        out = capsys.readouterr().out
        assert "cancel" in out.lower() or "No active" in out

    def test_plan_approve_no_plan(self, tmp_path, capsys):
        ps = self._make_plan_session(tmp_path)
        ps.cmd_plan(["approve"], chat_history=[])
        out = capsys.readouterr().out
        assert "No active plan" in out

    def test_plan_generate_and_status(self, tmp_path, capsys):
        ps = self._make_plan_session(tmp_path)
        llm_resp = textwrap.dedent("""\
            TASK: Add a login endpoint

            PLAN:
            1. Create auth.py -- add login function
            2. Update main.py -- register route

            RISKS:
            - SQL injection if input not sanitized

            TESTS:
            - pytest tests/test_auth.py
        """)
        with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm(llm_resp)):
            with patch("app.core.repo_map.RepoMap.to_prompt_block", return_value="Workspace: tmp"):
                with patch("app.core.spinner.Spinner.__enter__", return_value=None):
                    with patch("app.core.spinner.Spinner.__exit__", return_value=None):
                        ps.cmd_plan(["Add a login endpoint"], chat_history=[])
        out = capsys.readouterr().out
        assert "Add a login endpoint" in out or "Plan" in out

    def test_plan_parse_steps(self, tmp_path):
        ps = self._make_plan_session(tmp_path)
        raw = (
            "TASK: Fix bug\n\nPLAN:\n1. Edit foo.py -- fix null check\n"
            "2. Add test in test_foo.py\n\nRISKS:\n- Race condition\n\nTESTS:\n- pytest"
        )
        plan = ps._parse_plan(raw)
        assert plan.task == "Fix bug"
        assert len(plan.steps) == 2
        assert plan.steps[0].number == 1
        assert "foo.py" in plan.steps[0].description
        assert len(plan.risks) == 1
        assert len(plan.tests) == 1

    def test_plan_parse_section_markers_with_trailing_text(self, tmp_path):
        ps = self._make_plan_session(tmp_path)
        raw = "TASK: Something\nPLAN: steps follow\n1. Do X\nRISKS: here\n- Risk A\nTESTS: commands\n- run tests"
        plan = ps._parse_plan(raw)
        assert plan.task == "Something"
        assert len(plan.steps) == 1
        assert "Do X" in plan.steps[0].description

    def test_plan_cancel_active(self, tmp_path, capsys):
        from cli.plan_session import Plan, PlanStep
        ps = self._make_plan_session(tmp_path)
        ps._current = Plan(task="Test task", steps=[PlanStep(1, "Step A")])
        ps.cmd_plan(["cancel"], chat_history=[])
        out = capsys.readouterr().out
        assert ps._current is None
        assert "Test task" in out or "discard" in out.lower()

    def test_plan_status_shows_steps(self, tmp_path, capsys):
        from cli.plan_session import Plan, PlanStep
        ps = self._make_plan_session(tmp_path)
        ps._current = Plan(
            task="My task",
            steps=[PlanStep(1, "Create auth.py", done=True), PlanStep(2, "Add tests")]
        )
        ps.cmd_plan(["status"], chat_history=[])
        out = capsys.readouterr().out
        assert "My task" in out
        assert "Create auth.py" in out
        assert "Add tests" in out


# ===========================================================================
# ReviewRunner unit tests (engine-level)
# ===========================================================================

class TestReviewRunnerEngine:
    def test_parse_missing_line_number(self):
        from app.core.review_runner import ReviewRunner
        cfg = MagicMock()
        runner = ReviewRunner(cfg)
        raw = "RISK:MED  FILE:foo.py  LINE:none  CAT:bugs  MSG:Unchecked return\nSUMMARY: One issue."
        result = runner._parse_response(raw)
        assert len(result.findings) == 1
        assert result.findings[0].line is None
        assert result.findings[0].risk == "MED"

    def test_parse_invalid_risk_normalized(self):
        from app.core.review_runner import ReviewRunner
        cfg = MagicMock()
        runner = ReviewRunner(cfg)
        raw = "RISK:CRITICAL  FILE:x.py  LINE:1  CAT:security  MSG:Bad\nSUMMARY: Fixed."
        result = runner._parse_response(raw)
        # CRITICAL is not a known level — should normalize to INFO
        assert result.findings[0].risk == "INFO"

    def test_format_finding_with_line(self):
        from app.core.review_runner import ReviewFinding
        f = ReviewFinding(risk="HIGH", file="auth.py", line=42, category="security", message="Injection")
        formatted = f.format()
        assert "auth.py:42" in formatted
        assert "HIGH" in formatted
        assert "Injection" in formatted

    def test_format_finding_no_line(self):
        from app.core.review_runner import ReviewFinding
        f = ReviewFinding(risk="LOW", file="util.py", line=None, category="perf", message="Slow loop")
        formatted = f.format()
        assert "util.py" in formatted
        assert "LOW" in formatted
        assert ":" not in formatted.split("util.py")[1].split("--")[0]

    def test_review_security_no_content(self):
        from app.core.review_runner import ReviewRunner
        cfg = MagicMock()
        runner = ReviewRunner(cfg)
        result = runner.review_security()
        assert result.error == "Provide a diff or file paths."

    def test_review_files_context_cap(self, tmp_path):
        from app.core.review_runner import ReviewRunner
        # Create a large file (>8192 chars)
        large = tmp_path / "big.py"
        large.write_text("x = 1\n" * 5000, encoding="utf-8")
        cfg = MagicMock()
        runner = ReviewRunner(cfg)
        with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm("SUMMARY: ok.")):
            result = runner.review_files([str(large)])
        assert result.files_reviewed == 1
        assert not result.error


# ===========================================================================
# HybridRetriever unit tests
# ===========================================================================

class TestHybridRetrieverEngine:
    def test_index_and_query(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = MagicMock()
        cfg.ollama_url = "http://localhost:11434"
        retriever = HybridRetriever(cfg)
        (tmp_path / "sample.py").write_text(
            "def authenticate(user, password): return True\n", encoding="utf-8"
        )
        count = retriever.index_folder(str(tmp_path))
        assert count >= 1
        results = retriever.query("authenticate")
        assert isinstance(results, list)

    def test_stats_empty(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = MagicMock()
        cfg.ollama_url = "http://localhost:11434"
        retriever = HybridRetriever(cfg)
        stats = retriever.stats()
        assert stats.file_count == 0
        assert stats.chunk_count == 0
        assert stats.symbol_count == 0

    def test_clear_resets_state(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = MagicMock()
        cfg.ollama_url = "http://localhost:11434"
        retriever = HybridRetriever(cfg)
        (tmp_path / "a.py").write_text("class Foo: pass\n", encoding="utf-8")
        retriever.index_folder(str(tmp_path))
        assert retriever._symbol_index  # populated
        retriever.clear()
        assert retriever._symbol_index == {}

    def test_symbol_index_populated(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = MagicMock()
        cfg.ollama_url = "http://localhost:11434"
        retriever = HybridRetriever(cfg)
        py_file = tmp_path / "mod.py"
        py_file.write_text(
            "class Auth:\n    def login(self): pass\n    def logout(self): pass\n",
            encoding="utf-8",
        )
        retriever.index_folder(str(tmp_path))
        assert "Auth" in retriever._symbol_index
        assert "login" in retriever._symbol_index
        assert "logout" in retriever._symbol_index

    def test_index_file_returns_true(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = MagicMock()
        cfg.ollama_url = "http://localhost:11434"
        retriever = HybridRetriever(cfg)
        f = tmp_path / "x.py"
        f.write_text("x = 1\n", encoding="utf-8")
        assert retriever.index_file(str(f)) is True

    def test_index_file_missing_returns_false(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = MagicMock()
        cfg.ollama_url = "http://localhost:11434"
        retriever = HybridRetriever(cfg)
        assert retriever.index_file(str(tmp_path / "ghost.py")) is False

    def test_skip_dirs_excluded(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = MagicMock()
        cfg.ollama_url = "http://localhost:11434"
        retriever = HybridRetriever(cfg)
        # create files in skip dirs
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "site.py").write_text("import sys\n", encoding="utf-8")
        # create a real file
        (tmp_path / "real.py").write_text("def real(): pass\n", encoding="utf-8")
        count = retriever.index_folder(str(tmp_path))
        assert count == 1  # only real.py


# ===========================================================================
# ResearchRunner unit tests
# ===========================================================================

class TestResearchRunnerEngine:
    def test_query_no_indexed_content(self, tmp_path):
        from app.core.research_runner import ResearchRunner
        cfg = MagicMock()
        cfg.ollama_url = "http://localhost:11434"
        runner = ResearchRunner(cfg)
        result = runner.query("what does foo do")
        assert result.error != ""
        assert "No indexed content" in result.error

    def test_query_returns_result(self, tmp_path):
        from app.core.research_runner import ResearchRunner
        from app.core.hybrid_retriever import RetrievedChunk
        cfg = MagicMock()
        cfg.ollama_url = "http://localhost:11434"
        runner = ResearchRunner(cfg)
        chunks = [
            RetrievedChunk(source="auth.py", content="def login(u, p): return True", score=0.9, kind="bm25"),
        ]
        mock_retriever = MagicMock()
        mock_retriever.query.return_value = chunks
        mock_retriever.stats.return_value = MagicMock(file_count=1)
        runner._retriever = mock_retriever
        with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm(
            "## Answer\nThe login function returns True.\n\n## Files Referenced\n- auth.py\n\n## Follow-up Questions\n- How is the session managed?\n"
        )):
            result = runner.query("what does login do")
        assert result.answer != ""
        assert "auth.py" in result.files_used
        assert result.chunks_used == 1

    def test_extract_follow_ups(self, tmp_path):
        from app.core.research_runner import ResearchRunner
        cfg = MagicMock()
        runner = ResearchRunner(cfg)
        answer = (
            "## Answer\nSome answer.\n\n## Files Referenced\n- a.py\n\n"
            "## Follow-up Questions\n- How is session managed?\n- What about tokens?\n- Where is logout?\n"
        )
        ups = runner._extract_follow_ups(answer)
        assert len(ups) == 3
        assert "How is session managed?" in ups[0]

    def test_follow_ups_capped_at_3(self, tmp_path):
        from app.core.research_runner import ResearchRunner
        cfg = MagicMock()
        runner = ResearchRunner(cfg)
        answer = (
            "## Follow-up Questions\n"
            "- Q1?\n- Q2?\n- Q3?\n- Q4?\n- Q5?\n"
        )
        ups = runner._extract_follow_ups(answer)
        assert len(ups) == 3


# ===========================================================================
# TestFixLoop unit tests (engine-level)
# ===========================================================================

class TestFixLoopEngine:
    def test_detect_runner_pytest(self, tmp_path):
        from app.core.test_fix_loop import detect_test_runner
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n", encoding="utf-8")
        cmd = detect_test_runner(str(tmp_path))
        assert sys.executable in cmd
        assert "-m" in cmd
        assert "pytest" in cmd

    def test_detect_runner_npm(self, tmp_path):
        from app.core.test_fix_loop import detect_test_runner
        (tmp_path / "package.json").write_text('{"name":"test"}', encoding="utf-8")
        cmd = detect_test_runner(str(tmp_path))
        assert "npm" in cmd

    def test_detect_runner_cargo(self, tmp_path):
        from app.core.test_fix_loop import detect_test_runner
        (tmp_path / "Cargo.toml").write_text("[package]\nname='test'\n", encoding="utf-8")
        cmd = detect_test_runner(str(tmp_path))
        assert "cargo" in cmd

    def test_detect_runner_go(self, tmp_path):
        from app.core.test_fix_loop import detect_test_runner
        (tmp_path / "go.mod").write_text("module example.com/test\n", encoding="utf-8")
        cmd = detect_test_runner(str(tmp_path))
        assert "go" in cmd

    def test_parse_pytest_failures(self):
        from app.core.test_fix_loop import parse_pytest_failures
        output = (
            "FAILED tests/test_auth.py::test_login - AssertionError: expected True\n"
            "FAILED tests/test_utils.py::test_format - TypeError: bad type\n"
        )
        failures = parse_pytest_failures(output)
        assert len(failures) == 2
        assert failures[0].test_id == "tests/test_auth.py::test_login"
        assert failures[0].file == "tests/test_auth.py"
        assert "AssertionError" in failures[0].error

    def test_parse_failures_routes_to_pytest(self):
        from app.core.test_fix_loop import parse_failures
        import sys
        runner = [sys.executable, "-m", "pytest", "--tb=short", "-q"]
        output = "FAILED tests/t.py::test_x - AssertionError\n"
        failures = parse_failures(runner, output)
        assert len(failures) == 1

    def test_parse_failures_routes_to_jest(self):
        from app.core.test_fix_loop import parse_failures
        runner = ["npm", "test"]
        output = "● test name\n\nsome failure\n\n"
        failures = parse_failures(runner, output)
        assert isinstance(failures, list)

    def test_split_patches_single(self):
        from app.core.test_fix_loop import TestFixLoop
        loop = TestFixLoop(MagicMock(), max_attempts=3)
        patch_text = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x=1\n+x=2\n"
        patches = loop._split_patches(patch_text)
        assert len(patches) == 1
        assert "foo.py" in patches[0]

    def test_split_patches_multiple(self):
        from app.core.test_fix_loop import TestFixLoop
        loop = TestFixLoop(MagicMock(), max_attempts=3)
        patch_text = (
            "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x=1\n+x=2\n"
            "--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-y=1\n+y=2\n"
        )
        patches = loop._split_patches(patch_text)
        assert len(patches) == 2

    def test_only_flag_uses_runner_string(self, tmp_path):
        from app.core.test_fix_loop import TestFixLoop
        from app.core.process_runner import ProcessResult
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n", encoding="utf-8")
        cfg = MagicMock()
        cfg.working_folder = str(tmp_path)
        loop = TestFixLoop(cfg, max_attempts=1)
        pr = ProcessResult(0, "", "", True)
        with patch("app.core.process_runner.run", return_value=pr) as mock_run:
            loop.run(str(tmp_path), only="test_auth")
        # Verify -k flag was added to pytest command
        called_cmds = [call[0][0] for call in mock_run.call_args_list]
        assert any("-k" in cmd and "test_auth" in cmd for cmd in called_cmds)


# ===========================================================================
# ProcessRunner tests
# ===========================================================================

class TestProcessRunnerIntegration:
    def test_run_simple_command(self):
        from app.core.process_runner import run
        result = run([sys.executable, "-c", "print('hello')"])
        assert result.ok
        assert "hello" in result.stdout

    def test_run_nonexistent_command(self):
        from app.core.process_runner import run
        result = run(["this_command_definitely_does_not_exist_xyz_123"])
        assert not result.ok
        assert "not found" in result.stderr.lower() or result.returncode == -1

    def test_run_timeout(self):
        from app.core.process_runner import run
        result = run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=1)
        assert not result.ok
        assert "Timed out" in result.stderr

    def test_run_exit_code_nonzero(self):
        from app.core.process_runner import run
        result = run([sys.executable, "-c", "raise SystemExit(3)"])
        assert result.returncode == 3
        assert not result.ok

    def test_run_stderr_captured(self):
        from app.core.process_runner import run
        result = run([sys.executable, "-c", "import sys; sys.stderr.write('oops')"])
        assert "oops" in result.stderr

    def test_run_with_cwd(self, tmp_path):
        from app.core.process_runner import run
        result = run([sys.executable, "-c", "import os; print(os.getcwd())"], cwd=str(tmp_path))
        assert result.ok
        # Normalise Windows drive letter casing for comparison
        assert tmp_path.name in result.stdout


# ===========================================================================
# display helpers
# ===========================================================================

class TestDisplayHelpers:
    def test_render_chat_response_plain(self, capsys):
        from cli.display import render_chat_response
        render_chat_response("Hello world")
        out = capsys.readouterr().out
        assert "Hello world" in out

    def test_render_chat_response_code_block(self, capsys):
        import re as _re
        from cli.display import render_chat_response
        text = "Here is some code:\n```python\nx = 1 + 1\n```\nDone."
        render_chat_response(text)
        raw = capsys.readouterr().out
        # Strip ANSI escape codes before assertion (Pygments adds them)
        plain = _re.sub(r"\x1b\[[0-9;]*m", "", raw)
        assert "x = 1 + 1" in plain
        assert "Done." in plain

    def test_estimate_cost_ollama_is_free(self):
        from cli.display import estimate_cost
        cost = estimate_cost("ollama", "codellama:7b", 1000, 500)
        assert cost == 0.0

    def test_estimate_cost_known_model(self):
        from cli.display import estimate_cost
        cost = estimate_cost("openai", "gpt-4o", 1_000_000, 1_000_000)
        assert cost is not None
        assert cost > 0

    def test_estimate_cost_unknown_model_returns_none(self):
        from cli.display import estimate_cost
        cost = estimate_cost("openai", "totally-made-up-model-xyz", 1000, 500)
        assert cost is None

    def test_format_cost_free(self):
        from cli.display import format_cost
        assert "FREE" in format_cost(0.0, "ollama")

    def test_format_cost_zero_paid(self):
        from cli.display import format_cost
        result = format_cost(0.0, "openai")
        assert "$0" in result

    def test_format_cost_small(self):
        from cli.display import format_cost
        result = format_cost(0.00005, "openai")
        assert "$" in result

    def test_hr_returns_string(self):
        from cli.display import hr
        result = hr()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_print_diff_line_added(self, capsys):
        from cli.display import print_diff_line
        print_diff_line("+new line")
        out = capsys.readouterr().out
        assert "new line" in out

    def test_print_diff_line_removed(self, capsys):
        from cli.display import print_diff_line
        print_diff_line("-old line")
        out = capsys.readouterr().out
        assert "old line" in out


# ===========================================================================
# config load/save round-trip
# ===========================================================================

class TestConfigRoundTrip:
    def test_load_defaults(self, tmp_path):
        from app.core.config import AppConfig, PermissionMode
        cfg = AppConfig()
        assert cfg.provider == "ollama"
        assert cfg.permission_mode == PermissionMode.ASK
        assert cfg.autofix_max_iterations == 5
        assert cfg.temperature == 0.7

    def test_working_folder_default_not_empty(self):
        from app.core.config import AppConfig
        cfg = AppConfig()
        assert cfg.working_folder != ""

    def test_permission_mode_enum(self):
        from app.core.config import AppConfig, PermissionMode
        cfg = AppConfig()
        cfg.permission_mode = PermissionMode.AUTO_APPROVE
        assert cfg.permission_mode.value == "auto_approve"

    def test_config_fields_present(self):
        from app.core.config import AppConfig
        cfg = AppConfig()
        assert hasattr(cfg, "route_strategy")
        assert hasattr(cfg, "permission_profile")
        assert hasattr(cfg, "command_allowlist")
        assert hasattr(cfg, "command_denylist")
        assert hasattr(cfg, "sandbox_mode")

    def test_list_fields_are_lists(self):
        from app.core.config import AppConfig
        cfg = AppConfig()
        assert isinstance(cfg.command_allowlist, list)
        assert isinstance(cfg.command_denylist, list)
        assert isinstance(cfg.fallback_providers, list)


# ===========================================================================
# display_compat (out / out_error / out_status / out_result)
# ===========================================================================

class TestDisplayCompat:
    def test_out_ansi_mode(self, capsys):
        from cli.display_compat import out
        with patch("cli.rich_display.get_output_mode", return_value="ansi"):
            out("hello world")
        assert "hello world" in capsys.readouterr().out

    def test_out_quiet_mode_suppressed(self, capsys):
        from cli.display_compat import out
        with patch("cli.rich_display.get_output_mode", return_value="quiet"):
            out("this should not appear")
        assert capsys.readouterr().out == ""

    def test_out_json_mode(self, capsys):
        from cli.display_compat import out
        with patch("cli.rich_display.get_output_mode", return_value="json"):
            out("json content")
        raw = capsys.readouterr().out.strip()
        data = json.loads(raw)
        assert data["type"] == "output"
        assert "json content" in data["content"]

    def test_out_error_always_shown(self, capsys):
        from cli.display_compat import out_error
        with patch("cli.rich_display.get_output_mode", return_value="quiet"):
            out_error("critical error")
        assert "critical error" in capsys.readouterr().out

    def test_out_status_suppressed_in_quiet(self, capsys):
        from cli.display_compat import out_status
        with patch("cli.rich_display.get_output_mode", return_value="quiet"):
            out_status("status message")
        assert capsys.readouterr().out == ""

    def test_out_result_always_shown(self, capsys):
        from cli.display_compat import out_result
        with patch("cli.rich_display.get_output_mode", return_value="ansi"):
            out_result("final result")
        assert "final result" in capsys.readouterr().out
