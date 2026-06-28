"""Reflexion-based self-improvement for LLM-generated code.

Based on Shinn et al. (2023) "Reflexion: Language Agents with Verbal Reinforcement Learning"
arXiv:2303.11366

The loop:
  1. Generate code attempt
  2. Validate / run tests
  3. If failure: generate a "reflection" — a natural-language explanation
     of what went wrong and how to fix it
  4. On next attempt, include the reflection in the prompt
  5. Repeat up to max_attempts

Key improvement over simple retry: the reflection is appended to the
prompt verbatim, giving the LLM explicit error context rather than
just hoping it produces different output.
"""
from __future__ import annotations

import logging
import re
import tempfile
import os
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("ilx_cli.reflexion")

_DEFAULT_REFLECT_TEMPLATE = """\
Your previous code attempt failed with these errors:
{errors}

Code you generated:
```python
{code}
```

Reflect on WHY this failed. Think step by step:
1. What specific line or logic caused the error?
2. What assumption was wrong?
3. What would a correct implementation look like?

Your reflection (be specific, not generic):"""

_NEXT_ATTEMPT_TEMPLATE = """\
{original_prompt}

Previous attempt reflection:
{reflection}

Generate a corrected version that addresses the issues identified above.
Return ONLY the Python code, no markdown fences."""


@dataclass
class ReflexionAttempt:
    """Record of a single attempt in the Reflexion loop."""

    attempt_number: int
    code: str
    errors: list[str]
    reflection: str  # LLM-generated explanation of what went wrong


@dataclass
class ReflexionResult:
    """Overall result of a complete Reflexion run."""

    success: bool
    final_code: str
    attempts: list[ReflexionAttempt] = field(default_factory=list)
    total_attempts: int = 0


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if the LLM wrapped the code anyway."""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


class ReflexionLoop:
    """Runs the Reflexion improvement cycle for code generation.

    Usage::

        loop = ReflexionLoop(llm_client=my_llm, validator=my_validator)
        result = loop.run(initial_prompt="Write a web scraper that ...")
        if result.success:
            use(result.final_code)

    The validator must have a ``validate(path: str) -> ValidationResult``
    method where ``ValidationResult.ok`` is truthy on success and
    ``ValidationResult.errors`` is a list of error strings on failure.
    """

    def __init__(
        self,
        llm_client,
        validator,
        max_attempts: int = 4,
        reflect_prompt_template: str | None = None,
    ) -> None:
        self._llm = llm_client
        self._validator = validator
        self.max_attempts = max_attempts
        self._reflect_template = reflect_prompt_template or _DEFAULT_REFLECT_TEMPLATE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        initial_prompt: str,
        task_context: str = "",
    ) -> ReflexionResult:
        """Run the full Reflexion loop.

        Returns the best code found (succeeding, or last attempt if all fail).

        Args:
            initial_prompt: The generation prompt sent to the LLM on the
                first attempt.
            task_context:   Optional extra context prepended to prompts on
                retry (not used by default but available for callers to
                thread additional info through).
        """
        attempts: list[ReflexionAttempt] = []
        current_prompt = initial_prompt
        reflection = ""

        for attempt_number in range(1, self.max_attempts + 1):
            _log.debug("Reflexion attempt %d/%d", attempt_number, self.max_attempts)

            # Build the prompt for this attempt
            if attempt_number == 1:
                prompt = current_prompt
            else:
                prompt = _NEXT_ATTEMPT_TEMPLATE.format(
                    original_prompt=initial_prompt,
                    reflection=reflection,
                )
            if task_context:
                prompt = task_context + "\n\n" + prompt

            # Generate code
            code = self._generate(prompt)

            # Validate the generated code
            errors = self._validate(code)

            if not errors:
                # Success — record the attempt and return
                record = ReflexionAttempt(
                    attempt_number=attempt_number,
                    code=code,
                    errors=[],
                    reflection="",
                )
                attempts.append(record)
                _log.info("Reflexion succeeded on attempt %d", attempt_number)
                return ReflexionResult(
                    success=True,
                    final_code=code,
                    attempts=attempts,
                    total_attempts=attempt_number,
                )

            # Failed — generate a reflection (unless this is the last attempt)
            if attempt_number < self.max_attempts:
                reflection = self._reflect(code, errors)
                _log.debug(
                    "Reflexion attempt %d failed; generated reflection (%d chars)",
                    attempt_number,
                    len(reflection),
                )
            else:
                reflection = ""

            record = ReflexionAttempt(
                attempt_number=attempt_number,
                code=code,
                errors=errors,
                reflection=reflection,
            )
            attempts.append(record)

        # All attempts exhausted — return last code with failure status
        last_code = attempts[-1].code if attempts else ""
        _log.warning("Reflexion failed after %d attempts", self.max_attempts)
        return ReflexionResult(
            success=False,
            final_code=last_code,
            attempts=attempts,
            total_attempts=self.max_attempts,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate(self, prompt: str) -> str:
        """Call the LLM and return cleaned code string."""
        try:
            response = self._llm.chat([{"role": "user", "content": prompt}])
        except Exception as exc:
            _log.warning("LLM generation failed in Reflexion: %s", exc)
            return ""
        return _strip_fences(response) if response else ""

    def _validate(self, code: str) -> list[str]:
        """Write *code* to a temp file, run the validator, return error list.

        Returns an empty list when validation passes.
        """
        if not code:
            return ["LLM returned empty code"]

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                encoding="utf-8",
                prefix="ilx_reflexion_",
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            result = self._validator.validate(tmp_path)
        except Exception as exc:
            return [f"Validation infrastructure error: {exc}"]
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        if result.ok:
            return []
        return list(result.errors) if result.errors else ["Validation failed (no details)"]

    def _reflect(self, code: str, errors: list[str]) -> str:
        """Ask the LLM to reflect on why the code failed.

        Returns the reflection text, or a fallback string on LLM error.
        """
        errors_text = "\n".join(f"- {e}" for e in errors)
        reflect_prompt = self._reflect_template.format(
            errors=errors_text,
            code=code,
        )
        try:
            response = self._llm.chat([{"role": "user", "content": reflect_prompt}])
            return (response or "").strip()
        except Exception as exc:
            _log.warning("LLM reflection call failed: %s", exc)
            return f"(reflection unavailable: {exc})"
