from __future__ import annotations

import ast
import difflib
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .chunker import ProjectChunker
from .llm_client import BaseLLMClient
from .logger import AgentLogger, generate_run_id
from .memory import AgentMemory, AttemptRecord
from .paths import AppPaths
from .prompt_builder import PromptBuilder
from .response_parser import ParseError, ResponseParser
from .runner import CommandRunner, RunResult
from .validator import ResponseValidator, ValidationError
from .workspace import WorkspaceManager

try:
    from app.core import git_helper as _git_helper
    from app.core import hooks as _hooks
    from app.core import project_rules as _project_rules
except ImportError:
    _project_rules = None  # type: ignore[assignment]
    _hooks = None          # type: ignore[assignment]
    _git_helper = None     # type: ignore[assignment]

_EXIT_CODE_HINTS: dict[int, str] = {
    0:   "success",
    1:   "generic error",
    2:   "misuse / argparse error",
    124: "timed out",
    126: "permission denied",
    127: "command not found",
    130: "interrupted (SIGINT)",
    137: "killed (SIGKILL / OOM)",
    139: "segmentation fault",
    143: "terminated (SIGTERM)",
    -1:  "killed by host before exit",
}


def _classify_exit_code(code: int, timed_out: bool) -> str:
    if timed_out:
        return "timed out"
    return _EXIT_CODE_HINTS.get(code, "")


def _python_syntax_errors(workspace: Path, files: list[str]) -> list[str]:
    errs: list[str] = []
    for rel in files:
        if not rel.endswith(".py"):
            continue
        path = workspace / rel
        try:
            src = path.read_text(encoding="utf-8")
        except OSError as exc:
            errs.append(f"{rel}: could not read back: {exc}")
            continue
        try:
            ast.parse(src, filename=rel)
        except SyntaxError as exc:
            line_no  = exc.lineno or 0
            line_txt = exc.text.rstrip() if exc.text else ""
            errs.append(
                f"{rel}: SyntaxError at line {line_no}: {exc.msg}\n"
                f"   >>> {line_txt}"
            )
    return errs


@dataclass
class AgentResult:
    success:       bool
    attempts:      int
    final_output:  str
    final_error:   str | None
    files_written: list[str]
    run_id:        str
    commit_info:   str = ""


class CodingAgent:
    def __init__(
        self,
        llm_client:           BaseLLMClient,
        on_status:            Callable[[str], None] | None = None,
        on_output:            Callable[[str, str], None] | None = None,
        permission_callback:  Callable[[str, str, str], bool] | None = None,
        max_attempts:         int = 5,
        run_timeout:          int = 30,
        auto_commit:          bool = False,
        commit_message_prefix: str = "ilx: ",
        on_diff:              Callable[[str, str, str], None] | None = None,
    ):
        self.llm_client            = llm_client
        self.on_status             = on_status
        self.on_output             = on_output
        self.permission_callback   = permission_callback
        self.max_attempts          = max_attempts
        self.run_timeout           = run_timeout
        self.auto_commit           = auto_commit
        self.commit_message_prefix = commit_message_prefix
        self.on_diff               = on_diff

    def run(
        self,
        task:           str,
        working_folder: str = "",
    ) -> AgentResult:
        project_name = "active_project"
        paths        = AppPaths(project_name)

        if working_folder:
            paths.workspace       = Path(working_folder)
            paths.workspace.mkdir(parents=True, exist_ok=True)
            paths.project_index   = paths.workspace / ".project_index"
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

        self._emit("Scanning workspace...")
        try:
            chunker.index_workspace()
        except Exception as exc:
            logger.log("index_error", {"error": str(exc)})

        file_tree      = chunker.get_file_tree()
        existing_files = [f for f in file_tree.splitlines() if f.strip()]
        if existing_files:
            self._emit(f"Found {len(existing_files)} existing file(s) — reading contents...")
        else:
            self._emit("Empty workspace — ready to create files")

        file_contents = chunker.get_file_contents()

        # Load project rules once for this run
        rules_text = ""
        if _project_rules is not None:
            try:
                rules_text = _project_rules.system_prompt_prefix(working_folder)
            except Exception:
                pass

        self._emit("Building prompt...")
        prompt = prompt_builder.build_initial(
            task=task,
            file_tree=file_tree,
            file_contents=file_contents,
            rules=rules_text,
        )

        logger.log("start", {"task": task, "max_attempts": self.max_attempts})

        all_files_written: list[str] = []

        for attempt in range(1, self.max_attempts + 1):
            logger.set_attempt(attempt)
            self._emit(f"Attempt {attempt}/{self.max_attempts}: calling LLM...")

            try:
                raw = self.llm_client.generate(prompt)
                self._emit("Response received — parsing...")
                logger.log("llm_call", {"prompt_len": len(prompt), "response_len": len(raw)})

                try:
                    response = parser.parse(raw)
                except ParseError as exc:
                    self._emit(f"Parse error on attempt {attempt} — retrying...")
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

                self._emit("Validating response...")
                try:
                    warnings = validator.validate(response)
                except ValidationError as exc:
                    self._emit(f"Validation failed on attempt {attempt} — retrying...")
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

                if warnings:
                    logger.log("warnings", {"warnings": [{"field": w.field, "message": w.message} for w in warnings]})

                attempt_files_written: list[str] = []
                attempt_denied:        list[str] = []

                for fa in response.files:
                    try:
                        if fa.action in ("replace", "append"):
                            line_count = len(fa.content.splitlines()) if fa.content else 0
                            full_path  = str((paths.workspace / fa.path).resolve())
                            detail     = f"{fa.action.upper()}  ·  {line_count} line(s)"

                            # Show unified diff before permission prompt (replace only)
                            if fa.action == "replace":
                                try:
                                    existing_for_diff = workspace.read_file(fa.path)
                                except (FileNotFoundError, OSError):
                                    existing_for_diff = ""
                                if existing_for_diff != (fa.content or ""):
                                    old_lines = existing_for_diff.splitlines(keepends=True)
                                    new_lines = (fa.content or "").splitlines(keepends=True)
                                    diff_lines = list(difflib.unified_diff(
                                        old_lines, new_lines,
                                        fromfile=f"a/{fa.path}",
                                        tofile=f"b/{fa.path}",
                                        lineterm="",
                                    ))
                                    for dl in diff_lines[:80]:
                                        self._emit_output("diff", dl)
                                    if len(diff_lines) > 80:
                                        self._emit_output("diff", f"… ({len(diff_lines) - 80} more lines)")

                            # Fire PreToolUse hook before permission check
                            if _hooks is not None:
                                hook_result = _hooks.trigger("PreToolUse", {
                                    "tool": "write_file",
                                    "path": full_path,
                                    "action": fa.action,
                                })
                                if not hook_result.allowed:
                                    self._emit(f"Blocked by hook: {fa.path} — {hook_result.reason}")
                                    self._emit_output("file", f"{fa.path}  ·  blocked by hook")
                                    logger.log("file_write_blocked_by_hook", {"path": fa.path, "reason": hook_result.reason})
                                    attempt_denied.append(fa.path)
                                    continue
                            if self.permission_callback is not None and not self.permission_callback(
                                "write", full_path, detail
                            ):
                                self._emit(f"Denied: {fa.path}")
                                self._emit_output("file", f"{fa.path}  ·  denied by user")
                                logger.log("file_write_denied", {"path": fa.path, "action": fa.action})
                                attempt_denied.append(fa.path)
                                continue
                            if fa.action == "append":
                                self._emit(f"Appending to: {fa.path}  ({line_count} lines)")
                                try:
                                    existing = workspace.read_file(fa.path)
                                except FileNotFoundError:
                                    existing = ""
                                separator = ""
                                if existing and not existing.endswith(("\n", "\r")) \
                                        and fa.content and not fa.content.startswith(("\n", "\r")):
                                    separator = "\n"
                                workspace.write_file(fa.path, existing + separator + fa.content)
                            else:
                                self._emit(f"Writing: {fa.path}  ({line_count} lines)")
                                try:
                                    old_content = workspace.read_file(fa.path)
                                except (FileNotFoundError, OSError):
                                    old_content = ""
                                workspace.write_file(fa.path, fa.content)
                                if self.on_diff and fa.action in ("replace", "create") and fa.content:
                                    try:
                                        self.on_diff(fa.path, old_content, fa.content)
                                    except Exception:
                                        pass
                            self._emit_output("file", f"{fa.path}  ·  {line_count} lines written")
                            attempt_files_written.append(fa.path)
                            all_files_written.append(fa.path)

                        elif fa.action == "delete":
                            full_path = str((paths.workspace / fa.path).resolve())
                            if self.permission_callback is not None and not self.permission_callback(
                                "delete", full_path, "DELETE"
                            ):
                                self._emit(f"Denied: {fa.path}")
                                attempt_denied.append(fa.path)
                                continue
                            self._emit(f"Deleting: {fa.path}")
                            workspace.delete_file(fa.path)
                            self._emit_output("file", f"{fa.path}  ·  deleted")
                            attempt_files_written.append(fa.path)
                            all_files_written.append(fa.path)

                        logger.log("file_write", {"path": fa.path, "action": fa.action})

                    except Exception as exc:
                        self._emit(f"File error: {fa.path} — {exc}")
                        logger.log("file_write_error", {"path": fa.path, "error": str(exc)})

                if response.command_to_run:
                    if self.permission_callback is not None and not self.permission_callback(
                        "command", response.command_to_run, f"cwd: {paths.workspace}"
                    ):
                        self._emit(f"Command denied: {response.command_to_run}")
                        logger.log("command_denied", {"command": response.command_to_run})
                        if attempt_files_written:
                            ci = self._maybe_commit(working_folder, all_files_written, "(command denied; files written)")
                            return AgentResult(
                                success=True, attempts=attempt,
                                final_output="(command denied; files were written)",
                                final_error=None, files_written=all_files_written, run_id=run_id,
                                commit_info=ci,
                            )
                        return AgentResult(
                            success=False, attempts=attempt, final_output="",
                            final_error="Command denied by user", files_written=all_files_written, run_id=run_id,
                        )

                    self._emit(f"Running: {response.command_to_run}")
                    self._emit_output("command", response.command_to_run)
                    result: RunResult = runner.run(
                        response.command_to_run,
                        timeout=self.run_timeout,
                        on_line=self._emit_output,
                    )
                    self._emit("Checking result...")
                    logger.log("run", {
                        "command": response.command_to_run,
                        "exit_code": result.exit_code,
                        "stdout": result.stdout[:1000],
                        "stderr": result.stderr[:1000],
                        "timed_out": result.timed_out,
                    })

                    if result.exit_code == 0:
                        self._emit(f"Command succeeded on attempt {attempt}")
                        logger.log("success", {"attempt": attempt, "files_written": attempt_files_written})
                        memory.add(AttemptRecord(
                            attempt=attempt, files_written=attempt_files_written,
                            command=response.command_to_run, exit_code=result.exit_code,
                            error_snippet=None, outcome="success",
                        ))
                        ci = self._maybe_commit(working_folder, all_files_written, task)
                        return AgentResult(
                            success=True, attempts=attempt, final_output=result.stdout,
                            final_error=None, files_written=all_files_written, run_id=run_id,
                            commit_info=ci,
                        )
                    else:
                        self._emit(f"Command failed (exit {result.exit_code}) — analyzing error...")
                        error_snippet = (result.stderr or result.stdout)[:500]
                        chunk         = chunker.find_chunk_for_error(result.stderr)
                        exit_hint     = _classify_exit_code(result.exit_code, result.timed_out)
                        enriched_error = (
                            f"$ {response.command_to_run}\n"
                            f"exit code: {result.exit_code}"
                            + (f"  ({exit_hint})" if exit_hint else "")
                            + (f"  [TIMED OUT after {self.run_timeout}s]" if result.timed_out else "")
                            + f"\n\nstderr:\n{error_snippet}"
                        )
                        memory.add(AttemptRecord(
                            attempt=attempt, files_written=attempt_files_written,
                            command=response.command_to_run, exit_code=result.exit_code,
                            error_snippet=error_snippet,
                            outcome="timeout" if result.timed_out else "failed",
                        ))
                        prompt = prompt_builder.build_repair(
                            task=task, error=enriched_error, chunk=chunk,
                            previous_attempts=memory.summary_for_prompt(),
                            rules=rules_text,
                        )
                        continue

                else:
                    syntax_errs = _python_syntax_errors(paths.workspace, attempt_files_written)
                    if syntax_errs:
                        joined = "\n".join(syntax_errs[:5])
                        self._emit(f"Syntax check failed on attempt {attempt} — retrying...")
                        logger.log("syntax_error", {"attempt": attempt, "errors": syntax_errs[:5]})
                        memory.add(AttemptRecord(
                            attempt=attempt, files_written=attempt_files_written,
                            command=None, exit_code=None, error_snippet=joined[:500],
                            outcome="syntax_error",
                        ))
                        prompt = prompt_builder.build_repair(
                            task=task,
                            error=(
                                "The Python file(s) you wrote did not parse:\n\n" + joined
                                + "\n\nFix the syntax error(s) and return the complete corrected file(s) in the JSON."
                            ),
                            chunk=chunker.find_chunk_for_error(joined),
                            previous_attempts=memory.summary_for_prompt(),
                            rules=rules_text,
                        )
                        continue

                    if not attempt_files_written:
                        self._emit(f"Model returned no files on attempt {attempt} — retrying...")
                        logger.log("empty_response", {"attempt": attempt, "summary": response.summary[:200]})
                        memory.add(AttemptRecord(
                            attempt=attempt, files_written=[], command=None, exit_code=None,
                            error_snippet=f"Model returned empty files list: {response.summary[:160]!r}",
                            outcome="empty_response",
                        ))
                        prompt = prompt_builder.build_repair(
                            task=task,
                            error=(
                                "Your previous response had files=[] (no files written). "
                                "The TASK is real and must be implemented — write the actual "
                                "file(s) it describes, with full content, and return them in the files array."
                            ),
                            chunk="", previous_attempts=memory.summary_for_prompt(),
                            rules=rules_text,
                        )
                        continue

                    self._emit(f"{len(attempt_files_written)} file(s) written successfully")
                    logger.log("success", {"attempt": attempt, "files_written": attempt_files_written})
                    memory.add(AttemptRecord(
                        attempt=attempt, files_written=attempt_files_written,
                        command=None, exit_code=None, error_snippet=None, outcome="success",
                    ))
                    ci = self._maybe_commit(working_folder, all_files_written, response.summary)
                    return AgentResult(
                        success=True, attempts=attempt, final_output=response.summary,
                        final_error=None, files_written=all_files_written, run_id=run_id,
                        commit_info=ci,
                    )

            except Exception as exc:
                import logging as _logging
                _log = _logging.getLogger(__name__)
                tb  = traceback.format_exc()
                logger.log("unexpected_error", {"error": str(exc), "traceback": tb[:1000]})
                _log.error("Agent attempt %d failed: %s", attempt, exc, exc_info=True)
                from app.core.error_classifier import ErrorClass, classify_error
                classified = classify_error(exc, getattr(self.llm_client, 'model', ''))

                # Non-retriable classes abort immediately
                terminal_classes = {
                    ErrorClass.AUTH, ErrorClass.QUOTA, ErrorClass.CONTENT_POLICY,
                    ErrorClass.MODEL_NOT_FOUND, ErrorClass.PERMANENT,
                }
                if classified.error_class in terminal_classes:
                    last_error = f"{classified.message}\n\nSuggestion: {classified.suggestion}"
                    self._emit(f"Aborting — {classified.message}")
                    return AgentResult(
                        success=False, attempts=attempt, final_output="",
                        final_error=last_error, files_written=all_files_written, run_id=run_id,
                    )
                else:
                    # TRANSIENT, RATE_LIMIT, CONTEXT_LENGTH — retry with repair prompt
                    last_error = str(exc)
                    if classified.error_class == ErrorClass.RATE_LIMIT and classified.retry_after > 0:
                        import time
                        time.sleep(min(classified.retry_after, 30))

                memory.add(AttemptRecord(
                    attempt=attempt, files_written=[], command=None, exit_code=None,
                    error_snippet=str(exc)[:200], outcome="failed",
                ))
                prompt = prompt_builder.build_repair(
                    task=task, error=last_error, chunk="",
                    previous_attempts=memory.summary_for_prompt(),
                    rules=rules_text,
                )
                continue

        self._emit(f"Failed after {self.max_attempts} attempts")
        last        = memory.last()
        final_error = last.error_snippet if last else "Unknown error after all attempts"
        logger.log("failure", {"max_attempts": self.max_attempts, "final_error": final_error})
        return AgentResult(
            success=False, attempts=self.max_attempts, final_output="",
            final_error=final_error, files_written=all_files_written, run_id=run_id,
        )

    def run_streaming(
        self,
        task: str,
        working_folder: str = "",
        on_chunk: Callable[[str], None] | None = None,
        on_tool: Callable[[str, dict], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> AgentResult:
        """Run the agent and stream tokens via callbacks instead of blocking.

        on_chunk(text)        — called for each text token
        on_tool(name, args)   — called when a tool is about to be invoked
        on_status(msg)        — called for status updates ("Autofix attempt 2/5")

        Falls back to non-streaming generate() for clients that lack chat_stream().
        Returns an AgentResult identical to run().

        Implementation lives in controller_streaming.run_streaming_impl() to keep
        this file under the 700-line limit.
        """
        from .controller_streaming import run_streaming_impl
        return run_streaming_impl(self, task, working_folder, on_chunk, on_tool, on_status)

    def _maybe_commit(self, working_folder: str, files: list[str], summary: str) -> str:
        """Auto-commit touched files if auto_commit is enabled. Returns commit info or ''."""
        if not self.auto_commit or not files or _git_helper is None:
            return ""
        try:
            msg = self.commit_message_prefix + summary[:72 - len(self.commit_message_prefix)]
            ok, out = _git_helper.commit(working_folder, msg, add_all=False)
            if ok:
                self._emit(f"Auto-committed: {msg}")
                return out.splitlines()[0] if out else msg
        except Exception as exc:
            self._emit(f"Auto-commit skipped: {exc}")
        return ""

    def _emit(self, message: str) -> None:
        if self.on_status is not None:
            try:
                self.on_status(message)
            except Exception:
                pass

    def _emit_output(self, stream_type: str, text: str) -> None:
        if self.on_output is not None:
            try:
                self.on_output(stream_type, text)
            except Exception:
                pass
