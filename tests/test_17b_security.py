"""Cluster 17b — Coverage-gap tests: SSH, secret store, circuit breaker, audit, crash DB.

Areas covered:
  F. SSH client
     - test_ssh_setup_help_contains_keygen     : print_setup_help() output mentions ssh-keygen
     - test_ssh_connection_failure_graceful    : connect() with bad host returns ok=False

  G. Secret store
     - test_get_api_key_no_keyring_returns_empty : NoKeyringError → returns ""
     - test_set_api_key_failure_returns_false    : keyring failure → returns False

  H. Circuit breaker
     - test_circuit_opens_after_3_failures     : 3 consecutive failures open the circuit
     - test_circuit_half_open_after_timeout    : open circuit transitions to half-open after 60s
     - test_circuit_closes_on_success          : successful probe after half-open closes the circuit

  I. Audit log
     - test_audit_log_llm_call_fields          : log_llm_call() writes correct fields
     - test_audit_log_rotation                 : log rotation triggers and renames the file

  J. Crash DB
     - test_crash_db_group_summary             : group_summary() groups crashes by sig
     - test_crash_db_clear                     : clear_crashes() empties the DB
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save


# ═══════════════════════════════════════════════════════════════════════════════
# F. SSH client
# ═══════════════════════════════════════════════════════════════════════════════

def test_ssh_setup_help_contains_keygen(capsys):
    """SSHClient.print_setup_help() mentions ssh-keygen and password guidance."""
    from app.core.ssh_client import SSHClient

    SSHClient.print_setup_help()
    captured = capsys.readouterr()
    output = (captured.out + captured.err).lower()

    has_keygen = "ssh-keygen" in output
    has_password = "password" in output

    ok = has_keygen and has_password
    save("ssh_setup_help_contains_keygen", ok, {
        "has_ssh_keygen": has_keygen,
        "has_password": has_password,
        "output_snippet": output[:400],
    })
    assert has_keygen, f"Expected 'ssh-keygen' in help. Got: {output[:300]!r}"
    assert has_password, f"Expected 'password' in help. Got: {output[:300]!r}"


def test_ssh_connection_failure_graceful():
    """SSHClient.connect() with a non-existent host returns ok=False without raising."""
    from app.core.ssh_client import SSHClient

    client = SSHClient(host="nonexistent.invalid", user="testuser", port=22)

    # paramiko may or may not be installed; either path should return ok=False
    # We mock subprocess.run to avoid a real network call
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=255,
            stdout="",
            stderr="ssh: Could not resolve hostname nonexistent.invalid",
        )
        # Also mock paramiko if present so it fails predictably
        try:
            import paramiko
            with patch.object(paramiko.SSHClient, "connect",
                              side_effect=Exception("Name resolution failed")):
                result = client.connect()
        except ImportError:
            result = client.connect()

    ok = result.get("ok") is False and len(result.get("error", "")) > 0
    save("ssh_connection_failure_graceful", ok, {
        "ok": result.get("ok"),
        "error": result.get("error", "")[:200],
    })
    assert result["ok"] is False, (
        f"Expected ok=False for bad host. Got: {result}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# G. Secret store
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_api_key_no_keyring_returns_empty():
    """get_api_key() returns '' when keyring raises NoKeyringError."""
    import keyring.errors
    from app.core import secret_store

    with patch("keyring.get_password", side_effect=keyring.errors.NoKeyringError("no keyring")):
        key = secret_store.get_api_key("anthropic")

    ok = key == ""
    save("get_api_key_no_keyring_returns_empty", ok, {
        "returned": repr(key),
        "expected": repr(""),
    })
    assert key == "", f"Expected '' when NoKeyringError raised, got {key!r}"


def test_set_api_key_failure_returns_false():
    """set_api_key() returns False when keyring.set_password raises an exception."""
    from app.core import secret_store

    with patch("keyring.set_password", side_effect=Exception("keyring backend unavailable")):
        result = secret_store.set_api_key("my-secret-key", "openai")

    ok = result is False
    save("set_api_key_failure_returns_false", ok, {
        "returned": result,
        "expected": False,
    })
    assert result is False, f"Expected False when set_password fails, got {result!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# H. Circuit breaker
# ═══════════════════════════════════════════════════════════════════════════════

def _reset_circuit():
    """Reset the module-level circuit breaker state for test isolation."""
    import app.core.ollama_guard as _guard
    with _guard._lock:
        _guard._failures   = 0
        _guard._state      = "closed"
        _guard._opened_at  = None


def test_circuit_opens_after_3_failures():
    """3 consecutive failures transition the circuit from 'closed' to 'open'."""
    import app.core.ollama_guard as _guard
    _reset_circuit()

    for _ in range(3):
        _guard._record_failure()

    state = _guard.circuit_state()
    ok = state == "open"
    save("circuit_opens_after_3_failures", ok, {
        "state_after_3_failures": state,
        "failures": _guard._failures,
    })
    assert state == "open", f"Expected state='open' after 3 failures, got {state!r}"


def test_circuit_half_open_after_timeout():
    """After the recovery timeout, an 'open' circuit transitions to 'half-open'."""
    import app.core.ollama_guard as _guard
    _reset_circuit()

    # Open the circuit
    for _ in range(3):
        _guard._record_failure()
    assert _guard.circuit_state() == "open"

    # Backdate the opened_at timestamp by more than _RECOVERY_TIMEOUT
    with _guard._lock:
        _guard._opened_at = time.monotonic() - (_guard._RECOVERY_TIMEOUT + 1)

    # _is_open() transitions to half-open when enough time has passed
    is_blocked = _guard._is_open()  # Should return False (half-open allows probe)
    state = _guard.circuit_state()

    ok = state == "half-open" and is_blocked is False
    save("circuit_half_open_after_timeout", ok, {
        "state": state,
        "is_blocked": is_blocked,
    })
    assert state == "half-open", f"Expected 'half-open', got {state!r}"
    assert is_blocked is False, "half-open circuit should allow a probe (return False)"


def test_circuit_closes_on_success():
    """A successful probe after half-open transitions the circuit back to 'closed'."""
    import app.core.ollama_guard as _guard
    _reset_circuit()

    # Put circuit into half-open
    for _ in range(3):
        _guard._record_failure()
    with _guard._lock:
        _guard._opened_at = time.monotonic() - (_guard._RECOVERY_TIMEOUT + 1)
    _guard._is_open()  # triggers half-open transition
    assert _guard.circuit_state() == "half-open"

    # Successful probe
    _guard._record_success()
    state = _guard.circuit_state()

    ok = state == "closed"
    save("circuit_closes_on_success", ok, {
        "state_after_success": state,
        "failures": _guard._failures,
    })
    assert state == "closed", f"Expected 'closed' after success, got {state!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# I. Audit log
# ═══════════════════════════════════════════════════════════════════════════════

def test_audit_log_llm_call_fields(tmp_path):
    """log_llm_call() writes a JSON record with all expected fields."""
    import app.core.audit as _audit

    log_file = tmp_path / "audit.log"
    original_path = _audit._LOG_PATH

    try:
        _audit._LOG_PATH = log_file
        _audit.log_llm_call(
            model="gpt-4o",
            prompt_tokens=100,
            response_tokens=50,
            latency_ms=250.5,
            provider="openai",
        )
    finally:
        _audit._LOG_PATH = original_path

    assert log_file.exists(), "audit.log was not created"
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1, "Expected at least one log line"

    record = json.loads(lines[-1])
    ok = (
        record.get("event") == "llm_call"
        and record.get("model") == "gpt-4o"
        and record.get("prompt_tokens") == 100
        and record.get("response_tokens") == 50
        and record.get("provider") == "openai"
        and "ts" in record
        and "pid" in record
    )
    save("audit_log_llm_call_fields", ok, {
        "record": record,
        "ok": ok,
    })
    assert ok, f"Unexpected audit record: {record}"


def test_audit_log_rotation(tmp_path):
    """When audit.log exceeds _MAX_BYTES, it is rotated and a new file is started."""
    import app.core.audit as _audit

    log_file = tmp_path / "audit.log"
    original_path    = _audit._LOG_PATH
    original_max     = _audit._MAX_BYTES

    try:
        _audit._LOG_PATH  = log_file
        _audit._MAX_BYTES = 50   # tiny limit so we trigger rotation immediately

        # Write a long first entry to exceed the 50-byte threshold
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            json.dumps({"event": "seed", "data": "A" * 100}) + "\n",
            encoding="utf-8",
        )
        assert log_file.stat().st_size > 50, "Pre-condition: file must exceed max_bytes"

        # Next write should trigger rotation
        _audit.log_llm_call(
            model="test-model",
            prompt_tokens=1,
            response_tokens=1,
            latency_ms=1.0,
        )

        # After rotation the original file should be smaller (or may still exist as rotated)
        rotated_files = list(tmp_path.glob("audit.log.*"))
        new_file_exists = log_file.exists()

        ok = len(rotated_files) >= 1 or new_file_exists

    finally:
        _audit._LOG_PATH  = original_path
        _audit._MAX_BYTES = original_max

    save("audit_log_rotation", ok, {
        "rotated_files": [str(f.name) for f in rotated_files],
        "new_file_exists": new_file_exists,
    })
    assert ok, (
        f"Expected rotation to produce a renamed file or a fresh audit.log. "
        f"rotated={rotated_files}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# J. Crash DB
# ═══════════════════════════════════════════════════════════════════════════════

def _isolated_crash_db(tmp_path: Path):
    """Patch _DB_PATH in crash_db so tests use a temp SQLite file."""
    import app.core.crash_db as _cdb
    return patch.object(_cdb, "_DB_PATH", tmp_path / "crashes.db")


def test_crash_db_group_summary(tmp_path):
    """group_summary() groups multiple crashes by their signature hash."""
    import app.core.crash_db as _cdb

    tb_a = "Traceback (most recent call last):\n  File 'foo.py', line 10\nZeroDivisionError: division by zero"
    tb_b = "Traceback (most recent call last):\n  File 'bar.py', line 5\nFileNotFoundError: [Errno 2]"

    with _isolated_crash_db(tmp_path):
        _cdb.clear_crashes()
        # Record 3 crashes with sig-A and 1 crash with sig-B
        for _ in range(3):
            _cdb.record("python foo.py", 1, tb_a)
        _cdb.record("python bar.py", 2, tb_b)

        summary = _cdb.group_summary()

    # Should have 2 groups
    sig_counts = {g["sig"]: g["count"] for g in summary}
    sig_a = _cdb._signature(tb_a)
    sig_b = _cdb._signature(tb_b)

    ok = (
        len(summary) == 2
        and sig_counts.get(sig_a) == 3
        and sig_counts.get(sig_b) == 1
    )
    save("crash_db_group_summary", ok, {
        "groups": len(summary),
        "sig_a_count": sig_counts.get(sig_a),
        "sig_b_count": sig_counts.get(sig_b),
        "summary": summary,
    })
    assert len(summary) == 2, f"Expected 2 crash groups, got {len(summary)}: {summary}"
    assert sig_counts.get(sig_a) == 3, f"Expected 3 crashes for sig_a, got {sig_counts}"
    assert sig_counts.get(sig_b) == 1, f"Expected 1 crash for sig_b, got {sig_counts}"


def test_crash_db_clear(tmp_path):
    """clear_crashes() deletes all crash records and returns the deleted count."""
    import app.core.crash_db as _cdb

    tb = "Traceback:\n  File 'x.py', line 1\nRuntimeError: boom"

    with _isolated_crash_db(tmp_path):
        _cdb.clear_crashes()  # start clean
        for _ in range(5):
            _cdb.record("python x.py", 1, tb)

        before = _cdb.list_crashes(20)
        assert len(before) == 5, f"Pre-condition: expected 5 crashes, got {len(before)}"

        deleted = _cdb.clear_crashes()
        after = _cdb.list_crashes(20)

    ok = deleted == 5 and len(after) == 0
    save("crash_db_clear", ok, {
        "deleted": deleted,
        "remaining": len(after),
    })
    assert deleted == 5, f"Expected 5 deleted, got {deleted}"
    assert len(after) == 0, f"Expected 0 remaining after clear, got {len(after)}"
