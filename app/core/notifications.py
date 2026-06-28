"""Desktop notification utility for ILX AI CLI.

Windows: win10toast (fallback: console print)  |  macOS: osascript  |  Linux: notify-send

MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

import logging
import platform
from typing import TYPE_CHECKING

from app.core import process_runner

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.notifications")
_TIMEOUT = 5  # seconds for subprocess calls


def send_notification(title: str, message: str, cfg: AppConfig) -> bool:
    """Send a desktop notification. Returns True on success, False otherwise.

    Respects ``cfg.notifications_enabled``; never raises.
    """
    if not getattr(cfg, "notifications_enabled", False):
        _log.debug("notifications disabled — skipping")
        return False
    system = platform.system()
    if system == "Windows":
        return _notify_windows(title, message)
    if system == "Darwin":
        return _notify_macos(title, message)
    if system == "Linux":
        return _notify_linux(title, message)
    _log.warning("unsupported platform for notifications: %s", system)
    return False


def _notify_windows(title: str, message: str) -> bool:
    """Use win10toast; fall back to a console print."""
    try:
        from win10toast import ToastNotifier  # type: ignore
        ToastNotifier().show_toast(title, message, duration=5, threaded=True)
        return True
    except ImportError:
        print(f"  [Notification] {title}: {message}")
        print("  (pip install win10toast for native Windows toasts)")
        return True
    except Exception as exc:
        _log.warning("win10toast failed: %s", exc)
        return False


def _notify_macos(title: str, message: str) -> bool:
    """Send via osascript on macOS."""
    safe_title   = title.replace("'", "")
    safe_message = message.replace("'", "")
    script = f"display notification '{safe_message}' with title '{safe_title}'"
    try:
        r = process_runner.run(["osascript", "-e", script], timeout=_TIMEOUT)
        return r.returncode == 0
    except Exception as exc:
        _log.warning("osascript error: %s", exc)
        return False


def _notify_linux(title: str, message: str) -> bool:
    """Send via notify-send on Linux."""
    try:
        r = process_runner.run(["notify-send", title, message], timeout=_TIMEOUT)
        return r.returncode == 0
    except Exception as exc:
        _log.warning("notify-send error: %s", exc)
        return False
