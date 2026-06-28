"""Cluster 14 — Process management: Ollama retry, process tree kill, task queue, graceful shutdown.

Tests (all mock-based — no live Ollama or subprocesses required):
  - test_ollama_retry_on_connect_error       : chat() retries 3× on ConnectError then raises
  - test_ollama_no_retry_on_http_error       : chat() raises immediately on HTTPStatusError
  - test_ollama_retry_succeeds_on_second_attempt : first call ConnectError, second succeeds
  - test_cloud_clients_no_retry              : AnthropicClient / OpenAIClient never retry
  - test_supervisor_queue_at_capacity        : tasks 3-5 are queued when limit=2
  - test_supervisor_graceful_shutdown        : shutdown() sets _shutting_down=True
  - test_supervisor_shutdown_rejects_new_tasks : spawn() raises after shutdown()
  - test_task_status_includes_queued         : running_tasks() includes QUEUED tasks
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_ok_ollama_chat_response() -> MagicMock:
    """Return a mock httpx Response that looks like a successful Ollama /api/chat reply."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()  # no-op
    mock_resp.json.return_value = {
        "message": {"content": "hello from ollama"},
        "prompt_eval_count": 10,
        "eval_count": 5,
    }
    return mock_resp


def _make_ok_ollama_generate_response() -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "response": "generated text",
        "prompt_eval_count": 8,
        "eval_count": 4,
    }
    return mock_resp


def _connect_error() -> Exception:
    """Build a ConnectError without needing a real request object."""
    import httpx
    return httpx.ConnectError("connection refused")


def _http_401() -> Exception:
    """Build an HTTPStatusError (401) without needing a real transport."""
    import httpx
    req = httpx.Request("POST", "http://localhost:11434/api/chat")
    resp = httpx.Response(401, request=req, text="Unauthorized")
    return httpx.HTTPStatusError("401", request=req, response=resp)


# ── OllamaClient retry tests ──────────────────────────────────────────────────

def test_ollama_retry_on_connect_error():
    """chat() retries up to max_retries=3 on ConnectError then raises RuntimeError."""
    import httpx
    from codex.app.llm_client import OllamaClient

    client = OllamaClient(model="llama3", base_url="http://localhost:11434")

    with patch("httpx.post", side_effect=_connect_error()) as mock_post:
        # patch raises the same error every call
        mock_post.side_effect = [_connect_error(), _connect_error(), _connect_error()]
        with pytest.raises((RuntimeError, httpx.ConnectError)):
            client.chat([{"role": "user", "content": "hi"}])

        assert mock_post.call_count == 3, (
            f"Expected exactly 3 httpx.post calls (1 try + 2 retries), got {mock_post.call_count}"
        )


def test_ollama_no_retry_on_http_error():
    """chat() raises immediately on HTTPStatusError — no retry attempted."""
    import httpx
    from codex.app.llm_client import OllamaClient

    client = OllamaClient(model="llama3")

    with patch("httpx.post") as mock_post:
        mock_post.side_effect = _http_401()
        with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
            client.chat([{"role": "user", "content": "hi"}])

        assert mock_post.call_count == 1, (
            f"Expected exactly 1 call (no retry on HTTP error), got {mock_post.call_count}"
        )


def test_ollama_retry_succeeds_on_second_attempt():
    """First call raises ConnectError; second call returns a valid response."""
    from codex.app.llm_client import OllamaClient

    client = OllamaClient(model="llama3")
    ok_resp = _make_ok_ollama_chat_response()

    with patch("httpx.post") as mock_post:
        mock_post.side_effect = [_connect_error(), ok_resp]
        result = client.chat([{"role": "user", "content": "ping"}])

    assert result == "hello from ollama", f"Unexpected result: {result!r}"
    assert mock_post.call_count == 2


def test_ollama_generate_retry_on_connect_error():
    """generate() retries 3× on ConnectError then raises."""
    import httpx
    from codex.app.llm_client import OllamaClient

    client = OllamaClient(model="llama3")

    with patch("httpx.post") as mock_post:
        mock_post.side_effect = [_connect_error(), _connect_error(), _connect_error()]
        with pytest.raises((RuntimeError, httpx.ConnectError)):
            client.generate("write me a poem")

        assert mock_post.call_count == 3


def test_ollama_generate_succeeds_on_retry():
    """generate() first call fails with ConnectError, second succeeds."""
    from codex.app.llm_client import OllamaClient

    client = OllamaClient(model="llama3")
    ok_resp = _make_ok_ollama_generate_response()

    with patch("httpx.post") as mock_post:
        mock_post.side_effect = [_connect_error(), ok_resp]
        result = client.generate("hello")

    assert result == "generated text"
    assert mock_post.call_count == 2


# ── Cloud client no-retry tests ───────────────────────────────────────────────

def test_cloud_clients_no_retry():
    """AnthropicClient and OpenAIClient must NOT retry — fail fast on ConnectError."""
    import httpx
    from codex.app.llm_client import AnthropicClient, OpenAIClient

    for ClientClass, extra in [
        (AnthropicClient, {"api_key": "test-key"}),
        (OpenAIClient,    {"api_key": "test-key"}),
    ]:
        client = ClientClass(**extra)
        # Clients use a persistent httpx.Client instance (self._client.post)
        # so we patch the instance's post method directly.
        with patch.object(client._client, "post", side_effect=_connect_error()) as mock_post:
            with pytest.raises((RuntimeError, httpx.ConnectError)):
                client.chat([{"role": "user", "content": "hi"}])

            assert mock_post.call_count == 1, (
                f"{ClientClass.__name__} made {mock_post.call_count} calls — "
                "cloud clients must not retry"
            )


# ── Supervisor queue tests ────────────────────────────────────────────────────

def _make_supervisor(max_concurrent: int = 2):
    """Return a fresh ProcessSupervisor with a small concurrency cap."""
    from app.core.supervisor import ProcessSupervisor
    return ProcessSupervisor(max_concurrent=max_concurrent)


def _fake_popen(pid: int = 9999) -> MagicMock:
    """Mock subprocess.Popen so no real process is created."""
    mock_proc = MagicMock()
    mock_proc.pid = pid
    mock_proc.stdout = iter([])           # empty stdout
    mock_proc.returncode = 0
    mock_proc.poll.return_value = None    # appears alive initially
    mock_proc.wait.return_value = 0
    return mock_proc


def test_supervisor_queue_at_capacity():
    """When max_concurrent=2 and 5 tasks are submitted, only 2 run and 3 are queued."""
    from app.core.supervisor import TaskStatus

    sup = _make_supervisor(max_concurrent=2)

    launched_tasks = []

    def _patched_launch(task_id, command, label, cwd, timeout, on_line, on_finish, env):
        """Replace _launch so no real subprocess is created."""
        from app.core.supervisor import ManagedTask, TaskStatus
        task = ManagedTask(
            task_id=task_id,
            label=label or " ".join(command[:3]),
            command=command,
            cwd=cwd,
            status=TaskStatus.RUNNING,
        )
        with sup._lock:
            sup._tasks[task_id] = task
        launched_tasks.append(task_id)
        return task

    tasks = []
    with patch.object(sup, "_launch", side_effect=_patched_launch):
        for i in range(5):
            t = sup.spawn(["echo", str(i)], label=f"task-{i}")
            tasks.append(t)

    running = [t for t in tasks if t.status == TaskStatus.RUNNING]
    queued  = [t for t in tasks if t.status == TaskStatus.QUEUED]

    assert len(running) == 2, f"Expected 2 RUNNING tasks, got {len(running)}: {[t.task_id for t in running]}"
    assert len(queued)  == 3, f"Expected 3 QUEUED tasks, got {len(queued)}: {[t.task_id for t in queued]}"
    assert len(sup._queue) == 3, f"Queue depth should be 3, got {len(sup._queue)}"


def test_task_status_includes_queued():
    """running_tasks() returns both RUNNING and QUEUED tasks."""
    from app.core.supervisor import TaskStatus

    sup = _make_supervisor(max_concurrent=1)

    def _patched_launch(task_id, command, label, cwd, timeout, on_line, on_finish, env):
        from app.core.supervisor import ManagedTask, TaskStatus
        task = ManagedTask(
            task_id=task_id,
            label=label or " ".join(command[:3]),
            command=command,
            cwd=cwd,
            status=TaskStatus.RUNNING,
        )
        with sup._lock:
            sup._tasks[task_id] = task
        return task

    with patch.object(sup, "_launch", side_effect=_patched_launch):
        sup.spawn(["echo", "1"], label="task-1")
        sup.spawn(["echo", "2"], label="task-2")

    active = sup.running_tasks()
    statuses = {t.status for t in active}
    assert TaskStatus.RUNNING in statuses, "running_tasks() should include RUNNING"
    assert TaskStatus.QUEUED  in statuses, "running_tasks() should include QUEUED"
    assert len(active) == 2


# ── Graceful shutdown tests ───────────────────────────────────────────────────

def test_supervisor_graceful_shutdown():
    """shutdown() sets _shutting_down=True and kills running tasks."""
    from app.core.supervisor import TaskStatus

    sup = _make_supervisor(max_concurrent=4)

    # Inject a fake running task so kill_all has something to do.
    from app.core.supervisor import ManagedTask
    fake_task = ManagedTask(
        task_id="T0001",
        label="fake",
        command=["sleep", "999"],
        cwd=None,
        status=TaskStatus.RUNNING,
    )
    with sup._lock:
        sup._tasks["T0001"] = fake_task

    killed = []
    original_kill = sup.kill

    def _fake_kill(tid=None):
        killed.append(tid)
        with sup._lock:
            t = sup._tasks.get(tid or "T0001")
            if t:
                t.status = TaskStatus.KILLED
        return True

    with patch.object(sup, "kill", side_effect=_fake_kill):
        sup.shutdown(drain=False, timeout=0)

    assert sup._shutting_down is True, "_shutting_down must be True after shutdown()"
    # Queue must be cleared.
    assert len(sup._queue) == 0, "Queue should be empty after shutdown"


def test_supervisor_shutdown_rejects_new_tasks():
    """After shutdown(), calling spawn() raises RuntimeError."""
    sup = _make_supervisor(max_concurrent=4)
    sup.shutdown(drain=False, timeout=0)

    with pytest.raises(RuntimeError, match="shutting down"):
        sup.spawn(["echo", "too late"])


def test_supervisor_shutdown_clears_queue():
    """Queued-but-not-started tasks are cancelled when shutdown() is called."""
    from app.core.supervisor import TaskStatus

    sup = _make_supervisor(max_concurrent=1)

    def _patched_launch(task_id, command, label, cwd, timeout, on_line, on_finish, env):
        from app.core.supervisor import ManagedTask, TaskStatus
        task = ManagedTask(
            task_id=task_id,
            label=label or " ".join(command[:3]),
            command=command,
            cwd=cwd,
            status=TaskStatus.RUNNING,
        )
        with sup._lock:
            sup._tasks[task_id] = task
        return task

    with patch.object(sup, "_launch", side_effect=_patched_launch):
        sup.spawn(["echo", "1"], label="task-1")  # runs immediately
        sup.spawn(["echo", "2"], label="task-2")  # queued

    assert len(sup._queue) == 1, "One task should be in the queue before shutdown"

    sup.shutdown(drain=False, timeout=0)

    assert len(sup._queue) == 0, "Queue must be empty after shutdown"


# ── TaskStatus enum ───────────────────────────────────────────────────────────

def test_task_status_has_queued():
    """TaskStatus enum must include a QUEUED value."""
    from app.core.supervisor import TaskStatus
    assert hasattr(TaskStatus, "QUEUED"), "TaskStatus is missing QUEUED member"
    assert TaskStatus.QUEUED.value == "queued"
