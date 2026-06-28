"""Lightweight terminal spinner for indicating background work.

Usage:
    with Spinner("Thinking"):
        result = slow_llm_call()
"""
from __future__ import annotations

import sys
import threading
import time


_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    """Context-manager spinner. Clears itself on exit."""

    def __init__(self, label: str = "", interval: float = 0.1) -> None:
        self.label    = label
        self.interval = interval
        self._stop    = threading.Event()
        self._thread  = threading.Thread(target=self._spin, daemon=True)

    def _spin(self) -> None:
        i = 0
        while not self._stop.is_set():
            frame = _FRAMES[i % len(_FRAMES)]
            sys.stdout.write(f"\r  {frame} {self.label}…")
            sys.stdout.flush()
            time.sleep(self.interval)
            i += 1

    def start(self) -> "Spinner":
        if sys.stdout.isatty():
            self._thread.start()
        return self

    def stop(self, clear: bool = True) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)
        if clear and sys.stdout.isatty():
            sys.stdout.write("\r" + " " * (len(self.label) + 8) + "\r")
            sys.stdout.flush()

    def __enter__(self) -> "Spinner":
        return self.start()

    def __exit__(self, *_) -> None:
        self.stop()
