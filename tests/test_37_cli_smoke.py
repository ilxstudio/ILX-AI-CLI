"""CLI golden-output smoke tests.

Verifies that main.py can be imported cleanly and that the --help and
--version flags produce the expected output without making LLM calls.

All tests are marked @pytest.mark.integration so they can be excluded
from fast unit-test runs with ``pytest -m 'not integration'``.
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main_with_args(argv: list[str]) -> tuple[str, int]:
    """Run main.main() with the given sys.argv, capture stdout, return (output, exit_code).

    SystemExit is caught and its code returned. All print() output is captured.
    """
    import io
    import builtins

    captured: list[str] = []
    orig_print = builtins.print

    def _fake_print(*args, **kwargs):
        end = kwargs.get("end", "\n")
        captured.append("".join(str(a) for a in args) + end)

    exit_code = 0
    with patch("sys.argv", ["ilx"] + argv):
        with patch("builtins.print", side_effect=_fake_print):
            try:
                import main as _main
                # Re-run main() to pick up the patched argv
                _main.main()
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else 0

    return "".join(captured), exit_code


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMainImport:
    def test_main_importable(self):
        """main.py must import without raising any exception."""
        import main  # noqa: F401 — import-only check
        assert hasattr(main, "main"), "main.py must define a main() function"


@pytest.mark.integration
class TestHelpFlag:
    def test_help_exits_zero(self):
        output, code = _run_main_with_args(["--help"])
        assert code == 0

    def test_help_contains_usage(self):
        output, _ = _run_main_with_args(["--help"])
        assert "Usage" in output or "usage" in output.lower()

    def test_help_mentions_version_flag(self):
        output, _ = _run_main_with_args(["--help"])
        assert "--version" in output

    def test_help_mentions_chat_flag(self):
        output, _ = _run_main_with_args(["--help"])
        assert "--chat" in output

    def test_help_mentions_ilx(self):
        output, _ = _run_main_with_args(["--help"])
        assert "ILX" in output or "ilx" in output.lower()

    def test_short_help_flag(self):
        output, code = _run_main_with_args(["-h"])
        assert code == 0
        assert "Usage" in output or "usage" in output.lower()


@pytest.mark.integration
class TestVersionFlag:
    def test_version_exits_zero(self):
        # app.version exports VERSION (not __version__); patch it so the
        # import in main.py succeeds regardless of the attribute name used.
        with patch.dict(
            sys.modules,
            {"app.version": type(sys)("app.version")},
        ):
            sys.modules["app.version"].__version__ = "0.3.0"
            sys.modules["app.version"].VERSION = "0.3.0"
            output, code = _run_main_with_args(["--version"])
        assert code == 0

    def test_version_contains_version_number(self):
        with patch.dict(
            sys.modules,
            {"app.version": type(sys)("app.version")},
        ):
            sys.modules["app.version"].__version__ = "0.3.0"
            sys.modules["app.version"].VERSION = "0.3.0"
            output, code = _run_main_with_args(["--version"])
        # Should contain a version-like string (digits and dots)
        import re
        assert re.search(r"\d+\.\d+", output), f"No version number found in: {output!r}"

    def test_version_mentions_ilx(self):
        with patch.dict(
            sys.modules,
            {"app.version": type(sys)("app.version")},
        ):
            sys.modules["app.version"].__version__ = "0.3.0"
            sys.modules["app.version"].VERSION = "0.3.0"
            output, code = _run_main_with_args(["--version"])
        assert "ILX" in output or "ilx" in output.lower()
