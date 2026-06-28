"""Tests for app.core.secret_store and app.core.spinner
— Copyright 2026 ILX Studio — MIT License"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# secret_store tests
# ---------------------------------------------------------------------------

class TestGetApiKey:

    def test_returns_empty_string_when_no_keyring_error(self) -> None:
        """get_api_key returns '' when NoKeyringError is raised."""
        import keyring.errors
        import app.core.secret_store as ss
        with patch("app.core.secret_store.keyring.get_password",
                   side_effect=keyring.errors.NoKeyringError()):
            result = ss.get_api_key("openai")
        assert result == ""

    def test_returns_stored_value_when_keyring_available(self) -> None:
        """get_api_key returns the value stored in keyring."""
        import app.core.secret_store as ss
        with patch("app.core.secret_store.keyring.get_password", return_value="sk-test-123"):
            result = ss.get_api_key("openai")
        assert result == "sk-test-123"

    def test_returns_empty_string_on_generic_exception(self) -> None:
        """get_api_key returns '' when keyring raises an unexpected exception."""
        import app.core.secret_store as ss
        with patch("app.core.secret_store.keyring.get_password",
                   side_effect=OSError("backend error")):
            result = ss.get_api_key("anthropic")
        assert result == ""

    def test_returns_empty_string_when_keyring_returns_none(self) -> None:
        """get_api_key returns '' (not None) when keyring returns None."""
        import app.core.secret_store as ss
        with patch("app.core.secret_store.keyring.get_password", return_value=None):
            result = ss.get_api_key("groq")
        assert result == ""


class TestSetApiKey:

    def test_set_api_key_calls_keyring_set_password(self) -> None:
        """set_api_key delegates to keyring.set_password with correct args."""
        import app.core.secret_store as ss
        with patch("app.core.secret_store.keyring.set_password") as mock_set:
            result = ss.set_api_key("my-key", provider="openai")
        mock_set.assert_called_once_with("ilx-cli", "api_key:openai", "my-key")
        assert result is True

    def test_set_api_key_returns_false_on_no_keyring_error(self) -> None:
        """set_api_key returns False when NoKeyringError is raised."""
        import keyring.errors
        import app.core.secret_store as ss
        with patch("app.core.secret_store.keyring.set_password",
                   side_effect=keyring.errors.NoKeyringError()):
            result = ss.set_api_key("my-key", provider="openai")
        assert result is False

    def test_set_api_key_empty_string_calls_delete(self) -> None:
        """set_api_key with an empty key delegates to delete_api_key."""
        import app.core.secret_store as ss
        with patch("app.core.secret_store.delete_api_key") as mock_del:
            result = ss.set_api_key("", provider="openai")
        mock_del.assert_called_once_with("openai")
        assert result is True


class TestIsKeyringAvailable:

    def test_returns_false_when_get_keyring_raises(self) -> None:
        """is_keyring_available returns False when keyring.get_keyring() raises."""
        import app.core.secret_store as ss
        with patch("app.core.secret_store.keyring.get_keyring",
                   side_effect=RuntimeError("no backend")):
            assert ss.is_keyring_available() is False

    def test_returns_false_for_fallback_backend(self) -> None:
        """is_keyring_available returns False when backend class name contains 'Keyring'."""
        import app.core.secret_store as ss
        mock_backend = MagicMock()
        mock_backend.__class__.__name__ = "fail.Keyring"
        with patch("app.core.secret_store.keyring.get_keyring", return_value=mock_backend):
            assert ss.is_keyring_available() is False

    def test_returns_true_for_real_backend(self) -> None:
        """is_keyring_available returns True when backend class name lacks 'Keyring'."""
        import app.core.secret_store as ss
        mock_backend = MagicMock()
        mock_backend.__class__.__name__ = "WindowsCredentialStoreBackend"
        with patch("app.core.secret_store.keyring.get_keyring", return_value=mock_backend):
            assert ss.is_keyring_available() is True


class TestWarnKeyringUnavailable:

    def test_warns_only_once(self) -> None:
        """_warn_keyring_unavailable logs at most one warning per process."""
        import app.core.secret_store as ss
        # Reset the flag so the test is idempotent
        original = ss._KEYRING_WARNED
        ss._KEYRING_WARNED = False
        try:
            with patch.object(ss._log, "warning") as mock_warn:
                ss._warn_keyring_unavailable()
                ss._warn_keyring_unavailable()
                ss._warn_keyring_unavailable()
            assert mock_warn.call_count == 1
        finally:
            ss._KEYRING_WARNED = original

    def test_sets_warned_flag(self) -> None:
        """_warn_keyring_unavailable sets _KEYRING_WARNED to True."""
        import app.core.secret_store as ss
        original = ss._KEYRING_WARNED
        ss._KEYRING_WARNED = False
        try:
            with patch.object(ss._log, "warning"):
                ss._warn_keyring_unavailable()
            assert ss._KEYRING_WARNED is True
        finally:
            ss._KEYRING_WARNED = original


class TestApiKeyAccount:

    def test_account_with_provider(self) -> None:
        """_api_key_account returns 'api_key:<provider>' for a named provider."""
        from app.core.secret_store import _api_key_account
        assert _api_key_account("openai") == "api_key:openai"

    def test_account_without_provider(self) -> None:
        """_api_key_account returns the default ACCOUNT constant when no provider given."""
        from app.core.secret_store import _api_key_account, ACCOUNT
        assert _api_key_account("") == ACCOUNT


# ---------------------------------------------------------------------------
# Spinner tests
# ---------------------------------------------------------------------------

class TestSpinner:

    def test_spinner_instantiation(self) -> None:
        """Spinner can be instantiated with a label."""
        from app.core.spinner import Spinner
        s = Spinner("Loading")
        assert s.label == "Loading"

    def test_start_and_stop_no_tty(self) -> None:
        """start() and stop() complete without error when stdout is not a tty."""
        from app.core.spinner import Spinner
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            s = Spinner("Working")
            s.start()
            s.stop()

    def test_context_manager_no_error(self) -> None:
        """Using Spinner as a context manager completes without raising."""
        from app.core.spinner import Spinner
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            with Spinner("Thinking"):
                pass  # body executes normally

    def test_context_manager_propagates_exception(self) -> None:
        """Spinner __exit__ does not suppress exceptions from the body."""
        from app.core.spinner import Spinner
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            with pytest.raises(ValueError, match="expected error"):
                with Spinner("Test"):
                    raise ValueError("expected error")
