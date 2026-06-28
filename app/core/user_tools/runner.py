"""User tool runner — execute user tools in isolated subprocesses."""
from __future__ import annotations

import logging
import subprocess
import sys as _sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

PYTHON_EXE = _sys.executable

_log = logging.getLogger("ilx_cli.user_tools.runner")


def _resolve_python() -> str:
    """Return the running Python executable."""
    return _sys.executable


class ToolRunner:
    """Runs user tools in isolated subprocesses.

    - run_sync  — blocks the caller; returns a result dict.
    - run_async — spawns a daemon thread; streams output via callbacks.

    Neither method can crash the main CLI process: all exceptions are caught
    and surfaced through the result dict / on_done callback.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_sync(
        self,
        path: str | Path,
        args: list[str] | None = None,
        timeout: int = 60,
    ) -> dict:
        """Run *path* synchronously and return a result dict.

        Keys: ok (bool), output (str), error (str), exit_code (int | None).
        Captures stdout + stderr merged into *output*.
        """
        path = Path(path)
        if not path.exists():
            return {
                "ok": False,
                "output": "",
                "error": f"Tool file not found: {path}",
                "exit_code": None,
            }

        cmd = [_resolve_python(), str(path)] + (args or [])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=str(path.parent),
            )
            output = (proc.stdout + proc.stderr).strip()
            ok = proc.returncode == 0
            return {
                "ok": ok,
                "output": output[:8000],
                "error": "" if ok else f"Exit code {proc.returncode}",
                "exit_code": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "output": "",
                "error": f"Tool timed out after {timeout}s",
                "exit_code": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "output": "",
                "error": str(exc),
                "exit_code": None,
            }

    def run_async(
        self,
        path: str | Path,
        args: list[str] | None = None,
        on_output: Callable[[str], None] | None = None,
        on_done: Callable[[dict], None] | None = None,
        timeout: int = 300,
    ) -> threading.Thread:
        """Run *path* in a background daemon thread.

        *on_output(line)* is called for each stdout/stderr line as it arrives.
        *on_done(result_dict)* is called once when the process finishes.
        The thread is daemonic so it never blocks CLI shutdown.

        Returns the already-started Thread (callers can .join() if needed).
        """
        path = Path(path)
        t = threading.Thread(
            target=self._stream_subprocess,
            args=(path, args or [], on_output, on_done, timeout),
            daemon=True,
            name=f"ilx-tool-{path.stem}",
        )
        t.start()
        return t

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _stream_subprocess(
        self,
        path: Path,
        args: list[str],
        on_output: Callable[[str], None] | None,
        on_done: Callable[[dict], None] | None,
        timeout: int,
    ) -> None:
        """Internal: spawn subprocess, stream output line-by-line, call callbacks."""
        if not path.exists():
            result = {
                "ok": False,
                "output": "",
                "error": f"Tool file not found: {path}",
                "exit_code": None,
            }
            if on_done:
                try:
                    on_done(result)
                except Exception as exc:
                    _log.debug("User tool on_done callback error (missing file): %s", exc)
            return

        cmd = [_resolve_python(), str(path)] + args
        output_lines: list[str] = []
        deadline = time.monotonic() + timeout
        timed_out = False

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(path.parent),
            )
        except Exception as exc:
            result = {
                "ok": False,
                "output": "",
                "error": f"Failed to launch tool: {exc}",
                "exit_code": None,
            }
            if on_done:
                try:
                    on_done(result)
                except Exception as exc:
                    _log.debug("User tool on_done callback error (launch failure): %s", exc)
            return

        # Stream output
        assert proc.stdout is not None
        try:
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                output_lines.append(line)
                if on_output:
                    try:
                        on_output(line)
                    except Exception as exc:
                        _log.debug("User tool on_output callback error: %s", exc)
                if time.monotonic() > deadline:
                    timed_out = True
                    _log.warning("User tool '%s' exceeded timeout (%ds), killing", path.name, timeout)
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
        except Exception as exc:
            _log.debug("Output read error for tool '%s': %s", path.name, exc)
        finally:
            try:
                proc.stdout.close()
            except Exception as exc:
                _log.debug("User tool stdout close error for '%s': %s", path.name, exc)

        # Await exit
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception as exc:
                _log.debug("User tool force-kill failed for '%s': %s", path.name, exc)

        exit_code = proc.returncode
        full_output = "\n".join(output_lines)[:8000]

        if timed_out:
            result = {
                "ok": False,
                "output": full_output,
                "error": f"Tool timed out after {timeout}s",
                "exit_code": exit_code,
            }
        elif exit_code == 0:
            result = {
                "ok": True,
                "output": full_output,
                "error": "",
                "exit_code": 0,
            }
        else:
            result = {
                "ok": False,
                "output": full_output,
                "error": f"Exit code {exit_code}",
                "exit_code": exit_code,
            }

        if on_done:
            try:
                on_done(result)
            except Exception as exc:
                _log.debug("on_done callback raised: %s", exc)
