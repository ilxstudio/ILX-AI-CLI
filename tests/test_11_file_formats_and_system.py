"""Cluster 11 — File formats, sandbox, web fetch, tool builder, SSH, CLI commands.

Tests:
  test_working_folder_read          — read a file inside working_folder via config
  test_sandbox_blocks_outside_path  — safe_resolve() rejects path outside working_folder
  test_pdf_read                     — read_pdf() extracts text (requires pypdf)
  test_docx_read_write              — read/write .docx (requires python-docx)
  test_xlsx_read_write              — read/write .xlsx (requires openpyxl)
  test_png_read                     — read_png() returns dimensions (requires Pillow)
  test_web_fetch_public_url         — fetch_url() returns text for a public URL
  test_web_fetch_ssrf_blocked       — fetch_url() blocks localhost/private IPs
  test_tool_builder_create          — ToolBuilder.create_tool() writes tool with permission
  test_tool_builder_permission_deny — ToolBuilder.create_tool() denied by permission_cb
  test_ssh_help_text                — SSHClient.print_setup_help() prints SSH guide
  test_ssh_parse_user_host          — SSHClient parses user@host correctly
  test_cli_command_python_version   — run 'python --version' via MCP run_command
  test_cli_command_cross_platform   — platform-appropriate list-dir command works
  test_file_converter_missing_lib   — file_converter degrades gracefully when lib absent
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from unittest import mock

import pytest

# ── Project root on path ───────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save  # noqa: E402

# ── Python executable used by CLI runtime ─────────────────────────────────────
import sys as _sys; PYTHON_EXE = _sys.executable

# ── Optional-dependency availability flags ────────────────────────────────────
try:
    import pypdf  # noqa: F401
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    import docx  # noqa: F401  (python-docx exposes the 'docx' package)
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    from PIL import Image  # noqa: F401
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    import paramiko  # noqa: F401
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

# ── Availability flags for optional project modules ───────────────────────────
try:
    from app.core.tool_builder import ToolBuilder  # type: ignore
    HAS_TOOL_BUILDER = True
except (ImportError, ModuleNotFoundError):
    HAS_TOOL_BUILDER = False
    ToolBuilder = None  # type: ignore

try:
    from app.core.ssh_client import SSHClient  # type: ignore
    HAS_SSH_CLIENT = True
except (ImportError, ModuleNotFoundError):
    HAS_SSH_CLIENT = False
    SSHClient = None  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Working-folder read
# ═══════════════════════════════════════════════════════════════════════════════

def test_working_folder_read(tmp_path, cfg):
    """Files inside working_folder are readable through the MCP read_file tool."""
    from app.core.mcp_client import MCPClient

    # Write a sentinel file into tmp_path (our isolated working folder)
    sentinel = tmp_path / "hello.txt"
    sentinel.write_text("ILX working folder read test", encoding="utf-8")

    # Override working folder for this test
    cfg.working_folder = str(tmp_path)

    client = MCPClient(cfg)
    client.register_builtin_tools()

    result = client.call("read_file", {"path": "hello.txt"})

    ok = result.get("success", False)
    save(
        "working_folder_read",
        ok,
        {
            "working_folder": str(tmp_path),
            "result_snippet": str(result.get("result", ""))[:200],
            "error": result.get("error", ""),
        },
    )
    assert ok, f"read_file failed: {result.get('error')}"
    assert "ILX working folder read test" in (result.get("result") or "")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Sandbox — block paths outside working folder
# ═══════════════════════════════════════════════════════════════════════════════

def test_sandbox_blocks_outside_path(tmp_path):
    """safe_resolve() returns None when the path escapes the working folder."""
    from app.utils.file_utils import safe_resolve

    # Attempt path traversal
    escaped = safe_resolve("../../etc/passwd", str(tmp_path))

    ok = escaped is None
    save(
        "sandbox_blocks_outside_path",
        ok,
        {
            "working_folder": str(tmp_path),
            "attempted_path": "../../etc/passwd",
            "resolved": str(escaped),
        },
    )
    assert ok, (
        f"safe_resolve should return None for path-traversal but got: {escaped!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PDF read
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_PYPDF, reason="pypdf not installed")
def test_pdf_read(tmp_path):
    """read_pdf() extracts text from a valid PDF created by reportlab."""
    from app.core.file_converter import read_pdf, write_pdf

    pdf_path = str(tmp_path / "sample.pdf")

    # Create a minimal PDF using write_pdf (requires reportlab) or fallback
    try:
        wr = write_pdf(pdf_path, "Hello PDF world\n\nSecond paragraph.")
        if not wr["ok"]:
            pytest.skip(f"write_pdf failed (reportlab missing?): {wr['error']}")
    except Exception as exc:
        pytest.skip(f"write_pdf raised: {exc}")

    result = read_pdf(pdf_path)

    ok = result["ok"] and "Hello PDF world" in result.get("text", "")
    save(
        "pdf_read",
        ok,
        {
            "pdf_path": pdf_path,
            "pages": result.get("pages", 0),
            "text_snippet": result.get("text", "")[:200],
            "error": result.get("error", ""),
        },
    )
    assert result["ok"], f"read_pdf failed: {result.get('error')}"
    assert "Hello PDF world" in result["text"], (
        f"Expected text not found. Got: {result['text'][:300]!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DOCX read/write
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_DOCX, reason="python-docx not installed")
def test_docx_read_write(tmp_path):
    """write_docx() creates a .docx and read_docx() extracts the text back."""
    from app.core.file_converter import read_docx, write_docx

    docx_path = str(tmp_path / "sample.docx")
    content = "Hello DOCX world\nLine two of the document."

    wr = write_docx(docx_path, content)
    assert wr["ok"], f"write_docx failed: {wr.get('error')}"

    rd = read_docx(docx_path)

    ok = rd["ok"] and "Hello DOCX world" in rd.get("text", "")
    save(
        "docx_read_write",
        ok,
        {
            "docx_path": docx_path,
            "text_snippet": rd.get("text", "")[:300],
            "error": rd.get("error", ""),
        },
    )
    assert rd["ok"], f"read_docx failed: {rd.get('error')}"
    assert "Hello DOCX world" in rd["text"], (
        f"Expected text not found. Got: {rd['text'][:300]!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. XLSX read/write
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl not installed")
def test_xlsx_read_write(tmp_path):
    """write_xlsx() creates an .xlsx and read_xlsx() returns the cell data."""
    from app.core.file_converter import read_xlsx, write_xlsx

    xlsx_path = str(tmp_path / "sample.xlsx")
    data = [["Name", "Score"], ["Alice", 95], ["Bob", 87]]

    wr = write_xlsx(xlsx_path, data)
    assert wr["ok"], f"write_xlsx failed: {wr.get('error')}"

    rd = read_xlsx(xlsx_path)

    # Verify at least the header row is present
    text = rd.get("text", "")
    ok = rd["ok"] and "Name" in text and "Alice" in text
    save(
        "xlsx_read_write",
        ok,
        {
            "xlsx_path": xlsx_path,
            "sheets": list(rd.get("sheets", {}).keys()),
            "text_snippet": text[:300],
            "error": rd.get("error", ""),
        },
    )
    assert rd["ok"], f"read_xlsx failed: {rd.get('error')}"
    assert "Name" in text, f"Header row not found. Got: {text[:300]!r}"
    assert "Alice" in text, f"Data row not found. Got: {text[:300]!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PNG read
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_PILLOW, reason="Pillow not installed")
def test_png_read(tmp_path):
    """write_png() creates a PNG and read_png() returns correct dimensions."""
    from app.core.file_converter import read_png, write_png

    png_path = str(tmp_path / "sample.png")

    wr = write_png(png_path, width=320, height=240, color=(128, 64, 255))
    assert wr["ok"], f"write_png failed: {wr.get('error')}"

    rd = read_png(png_path)

    ok = rd["ok"] and rd.get("width") == 320 and rd.get("height") == 240
    save(
        "png_read",
        ok,
        {
            "png_path": png_path,
            "width": rd.get("width"),
            "height": rd.get("height"),
            "mode": rd.get("mode"),
            "text": rd.get("text", ""),
            "error": rd.get("error", ""),
        },
    )
    assert rd["ok"], f"read_png failed: {rd.get('error')}"
    assert rd["width"] == 320, f"Expected width=320, got {rd['width']}"
    assert rd["height"] == 240, f"Expected height=240, got {rd['height']}"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Web fetch — public URL
# ═══════════════════════════════════════════════════════════════════════════════

def test_web_fetch_public_url():
    """fetch_url() fetches http://example.com and returns HTML text."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("http://example.com", timeout=20)

    # Accept the test even if network is unavailable — but record the outcome
    if not result["ok"]:
        # Network may be unreachable in CI; record as skipped-like (ok=False)
        save(
            "web_fetch_public_url",
            False,
            {
                "url": "http://example.com",
                "error": result.get("error", ""),
                "note": "Network may be unavailable",
            },
        )
        pytest.skip(f"fetch_url failed (network issue?): {result.get('error')}")

    text_blob = (result.get("title", "") + " " + result.get("text", "")).lower()
    ok = "example" in text_blob
    save(
        "web_fetch_public_url",
        ok,
        {
            "url": result.get("url"),
            "title": result.get("title"),
            "text_snippet": result.get("text", "")[:200],
            "error": result.get("error", ""),
        },
    )
    assert ok, (
        f"Expected 'Example' in fetched content. "
        f"Title={result.get('title')!r}, text[:200]={result.get('text','')[:200]!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Web fetch — SSRF blocked
# ═══════════════════════════════════════════════════════════════════════════════

def test_web_fetch_ssrf_blocked():
    """fetch_url() rejects requests to localhost/private addresses."""
    from app.core.web_fetch import fetch_url

    result = fetch_url("http://127.0.0.1/")

    ok = not result["ok"]
    error_msg = result.get("error", "")
    # The error should mention blocking — "Blocked loopback", "SSRF", or "private"
    mentions_block = any(
        kw in error_msg.lower()
        for kw in ("blocked", "ssrf", "private", "loopback", "local")
    )

    save(
        "web_fetch_ssrf_blocked",
        ok and mentions_block,
        {
            "url": "http://127.0.0.1/",
            "ok_returned": result["ok"],
            "error": error_msg,
        },
    )
    assert not result["ok"], (
        "fetch_url should return ok=False for 127.0.0.1 but returned ok=True"
    )
    assert mentions_block, (
        f"Error message should mention blocking but got: {error_msg!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 9. ToolBuilder — create tool (permission granted)
# ═══════════════════════════════════════════════════════════════════════════════

def test_tool_builder_create(tmp_path):
    """ToolBuilder.create_tool() writes a .py file when permission is granted."""
    if not HAS_TOOL_BUILDER:
        save(
            "tool_builder_create",
            False,
            {"note": "app.core.tool_builder not importable"},
        )
        pytest.skip("ToolBuilder module not found (app.core.tool_builder)")

    class _Cfg:
        working_folder = str(tmp_path)

    builder = ToolBuilder(_Cfg())
    result = builder.create_tool(
        "hello_tool",
        "prints hello",
        "print('hello')",
        permission_callback=lambda *_: True,
    )

    tool_file = tmp_path / "tools" / "hello_tool.py"
    ok = result.get("ok", False) and tool_file.exists()
    save(
        "tool_builder_create",
        ok,
        {
            "tool_file": str(tool_file),
            "file_exists": tool_file.exists(),
            "result": result,
        },
    )
    assert result.get("ok"), f"create_tool returned ok=False: {result}"
    assert tool_file.exists(), f"Tool file not created at {tool_file}"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. ToolBuilder — permission denied
# ═══════════════════════════════════════════════════════════════════════════════

def test_tool_builder_permission_deny(tmp_path):
    """ToolBuilder.create_tool() does NOT write a file when callback returns False."""
    if not HAS_TOOL_BUILDER:
        save(
            "tool_builder_permission_deny",
            False,
            {"note": "app.core.tool_builder not importable"},
        )
        pytest.skip("ToolBuilder module not found (app.core.tool_builder)")

    class _Cfg:
        working_folder = str(tmp_path)

    builder = ToolBuilder(_Cfg())
    result = builder.create_tool(
        "secret_tool",
        "should not be created",
        "print('secret')",
        permission_callback=lambda *_: False,
    )

    tool_file = tmp_path / "tools" / "secret_tool.py"
    ok = not result.get("ok", True) and not tool_file.exists()
    save(
        "tool_builder_permission_deny",
        ok,
        {
            "tool_file": str(tool_file),
            "file_exists": tool_file.exists(),
            "result": result,
        },
    )
    assert not result.get("ok", True), (
        "create_tool should return ok=False when permission is denied"
    )
    assert not tool_file.exists(), (
        f"Tool file should NOT be created when permission is denied, but found {tool_file}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 11. SSH help text
# ═══════════════════════════════════════════════════════════════════════════════

def test_ssh_help_text(capsys):
    """SSHClient.print_setup_help() outputs ssh-keygen and password guidance."""
    if not HAS_SSH_CLIENT:
        save(
            "ssh_help_text",
            False,
            {
                "note": (
                    "app.core.ssh_client not found in project. "
                    "SSHClient is a planned module — implement to pass this test."
                )
            },
        )
        pytest.skip("SSHClient module not found (app.core.ssh_client)")

    SSHClient.print_setup_help()
    captured = capsys.readouterr()
    output = (captured.out + captured.err).lower()

    ok = "ssh-keygen" in output and "password" in output
    save(
        "ssh_help_text",
        ok,
        {
            "output_snippet": output[:400],
            "has_ssh_keygen": "ssh-keygen" in output,
            "has_password": "password" in output,
        },
    )
    assert "ssh-keygen" in output, (
        f"Expected 'ssh-keygen' in help output. Got: {output[:400]!r}"
    )
    assert "password" in output, (
        f"Expected 'password' in help output. Got: {output[:400]!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 12. SSH parse user@host
# ═══════════════════════════════════════════════════════════════════════════════

def test_ssh_parse_user_host():
    """SSHClient stores host, user, and port correctly on construction."""
    if not HAS_SSH_CLIENT:
        save(
            "ssh_parse_user_host",
            False,
            {
                "note": (
                    "app.core.ssh_client not found in project. "
                    "SSHClient is a planned module — implement to pass this test."
                )
            },
        )
        pytest.skip("SSHClient module not found (app.core.ssh_client)")

    client = SSHClient("hostname", "alice", port=22)

    ok = (
        getattr(client, "host", None) == "hostname"
        and getattr(client, "user", None) == "alice"
        and getattr(client, "port", None) == 22
    )
    save(
        "ssh_parse_user_host",
        ok,
        {
            "host": getattr(client, "host", None),
            "user": getattr(client, "user", None),
            "port": getattr(client, "port", None),
        },
    )
    assert client.host == "hostname", f"Expected host='hostname', got {client.host!r}"
    assert client.user == "alice",    f"Expected user='alice', got {client.user!r}"
    assert client.port == 22,         f"Expected port=22, got {client.port!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. CLI command — python --version via MCP run_command
# ═══════════════════════════════════════════════════════════════════════════════

def test_cli_command_python_version(tmp_path, cfg):
    """run_command with 'python --version' returns 'Python' in the output."""
    from app.core.mcp_client import MCPClient

    cfg.working_folder = str(tmp_path)
    client = MCPClient(cfg)
    client.register_builtin_tools()

    # Use PYTHON_EXE if it exists, otherwise fall back to 'python'
    import os
    python_exe = PYTHON_EXE if os.path.exists(PYTHON_EXE) else sys.executable

    # run_command accepts a string; shlex.split handles it internally
    result = client.call("run_command", {"command": f'"{python_exe}" --version'})

    output = result.get("result") or ""
    ok = result.get("success", False) and "Python" in output
    save(
        "cli_command_python_version",
        ok,
        {
            "python_exe": python_exe,
            "success": result.get("success"),
            "output": output[:200],
            "error": result.get("error", ""),
        },
    )
    assert result["success"], f"run_command failed: {result.get('error')}, out={output[:200]!r}"
    assert "Python" in output, f"Expected 'Python' in output, got: {output[:200]!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# 14. CLI command — cross-platform directory listing
# ═══════════════════════════════════════════════════════════════════════════════

def test_cli_command_cross_platform(tmp_path, cfg):
    """Platform-appropriate directory-listing command succeeds."""
    from app.core.mcp_client import MCPClient

    cfg.working_folder = str(tmp_path)
    client = MCPClient(cfg)
    client.register_builtin_tools()

    # Create a file so the listing is non-empty
    (tmp_path / "canary.txt").write_text("exists", encoding="utf-8")

    if platform.system() == "Windows":
        # Use Python itself to list dir — avoids cmd.exe quoting issues in CI
        import shlex
        cmd = (
            f'"{sys.executable}" -c '
            f'"import os; print(\'\\n\'.join(os.listdir(r\'{tmp_path}\')))"'
        )
    else:
        cmd = f"ls -la '{tmp_path}'"

    result = client.call("run_command", {"command": cmd, "cwd": str(tmp_path)})

    output = result.get("result") or ""
    ok = result.get("success", False)
    save(
        "cli_command_cross_platform",
        ok,
        {
            "platform": platform.system(),
            "command": cmd,
            "success": result.get("success"),
            "output_snippet": output[:300],
            "error": result.get("error", ""),
        },
    )
    assert result["success"], (
        f"Cross-platform dir command failed on {platform.system()}: "
        f"{result.get('error')}, out={output[:300]!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 15. file_converter — graceful degradation when lib absent
# ═══════════════════════════════════════════════════════════════════════════════

def test_file_converter_missing_lib(tmp_path):
    """read_pdf() returns ok=False with a pip-install hint when pypdf is absent."""
    # Mock pypdf as unavailable regardless of whether it's actually installed
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("pypdf mocked as missing")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=mock_import):
        # Force re-import of the converter so our mock takes effect
        import importlib
        import app.core.file_converter as _fc_mod
        importlib.reload(_fc_mod)
        try:
            result = _fc_mod.read_pdf(str(tmp_path / "nonexistent.pdf"))
        finally:
            # Always reload back to normal state
            importlib.reload(_fc_mod)

    ok = not result["ok"] and "pip install" in result.get("error", "").lower()
    save(
        "file_converter_missing_lib",
        ok,
        {
            "ok_returned": result["ok"],
            "error": result.get("error", ""),
            "has_pip_hint": "pip install" in result.get("error", "").lower(),
        },
    )
    assert not result["ok"], (
        "read_pdf should return ok=False when pypdf is not installed"
    )
    assert "pip install" in result.get("error", "").lower(), (
        f"Expected pip-install hint in error, got: {result.get('error')!r}"
    )
