"""Tests for codex.app.chunker and codex.app.workspace — Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from codex.app.chunker import ProjectChunker, ChunkRecord, FileSummary
from codex.app.workspace import WorkspaceManager


# ---------------------------------------------------------------------------
# ProjectChunker tests
# ---------------------------------------------------------------------------

class TestProjectChunker:

    def _make_chunker(self, tmp_path: Path) -> ProjectChunker:
        index_dir = tmp_path / ".project_index"
        return ProjectChunker(workspace=tmp_path, index_dir=index_dir)

    def test_get_chunk_small_file(self, tmp_path: Path) -> None:
        """get_chunk returns numbered lines for a small text file."""
        chunker = self._make_chunker(tmp_path)
        (tmp_path / "hello.txt").write_text("line one\nline two\nline three\n", encoding="utf-8")
        result = chunker.get_chunk("hello.txt", 1, 3)
        assert "line one" in result
        assert "line two" in result
        assert "1" in result

    def test_get_chunk_python_content(self, tmp_path: Path) -> None:
        """get_chunk correctly slices Python source content."""
        chunker = self._make_chunker(tmp_path)
        src = "class Foo:\n    def bar(self):\n        return 42\n"
        (tmp_path / "foo.py").write_text(src, encoding="utf-8")
        result = chunker.get_chunk("foo.py", 1, 3)
        assert "class Foo" in result
        assert "def bar" in result

    def test_get_chunk_non_python_file(self, tmp_path: Path) -> None:
        """get_chunk works for non-Python files (e.g. .md)."""
        chunker = self._make_chunker(tmp_path)
        (tmp_path / "README.md").write_text("# Title\n\nBody text.\n", encoding="utf-8")
        result = chunker.get_chunk("README.md", 1, 3)
        assert "# Title" in result

    def test_get_chunk_empty_file_returns_empty_string(self, tmp_path: Path) -> None:
        """get_chunk on an empty file returns an empty string."""
        chunker = self._make_chunker(tmp_path)
        (tmp_path / "empty.py").write_text("", encoding="utf-8")
        result = chunker.get_chunk("empty.py", 1, 10)
        assert result == ""

    def test_chunk_size_respected(self, tmp_path: Path) -> None:
        """index_workspace creates chunks that never exceed CHUNK_SIZE lines."""
        chunker = self._make_chunker(tmp_path)
        total_lines = 200
        content = "\n".join(f"line {i}" for i in range(total_lines)) + "\n"
        (tmp_path / "big.py").write_text(content, encoding="utf-8")
        chunker.index_workspace()
        import json
        chunk_records = json.loads((tmp_path / ".project_index" / "chunk_summaries.json").read_text())
        for record in chunk_records:
            start_str, end_str = record["lines"].split("-")
            chunk_len = int(end_str) - int(start_str) + 1
            assert chunk_len <= ProjectChunker.CHUNK_SIZE

    def test_overlap_context_in_get_chunk(self, tmp_path: Path) -> None:
        """get_chunk with overlapping start/end includes surrounding lines."""
        chunker = self._make_chunker(tmp_path)
        lines = [f"line {i}\n" for i in range(1, 21)]
        (tmp_path / "file.py").write_text("".join(lines), encoding="utf-8")
        result = chunker.get_chunk("file.py", 5, 10)
        assert "line 5" in result
        assert "line 10" in result
        assert "line 4" not in result  # boundary respected

    def test_index_workspace_creates_json_files(self, tmp_path: Path) -> None:
        """index_workspace creates all three JSON index files."""
        chunker = self._make_chunker(tmp_path)
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        chunker.index_workspace()
        index = tmp_path / ".project_index"
        assert (index / "file_tree.json").exists()
        assert (index / "file_summaries.json").exists()
        assert (index / "chunk_summaries.json").exists()

    def test_find_chunk_for_error_no_matches(self, tmp_path: Path) -> None:
        """find_chunk_for_error returns empty string when no traceback pattern found."""
        chunker = self._make_chunker(tmp_path)
        result = chunker.find_chunk_for_error("some random string with no traceback")
        assert result == ""

    def test_read_lines_nonexistent_file(self, tmp_path: Path) -> None:
        """_read_lines returns [] for a file that does not exist."""
        chunker = self._make_chunker(tmp_path)
        result = chunker._read_lines("does_not_exist.py")
        assert result == []

    def test_get_file_tree_triggers_index(self, tmp_path: Path) -> None:
        """get_file_tree auto-indexes when the index is missing."""
        chunker = self._make_chunker(tmp_path)
        (tmp_path / "src.py").write_text("pass\n", encoding="utf-8")
        tree = chunker.get_file_tree()
        assert "src.py" in tree

    def test_get_file_contents_empty_workspace(self, tmp_path: Path) -> None:
        """get_file_contents returns '' for a workspace with no text files."""
        chunker = self._make_chunker(tmp_path)
        result = chunker.get_file_contents()
        assert result == ""


# ---------------------------------------------------------------------------
# WorkspaceManager tests
# ---------------------------------------------------------------------------

class TestWorkspaceManager:

    def test_init_resolves_path(self, tmp_path: Path) -> None:
        """WorkspaceManager.workspace is an absolute resolved path."""
        ws = WorkspaceManager(tmp_path)
        assert ws.workspace.is_absolute()

    def test_write_and_read_file(self, tmp_path: Path) -> None:
        """write_file persists content that read_file retrieves."""
        ws = WorkspaceManager(tmp_path)
        ws.write_file("notes.txt", "hello world")
        assert ws.read_file("notes.txt") == "hello world"

    def test_read_file_not_found_raises(self, tmp_path: Path) -> None:
        """read_file raises FileNotFoundError for a missing file."""
        ws = WorkspaceManager(tmp_path)
        with pytest.raises(FileNotFoundError):
            ws.read_file("missing.txt")

    def test_list_files_returns_written_files(self, tmp_path: Path) -> None:
        """list_files includes files written via write_file."""
        ws = WorkspaceManager(tmp_path)
        ws.write_file("a.txt", "aaa")
        ws.write_file("b.txt", "bbb")
        files = ws.list_files()
        assert "a.txt" in files
        assert "b.txt" in files

    def test_exists_true_and_false(self, tmp_path: Path) -> None:
        """WorkspaceManager.safe_path resolves correctly for existence checks."""
        ws = WorkspaceManager(tmp_path)
        ws.write_file("present.txt", "data")
        present = ws.safe_path("present.txt")
        absent = ws.safe_path("absent.txt")
        assert present.exists() is True
        assert absent.exists() is False

    def test_delete_file_removes_file(self, tmp_path: Path) -> None:
        """delete_file removes an existing file."""
        ws = WorkspaceManager(tmp_path)
        ws.write_file("del_me.txt", "bye")
        ws.delete_file("del_me.txt")
        assert not ws.safe_path("del_me.txt").exists()

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """safe_path raises ValueError for a path that escapes the workspace."""
        ws = WorkspaceManager(tmp_path)
        with pytest.raises(ValueError, match="Path traversal blocked"):
            ws.safe_path("../../etc/passwd")

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        """write_file creates intermediate directories automatically."""
        ws = WorkspaceManager(tmp_path)
        ws.write_file("sub/dir/file.txt", "nested")
        assert (tmp_path / "sub" / "dir" / "file.txt").exists()
