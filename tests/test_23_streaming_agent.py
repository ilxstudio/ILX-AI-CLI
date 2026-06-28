"""Tests for streaming CodingAgent and parallel file writer.

Coverage:
  test_write_parallel_writes_multiple_files    — write_parallel creates files correctly
  test_write_parallel_atomicity_rollback       — failure in one write rolls back others
  test_write_parallel_dry_run                  — dry_run=True never creates files
  test_write_parallel_rejects_path_traversal   — ../etc/passwd style paths are rejected
  test_file_edit_dataclass_fields              — FileEdit has correct fields and defaults
  test_run_streaming_calls_on_chunk            — on_chunk callback receives tokens
  test_run_streaming_calls_on_status           — on_status called at least once
  test_run_streaming_returns_agent_result      — run_streaming() returns AgentResult
  test_write_parallel_empty_list               — empty edits returns empty list
  test_write_parallel_single_file              — single-file write works
"""
from __future__ import annotations

import json
import sys
from dataclasses import fields as dc_fields
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.parallel_writer import FileEdit, WriteResult, write_parallel
from codex.app.controller import AgentResult, CodingAgent
from codex.app.llm_client_base import BaseLLMClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid_json_response(summary: str = "done") -> str:
    """Return a minimal valid CodingAgent JSON response string."""
    return json.dumps({
        "summary": summary,
        "files": [{"path": "out.txt", "action": "replace", "content": "hello\n"}],
        "command_to_run": None,
    })


class _MockStreamingClient(BaseLLMClient):
    """Fake LLM client that exposes chat_stream and records calls."""

    def __init__(self, chunks: list[str]):
        super().__init__()
        self.chunks     = chunks
        self.call_count = 0

    def generate(self, prompt: str) -> str:
        self.call_count += 1
        return "".join(self.chunks)

    def chat_stream(self, messages: list[dict], system: str = ""):
        self.call_count += 1
        yield from self.chunks


class _MockNonStreamingClient(BaseLLMClient):
    """Fake LLM client with no chat_stream — tests fallback path."""

    def __init__(self, response: str):
        super().__init__()
        self.response   = response
        self.call_count = 0

    def generate(self, prompt: str) -> str:
        self.call_count += 1
        return self.response


# ── parallel_writer tests ─────────────────────────────────────────────────────

class TestWriteParallel:
    def test_writes_multiple_files(self, tmp_path):
        """write_parallel creates all requested files with correct content."""
        edits = [
            FileEdit(path=str(tmp_path / "a.txt"), content="alpha"),
            FileEdit(path=str(tmp_path / "b.txt"), content="beta"),
            FileEdit(path=str(tmp_path / "c.txt"), content="gamma"),
        ]
        results = write_parallel(edits)

        assert len(results) == 3
        assert all(r.ok for r in results), [r.error for r in results if not r.ok]
        assert (tmp_path / "a.txt").read_text() == "alpha"
        assert (tmp_path / "b.txt").read_text() == "beta"
        assert (tmp_path / "c.txt").read_text() == "gamma"

    def test_atomicity_rollback_on_failure(self, tmp_path):
        """If one write fails, all successfully written files are removed."""
        good1 = str(tmp_path / "good1.txt")
        good2 = str(tmp_path / "good2.txt")
        # A path inside a file (not a directory) will fail on mkdir
        bad_parent = tmp_path / "not_a_dir.txt"
        bad_parent.write_text("I am a file, not a dir")
        bad = str(bad_parent / "impossible.txt")

        edits = [
            FileEdit(path=good1, content="ok1"),
            FileEdit(path=bad,   content="will fail"),
            FileEdit(path=good2, content="ok2"),
        ]
        results = write_parallel(edits, max_workers=1)  # serial to keep order predictable

        # At least one result must be a failure
        assert any(not r.ok for r in results)
        # Rolled-back files must not exist on disk
        assert not Path(good1).exists(), "good1 should have been rolled back"
        assert not Path(good2).exists(), "good2 should have been rolled back"

    def test_dry_run_does_not_create_files(self, tmp_path):
        """dry_run=True validates paths but writes nothing."""
        path = str(tmp_path / "should_not_exist.txt")
        results = write_parallel([FileEdit(path=path, content="x")], dry_run=True)

        assert len(results) == 1
        assert results[0].ok
        assert not Path(path).exists()

    def test_rejects_path_traversal(self, tmp_path):
        """Path traversal patterns must be rejected without writing.

        We build the path as a raw string so the '..' component is NOT
        collapsed by Python's Path operator before reaching _validate_path.
        """
        # Construct the traversal path as a raw string to preserve '..'
        traversal = str(tmp_path) + "/../etc/passwd"
        results = write_parallel([FileEdit(path=traversal, content="evil")])

        assert len(results) == 1
        assert not results[0].ok, (
            f"Expected traversal path to be rejected but got ok=True: {results[0]}"
        )

    def test_rejects_relative_path(self):
        """Relative paths must be rejected."""
        results = write_parallel([FileEdit(path="relative/path.txt", content="x")])
        assert len(results) == 1
        assert not results[0].ok
        assert "absolute" in results[0].error.lower()

    def test_empty_list_returns_empty(self):
        """write_parallel([]) returns [] without error."""
        assert write_parallel([]) == []

    def test_single_file_write(self, tmp_path):
        """Single-file write produces one successful result."""
        p = str(tmp_path / "single.txt")
        results = write_parallel([FileEdit(path=p, content="solo")])

        assert len(results) == 1
        assert results[0].ok
        assert Path(p).read_text() == "solo"

    def test_creates_parent_directories(self, tmp_path):
        """write_parallel creates missing intermediate directories."""
        deep = str(tmp_path / "a" / "b" / "c" / "file.txt")
        results = write_parallel([FileEdit(path=deep, content="deep")])
        assert results[0].ok
        assert Path(deep).read_text() == "deep"


class TestFileEditDataclass:
    def test_has_required_fields(self):
        """FileEdit has path, content, and encoding fields."""
        names = {f.name for f in dc_fields(FileEdit)}
        assert "path" in names
        assert "content" in names
        assert "encoding" in names

    def test_encoding_defaults_to_utf8(self):
        fe = FileEdit(path="/tmp/x.txt", content="hi")
        assert fe.encoding == "utf-8"

    def test_write_result_fields(self):
        names = {f.name for f in dc_fields(WriteResult)}
        assert "path" in names
        assert "ok" in names
        assert "error" in names


# ── CodingAgent.run_streaming tests ──────────────────────────────────────────

class TestRunStreaming:
    """Unit tests for CodingAgent.run_streaming() using mock LLM clients.

    We patch WorkspaceManager, ProjectChunker, AgentLogger, and friends so
    that no real filesystem scanning or LLM calls occur.
    """

    def _make_agent(self, client: BaseLLMClient) -> CodingAgent:
        return CodingAgent(
            llm_client=client,
            max_attempts=3,
            run_timeout=5,
        )

    def _patch_internals(self, tmp_path: Path, response_json: str):
        """Return a context-manager dict of patches for the agent internals."""
        import codex.app.controller_streaming as cs

        patches: list = [
            patch.object(cs, "_project_rules", None),
            patch("codex.app.controller_streaming.WorkspaceManager"),
            patch("codex.app.controller_streaming.CommandRunner"),
            patch("codex.app.controller_streaming.AgentLogger"),
            patch("codex.app.controller_streaming.AgentMemory"),
            patch("codex.app.controller_streaming.ProjectChunker"),
            patch("codex.app.controller_streaming.PromptBuilder"),
        ]
        return patches

    def test_on_chunk_called_with_tokens(self, tmp_path):
        """run_streaming() calls on_chunk for each streamed token."""
        chunks = ['{"summary":"ok","files":[{"path":"x.txt","action":"replace","content":"hi"}],'
                  '"command_to_run":null}']
        client = _MockStreamingClient(chunks)
        agent  = self._make_agent(client)

        received: list[str] = []

        import codex.app.controller_streaming as cs
        with (
            patch.object(cs, "_project_rules", None),
            patch("codex.app.controller_streaming.WorkspaceManager") as MockWS,
            patch("codex.app.controller_streaming.CommandRunner"),
            patch("codex.app.controller_streaming.AgentLogger") as MockLog,
            patch("codex.app.controller_streaming.AgentMemory"),
            patch("codex.app.controller_streaming.ProjectChunker") as MockChunker,
            patch("codex.app.controller_streaming.PromptBuilder") as MockPB,
        ):
            _setup_mocks(MockWS, MockLog, MockChunker, MockPB, tmp_path, chunks[0])
            result = agent.run_streaming(
                task="make x.txt",
                working_folder=str(tmp_path),
                on_chunk=received.append,
            )

        assert len(received) >= 1, "on_chunk was never called"
        assert "".join(received) != ""

    def test_on_status_called_at_least_once(self, tmp_path):
        """run_streaming() calls on_status at least once during a run."""
        response = _valid_json_response()
        client   = _MockStreamingClient([response])
        agent    = self._make_agent(client)

        statuses: list[str] = []

        import codex.app.controller_streaming as cs
        with (
            patch.object(cs, "_project_rules", None),
            patch("codex.app.controller_streaming.WorkspaceManager") as MockWS,
            patch("codex.app.controller_streaming.CommandRunner"),
            patch("codex.app.controller_streaming.AgentLogger") as MockLog,
            patch("codex.app.controller_streaming.AgentMemory"),
            patch("codex.app.controller_streaming.ProjectChunker") as MockChunker,
            patch("codex.app.controller_streaming.PromptBuilder") as MockPB,
        ):
            _setup_mocks(MockWS, MockLog, MockChunker, MockPB, tmp_path, response)
            agent.run_streaming(
                task="test",
                working_folder=str(tmp_path),
                on_status=statuses.append,
            )

        assert len(statuses) >= 1, "on_status was never called"

    def test_returns_agent_result(self, tmp_path):
        """run_streaming() returns an AgentResult instance."""
        response = _valid_json_response()
        client   = _MockStreamingClient([response])
        agent    = self._make_agent(client)

        import codex.app.controller_streaming as cs
        with (
            patch.object(cs, "_project_rules", None),
            patch("codex.app.controller_streaming.WorkspaceManager") as MockWS,
            patch("codex.app.controller_streaming.CommandRunner"),
            patch("codex.app.controller_streaming.AgentLogger") as MockLog,
            patch("codex.app.controller_streaming.AgentMemory"),
            patch("codex.app.controller_streaming.ProjectChunker") as MockChunker,
            patch("codex.app.controller_streaming.PromptBuilder") as MockPB,
        ):
            _setup_mocks(MockWS, MockLog, MockChunker, MockPB, tmp_path, response)
            result = agent.run_streaming(
                task="test",
                working_folder=str(tmp_path),
            )

        assert isinstance(result, AgentResult)
        assert hasattr(result, "success")
        assert hasattr(result, "attempts")
        assert hasattr(result, "run_id")

    def test_fallback_when_no_chat_stream(self, tmp_path):
        """run_streaming() falls back to generate() when chat_stream is absent."""
        response = _valid_json_response()
        client   = _MockNonStreamingClient(response)
        agent    = self._make_agent(client)

        received: list[str] = []

        import codex.app.controller_streaming as cs
        with (
            patch.object(cs, "_project_rules", None),
            patch("codex.app.controller_streaming.WorkspaceManager") as MockWS,
            patch("codex.app.controller_streaming.CommandRunner"),
            patch("codex.app.controller_streaming.AgentLogger") as MockLog,
            patch("codex.app.controller_streaming.AgentMemory"),
            patch("codex.app.controller_streaming.ProjectChunker") as MockChunker,
            patch("codex.app.controller_streaming.PromptBuilder") as MockPB,
        ):
            _setup_mocks(MockWS, MockLog, MockChunker, MockPB, tmp_path, response)
            result = agent.run_streaming(
                task="test",
                working_folder=str(tmp_path),
                on_chunk=received.append,
            )

        # generate() was called (not chat_stream)
        assert client.call_count >= 1
        assert isinstance(result, AgentResult)


# ── Shared mock-setup helper ──────────────────────────────────────────────────

def _setup_mocks(MockWS, MockLog, MockChunker, MockPB, tmp_path: Path, response_json: str) -> None:
    """Wire the common mock objects used by run_streaming_impl internals."""
    # WorkspaceManager
    ws_inst = MockWS.return_value
    ws_inst.read_file.return_value = ""

    # AgentLogger
    log_inst = MockLog.return_value
    log_inst.set_attempt = MagicMock()
    log_inst.log         = MagicMock()

    # ProjectChunker
    chunker_inst = MockChunker.return_value
    chunker_inst.index_workspace.return_value  = None
    chunker_inst.get_file_tree.return_value    = ""
    chunker_inst.get_file_contents.return_value = ""
    chunker_inst.find_chunk_for_error.return_value = ""

    # PromptBuilder
    pb_inst = MockPB.return_value
    pb_inst.build_initial.return_value = "PROMPT"
    pb_inst.build_repair.return_value  = "REPAIR_PROMPT"

    # AppPaths / workspace path — point at tmp_path so file writes land there
    import codex.app.controller_streaming as cs
    from codex.app.paths import AppPaths

    real_paths         = AppPaths("active_project")
    real_paths.workspace     = tmp_path
    real_paths.project_index = tmp_path / ".project_index"
    real_paths.project_index.mkdir(exist_ok=True)

    # Patch AppPaths constructor in the streaming module to return our instance
    with patch("codex.app.controller_streaming.AppPaths", return_value=real_paths):
        pass  # context already entered by caller — nothing to do here


# ── Re-run the two helpers with proper AppPaths patching ─────────────────────
# The _setup_mocks helper's AppPaths patch can't nest inside outer `with` blocks
# easily, so the three streaming tests above inline the AppPaths patch by
# letting working_folder set paths.workspace directly (which run_streaming_impl
# does via `if working_folder: paths.workspace = Path(working_folder)`).
# That is the correct integration path and requires no extra patching.
