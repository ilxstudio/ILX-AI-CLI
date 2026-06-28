"""Plan-then-act mode -- inspect repo, propose plan, execute on approval."""
from __future__ import annotations

import datetime
import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig
    from cli.context import ContextManager

from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
from cli.display_compat import out, out_error

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
    plan_id:  str = ""


class PlanSession:
    """Manages the /plan workflow: generate, review, approve, execute."""

    def __init__(self, cfg: AppConfig, ctx: ContextManager) -> None:
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
        elif sub == "list":
            self._plan_list()
        elif sub == "resume":
            self._plan_resume(args[1:], chat_history)
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
            if step.done:
                out(f"  {DIM}[{step.number}] (already done) {step.description}{RESET}")
                continue
            out(f"  {CYAN}[{step.number}]{RESET} {step.description}")
            self._execute_step(step, chat_history)
            step.done = True
            self._update_plan_checkpoint(plan)
            out(f"      {GREEN}[done]{RESET}")
            out("")

        self._mark_plan_complete(plan)
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

    def _plan_list(self) -> None:
        """List all saved plans from disk."""
        _PLANS_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(_PLANS_DIR.glob("plan_*.json"), reverse=True)
        if not files:
            out(f"\n  {DIM}No saved plans found.{RESET}\n")
            return
        out(f"\n{BOLD}Saved plans:{RESET}")
        for f in files[:20]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                pid = data.get("id", f.stem)
                task = data.get("task", "")[:60]
                status = data.get("status", "unknown")
                completed = len(data.get("completed_steps", []))
                total = len(data.get("steps", []))
                color = GREEN if status == "complete" else YELLOW
                out(f"  {color}{pid}{RESET}  {DIM}[{completed}/{total}]{RESET}  {task}")
            except Exception:
                out(f"  {DIM}{f.name}{RESET}")
        out("")

    def _plan_resume(self, args: list[str], chat_history: list[dict]) -> None:
        """Resume a saved plan by ID."""
        if not args:
            out(f"  {YELLOW}Usage: /plan resume <id>{RESET}\n")
            return
        plan_id = args[0]
        _PLANS_DIR.mkdir(parents=True, exist_ok=True)
        matches = list(_PLANS_DIR.glob(f"plan_{plan_id}*.json"))
        # Also try exact match
        if not matches:
            matches = [p for p in _PLANS_DIR.glob("plan_*.json")
                       if json.loads(p.read_text(encoding="utf-8")).get("id", "") == plan_id]
        if not matches:
            out_error(f"  {RED}No plan found with id '{plan_id}'.{RESET}\n")
            return
        f = matches[0]
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            out_error(f"  {RED}Could not load plan: {exc}{RESET}\n")
            return
        completed_nums = set(data.get("completed_steps", []))
        plan = Plan(
            task=data.get("task", ""),
            risks=data.get("risks", []),
            tests=data.get("tests", []),
            plan_id=data.get("id", f.stem),
            saved_at=str(f),
        )
        for s in data.get("steps", []):
            n = s.get("n", 0)
            plan.steps.append(PlanStep(
                number=n,
                description=s.get("desc", ""),
                done=(n in completed_nums),
            ))
        self._current = plan
        pending = [s for s in plan.steps if not s.done]
        out(f"\n{BOLD}Resuming plan: {plan.task}{RESET}")
        out(f"  {DIM}Completed: {len(completed_nums)}/{len(plan.steps)} steps{RESET}")
        if pending:
            out(f"  Next: {CYAN}{pending[0].description}{RESET}")
        out(f"\n  Run {CYAN}/plan approve{RESET} to continue execution.\n")

    def _plan_help(self) -> None:
        out(f"\n{BOLD}/plan{RESET} -- inspect repo and propose a structured implementation plan")
        out(f"  {CYAN}/plan <task>{RESET}           Generate a plan for the given task")
        out(f"  {CYAN}/plan approve{RESET}          Execute the approved plan step by step")
        out(f"  {CYAN}/plan cancel{RESET}           Discard the current plan")
        out(f"  {CYAN}/plan status{RESET}           Show current plan and step completion")
        out(f"  {CYAN}/plan list{RESET}             List all saved plans")
        out(f"  {CYAN}/plan resume <id>{RESET}      Resume a saved plan from last checkpoint\n")

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
            plan_id = uuid.uuid4().hex[:8]
            plan.plan_id = plan_id
            p = _PLANS_DIR / f"plan_{plan_id}.json"
            p.write_text(json.dumps({
                "id": plan_id,
                "task": plan.task,
                "steps": [{"n": s.number, "desc": s.description} for s in plan.steps],
                "completed_steps": [],
                "risks": plan.risks,
                "tests": plan.tests,
                "created_at": datetime.datetime.utcnow().isoformat(),
                "status": "in_progress",
            }, indent=2), encoding="utf-8")
            plan.saved_at = str(p)
        except Exception as exc:
            _log.debug("Could not save plan: %s", exc)

    def _update_plan_checkpoint(self, plan: Plan) -> None:
        """Persist completed step numbers to disk after each step."""
        if not plan.saved_at:
            return
        try:
            p = Path(plan.saved_at)
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            data["completed_steps"] = [s.number for s in plan.steps if s.done]
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            _log.debug("Could not update plan checkpoint: %s", exc)

    def _mark_plan_complete(self, plan: Plan) -> None:
        """Mark the plan file as complete on disk."""
        if not plan.saved_at:
            return
        try:
            p = Path(plan.saved_at)
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            data["completed_steps"] = [s.number for s in plan.steps]
            data["status"] = "complete"
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            _log.debug("Could not mark plan complete: %s", exc)
