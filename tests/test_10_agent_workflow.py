"""End-to-end agent workflow tests — full task cycles with real code execution.

Cluster coverage:
  test_full_cycle_hello_world          — agent writes, runs, confirms Hello World
  test_full_cycle_data_processor       — agent writes CSV processor, we feed it real data
  test_full_cycle_cli_tool             — agent writes a small argparse CLI tool
  test_full_cycle_error_and_retry      — agent writes code with error, retries, succeeds
  test_full_cycle_file_transform       — agent reads a file, transforms it, writes result
  test_autofix_loop_corrects_imports   — autofix loop resolves a missing import
  test_agent_writes_then_tests_itself  — agent writes code then writes its own tests
  test_agent_produces_valid_json       — agent asked for JSON output returns parseable JSON
  test_agent_explains_then_fixes       — agent explains error, then provides fix
  test_agent_refactors_existing_code   — agent refactors a monolithic function
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.result_store import save

import sys as _sys; PYTHON_EXE = _sys.executable


def _run(path: Path, input_text: str = "", timeout: int = 10, cwd: str | None = None) -> tuple[int, str]:
    r = subprocess.run(
        [PYTHON_EXE, str(path)],
        input=input_text, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
        cwd=cwd or str(path.parent),
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _extract(text: str, lang: str = "python") -> str:
    m = re.search(rf"```{lang}?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def _syntax_ok(code: str) -> tuple[bool, str]:
    try:
        compile(code, "<check>", "exec")
        return True, ""
    except SyntaxError as e:
        return False, str(e)


# ── Full cycle: Hello World ───────────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_full_cycle_hello_world(llm, tmp_path):
    """Agent writes Hello World → we run it → verify output."""
    resp = llm.chat([{"role": "user", "content":
        "Write a Python script that prints exactly: Hello, World!\nReturn only the code."}])
    code = _extract(resp)
    f = tmp_path / "hello.py"
    f.write_text(code, encoding="utf-8")
    rc, out = _run(f)
    ok = rc == 0 and "Hello" in out and "World" in out
    save("full_cycle_hello_world", ok, {"exit": rc, "output": out[:200], "code": code[:200]})
    assert ok, f"Hello World failed: exit={rc} out={out!r}"


# ── Full cycle: CSV data processor ───────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_full_cycle_data_processor(llm, tmp_path):
    """Agent writes a CSV processor; we feed it real data and verify output. Retries once on failure."""
    csv_data = "name,score\nAlice,95\nBob,82\nCarol,91\n"
    csv_file = tmp_path / "scores.csv"
    csv_file.write_text(csv_data, encoding="utf-8")

    messages = [{"role": "user", "content":
        "Write a Python script that reads 'scores.csv' from the current directory, "
        "computes the average score column, and prints exactly: Average: <value>. "
        "Use only the stdlib csv module. The script must work when run as: "
        "python processor.py (no arguments). Return only the code."
    }]

    rc, out, code = 1, "", ""
    for attempt in range(2):
        resp = llm.chat(messages)
        code = _extract(resp)
        f = tmp_path / "processor.py"
        f.write_text(code, encoding="utf-8")
        rc, out = _run(f)
        if rc == 0:
            break
        # Feed error back for retry
        messages.append({"role": "assistant", "content": resp})
        messages.append({"role": "user", "content":
            f"That script crashed with:\n{out[:300]}\n"
            "Fix it and return only the corrected code. "
            "The file scores.csv is in the same directory as the script."
        })

    has_average = "average" in out.lower() or "avg" in out.lower()
    try:
        nums = [float(x) for x in re.findall(r"\d+\.?\d*", out)]
        correct_avg = any(abs(n - 89.33) < 1.0 for n in nums)
    except Exception:
        correct_avg = False

    ok = rc == 0 and (has_average or correct_avg)
    save("full_cycle_data_processor", ok, {
        "exit": rc, "output": out[:300], "has_average": has_average, "correct_avg": correct_avg
    })
    assert ok, f"CSV processor failed: exit={rc} out={out[:200]!r}"


# ── Full cycle: CLI tool ──────────────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_full_cycle_cli_tool(llm, tmp_path):
    """Agent writes an argparse CLI tool; we invoke it with args and check output."""
    prompt = (
        "Write a Python CLI tool using argparse with two commands:\n"
        "  python tool.py greet --name Alice  → prints 'Hello, Alice!'\n"
        "  python tool.py add --a 3 --b 4     → prints '7'\n"
        "Return only the Python code."
    )
    resp = llm.chat([{"role": "user", "content": prompt}])
    code = _extract(resp)
    f = tmp_path / "tool.py"
    f.write_text(code, encoding="utf-8")

    r1 = subprocess.run([PYTHON_EXE, str(f), "greet", "--name", "Alice"],
                        capture_output=True, text=True, encoding="utf-8", timeout=10)
    r2 = subprocess.run([PYTHON_EXE, str(f), "add", "--a", "3", "--b", "4"],
                        capture_output=True, text=True, encoding="utf-8", timeout=10)

    greet_ok = r1.returncode == 0 and "Alice" in r1.stdout
    add_ok   = r2.returncode == 0 and "7" in r2.stdout

    ok = greet_ok and add_ok
    save("full_cycle_cli_tool", ok, {
        "greet_ok": greet_ok, "greet_out": r1.stdout[:100],
        "add_ok": add_ok, "add_out": r2.stdout[:100],
        "code_snippet": code[:300],
    })
    assert ok, f"CLI tool: greet_ok={greet_ok} add_ok={add_ok}"


# ── Full cycle: error and retry ───────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_full_cycle_error_and_retry(llm, tmp_path):
    """Agent produces code, it fails at runtime, agent is given the error and retries."""
    # Ask for code that will likely fail without careful handling
    prompt = (
        "Write a Python script that opens 'data.json', reads a list of numbers, "
        "and prints their sum. The file does not exist yet — do NOT create it. "
        "Return only the code."
    )
    resp1 = llm.chat([{"role": "user", "content": prompt}])
    code1 = _extract(resp1)
    f = tmp_path / "sum_json.py"
    f.write_text(code1, encoding="utf-8")
    rc1, out1 = _run(f)
    # This will likely fail (FileNotFoundError) — that's expected
    step1_failed = rc1 != 0

    # Now give it the error and ask to handle it gracefully
    fix_prompt = (
        f"The script failed with:\n{out1[:300]}\n\n"
        "Please rewrite it to handle the case where 'data.json' doesn't exist: "
        "print 'No data file found' and exit with code 0. Return only the code."
    )
    resp2 = llm.chat([
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": resp1},
        {"role": "user", "content": fix_prompt},
    ])
    code2 = _extract(resp2)
    f2 = tmp_path / "sum_json_fixed.py"
    f2.write_text(code2, encoding="utf-8")
    rc2, out2 = _run(f2)

    ok = rc2 == 0
    save("full_cycle_error_and_retry", ok, {
        "step1_failed": step1_failed,
        "step2_exit": rc2,
        "step2_output": out2[:200],
    })
    assert ok, f"Retry still failed: exit={rc2} output={out2[:200]!r}"


# ── Full cycle: file transform ────────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_full_cycle_file_transform(llm, tmp_path):
    """Agent reads input.txt, transforms content (uppercase), writes output.txt."""
    input_file = tmp_path / "input.txt"
    input_file.write_text("hello world\nfoo bar baz\n", encoding="utf-8")

    prompt = (
        "Write a Python script that reads 'input.txt', converts all text to uppercase, "
        "and writes the result to 'output.txt'. Run in the same directory as the files. "
        "Return only the code."
    )
    resp = llm.chat([{"role": "user", "content": prompt}])
    code = _extract(resp)
    f = tmp_path / "transform.py"
    f.write_text(code, encoding="utf-8")
    rc, out = _run(f)

    output_file = tmp_path / "output.txt"
    if output_file.exists():
        content = output_file.read_text(encoding="utf-8")
        has_upper = "HELLO WORLD" in content
    else:
        content = ""
        has_upper = False

    ok = rc == 0 and has_upper
    save("full_cycle_file_transform", ok, {
        "exit": rc, "output_content": content[:200], "has_upper": has_upper
    })
    assert ok, f"File transform: exit={rc} has_upper={has_upper} content={content[:100]!r}"


# ── Autofix loop corrects imports ─────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_autofix_loop_corrects_imports(llm, tmp_path):
    """Code with a missing import is caught; agent fixes the import in next attempt."""
    # Start with broken code (missing import)
    broken_code = textwrap.dedent("""\
        def get_date():
            return datetime.now().strftime('%Y-%m-%d')

        print(get_date())
    """)
    f = tmp_path / "date_broken.py"
    f.write_text(broken_code, encoding="utf-8")
    rc1, out1 = _run(f)
    step1_failed = rc1 != 0  # NameError: datetime

    prompt = (
        f"This Python code has an error:\n```python\n{broken_code}\n```\n"
        f"Error: {out1[:200]}\n\n"
        "Fix the import and return only the corrected Python code."
    )
    resp = llm.chat([{"role": "user", "content": prompt}])
    fixed_code = _extract(resp)
    f2 = tmp_path / "date_fixed.py"
    f2.write_text(fixed_code, encoding="utf-8")
    rc2, out2 = _run(f2)

    import re as _re
    date_pattern = _re.compile(r"\d{4}-\d{2}-\d{2}")
    has_date = bool(date_pattern.search(out2))

    ok = step1_failed and rc2 == 0 and has_date
    save("autofix_loop_corrects_imports", ok, {
        "step1_failed": step1_failed,
        "step2_exit": rc2,
        "step2_output": out2[:100],
        "has_date": has_date,
    })
    assert ok, f"Import fix: step1_failed={step1_failed} rc2={rc2} has_date={has_date}"


# ── Agent writes then tests itself ────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_agent_writes_then_tests_itself(llm, tmp_path):
    """Agent writes a function, then writes tests for it; tests must pass."""
    # Step 1: write the function
    fn_prompt = (
        "Write a Python function `is_palindrome(s: str) -> bool` "
        "that returns True if s is a palindrome (case-insensitive, ignoring spaces). "
        "Return only the function code."
    )
    resp1 = llm.chat([{"role": "user", "content": fn_prompt}])
    fn_code = _extract(resp1)

    # Step 2: write tests for it
    test_prompt = (
        f"Here is a Python function:\n```python\n{fn_code}\n```\n\n"
        "Write pytest tests for is_palindrome(). Include at least 5 tests: "
        "true cases (racecar, A man a plan a canal Panama), false cases (hello), "
        "edge cases (empty string, single char). "
        "Define the function inline in the test file (copy it above the tests). "
        "Return only the complete test file."
    )
    resp2 = llm.chat([
        {"role": "user", "content": fn_prompt},
        {"role": "assistant", "content": resp1},
        {"role": "user", "content": test_prompt},
    ])
    test_code = _extract(resp2)

    test_file = tmp_path / "test_palindrome.py"
    test_file.write_text(test_code, encoding="utf-8")

    r = subprocess.run(
        [PYTHON_EXE, "-m", "pytest", str(test_file), "-v", "--tb=short"],
        cwd=str(tmp_path), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    output = r.stdout + r.stderr
    passed_count = output.count("PASSED")
    # Also accept "N passed" summary line (compact output)
    m = re.search(r"(\d+) passed", output)
    if m and passed_count == 0:
        passed_count = int(m.group(1))
    ok = r.returncode == 0 and passed_count >= 1

    save("agent_writes_then_tests_itself", ok, {
        "exit": r.returncode,
        "passed_count": passed_count,
        "output_tail": output[-400:],
    })
    assert ok, f"Self-test: rc={r.returncode} passed={passed_count} output={output[-300:]!r}"


# ── Agent produces valid JSON ─────────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
def test_agent_produces_valid_json(llm):
    """Agent asked for a JSON object returns parseable JSON."""
    prompt = (
        "Return a JSON object representing a user profile with these fields: "
        "id (integer), name (string), email (string), age (integer), "
        "skills (array of strings, at least 3). "
        "Return ONLY valid JSON, no explanation, no code fences."
    )
    resp = llm.chat([{"role": "user", "content": prompt}])

    # Try to parse it — strip code fences if present
    cleaned = re.sub(r"```(?:json)?\s*\n?", "", resp).replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        parse_ok = True
    except json.JSONDecodeError:
        # Try extracting JSON block
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                parse_ok = True
            except json.JSONDecodeError:
                data = {}
                parse_ok = False
        else:
            data = {}
            parse_ok = False

    has_name   = "name" in data
    has_email  = "email" in data
    has_skills = isinstance(data.get("skills"), list) and len(data.get("skills", [])) >= 2

    ok = parse_ok and has_name and has_email
    save("agent_produces_valid_json", ok, {
        "parse_ok": parse_ok,
        "has_name": has_name,
        "has_email": has_email,
        "has_skills": has_skills,
        "data_keys": list(data.keys()) if isinstance(data, dict) else [],
    })
    assert ok, f"JSON output invalid: parse_ok={parse_ok} data={str(data)[:200]}"


# ── Agent explains then fixes ────────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_agent_explains_then_fixes(llm, tmp_path):
    """Agent given an error explains it in plain language, then provides working fix."""
    buggy_code = textwrap.dedent("""\
        numbers = [1, 2, 3, 4, 5]
        print(numbers[10])  # IndexError
    """)

    explain_prompt = (
        f"This Python code has a bug:\n```python\n{buggy_code}\n```\n"
        "In one sentence, explain what is wrong."
    )
    explanation = llm.chat([{"role": "user", "content": explain_prompt}])
    has_explanation = len(explanation.strip()) > 20

    fix_prompt = (
        "Now provide the corrected code that prints the last element of the list safely "
        "(using index -1 or len()). Return only the corrected Python code."
    )
    resp_fix = llm.chat([
        {"role": "user", "content": explain_prompt},
        {"role": "assistant", "content": explanation},
        {"role": "user", "content": fix_prompt},
    ])
    fixed_code = _extract(resp_fix)
    f = tmp_path / "fixed_index.py"
    f.write_text(fixed_code, encoding="utf-8")
    rc, out = _run(f)

    ok = has_explanation and rc == 0 and "5" in out

    save("agent_explains_then_fixes", ok, {
        "has_explanation": has_explanation,
        "explanation_snippet": explanation[:150],
        "fix_exit": rc,
        "fix_output": out[:100],
    })
    assert ok, f"Explain+fix: explanation={has_explanation} fix_rc={rc} fix_out={out!r}"


# ── Agent refactors existing code ─────────────────────────────────────────────

@pytest.mark.ollama_live
@pytest.mark.model_quality
@pytest.mark.integration
def test_agent_refactors_existing_code(llm, tmp_path):
    """Agent refactors a monolithic function into smaller helper functions."""
    monolith = textwrap.dedent("""\
        def process_order(order):
            # validate
            if not order.get('item'):
                raise ValueError('item required')
            if not order.get('quantity') or order['quantity'] <= 0:
                raise ValueError('quantity must be positive')
            if not order.get('price') or order['price'] <= 0:
                raise ValueError('price must be positive')
            # calculate
            subtotal = order['quantity'] * order['price']
            tax = subtotal * 0.1
            total = subtotal + tax
            # format
            return {
                'item': order['item'],
                'subtotal': round(subtotal, 2),
                'tax': round(tax, 2),
                'total': round(total, 2),
            }
    """)

    prompt = (
        f"Refactor this Python function into 3 smaller functions: "
        f"_validate_order(), _calculate_totals(), and process_order() that calls them. "
        f"Keep the same behavior and return value.\n```python\n{monolith}\n```\n"
        "Return only the refactored Python code."
    )
    resp = llm.chat([{"role": "user", "content": prompt}])
    refactored = _extract(resp)

    # Verify the refactored code is valid and behaves correctly
    syntax_ok, syntax_err = _syntax_ok(refactored)
    if not syntax_ok:
        save("agent_refactors_existing_code", False, {"syntax_error": syntax_err})
        pytest.fail(f"Refactored code has syntax error: {syntax_err}")

    # Execute with a test order
    test_code = refactored + textwrap.dedent("""
        result = process_order({'item': 'widget', 'quantity': 2, 'price': 10.0})
        print(result['total'])
    """)
    f = tmp_path / "refactored.py"
    f.write_text(test_code, encoding="utf-8")
    rc, out = _run(f)

    # Expected total: (2*10) * 1.1 = 22.0
    try:
        total_val = float(out.strip().split()[-1])
        correct_total = abs(total_val - 22.0) < 0.01
    except (ValueError, IndexError):
        correct_total = False

    has_validate   = "_validate" in refactored or "validate" in refactored
    has_calculate  = "_calculate" in refactored or "calculate" in refactored
    is_split       = refactored.count("def ") >= 2

    ok = syntax_ok and rc == 0 and correct_total and is_split

    save("agent_refactors_existing_code", ok, {
        "syntax_ok": syntax_ok,
        "exit": rc,
        "output": out[:100],
        "correct_total": correct_total,
        "function_count": refactored.count("def "),
        "has_validate": has_validate,
        "has_calculate": has_calculate,
    })
    assert ok, f"Refactor: syntax_ok={syntax_ok} rc={rc} correct_total={correct_total} fns={refactored.count('def ')}"
