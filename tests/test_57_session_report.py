"""Tests for app.core.session_report — SessionReport data model.

MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

import dataclasses
from unittest.mock import patch, MagicMock


def test_session_report_imports():
    from app.core.session_report import (
        SessionReport, FileSummary, CommandSummary,
        PermissionSummary, RiskSummary, FailureSummary, CostSummary,
    )
    assert SessionReport is not None


def test_session_report_empty():
    from app.core.session_report import SessionReport
    r = SessionReport(sid="x", started_at="t")
    assert r.files_changed == 0
    assert r.commands_run == 0
    assert r.commands_failed == 0
    assert r.permissions_granted == 0
    assert r.permissions_denied == 0
    assert r.risk_count == 0
    assert r.high_risks == []


def test_files_changed_count():
    from app.core.session_report import SessionReport, FileSummary
    r = SessionReport(sid="s1", started_at="t1")
    assert r.files_changed == 0
    r.files.append(FileSummary(path="foo.py", op_type="write"))
    r.files.append(FileSummary(path="bar.py", op_type="create", bytes=512))
    assert r.files_changed == 2


def test_commands_failed_count():
    from app.core.session_report import SessionReport, CommandSummary
    r = SessionReport(sid="s2", started_at="t2")
    r.commands.append(CommandSummary(command="ls", exit_code=0))
    r.commands.append(CommandSummary(command="false", exit_code=1))
    r.commands.append(CommandSummary(command="missing", exit_code=127))
    r.commands.append(CommandSummary(command="pending", exit_code=None))
    assert r.commands_run == 4
    assert r.commands_failed == 2   # exit_code 1 and 127


def test_permissions_granted_denied():
    from app.core.session_report import SessionReport, PermissionSummary
    r = SessionReport(sid="s3", started_at="t3")
    r.permissions.append(PermissionSummary(
        kind="write", target="/tmp/a", decision="allowed", source="allowlist"))
    r.permissions.append(PermissionSummary(
        kind="execute", target="rm -rf /", decision="denied", source="console_ask"))
    r.permissions.append(PermissionSummary(
        kind="network", target="http://x.com", decision="allowed", source="auto_approve"))
    assert r.permissions_granted == 2
    assert r.permissions_denied == 1


def test_risk_high_filter():
    from app.core.session_report import SessionReport, RiskSummary
    r = SessionReport(sid="s4", started_at="t4")
    for sev in ("low", "medium", "high", "critical"):
        r.risks.append(RiskSummary(kind="k", detail="d", severity=sev))
    assert r.risk_count == 4
    assert len(r.high_risks) == 2
    assert {rs.severity for rs in r.high_risks} == {"high", "critical"}


def test_to_dict_serializable():
    from app.core.session_report import (
        SessionReport, FileSummary, CommandSummary,
        PermissionSummary, RiskSummary, FailureSummary, CostSummary,
    )
    r = SessionReport(
        sid="s5", started_at="2026-01-01T00:00:00Z",
        files=[FileSummary(path="a.py", op_type="write", bytes=100)],
        commands=[CommandSummary(command="git status", exit_code=0)],
        permissions=[PermissionSummary(
            kind="write", target="x", decision="allowed", source="allowlist")],
        risks=[RiskSummary(kind="ssrf_blocked", detail="blocked", severity="high")],
        failures=[FailureSummary(error_class="TRANSIENT", message="timeout")],
        cost=CostSummary(total_usd=0.05, prompt_tokens=100, completion_tokens=50),
    )
    d = r.to_dict()
    assert isinstance(d, dict)

    def _no_dataclass(obj):
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return False
        if isinstance(obj, dict):
            return all(_no_dataclass(v) for v in obj.values())
        if isinstance(obj, list):
            return all(_no_dataclass(i) for i in obj)
        return True

    assert _no_dataclass(d)
    assert d["sid"] == "s5"
    assert d["files"][0]["path"] == "a.py"
    assert d["cost"]["total_usd"] == 0.05


def test_for_current_session_returns_instance():
    from app.core.session_report import SessionReport
    audit_mock = MagicMock()
    audit_mock.get_session_id.return_value = "test-sid-123"
    audit_mock.session_file_changes.return_value = [
        {"path": "main.py", "op_type": "write", "bytes": 200, "ts": "2026-01-01"}]
    audit_mock.session_commands.return_value = [
        {"command": ["git", "status"], "exit_code": 0,
         "duration_ms": 10.5, "allowed": True, "ts": "2026-01-01"}]
    audit_mock.session_permissions.return_value = []
    audit_mock.session_risks.return_value = []
    audit_mock.recent_errors.return_value = []
    cost_mock = MagicMock()
    cost_mock.tracker.session_summary.return_value = {
        "total_usd": 0.001, "prompt_tokens": 50,
        "completion_tokens": 25, "breakdown": []}
    with patch.dict("sys.modules", {
        "app.core.audit": audit_mock,
        "app.core.cost_tracker": cost_mock,
    }):
        report = SessionReport.for_current_session()
    assert isinstance(report, SessionReport)
    assert report.sid == "test-sid-123"
    assert report.files_changed == 1
    assert report.files[0].path == "main.py"
    assert report.commands_run == 1
    assert report.commands[0].command == "git status"


def test_cost_summary_defaults():
    from app.core.session_report import CostSummary
    c = CostSummary()
    assert c.total_usd == 0.0
    assert c.prompt_tokens == 0
    assert c.completion_tokens == 0
    assert c.breakdown == []
