"""Phase 3 & 4 feature tests -- review, fix-tests loop, plan, hybrid retriever, research."""
from __future__ import annotations

import json
import os
import sys
import textwrap
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(**kwargs):
    from app.core.config import AppConfig, PermissionMode
    cfg = AppConfig()
    cfg.working_folder = kwargs.get("working_folder", str(Path.home()))
    cfg.provider = kwargs.get("provider", "ollama")
    cfg.ollama_url = kwargs.get("ollama_url", "http://localhost:11434")
    cfg.ollama_model = kwargs.get("ollama_model", "codellama:7b")
    cfg.autofix_max_iterations = kwargs.get("autofix_max_iterations", 3)
    return cfg


def _fake_llm(response: str):
    """Return a mock LLM client that always returns *response*."""
    client = MagicMock()
    client.chat.return_value = response
    return client


# ===========================================================================
# P3-C: ReviewRunner
# ===========================================================================

class TestReviewRunner:
    def test_import(self):
        from app.core.review_runner import ReviewRunner, ReviewResult, ReviewFinding
        assert ReviewRunner is not None

    def test_parse_response_findings(self):
        from app.core.review_runner import ReviewRunner
        cfg = _make_cfg()
        runner = ReviewRunner(cfg)
        raw = (
            "RISK:HIGH  FILE:auth.py  LINE:42  CAT:security  MSG:SQL injection risk\n"
            "RISK:MED   FILE:utils.py LINE:none CAT:bugs  MSG:Unhandled None\n"
            "SUMMARY: Two issues found."
        )
        result = runner._parse_response(raw)
        assert len(result.findings) == 2
        assert result.findings[0].risk == "HIGH"
        assert result.findings[0].file == "auth.py"
        assert result.findings[0].line == 42
        assert result.findings[0].category == "security"
        assert result.findings[1].risk == "MED"
        assert result.findings[1].line is None
        assert result.summary == "Two issues found."

    def test_parse_response_no_findings(self):
        from app.core.review_runner import ReviewRunner
        cfg = _make_cfg()
        runner = ReviewRunner(cfg)
        result = runner._parse_response("SUMMARY: No significant issues found.")
        assert result.findings == []
        assert result.summary == "No significant issues found."

    def test_high_med_low_counts(self):
        from app.core.review_runner import ReviewRunner, ReviewFinding
        cfg = _make_cfg()
        runner = ReviewRunner(cfg)
        raw = (
            "RISK:HIGH  FILE:a.py LINE:1 CAT:security MSG:x\n"
            "RISK:HIGH  FILE:b.py LINE:2 CAT:bugs MSG:y\n"
            "RISK:MED   FILE:c.py LINE:3 CAT:maintainability MSG:z\n"
            "RISK:LOW   FILE:d.py LINE:4 CAT:perf MSG:w\n"
            "SUMMARY: Done."
        )
        result = runner._parse_response(raw)
        assert result.high_count() == 2
        assert result.med_count() == 1
        assert result.low_count() == 1

    def test_review_diff_empty(self):
        from app.core.review_runner import ReviewRunner
        cfg = _make_cfg()
        runner = ReviewRunner(cfg)
        result = runner.review_diff("")
        assert result.error != ""

    def test_review_files_missing(self):
        from app.core.review_runner import ReviewRunner
        cfg = _make_cfg()
        runner = ReviewRunner(cfg)
        result = runner.review_files(["/nonexistent/file.py"])
        assert result.error != ""

    def test_review_files_real(self, tmp_path):
        from app.core.review_runner import ReviewRunner
        cfg = _make_cfg(working_folder=str(tmp_path))
        f = tmp_path / "sample.py"
        f.write_text("def foo():\n    pass\n", encoding="utf-8")

        llm_response = (
            "RISK:LOW  FILE:sample.py  LINE:1  CAT:maintainability  MSG:Missing docstring\n"
            "SUMMARY: Minor issue."
        )
        runner = ReviewRunner(cfg)
        with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm(llm_response)):
            result = runner.review_files([str(f)])
        assert result.files_reviewed == 1
        assert len(result.findings) == 1

    def test_review_diff_real(self):
        from app.core.review_runner import ReviewRunner
        cfg = _make_cfg()
        diff = "--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@\n-x=1\n+x=input()\n"
        llm_response = (
            "RISK:HIGH  FILE:auth.py  LINE:1  CAT:security  MSG:User input not sanitized\n"
            "SUMMARY: Critical security issue."
        )
        runner = ReviewRunner(cfg)
        with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm(llm_response)):
            result = runner.review_diff(diff)
        assert result.high_count() == 1

    def test_review_security_no_input(self):
        from app.core.review_runner import ReviewRunner
        cfg = _make_cfg()
        runner = ReviewRunner(cfg)
        result = runner.review_security()
        assert result.error != ""

    def test_finding_format(self):
        from app.core.review_runner import ReviewFinding
        f = ReviewFinding(risk="HIGH", file="auth.py", line=10, category="security", message="SQL injection")
        formatted = f.format()
        assert "HIGH" in formatted
        assert "auth.py:10" in formatted
        assert "SQL injection" in formatted

    def test_finding_format_no_line(self):
        from app.core.review_runner import ReviewFinding
        f = ReviewFinding(risk="LOW", file="utils.py", line=None, category="perf", message="slow loop")
        formatted = f.format()
        assert "utils.py" in formatted
        assert ":None" not in formatted

    def test_llm_error_returns_result_with_error(self):
        from app.core.review_runner import ReviewRunner
        cfg = _make_cfg()
        runner = ReviewRunner(cfg)
        with patch("codex.app.llm_client.get_llm_client", side_effect=RuntimeError("no model")):
            result = runner.review_diff("diff content here")
        assert result.error != ""
        assert result.findings == []


# ===========================================================================
# P3-D: TestFixLoop
# ===========================================================================

class TestTestFixLoop:
    def test_import(self):
        from app.core.test_fix_loop import TestFixLoop, TestFixResult, TestFailure, FixAttempt
        assert TestFixLoop is not None

    def test_detect_runner_pytest(self, tmp_path):
        from app.core.test_fix_loop import detect_test_runner
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
        cmd = detect_test_runner(str(tmp_path))
        assert any("pytest" in c for c in cmd)

    def test_detect_runner_jest(self, tmp_path):
        from app.core.test_fix_loop import detect_test_runner
        (tmp_path / "package.json").write_text('{"name":"app"}', encoding="utf-8")
        cmd = detect_test_runner(str(tmp_path))
        assert "npm" in cmd

    def test_detect_runner_cargo(self, tmp_path):
        from app.core.test_fix_loop import detect_test_runner
        (tmp_path / "Cargo.toml").write_text("[package]\nname=\"app\"\n", encoding="utf-8")
        cmd = detect_test_runner(str(tmp_path))
        assert "cargo" in cmd

    def test_detect_runner_default(self, tmp_path):
        from app.core.test_fix_loop import detect_test_runner
        cmd = detect_test_runner(str(tmp_path))
        assert any("pytest" in c for c in cmd)

    def test_parse_pytest_failures(self):
        from app.core.test_fix_loop import parse_pytest_failures
        output = (
            "FAILED tests/test_foo.py::test_bar - AssertionError: expected 1, got 2\n"
            "FAILED tests/test_baz.py::test_qux - ValueError: invalid\n"
        )
        failures = parse_pytest_failures(output)
        assert len(failures) == 2
        assert failures[0].test_id == "tests/test_foo.py::test_bar"
        assert "AssertionError" in failures[0].error
        assert failures[1].test_id == "tests/test_baz.py::test_qux"

    def test_parse_jest_failures(self):
        from app.core.test_fix_loop import parse_jest_failures
        output = (
            "● my test suite > fails here\n\n"
            "  Expected: 1\n  Received: 2\n\n"
        )
        failures = parse_jest_failures(output)
        assert len(failures) >= 1

    def test_parse_failures_routes_pytest(self):
        from app.core.test_fix_loop import parse_failures
        output = "FAILED tests/x.py::y - AssertionError: x\n"
        # parse_failures checks if "pytest" appears anywhere in the command list
        cmd = [sys.executable, "-m", "pytest"]
        failures = parse_failures(cmd, output)
        # pytest is in position 2, so detection falls through to parse_pytest_failures
        assert len(failures) == 1

    def test_parse_failures_routes_pytest_direct(self):
        from app.core.test_fix_loop import parse_failures, parse_pytest_failures
        output = "FAILED tests/x.py::y - AssertionError: x\n"
        failures = parse_pytest_failures(output)
        assert len(failures) == 1

    def test_split_patches_single(self):
        from app.core.test_fix_loop import TestFixLoop
        cfg = _make_cfg()
        loop = TestFixLoop(cfg)
        patch_text = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
        patches = loop._split_patches(patch_text)
        assert len(patches) == 1

    def test_split_patches_multiple(self):
        from app.core.test_fix_loop import TestFixLoop
        cfg = _make_cfg()
        loop = TestFixLoop(cfg)
        patch_text = (
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"
            "--- a/bar.py\n+++ b/bar.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        patches = loop._split_patches(patch_text)
        assert len(patches) == 2

    def test_run_all_pass(self, tmp_path):
        """If tests already pass, loop exits immediately with final_pass=True."""
        from app.core.test_fix_loop import TestFixLoop

        cfg = _make_cfg(working_folder=str(tmp_path))
        loop = TestFixLoop(cfg, max_attempts=3)

        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "1 passed"
        mock_run.return_value.stderr = ""
        mock_run.return_value.ok = True

        with patch("app.core.process_runner.run", mock_run):
            result = loop.run(str(tmp_path))

        assert result.final_pass is True
        assert result.attempts == []

    def test_fix_attempt_dataclass(self):
        from app.core.test_fix_loop import FixAttempt
        a = FixAttempt(attempt=1, failures_before=3, failures_after=1, patches_applied=2)
        assert a.attempt == 1
        assert a.failures_before == 3
        assert a.failures_after == 1

    def test_test_failure_dataclass(self):
        from app.core.test_fix_loop import TestFailure
        f = TestFailure(test_id="test_foo", file="test_foo.py", line=10,
                        error="AssertionError", traceback="...")
        assert f.test_id == "test_foo"

    def test_result_error_propagates(self, tmp_path):
        from app.core.test_fix_loop import TestFixLoop

        cfg = _make_cfg(working_folder=str(tmp_path))
        loop = TestFixLoop(cfg, max_attempts=1)

        # Runner exits non-zero with no parseable failures
        mock_run = MagicMock()
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = "some unexpected output"
        mock_run.return_value.stderr = ""
        mock_run.return_value.ok = False

        with patch("app.core.process_runner.run", mock_run):
            result = loop.run(str(tmp_path))

        assert result.final_pass is False


# ===========================================================================
# P3-B: PlanSession
# ===========================================================================

class TestPlanSession:
    def _make_plan_session(self, tmp_path):
        from cli.plan_session import PlanSession
        cfg = _make_cfg(working_folder=str(tmp_path))
        ctx = MagicMock()
        return PlanSession(cfg, ctx)

    def test_import(self):
        from cli.plan_session import PlanSession, Plan, PlanStep
        assert PlanSession is not None

    def test_parse_plan_full(self, tmp_path):
        ps = self._make_plan_session(tmp_path)
        raw = (
            "TASK: Add auth middleware\n\n"
            "PLAN:\n"
            "1. Create middleware.py with JWT validation -- needed for auth\n"
            "2. Register in app.py -- wire it up\n\n"
            "RISKS:\n"
            "- Token expiry not handled\n\n"
            "TESTS:\n"
            "- pytest tests/test_auth.py\n"
        )
        plan = ps._parse_plan(raw)
        assert plan.task == "Add auth middleware"
        assert len(plan.steps) == 2
        assert plan.steps[0].number == 1
        assert "middleware.py" in plan.steps[0].description
        assert len(plan.risks) == 1
        assert len(plan.tests) == 1

    def test_parse_plan_empty(self, tmp_path):
        ps = self._make_plan_session(tmp_path)
        plan = ps._parse_plan("")
        assert plan.task == ""
        assert plan.steps == []

    def test_plan_cancel_no_plan(self, tmp_path, capsys):
        ps = self._make_plan_session(tmp_path)
        ps._plan_cancel()   # should not crash
        out = capsys.readouterr().out
        assert "No active plan" in out

    def test_plan_status_no_plan(self, tmp_path, capsys):
        ps = self._make_plan_session(tmp_path)
        ps._plan_status()
        out = capsys.readouterr().out
        assert "No active plan" in out

    def test_plan_status_with_plan(self, tmp_path, capsys):
        from cli.plan_session import Plan, PlanStep
        ps = self._make_plan_session(tmp_path)
        ps._current = Plan(task="Build feature X", steps=[
            PlanStep(number=1, description="Create foo.py"),
            PlanStep(number=2, description="Register in app.py", done=True),
        ])
        ps._plan_status()
        out = capsys.readouterr().out
        assert "Build feature X" in out
        assert "Create foo.py" in out

    def test_save_plan(self, tmp_path):
        from cli.plan_session import Plan, PlanStep
        ps = self._make_plan_session(tmp_path)
        plan = Plan(task="T", steps=[PlanStep(1, "do thing")], risks=["r"], tests=["t"])

        with patch("cli.plan_session._PLANS_DIR", tmp_path / "plans"):
            ps._save_plan(plan)
        saved = list((tmp_path / "plans").glob("plan_*.json"))
        assert len(saved) == 1
        data = json.loads(saved[0].read_text())
        assert data["task"] == "T"

    def test_cmd_plan_help(self, tmp_path, capsys):
        ps = self._make_plan_session(tmp_path)
        ps.cmd_plan(["help"], [])
        out = capsys.readouterr().out
        assert "/plan" in out

    def test_cmd_plan_cancel(self, tmp_path, capsys):
        from cli.plan_session import Plan
        ps = self._make_plan_session(tmp_path)
        ps._current = Plan(task="existing task")
        ps.cmd_plan(["cancel"], [])
        assert ps._current is None

    def test_plan_generate_calls_llm(self, tmp_path, capsys):
        ps = self._make_plan_session(tmp_path)
        llm_response = (
            "TASK: Test task\n\nPLAN:\n1. Step one in foo.py -- reason\n\n"
            "RISKS:\n- none\n\nTESTS:\n- pytest\n"
        )
        with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm(llm_response)):
            with patch("cli.plan_session._PLANS_DIR", tmp_path / "plans"):
                ps._plan_generate("add tests", [])
        assert ps._current is not None
        assert ps._current.task == "Test task"


# ===========================================================================
# P4-A/B: HybridRetriever
# ===========================================================================

class TestHybridRetriever:
    def test_import(self):
        from app.core.hybrid_retriever import HybridRetriever, RetrievedChunk, IndexStats
        assert HybridRetriever is not None

    def test_index_and_query(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = _make_cfg(working_folder=str(tmp_path))
        hr = HybridRetriever(cfg)

        # Create a source file
        src = tmp_path / "auth.py"
        src.write_text("def check_token(token):\n    return token == 'secret'\n", encoding="utf-8")

        count = hr.index_folder(str(tmp_path))
        assert count >= 1

        results = hr.query("token authentication")
        # query() returns a formatted context string (may be empty if BM25 finds nothing)
        assert isinstance(results, str)

    def test_index_file(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = _make_cfg(working_folder=str(tmp_path))
        hr = HybridRetriever(cfg)
        f = tmp_path / "foo.py"
        f.write_text("def foo(): pass\n", encoding="utf-8")
        assert hr.index_file(str(f)) is True

    def test_index_missing_file(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = _make_cfg()
        hr = HybridRetriever(cfg)
        assert hr.index_file("/nonexistent/path.py") is False

    def test_stats_empty(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = _make_cfg()
        hr = HybridRetriever(cfg)
        stats = hr.stats()
        assert stats.file_count == 0
        assert stats.symbol_count == 0

    def test_symbol_index_python(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = _make_cfg(working_folder=str(tmp_path))
        hr = HybridRetriever(cfg)
        src = tmp_path / "models.py"
        src.write_text(
            "class User:\n    pass\n\ndef create_user(name): pass\n",
            encoding="utf-8"
        )
        hr._index_symbols_from_file(str(src), src.read_text(encoding="utf-8"))
        assert "User" in hr._symbol_index
        assert "create_user" in hr._symbol_index

    def test_symbol_search_returns_hit(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = _make_cfg(working_folder=str(tmp_path))
        hr = HybridRetriever(cfg)
        src = tmp_path / "models.py"
        src.write_text("class UserModel:\n    pass\n", encoding="utf-8")
        hr._index_symbols_from_file(str(src), src.read_text(encoding="utf-8"))
        # Symbol should be registered in the symbol index
        assert "UserModel" in hr._symbol_index
        # query() returns a formatted context string
        results = hr.query("UserModel")
        assert isinstance(results, str)

    def test_clear(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = _make_cfg(working_folder=str(tmp_path))
        hr = HybridRetriever(cfg)
        f = tmp_path / "x.py"
        f.write_text("def x(): pass\n", encoding="utf-8")
        hr.index_file(str(f))
        hr.clear()
        stats = hr.stats()
        assert stats.file_count == 0

    def test_iter_source_files_skips_pycache(self, tmp_path):
        from app.core.hybrid_retriever import HybridRetriever
        cfg = _make_cfg()
        hr = HybridRetriever(cfg)
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "foo.pyc").write_bytes(b"\x00" * 10)
        (tmp_path / "real.py").write_text("x = 1\n", encoding="utf-8")
        files = list(hr._iter_source_files(tmp_path))
        assert all("__pycache__" not in str(f) for f in files)
        assert any(f.name == "real.py" for f in files)

    def test_retrieved_chunk_dataclass(self):
        from app.core.hybrid_retriever import RetrievedChunk
        c = RetrievedChunk(source="a.py", content="code", score=0.9, kind="bm25")
        assert c.score == 0.9
        assert c.kind == "bm25"

    def test_index_stats_dataclass(self):
        from app.core.hybrid_retriever import IndexStats
        s = IndexStats(file_count=5, chunk_count=20, symbol_count=10, db_size_kb=1.5)
        assert s.file_count == 5


# ===========================================================================
# P4-C: ResearchRunner
# ===========================================================================

class TestResearchRunner:
    def test_import(self):
        from app.core.research_runner import ResearchRunner, ResearchResult
        assert ResearchRunner is not None

    def test_query_no_index(self, tmp_path):
        from app.core.research_runner import ResearchRunner
        cfg = _make_cfg(working_folder=str(tmp_path))
        runner = ResearchRunner(cfg)
        # Empty index -> error
        result = runner.query("how does auth work?")
        assert result.error != "" or result.answer == ""

    def test_query_with_indexed_content(self, tmp_path):
        from app.core.research_runner import ResearchRunner
        cfg = _make_cfg(working_folder=str(tmp_path))
        # Write a source file
        src = tmp_path / "auth.py"
        src.write_text(
            "def verify_token(token): return token == 'secret'\n",
            encoding="utf-8"
        )
        llm_response = (
            "## Answer\nThe `verify_token` function in auth.py checks tokens.\n\n"
            "## Files Referenced\n- auth.py\n\n"
            "## Follow-up Questions\n- How are tokens generated?\n"
        )
        runner = ResearchRunner(cfg)
        # Explicitly build the index so chunks exist before querying
        runner.index_folder(str(tmp_path))
        with patch("codex.app.llm_client.get_llm_client", return_value=_fake_llm(llm_response)):
            result = runner.query("how does auth work?")
        assert result.error == ""
        assert result.answer != ""

    def test_extract_follow_ups(self, tmp_path):
        from app.core.research_runner import ResearchRunner
        cfg = _make_cfg()
        runner = ResearchRunner(cfg)
        answer = (
            "## Answer\nSome answer.\n\n"
            "## Follow-up Questions\n"
            "- How are tokens generated?\n"
            "- Where is this called from?\n"
        )
        fups = runner._extract_follow_ups(answer)
        assert len(fups) == 2
        assert "How are tokens generated?" in fups

    def test_result_dataclass(self):
        from app.core.research_runner import ResearchResult
        r = ResearchResult(
            query="q",
            answer="a",
            files_used=["a.py"],
            chunks_used=3,
            follow_ups=["next?"],
        )
        assert r.query == "q"
        assert r.chunks_used == 3

    def test_index_folder_delegates(self, tmp_path):
        from app.core.research_runner import ResearchRunner
        cfg = _make_cfg(working_folder=str(tmp_path))
        (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
        runner = ResearchRunner(cfg)
        count = runner.index_folder(str(tmp_path))
        assert count >= 1

    def test_llm_error_returns_error_result(self, tmp_path):
        from app.core.research_runner import ResearchRunner
        cfg = _make_cfg(working_folder=str(tmp_path))
        (tmp_path / "auth.py").write_text("def f(): pass\n", encoding="utf-8")
        runner = ResearchRunner(cfg)
        runner.index_folder(str(tmp_path))
        # Force LLM to fail — index is already populated by index_folder above
        with patch("codex.app.llm_client.get_llm_client", side_effect=RuntimeError("down")):
            result = runner.query("what does f do?", working_folder=str(tmp_path))
        assert result.error != ""


# ===========================================================================
# CLI command handlers
# ===========================================================================

class TestReviewCmds:
    def test_import(self):
        from cli.commands.review_cmds import ReviewCommands
        assert ReviewCommands is not None

    def test_help(self, capsys):
        from cli.commands.review_cmds import ReviewCommands
        cfg = _make_cfg()
        rc = ReviewCommands(cfg)
        rc.cmd_review(["help"])
        out = capsys.readouterr().out
        assert "/review" in out

    def test_no_args_shows_diff_review(self, tmp_path, capsys):
        from cli.commands.review_cmds import ReviewCommands
        cfg = _make_cfg(working_folder=str(tmp_path))
        rc = ReviewCommands(cfg)
        mock_run = MagicMock()
        mock_run.return_value.ok = False
        mock_run.return_value.stdout = ""
        with patch("app.core.process_runner.run", mock_run):
            rc.cmd_review([])
        out = capsys.readouterr().out
        assert "No uncommitted" in out or "review" in out.lower()

    def test_staged_no_changes(self, tmp_path, capsys):
        from cli.commands.review_cmds import ReviewCommands
        cfg = _make_cfg(working_folder=str(tmp_path))
        rc = ReviewCommands(cfg)
        mock_run = MagicMock()
        mock_run.return_value.ok = True
        mock_run.return_value.stdout = ""
        with patch("app.core.process_runner.run", mock_run):
            rc.cmd_review(["staged"])
        out = capsys.readouterr().out
        assert "No staged" in out


class TestFixCmds:
    def test_import(self):
        from cli.commands.fix_cmds import FixCommands
        assert FixCommands is not None

    def test_help(self, capsys):
        from cli.commands.fix_cmds import FixCommands
        cfg = _make_cfg()
        fc = FixCommands(cfg)
        fc.cmd_fix_tests(["help"])
        out = capsys.readouterr().out
        assert "/fix-tests" in out

    def test_dry_run(self, tmp_path, capsys):
        from cli.commands.fix_cmds import FixCommands
        cfg = _make_cfg(working_folder=str(tmp_path))
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        fc = FixCommands(cfg)
        fc.cmd_fix_tests(["--dry-run"])
        out = capsys.readouterr().out
        assert "dry run" in out.lower()

    def test_max_arg_parsed(self, tmp_path, capsys):
        from cli.commands.fix_cmds import FixCommands
        cfg = _make_cfg(working_folder=str(tmp_path))
        fc = FixCommands(cfg)
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "1 passed"
        mock_run.return_value.stderr = ""
        mock_run.return_value.ok = True
        with patch("app.core.process_runner.run", mock_run):
            fc.cmd_fix_tests(["--max", "1"])
        out = capsys.readouterr().out
        assert "Test-Fix Loop" in out


class TestIndexCmds:
    def test_import(self):
        from cli.commands.index_cmds import IndexCommands
        assert IndexCommands is not None

    def test_help(self, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg()
        ic = IndexCommands(cfg)
        ic.cmd_index(["help"])
        out = capsys.readouterr().out
        assert "/index" in out

    def test_status_empty(self, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg()
        ic = IndexCommands(cfg)
        ic.cmd_index(["status"])
        out = capsys.readouterr().out
        assert "Index" in out

    def test_build_invalid_path(self, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg()
        ic = IndexCommands(cfg)
        ic.cmd_index(["build", "/totally/nonexistent/path"])
        out = capsys.readouterr().out
        assert "Invalid" in out or "error" in out.lower()

    def test_build_valid_path(self, tmp_path, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg(working_folder=str(tmp_path))
        (tmp_path / "code.py").write_text("def hello(): pass\n", encoding="utf-8")
        ic = IndexCommands(cfg)
        ic.cmd_index(["build", str(tmp_path)])
        out = capsys.readouterr().out
        assert "Indexed" in out

    def test_clear(self, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg()
        ic = IndexCommands(cfg)
        ic.cmd_index(["clear"])
        out = capsys.readouterr().out
        assert "cleared" in out.lower() or "Index" in out

    def test_explain_no_args(self, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg()
        ic = IndexCommands(cfg)
        ic.cmd_index(["explain"])
        out = capsys.readouterr().out
        assert "Usage" in out

    def test_unknown_sub_shows_help(self, capsys):
        from cli.commands.index_cmds import IndexCommands
        cfg = _make_cfg()
        ic = IndexCommands(cfg)
        ic.cmd_index(["unknowncmd"])
        out = capsys.readouterr().out
        assert "/index" in out


# ===========================================================================
# App.py wiring
# ===========================================================================

class TestAppWiring:
    def _make_app(self):
        from cli.app import ILXApp
        from cli.command_registry import CommandRegistry
        with patch("cli.app.ILXApp.__init__", return_value=None):
            app = ILXApp.__new__(ILXApp)
            app._alias_store = MagicMock()
            app._registry = CommandRegistry()
            return app

    def test_all_commands_includes_plan(self):
        app = self._make_app()
        cmds = app._all_commands()
        assert "/plan" in cmds

    def test_all_commands_includes_review(self):
        app = self._make_app()
        cmds = app._all_commands()
        assert "/review" in cmds

    def test_all_commands_includes_fix_tests(self):
        app = self._make_app()
        cmds = app._all_commands()
        assert "/fix-tests" in cmds

    def test_all_commands_includes_index(self):
        app = self._make_app()
        cmds = app._all_commands()
        assert "/index" in cmds


# ===========================================================================
# Display help updated
# ===========================================================================

class TestDisplayHelp:
    def test_print_help_contains_plan(self, capsys):
        from cli.display import print_help
        print_help()
        out = capsys.readouterr().out
        assert "/plan" in out

    def test_print_help_contains_review(self, capsys):
        from cli.display import print_help
        print_help()
        out = capsys.readouterr().out
        assert "/review" in out

    def test_print_help_contains_fix_tests(self, capsys):
        from cli.display import print_help
        print_help()
        out = capsys.readouterr().out
        assert "/fix-tests" in out

    def test_print_help_contains_index(self, capsys):
        from cli.display import print_help
        print_help()
        out = capsys.readouterr().out
        assert "/index" in out

    def test_print_help_dev_contains_plan(self, capsys):
        from cli.display import print_help_dev
        print_help_dev()
        out = capsys.readouterr().out
        assert "/plan" in out

    def test_print_help_dev_contains_review(self, capsys):
        from cli.display import print_help_dev
        print_help_dev()
        out = capsys.readouterr().out
        assert "/review" in out

    def test_print_help_dev_contains_fix_tests(self, capsys):
        from cli.display import print_help_dev
        print_help_dev()
        out = capsys.readouterr().out
        assert "/fix-tests" in out

    def test_print_help_dev_contains_index_explain(self, capsys):
        from cli.display import print_help_dev
        print_help_dev()
        out = capsys.readouterr().out
        assert "/index explain" in out
