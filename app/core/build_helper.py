"""Helpers for /build command — wraps PyInstaller for EXE generation."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def pyinstaller_available() -> bool:
    return shutil.which("pyinstaller") is not None


def install_pyinstaller() -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode == 0, (r.stdout + r.stderr)[-500:]
    except Exception as exc:
        return False, str(exc)


def build(
    entry: str,
    workspace: str,
    onefile: bool = True,
    on_output=None,
) -> tuple[bool, str]:
    """Run PyInstaller on *entry* inside *workspace*.

    Returns (success, summary_message).
    *on_output(line)* is called for each line of build output.
    """
    if not pyinstaller_available():
        return False, "PyInstaller not found. Install with: pip install pyinstaller"

    cmd = ["pyinstaller", "--noconfirm", "--clean"]
    if onefile:
        cmd.append("--onefile")
    cmd.append(entry)

    try:
        proc = subprocess.Popen(
            cmd, cwd=workspace,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_output:
                on_output(line.rstrip())
        proc.wait(timeout=600)

        dist_dir = Path(workspace) / "dist"
        if proc.returncode == 0 and dist_dir.exists():
            exes = list(dist_dir.glob("*.exe")) + list(dist_dir.glob(Path(entry).stem))
            loc = exes[0] if exes else dist_dir
            return True, f"Build complete: {loc}"
        else:
            return False, f"PyInstaller exited with code {proc.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Build timed out after 600s"
    except Exception as exc:
        return False, f"Build error: {exc}"


def bump_version(workspace: str) -> str | None:
    """Bump patch version in version.py. Returns new version string or None."""
    vpath = Path(workspace) / "version.py"
    if not vpath.exists():
        vpath = Path(workspace) / "app" / "version.py"
    if not vpath.exists():
        return None
    try:
        text = vpath.read_text(encoding="utf-8")
        import re
        m = re.search(r'VERSION\s*=\s*["\'](\d+)\.(\d+)\.(\d+)["\'"]', text)
        if not m:
            return None
        major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
        new_ver = f"{major}.{minor}.{patch + 1}"
        new_text = text[:m.start()] + f'VERSION = "{new_ver}"' + text[m.end():]
        vpath.write_text(new_text, encoding="utf-8")
        return new_ver
    except Exception:
        return None
