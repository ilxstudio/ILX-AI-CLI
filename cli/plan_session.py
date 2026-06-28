"""Plan-then-act mode -- inspect repo, propose plan, execute on approval."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig
    from cli.context import ContextManager

from cli.display_compat import out, out_error, out_status
from cli.display import BOLD, DIM, GREEN, YELLOW, RED, CYAN, RESET

_log = logging.getLogger("ilx_cli.plan_session")

_PLANS_DIR = Path.home() / ".ilx_cli" / "plans"

_PLAN_SYSTEM = """\
You are a senior software architect. The user has a coding task.
Inspect the provided repo context and produce a numbered implementation plan.

Output format — EXACTLY this structure, no deviation:
TASK: <one-line summary of the user's goal>

PLAN:
1. <action> in <file> -- <why>
2. <action> in <file> -- <why>
...

RISKS:
- <risk or consideration>

TESTS:
- <what to test / test command>

Rules:
- Be specific: name real files and functions
- Keep each step actionable (one file per step when possible)
- Limit to 10 steps max
- No prose outside the structure above
"""


@dataclass
class PlanStep:
    number: int
    description: str
    done: bool = False


@dataclass
class Plan:
    task:    str
    steps:   list[PlanStep] = field(default_factory=list)
    risks:   list[str] = field(default_factory=list)
    tests:   list[str] = field(default_factory=list)
    raw:     str = ""
    saved_at: str = ""


class PlanSession:
    """Manages the /plan workflow: generate, review, approve, execute."""

    def __init__(self, cfg: "AppConfig", ctx: "ContextManager") -> None:
        self._cfg = cfg
        self._ctx = ctx
        self._current: Plan | None = None

    # ── public commands ───────────────────────────────────────────────────

    def cmd_plan(self, args: list[str], chat_history: list[dict]) -> None:
        """/plan [approve|cancel|edit|status|help]"""
        sub = args[0].lower() if args else ""

        if not sub or sub == "help":
            self._plan_help()
        elif sub == "approve":
            self._plan_approve(chat_history)
        elif sub == "cancel":
            self._plan_cancel()
        elif sub == "status":
            self._plan_status()
        else:
            # Everything else is a task description
            task = " ".join(args)
            self._plan_generate(task, chat_history)

    # ── subcommands ───────────────────────────────────────────────────────

    def _plan_generate(self, task: str, chat_history: list[dict]) -> None:
        """Generate an implementation plan for *task*."""
        from app.core.spinner import Spinner

        out(f"\n{BOLD}Generating implementation plan...{RESET}")

        # Build context
        context_parts: list[str] = []
        wf = self._cfg.working_folder
        if wf and Path(wf).is_dir():
            context_parts.append(self._repo_context(wf))
        if chat_history:
            recent = chat_history[-4:]
            context_parts.append("Recent conversation:\n" + "\n".join(
                f"{m['role'].capitalize()}: {str(m.get('content',''))[:300]}"
                for m in recent
            ))

        user_msg = f"Task: {task}\n\n" + "\n\n".join(context_parts)

        try:
            from codex.app.llm_client import get_llm_client
            client = get_llm_client(self._cfg)
            with Spinner("Analyzing codebase"):
                response = client.chat(
                    messages=[{"role": "user", "content": user_msg}],
                    system=_PLAN_SYSTEM,
                    temperature=0.2,
                    max_tokens=2048,
                )
        except Exception as exc:
            out_error(f"{RED}Plan generation failed: {exc}{RESET}")
            return

        plan = self._parse_plan(response)
        plan.raw = response
        self._current = plan
        self._save_plan(plan)
        self._print_plan(plan)
        out(f"\n  {DIM}Review the plan above.{RESET}")
        out(f"  {CYAN}/plan approve{RESET}  -- execute all steps")
        out(f"  {CYAN}/plan cancel{RESET}   -- discard\n")

    def _plan_approve(self, chat_history: list[dict]) -> None:
        """Execute the current plan step by step."""
        if not self._current:
            out(f"  {YELLOW}No active plan. Run: /plan <your task>{RESET}")
            return

        plan = self._current
        out(f"\n{BOLD}Executing plan: {plan.task}{RESET}\n")

        for step in plan.steps:
            out(f"  {CYAN}[{step.number}]{RESET} {step.description}")
            self._execute_step(step, chat_history)
            step.done = True
            out(f"      {GREEN}[done]{RESET}")
            out("")

        out(f"\n{GREEN}Plan complete!{RESET}")
        if plan.tests:
            out(f"\n{BOLD}Suggested tests:{RESET}")
            for t in plan.tests:
                out(f"  {DIM}{t}{RESET}")
        out("")
        self._current = None

    def _plan_cancel(self) -> None:
        if self._current:
            out(f"  {DIM}Plan discarded: {self._current.task}{RESET}")
            self._current = None
        else:
            out(f"  {YELLOW}No active plan to cancel.{RESET}")

    def _plan_status(self) -> None:
        if not self._current:
            out(f"\n  {DIM}No active plan.{RESET}")
            out(f"  Start one with: {CYAN}/plan <your task>{RESET}\n")
            return
        plan = self._current
        out(f"\n{BOLD}Current plan: {plan.task}{RESET}")
        for step in plan.steps:
            marker = GREEN + "[x]" + RESET if step.done else DIM + "[ ]" + RESET
            out(f"  {marker} {step.number}. {step.description}")
        out("")

    def _plan_help(self) -> None:
        out(f"\n{BOLD}/plan{RESET} -- inspect repo and propose a structured implementation plan")
        out(f"  {CYAN}/plan <task>{RESET}       Generate a plan for the given task")
        out(f"  {CYAN}/plan approve{RESET}      Execute the approved plan step by step")
        out(f"  {CYAN}/plan cancel{RESET}       Discard the current plan")
        out(f"  {CYAN}/plan status{RESET}       Show current plan and step completion\n")

    # ── helpers ───────────────────────────────────────────────────────────

    def _repo_context(self, wf: str) -> str:
        """Build a compact repo map for the plan prompt."""
        from app.core.repo_map import RepoMap
        try:
            rm = RepoMap(wf)
            return rm.to_prompt_block(budget_kb=16)
        except Exception:
            return f"Workspace: {wf}"

    def _execute_step(self, step: PlanStep, chat_history: list[dict]) -> None:
        """Send a step to the code agent for execution."""
        try:
            from codex.app.llm_client import get_llm_client
            client = get_llm_client(self._cfg)
            history = chat_history[-6:] if chat_history else []
            response = client.chat(
                messages=[
                    *history,
                    {"role": "user", "content": f"Execute this step: {step.description}"}
                ],
                system=(
                    "You are a coding agent. Execute the given step precisely. "
                    "Output only the files you create or modify using the format:\n"
                    "FILE: path/to/file.py\n```python\n<content>\n```"
                ),
                temperature=0.2,
                max_tokens=4096,
            )
            # File writes are handled by the code session's MCP client in a full
            # execution flow; here we surface the LLM output so the user sees it.
            if response and response.strip():
                for ln in response.strip().splitlines()[:30]:
                    out(f"      {DIM}{ln}{RESET}")
        except Exception as exc:
            out_error(f"    {YELLOW}Step execution error: {exc}{RESET}")

    def _parse_plan(self, text: str) -> Plan:
        plan = Plan(task="")
        section = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            upper = stripped.upper()
            if upper.startswith("TASK:"):
                plan.task = stripped[5:].strip()
            elif upper.startswith("PLAN:"):
                section = "plan"
            elif upper.startswith("RISKS:"):
                section = "risks"
            elif upper.startswith("TESTS:"):
                section = "tests"
            elif section == "plan" and stripped[0].isdigit() and "." in stripped:
                dot = stripped.index(".")
                try:
                    num = int(stripped[:dot])
                    desc = stripped[dot+1:].strip()
                    plan.steps.append(PlanStep(number=num, description=desc))
                except ValueError:
                    pass
            elif section == "risks" and stripped.startswith("-"):
                plan.risks.append(stripped[1:].strip())
            elif section == "tests" and stripped.startswith("-"):
                plan.tests.append(stripped[1:].strip())
        return plan

    def _print_plan(self, plan: Plan) -> None:
        out(f"\n{BOLD}Plan: {plan.task}{RESET}\n")
        if plan.steps:
            out(f"{BOLD}Steps:{RESET}")
            for step in plan.steps:
                out(f"  {CYAN}{step.number}.{RESET} {step.description}")
        if plan.risks:
            out(f"\n{BOLD}Risks:{RESET}")
            for r in plan.risks:
                out(f"  {YELLOW}!{RESET} {r}")
        if plan.tests:
            out(f"\n{BOLD}Tests:{RESET}")
            for t in plan.tests:
                out(f"  {DIM}{t}{RESET}")

    def _save_plan(self, plan: Plan) -> None:
        try:
            _PLANS_DIR.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            p = _PLANS_DIR / f"plan_{ts}.json"
            p.write_text(json.dumps({
                "task": plan.task,
                "steps": [{"n": s.number, "desc": s.description} for s in plan.steps],
                "risks": plan.risks,
                "tests": plan.tests,
            }, indent=2), encoding="utf-8")
            plan.saved_at = str(p)
        except Exception as exc:
            _log.debug("Could not save plan: %s", exc)
