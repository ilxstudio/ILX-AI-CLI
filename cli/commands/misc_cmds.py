"""Miscellaneous command helpers — /version, /export, /alias, /copy,
/env, /search, /profile, /notify.

These are thin wrappers kept out of cli/app.py to stay under the 700-line
limit; they take all the state they need as arguments rather than living as
ILXApp methods.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig


def cmd_version(cfg: AppConfig) -> None:
    """Show ILX AI CLI version, Python info, platform, and active provider/model."""
    import platform
    import sys

    from app.version import VERSION
    from cli.display import BOLD, CYAN, DIM, GREEN, RESET

    print(f"\n{BOLD}ILX AI CLI{RESET}  {CYAN}v{VERSION}{RESET}")
    print(f"  {DIM}Python     {RESET}{sys.version.split()[0]}  ({sys.executable})")
    print(f"  {DIM}Platform   {RESET}{platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  {DIM}Provider   {RESET}{GREEN}{cfg.provider}{RESET}")
    print(f"  {DIM}Model      {RESET}{cfg.ollama_model}")
    if cfg.chat_model:
        print(f"  {DIM}Chat model {RESET}{cfg.chat_model}")
    print()


def cmd_export(cfg: AppConfig, history: list[dict], args: list[str]) -> None:
    """Export current conversation history to a Markdown file."""
    from datetime import datetime

    from cli.display import DIM, GREEN, RESET, YELLOW

    if not history:
        print(f"  {YELLOW}Nothing to export — conversation history is empty.{RESET}")
        return

    date_str  = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args:
        out_path = Path(args[0])
    else:
        workspace = cfg.working_folder or str(Path.home() / "Documents")
        out_path = Path(workspace) / f"ilx_session_{timestamp}.md"

    lines: list[str] = [f"# ILX AI Session — {date_str}\n"]
    role_map = {"user": "You", "assistant": "ILX AI", "system": "System"}
    for msg in history:
        role    = msg.get("role", "unknown")
        label   = role_map.get(role, role.title())
        content = msg.get("content", "").strip()
        lines.append(f"## {label}\n\n{content}\n")

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  {GREEN}Exported {len(history)} messages to:{RESET}  {DIM}{out_path}{RESET}")
    except OSError as exc:
        print(f"  {YELLOW}Export failed: {exc}{RESET}")


def cmd_alias(alias_store, args: list[str]) -> None:
    """/alias [list | <name> <command> | remove <name>]"""
    from cli.display import BOLD, CYAN, DIM, GREEN, RESET, YELLOW

    if not args or args[0].lower() == "list":
        aliases = alias_store.all()
        if not aliases:
            print(f"  {DIM}No aliases defined. Use /alias <name> <command> to add one.{RESET}")
        else:
            print(f"\n{BOLD}Aliases:{RESET}")
            for name, cmd in sorted(aliases.items()):
                print(f"  {CYAN}/{name}{RESET}  →  {DIM}{cmd}{RESET}")
            print()
        return

    if args[0].lower() == "remove" and len(args) >= 2:
        name = args[1].lstrip("/")
        if alias_store.remove(name):
            print(f"  {GREEN}Alias '/{name}' removed.{RESET}")
        else:
            print(f"  {YELLOW}No alias named '/{name}'.{RESET}")
        return

    if len(args) >= 2:
        name    = args[0].lstrip("/")
        command = " ".join(args[1:])
        if not command.startswith("/"):
            command = "/" + command
        alias_store.set(name, command)
        print(f"  {GREEN}Alias set:{RESET}  {CYAN}/{name}{RESET}  →  {DIM}{command}{RESET}")
        return

    print(f"  {YELLOW}Usage: /alias list | /alias <name> <command> | /alias remove <name>{RESET}")


def cmd_copy(history: list[dict]) -> None:
    """Copy the last AI response to the clipboard."""
    from cli.display import DIM, GREEN, RESET, YELLOW

    last_ai = next(
        (m["content"] for m in reversed(history) if m.get("role") == "assistant"),
        None,
    )
    if not last_ai:
        print(f"  {YELLOW}No AI response in history to copy.{RESET}")
        return
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(last_ai)
        preview = last_ai[:80].replace("\n", " ")
        print(
            f"  {GREEN}Copied to clipboard.{RESET}  {DIM}{preview}{'…' if len(last_ai) > 80 else ''}{RESET}"
        )
    except ImportError:
        print(
            f"  {YELLOW}pyperclip not installed — run: pip install pyperclip{RESET}\n"
            f"  {DIM}Last response ({len(last_ai)} chars):{RESET}\n{last_ai}"
        )
    except Exception as exc:
        print(f"  {YELLOW}Could not copy to clipboard: {exc}{RESET}")


# ---------------------------------------------------------------------------
# FEAT-2: /env — environment summary
# ---------------------------------------------------------------------------

def cmd_env(args: list[str], cfg: AppConfig) -> None:
    """Show current environment info relevant to ILX AI. Use --json for scripting."""
    import importlib.util
    import os
    import platform
    import sys

    from app.version import VERSION

    want_json = "--json" in args

    # Optional dependency check
    _opt_deps = ["Pillow", "pypdf", "python-docx", "rank-bm25", "pyreadline3"]
    dep_status: dict[str, bool] = {}
    for dep in _opt_deps:
        import_name = dep.replace("-", "_").replace("python_docx", "docx")
        if dep == "Pillow":
            import_name = "PIL"
        elif dep == "python-docx":
            import_name = "docx"
        dep_status[dep] = importlib.util.find_spec(import_name) is not None

    # API key presence (by env var name, not value)
    _key_vars = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai":    "OPENAI_API_KEY",
        "groq":      "GROQ_API_KEY",
        "gemini":    "GEMINI_API_KEY",
        "meta":      "META_API_KEY",
    }
    key_status: dict[str, bool] = {
        prov: bool(os.environ.get(var, "")) for prov, var in _key_vars.items()
    }

    env_count = len(os.environ)

    data: dict = {
        "ilx_version":      VERSION,
        "python_version":   sys.version.split()[0],
        "python_path":      sys.executable,
        "platform":         platform.system(),
        "os_version":       platform.version(),
        "machine":          platform.machine(),
        "provider":         cfg.provider,
        "model":            cfg.ollama_model,
        "chat_model":       cfg.chat_model or None,
        "working_folder":   cfg.working_folder,
        "ollama_url":       cfg.ollama_url if cfg.provider == "ollama" else None,
        "env_var_count":    env_count,
        "api_keys":         key_status,
        "optional_deps":    dep_status,
    }

    if want_json:
        import json
        print(json.dumps(data, indent=2))
        return

    from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET

    def _tick(ok: bool) -> str:
        return f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"

    print(f"\n{BOLD}ILX AI Environment{RESET}")
    print(f"  {DIM}Version        {RESET}{CYAN}{VERSION}{RESET}")
    print(f"  {DIM}Python         {RESET}{data['python_version']}  ({data['python_path']})")
    print(f"  {DIM}Platform       {RESET}{data['platform']} {data['os_version']} ({data['machine']})")
    print(f"  {DIM}Provider       {RESET}{cfg.provider}")
    print(f"  {DIM}Model          {RESET}{cfg.ollama_model}" +
          (f"  (chat: {cfg.chat_model})" if cfg.chat_model else ""))
    print(f"  {DIM}Working folder {RESET}{cfg.working_folder}")
    if cfg.provider == "ollama":
        print(f"  {DIM}Ollama URL     {RESET}{cfg.ollama_url}")
    print(f"  {DIM}Env vars       {RESET}{env_count} (values not shown)")
    print(f"\n{BOLD}API keys configured:{RESET}")
    for prov, ok in key_status.items():
        print(f"  {_tick(ok)}  {prov}")
    print(f"\n{BOLD}Optional dependencies:{RESET}")
    for dep, ok in dep_status.items():
        print(f"  {_tick(ok)}  {dep}")
    print()


# ---------------------------------------------------------------------------
# FEAT-3: /search — find text across conversation history
# ---------------------------------------------------------------------------

def cmd_search_history(args: list[str], cfg: AppConfig) -> None:
    """Search session history files for a query string."""
    from pathlib import Path

    from cli.display import BOLD, CYAN, DIM, RESET, YELLOW

    if not args:
        print(f"  {YELLOW}Usage: /search <query>{RESET}")
        print(f"  {DIM}Searches all saved sessions for the given text (case-insensitive).{RESET}")
        return

    query = " ".join(args).lower()
    session_dir = Path.home() / ".ilx_cli" / "sessions"

    if not session_dir.exists():
        print(f"  {YELLOW}No session directory found at {session_dir}{RESET}")
        return

    session_files = sorted(
        session_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not session_files:
        print(f"  {YELLOW}No saved sessions found.{RESET}")
        return

    import json
    from datetime import datetime

    matches: list[dict] = []
    for sf in session_files:
        if len(matches) >= 10:
            break
        try:
            lines = sf.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        meta: dict = {}
        snippets: list[str] = []
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if obj.get("_meta"):
                meta = obj
                continue
            content = obj.get("content", "")
            if query in content.lower():
                # Grab a 120-char snippet around the first match
                idx = content.lower().find(query)
                start = max(0, idx - 40)
                end   = min(len(content), idx + 80)
                snippet = content[start:end].replace("\n", " ").strip()
                if start > 0:
                    snippet = "…" + snippet
                if end < len(content):
                    snippet = snippet + "…"
                snippets.append(snippet)
        if snippets:
            ts_raw = meta.get("ts", sf.stem)
            try:
                ts_str = datetime.fromisoformat(ts_raw).strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts_str = sf.stem
            matches.append({
                "ts":      ts_str,
                "model":   meta.get("model", "?"),
                "provider": meta.get("provider", "?"),
                "snippets": snippets[:2],
            })

    if not matches:
        print(f"  {YELLOW}No sessions matched '{query}'.{RESET}")
        return

    print(f"\n{BOLD}Search results for '{query}' — {len(matches)} session(s):{RESET}\n")
    for m in matches:
        print(f"  {CYAN}{m['ts']}{RESET}  {DIM}{m['provider']}/{m['model']}{RESET}")
        for snippet in m["snippets"]:
            print(f"    {DIM}…{snippet}…{RESET}")
        print()


# ---------------------------------------------------------------------------
# FEAT-4: /profile — full system profile for bug reports
# ---------------------------------------------------------------------------

def cmd_profile(args: list[str], cfg: AppConfig) -> None:
    """Collect and display a full system profile for bug reports."""
    import importlib.metadata
    import os
    import platform
    import sys
    import time

    from app.version import VERSION

    want_json = "--json" in args

    # Installed dependency versions
    _tracked = ["httpx", "keyring", "pyperclip", "Pillow", "pypdf",
                "python-docx", "rank-bm25", "pyreadline3", "rich"]
    dep_versions: dict[str, str] = {}
    for pkg in _tracked:
        try:
            dep_versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            dep_versions[pkg] = "not installed"

    # Ollama reachability
    ollama_ok   = False
    ollama_ms   = None
    if cfg.provider == "ollama":
        try:
            import httpx
            t0 = time.monotonic()
            r  = httpx.get(f"{cfg.ollama_url.rstrip('/')}/api/tags", timeout=4.0)
            ollama_ok = r.status_code == 200
            ollama_ms = round((time.monotonic() - t0) * 1000)
        except Exception:
            pass

    # Recent crashes
    from app.core import crash_db
    recent_crashes = crash_db.list_crashes(limit=3)

    profile: dict = {
        "ilx_version":      VERSION,
        "python_version":   sys.version.split()[0],
        "python_impl":      platform.python_implementation(),
        "platform":         platform.platform(),
        "architecture":     platform.machine(),
        "cpu_count":        os.cpu_count(),
        "provider":         cfg.provider,
        "model":            cfg.ollama_model,
        "permission_mode":  cfg.permission_mode.value,
        "ollama_reachable": ollama_ok,
        "ollama_latency_ms": ollama_ms,
        "dependencies":     dep_versions,
        "recent_errors":    [
            {"ts": c["ts"], "command": c["command"],
             "exit_code": c["exit_code"], "tb_snippet": c["tb"][:200]}
            for c in recent_crashes
        ],
    }

    if want_json:
        import json
        print(json.dumps(profile, indent=2))
        return

    from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET

    print(f"\n{BOLD}ILX AI System Profile{RESET}  {DIM}(copy this for bug reports){RESET}\n")
    print(f"  ILX version  : {CYAN}{VERSION}{RESET}")
    print(f"  Python       : {profile['python_version']} ({profile['python_impl']})")
    print(f"  Platform     : {profile['platform']}")
    print(f"  Architecture : {profile['architecture']}  CPUs: {profile['cpu_count']}")
    print(f"  Provider     : {cfg.provider}  Model: {cfg.ollama_model}")
    print(f"  Permissions  : {cfg.permission_mode.value}")
    if cfg.provider == "ollama":
        reach = f"{GREEN}reachable{RESET} ({ollama_ms} ms)" if ollama_ok else f"{RED}unreachable{RESET}"
        print(f"  Ollama       : {cfg.ollama_url}  [{reach}]")

    print(f"\n{BOLD}Dependencies:{RESET}")
    for pkg, ver in dep_versions.items():
        marker = f"{GREEN}{ver}{RESET}" if ver != "not installed" else f"{DIM}not installed{RESET}"
        print(f"  {pkg:<20} {marker}")

    print(f"\n{BOLD}Recent errors ({len(recent_crashes)}):{RESET}")
    if not recent_crashes:
        print(f"  {DIM}No recorded errors.{RESET}")
    for c in recent_crashes:
        print(f"  [{c['ts'][:19]}] exit={c['exit_code']}  cmd={c['command']}")
        print(f"    {DIM}{c['tb'][:120].replace(chr(10), ' ')}{RESET}")
    print()


# ---------------------------------------------------------------------------
# FEAT-5: /notify — desktop notifications toggle
# ---------------------------------------------------------------------------

def cmd_notify(args: list[str], cfg: AppConfig) -> None:
    """/notify on | off | test — manage desktop notifications."""
    from app.core.notifications import send_notification
    from cli.display import DIM, GREEN, RESET, YELLOW

    sub = args[0].lower() if args else ""

    if sub == "on":
        cfg.notifications_enabled = True  # type: ignore[attr-defined]
        # Persist if config manager is available
        try:
            from app.core.config import ConfigManager
            ConfigManager().save(cfg)
        except Exception:
            pass
        print(f"  {GREEN}Desktop notifications enabled.{RESET}")

    elif sub == "off":
        cfg.notifications_enabled = False  # type: ignore[attr-defined]
        try:
            from app.core.config import ConfigManager
            ConfigManager().save(cfg)
        except Exception:
            pass
        print(f"  {DIM}Desktop notifications disabled.{RESET}")

    elif sub == "test":
        ok = send_notification("ILX AI", "Test notification from ILX AI CLI.", cfg)
        if ok:
            print(f"  {GREEN}Test notification sent.{RESET}")
        else:
            print(f"  {YELLOW}Notification could not be sent — see above for details.{RESET}")

    else:
        print(f"  {YELLOW}Usage: /notify on | off | test{RESET}")
        enabled = getattr(cfg, "notifications_enabled", False)
        state = "enabled" if enabled else "disabled"
        print(f"  {DIM}Notifications are currently {state}.{RESET}")
