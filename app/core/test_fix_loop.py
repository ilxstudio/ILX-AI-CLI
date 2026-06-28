"""Test-fix loop engine — run tests, parse failures, patch, repeat."""
from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.test_fix_loop")


@dataclass
class TestFailure:
    test_id:  str    # nodeid or test name
    file:     str
    line:     int | None
    error:    str    # short error message
    traceback: str   # full traceback


@dataclass
class FixAttempt:
    attempt:   int
    failures_before: int
    failures_after:  int
    patches_applied: int
    error:     str = ""


@dataclass
class TestFixResult:
    attempts:        list[FixAttempt] = field(default_factory=list)
    final_pass:      bool = False
    final_failures:  list[TestFailure] = field(default_factory=list)
    total_fixed:     int = 0
    error:           str = ""


# ── Test runner detection ─────────────────────────────────────────────────────

def detect_test_runner(working_folder: str) -> list[str]:
    """Return a test command list for the workspace (pytest, jest, cargo test, etc.)."""
    wf = Path(working_folder)
    if (wf / "pyproject.toml").exists() or (wf / "pytest.ini").exists() or (wf / "setup.cfg").exists():
        return [sys.executable, "-m", "pytest", "--tb=short", "-q"]
    if (wf / "package.json").exists():
        return ["npm", "test", "--", "--reporter=verbose"]
    if (wf / "Cargo.toml").exists():
        return ["cargo", "test"]
    if (wf / "go.mod").exists():
        return ["go", "test", "./..."]
    return [sys.executable, "-m", "pytest", "--tb=short", "-q"]


# ── Failure parsers ───────────────────────────────────────────────────────────

def parse_pytest_failures(output: str) -> list[TestFailure]:
    """Parse pytest --tb=short output into structured failures."""
    failures: list[TestFailure] = []
    failed_re = re.compile(r"^FAILED\s+(\S+)\s+-\s+(.+)$", re.MULTILINE)
    loc_re = re.compile(r"(\S+\.py):(\d+):\s*(\w+Error[^\n]*)", re.MULTILINE)

    for m in failed_re.finditer(output):
        nodeid = m.group(1)
        errmsg = m.group(2)
        file_part = nodeid.split("::")[0] if "::" in nodeid else nodeid
        lineno: int | None = None
        loc = loc_re.search(output[m.start():m.start() + 2000])
        if loc:
            try:
                lineno = int(loc.group(2))
            except ValueError:
                pass
        failures.append(TestFailure(
            test_id=nodeid,
            file=file_part,
            line=lineno,
            error=errmsg,
            traceback=output[m.start():m.start() + 1500],
        ))
    return failures


def parse_jest_failures(output: str) -> list[TestFailure]:
    """Parse Jest verbose output into structured failures."""
    failures: list[TestFailure] = []
    fail_re = re.compile(r"● (.+?)\n\n(.+?)(?=\n●|\Z)", re.DOTALL)
    for m in fail_re.finditer(output):
        test_name = m.group(1).strip()
        body = m.group(2).strip()
        failures.append(TestFailure(
            test_id=test_name,
            file="",
            line=None,
            error=body[:200],
            traceback=body[:1000],
        ))
    return failures


def parse_failures(runner: list[str], output: str) -> list[TestFailure]:
    runner_str = " ".join(runner)
    if "pytest" in runner_str:
        return parse_pytest_failures(output)
    if "npm" in runner_str:
        return parse_jest_failures(output)
    return []  # cargo/go: return empty, let LLM handle raw output


# ── Fix prompt ────────────────────────────────────────────────────────────────

# system prompt that steers the LLM toward minimal surgical patches
_FIX_SYSTEM = """\
You are an expert Python developer. You will be given test failures and the
relevant source files. Produce minimal, surgical patches to fix the failures.

Output patches in unified diff format ONLY:
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -N,M +N,M @@
 context line
-old line
+new line
 context line

Rules:
- Fix ONLY what is needed for the failing tests
- Do not rewrite working code
- Do not add features
- Output patches only — no prose, no markdown fences
"""


class TestFixLoop:

    def __init__(self, cfg: AppConfig, max_attempts: int = 5) -> None:
        self._cfg = cfg
        self._max = max_attempts

    def run(
        self,
        working_folder: str,
        runner: list[str] | None = None,
        only: str | None = None,
        on_progress: Callable | None = None,
    ) -> TestFixResult:
        """Run the test-fix loop until all tests pass or max_attempts is reached."""
        from app.core import process_runner as _pr

        wf = working_folder or self._cfg.working_folder or ""
        cmd = list(runner) if runner else detect_test_runner(wf)
        if only:
            runner_str = " ".join(cmd)
            cmd = [*cmd, "-k", only] if "pytest" in runner_str else [*cmd, only]

        result = TestFixResult()

        for attempt_num in range(1, self._max + 1):
            run_result = _pr.run(cmd, cwd=wf or None, timeout=120)
            output = (run_result.stdout or "") + "\n" + (run_result.stderr or "")

            failures = parse_failures(cmd, output)
            failures_before = len(failures)

            if on_progress:
                try:
                    on_progress(attempt_num, failures_before, output)
                except Exception:
                    pass

            if not failures and run_result.returncode == 0:
                result.final_pass = True
                break

            if not failures:
                # runner failed but we couldn't parse any failures — give up
                result.error = f"Test runner exited {run_result.returncode} with unparseable output."
                result.final_failures = []
                break

            _log.info("attempt %d: %d failure(s)", attempt_num, failures_before)

            patches_applied = self._fix_failures(failures, wf)

            # run again to see if the patches helped
            run2 = _pr.run(cmd, cwd=wf, timeout=120)
            output2 = (run2.stdout or "") + "\n" + (run2.stderr or "")
            failures_after_list = parse_failures(cmd, output2)
            failures_after = len(failures_after_list)

            result.attempts.append(FixAttempt(
                attempt=attempt_num,
                failures_before=failures_before,
                failures_after=failures_after,
                patches_applied=patches_applied,
            ))

            if failures_after == 0 and run2.returncode == 0:
                result.final_pass = True
                result.total_fixed = failures_before
                break

            result.total_fixed += max(0, failures_before - failures_after)
            result.final_failures = failures_after_list

            # stop if we're making no progress — avoid spinning forever
            if failures_after >= failures_before:
                _log.warning("attempt %d made no progress — stopping", attempt_num)
                break

        return result

    def _fix_failures(self, failures: list[TestFailure], wf: str) -> int:
        # gather source context for the failing files so the LLM has something to work with
        file_contents: dict[str, str] = {}
        for f in failures[:5]:  # cap at 5 failures per round
            if f.file:
                p = Path(wf) / f.file
                if p.exists():
                    try:
                        file_contents[f.file] = p.read_text(encoding="utf-8")[:6000]
                    except OSError:
                        pass

        failures_text = "\n\n".join(
            f"FAILURE {i+1}: {fail.test_id}\n{fail.traceback[:800]}"
            for i, fail in enumerate(failures[:5])
        )
        files_text = "\n\n".join(
            f"=== {fname} ===\n{content}"
            for fname, content in file_contents.items()
        )

        user_msg = f"Test failures:\n{failures_text}\n\nSource files:\n{files_text}"

        try:
            from codex.app.llm_client import get_llm_client
            client = get_llm_client(self._cfg)
            patch_text = client.chat(
                messages=[{"role": "user", "content": user_msg}],
                system=_FIX_SYSTEM,
                temperature=0.1,
                max_tokens=4096,
            )
        except Exception as exc:
            _log.error("fix LLM call failed: %s", exc)
            return 0

        return self._apply_patches(patch_text, wf)

    def _apply_patches(self, patch_text: str, wf: str) -> int:
        """Apply unified diff patches from LLM output. Returns count applied."""
        from app.core import process_runner as _pr

        patches = self._split_patches(patch_text)
        applied = 0
        for patch in patches:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".patch", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(patch)
                tmp_path = tmp.name
            try:
                r = _pr.run(
                    ["git", "apply", "--whitespace=fix", tmp_path],
                    cwd=wf,
                    timeout=10,
                )
                if r.ok:
                    applied += 1
                    _log.debug("patch applied: %s", patch[:60])
                else:
                    _log.debug("patch failed: %s", r.stderr[:200])
            except Exception as exc:
                _log.debug("patch exception: %s", exc)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        return applied

    def _split_patches(self, text: str) -> list[str]:
        """Split a multi-patch LLM output into individual unified diffs."""
        patches: list[str] = []
        current: list[str] = []
        for line in text.splitlines(keepends=True):
            if line.startswith("--- a/") and current:
                patches.append("".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            patches.append("".join(current))
        return [p for p in patches if p.strip()]
