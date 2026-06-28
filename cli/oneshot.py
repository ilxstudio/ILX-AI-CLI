"""One-shot execution modes — pipe/stdin and argv --chat/--code flags."""
from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display_compat import out, out_error, out_result, out_status


def run_pipe_mode(cfg: AppConfig) -> None:
    """Read all of stdin and send as a single chat message, then exit."""
    from codex.app.llm_client import get_llm_client

    piped = sys.stdin.read().strip()
    if not piped:
        sys.exit(0)
    client = get_llm_client(cfg)
    system = (
        "You are ILX AI, a helpful assistant specialized in software development. "
        "Be concise and accurate."
    )
    try:
        result = client.chat([{"role": "user", "content": piped}], system=system)
        out_result(result)
    except Exception as exc:
        out_error(f"Error: {exc}")
        sys.exit(1)
    sys.exit(0)


def run_argv_chat(prompt: str, cfg: AppConfig) -> None:
    """Send prompt as a single chat message and exit."""
    from cli.display import BANNER, GREEN, RESET
    from codex.app.llm_client import get_llm_client

    out_status(BANNER)
    client = get_llm_client(cfg)
    system = (
        "You are ILX AI, a helpful assistant specialized in software development. "
        "Be concise and accurate."
    )
    out_status(f"{GREEN}ILX AI:{RESET} ")
    chunks: list[str] = []
    try:
        for chunk in client.chat_stream([{"role": "user", "content": prompt}], system=system):
            chunks.append(chunk)
            out(chunk, end="")
        out("")
    except Exception as exc:
        if chunks:
            out("")  # end the partial line
            out_error(f"[Stream interrupted: {exc}]")
        else:
            from app.core.error_classifier import classify_error
            classified = classify_error(exc, getattr(cfg, 'provider', ''))
            out_error(f"Error: {classified.message}")
            out_error(f"Suggestion: {classified.suggestion}")
        sys.exit(1)
    sys.exit(0)


def run_argv_code(task: str, cfg: AppConfig) -> None:
    """Run the code-agent on task and exit with appropriate code."""
    from app.core import audit
    from app.core.config import PermissionMode
    from app.core.permissions import PermissionEngine
    from cli.diff_viewer import show_file_change
    from cli.display import BANNER, DIM, GREEN, RED, RESET, print_diff_line
    from codex.app.controller import CodingAgent
    from codex.app.llm_client import get_llm_client

    out_status(BANNER)
    client = get_llm_client(cfg)

    def _status(msg: str) -> None:
        out_status(f"  {DIM}{msg}{RESET}")

    def _output(stream: str, text: str) -> None:
        if stream == "diff":
            print_diff_line(text)
            return
        col    = GREEN if stream == "stdout" else (RED if stream == "stderr" else DIM)
        prefix = {"stdout": "out", "stderr": "err", "file": "file", "command": "run"}.get(stream, stream)
        out(f"  {col}[{prefix}]{RESET} {text}")

    def _permission_callback(kind: str, name: str, detail: str) -> bool:
        # auto_yes flag — allow all and log to audit
        if getattr(cfg, "auto_yes", False):
            audit.log_permission_decision(
                kind=kind, target=name, decision="allowed",
                mode="auto_yes", source="oneshot", detail=detail,
            )
            return True
        # deny_all mode — reject all
        if cfg.permission_mode == PermissionMode.DENY_ALL:
            audit.log_permission_decision(
                kind=kind, target=name, decision="denied",
                mode="deny_all", source="oneshot", detail=detail,
            )
            return False
        # Otherwise delegate to the permission engine
        from app.core.permissions import FileOperation
        op = FileOperation(op_type=kind, path=name)
        return PermissionEngine(cfg).request_permission(op)

    agent = CodingAgent(
        llm_client=client,
        on_status=_status,
        on_output=_output,
        permission_callback=_permission_callback,
        on_diff=lambda path, old, new: show_file_change(path, old, new),
        max_attempts=cfg.autofix_max_iterations,
        run_timeout=cfg.exec_timeout,
    )
    try:
        result = agent.run(task=task, working_folder=cfg.working_folder)
        if result.success:
            out_result(f"{GREEN}Done.{RESET}")
            if result.files_written:
                out_result(f"Files: {', '.join(result.files_written)}")
            sys.exit(0)
        else:
            out_error(f"{RED}Failed: {result.final_error}{RESET}")
            sys.exit(1)
    except Exception as exc:
        from app.core.error_classifier import classify_error
        classified = classify_error(exc, getattr(cfg, 'provider', ''))
        out_error(f"Error: {classified.message}")
        out_error(f"Suggestion: {classified.suggestion}")
        sys.exit(1)


def parse_argv(cfg: AppConfig | None = None) -> tuple[str | None, str]:
    """Parse sys.argv for --chat/--code and output/behaviour flags.

    Recognised flags (consumed and removed from the prompt):
      --chat          one-shot chat mode
      --code / -c     one-shot code-agent mode
      --yes           auto-approve all permission prompts (also ILX_YES=1)
      --dry-run       show proposed edits but do not write files
      --json          set output_mode to "json"
      --quiet         set output_mode to "quiet"
      --no-color      disable ANSI colour output

    Returns (mode, prompt).  If *cfg* is provided the flags are applied to it
    in-place; otherwise the caller must apply them manually.
    """
    argv = sys.argv[1:]
    mode: str | None = None

    # --- mode flags ---
    if "--chat" in argv:
        mode = "chat"
        argv = [a for a in argv if a != "--chat"]
    if "--code" in argv or "-c" in argv:
        mode = "code"
        argv = [a for a in argv if a not in ("--code", "-c")]

    # --- behaviour flags ---
    auto_yes = os.environ.get("ILX_YES") == "1"
    dry_run = False
    output_mode = "ansi"
    autofix: bool | None = None  # None means "use config default"

    if "--yes" in argv:
        auto_yes = True
        argv = [a for a in argv if a != "--yes"]
    if "--dry-run" in argv:
        dry_run = True
        argv = [a for a in argv if a != "--dry-run"]
    if "--json" in argv:
        output_mode = "json"
        argv = [a for a in argv if a != "--json"]
    if "--quiet" in argv:
        output_mode = "quiet"
        argv = [a for a in argv if a != "--quiet"]
    if "--no-color" in argv:
        # Signal is set on cfg; actual colour suppression is handled by display module
        argv = [a for a in argv if a != "--no-color"]
        if cfg is not None:
            # Use output_mode quiet only if not already overridden to json
            if output_mode == "ansi":
                output_mode = "quiet"
    if "--autofix" in argv:
        autofix = True
        argv = [a for a in argv if a != "--autofix"]
    if "--no-autofix" in argv:
        autofix = False
        argv = [a for a in argv if a != "--no-autofix"]

    # Apply to config if provided
    if cfg is not None:
        if auto_yes:
            cfg.auto_yes = True
        if dry_run:
            cfg.dry_run = True
        cfg.output_mode = output_mode
        if autofix is not None:
            cfg.autofix_enabled = autofix

    prompt = " ".join(argv).strip() if argv else ""
    return mode, prompt
