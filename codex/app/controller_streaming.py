"""Streaming implementation for CodingAgent.

Extracted from controller.py to keep that file under 700 lines.
Do not import this module directly — use CodingAgent.run_streaming() instead.
"""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .paths import AppPaths
from .workspace import WorkspaceManager
from .runner import CommandRunner, RunResult
from .logger import AgentLogger, generate_run_id
from .llm_client import _CODEX_SYSTEM
from .response_parser import ResponseParser, ParseError
from .validator import ResponseValidator, ValidationError
from .chunker import ProjectChunker
from .memory import AgentMemory, AttemptRecord
from .prompt_builder import PromptBuilder
from .controller import AgentResult, _classify_exit_code

if TYPE_CHECKING:
    from .controller import CodingAgent

try:
    from app.core import project_rules as _project_rules
except ImportError:
    _project_rules = None  # type: ignore[assignment]


def run_streaming_impl(
    agent: "CodingAgent",
    task: str,
    working_folder: str,
    on_chunk: Callable[[str], None] | None,
    on_tool: Callable[[str, dict], None] | None,
    on_status: Callable[[str], None] | None,
) -> AgentResult:
    """Core streaming loop — called by CodingAgent.run_streaming()."""
    # Swap in the caller-supplied on_status for the duration of this call
    _saved_status = agent.on_status
    if on_status is not None:
        agent.on_status = on_status

    def _emit_tool(name: str, args: dict) -> None:
        if on_tool is not None:
            try:
                on_tool(name, args)
            except Exception:
                pass

    paths = AppPaths("active_project")

    if working_folder:
        paths.workspace     = Path(working_folder)
        paths.workspace.mkdir(parents=True, exist_ok=True)
        paths.project_index = paths.workspace / ".project_index"
        paths.project_index.mkdir(parents=True, exist_ok=True)

    workspace      = WorkspaceManager(paths.workspace)
    runner         = CommandRunner(paths.workspace)
    run_id         = generate_run_id()
    logger         = AgentLogger(paths.logs, run_id)
    memory         = AgentMemory(max_history=5)
    chunker        = ProjectChunker(paths.workspace, paths.project_index)
    prompt_builder = PromptBuilder(paths.prompts)
    parser         = ResponseParser()
    validator      = ResponseValidator()

    logger.set_attempt(0)
    agent._emit("Scanning workspace...")
    try:
        chunker.index_workspace()
    except Exception as exc:
        logger.log("index_error", {"error": str(exc)})

    file_tree      = chunker.get_file_tree()
    existing_files = [f for f in file_tree.splitlines() if f.strip()]
    if existing_files:
        agent._emit(f"Found {len(existing_files)} existing file(s) — reading contents...")
    else:
        agent._emit("Empty workspace — ready to create files")

    file_contents = chunker.get_file_contents()

    rules_text = ""
    if _project_rules is not None:
        try:
            rules_text = _project_rules.system_prompt_prefix(working_folder)
        except Exception:
            pass

    agent._emit("Building prompt...")
    prompt = prompt_builder.build_initial(
        task=task,
        file_tree=file_tree,
        file_contents=file_contents,
        rules=rules_text,
    )
    logger.log("start", {"task": task, "max_attempts": agent.max_attempts, "mode": "streaming"})

    all_files_written: list[str] = []

    try:
        for attempt in range(1, agent.max_attempts + 1):
            logger.set_attempt(attempt)
            agent._emit(f"Attempt {attempt}/{agent.max_attempts}: calling LLM (streaming)...")

            try:
                raw = _call_llm_streaming(agent, prompt, attempt, on_chunk, _emit_tool)
                agent._emit("Response received — parsing...")
                logger.log("llm_call", {"prompt_len": len(prompt), "response_len": len(raw)})

                try:
                    response = parser.parse(raw)
                except ParseError as exc:
                    agent._emit(f"Parse error on attempt {attempt} — retrying...")
                    logger.log("parse_error", {"error": str(exc), "raw_snippet": raw[:300]})
                    memory.add(AttemptRecord(
                        attempt=attempt, files_written=[], command=None,
                        exit_code=None, error_snippet=str(exc)[:200], outcome="parse_error",
                    ))
                    prompt = prompt_builder.build_repair(
                        task=task, error=f"Fix your JSON format: {exc}",
                        chunk="", previous_attempts=memory.summary_for_prompt(),
                        rules=rules_text,
                    )
                    continue

                agent._emit("Validating response...")
                try:
                    validator.validate(response)
                except ValidationError as exc:
                    agent._emit(f"Validation failed on attempt {attempt} — retrying...")
                    logger.log("validation_error", {"error": str(exc)})
                    memory.add(AttemptRecord(
                        attempt=attempt, files_written=[], command=None,
                        exit_code=None, error_snippet=str(exc)[:200], outcome="validation_error",
                    ))
                    prompt = prompt_builder.build_repair(
                        task=task, error=str(exc),
                        chunk="", previous_attempts=memory.summary_for_prompt(),
                        rules=rules_text,
                    )
                    continue

                attempt_files_written: list[str] = []

                for fa in response.files:
                    try:
                        _apply_file_action(
                            agent, fa, paths, workspace, logger,
                            attempt_files_written, all_files_written, _emit_tool,
                        )
                    except Exception as exc:
                        agent._emit(f"File error: {fa.path} — {exc}")
                        logger.log("file_write_error", {"path": fa.path, "error": str(exc)})

                if response.command_to_run:
                    result_or_return = _handle_command(
                        agent, response.command_to_run, paths, runner, logger,
                        chunker, prompt_builder, memory, all_files_written,
                        attempt_files_written, attempt, task, run_id, rules_text,
                        working_folder, _emit_tool,
                    )
                    if isinstance(result_or_return, AgentResult):
                        return result_or_return
                    # result_or_return is a new prompt string — continue loop
                    prompt = result_or_return
                    continue

                # No command — check files
                if not attempt_files_written:
                    agent._emit(f"No files written on attempt {attempt} — retrying...")
                    memory.add(AttemptRecord(
                        attempt=attempt, files_written=[], command=None, exit_code=None,
                        error_snippet="Model returned empty files list", outcome="empty_response",
                    ))
                    prompt = prompt_builder.build_repair(
                        task=task,
                        error="Your previous response had files=[] — write the actual file(s).",
                        chunk="", previous_attempts=memory.summary_for_prompt(),
                        rules=rules_text,
                    )
                    continue

                agent._emit(f"{len(attempt_files_written)} file(s) written successfully")
                logger.log("success", {"attempt": attempt, "files_written": attempt_files_written})
                ci = agent._maybe_commit(working_folder, all_files_written, response.summary)
                return AgentResult(
                    success=True, attempts=attempt, final_output=response.summary,
                    final_error=None, files_written=all_files_written, run_id=run_id,
                    commit_info=ci,
                )

            except Exception as exc:
                tb = traceback.format_exc()
                logger.log("unexpected_error", {"error": str(exc), "traceback": tb[:1000]})
                msg = str(exc).lower()
                if any(k in msg for k in (" 404", "not found", "401", "unauthorized", "connection")):
                    agent._emit(f"Aborting — LLM not reachable: {str(exc)[:200]}")
                    return AgentResult(
                        success=False, attempts=attempt, final_output="",
                        final_error=str(exc), files_written=all_files_written, run_id=run_id,
                    )
                memory.add(AttemptRecord(
                    attempt=attempt, files_written=[], command=None, exit_code=None,
                    error_snippet=str(exc)[:200], outcome="failed",
                ))
                prompt = prompt_builder.build_repair(
                    task=task, error=str(exc), chunk="",
                    previous_attempts=memory.summary_for_prompt(),
                    rules=rules_text,
                )
                continue

        agent._emit(f"Failed after {agent.max_attempts} attempts")
        last        = memory.last()
        final_error = last.error_snippet if last else "Unknown error after all attempts"
        logger.log("failure", {"max_attempts": agent.max_attempts, "final_error": final_error})
        return AgentResult(
            success=False, attempts=agent.max_attempts, final_output="",
            final_error=final_error, files_written=all_files_written, run_id=run_id,
        )
    finally:
        agent.on_status = _saved_status


# ── Private helpers ───────────────────────────────────────────────────────────

def _call_llm_streaming(
    agent: "CodingAgent",
    prompt: str,
    attempt: int,
    on_chunk: Callable[[str], None] | None,
    emit_tool: Callable[[str, dict], None],
) -> str:
    """Call the LLM, streaming tokens if supported. Returns the full response string."""
    messages = [{"role": "user", "content": prompt}]
    if hasattr(agent.llm_client, "chat_stream"):
        emit_tool("chat_stream", {"attempt": attempt})
        chunks: list[str] = []
        for chunk in agent.llm_client.chat_stream(messages, system=_CODEX_SYSTEM):
            chunks.append(chunk)
            if on_chunk is not None:
                try:
                    on_chunk(chunk)
                except Exception:
                    pass
        return "".join(chunks)
    # Fallback: non-streaming generate
    raw = agent.llm_client.generate(prompt)
    if on_chunk is not None:
        try:
            on_chunk(raw)
        except Exception:
            pass
    return raw


def _apply_file_action(
    agent: "CodingAgent",
    fa,
    paths,
    workspace,
    logger,
    attempt_files_written: list[str],
    all_files_written: list[str],
    emit_tool: Callable[[str, dict], None],
) -> None:
    """Write, append, or delete a single file from the LLM response."""
    if fa.action in ("replace", "append"):
        line_count = len(fa.content.splitlines()) if fa.content else 0
        full_path  = str((paths.workspace / fa.path).resolve())
        emit_tool("write_file", {"path": fa.path, "action": fa.action})
        if agent.permission_callback is not None and not agent.permission_callback(
            "write", full_path, f"{fa.action.upper()} · {line_count} line(s)"
        ):
            agent._emit(f"Denied: {fa.path}")
            return
        if fa.action == "append":
            try:
                existing = workspace.read_file(fa.path)
            except FileNotFoundError:
                existing = ""
            sep = "\n" if existing and not existing.endswith(("\n", "\r")) else ""
            workspace.write_file(fa.path, existing + sep + fa.content)
        else:
            workspace.write_file(fa.path, fa.content)
        agent._emit_output("file", f"{fa.path}  ·  {line_count} lines written")
        attempt_files_written.append(fa.path)
        all_files_written.append(fa.path)
    elif fa.action == "delete":
        full_path = str((paths.workspace / fa.path).resolve())
        emit_tool("delete_file", {"path": fa.path})
        if agent.permission_callback is not None and not agent.permission_callback(
            "delete", full_path, "DELETE"
        ):
            agent._emit(f"Denied: {fa.path}")
            return
        workspace.delete_file(fa.path)
        agent._emit_output("file", f"{fa.path}  ·  deleted")
        attempt_files_written.append(fa.path)
        all_files_written.append(fa.path)
    logger.log("file_write", {"path": fa.path, "action": fa.action})


def _handle_command(
    agent: "CodingAgent",
    command: str,
    paths,
    runner,
    logger,
    chunker,
    prompt_builder,
    memory,
    all_files_written: list[str],
    attempt_files_written: list[str],
    attempt: int,
    task: str,
    run_id: str,
    rules_text: str,
    working_folder: str,
    emit_tool: Callable[[str, dict], None],
):
    """Run the LLM-requested command. Returns AgentResult on terminal outcomes, else new prompt."""
    emit_tool("run_command", {"command": command})
    if agent.permission_callback is not None and not agent.permission_callback(
        "command", command, f"cwd: {paths.workspace}"
    ):
        agent._emit(f"Command denied: {command}")
        logger.log("command_denied", {"command": command})
        ci = agent._maybe_commit(working_folder, all_files_written, task) if attempt_files_written else ""
        return AgentResult(
            success=bool(attempt_files_written), attempts=attempt,
            final_output="(command denied)" if attempt_files_written else "",
            final_error=None if attempt_files_written else "Command denied by user",
            files_written=all_files_written, run_id=run_id,
            commit_info=ci,
        )

    agent._emit(f"Running: {command}")
    result: RunResult = runner.run(command, timeout=agent.run_timeout, on_line=agent._emit_output)
    logger.log("run", {
        "command": command,
        "exit_code": result.exit_code,
        "stdout": result.stdout[:1000],
        "stderr": result.stderr[:1000],
        "timed_out": result.timed_out,
    })

    if result.exit_code == 0:
        agent._emit(f"Command succeeded on attempt {attempt}")
        ci = agent._maybe_commit(working_folder, all_files_written, task)
        return AgentResult(
            success=True, attempts=attempt, final_output=result.stdout,
            final_error=None, files_written=all_files_written, run_id=run_id,
            commit_info=ci,
        )

    agent._emit(f"Command failed (exit {result.exit_code}) — retrying...")
    error_snippet = (result.stderr or result.stdout)[:500]
    chunk         = chunker.find_chunk_for_error(result.stderr)
    exit_hint     = _classify_exit_code(result.exit_code, result.timed_out)
    enriched      = (
        f"$ {command}\nexit code: {result.exit_code}"
        + (f"  ({exit_hint})" if exit_hint else "")
        + f"\n\nstderr:\n{error_snippet}"
    )
    memory.add(AttemptRecord(
        attempt=attempt, files_written=attempt_files_written,
        command=command, exit_code=result.exit_code,
        error_snippet=error_snippet,
        outcome="timeout" if result.timed_out else "failed",
    ))
    return prompt_builder.build_repair(
        task=task, error=enriched, chunk=chunk,
        previous_attempts=memory.summary_for_prompt(),
        rules=rules_text,
    )
