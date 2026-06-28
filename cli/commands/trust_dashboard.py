"""Trust dashboard — /trust command renders a 6-panel session summary.

Shows: files changed, commands run, failures, cost, permissions, risks.
MIT License — Copyright 2026 ILX Studio
"""
from __future__ import annotations

import datetime
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig
    from app.core.session_report import SessionReport

_log = logging.getLogger("ilx_cli.trust_dashboard")

_REPORTS_DIR = Path.home() / ".ilx_cli" / "reports"


# ── Panel content builders ─────────────────────────────────────────────────────

def _build_panel_content(items, empty_msg: str, formatter) -> str:
    """Build Rich markup text for a panel."""
    if not items:
        return f"[green]  ✓ {empty_msg}[/green]"
    lines = [formatter(item) for item in items[:10]]
    if len(items) > 10:
        lines.append(f"[dim]  ... and {len(items) - 10} more[/dim]")
    return "\n".join(lines)


def _files_content(report: "SessionReport") -> str:
    def fmt(f):
        size = f"  {f.bytes:,} bytes" if f.bytes else ""
        return f"  [cyan]{f.path}[/cyan]  [dim]{f.op_type}{size}[/dim]"
    return _build_panel_content(report.files, "No files modified", fmt)


def _commands_content(report: "SessionReport") -> str:
    def fmt(c):
        elapsed = f"  {c.duration_ms / 1000:.1f}s" if c.duration_ms else ""
        if c.exit_code in (None, 0):
            return (
                f"  [white]{c.command[:55]}[/white]"
                f"  [green]✓ exit:{c.exit_code if c.exit_code is not None else 0}[/green]"
                f"[dim]{elapsed}[/dim]"
            )
        return (
            f"  [red]{c.command[:55]}[/red]"
            f"  [red]✗ exit:{c.exit_code}[/red]"
            f"[dim]{elapsed}[/dim]"
        )
    return _build_panel_content(report.commands, "No commands executed", fmt)


def _failures_content(report: "SessionReport") -> str:
    def fmt(f):
        return f"  [red bold]{f.error_class}[/red bold]  [dim]{f.message[:60]}[/dim]"
    return _build_panel_content(report.failures, "Clean session — no failures", fmt)


def _cost_content(report: "SessionReport") -> str:
    cost = report.cost
    breakdown = cost.breakdown if cost else []
    total_usd = cost.total_usd if cost else 0.0
    prompt_tok = cost.prompt_tokens if cost else 0
    comp_tok = cost.completion_tokens if cost else 0
    total_tok = prompt_tok + comp_tok

    if total_usd == 0.0 and not breakdown:
        return "[green]  ✓ No cloud API calls this session[/green]"

    lines: list[str] = []
    for entry in breakdown[:8]:
        provider = entry.get("provider", "?")
        model = entry.get("model", "?")
        usd = entry.get("cost_usd", 0.0)
        tok = entry.get("tokens", 0)
        lines.append(
            f"  [dim]{provider} / {model}[/dim]"
            f"  [yellow]${usd:.4f}[/yellow]  [dim]{tok:,} tok[/dim]"
        )
    if breakdown:
        lines.append("  [dim]───────────────[/dim]")
    lines.append(
        f"  [bold]TOTAL[/bold]  [yellow]${total_usd:.4f}[/yellow]"
        f"  [dim]{total_tok:,} tok[/dim]"
    )
    return "\n".join(lines)


def _permissions_content(report: "SessionReport") -> str:
    granted = report.permissions_granted
    denied = report.permissions_denied
    denied_perms = [p for p in report.permissions if p.decision == "denied"]

    if denied == 0 and granted == 0:
        return "[green]  ✓ No permission events this session[/green]"

    lines: list[str] = []
    if denied == 0:
        lines.append("[green]  ✓ All operations auto-approved[/green]")
    else:
        lines.append(
            f"  [green]✓ {granted} auto-granted[/green]"
            f"   [red]✗ {denied} denied[/red]"
        )
        for p in denied_perms[:8]:
            lines.append(f"  [red]✗ {p.kind}: {p.target[:50]}[/red]")
        if len(denied_perms) > 8:
            lines.append(f"[dim]  ... and {len(denied_perms) - 8} more[/dim]")
    return "\n".join(lines)


def _risks_content(report: "SessionReport") -> str:
    _SEV_COLOR = {
        "critical": "bold red",
        "high":     "red",
        "medium":   "yellow",
        "low":      "dim",
    }

    def fmt(r):
        color = _SEV_COLOR.get(r.severity, "dim")
        detail = r.detail or r.target or ""
        return (
            f"  [{color}]⚠ {r.severity.upper()}[/{color}]"
            f"  [dim]{r.kind}: {detail[:45]}[/dim]"
        )

    return _build_panel_content(report.risks, "No risks detected", fmt)


def _risks_panel_title(report: "SessionReport") -> str:
    high_count = len(report.high_risks)
    if high_count:
        return f"[bold]RISKS DETECTED[/bold] [bold red]({high_count} HIGH+)[/bold red]"
    return "[bold]RISKS DETECTED[/bold]"


# ── Dashboard renderer ─────────────────────────────────────────────────────────

def _render_dashboard(report: "SessionReport", console) -> None:
    """Render the 6-panel trust dashboard to *console*."""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    # Header panel
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d  %H:%M:%S UTC")
    header_text = Text(justify="center")
    header_text.append("ILX AI CLI — Session Trust Report ", style="bold")
    header_text.append(f"[sid: {report.sid}]", style="dim cyan")
    header_text.append(f"\n{ts}", style="dim")
    console.print(Panel(header_text, box=box.ROUNDED, border_style="cyan"))

    # 2-column grid
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)

    grid.add_row(
        Panel(
            _files_content(report),
            title="[bold]FILES CHANGED[/bold]",
            box=box.ROUNDED,
            border_style="blue",
        ),
        Panel(
            _commands_content(report),
            title="[bold]COMMANDS RUN[/bold]",
            box=box.ROUNDED,
            border_style="blue",
        ),
    )
    grid.add_row(
        Panel(
            _failures_content(report),
            title="[bold]FAILURES[/bold]",
            box=box.ROUNDED,
            border_style="red" if report.failures else "green",
        ),
        Panel(
            _cost_content(report),
            title="[bold]MODEL COST[/bold]",
            box=box.ROUNDED,
            border_style="yellow",
        ),
    )
    grid.add_row(
        Panel(
            _permissions_content(report),
            title="[bold]PERMISSIONS[/bold]",
            box=box.ROUNDED,
            border_style="green" if report.permissions_denied == 0 else "red",
        ),
        Panel(
            _risks_content(report),
            title=_risks_panel_title(report),
            box=box.ROUNDED,
            border_style="red" if report.high_risks else "green",
        ),
    )

    console.print(grid)


# ── /trust --history helper ────────────────────────────────────────────────────

def _list_saved_reports() -> None:
    from cli.display_compat import out, out_error

    if not _REPORTS_DIR.exists():
        out("[dim]No saved reports found.[/dim]")
        return

    files = sorted(_REPORTS_DIR.glob("session_*.json"), reverse=True)
    if not files:
        out("  No saved session reports.")
        return

    out(f"\n  Saved session reports in {_REPORTS_DIR}:\n")
    for f in files[:20]:
        mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M"
        )
        out(f"  {mtime}  {f.name}")
    if len(files) > 20:
        out(f"  ... and {len(files) - 20} more")
    out("")


# ── Public command entry-point ─────────────────────────────────────────────────

def cmd_trust(args: list[str] | str, cfg: "AppConfig") -> None:
    """/trust [--json | --save | history] — Session trust dashboard."""
    # Normalise args to a single string for simple flag parsing
    if isinstance(args, list):
        args_str = " ".join(args).strip()
    else:
        args_str = (args or "").strip()

    # ── history subcommand ─────────────────────────────────────────────────
    if args_str == "history":
        _list_saved_reports()
        return

    # ── build the report ──────────────────────────────────────────────────
    try:
        from app.core.session_report import SessionReport
        report = SessionReport.for_current_session()
    except Exception as exc:
        from cli.display_compat import out_error
        out_error(f"[trust] Could not build session report: {exc}")
        return

    # ── --json flag ───────────────────────────────────────────────────────
    if "--json" in args_str:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return

    # ── --save flag ───────────────────────────────────────────────────────
    if "--save" in args_str:
        try:
            saved_path = report.save()
            from cli.display_compat import out_status
            out_status(f"  Report saved: {saved_path}")
        except Exception as exc:
            from cli.display_compat import out_error
            out_error(f"[trust] Save failed: {exc}")
        # Fall through to also render the dashboard

    # ── render Rich dashboard ─────────────────────────────────────────────
    try:
        from rich.console import Console

        from cli.rich_display import get_output_mode
        mode = get_output_mode()
        if mode == "quiet":
            return
        if mode == "json":
            sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
            sys.stdout.flush()
            return

        console = Console()
        _render_dashboard(report, console)

    except ImportError:
        # Rich not available — plain text fallback
        _plain_fallback(report)
    except Exception as exc:
        _log.debug("trust dashboard render error: %s", exc)
        _plain_fallback(report)


def _plain_fallback(report: "SessionReport") -> None:
    """Minimal plain-text fallback when Rich is unavailable."""
    from cli.display_compat import out
    out(f"\nILX AI CLI — Session Trust Report  [sid: {report.sid}]")
    out(f"  Files changed:  {report.files_changed}")
    out(f"  Commands run:   {report.commands_run}")
    out(f"  Failures:       {len(report.failures)}")
    out(f"  Cost:           ${report.cost.total_usd:.4f}")
    out(f"  Permissions:    {report.permissions_granted} granted / {report.permissions_denied} denied")
    out(f"  Risks:          {report.risk_count}")
    out("")
