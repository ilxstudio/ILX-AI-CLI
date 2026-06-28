#!/usr/bin/env python3
"""Verify version consistency between app/version.py and pyproject.toml."""
# MIT License — Copyright 2026 ILX Studio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def get_version_py() -> str:
    text = (ROOT / "app" / "version.py").read_text()
    m = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else ""


def get_version_toml() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return m.group(1) if m else ""


def main() -> int:
    v_py = get_version_py()
    v_toml = get_version_toml()
    if v_py == v_toml:
        print(f"OK: version {v_py}")
        return 0
    print(f"FAIL: app/version.py={v_py!r} != pyproject.toml={v_toml!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
