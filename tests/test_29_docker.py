"""Tests for cli.commands.docker_cmds — all Docker CLI calls are mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_cfg(working_folder: str = "") -> MagicMock:
    cfg = MagicMock()
    cfg.working_folder = working_folder
    return cfg


def _make_docker(wf: str = "") -> "DockerCommands":
    from cli.commands.docker_cmds import DockerCommands
    return DockerCommands(_make_cfg(wf))


# ---------------------------------------------------------------------------
# Test 1 — Instantiation
# ---------------------------------------------------------------------------

class TestDockerCommandsInit:
    def test_instantiates_without_error(self):
        """DockerCommands can be constructed without raising."""
        dc = _make_docker()
        assert dc is not None

    def test_cfg_stored(self):
        cfg = _make_cfg("/some/path")
        from cli.commands.docker_cmds import DockerCommands
        dc = DockerCommands(cfg)
        assert dc._cfg is cfg


# ---------------------------------------------------------------------------
# Test 2 — scaffold_dockerfile for 'python'
# ---------------------------------------------------------------------------

class TestScaffoldPython:
    def test_creates_dockerfile(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("python", tmp_path)
        assert (tmp_path / "Dockerfile").exists()

    def test_dockerfile_contains_python_from(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("python", tmp_path)
        content = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
        assert "FROM python:" in content

    def test_dockerfile_contains_non_root_user(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("python", tmp_path)
        content = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
        assert "USER appuser" in content

    def test_dockerignore_created_alongside(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("python", tmp_path)
        assert (tmp_path / ".dockerignore").exists()

    def test_dockerignore_contains_node_modules(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("python", tmp_path)
        content = (tmp_path / ".dockerignore").read_text(encoding="utf-8")
        assert "node_modules" in content

    def test_dockerignore_contains_dotenv(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("python", tmp_path)
        content = (tmp_path / ".dockerignore").read_text(encoding="utf-8")
        assert ".env" in content


# ---------------------------------------------------------------------------
# Test 3 — scaffold_dockerfile for 'go' (multi-stage)
# ---------------------------------------------------------------------------

class TestScaffoldGo:
    def test_go_scaffold_creates_dockerfile(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("go", tmp_path)
        assert (tmp_path / "Dockerfile").exists()

    def test_go_dockerfile_contains_scratch(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("go", tmp_path)
        content = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
        assert "FROM scratch" in content


# ---------------------------------------------------------------------------
# Test 4 — scaffold_dockerfile for 'fastapi'
# ---------------------------------------------------------------------------

class TestScaffoldFastapi:
    def test_fastapi_contains_uvicorn(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("fastapi", tmp_path)
        content = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
        assert "uvicorn" in content


# ---------------------------------------------------------------------------
# Test 5 — scaffold_dockerfile for 'node'
# ---------------------------------------------------------------------------

class TestScaffoldNode:
    def test_node_contains_npm_ci(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("node", tmp_path)
        content = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
        assert "npm ci" in content


# ---------------------------------------------------------------------------
# Test 6 — unknown project type
# ---------------------------------------------------------------------------

class TestScaffoldUnknownType:
    def test_unknown_type_returns_false(self, tmp_path, capsys):
        dc = _make_docker(str(tmp_path))
        result = dc.scaffold_dockerfile("cobol", tmp_path)
        assert result is False

    def test_unknown_type_does_not_create_dockerfile(self, tmp_path, capsys):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("cobol", tmp_path)
        assert not (tmp_path / "Dockerfile").exists()

    def test_unknown_type_prints_error_message(self, tmp_path, capsys):
        dc = _make_docker(str(tmp_path))
        dc.scaffold_dockerfile("cobol", tmp_path)
        captured = capsys.readouterr()
        assert "cobol" in captured.out.lower() or "unknown" in captured.out.lower()


# ---------------------------------------------------------------------------
# Test 7 — _run_docker (mocked subprocess)
# ---------------------------------------------------------------------------

class TestRunDocker:
    def test_run_docker_ok_returns_dict_with_ok_true(self):
        dc = _make_docker()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "24.0.5\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = dc._run_docker(["info", "--format", "{{.ServerVersion}}"], capture=True)

        assert isinstance(result, dict)
        assert result["ok"] is True
        assert "output" in result

    def test_run_docker_nonzero_returns_ok_false(self):
        dc = _make_docker()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error: docker daemon not running"

        with patch("subprocess.run", return_value=mock_result):
            result = dc._run_docker(["info"], capture=True)

        assert result["ok"] is False

    def test_run_docker_file_not_found_returns_ok_false(self):
        """If docker binary is missing, _run_docker returns ok=False gracefully."""
        dc = _make_docker()
        with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")):
            result = dc._run_docker(["info"], capture=True)

        assert result["ok"] is False
        assert "output" in result


# ---------------------------------------------------------------------------
# Test 8 — cmd_docker dispatcher for unknown sub-command
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_unknown_subcommand_prints_warning(self, capsys):
        dc = _make_docker()
        dc.cmd_docker(["xyzzy"])
        captured = capsys.readouterr()
        assert "xyzzy" in captured.out or "unknown" in captured.out.lower()

    def test_help_subcommand_does_not_raise(self, capsys):
        dc = _make_docker()
        dc.cmd_docker(["help"])
        captured = capsys.readouterr()
        assert len(captured.out) > 0


# ---------------------------------------------------------------------------
# Test 9 — scaffold returns True for valid types
# ---------------------------------------------------------------------------

class TestScaffoldReturnValue:
    def test_scaffold_python_returns_true(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        result = dc.scaffold_dockerfile("python", tmp_path)
        assert result is True

    def test_scaffold_rust_returns_true(self, tmp_path):
        dc = _make_docker(str(tmp_path))
        result = dc.scaffold_dockerfile("rust", tmp_path)
        assert result is True

    def test_all_supported_types_scaffold_successfully(self, tmp_path):
        from cli.commands.docker_cmds import BEST_PRACTICE_DOCKERFILES
        for ptype in BEST_PRACTICE_DOCKERFILES:
            subdir = tmp_path / ptype
            subdir.mkdir()
            dc = _make_docker(str(subdir))
            result = dc.scaffold_dockerfile(ptype, subdir)
            assert result is True, f"scaffold_dockerfile failed for type '{ptype}'"
            assert (subdir / "Dockerfile").exists(), f"Dockerfile missing for type '{ptype}'"
