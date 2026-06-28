"""Process supervisor — manages all user-spawned subprocesses."""
from __future__ import annotations

import collections
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_log = logging.getLogger("ilx_cli.supervisor")

# maps script extensions to their interpreter so we can print a helpful hint on failure
_SCRIPT_HINTS: dict[str, str] = {
    ".py":  "python",
    ".pyw": "python",
    ".js":  "node",
    ".mjs": "node",
    ".ts":  "npx ts-node",
    ".rb":  "ruby",
    ".go":  "go run",
    ".sh":  "bash",
}


def _hint_for_script(command: list[str]) -> None:
    if not command:
        return
    ext = Path(command[0]).suffix.lower()
    interp = _SCRIPT_HINTS.get(ext)
    if interp:
        print(f"  Hint: run script files with their interpreter — e.g.  /run {interp} {command[0]}")
        print(f"  (ILX AI auto-detects .py, .js and other extensions — just use /run {command[0]} again)")


class TaskStatus(str, Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    KILLED    = "killed"
    TIMEOUT   = "timeout"


@dataclass
class ManagedTask:
    task_id:    str
    label:      str
    command:    list[str]
    cwd:        str | None
    started_at: float = field(default_factory=time.monotonic)
    status:     TaskStatus = TaskStatus.RUNNING
    exit_code:  int | None = None
    pid:        int | None = None
    output_tail: collections.deque = field(  # O(1) append+evict ring buffer
        default_factory=lambda: collections.deque(maxlen=100)
    )
    finished_at: float | None = None

    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.monotonic()
        return end - self.started_at

    def status_line(self) -> str:
        elapsed_s = f"{self.elapsed:.1f}s"
        pid_s     = f"  PID {self.pid}" if self.pid else ""
        code_s    = f"  exit={self.exit_code}" if self.exit_code is not None else ""
        return f"[{self.task_id}] {self.status.value:<10}  {elapsed_s:<8}{pid_s}{code_s}  {self.label}"


# holds everything needed to start a queued task once a slot opens up
@dataclass
class _QueuedItem:
    task_id:   str
    command:   list[str]
    label:     str
    cwd:       str | None
    timeout:   int | None
    on_line:   Callable[[str], None] | None
    on_finish: Callable[[ManagedTask], None] | None
    env:       dict | None


class ProcessSupervisor:

    _MAX_TAIL       = 100   # lines of output kept per task
    _NEXT_ID        = 1

    def __init__(self, max_concurrent: int = 4) -> None:
        self._lock            = threading.RLock()
        self._tasks:  dict[str, ManagedTask]       = {}
        self._procs:  dict[str, subprocess.Popen]  = {}
        self._queue:  collections.deque[_QueuedItem] = collections.deque()
        self._max_concurrent: int = max_concurrent
        self._shutting_down: bool = False

    # ── public API ────────────────────────────────────────────────────────────

    def spawn(
        self,
        command:    list[str],
        label:      str = "",
        cwd:        str | None = None,
        timeout:    int | None = None,
        on_line:    Callable[[str], None] | None = None,
        on_finish:  Callable[[ManagedTask], None] | None = None,
        env:        dict | None = None,
    ) -> ManagedTask:
        """Spawn *command* as a supervised child process.

        If the concurrency limit has been reached, the task is queued and
        started automatically when a running task finishes.
        Raises RuntimeError if shutdown() has been called.
        Returns the ManagedTask immediately (non-blocking).
        """
        with self._lock:
            if self._shutting_down:
                raise RuntimeError(
                    "ProcessSupervisor is shutting down — no new tasks accepted."
                )

        task_id = self._next_id()

        with self._lock:
            running_count = sum(
                1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING
            )
            if running_count >= self._max_concurrent:
                # queue instead of launching — _on_task_done will start it later
                task = ManagedTask(
                    task_id=task_id,
                    label=label or " ".join(command[:3]),
                    command=command,
                    cwd=cwd,
                    status=TaskStatus.QUEUED,
                )
                self._tasks[task_id] = task
                self._queue.append(
                    _QueuedItem(
                        task_id=task_id,
                        command=command,
                        label=label,
                        cwd=cwd,
                        timeout=timeout,
                        on_line=on_line,
                        on_finish=on_finish,
                        env=env,
                    )
                )
                _log.info("Task %s queued (running=%d, limit=%d)", task_id, running_count, self._max_concurrent)
                return task

        return self._launch(task_id, command, label, cwd, timeout, on_line, on_finish, env)

    def _launch(
        self,
        task_id:   str,
        command:   list[str],
        label:     str,
        cwd:       str | None,
        timeout:   int | None,
        on_line:   Callable[[str], None] | None,
        on_finish: Callable[[ManagedTask], None] | None,
        env:       dict | None,
    ) -> ManagedTask:
        task = ManagedTask(
            task_id=task_id,
            label=label or " ".join(command[:3]),
            command=command,
            cwd=cwd,
        )

        # stderr=PIPE (not STDOUT) avoids WinError 6 when pytest captures the
        # parent's stdout — merging via STDOUT reuses the same handle which
        # can become invalid under capsys
        popen_kwargs: dict = dict(
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP only — avoids WinError 6/50 that occur when
            # CREATE_NO_WINDOW is combined with PIPE stdio in headless/pytest contexts
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["close_fds"] = True
            popen_kwargs["preexec_fn"] = os.setsid

        try:
            proc = subprocess.Popen(command, **popen_kwargs)
            task.pid = proc.pid
        except FileNotFoundError:
            task.status    = TaskStatus.FAILED
            task.exit_code = -1
            task.finished_at = time.monotonic()
            with self._lock:
                self._tasks[task_id] = task
            _log.error("Command not found: %s", command[0])
            _hint_for_script(command)
            return task
        except OSError as exc:
            task.status    = TaskStatus.FAILED
            task.exit_code = -1
            task.finished_at = time.monotonic()
            with self._lock:
                self._tasks[task_id] = task
            _log.error("Failed to spawn %s: %s", command, exc)
            _hint_for_script(command)
            return task
        except Exception as exc:
            task.status    = TaskStatus.FAILED
            task.exit_code = -1
            task.finished_at = time.monotonic()
            with self._lock:
                self._tasks[task_id] = task
            _log.error("Failed to spawn %s: %s", command, exc)
            return task

        with self._lock:
            self._tasks[task_id] = task
            self._procs[task_id] = proc

        # reader thread drains stdout and enforces the timeout
        t = threading.Thread(
            target=self._reader,
            args=(task_id, proc, timeout, on_line, on_finish),
            daemon=True,
            name=f"ilx-reader-{task_id}",
        )
        t.start()
        # separate stderr drain thread so the child never blocks on a full pipe
        if proc.stderr is not None:
            t_err = threading.Thread(
                target=self._drain_stderr,
                args=(task_id, proc),
                daemon=True,
                name=f"ilx-stderr-{task_id}",
            )
            t_err.start()
        return task

    def spawn_blocking(
        self,
        command:   list[str],
        label:     str = "",
        cwd:       str | None = None,
        timeout:   int | None = None,
        on_line:   Callable[[str], None] | None = None,
        env:       dict | None = None,
    ) -> ManagedTask:
        """Spawn and block until the task finishes. Returns completed ManagedTask."""
        done = threading.Event()
        task_ref: list[ManagedTask] = []

        def _on_finish(t: ManagedTask) -> None:
            task_ref.append(t)
            done.set()

        task = self.spawn(command, label=label, cwd=cwd, timeout=timeout,
                          on_line=on_line, on_finish=_on_finish, env=env)

        if task.status not in (TaskStatus.RUNNING, TaskStatus.QUEUED):
            return task  # failed to start

        wait_timeout = (timeout or 0) + 10 if timeout else None
        done.wait(timeout=wait_timeout)
        return task_ref[0] if task_ref else task

    def kill(self, task_id: str | None = None) -> bool:
        """Kill task by ID (entire process tree), or the most-recently-started
        running task if *task_id* is None."""
        with self._lock:
            tid = task_id or self._latest_running()
            if tid is None:
                return False
            proc = self._procs.get(tid)
            task = self._tasks.get(tid)
            if proc is None or task is None or task.status != TaskStatus.RUNNING:
                return False

        return self._kill_proc(tid, proc)

    def _kill_proc(self, tid: str, proc: subprocess.Popen) -> bool:
        try:
            if sys.platform == "win32":
                # taskkill /T kills the entire process tree, /F forces immediate kill
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                # send SIGTERM to the whole process group first
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    pass  # already gone

                # escalate to SIGKILL after 5s if the process is still alive
                def _escalate():
                    time.sleep(5)
                    try:
                        pgid = os.getpgid(proc.pid)
                        if proc.poll() is None:
                            os.killpg(pgid, signal.SIGKILL)
                            _log.info("Escalated to SIGKILL for task %s (PID %s)", tid, proc.pid)
                    except (ProcessLookupError, OSError):
                        pass

                threading.Thread(target=_escalate, daemon=True).start()

            _log.info("Sent kill to task %s (PID %s)", tid, proc.pid)
            return True
        except Exception as exc:
            _log.warning("Kill failed for task %s: %s", tid, exc)
            return False

    def kill_all(self) -> int:
        """Kill all running tasks. Returns count killed."""
        with self._lock:
            running = [tid for tid, t in self._tasks.items()
                       if t.status == TaskStatus.RUNNING]
        killed = 0
        for tid in running:
            if self.kill(tid):
                killed += 1
        return killed

    def running_tasks(self) -> list[ManagedTask]:
        """Return tasks that are RUNNING or QUEUED."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status in (TaskStatus.RUNNING, TaskStatus.QUEUED)
            ]

    def all_tasks(self, limit: int = 20) -> list[ManagedTask]:
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda t: t.started_at, reverse=True)
            return tasks[:limit]

    def get(self, task_id: str) -> ManagedTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def tail(self, task_id: str, n: int = 20) -> list[str]:
        with self._lock:
            t = self._tasks.get(task_id)
            return list(t.output_tail)[-n:] if t else []

    def status_report(self) -> list[str]:
        """Return human-readable status lines for /tasks command."""
        tasks = self.all_tasks(20)
        if not tasks:
            return ["  No tasks recorded yet."]
        lines: list[str] = []
        running  = [t for t in tasks if t.status in (TaskStatus.RUNNING, TaskStatus.QUEUED)]
        finished = [t for t in tasks if t.status not in (TaskStatus.RUNNING, TaskStatus.QUEUED)]
        if running:
            lines.append("  RUNNING/QUEUED:")
            for t in running:
                lines.append(f"    {t.status_line()}")
        if finished:
            lines.append("  RECENT:")
            for t in finished[:10]:
                lines.append(f"    {t.status_line()}")
        return lines

    def shutdown(self, drain: bool = True, timeout: float = 10.0) -> None:
        """Drain or force-kill all tasks and block new submissions.

        If *drain* is True, waits up to *timeout* seconds for running tasks to
        finish naturally before force-killing them.
        After this call, spawn() raises RuntimeError.
        """
        with self._lock:
            self._shutting_down = True
            # drop everything waiting in the queue — no point starting them
            queued_ids = [item.task_id for item in self._queue]
            self._queue.clear()
            for qid in queued_ids:
                t = self._tasks.get(qid)
                if t and t.status == TaskStatus.QUEUED:
                    t.status = TaskStatus.KILLED
                    t.finished_at = time.monotonic()

        if drain:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                with self._lock:
                    still_running = [
                        t for t in self._tasks.values() if t.status == TaskStatus.RUNNING
                    ]
                if not still_running:
                    break
                time.sleep(0.1)

        self.kill_all()

    def save_registry(self, limit: int = 50) -> None:
        """Persist the last N completed task records to ~/.ilx_cli/tasks.json."""
        import json
        tasks_file = Path.home() / ".ilx_cli" / "tasks.json"
        tasks_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            records = [
                {
                    "task_id":   t.task_id,
                    "label":     t.label,
                    "command":   t.command,
                    "status":    t.status.value,
                    "exit_code": t.exit_code,
                    "elapsed":   round(t.elapsed, 2),
                    "pid":       t.pid,
                }
                for t in sorted(self._tasks.values(), key=lambda x: x.started_at, reverse=True)
                if t.status.value not in ("running", "queued")
            ][:limit]
        try:
            tasks_file.write_text(json.dumps(records, indent=2), encoding="utf-8")
        except OSError as exc:
            _log.warning("Could not save task registry: %s", exc)

    def load_registry(self) -> int:
        """Load prior completed task records from disk into memory. Returns count."""
        import json
        tasks_file = Path.home() / ".ilx_cli" / "tasks.json"
        if not tasks_file.exists():
            return 0
        try:
            records = json.loads(tasks_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        loaded = 0
        with self._lock:
            for rec in records:
                tid = rec.get("task_id", "")
                if tid and tid not in self._tasks:
                    t = ManagedTask(
                        task_id=tid,
                        label=rec.get("label", ""),
                        command=rec.get("command", []),
                        cwd=None,
                    )
                    t.status    = TaskStatus(rec.get("status", "completed"))
                    t.exit_code = rec.get("exit_code")
                    t.pid       = rec.get("pid")
                    t.finished_at = t.started_at  # approximate
                    self._tasks[tid] = t
                    loaded += 1
        return loaded

    # ── internal ──────────────────────────────────────────────────────────────

    def _next_id(self) -> str:
        with self._lock:
            tid = f"T{ProcessSupervisor._NEXT_ID:04d}"
            ProcessSupervisor._NEXT_ID += 1
            return tid

    def _latest_running(self) -> str | None:
        running = [t for t in self._tasks.values() if t.status == TaskStatus.RUNNING]
        if not running:
            return None
        return max(running, key=lambda t: t.started_at).task_id

    def _on_task_done(self, finished_task_id: str) -> None:
        # pop the next item from the queue and start it now that a slot is free
        with self._lock:
            if not self._queue or self._shutting_down:
                return
            item = self._queue.popleft()

        _log.info("Starting queued task %s after %s finished", item.task_id, finished_task_id)
        self._launch(
            item.task_id,
            item.command,
            item.label,
            item.cwd,
            item.timeout,
            item.on_line,
            item.on_finish,
            item.env,
        )

    def _reader(
        self,
        task_id:   str,
        proc:      subprocess.Popen,
        timeout:   int | None,
        on_line:   Callable[[str], None] | None,
        on_finish: Callable[[ManagedTask], None] | None,
    ) -> None:
        deadline      = time.monotonic() + timeout if timeout else None
        warn_at       = time.monotonic() + timeout * 0.8 if timeout else None
        timed_out     = False
        warned        = False

        assert proc.stdout is not None
        try:
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                with self._lock:
                    task = self._tasks[task_id]
                    task.output_tail.append(line)  # deque(maxlen=100) evicts automatically
                if on_line:
                    try:
                        on_line(line)
                    except Exception as exc:
                        _log.warning("Supervisor on_line callback error: %s", exc)

                now = time.monotonic()

                # warn once at 80% of the timeout so the user isn't caught off guard
                if warn_at and not warned and now >= warn_at:
                    warned = True
                    with self._lock:
                        task = self._tasks[task_id]
                        elapsed = now - task.started_at
                        warn_msg = (
                            f"[ILX] Approaching timeout ({elapsed:.0f}s/{timeout}s)"
                            " — will terminate soon"
                        )
                        task.output_tail.append(warn_msg)
                    _log.warning("Task %s approaching timeout (%s/%ss)", task_id, f"{elapsed:.0f}", timeout)

                if deadline and now > deadline:
                    timed_out = True
                    _log.warning("Task %s exceeded timeout, killing", task_id)
                    self._kill_proc(task_id, proc)
                    break
        except Exception as exc:
            _log.debug("Reader error for task %s: %s", task_id, exc)
        finally:
            try:
                proc.stdout.close()
            except Exception as exc:
                _log.debug("Supervisor stdout close error for task %s: %s", task_id, exc)

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._kill_proc(task_id, proc)

        exit_code = proc.returncode
        with self._lock:
            task = self._tasks[task_id]
            task.exit_code   = exit_code
            task.finished_at = time.monotonic()
            if timed_out:
                task.status = TaskStatus.TIMEOUT
            elif exit_code == 0:
                task.status = TaskStatus.COMPLETED
            elif exit_code == -9 or exit_code == -15:
                task.status = TaskStatus.KILLED
            else:
                task.status = TaskStatus.FAILED
            self._procs.pop(task_id, None)

        try:
            self.save_registry()
        except Exception as exc:
            _log.warning("Supervisor task registry save failed for task %s: %s", task_id, exc)

        if on_finish:
            try:
                on_finish(task)
            except Exception as exc:
                _log.warning("Supervisor on_finish callback error for task %s: %s", task_id, exc)

        # start next queued task now that this one is done
        self._on_task_done(task_id)

        # record crashes for non-zero exits that aren't user-initiated kills
        if exit_code not in (0, None) and not timed_out:
            _kill_codes = {-9, -15, 130, 137}
            if exit_code not in _kill_codes:
                try:
                    from app.core import crash_db
                    snippet = "\n".join(list(task.output_tail)[-20:])
                    crash_db.record(" ".join(task.command), exit_code, snippet)
                except Exception as exc:
                    _log.warning("Supervisor crash_db record failed for task %s: %s", task_id, exc)

    def _drain_stderr(self, task_id: str, proc: subprocess.Popen) -> None:
        # keep reading stderr so the child never blocks on a full pipe
        # lines are appended to output_tail so they show up alongside stdout in /run
        if proc.stderr is None:
            return
        try:
            for raw_line in proc.stderr:
                line = raw_line.rstrip()
                with self._lock:
                    task = self._tasks.get(task_id)
                    if task is not None:
                        task.output_tail.append(line)  # deque(maxlen=100) evicts automatically
        except Exception as exc:
            _log.debug("Supervisor stderr drain error for task %s: %s", task_id, exc)
        finally:
            try:
                proc.stderr.close()
            except Exception:
                pass


# module-level singleton — import and use directly
supervisor = ProcessSupervisor()
