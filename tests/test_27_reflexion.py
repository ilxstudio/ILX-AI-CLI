"""Tests for the Reflexion-based self-improvement loop.

Covers:
  - ReflexionAttempt / ReflexionResult dataclass fields
  - ReflexionLoop.run() happy-path (first attempt succeeds)
  - ReflexionLoop.run() reflection generation on failure
  - Prompt injection: "Previous attempt reflection" appears in next prompt
  - max_attempts cap
  - Return value when all attempts fail
  - UserToolRegistry.search()
  - UserTool.generation_attempts default
  - ReflexionResult.attempts list length
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, call, patch

import pytest

from app.core.reflexion import ReflexionAttempt, ReflexionLoop, ReflexionResult
from app.core.user_tools.registry import UserTool, UserToolRegistry


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

def _make_validation(ok: bool, errors: list[str] | None = None):
    """Return a lightweight ValidationResult-alike."""
    v = MagicMock()
    v.ok = ok
    v.errors = errors or []
    return v


def _make_validator(ok: bool, errors: list[str] | None = None):
    """Return a validator mock whose validate() always returns the given result."""
    validator = MagicMock()
    validator.validate.return_value = _make_validation(ok, errors)
    return validator


def _make_llm(responses: list[str]):
    """Return an LLM mock whose chat() returns responses in sequence."""
    llm = MagicMock()
    llm.chat.side_effect = responses
    return llm


# Minimal valid Python that satisfies ToolValidator (we skip actual subprocess
# in unit tests — the validator is always mocked here).
_VALID_CODE = """\
def main():
    return 0

if __name__ == "__main__":
    main()
"""

_INVALID_CODE = "this is not valid python !!!"


# ===========================================================================
# 1. ReflexionAttempt has correct fields
# ===========================================================================

def test_reflexion_attempt_fields():
    attempt = ReflexionAttempt(
        attempt_number=1,
        code="print('hello')",
        errors=["SyntaxError"],
        reflection="I forgot to add a colon.",
    )
    assert attempt.attempt_number == 1
    assert attempt.code == "print('hello')"
    assert attempt.errors == ["SyntaxError"]
    assert attempt.reflection == "I forgot to add a colon."


# ===========================================================================
# 2. ReflexionResult has correct fields
# ===========================================================================

def test_reflexion_result_fields():
    result = ReflexionResult(
        success=True,
        final_code="print('done')",
        attempts=[],
        total_attempts=1,
    )
    assert result.success is True
    assert result.final_code == "print('done')"
    assert result.attempts == []
    assert result.total_attempts == 1


def test_reflexion_result_default_attempts():
    """attempts defaults to empty list when not supplied."""
    result = ReflexionResult(success=False, final_code="x")
    assert result.attempts == []
    assert result.total_attempts == 0


# ===========================================================================
# 3. run() returns success=True on first valid attempt (mock validator)
# ===========================================================================

def test_run_success_on_first_attempt():
    llm = _make_llm([_VALID_CODE])
    validator = _make_validator(ok=True)

    loop = ReflexionLoop(llm_client=llm, validator=validator, max_attempts=4)
    result = loop.run("Write a hello-world script.")

    assert result.success is True
    assert result.final_code == _VALID_CODE.strip()
    assert result.total_attempts == 1
    assert len(result.attempts) == 1
    # No reflection generated on success
    assert result.attempts[0].reflection == ""
    assert result.attempts[0].errors == []


# ===========================================================================
# 4. run() generates a reflection when validation fails
# ===========================================================================

def test_run_generates_reflection_on_failure():
    # Attempt 1 fails, attempt 2 succeeds
    llm = _make_llm([
        _INVALID_CODE,           # first code attempt
        "I used wrong syntax.",  # reflection call
        _VALID_CODE,             # second code attempt
    ])
    validator = MagicMock()
    validator.validate.side_effect = [
        _make_validation(ok=False, errors=["SyntaxError: invalid syntax"]),
        _make_validation(ok=True),
    ]

    loop = ReflexionLoop(llm_client=llm, validator=validator, max_attempts=3)
    result = loop.run("Write something.")

    assert result.success is True
    assert result.total_attempts == 2
    # First attempt must have a reflection
    assert result.attempts[0].reflection == "I used wrong syntax."
    assert "SyntaxError" in result.attempts[0].errors[0]


# ===========================================================================
# 5. run() injects "Previous attempt reflection" into the next prompt
# ===========================================================================

def test_run_injects_reflection_into_next_prompt():
    """Verify the second LLM call's prompt contains the reflection text."""
    reflection_text = "I made a terrible mistake on line 3."
    llm = _make_llm([
        _INVALID_CODE,
        reflection_text,
        _VALID_CODE,
    ])
    validator = MagicMock()
    validator.validate.side_effect = [
        _make_validation(ok=False, errors=["error"]),
        _make_validation(ok=True),
    ]

    loop = ReflexionLoop(llm_client=llm, validator=validator, max_attempts=3)
    loop.run("Build a parser.")

    # The third call to llm.chat() is the second code-generation attempt
    # (first = gen code, second = reflect, third = gen code again)
    third_call_args = llm.chat.call_args_list[2]
    prompt_sent = third_call_args[0][0][0]["content"]
    assert "Previous attempt reflection" in prompt_sent
    assert reflection_text in prompt_sent


# ===========================================================================
# 6. run() stops after max_attempts even if all fail
# ===========================================================================

def test_run_stops_at_max_attempts():
    # All code attempts fail; reflection calls return generic text
    responses = []
    for i in range(3):
        responses.append(_INVALID_CODE)   # code attempt
        if i < 2:
            responses.append(f"Reflection {i + 1}")  # reflection (not after last)

    llm = _make_llm(responses)
    validator = _make_validator(ok=False, errors=["always fails"])

    loop = ReflexionLoop(llm_client=llm, validator=validator, max_attempts=3)
    result = loop.run("A doomed prompt.")

    assert result.success is False
    assert result.total_attempts == 3
    assert len(result.attempts) == 3


# ===========================================================================
# 7. run() returns last attempt's code when all fail
# ===========================================================================

def test_run_returns_last_code_when_all_fail():
    code_v1 = "# attempt 1"
    code_v2 = "# attempt 2"

    llm = _make_llm([
        code_v1, "reflection 1",
        code_v2,
    ])
    validator = _make_validator(ok=False, errors=["fail"])

    loop = ReflexionLoop(llm_client=llm, validator=validator, max_attempts=2)
    result = loop.run("A failing prompt.")

    assert result.success is False
    # Last generated code is returned
    assert result.final_code == code_v2.strip()


# ===========================================================================
# 8. UserToolRegistry.search() returns matching tools
# ===========================================================================

def test_registry_search_returns_matching_tools(tmp_path):
    reg_path = tmp_path / "registry.json"
    registry = UserToolRegistry(registry_path=reg_path)

    registry.register(UserTool(
        name="webscraper", description="Scrape web pages for data", path="/fake/ws.py"
    ))
    registry.register(UserTool(
        name="csvparser", description="Parse CSV files", path="/fake/csv.py"
    ))
    registry.register(UserTool(
        name="imageresize", description="Resize images in bulk", path="/fake/img.py"
    ))

    # "web scraper" should match "webscraper" (name) and its description
    results = registry.search("web scraper")
    names = [t.name for t in results]
    assert "webscraper" in names
    assert "csvparser" not in names
    assert "imageresize" not in names


def test_registry_search_empty_query_returns_all(tmp_path):
    reg_path = tmp_path / "registry.json"
    registry = UserToolRegistry(registry_path=reg_path)

    registry.register(UserTool(name="toolone", description="First", path="/a.py"))
    registry.register(UserTool(name="tooltwo", description="Second", path="/b.py"))

    results = registry.search("")
    assert len(results) == 2


# ===========================================================================
# 9. UserTool has generation_attempts field defaulting to 1
# ===========================================================================

def test_user_tool_generation_attempts_default():
    tool = UserTool(name="mytool", description="Does stuff", path="/fake.py")
    assert tool.generation_attempts == 1


def test_user_tool_generation_attempts_custom():
    tool = UserTool(
        name="mytool", description="Does stuff", path="/fake.py",
        generation_attempts=3,
    )
    assert tool.generation_attempts == 3


# ===========================================================================
# 10. ReflexionResult.attempts list has correct length after multi-attempt run
# ===========================================================================

def test_reflexion_result_attempts_length_multi():
    """After a 3-attempt run where only the last succeeds, attempts list == 3."""
    llm = _make_llm([
        "# bad 1", "reflection 1",
        "# bad 2", "reflection 2",
        _VALID_CODE,
    ])
    validator = MagicMock()
    validator.validate.side_effect = [
        _make_validation(ok=False, errors=["err1"]),
        _make_validation(ok=False, errors=["err2"]),
        _make_validation(ok=True),
    ]

    loop = ReflexionLoop(llm_client=llm, validator=validator, max_attempts=4)
    result = loop.run("Write good code.")

    assert result.success is True
    assert result.total_attempts == 3
    assert len(result.attempts) == 3
    # First two attempts have errors; last does not
    assert result.attempts[0].errors == ["err1"]
    assert result.attempts[1].errors == ["err2"]
    assert result.attempts[2].errors == []


# ===========================================================================
# Bonus: dataclass is a proper dataclass (fields introspectable)
# ===========================================================================

def test_reflexion_attempt_is_dataclass():
    field_names = {f.name for f in dataclasses.fields(ReflexionAttempt)}
    assert {"attempt_number", "code", "errors", "reflection"} == field_names


def test_reflexion_result_is_dataclass():
    field_names = {f.name for f in dataclasses.fields(ReflexionResult)}
    assert {"success", "final_code", "attempts", "total_attempts"} == field_names
