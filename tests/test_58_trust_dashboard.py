"""Cluster 58 — /trust dashboard command.

Tests:
  1. test_trust_dashboard_import       — can import cmd_trust and _render_dashboard
  2. test_render_empty_report          — SessionReport with no data renders without crash
  3. test_render_with_files            — FileSummary items appear in output
  4. test_render_with_commands         — CommandSummary items appear
  5. test_render_with_failures         — FailureSummary items appear
  6. test_render_with_risks            — RiskSummary items appear
  7. test_render_with_cost             — CostSummary with $0.01 appears in output
  8. test_json_output                  — --json arg returns JSON-serialisable output
  9. test_permissions_granted_denied   — correct panel content for mixed permissions

MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_report(**kwargs):
    """Build a minimal SessionReport from app.core.session_report."""
    from app.core.session_report import SessionReport
    return SessionReport(sid="test01", started_at="2026-01-01T00:00:00Z", **kwargs)


def _capture_dashboard(report):
    """Render _render_dashboard to a StringIO and return the captured text."""
    from rich.console import Console
    from cli.commands.trust_dashboard import _render_dashboard

    buf = io.StringIO()
    console = Console(file=buf, width=120, highlight=False)
    _render_dashboard(report, console)
    return buf.getvalue()


# ── tests ─────────────────────────────────────────────────────────────────────

def test_trust_dashboard_import():
    """cmd_trust and _render_dashboard are importable."""
    from cli.commands.trust_dashboard import cmd_trust, _render_dashboard  # noqa: F401
    assert callable(cmd_trust)
    assert callable(_render_dashboard)


def test_render_empty_report():
    """An empty SessionReport renders all 6 panel headers without error."""
    report = _make_report()
    out = _capture_dashboard(report)

    assert "FILES CHANGED" in out
    assert "COMMANDS RUN" in out
    assert "FAILURES" in out
    assert "MODEL COST" in out
    assert "PERMISSIONS" in out
    assert "RISKS DETECTED" in out


def test_render_with_files():
    """FileSummary items appear in the FILES CHANGED panel."""
    from app.core.session_report import FileSummary

    report = _make_report(files=[
        FileSummary(path="src/main.py", op_type="write", bytes=2048),
        FileSummary(path="tests/test_foo.py", op_type="create", bytes=512),
    ])
    out = _capture_dashboard(report)

    assert "main.py" in out
    assert "write" in out


def test_render_with_commands():
    """CommandSummary items (pass and fail) appear in the COMMANDS RUN panel."""
    from app.core.session_report import CommandSummary

    report = _make_report(commands=[
        CommandSummary(command="python test.py", exit_code=0, duration_ms=1200.0),
        CommandSummary(command="make build", exit_code=2, duration_ms=3400.0),
    ])
    out = _capture_dashboard(report)

    assert "python test.py" in out
    assert "make build" in out


def test_render_with_failures():
    """FailureSummary items appear in the FAILURES panel."""
    from app.core.session_report import FailureSummary

    report = _make_report(failures=[
        FailureSummary(error_class="AUTH", message="anthropic: invalid key"),
    ])
    out = _capture_dashboard(report)

    assert "AUTH" in out
    assert "anthropic" in out


def test_render_with_risks():
    """RiskSummary items appear in the RISKS DETECTED panel."""
    from app.core.session_report import RiskSummary

    report = _make_report(risks=[
        RiskSummary(kind="destructive_command", detail="rm -rf /tmp", severity="high"),
        RiskSummary(kind="sql_destructive", detail="DROP TABLE users", severity="critical"),
    ])
    out = _capture_dashboard(report)

    assert "destructive_command" in out or "HIGH" in out
    assert "RISKS DETECTED" in out


def test_render_with_cost():
    """CostSummary with a non-zero total appears as a dollar value in output."""
    from app.core.session_report import CostSummary

    cost = CostSummary(
        total_usd=0.0041,
        prompt_tokens=1000,
        completion_tokens=200,
        breakdown=[
            {"provider": "anthropic", "model": "sonnet-4-6", "cost_usd": 0.0041, "tokens": 1200},
        ],
    )
    report = _make_report(cost=cost)
    out = _capture_dashboard(report)

    assert "$0.0041" in out or "0.004" in out


def test_json_output(capsys):
    """--json arg writes valid JSON to stdout without rendering Rich panels."""
    from unittest.mock import MagicMock
    from cli.commands.trust_dashboard import cmd_trust
    from app.core.session_report import SessionReport

    report = _make_report()

    with patch(
        "app.core.session_report.SessionReport.for_current_session",
        return_value=report,
    ), patch(
        "cli.rich_display.get_output_mode",
        return_value="ansi",
    ):
        # Capture stdout
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            cmd_trust("--json", MagicMock())
        finally:
            sys.stdout = old_stdout

    captured = buf.getvalue()
    parsed = json.loads(captured)
    assert "sid" in parsed
    assert "files" in parsed
    assert "commands" in parsed


def test_permissions_granted_denied_counts():
    """Mixed granted/denied permissions produce the expected panel content."""
    from app.core.session_report import PermissionSummary

    perms = [
        PermissionSummary(kind="execute", target="git status", decision="allowed", source="auto_approve"),
        PermissionSummary(kind="execute", target="git status", decision="allowed", source="auto_approve"),
        PermissionSummary(kind="execute", target="rm -rf /tmp", decision="denied",  source="console_ask"),
    ]
    report = _make_report(permissions=perms)
    out = _capture_dashboard(report)

    # The panel should mention the denied count
    assert "denied" in out.lower() or "✗" in out
