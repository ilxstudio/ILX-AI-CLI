"""Session-scoped trust report — aggregates all observable events for one CLI session.

MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FileSummary:
    path: str
    op_type: str        # "write" | "delete" | "create"
    bytes: int = 0
    ts: str = ""


@dataclass
class CommandSummary:
    command: str
    exit_code: int | None
    duration_ms: float = 0.0
    allowed: bool = True
    ts: str = ""


@dataclass
class PermissionSummary:
    kind: str           # "write" | "execute" | "network" | ...
    target: str
    decision: str       # "allowed" | "denied"
    source: str         # "auto_approve" | "console_ask" | "allowlist" | ...
    ts: str = ""


@dataclass
class RiskSummary:
    kind: str           # "destructive_command" | "ssrf_blocked" | ...
    detail: str
    severity: str       # "low" | "medium" | "high" | "critical"
    target: str = ""
    ts: str = ""


@dataclass
class FailureSummary:
    error_class: str    # "TRANSIENT" | "AUTH" | "RATE_LIMIT" | ...
    message: str
    provider: str = ""
    ts: str = ""


@dataclass
class CostSummary:
    total_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    breakdown: list[dict] = field(default_factory=list)


@dataclass
class SessionReport:
    sid: str
    started_at: str
    files: list[FileSummary] = field(default_factory=list)
    commands: list[CommandSummary] = field(default_factory=list)
    permissions: list[PermissionSummary] = field(default_factory=list)
    risks: list[RiskSummary] = field(default_factory=list)
    failures: list[FailureSummary] = field(default_factory=list)
    cost: CostSummary = field(default_factory=CostSummary)

    # ── convenience counts ──────────────────────────────────────────────────

    @property
    def files_changed(self) -> int:
        return len(self.files)

    @property
    def commands_run(self) -> int:
        return len(self.commands)

    @property
    def commands_failed(self) -> int:
        return sum(1 for c in self.commands if c.exit_code not in (None, 0))

    @property
    def permissions_granted(self) -> int:
        return sum(1 for p in self.permissions if p.decision == "allowed")

    @property
    def permissions_denied(self) -> int:
        return sum(1 for p in self.permissions if p.decision == "denied")

    @property
    def risk_count(self) -> int:
        return len(self.risks)

    @property
    def high_risks(self) -> list[RiskSummary]:
        return [r for r in self.risks if r.severity in ("high", "critical")]

    # ── factory ────────────────────────────────────────────────────────────

    @classmethod
    def for_current_session(cls) -> "SessionReport":
        """Build a SessionReport from the current session's audit data."""
        try:
            from app.core.audit import (
                get_session_id,
                session_file_changes,
                session_commands,
                session_permissions,
                session_risks,
            )
            sid = get_session_id()
            file_recs = session_file_changes(sid)
            cmd_recs = session_commands(sid)
            perm_recs = session_permissions(sid)
            risk_recs = session_risks(sid)
        except Exception:
            sid = "unknown"
            file_recs = cmd_recs = perm_recs = risk_recs = []

        # failures from recent errored LLM calls
        failures: list[FailureSummary] = []
        try:
            from app.core.audit import recent_errors
            for rec in recent_errors(limit=20):
                if rec.get("sid") == sid:
                    failures.append(FailureSummary(
                        error_class="LLM_ERROR",
                        message=str(rec.get("error", ""))[:120],
                        provider=rec.get("provider", ""),
                        ts=rec.get("ts", ""),
                    ))
        except Exception:
            pass

        # cost from the live CostTracker singleton
        cost = CostSummary()
        try:
            from app.core.cost_tracker import tracker
            summary = tracker.session_summary()
            cost = CostSummary(
                total_usd=summary.get("total_usd", 0.0),
                prompt_tokens=summary.get("prompt_tokens", 0),
                completion_tokens=summary.get("completion_tokens", 0),
                breakdown=summary.get("breakdown", []),
            )
        except Exception:
            pass

        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        return cls(
            sid=sid,
            started_at=started_at,
            files=[FileSummary(
                path=r.get("path", ""),
                op_type=r.get("op_type", "write"),
                bytes=r.get("bytes", 0),
                ts=r.get("ts", ""),
            ) for r in file_recs],
            commands=[CommandSummary(
                command=" ".join(r.get("command", [])) if isinstance(r.get("command"), list) else str(r.get("command", "")),
                exit_code=r.get("exit_code"),
                duration_ms=r.get("duration_ms", 0.0),
                allowed=r.get("allowed", True),
                ts=r.get("ts", ""),
            ) for r in cmd_recs],
            permissions=[PermissionSummary(
                kind=r.get("kind", ""),
                target=str(r.get("target", ""))[:80],
                decision=r.get("decision", ""),
                source=r.get("source", ""),
                ts=r.get("ts", ""),
            ) for r in perm_recs],
            risks=[RiskSummary(
                kind=r.get("kind", ""),
                detail=r.get("detail", ""),
                severity=r.get("severity", "medium"),
                target=str(r.get("target", ""))[:80],
                ts=r.get("ts", ""),
            ) for r in risk_recs],
            failures=failures,
            cost=cost,
        )

    def to_dict(self) -> dict[str, Any]:
        import dataclasses
        return dataclasses.asdict(self)
