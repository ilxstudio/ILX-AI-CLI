"""ILX AI CLI — PyInstaller build script (stdlib only, no shell=True).

Usage:
    python build_exe.py

Produces:
    dist/ilx       (Linux/macOS)
    dist/ilx.exe   (Windows)

Requirements:
    PyInstaller must be installed in the active environment.
    If it is not found, this script prints the install command and exits.
"""
from __future__ import annotations

import importlib.util
import platform
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
ENTRY_POINT = PROJECT_ROOT / "main.py"

# Top-level packages that PyInstaller's static analyser may miss because
# they are imported dynamically (e.g. via importlib or late-binding).
HIDDEN_IMPORTS: list[str] = [
    "app.core",
    "cli",
    "codex.app",
]

EXE_NAME = "ilx"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step(msg: str) -> None:
    print(f"\n>>> {msg}", flush=True)


def _check_pyinstaller() -> None:
    _step("Checking for PyInstaller...")
    if importlib.util.find_spec("PyInstaller") is None:
        print(
            "\n[ERROR] PyInstaller is not installed in the current environment.\n"
            "        Install it with:\n\n"
            "            pip install pyinstaller\n\n"
            "        Then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("    PyInstaller found.")


def _build() -> None:
    _step(f"Building standalone executable: dist/{EXE_NAME} ...")

    hidden_args: list[str] = []
    for imp in HIDDEN_IMPORTS:
        hidden_args += ["--hidden-import", imp]

    cmd: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name", EXE_NAME,
        *hidden_args,
        str(ENTRY_POINT),
    ]

    print(f"    Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(
            "\n[ERROR] PyInstaller exited with a non-zero return code.\n"
            "        Check the output above for details.",
            file=sys.stderr,
        )
        sys.exit(result.returncode)


def _report() -> None:
    suffix = ".exe" if platform.system() == "Windows" else ""
    output = PROJECT_ROOT / "dist" / f"{EXE_NAME}{suffix}"
    print("\n" + "=" * 60)
    if output.exists():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"  Build complete!")
        print(f"  Output : {output}")
        print(f"  Size   : {size_mb:.1f} MB")
    else:
        print("  Build finished but output file was not found.")
        print(f"  Expected: {output}")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  ILX AI CLI — PyInstaller Build")
    print("=" * 60)

    _check_pyinstaller()
    _build()
    _report()


if __name__ == "__main__":
    main()
