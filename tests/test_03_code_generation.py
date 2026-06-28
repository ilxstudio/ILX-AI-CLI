"""Cluster 03 — Live code generation and execution.

Tests (live Ollama required):
  - test_llm_writes_hello_world  : ask LLM for a hello.py, verify it contains print()
  - test_llm_creates_add_func    : ask for add(a,b), extract and exec the function
  - test_coding_agent_creates_file : CodingAgent creates a real file in a tmp workspace
  - test_llm_checks_python_file  : feed a buggy .py to LLM, ask for analysis
  - test_llm_fixes_syntax_error  : give LLM broken Python, ask it to fix, eval result
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.result_store import save

PYTHON_EXE = sys.executable


def _extract_code_block(text: str) -> str:
    """Extract first fenced code block from markdown text."""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
def test_llm_writes_hello_world(llm):
    """Ask LLM to write a hello world script and verify it contains print()."""
    prompt = (
        "Write a Python script called hello.py that prints 'Hello, ILX!' to stdout. "
        "Return ONLY the Python code inside a ```python ... ``` code block. Nothing else."
    )
    try:
        response = llm.chat([_msg("user", prompt)])
    except Exception as exc:
        save("llm_writes_hello_world", False, {"error": str(exc)})
        pytest.fail(f"llm.chat() raised: {exc}")

    code = _extract_code_block(response)
    has_print = "print" in code
    has_ilx   = "ILX" in code or "ilx" in code.lower()
    ok = has_print and len(code) > 10

    save("llm_writes_hello_world", ok, {
        "prompt":    prompt,
        "response":  response[:800],
        "code":      code[:400],
        "has_print": has_print,
        "has_ilx":   has_ilx,
    })
    assert ok, f"Expected print() in generated code. Got:\n{code}"


@pytest.mark.ollama_live
@pytest.mark.model_quality
def test_llm_creates_add_func(llm):
    """Ask LLM to write an add(a,b) function, extract it, and actually exec it."""
    prompt = (
        "Write a Python function called add(a, b) that returns a + b. "
        "Return ONLY the function definition inside a ```python ... ``` block."
    )
    try:
        response = llm.chat([_msg("user", prompt)])
    except Exception as exc:
        save("llm_creates_add_func", False, {"error": str(exc)})
        pytest.fail(f"llm.chat() raised: {exc}")

    code = _extract_code_block(response)

    # Try to parse the code
    try:
        ast.parse(code)
        parse_ok = True
        parse_err = None
    except SyntaxError as e:
        parse_ok = False
        parse_err = str(e)

    # Try to exec and call add()
    exec_ok = False
    exec_err = None
    result_val = None
    if parse_ok:
        try:
            ns: dict = {}
            exec(compile(code, "<llm>", "exec"), ns)
            if "add" in ns and callable(ns["add"]):
                result_val = ns["add"](3, 4)
                exec_ok = (result_val == 7)
        except Exception as e:
            exec_err = str(e)

    ok = parse_ok and exec_ok
    save("llm_creates_add_func", ok, {
        "prompt":     prompt,
        "response":   response[:600],
        "code":       code[:400],
        "parse_ok":   parse_ok,
        "parse_err":  parse_err,
        "exec_ok":    exec_ok,
        "exec_err":   exec_err,
        "result_val": result_val,
    })
    assert ok, f"parse_ok={parse_ok} parse_err={parse_err} exec_ok={exec_ok} exec_err={exec_err}"


@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_coding_agent_creates_file(cfg):
    """CodingAgent creates a real .py file in a temp workspace."""
    from codex.app.llm_client import get_llm_client
    from codex.app.controller import CodingAgent

    client = get_llm_client(cfg)

    with tempfile.TemporaryDirectory() as tmp:
        files_written: list[str] = []
        outputs: list[str] = []

        def _on_status(msg: str) -> None:
            pass

        def _on_output(stream: str, text: str) -> None:
            outputs.append(f"[{stream}] {text}")

        agent = CodingAgent(
            llm_client=client,
            on_status=_on_status,
            on_output=_on_output,
            permission_callback=lambda *_: True,
            max_attempts=2,
            run_timeout=15,
        )
        task = "Create a file called greeting.py that defines a function greet(name) returning f'Hello, {name}!'"
        result = agent.run(task=task, working_folder=tmp)

        # Check if greeting.py was created
        greeting = Path(tmp) / "greeting.py"
        file_exists = greeting.exists()
        file_content = greeting.read_text(encoding="utf-8") if file_exists else ""
        has_greet    = "greet" in file_content
        has_hello    = "Hello" in file_content or "hello" in file_content.lower()

        ok = result.success and file_exists and has_greet

        save("coding_agent_creates_file", ok, {
            "task":         task,
            "success":      result.success,
            "attempts":     result.attempts,
            "file_exists":  file_exists,
            "file_content": file_content[:400],
            "has_greet":    has_greet,
            "has_hello":    has_hello,
            "outputs":      outputs[:20],
            "final_error":  result.final_error,
        })
    assert ok, f"success={result.success} file={file_exists} has_greet={has_greet}\nfile:\n{file_content}"


@pytest.mark.ollama_live
@pytest.mark.model_quality
def test_llm_checks_python_file(llm):
    """Feed a buggy Python file to LLM and ask it to identify the bug."""
    buggy_code = '''\
def divide(a, b):
    return a / b  # bug: no zero check

result = divide(10, 0)
print(result)
'''
    prompt = (
        "Review this Python code and identify the bug:\n\n"
        f"```python\n{buggy_code}\n```\n\n"
        "What will happen when this runs? Mention the exception name."
    )
    try:
        response = llm.chat([_msg("user", prompt)])
    except Exception as exc:
        save("llm_checks_python_file", False, {"error": str(exc)})
        pytest.fail(f"llm.chat() raised: {exc}")

    # The LLM should mention ZeroDivisionError
    mentions_zero = any(word in response.lower() for word in ["zerodivision", "zero division", "divide by zero", "division by zero"])
    ok = mentions_zero

    save("llm_checks_python_file", ok, {
        "buggy_code":    buggy_code,
        "response":      response[:800],
        "mentions_zero": mentions_zero,
    })
    assert ok, f"Expected mention of ZeroDivisionError. Response: {response[:300]}"


@pytest.mark.ollama_live
@pytest.mark.model_quality
def test_llm_fixes_syntax_error(llm):
    """Give LLM Python with a syntax error, ask it to fix it, verify fixed code parses."""
    broken = '''\
def greet(name)
    print(f"Hello, {name}!")

greet("World")
'''
    prompt = (
        "This Python code has a syntax error. Fix it and return ONLY the corrected code "
        "inside a ```python ... ``` block:\n\n"
        f"```python\n{broken}\n```"
    )
    try:
        response = llm.chat([_msg("user", prompt)])
    except Exception as exc:
        save("llm_fixes_syntax_error", False, {"error": str(exc)})
        pytest.fail(f"llm.chat() raised: {exc}")

    fixed = _extract_code_block(response)
    try:
        ast.parse(fixed)
        parse_ok = True
        parse_err = None
    except SyntaxError as e:
        parse_ok = False
        parse_err = str(e)

    ok = parse_ok and "def greet" in fixed

    save("llm_fixes_syntax_error", ok, {
        "broken":    broken,
        "response":  response[:600],
        "fixed":     fixed[:400],
        "parse_ok":  parse_ok,
        "parse_err": parse_err,
    })
    assert ok, f"Fixed code still has syntax errors: {parse_err}\nFixed:\n{fixed}"
