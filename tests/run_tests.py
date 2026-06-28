"""Standalone test runner — runs all ILX AI CLI tests and prints an audit summary.

Usage:
  python tests/run_tests.py
  python tests/run_tests.py --fast    # skip live LLM tests (clusters 01, 03)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_ROOT  = Path(__file__).resolve().parent.parent
_TESTS = Path(__file__).resolve().parent
_RESULTS = _TESTS / "results"

CLUSTERS = [
    ("01_llm_connection",   "test_01_llm_connection.py",   False),
    ("02_context_display",  "test_02_context_and_display.py", True),
    ("03_code_generation",  "test_03_code_generation.py",  False),
    ("04_settings_git",     "test_04_settings_and_git.py", True),
    ("05_dev_tools",        "test_05_dev_tools.py",        True),
    ("06_workspace_rules",  "test_06_workspace_and_rules.py", True),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="ILX AI CLI test runner")
    parser.add_argument("--fast", action="store_true", help="Skip live LLM clusters (01, 03)")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  ILX AI CLI — Test Suite")
    print("=" * 60)

    py = sys.executable
    results: list[dict] = []

    for cluster_id, filename, offline_ok in CLUSTERS:
        if args.fast and not offline_ok:
            print(f"\n[SKIP] {cluster_id}  (--fast, needs live LLM)")
            continue

        test_file = str(_TESTS / filename)
        print(f"\n[RUN]  {cluster_id}")
        r = subprocess.run(
            [py, "-m", "pytest", test_file, "-v", "--tb=short", "--no-header"],
            capture_output=True, text=True, cwd=str(_ROOT),
            encoding="utf-8", errors="replace",
        )
        passed = r.returncode == 0
        lines  = (r.stdout + r.stderr).strip().splitlines()
        summary = next((l for l in reversed(lines) if l.strip().startswith("=")), lines[-1] if lines else "")
        print(f"  {'PASS' if passed else 'FAIL'}  {summary.strip()}")
        if not passed:
            for ln in lines[-20:]:
                print(f"    {ln}")
        results.append({"cluster": cluster_id, "passed": passed, "summary": summary})

    # ── Read per-test result.json files ───────────────────────────────────────
    print("\n" + "─" * 60)
    print("  Per-test audit results:")
    audit_files = sorted(_RESULTS.glob("result_*.json")) if _RESULTS.exists() else []
    pass_count = fail_count = 0
    for af in audit_files:
        try:
            data = json.loads(af.read_text(encoding="utf-8"))
            status = "PASS" if data.get("passed") else "FAIL"
            if data.get("passed"):
                pass_count += 1
            else:
                fail_count += 1
            print(f"  {status}  {data.get('test', af.stem):<40}  {data.get('ts', '')}")
        except Exception:
            print(f"  ????  {af.name}")

    # ── Cluster summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    total  = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"  Clusters:    {passed}/{total} passed")
    print(f"  Unit tests:  {pass_count} passed, {fail_count} failed")
    print(f"  Audit files: {_RESULTS}")
    print("=" * 60 + "\n")

    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
