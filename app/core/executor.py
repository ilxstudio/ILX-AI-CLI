# DEPRECATED: superseded by codex/app/runner.py — kept for reference only, not imported anywhere
from __future__ import annotations
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
from typing import Generator, TYPE_CHECKING

from app.core.audit import log_command, log_file_op
from app.core.permissions import FileOperation, PermissionEngine
from app.utils.file_utils import compute_diff, safe_resolve

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

_SENSITIVE_ENV_PREFIXES = (
    "ANTHROPIC_", "OPENAI_", "GOOGLE_", "GEMINI_", "AZURE_",
    "AWS_", "GCP_", "GCLOUD_", "DOCKER_", "GITHUB_", "GITLAB_",
    "BITBUCKET_", "HF_", "HUGGINGFACE_",
    "ILX_", "DATABASE_", "POSTGRES_", "MYSQL_", "REDIS_",
    "STRIPE_", "TWILIO_", "SENDGRID_", "MAILGUN_",
)
_SENSITIVE_ENV_NAMES = {
    "API_KEY", "APIKEY", "API_TOKEN", "ACCESS_TOKEN",
    "SECRET", "SECRET_KEY", "PRIVATE_KEY",
    "PASSWORD", "PASSWD", "DB_PASSWORD",
    "ENCRYPTION_KEY", "SESSION_SECRET",
}


def _sanitized_env() -> dict:
    env = {}
    for k, v in os.environ.items():
        if k in _SENSITIVE_ENV_NAMES:
            continue
        upper = k.upper()
        if upper.startswith(_SENSITIVE_ENV_PREFIXES):
            continue
        if any(upper.endswith(s) for s in ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD")):
            continue
        env[k] = v
    return env

if TYPE_CHECKING:
    from app.core.config import AppConfig


@dataclass
class ExecutorEvent:
    event_type: str
    line:       str | None = None
    exit_code:  int | None = None


class LocalExecutor:
    def __init__(self, config: "AppConfig", permission_engine: PermissionEngine):
        self._config   = config
        self._perms    = permission_engine
        self._proc: subprocess.Popen | None = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def reset_cancel(self) -> None:
        self._cancelled = False

    @property
    def working_folder(self) -> str:
        return self._config.working_folder

    def apply_file_operation(self, operation: FileOperation) -> bool:
        granted = self._perms.request_permission(operation)
        log_file_op(operation.op_type, str(operation.path), granted)
        if not granted:
            return False

        path = Path(operation.path)
        try:
            if operation.op_type == "delete":
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                content = operation.new_content or ""
                path.write_text(content, encoding="utf-8")
                log_file_op(operation.op_type, str(operation.path), True,
                            bytes_written=len(content.encode("utf-8")))
            return True
        except OSError as e:
            raise RuntimeError(f"File write failed: {e}") from e

    def _venv_python(self) -> str:
        wf = Path(self._config.working_folder)
        for rel in (".venv/Scripts/python.exe", ".venv/bin/python", ".venv/bin/python3"):
            p = wf / rel
            if p.exists():
                return str(p)
        return sys.executable

    def _resolve_command(self, command: list[str]) -> list[str]:
        if not command:
            return command
        first = command[0].lower()
        if first in ("python", "python3", "python.exe"):
            return [self._venv_python()] + command[1:]
        return command

    def execute(
        self,
        command: list[str],
        timeout: int | None = None,
    ) -> Generator[ExecutorEvent, None, None]:
        if timeout is None:
            timeout = self._config.exec_timeout

        wf = self._config.working_folder
        Path(wf).mkdir(parents=True, exist_ok=True)

        op = FileOperation(op_type="execute", path=wf, command=command)
        granted = self._perms.request_permission(op)
        log_command(list(command), wf, granted)
        if not granted:
            yield ExecutorEvent("denied", "Execution denied by permission settings.")
            return

        command = self._resolve_command(command)
        env = _sanitized_env()
        env["PYTHONUNBUFFERED"] = "1"

        try:
            self._proc = subprocess.Popen(
                command,
                cwd=wf,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=1,
                creationflags=_NO_WINDOW,
            )
        except FileNotFoundError as e:
            yield ExecutorEvent("error", str(e))
            return

        q: Queue = Queue()

        def _reader(stream, label):
            try:
                for line in stream:
                    q.put((label, line.rstrip("\n")))
            finally:
                q.put((label, None))

        t_out = threading.Thread(target=_reader, args=(self._proc.stdout, "stdout"), daemon=True)
        t_err = threading.Thread(target=_reader, args=(self._proc.stderr, "stderr"), daemon=True)
        t_out.start()
        t_err.start()

        closed = {"stdout": False, "stderr": False}
        try:
            while not (closed["stdout"] and closed["stderr"]):
                if self._cancelled:
                    self._proc.terminate()
                    break
                try:
                    label, line = q.get(timeout=0.1)
                except Empty:
                    continue
                if line is None:
                    closed[label] = True
                else:
                    yield ExecutorEvent(label, line)
        finally:
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            t_out.join(timeout=2)
            t_err.join(timeout=2)

        yield ExecutorEvent("exit", exit_code=self._proc.returncode)
