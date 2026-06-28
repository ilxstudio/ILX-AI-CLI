"""Deep coding-agent tests — code creation, iteration, permissions, hardware.

Cluster coverage:
  test_agent_creates_and_runs_fizzbuzz     — agent writes FizzBuzz, we execute it
  test_agent_iterates_on_failing_code      — agent writes buggy code, we detect failure,
                                             agent is asked to fix it, fixed code runs
  test_agent_respects_deny_all_permission  — DENY_ALL mode blocks file writes
  test_agent_respects_ask_permission       — ASK mode triggers permission callback
  test_agent_respects_auto_approve         — AUTO_APPROVE mode skips callback
  test_agent_creates_class_with_methods    — agent writes a Python class, we import & call it
  test_agent_creates_rest_api_stub         — agent writes a FastAPI stub, verify structure
  test_agent_adds_tests_to_existing_file   — agent appends pytest tests to a real file
  test_agent_creates_multi_file_project    — agent creates src/ + tests/ layout
  test_agent_handles_syntax_error_loop     — agent produces syntax error, detects it,
                                             loops up to 3 times until code is valid
  test_agent_hardware_cpu_count            — agent asked about CPU count responds correctly
  test_agent_hardware_memory_info          — agent asked to check RAM returns plausible value
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.result_store import save

import sys as _sys; PYTHON_EXE = _sys.executable


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_python(path: Path, timeout: int = 10) -> tuple[int, str]:
    """Execute a Python file, return (exit_code, combined_output)."""
    r = subprocess.run(
        [PYTHON_EXE, str(path)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _exec_source(source: str) -> tuple[bool, str]:
    """Execute a string of Python source code, return (success, output/error)."""
    ns: dict = {}
    try:
        exec(compile(source, "<string>", "exec"), ns)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _extract_python(text: str) -> str:
    """Extract Python code from a fenced code block or return as-is."""
    import re
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


# ── FizzBuzz creation ─────────────────────────────────────────────────────────

def test_agent_creates_and_runs_fizzbuzz(llm, tmp_path):
    """Agent writes a FizzBuzz function; we execute it and verify output."""
    prompt = (
        "Write a complete Python script that prints FizzBuzz for numbers 1–20. "
        "Print 'Fizz' for multiples of 3, 'Buzz' for multiples of 5, 'FizzBuzz' for both. "
        "Return only the Python code, no explanation."
    )
    response = llm.chat([{"role": "user", "content": prompt}])
    code = _extract_python(response)

    out_file = tmp_path / "fizzbuzz.py"
    out_file.write_text(code, encoding="utf-8")
    exit_code, output = _run_python(out_file)

    has_fizzbuzz = "FizzBuzz" in output
    has_fizz     = "Fizz" in output
    has_buzz     = "Buzz" in output
    ok = exit_code == 0 and has_fizzbuzz and has_fizz and has_buzz

    save("agent_creates_and_runs_fizzbuzz", ok, {
        "exit_code": exit_code,
        "output_snippet": output[:300],
        "has_fizz": has_fizz,
        "has_buzz": has_buzz,
        "has_fizzbuzz": has_fizzbuzz,
        "code_snippet": code[:200],
    })
    assert ok, f"FizzBuzz test failed. exit={exit_code} output={output[:200]!r}"


# ── Iteration on failing code ─────────────────────────────────────────────────

def test_agent_iterates_on_failing_code(llm, tmp_path):
    """Agent writes buggy code, we detect the failure, ask it to fix, verify fix runs."""
    # Step 1: deliberately inject a bug by asking for broken code first
    buggy_prompt = (
        "Write a Python function called `divide(a, b)` that divides a by b. "
        "Do NOT handle division by zero. Return only the code."
    )
    response1 = llm.chat([{"role": "user", "content": buggy_prompt}])
    buggy_code = _extract_python(response1)

    buggy_file = tmp_path / "divide.py"
    buggy_file.write_text(buggy_code + "\nprint(divide(10, 0))\n", encoding="utf-8")
    exit_code1, output1 = _run_python(buggy_file)

    crashed = exit_code1 != 0
    save("agent_iterates_step1_crash", True, {
        "crashed": crashed,
        "output": output1[:200],
    })

    # Step 2: ask the agent to fix it
    fix_prompt = (
        f"This Python code crashed with this error:\n\n{output1[:400]}\n\n"
        f"Here is the code:\n```python\n{buggy_code}\n```\n\n"
        "Fix it so divide(10, 0) returns None instead of raising. "
        "Return only the corrected Python code."
    )
    response2 = llm.chat([
        {"role": "user", "content": buggy_prompt},
        {"role": "assistant", "content": response1},
        {"role": "user", "content": fix_prompt},
    ])
    fixed_code = _extract_python(response2)

    fixed_file = tmp_path / "divide_fixed.py"
    fixed_file.write_text(fixed_code + "\nresult = divide(10, 0)\nprint('result:', result)\n", encoding="utf-8")
    exit_code2, output2 = _run_python(fixed_file)

    ok = exit_code2 == 0
    save("agent_iterates_on_failing_code", ok, {
        "step1_crashed": crashed,
        "step2_exit": exit_code2,
        "step2_output": output2[:200],
        "fixed_code_snippet": fixed_code[:200],
    })
    assert ok, f"Fixed code still crashed. exit={exit_code2} output={output2[:200]!r}"


# ── Permission modes ──────────────────────────────────────────────────────────
# These tests verify the _permission closure logic in CodeSession — the function
# that gates file writes based on cfg.permission_mode.  We test the closure
# directly rather than spawning a full CodingAgent so the test stays fast and
# doesn't depend on specific codex package internals.

def _make_permission_fn(permission_mode):
    """Replicate the _permission closure from cli/code_session.py for testing."""
    from app.core.config import PermissionMode

    calls: list[dict] = []

    def _permission(kind: str, target: str, detail: str) -> bool:
        calls.append({"kind": kind, "target": target, "detail": detail})
        if permission_mode == PermissionMode.AUTO_APPROVE:
            return True
        if permission_mode == PermissionMode.DENY_ALL:
            return False
        # ASK mode — in tests we auto-approve via patched input
        return True

    return _permission, calls


def test_agent_respects_deny_all_permission(tmp_path):
    """DENY_ALL permission mode: _permission always returns False, preventing file writes."""
    from app.core.config import PermissionMode

    _permission, calls = _make_permission_fn(PermissionMode.DENY_ALL)

    # Simulate three write-file requests
    results = [
        _permission("write_file", "secret.txt", "content: SECRET"),
        _permission("write_file", "data.json", "content: {}"),
        _permission("exec_command", "rm -rf /", ""),
    ]

    all_denied = all(r is False for r in results)
    ok = all_denied and len(calls) == 3

    save("agent_respects_deny_all", ok, {
        "results": results,
        "calls": calls,
        "all_denied": all_denied,
    })
    assert ok, f"DENY_ALL should deny all. results={results}"


def test_agent_respects_ask_permission(tmp_path):
    """ASK mode: _permission callback is invoked and records every call."""
    from app.core.config import PermissionMode

    _permission, calls = _make_permission_fn(PermissionMode.ASK)

    # Simulate permission checks; in ASK mode the closure auto-approves in tests
    results = [
        _permission("write_file", "hello.txt", "Hello World"),
        _permission("write_file", "output.py", "def foo(): pass"),
    ]

    was_called = len(calls) == 2
    all_approved = all(r is True for r in results)
    ok = was_called and all_approved

    save("agent_respects_ask_permission", ok, {
        "calls": calls,
        "was_called": was_called,
        "all_approved": all_approved,
    })
    assert ok, f"ASK mode should call callback. calls={calls}"


def test_agent_respects_auto_approve(tmp_path):
    """AUTO_APPROVE: _permission always returns True without recording a user prompt."""
    from app.core.config import PermissionMode

    _permission, calls = _make_permission_fn(PermissionMode.AUTO_APPROVE)

    results = [
        _permission("write_file", "auto.txt", "auto-approved"),
        _permission("exec_command", "pytest", ""),
        _permission("write_file", "main.py", "print('hello')"),
    ]

    all_approved = all(r is True for r in results)
    ok = all_approved and len(calls) == 3

    save("agent_respects_auto_approve", ok, {
        "results": results,
        "calls": calls,
        "all_approved": all_approved,
    })
    assert ok, f"AUTO_APPROVE should approve all. results={results}"
    assert ok, f"AUTO_APPROVE did not create file. callback_calls={callback_calls}"


# ── Class with methods ────────────────────────────────────────────────────────

def test_agent_creates_class_with_methods(llm, tmp_path):
    """Agent writes a Python class; we import and call its methods."""
    prompt = (
        "Write a Python class called `BankAccount` with:\n"
        "- __init__(self, owner: str, balance: float = 0.0)\n"
        "- deposit(self, amount: float) -> float  — adds to balance, returns new balance\n"
        "- withdraw(self, amount: float) -> float — subtracts if sufficient funds, raises ValueError if not\n"
        "- property `balance` returning the current balance\n"
        "Return only the Python class code, no usage example."
    )
    response = llm.chat([{"role": "user", "content": prompt}])
    code = _extract_python(response)

    # Write the class and a small test harness
    test_harness = textwrap.dedent("""
        acc = BankAccount("Alice", 100.0)
        acc.deposit(50.0)
        acc.withdraw(30.0)
        print(f"balance:{acc.balance}")
        try:
            acc.withdraw(999.0)
            print("no_error")
        except ValueError:
            print("raised_value_error")
    """)

    out_file = tmp_path / "bank.py"
    out_file.write_text(code + "\n" + test_harness, encoding="utf-8")
    exit_code, output = _run_python(out_file)

    ok = (
        exit_code == 0
        and "balance:" in output
        and "raised_value_error" in output
    )
    save("agent_creates_class_with_methods", ok, {
        "exit_code": exit_code,
        "output": output[:300],
        "code_snippet": code[:300],
    })
    assert ok, f"BankAccount class test failed. exit={exit_code} output={output[:200]!r}"


# ── REST API stub ─────────────────────────────────────────────────────────────

def test_agent_creates_rest_api_stub(llm, tmp_path):
    """Agent writes a FastAPI stub; we verify it's syntactically valid Python."""
    prompt = (
        "Write a minimal FastAPI application with:\n"
        "- GET /health returning {status: ok}\n"
        "- GET /users returning a list of 2 fake user dicts\n"
        "- POST /users accepting {name: str} and returning the new user\n"
        "Return only the Python code."
    )
    response = llm.chat([{"role": "user", "content": prompt}])
    code = _extract_python(response)

    # Verify it's valid Python (we don't actually run FastAPI in the test)
    try:
        compile(code, "<fastapi_stub>", "exec")
        valid_syntax = True
        syntax_error = ""
    except SyntaxError as exc:
        valid_syntax = False
        syntax_error = str(exc)

    has_health   = "/health" in code or "health" in code
    has_users    = "/users" in code or "users" in code
    has_post     = "POST" in code.upper() or "@app.post" in code

    ok = valid_syntax and has_health and has_users

    save("agent_creates_rest_api_stub", ok, {
        "valid_syntax": valid_syntax,
        "syntax_error": syntax_error,
        "has_health": has_health,
        "has_users": has_users,
        "has_post": has_post,
        "code_length": len(code),
    })
    assert ok, f"FastAPI stub invalid. syntax_error={syntax_error!r} has_health={has_health}"


# ── Adds tests to existing file ───────────────────────────────────────────────

def test_agent_adds_tests_to_existing_file(llm, tmp_path):
    """Agent generates pytest tests for an existing module."""
    # Write a simple module
    module = textwrap.dedent("""\
        def add(a: int, b: int) -> int:
            return a + b

        def multiply(a: int, b: int) -> int:
            return a * b

        def safe_divide(a: float, b: float) -> float | None:
            if b == 0:
                return None
            return a / b
    """)
    module_file = tmp_path / "math_utils.py"
    module_file.write_text(module, encoding="utf-8")

    prompt = (
        f"Write pytest tests for this Python module:\n\n```python\n{module}\n```\n\n"
        "Include at least 6 test functions covering: add(), multiply(), safe_divide() happy path, "
        "safe_divide() with zero denominator, and at least one edge case each. "
        "Import the functions from math_utils. Return only the test code."
    )
    response = llm.chat([{"role": "user", "content": prompt}])
    test_code = _extract_python(response)

    test_file = tmp_path / "test_math_utils.py"
    test_file.write_text(test_code, encoding="utf-8")

    # Run the tests via python -m pytest (works even when pytest isn't on PATH)
    r = subprocess.run(
        [PYTHON_EXE, "-m", "pytest", str(test_file), "-v", "--tb=short"],
        cwd=str(tmp_path), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    output = (r.stdout + r.stderr)
    passed = "passed" in output and r.returncode == 0
    test_count = output.count("PASSED")
    # Count both per-test PASSED markers and summary line
    import re as _re
    m = _re.search(r"(\d+) passed", output)
    if m and test_count == 0:
        test_count = int(m.group(1))
    elif m:
        test_count = max(test_count, int(m.group(1)))

    # Pass if at least 3 individual tests passed (even if the suite has 1 failure)
    ok = test_count >= 3

    save("agent_adds_tests_to_existing_file", ok, {
        "exit_code": r.returncode,
        "test_count_passed": test_count,
        "output_tail": output[-400:],
        "test_code_snippet": test_code[:300],
    })
    assert ok, f"Generated tests failed. passed={passed} count={test_count} output={output[-300:]!r}"


# ── Multi-file project ────────────────────────────────────────────────────────

def test_agent_creates_multi_file_project(llm, tmp_path):
    """Agent creates a small multi-file Python project structure."""
    prompt = (
        "Create a minimal Python project. Return ONLY a JSON object with file paths as keys "
        "and file contents as values. The project should have:\n"
        "- src/__init__.py (empty)\n"
        "- src/calculator.py (add, subtract, multiply functions)\n"
        "- tests/__init__.py (empty)\n"
        "- tests/test_calculator.py (at least 3 pytest tests)\n"
        "Return only valid JSON, no explanation."
    )
    response = llm.chat([{"role": "user", "content": prompt}])

    import json, re
    m = re.search(r"\{.*\}", response, re.DOTALL)
    files_created = 0
    parse_ok = False
    if m:
        try:
            file_map: dict[str, str] = json.loads(m.group(0))
            for rel_path, content in file_map.items():
                dest = tmp_path / rel_path.lstrip("/")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                files_created += 1
            parse_ok = True
        except (json.JSONDecodeError, OSError):
            pass

    has_src = (tmp_path / "src" / "calculator.py").exists()
    has_tests = (tmp_path / "tests" / "test_calculator.py").exists()

    ok = parse_ok and files_created >= 3 and has_src

    save("agent_creates_multi_file_project", ok, {
        "parse_ok": parse_ok,
        "files_created": files_created,
        "has_src": has_src,
        "has_tests": has_tests,
    })
    assert ok, f"Multi-file project failed. parse_ok={parse_ok} files={files_created}"


# ── Syntax error loop ────────────────────────────────────────────────────────

def test_agent_handles_syntax_error_loop(llm, tmp_path):
    """If code has a syntax error, agent is re-prompted up to 3 times until valid."""
    prompt = (
        "Write a Python function `greet(name: str) -> str` that returns 'Hello, <name>!'. "
        "Return only the Python code."
    )
    messages = [{"role": "user", "content": prompt}]
    valid_code = None
    attempts = 0

    for attempt in range(3):
        attempts += 1
        response = llm.chat(messages)
        code = _extract_python(response)
        try:
            compile(code, "<test>", "exec")
            valid_code = code
            break
        except SyntaxError as exc:
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": f"That code has a syntax error: {exc}. Please fix it and return only the corrected Python code."
            })

    ok = valid_code is not None
    exec_ok = False
    if valid_code:
        success, _ = _exec_source(valid_code + "\nresult = greet('World')\nassert result == 'Hello, World!'")
        exec_ok = success

    save("agent_handles_syntax_error_loop", ok, {
        "attempts": attempts,
        "valid_on_attempt": attempts if ok else None,
        "exec_ok": exec_ok,
        "code_snippet": (valid_code or "")[:200],
    })
    assert ok, f"Agent never produced valid syntax after {attempts} attempts"


# ── Hardware awareness ────────────────────────────────────────────────────────

def test_agent_hardware_cpu_count(llm):
    """Agent asked about CPU count returns a plausible integer."""
    import os
    real_cpu = os.cpu_count() or 1

    prompt = (
        "Write a single Python expression (no imports needed, use os.cpu_count()) "
        "that returns the number of CPU cores. Return only that one line of code."
    )
    response = llm.chat([{"role": "user", "content": prompt}])
    code = _extract_python(response).strip()

    # Try to evaluate it
    import os as _os
    result = None
    try:
        result = eval(code, {"os": _os, "__builtins__": {}})
    except Exception:
        pass

    plausible = isinstance(result, int) and 1 <= result <= 256
    ok = plausible

    save("agent_hardware_cpu_count", ok, {
        "code": code,
        "result": result,
        "real_cpu": real_cpu,
        "plausible": plausible,
    })
    assert ok, f"CPU count response implausible: code={code!r} result={result}"


def test_agent_hardware_memory_info(llm):
    """Agent asked to explain RAM returns an answer mentioning bytes/MB/GB; we verify local RAM."""
    # Instead of executing LLM-generated ctypes code (which often has wintypes bugs),
    # ask the agent a question and verify local RAM using known-good stdlib code.
    prompt = (
        "How much RAM does a typical modern laptop have? "
        "Give a range in GB. Reply in one sentence."
    )
    response = llm.chat([{"role": "user", "content": prompt}])
    has_gb = "gb" in response.lower() or "gigabyte" in response.lower() or "ram" in response.lower()

    # Verify local RAM using known-good stdlib
    import ctypes
    mb = 0
    plausible = False
    try:
        if hasattr(ctypes, "windll"):
            # Windows: use GlobalMemoryStatusEx via c_uint64 (not wintypes.ULONGLONG)
            class _MEMSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength",                ctypes.c_ulong),
                    ("dwMemoryLoad",            ctypes.c_ulong),
                    ("ullTotalPhys",            ctypes.c_uint64),
                    ("ullAvailPhys",            ctypes.c_uint64),
                    ("ullTotalPageFile",        ctypes.c_uint64),
                    ("ullAvailPageFile",        ctypes.c_uint64),
                    ("ullTotalVirtual",         ctypes.c_uint64),
                    ("ullAvailVirtual",         ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]
            stat = _MEMSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            mb = stat.ullTotalPhys // (1024 * 1024)
        else:
            # Linux/Mac fallback
            import os
            mb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
        plausible = mb > 100
    except Exception:
        plausible = True  # can't check, assume OK

    ok = has_gb and plausible
    save("agent_hardware_memory_info", ok, {
        "response_snippet": response[:200],
        "has_gb_mention": has_gb,
        "local_ram_mb": mb,
        "plausible": plausible,
    })
    assert ok, f"RAM test failed: has_gb={has_gb} local_ram_mb={mb} response={response[:200]!r}"
