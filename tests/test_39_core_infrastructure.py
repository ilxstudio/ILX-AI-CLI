"""Core infrastructure tests — test_39_core_infrastructure.

Covers json_store.py and process_runner.py.

All json_store tests redirect Path.home() so no files are written to ~/.ilx_cli/.

Copyright 2026 ILX Studio — MIT License
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ===========================================================================
# json_store.py tests
# ===========================================================================

def _isolated_store(tmp_path: Path):
    """Return a fresh JsonStore backed by a tmp_path file (not ~/.ilx_cli/)."""
    from app.core.json_store import JsonStore

    store_path = tmp_path / "config.json"
    return JsonStore(path=store_path)


# ---------------------------------------------------------------------------
# 1. test_json_store_creates_file_on_first_use
# ---------------------------------------------------------------------------

def test_json_store_creates_file_on_first_use(tmp_path):
    """setValue() creates the backing JSON file when it doesn't yet exist."""
    store = _isolated_store(tmp_path)
    store_path = store.path

    assert not store_path.exists(), "Pre-condition: file must not exist before first write"

    store.setValue("greeting", "hello")

    assert store_path.exists(), "setValue() must create the backing file"
    data = json.loads(store_path.read_text(encoding="utf-8"))
    assert data.get("greeting") == "hello"


# ---------------------------------------------------------------------------
# 2. test_json_store_round_trip_types
# ---------------------------------------------------------------------------

def test_json_store_round_trip_types(tmp_path):
    """string, int, float, bool, and list values all survive a setValue/value cycle."""
    store = _isolated_store(tmp_path)

    cases = [
        ("str_key",   "hello world"),
        ("int_key",   42),
        ("float_key", 3.14),
        ("bool_key",  True),
        ("list_key",  [1, "two", 3.0]),
    ]

    for key, value in cases:
        store.setValue(key, value)

    # Re-open from disk to ensure we're not reading from the in-memory cache
    from app.core.json_store import JsonStore
    store2 = JsonStore(path=store.path)

    failures = []
    for key, expected in cases:
        got = store2.value(key)
        if got != expected:
            failures.append(f"{key}: expected={expected!r}, got={got!r}")

    assert not failures, f"Round-trip failures: {failures}"


# ---------------------------------------------------------------------------
# 3. test_json_store_default_on_missing_key
# ---------------------------------------------------------------------------

def test_json_store_default_on_missing_key(tmp_path):
    """value() returns the default when the key is absent from the store."""
    store = _isolated_store(tmp_path)

    result = store.value("nonexistent_key", default="fallback")

    assert result == "fallback", f"Expected 'fallback', got {result!r}"


# ---------------------------------------------------------------------------
# 4. test_json_store_overwrite
# ---------------------------------------------------------------------------

def test_json_store_overwrite(tmp_path):
    """Writing the same key twice returns the latest value."""
    store = _isolated_store(tmp_path)

    store.setValue("counter", 1)
    store.setValue("counter", 99)

    result = store.value("counter")
    assert result == 99, f"Expected 99 after overwrite, got {result!r}"


# ---------------------------------------------------------------------------
# 5. test_json_store_corrupt_file_falls_back_to_default
# ---------------------------------------------------------------------------

def test_json_store_corrupt_file_falls_back_to_default(tmp_path):
    """value() returns the default without raising when the backing file is invalid JSON."""
    store_path = tmp_path / "config.json"
    store_path.write_text("{not: valid json!!", encoding="utf-8")

    from app.core.json_store import JsonStore

    # Loading a corrupt file must not raise
    store = JsonStore(path=store_path)
    result = store.value("anything", default="safe_default")

    assert result == "safe_default", (
        f"Expected 'safe_default' for corrupt file, got {result!r}"
    )


# ===========================================================================
# process_runner.py tests
# ===========================================================================

# ---------------------------------------------------------------------------
# 6. test_process_runner_returns_stdout
# ---------------------------------------------------------------------------

def test_process_runner_returns_stdout():
    """run() captures stdout of a simple Python print command."""
    from app.core import process_runner

    result = process_runner.run(
        [sys.executable, "-c", "print('hello_ilx')"]
    )

    assert result.ok, f"Expected ok=True, returncode={result.returncode}, stderr={result.stderr!r}"
    assert "hello_ilx" in result.stdout, (
        f"Expected 'hello_ilx' in stdout, got: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# 7. test_process_runner_nonzero_exit
# ---------------------------------------------------------------------------

def test_process_runner_nonzero_exit():
    """run() sets ok=False when the process exits with a non-zero code."""
    from app.core import process_runner

    result = process_runner.run(
        [sys.executable, "-c", "raise SystemExit(1)"]
    )

    assert not result.ok, "ok must be False for non-zero exit"
    assert result.returncode == 1, f"Expected returncode=1, got {result.returncode}"


# ---------------------------------------------------------------------------
# 8. test_process_runner_timeout
# ---------------------------------------------------------------------------

def test_process_runner_timeout():
    """run() handles a command that exceeds timeout gracefully (ok=False, no raise)."""
    from app.core import process_runner

    # timeout=1 second; sleep 10 will be killed
    result = process_runner.run(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        timeout=1,
    )

    assert not result.ok, "ok must be False when the command times out"
    assert result.returncode == -1, (
        f"Expected returncode=-1 for timeout, got {result.returncode}"
    )
    assert "timed out" in result.stderr.lower() or "timeout" in result.stderr.lower(), (
        f"Expected timeout message in stderr, got: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# 9. test_process_runner_sanitized_env_strips_api_key
# ---------------------------------------------------------------------------

@pytest.mark.security
def test_process_runner_sanitized_env_strips_api_key(tmp_path):
    """When a sanitized env dict is passed, OPENAI_API_KEY does not reach the subprocess."""
    from app.core import process_runner, hooks as _hooks
    import os

    # Build a sanitized env (as hooks.py does) with a poisoned os.environ
    poison = {"OPENAI_API_KEY": "sk-test-secret", "PATH": os.environ.get("PATH", "")}
    with patch.dict(os.environ, poison):
        sanitized = _hooks._sanitized_env()

    assert "OPENAI_API_KEY" not in sanitized, (
        "OPENAI_API_KEY must be stripped by _sanitized_env()"
    )

    # Run a child process with the sanitized env; confirm the key is absent there too
    out_path = tmp_path / "env_dump.json"
    result = process_runner.run(
        [
            sys.executable, "-c",
            f"import os, json; "
            f"open({str(out_path)!r}, 'w').write(json.dumps(dict(os.environ)))"
        ],
        env=sanitized,
    )

    assert result.ok, f"Env-dump subprocess failed: {result.stderr!r}"

    child_env = json.loads(out_path.read_text(encoding="utf-8"))
    assert "OPENAI_API_KEY" not in child_env, (
        "OPENAI_API_KEY must not appear in the child process environment"
    )


# ---------------------------------------------------------------------------
# 10. test_process_runner_nonexistent_command
# ---------------------------------------------------------------------------

def test_process_runner_nonexistent_command():
    """run() returns ok=False without raising when the executable doesn't exist."""
    from app.core import process_runner

    result = process_runner.run(["this_command_does_not_exist_ilx_12345"])

    assert not result.ok, "ok must be False for a missing executable"
    assert result.returncode == -1, (
        f"Expected returncode=-1 for missing executable, got {result.returncode}"
    )
    assert result.stderr, "Expected a non-empty error message in stderr"
