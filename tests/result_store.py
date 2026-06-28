"""Audit result store — every test writes a result JSON for post-run inspection."""
from __future__ import annotations

import json
import time
from pathlib import Path

_RESULTS_DIR = Path(__file__).parent / "results"


def save(test_name: str, passed: bool, data: dict) -> Path:
    """Write result_<test_name>.json to tests/results/. Returns path."""
    _RESULTS_DIR.mkdir(exist_ok=True)
    payload = {
        "test":    test_name,
        "passed":  passed,
        "ts":      time.strftime("%Y-%m-%dT%H:%M:%S"),
        **data,
    }
    out = _RESULTS_DIR / f"result_{test_name}.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out
