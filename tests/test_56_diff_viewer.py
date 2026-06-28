"""Tests for cli.diff_viewer — side-by-side terminal diff renderer.
MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

import io
import sys
import unittest


class TestDiffViewerImport(unittest.TestCase):
    def test_diff_viewer_import(self) -> None:
        """Module imports without error."""
        import importlib
        mod = importlib.import_module("cli.diff_viewer")
        self.assertTrue(hasattr(mod, "show_side_by_side_diff"))
        self.assertTrue(hasattr(mod, "show_file_change"))
        self.assertTrue(hasattr(mod, "_plain_diff"))


class TestShowSideBySideDiff(unittest.TestCase):
    """Tests for show_side_by_side_diff."""

    def _console(self) -> "object":
        """Return a Rich Console writing to a StringIO buffer, or None."""
        try:
            from rich.console import Console
            return Console(file=io.StringIO(), width=120, highlight=False, no_color=True)
        except ImportError:
            return None

    def test_no_changes(self) -> None:
        """Identical strings produce output mentioning 0 changes (or run without error)."""
        from cli.diff_viewer import show_side_by_side_diff
        console = self._console()
        original = "line one\nline two\nline three\n"
        show_side_by_side_diff(original, original, filename="same.py", console=console)
        if console is not None:
            buf = console.file.getvalue()  # type: ignore[union-attr]
            # Either "0 change" appears or at least the filename does
            self.assertTrue("0 change" in buf or "same.py" in buf)

    def test_additions(self) -> None:
        """Added lines appear in output."""
        from cli.diff_viewer import show_side_by_side_diff
        console = self._console()
        original = ""
        updated = "hello\nworld\n"
        show_side_by_side_diff(original, updated, filename="new.py", console=console)
        if console is not None:
            buf = console.file.getvalue()  # type: ignore[union-attr]
            self.assertIn("hello", buf)

    def test_deletions(self) -> None:
        """Removed lines are handled without error."""
        from cli.diff_viewer import show_side_by_side_diff
        console = self._console()
        original = "gone\nstays\n"
        updated = "stays\n"
        # Should not raise
        show_side_by_side_diff(original, updated, filename="del.py", console=console)

    def test_mixed_changes(self) -> None:
        """Mixed adds, removes, and unchanged lines run without error."""
        from cli.diff_viewer import show_side_by_side_diff
        console = self._console()
        original = "alpha\nbeta\ngamma\ndelta\n"
        updated = "alpha\nBETA\ngamma\nepsilon\n"
        show_side_by_side_diff(original, updated, filename="mixed.py", console=console)

    def test_empty_inputs(self) -> None:
        """Both empty strings produce no crash."""
        from cli.diff_viewer import show_side_by_side_diff
        console = self._console()
        show_side_by_side_diff("", "", filename="empty.py", console=console)

    def test_width_auto_detect(self) -> None:
        """width=None triggers auto-detection without error."""
        from cli.diff_viewer import show_side_by_side_diff
        console = self._console()
        show_side_by_side_diff("a\n", "b\n", filename="w.py", width=None, console=console)

    def test_width_override(self) -> None:
        """Explicit width is accepted."""
        from cli.diff_viewer import show_side_by_side_diff
        console = self._console()
        show_side_by_side_diff("a\n", "b\n", filename="w.py", width=80, console=console)


class TestShowFileChange(unittest.TestCase):
    """Tests for the show_file_change convenience wrapper."""

    def _console(self) -> "object":
        try:
            from rich.console import Console
            return Console(file=io.StringIO(), width=120, highlight=False, no_color=True)
        except ImportError:
            return None

    def test_show_file_change_wrapper(self) -> None:
        """show_file_change delegates to show_side_by_side_diff internally."""
        from cli.diff_viewer import show_file_change
        console = self._console()
        # Should not raise and should produce some output for a real change
        show_file_change(
            path="/some/project/utils.py",
            original="def foo():\n    pass\n",
            updated="def foo():\n    return 42\n",
            console=console,
        )
        if console is not None:
            buf = console.file.getvalue()  # type: ignore[union-attr]
            # Filename basename should appear
            self.assertIn("utils.py", buf)

    def test_show_file_change_new_file(self) -> None:
        """show_file_change with empty original (new file) runs without error."""
        from cli.diff_viewer import show_file_change
        console = self._console()
        show_file_change(
            path="new_module.py",
            original="",
            updated="x = 1\ny = 2\n",
            console=console,
        )


class TestPlainFallback(unittest.TestCase):
    """Tests for the _plain_diff ANSI fallback."""

    def test_plain_diff_output(self) -> None:
        """_plain_diff writes unified diff markers to stdout."""
        from cli.diff_viewer import _plain_diff
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            _plain_diff("old line\n", "new line\n", "sample.py")
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
        # Unified diff header lines always start with --- and +++
        self.assertTrue("---" in output or "+++" in output or "@" in output,
                        f"Expected unified diff markers, got: {output!r}")

    def test_plain_diff_no_changes(self) -> None:
        """_plain_diff with identical content produces no output."""
        from cli.diff_viewer import _plain_diff
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            _plain_diff("same\n", "same\n", "same.py")
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
        # No diff output for identical content
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
