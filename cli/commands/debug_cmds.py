"""Debug commands — /debug runs a program interactively and can call the LLM to explain errors."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
from cli.display_compat import out

_log = logging.getLogger("ilx_cli.debug_cmds")

_USAGE = (
    f"  {CYAN}/debug <script.py> [args]{RESET}   — run interactively (stdin live)\n"
    f"  {CYAN}/debug log{RESET}                   — show last session output\n"
    f"  {CYAN}/debug logs{RESET}                  — list recent debug sessions\n"
    f"  {CYAN}/debug analyze{RESET}               — AI analysis of last session errors\n"
    f"  {CYAN}/debug analyze <id>{RESET}          — AI analysis of a specific session"
)

# module-level list so we can track the most recent session across calls
_LAST_SESSION_ID: list[str] = []


class DebugCommands:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def cmd_debug(self, args: list[str]) -> None:
        if not args:
            out(f"\n{BOLD}ILX Debug Runner{RESET}\n{_USAGE}\n")
            return
        sub = args[0].lower()
        if sub == "log":
            self._show_log(None)
        elif sub == "logs":
            self._list_logs()
        elif sub == "analyze":
            sid = args[1] if len(args) > 1 else (_LAST_SESSION_ID[0] if _LAST_SESSION_ID else None)
            self._analyze(sid)
        else:
            self._run(args)

    def _run(self, args: list[str]) -> None:
        from cli.debug_runner import find_python, run_interactive
        from datetime import datetime as _dt

        wf = self._cfg.working_folder
        if not wf or not Path(wf).is_dir():
            out(f"  {YELLOW}No workspace set. Use /workspace first.{RESET}")
            return

        session_id = "debug_" + _dt.now().strftime("%Y%m%d_%H%M%S")
        _LAST_SESSION_ID.clear()
        _LAST_SESSION_ID.append(session_id)

        python_bin = find_python(wf)
        venv_label = ""
        if python_bin != __import__("sys").executable:
            venv_label = f"  {DIM}(venv: {Path(python_bin).parent.parent.name}){RESET}"

        script = " ".join(args)
        out(f"\n{BOLD}Debug:{RESET} {CYAN}{script}{RESET}{venv_label}")
        out(f"{DIM}  Session : {session_id}{RESET}")
        out(f"{DIM}  Python  : {python_bin}{RESET}")
        out(f"{DIM}  Log     : ~/.ilx_cli/debug/{session_id}.log{RESET}")
        out(f"{DIM}  Type input when prompted. Ctrl+C to stop.{RESET}\n")

        collected_output: list[tuple[str, str]] = []

        def _on_output(stream: str, line: str) -> None:
            collected_output.append((stream, line))
            if stream == "stdout":
                print(f"  {line}")
            elif stream == "stderr":
                print(f"  {RED}{line}{RESET}")
            elif stream == "system":
                print(f"  {DIM}[{line}]{RESET}")

        report = run_interactive(
            script_args=args,
            workspace=wf,
            session_id=session_id,
            on_output=_on_output,
        )

        print()
        if report.exit_code == 0:
            out(f"  {GREEN}Exited cleanly (0)  {report.elapsed_s:.1f}s{RESET}")
        else:
            out(f"  {RED}Exited {report.exit_code}  {report.elapsed_s:.1f}s{RESET}")

        out(f"  {DIM}Log saved: {report.log_path}{RESET}")

        if report.error_lines:
            out(f"\n  {YELLOW}{BOLD}{len(report.error_lines)} error line(s) detected:{RESET}")
            for ln in report.error_lines[:6]:
                out(f"    {RED}{ln[:120]}{RESET}")
            out(f"\n  {DIM}Run {CYAN}/debug analyze{DIM} to get AI suggestions for these errors.{RESET}")
        print()

    def _show_log(self, session_id: str | None) -> None:
        from cli.debug_runner import _LOG_DIR, list_sessions

        if session_id:
            log_p = _LOG_DIR / f"{session_id}.log"
        else:
            logs = list_sessions(1)
            if not logs:
                out(f"  {DIM}No debug sessions found. Run /debug <script.py> first.{RESET}")
                return
            log_p = logs[0]

        if not log_p.exists():
            out(f"  {YELLOW}Log not found: {log_p}{RESET}")
            return

        out(f"\n{BOLD}Debug log:{RESET}  {DIM}{log_p}{RESET}\n")
        text = log_p.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines()[-80:]:  # only show the tail so it's readable
            if "[stderr]" in line:
                out(f"  {RED}{line}{RESET}")
            elif "[stdin]" in line:
                out(f"  {CYAN}{line}{RESET}")
            elif "[system]" in line:
                out(f"  {DIM}{line}{RESET}")
            else:
                out(f"  {line}")
        print()

    def _list_logs(self) -> None:
        from cli.debug_runner import list_sessions

        logs = list_sessions(15)
        if not logs:
            out(f"  {DIM}No debug sessions yet.{RESET}")
            return
        out(f"\n{BOLD}Recent debug sessions:{RESET}\n")
        for p in logs:
            sid = p.stem
            size_kb = p.stat().st_size // 1024
            out(f"  {CYAN}{sid}{RESET}  {DIM}{size_kb} KB{RESET}  — /debug analyze {sid}")
        print()

    def _analyze(self, session_id: str | None) -> None:
        from cli.debug_runner import _LOG_DIR, list_sessions, load_session_report

        if not session_id:
            logs = list_sessions(1)
            if not logs:
                out(f"  {YELLOW}No debug session to analyze. Run /debug <script.py> first.{RESET}")
                return
            session_id = logs[0].stem

        report = load_session_report(session_id)
        if report is None:
            # fall back to raw log text if the JSON doesn't exist
            log_p = _LOG_DIR / f"{session_id}.log"
            if not log_p.exists():
                out(f"  {YELLOW}Session '{session_id}' not found.{RESET}")
                return
            raw = log_p.read_text(encoding="utf-8", errors="replace")[-4000:]
            report = {"session_id": session_id, "raw_log": raw}

        out(f"\n{BOLD}Analyzing session:{RESET}  {CYAN}{session_id}{RESET}\n")

        # pull out just the error-looking lines to keep the prompt focused
        lines  = report.get("lines", [])
        cmd    = " ".join(report.get("command", []))
        code   = report.get("exit_code", "?")
        stderr = "\n".join(
            l["text"] for l in lines if l.get("stream") in ("stderr", "stdout")
            and any(p in l.get("text", "") for p in (
                "Traceback", "Error", "error", "Exception", "line ", "File "
            ))
        )[:3000]
        stdin_sent = "\n".join(
            l["text"] for l in lines if l.get("stream") == "stdin"
        )

        if not stderr and not report.get("raw_log"):
            out(f"  {GREEN}No errors in session log — program appeared to run cleanly.{RESET}\n")
            return

        # build a prompt that gives the LLM everything it needs to diagnose the issue
        prompt = (
            f"A Python program was run interactively and produced errors.\n\n"
            f"Command: {cmd}\n"
            f"Exit code: {code}\n"
        )
        if stdin_sent:
            prompt += f"\nUser typed:\n{stdin_sent}\n"
        prompt += f"\nError output:\n```\n{stderr or report.get('raw_log','')}\n```\n\n"
        prompt += (
            "Explain what went wrong and provide the exact fix. "
            "If it's a missing dependency, show the pip install command. "
            "If it's a code bug, show the corrected code. "
            "Be specific — name the file and line number if visible."
        )

        try:
            from codex.app.llm_client import OllamaClient
            llm = OllamaClient(
                base_url=self._cfg.ollama_url,
                model=self._cfg.ollama_model,
            )
            out(f"  {DIM}Asking {self._cfg.provider}/{self._cfg.ollama_model}...{RESET}\n")
            from app.core.spinner import Spinner
            with Spinner("Analyzing errors..."):
                response = llm.generate(prompt, temperature=0.2)
            out(f"{BOLD}AI Analysis:{RESET}\n")
            for ln in response.strip().splitlines():
                out(f"  {ln}")
            out("")
            out(f"  {DIM}Run /debug {session_id} again after applying the fix.{RESET}\n")
        except Exception as exc:
            out(f"  {YELLOW}Could not reach LLM: {exc}{RESET}")
            out(f"  {DIM}Check /status or switch provider with /provider.{RESET}\n")
