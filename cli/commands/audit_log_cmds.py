"""Audit log subcommands — replay, explain, export, diff.

These are standalone functions called from AuditCommands in audit_cmds.py.
Kept in a separate module so audit_cmds.py stays under 700 lines.
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cli.display_compat import out, out_error, out_result, out_status

if TYPE_CHECKING:
    from app.core.config import AppConfig

_LOG_PATH = Path.home() / ".ilx_cli" / "logs" / "audit.log"


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_log_records() -> list[dict]:
    """Read all JSONL records from the audit log; silently skip malformed lines."""
    if not _LOG_PATH.exists():
        return []
    records: list[dict] = []
    try:
        with open(_LOG_PATH, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return records


def _ts_to_hms(ts: str) -> str:
    """Convert ISO-8601 timestamp to HH:MM:SS, or return '??:??:??' on failure."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%H:%M:%S")
    except Exception:
        return "??:??:??"


def _ts_to_date(ts: str) -> str:
    """Return YYYY-MM-DD local date from an ISO-8601 timestamp."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d")
    except Exception:
        return ""


def _format_event_line(rec: dict, *, colors: bool = True) -> str:
    """Return a single human-readable line for one audit record."""
    from cli.display import BLUE, CYAN, DIM, MAGENTA, RED, RESET, YELLOW

    event = rec.get("event", "unknown")
    ts    = _ts_to_hms(rec.get("ts", ""))

    if event == "llm_call":
        provider = rec.get("provider", "?")
        model    = rec.get("model", "?")
        tin      = rec.get("prompt_tokens", 0)
        tout     = rec.get("response_tokens", 0)
        latency  = rec.get("latency_ms", 0)
        label    = f"{CYAN}LLM {RESET}" if colors else "LLM  "
        return (
            f"[{ts}] {label} {provider}/{model}  "
            f"{tin}→{tout} tok  {latency:.0f}ms"
        )

    if event == "file_op":
        op      = rec.get("op_type", "?")
        path    = rec.get("path", "?")
        nbytes  = rec.get("bytes", 0)
        allowed = rec.get("allowed", True)
        status  = "allowed" if allowed else "denied"
        label   = f"{BLUE}FILE{RESET}" if colors else "FILE"
        return (
            f"[{ts}] {label} {op:<6} {path}  "
            f"({nbytes:,} B)  [{status}]"
        )

    if event == "command_exec":
        cmd      = rec.get("command", [])
        cmd_str  = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        exit_c   = rec.get("exit_code", "?")
        dur      = rec.get("duration_ms", 0)
        label    = f"{YELLOW}CMD {RESET}" if colors else "CMD  "
        return (
            f"[{ts}] {label} {cmd_str}  "
            f"exit={exit_c}  {dur:.0f}ms"
        )

    if event == "permission_decision":
        kind   = rec.get("kind", "?")
        target = rec.get("target", "?")
        dec    = rec.get("decision", "?")
        label  = f"{MAGENTA}PERM{RESET}" if colors else "PERM"
        return f"[{ts}] {label} kind={kind} target={target}  [{dec}]"

    if event == "egress":
        method  = rec.get("method", "?")
        url     = rec.get("url", "?")
        status  = rec.get("status", "?")
        bout    = rec.get("bytes_out", 0)
        bin_    = rec.get("bytes_in", 0)
        label   = f"{RED}NET {RESET}" if colors else "NET  "
        return (
            f"[{ts}] {label} {method} {url}  "
            f"HTTP {status}  {bout}→{bin_} B"
        )

    # Fallback: generic key=value
    label = f"{DIM}{event}{RESET}" if colors else event
    extra_fields = {
        k: v for k, v in rec.items()
        if k not in ("ts", "pid", "event")
    }
    kv = "  ".join(f"{k}={v}" for k, v in list(extra_fields.items())[:6])
    return f"[{ts}] {label}  {kv}"


# ── /audit replay ─────────────────────────────────────────────────────────────

def audit_replay(args: list[str]) -> None:
    """Show a human-readable replay of recent audit log events.

    Usage:
        /audit replay           — last 50 events
        /audit replay last      — same
        /audit replay 100       — last N events
        /audit replay today     — events from today only
    """
    from cli.display import BOLD, CYAN, DIM, RESET

    filter_today = False
    limit = 50

    for arg in args:
        if arg.lower() in ("last", ""):
            pass
        elif arg.lower() == "today":
            filter_today = True
        else:
            try:
                limit = int(arg)
            except ValueError:
                out_error(f"  Unknown argument '{arg}'. Usage: /audit replay [N|today]")
                return

    records = _read_log_records()

    if filter_today:
        today_str = datetime.now(UTC).astimezone().strftime("%Y-%m-%d")
        records = [r for r in records if _ts_to_date(r.get("ts", "")) == today_str]
        heading = "today"
    else:
        records = records[-limit:]
        heading = f"last {len(records)}"

    if not records:
        out(f"  {DIM}(no audit events found){RESET}")
        return

    out(f"\n{BOLD}{CYAN}Audit Replay{RESET}  {DIM}({heading} events from {_LOG_PATH}){RESET}\n")
    for rec in records:
        out(f"  {_format_event_line(rec)}")
    out("")


# ── /audit explain ────────────────────────────────────────────────────────────

def audit_explain(args: list[str], cfg: AppConfig) -> None:
    """Send recent audit events to the LLM for a plain-English summary.

    Usage:
        /audit explain          — explain last 30 events
        /audit explain 50       — explain last N events
    """
    from cli.display import BOLD, CYAN, DIM, RESET

    limit = 30
    for arg in args:
        try:
            limit = int(arg)
        except ValueError:
            out_error(f"  Unknown argument '{arg}'. Usage: /audit explain [N]")
            return

    records = _read_log_records()[-limit:]
    if not records:
        out(f"  {DIM}(no audit events found){RESET}")
        return

    out(f"\n{BOLD}{CYAN}Audit Explain{RESET}  {DIM}(last {len(records)} events){RESET}\n")

    # Build compact text for LLM context
    lines: list[str] = []
    for rec in records:
        lines.append(_format_event_line(rec, colors=False))
    audit_text = "\n".join(lines)

    system_prompt = (
        "You are a developer assistant analyzing an AI CLI session audit log.\n"
        "Summarize what the AI did in plain English. Group by activity type.\n"
        "Focus on: files read/written, commands run, LLM calls made, permission decisions.\n"
        "Be concise — 3-8 bullet points."
    )
    user_msg = f"Here is the audit log:\n\n{audit_text}\n\nPlease summarize what happened."

    # Try LLM
    try:
        from codex.app.llm_client_ext import get_llm_client
        client = get_llm_client(cfg)
        out_status(f"  {DIM}Analyzing with {client.model}...{RESET}")
        from app.core.spinner import Spinner
        spinner = Spinner("Generating summary")
        spinner.start()
        try:
            summary = client.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ])
            spinner.stop(clear=True)
        except Exception as exc:
            spinner.stop(clear=True)
            raise exc
        out_result(summary)
    except Exception as exc:
        # Fall back to rule-based summary
        out_status(f"  {DIM}LLM unavailable ({exc}); using rule-based summary.{RESET}\n")
        _rule_based_summary(records)


def _rule_based_summary(records: list[dict]) -> None:
    """Print a simple rule-based summary when the LLM is unavailable."""
    from collections import Counter

    from cli.display import BOLD, DIM, RESET

    counts: Counter = Counter(r.get("event", "unknown") for r in records)
    out(f"{BOLD}Event counts:{RESET}")
    for evt, cnt in counts.most_common():
        out(f"  {DIM}{evt:<30}{RESET} {cnt}")

    # Top file paths touched
    file_paths = [
        r.get("path", "")
        for r in records
        if r.get("event") == "file_op" and r.get("path")
    ]
    if file_paths:
        path_counts: Counter = Counter(file_paths)
        out(f"\n{BOLD}Files touched:{RESET}")
        for p, cnt in path_counts.most_common(10):
            out(f"  {DIM}{p}{RESET}  ({cnt}x)")

    # Commands run
    cmds = [
        r.get("command", [])
        for r in records
        if r.get("event") == "command_exec"
    ]
    if cmds:
        out(f"\n{BOLD}Commands run:{RESET}")
        for cmd in cmds[:10]:
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            out(f"  {DIM}{cmd_str}{RESET}")

    out("")


# ── /audit export ─────────────────────────────────────────────────────────────

def audit_export(args: list[str]) -> None:
    """Export the audit log to JSON or CSV.

    Usage:
        /audit export               — print JSON to stdout
        /audit export session.json  — write JSON to file
        /audit export --csv         — print CSV to stdout
    """
    from cli.display import GREEN, RED, RESET

    use_csv   = False
    out_file  = None

    for arg in args:
        if arg == "--csv":
            use_csv = True
        elif not arg.startswith("-"):
            out_file = arg

    records = _read_log_records()
    if not records:
        out("  (no audit events found)")
        return

    if use_csv:
        content = _records_to_csv(records)
    else:
        content = json.dumps(records, indent=2, ensure_ascii=False)

    if out_file:
        try:
            dest = Path(out_file)
            dest.write_text(content, encoding="utf-8")
            out_result(f"  {GREEN}Exported {len(records)} records to: {dest.resolve()}{RESET}")
        except OSError as exc:
            out_error(f"  {RED}Write failed: {exc}{RESET}")
    else:
        out_result(content)


def _records_to_csv(records: list[dict]) -> str:
    """Convert audit records to CSV text."""
    # Collect all field names across all records (deterministic order)
    base_cols = ["ts", "pid", "event"]
    extra_cols: list[str] = []
    seen: set[str] = set(base_cols)
    for rec in records:
        for k in rec:
            if k not in seen:
                extra_cols.append(k)
                seen.add(k)

    fieldnames = base_cols + extra_cols
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for rec in records:
        # Flatten any list/dict values to their repr
        flat: dict[str, Any] = {}
        for col in fieldnames:
            val = rec.get(col, "")
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            flat[col] = val
        writer.writerow(flat)
    return buf.getvalue()


# ── /audit diff ───────────────────────────────────────────────────────────────

def audit_diff() -> None:
    """Show net file changes made this session (current PID) from audit log.

    Usage:
        /audit diff     — show all file writes/deletes this session
    """
    from cli.display import BOLD, DIM, GREEN, RED, RESET

    current_pid = os.getpid()
    records = _read_log_records()

    # Filter to current PID, file_op events that were allowed, write or delete
    file_ops: list[dict] = [
        r for r in records
        if r.get("pid") == current_pid
        and r.get("event") == "file_op"
        and r.get("allowed", False)
        and r.get("op_type", "") in ("write", "delete")
    ]

    if not file_ops:
        out(f"  {DIM}(no file changes recorded in audit log this session){RESET}")
        return

    # Group by path — last write wins; delete wins over write
    last_op: dict[str, dict] = {}
    for rec in file_ops:
        path = rec.get("path", "")
        if path:
            last_op[path] = rec

    out(f"\n{BOLD}Files changed this session:{RESET}")
    for path, rec in sorted(last_op.items()):
        op = rec.get("op_type", "?").upper()
        if op == "WRITE":
            nbytes = rec.get("bytes", 0)
            out(f"  {GREEN}{op:<6}{RESET}  {path}  {DIM}({nbytes:,} bytes){RESET}")
        else:
            out(f"  {RED}{op:<6}{RESET}  {path}")
    out("")
