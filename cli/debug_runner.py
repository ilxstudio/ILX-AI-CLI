"""Interactive debug runner — runs a program with live stdin/stdout passthrough."""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_LOG_DIR = Path.home() / ".ilx_cli" / "debug"


@dataclass
class DebugLine:
    ts:      float
    stream:  str   # "stdout" | "stderr" | "stdin" | "system"
    text:    str


@dataclass
class ErrorReport:
    exit_code:   int
    stderr_text: str
    error_lines: list[str]  # lines that look like errors or tracebacks
    log_path:    str
    session_id:  str
    elapsed_s:   float

    @property
    def has_error(self) -> bool:
        return self.exit_code != 0 or bool(self.error_lines)

    def summary(self) -> str:
        if not self.has_error:
            return f"Program exited cleanly (exit 0) in {self.elapsed_s:.1f}s."
        lines = [f"Program exited with code {self.exit_code} after {self.elapsed_s:.1f}s."]
        if self.error_lines:
            lines.append("Errors detected:")
            for ln in self.error_lines[:10]:
                lines.append(f"  {ln}")
        lines.append(f"Full log: {self.log_path}")
        return "\n".join(lines)


@dataclass
class DebugSession:
    session_id:  str
    command:     list[str]
    workspace:   str
    python_bin:  str
    log_path:    str
    lines:       list[DebugLine] = field(default_factory=list)
    exit_code:   int | None = None
    started_at:  float = field(default_factory=time.monotonic)
    finished_at: float | None = None

    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.monotonic()
        return end - self.started_at


def find_python(workspace: str) -> str:
    """Return the best python executable for the given workspace — prefers venv over system."""
    wf = Path(workspace)
    candidates = [
        wf / ".venv" / "Scripts" / "python.exe",
        wf / ".venv" / "bin" / "python",
        wf / "venv"  / "Scripts" / "python.exe",
        wf / "venv"  / "bin" / "python",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return sys.executable  # fall back to whatever's running right now


def venv_env(workspace: str, python_bin: str) -> dict:
    """Return an env dict with VIRTUAL_ENV set and the venv Scripts/bin prepended to PATH."""
    import os
    env = dict(os.environ)
    venv_root = Path(python_bin).parent.parent
    env["VIRTUAL_ENV"] = str(venv_root)
    scripts = str(venv_root / ("Scripts" if sys.platform == "win32" else "bin"))
    env["PATH"] = scripts + (";" if sys.platform == "win32" else ":") + env.get("PATH", "")
    env.pop("PYTHONHOME", None)
    return env


def _log_path(session_id: str) -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR / f"{session_id}.log"


def _json_path(session_id: str) -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR / f"{session_id}.json"


# substrings that indicate an error line worth flagging
_ERROR_PATTERNS = (
    "Traceback", "Error:", "Exception:", "FAILED", "error:", "fatal:",
    "PermissionError", "FileNotFoundError", "TypeError", "ValueError",
    "ImportError", "ModuleNotFoundError", "SyntaxError", "NameError",
)


def _is_error_line(text: str) -> bool:
    return any(p in text for p in _ERROR_PATTERNS)


def run_interactive(
    script_args: list[str],
    workspace:   str,
    session_id:  str = "",
    on_output:   Callable[[str, str], None] | None = None,
) -> ErrorReport:
    """Run script_args interactively with stdin passthrough.

    on_output(stream, line) is called for each output line so callers can accumulate output.
    Returns an ErrorReport when the process exits.
    """
    if not session_id:
        from datetime import datetime as _dt
        session_id = "debug_" + _dt.now().strftime("%Y%m%d_%H%M%S")

    python_bin = find_python(workspace)
    env        = venv_env(workspace, python_bin)

    # auto-prepend python for .py scripts
    from cli.commands.dev_tools import _resolve_run_args
    command = _resolve_run_args(script_args)
    # swap generic 'python' for the venv python
    if command and command[0] in ("python", "python3"):
        command = [python_bin] + command[1:]

    log_file  = _log_path(session_id)
    log_f     = None
    log_f     = open(log_file, "w", encoding="utf-8", buffering=1)  # noqa: WPS515

    lines: list[DebugLine] = []
    error_lines: list[str] = []
    stderr_buf: list[str]  = []
    t0 = time.monotonic()

    def _record(stream: str, text: str) -> None:
        dl = DebugLine(ts=time.monotonic() - t0, stream=stream, text=text)
        lines.append(dl)
        log_f.write(f"[{dl.ts:7.3f}] [{stream:6}] {text}\n")
        log_f.flush()
        if on_output:
            on_output(stream, text)
        if stream == "stderr":
            stderr_buf.append(text)
            if _is_error_line(text):
                error_lines.append(text)
        if stream == "stdout" and _is_error_line(text):
            error_lines.append(text)

    _record("system", f"Starting: {' '.join(command)}")
    _record("system", f"Python  : {python_bin}")
    _record("system", f"Workdir : {workspace}")

    try:
        proc = subprocess.Popen(
            command,
            cwd=workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,
        )
    except (FileNotFoundError, OSError) as exc:
        _record("system", f"Launch failed: {exc}")
        log_f.close()
        return ErrorReport(
            exit_code=-1,
            stderr_text=str(exc),
            error_lines=[str(exc)],
            log_path=str(log_file),
            session_id=session_id,
            elapsed_s=0.0,
        )

    done_evt = threading.Event()
    stdin_q:  queue.Queue[str | None] = queue.Queue()

    def _read_stream(stream, name: str) -> None:
        for line in stream:
            _record(name, line.rstrip("\n\r"))
        done_evt.set()

    def _write_stdin() -> None:
        while True:
            item = stdin_q.get()
            if item is None:
                break
            try:
                proc.stdin.write(item + "\n")
                proc.stdin.flush()
                _record("stdin", item)
            except OSError:
                break

    t_out    = threading.Thread(target=_read_stream, args=(proc.stdout, "stdout"), daemon=True)
    t_err    = threading.Thread(target=_read_stream, args=(proc.stderr, "stderr"), daemon=True)
    t_stdin  = threading.Thread(target=_write_stdin, daemon=True)
    t_out.start()
    t_err.start()
    t_stdin.start()

    # forward terminal input to the child process; degrades cleanly if stdin is captured
    exit_code = None
    stdin_available = True
    try:
        while True:
            exit_code = proc.poll()
            if exit_code is not None:
                break
            if not stdin_available:
                time.sleep(0.05)
                continue
            try:
                line = input()
                stdin_q.put(line)
            except EOFError:
                stdin_available = False
            except OSError:
                stdin_available = False
            except KeyboardInterrupt:
                _record("system", "KeyboardInterrupt — sending SIGINT")
                proc.terminate()
                break
    finally:
        stdin_q.put(None)  # signal the stdin thread to stop
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.wait(timeout=5)
        if exit_code is None:
            exit_code = proc.returncode or 0
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        elapsed = time.monotonic() - t0
        _record("system", f"Exit {exit_code}  ({elapsed:.2f}s)")
        if log_f is not None:
            log_f.close()

    # write a machine-readable JSON log alongside the human-readable one
    try:
        _json_path(session_id).write_text(
            json.dumps({
                "session_id": session_id,
                "command":    command,
                "workspace":  workspace,
                "python_bin": python_bin,
                "exit_code":  exit_code,
                "elapsed_s":  round(elapsed, 3),
                "lines":      [{"ts": l.ts, "stream": l.stream, "text": l.text} for l in lines],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass

    return ErrorReport(
        exit_code=exit_code,
        stderr_text="\n".join(stderr_buf),
        error_lines=error_lines,
        log_path=str(log_file),
        session_id=session_id,
        elapsed_s=elapsed,
    )


def list_sessions(limit: int = 10) -> list[Path]:
    if not _LOG_DIR.exists():
        return []
    logs = sorted(_LOG_DIR.glob("debug_*.log"), reverse=True)
    return logs[:limit]


def load_session_report(session_id: str) -> dict | None:
    p = _json_path(session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
