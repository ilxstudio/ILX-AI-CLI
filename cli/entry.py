"""Installed entry point for ilx — delegates to main.main()."""
from __future__ import annotations

import sys
from pathlib import Path

# when installed via pip the package root is the parent of the cli/ package
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    from main import main as _main
    _main()
