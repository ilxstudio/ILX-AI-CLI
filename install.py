"""ILX AI CLI — standalone installer (stdlib only, no shell=True).

Usage:
    python install.py

What it does:
  1. Verifies Python >= 3.12.
  2. Creates a virtual environment at .venv/ next to this script.
  3. Installs the package in editable mode with all optional dependencies.
  4. Creates a thin launcher wrapper (ilx.bat on Windows, ilx on Unix)
     in the project root so you can run `ilx` directly after adding the
     folder to your PATH.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_PYTHON = (3, 12)
PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step(msg: str) -> None:
    print(f"\n>>> {msg}", flush=True)


def _check_python() -> None:
    _step("Checking Python version...")
    v = sys.version_info
    print(f"    Found Python {v.major}.{v.minor}.{v.micro}")
    if (v.major, v.minor) < MIN_PYTHON:
        print(
            f"\n[ERROR] Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required.\n"
            f"        You are running Python {v.major}.{v.minor}.\n"
            f"        Download a newer version from https://python.org/downloads/",
            file=sys.stderr,
        )
        sys.exit(1)
    print("    OK")


def _create_venv() -> None:
    _step(f"Creating virtual environment at {VENV_DIR} ...")
    if VENV_DIR.exists():
        print("    .venv/ already exists — skipping creation.")
        return
    subprocess.run(
        [sys.executable, "-m", "venv", str(VENV_DIR)],
        check=True,
    )
    print("    Done.")


def _venv_python() -> Path:
    """Return the path to the Python interpreter inside the venv."""
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _venv_ilx() -> Path:
    """Return the path to the ilx entry-point script inside the venv."""
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "ilx.exe"
    return VENV_DIR / "bin" / "ilx"


def _install_package() -> None:
    _step('Installing ilx-ai-cli with pip install -e ".[all]" ...')
    python = _venv_python()
    subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "-e", ".[all]"],
        cwd=str(PROJECT_ROOT),
        check=True,
    )
    print("    Package installed.")


def _create_launcher() -> None:
    _step("Creating launcher wrapper in project root...")
    if platform.system() == "Windows":
        bat_path = PROJECT_ROOT / "ilx.bat"
        ilx_exe = _venv_ilx()
        bat_path.write_text(
            f'@echo off\r\n"{ilx_exe}" %*\r\n',
            encoding="utf-8",
        )
        print(f"    Created: {bat_path}")
        print(
            "\n    To use 'ilx' from any directory, add the following folder to\n"
            "    your PATH (System Environment Variables):\n"
            f"\n        {PROJECT_ROOT}\n"
        )
    else:
        wrapper_path = PROJECT_ROOT / "ilx"
        ilx_bin = _venv_ilx()
        wrapper_path.write_text(
            f'#!/bin/sh\nexec "{ilx_bin}" "$@"\n',
            encoding="utf-8",
        )
        wrapper_path.chmod(0o755)
        print(f"    Created: {wrapper_path}")
        print(
            "\n    To use 'ilx' from any directory, add the following folder to\n"
            "    your PATH (e.g. in ~/.bashrc or ~/.zshrc):\n"
            f"\n        export PATH=\"{PROJECT_ROOT}:$PATH\"\n"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  ILX AI CLI — Installer")
    print("=" * 60)

    _check_python()
    _create_venv()
    _install_package()
    _create_launcher()

    print("\n" + "=" * 60)
    print("  Installation complete!")
    print("  Run:  ilx --help")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
