"""Build a sanitized diagnostic bundle for support / QA handoffs.

The bundle is a single ``ilx_cli_diagnostics_<timestamp>.zip`` containing:

- ``config.json``       — current settings with ``api_key`` redacted
- ``audit.log``         — last 1 MB of the JSONL audit trail
- ``app_version.txt``   — VERSION + Python + platform info
- ``system_info.json``  — structured system diagnostics dict
- ``installed.txt``     — ``pip freeze`` output
- ``README.txt``        — short note explaining what's inside

Nothing in the bundle should leak credentials.  ``api_key`` is the only
field we redact today, but the redaction is centralized so future
secret-shaped fields can be added in one place.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.core import process_runner

_log = logging.getLogger("ilx_cli.diagnostics")

_HOME_DIR  = Path.home() / ".ilx_cli"
_CONFIG    = _HOME_DIR / "config.json"
_AUDIT_LOG = _HOME_DIR / "logs" / "audit.log"

_REDACT_KEYS = {"api_key", "password", "secret", "token", "credential", "private_key", "access_key"}
_REDACT_PATTERNS = ("api_key", "secret", "token", "password", "credential", "private", "access_key")


def _sanitized_config() -> dict:
    if not _CONFIG.is_file():
        return {}
    try:
        raw = json.loads(_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"_error": f"could not read config.json: {exc}"}
    if not isinstance(raw, dict):
        return {"_error": "config.json is not an object"}
    clean: dict = {}
    for k, v in raw.items():
        if (k.lower() in _REDACT_KEYS or any(p in k.lower() for p in _REDACT_PATTERNS)) and isinstance(v, str) and v:
            clean[k] = f"<redacted: {len(v)} chars>"
        else:
            clean[k] = v
    return clean


def _audit_tail(max_bytes: int = 1_000_000) -> bytes:
    if not _AUDIT_LOG.is_file():
        return b""
    try:
        size = _AUDIT_LOG.stat().st_size
        with open(_AUDIT_LOG, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()
            return f.read()
    except OSError:
        return b""


def _pip_freeze() -> str:
    r = process_runner.run([sys.executable, "-m", "pip", "freeze"], timeout=10)
    if not r.ok:
        if r.returncode == -1:
            return f"<pip freeze failed: {r.stderr}>"
        return f"<pip freeze exit {r.returncode}>\n{r.stderr}"
    return r.stdout


def _version_info() -> str:
    try:
        from app.version import VERSION
    except ImportError:
        VERSION = "?"
    lines = [
        f"ILX AI CLI version: {VERSION}",
        f"Python:            {sys.version.split()[0]}",
        f"Platform:          {platform.platform()}",
        f"Machine:           {platform.machine()}",
        f"Cwd:               {os.getcwd()}",
        f"Bundle built:      {datetime.now(timezone.utc).isoformat()}",
    ]
    return "\n".join(lines) + "\n"


def system_info() -> dict:
    """Return a dict of system diagnostics useful for support."""
    try:
        from app.version import VERSION
    except ImportError:
        VERSION = "?"
    info: dict = {
        "version": VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cwd": os.getcwd(),
        "home": str(Path.home()),
    }
    # Check Ollama config
    config = _sanitized_config()
    info["ollama_url"] = config.get("ollama_url", "not configured")
    info["provider"]   = config.get("provider", "ollama")
    info["model"]      = config.get("ollama_model", "not configured")
    # Check session dir
    sess_dir = Path.home() / ".ilx_cli" / "sessions"
    try:
        sess_count = len(list(sess_dir.glob("*.jsonl"))) if sess_dir.exists() else 0
    except OSError:
        sess_count = 0
    info["saved_sessions"] = sess_count
    # Check crash DB
    crash_db = Path.home() / ".ilx_cli" / "crashes.db"
    info["crash_db_exists"] = crash_db.exists()
    return info


def export(out_path: Path | str) -> Path:
    """Write a diagnostic ZIP to ``out_path`` and return the resolved path.

    Raises ``OSError`` if the ZIP can't be written.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    config_text  = json.dumps(_sanitized_config(), indent=2, sort_keys=True)
    audit_bytes  = _audit_tail()
    version_txt  = _version_info()
    sysinfo_txt  = json.dumps(system_info(), indent=2)
    installed    = _pip_freeze()

    readme = (
        "ILX AI CLI diagnostic bundle\n"
        "----------------------------\n\n"
        "Contents:\n"
        "  config.json        — settings with API keys / secrets redacted\n"
        "  audit.log          — last 1 MB of the activity audit log\n"
        "  app_version.txt    — app + Python + platform versions\n"
        "  system_info.json   — structured system diagnostics (Ollama config, sessions, crash DB)\n"
        "  installed.txt      — output of `pip freeze`\n\n"
        "If you got this file from a user, any api_key field has been\n"
        "scrubbed; nothing in this archive should be treated as a\n"
        "credential.  On builds with OS-keychain support enabled, the\n"
        "api_key is stored in the system keychain (macOS Keychain,\n"
        "Windows Credential Manager, GNOME Keyring) and never written\n"
        "to config.json in the first place — so an absent api_key here\n"
        "does NOT mean the user has not signed in.  Open `audit.log`\n"
        "in any text editor — every line is one JSON event.\n"
    )

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt",        readme)
        zf.writestr("app_version.txt",   version_txt)
        zf.writestr("system_info.json",  sysinfo_txt)
        zf.writestr("config.json",       config_text)
        zf.writestr("audit.log",         audit_bytes)
        zf.writestr("installed.txt",     installed)

    return out.resolve()


def default_export_filename() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"ilx_cli_diagnostics_{ts}.zip"
