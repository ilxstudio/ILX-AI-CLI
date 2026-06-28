"""Settings commands — /server, /model, /provider, /workspace, /perms, /numctx, /status."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig, ConfigManager

_log = logging.getLogger("ilx_cli.settings")

# Module-level TTL cache for model list queries.
# Maps ollama_url -> (timestamp, result_tuple) so repeated /models calls
# within 30 seconds skip the network round-trip entirely.
_models_cache: dict[str, tuple[float, tuple[bool, list[str]]]] = {}
_MODELS_CACHE_TTL = 30.0


def _get_models_cached(ollama_url: str) -> tuple[bool, list[str]]:
    """Fetch available models, using a 30-second TTL cache keyed on ollama_url."""
    now = time.monotonic()
    entry = _models_cache.get(ollama_url)
    if entry is not None:
        ts, result = entry
        if now - ts < _MODELS_CACHE_TTL:
            _log.debug("models cache hit for %s (age %.1fs)", ollama_url, now - ts)
            return result
    result = _check_ollama(ollama_url)
    _models_cache[ollama_url] = (now, result)
    _log.debug("models cache miss for %s — fetched fresh", ollama_url)
    return result


def _check_ollama(url: str) -> tuple[bool, list[str]]:
    try:
        import httpx
        r = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=4.0)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        return True, models
    except Exception:
        return False, []


def _fetch_cloud_models(cfg) -> list[str]:
    """Return a list of available model names for the configured cloud provider.

    For providers with a public models endpoint (openai, groq) the list is
    fetched live and filtered to relevant model IDs.  Anthropic and Gemini
    return a hardcoded current list since they have no public endpoint.
    Falls back to a static list on any network error.
    """
    import httpx

    from app.core import secret_store

    provider = cfg.provider

    if provider == "anthropic":
        return [
            "claude-opus-4-8",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ]

    if provider == "gemini":
        return [
            "gemini-2.0-flash",
            "gemini-1.5-flash-latest",
            "gemini-1.5-pro-latest",
        ]

    if provider == "openai":
        _fallback = ["gpt-4o", "gpt-4o-mini", "o3"]
        key = secret_store.get_api_key("openai") or secret_store.get_api_key()
        if not key:
            return _fallback
        try:
            r = httpx.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8.0,
            )
            r.raise_for_status()
            import re
            ids = [m["id"] for m in r.json().get("data", [])]
            filtered = [i for i in ids if re.match(r"gpt-|o[0-9]", i)]
            return sorted(filtered) if filtered else _fallback
        except Exception:
            return _fallback

    if provider == "groq":
        _fallback = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it"]
        key = secret_store.get_api_key("groq") or secret_store.get_api_key()
        if not key:
            return _fallback
        try:
            r = httpx.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8.0,
            )
            r.raise_for_status()
            ids = [
                m["id"] for m in r.json().get("data", [])
                if not m.get("deprecated", False)
            ]
            return sorted(ids) if ids else _fallback
        except Exception:
            return _fallback

    return []


class SettingsCommands:
    """Handles all settings-related slash commands."""

    def __init__(self, cfg: AppConfig, mgr: ConfigManager) -> None:
        self.cfg = cfg
        self.mgr = mgr

    def check_ollama(self, url: str | None = None) -> tuple[bool, list[str]]:
        return _check_ollama(url or self.cfg.ollama_url)

    def cmd_status(self) -> None:
        from cli.display import BOLD, CYAN, GREEN, RED, RESET
        cfg = self.cfg
        if cfg.provider == "ollama":
            ok, _ = _check_ollama(cfg.ollama_url)
            srv_status = f"{GREEN}online{RESET}" if ok else f"{RED}offline{RESET}"
            server_line = f"  Ollama server : {cfg.ollama_url}  [{srv_status}]"
        else:
            server_line = f"  Provider      : {CYAN}{cfg.provider}{RESET}"
        print(f"""
{BOLD}Current settings:{RESET}
{server_line}
  Model         : {cfg.ollama_model}{f"  (chat: {cfg.chat_model})" if cfg.chat_model else ""}
  Num context   : {cfg.num_ctx} tokens
  Workspace     : {cfg.working_folder}
  Permissions   : {cfg.permission_mode.value}
  Auto-fix      : {cfg.autofix_enabled}  (max {cfg.autofix_max_iterations} attempts)
  Exec timeout  : {cfg.exec_timeout}s
""")

    def cmd_server(self) -> None:
        from cli.display import CYAN, DIM, GREEN, RED, RESET, YELLOW
        cfg = self.cfg
        print(f"\nCurrent Ollama server: {CYAN}{cfg.ollama_url}{RESET}")
        print(f"  {DIM}Examples:  http://localhost:11434   http://192.168.50.100:11434{RESET}")
        val = input("New server URL (blank to keep): ").strip()
        if not val:
            return
        if not val.startswith("http"):
            val = "http://" + val
        val = val.rstrip("/")
        print(f"  {DIM}Checking connectivity...{RESET}", end="", flush=True)
        ok, models = _check_ollama(val)
        if ok:
            cfg.ollama_url = val
            self.mgr.save(cfg)
            print(f"\r  {GREEN}Connected!{RESET} Server: {cfg.ollama_url}")
            if models:
                print(f"  Available models: {', '.join(models)}")
        else:
            print(f"\r  {RED}Could not reach {val}{RESET}")
            ans = input("  Save anyway? [y/N] ").strip().lower()
            if ans in ("y", "yes"):
                cfg.ollama_url = val
                self.mgr.save(cfg)
                print(f"  {YELLOW}Saved (unverified): {cfg.ollama_url}{RESET}")

    def cmd_model(self) -> None:
        from cli.display import CYAN, DIM, GREEN, RESET, YELLOW
        cfg = self.cfg
        print(f"\nCurrent model: {CYAN}{cfg.ollama_model}{RESET}")
        val = input("New model name (blank to keep): ").strip()
        if not val:
            return
        if cfg.provider == "ollama":
            ok, mlist = _get_models_cached(cfg.ollama_url)
            if ok and mlist and val not in mlist:
                print(f"  {YELLOW}Warning: '{val}' not in server model list.{RESET}")
                print(f"  {DIM}Pull it with: ollama pull {val}{RESET}")
        cfg.ollama_model = val
        self.mgr.save(cfg)
        print(f"{GREEN}Model set to: {cfg.ollama_model}{RESET}")

    def cmd_models(self) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, RESET, YELLOW
        cfg = self.cfg

        if cfg.provider in ("ollama", "meta"):
            print(f"  {DIM}Fetching models from {cfg.ollama_url}...{RESET}", end="", flush=True)
            ok, models = _get_models_cached(cfg.ollama_url)
            if ok and models:
                print(f"\r{BOLD}Available models on {cfg.ollama_url}:{RESET}")
                for m in models:
                    marker = f" {GREEN}<- active{RESET}" if m == cfg.ollama_model else ""
                    print(f"  * {m}{marker}")
            elif ok:
                print(f"\r  {YELLOW}Server reachable but no models found. Run: ollama pull <model>{RESET}")
            else:
                print(f"\r  {RED}Cannot reach {cfg.ollama_url}{RESET}")
            return

        models = _fetch_cloud_models(cfg)
        print(f"\n{BOLD}Available models ({cfg.provider}):{RESET}")
        for m in models:
            marker = f" {GREEN}<- active{RESET}" if m == cfg.ollama_model else ""
            print(f"  * {m}{marker}")
        print()

    def cmd_workspace(self, on_change=None) -> None:
        from pathlib import Path

        from cli.display import CYAN, GREEN, RESET
        cfg = self.cfg
        print(f"\nCurrent workspace: {CYAN}{cfg.working_folder}{RESET}")
        val = input("New workspace path (blank to keep): ").strip()
        if val:
            path = Path(val).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            cfg.working_folder = str(path)
            self.mgr.save(cfg)
            print(f"{GREEN}Workspace set to: {cfg.working_folder}{RESET}")
            if on_change:
                on_change(cfg.working_folder)

    def cmd_perms(self) -> None:
        from app.core.config import PermissionMode
        from cli.display import CYAN, GREEN, RESET, YELLOW
        cfg = self.cfg
        print(f"\nCurrent permission mode: {CYAN}{cfg.permission_mode.value}{RESET}")
        print("  ask    — prompt before each file write / command")
        print("  auto   — auto-approve everything")
        print("  deny   — deny all writes and commands")
        val = input("New mode [ask/auto/deny] (blank to keep): ").strip().lower()
        mapping = {
            "ask":  PermissionMode.ASK,
            "auto": PermissionMode.AUTO_APPROVE,
            "deny": PermissionMode.DENY_ALL,
        }
        if val in mapping:
            cfg.permission_mode = mapping[val]
            self.mgr.save(cfg)
            print(f"{GREEN}Permission mode set to: {cfg.permission_mode.value}{RESET}")
        elif val:
            print(f"{YELLOW}Unknown mode '{val}' — keeping current.{RESET}")

    def cmd_numctx(self, args: list[str]) -> None:
        from cli.display import GREEN, RESET, YELLOW
        cfg = self.cfg
        if args:
            try:
                cfg.num_ctx = int(args[0])
                self.mgr.save(cfg)
                print(f"{GREEN}Context window set to {cfg.num_ctx} tokens.{RESET}")
            except ValueError:
                print(f"{YELLOW}Invalid number: {args[0]}{RESET}")
        else:
            print(f"  Current num_ctx: {cfg.num_ctx}")
            print("  Usage: /numctx <N>  (e.g. /numctx 32768)")

    def cmd_provider(self, args: list[str]) -> None:
        from app.core import secret_store
        from cli.display import CYAN, DIM, GREEN, RESET, YELLOW
        cfg = self.cfg
        # provider name → (needs API key, suggested default model)
        providers = {
            "ollama":    (False, "codellama:7b",            "Local Ollama server"),
            "anthropic": (True,  "claude-sonnet-4-6",       "Anthropic Claude"),
            "openai":    (True,  "gpt-4o",                  "OpenAI ChatGPT"),
            "groq":      (True,  "llama-3.3-70b-versatile", "Groq (fast LLaMA/Mixtral)"),
            "gemini":    (True,  "gemini-1.5-flash-latest", "Google Gemini"),
            "meta":      (False, "llama3.2",                "Meta LLaMA via local Ollama"),
        }
        if not args:
            print(f"\nCurrent provider: {CYAN}{cfg.provider}{RESET}")
            print(f"\n  {'Provider':<12}  {'API Key?':<9}  {'Default Model':<30}  Description")
            print(f"  {'-'*12}  {'-'*9}  {'-'*30}  {'-'*25}")
            for name, (needs_key, default_model, desc) in providers.items():
                marker = " ◀" if name == cfg.provider else ""
                key_flag = "required" if needs_key else "no"
                print(f"  {CYAN}{name:<12}{RESET}  {key_flag:<9}  {default_model:<30}  {desc}{marker}")
            print("\n  Usage: /provider <name>  (e.g. /provider groq)")
            return

        p = args[0].lower()
        if p not in providers:
            print(f"{YELLOW}Unknown provider '{p}'. Available: {', '.join(providers)}{RESET}")
            return

        needs_key, default_model, _ = providers[p]
        if needs_key:
            existing_key = secret_store.get_api_key(p) or secret_store.get_api_key()
            if not existing_key:
                key = input(f"  Enter {p} API key (stored in OS keychain): ").strip()
                if key:
                    secret_store.set_api_key(key, p)
                    print(f"  {GREEN}API key for '{p}' saved to keychain.{RESET}")
                else:
                    print(f"  {YELLOW}No key entered — provider not switched.{RESET}")
                    return
            else:
                print(f"  {DIM}Using existing API key from keychain for '{p}'.{RESET}")

        if not cfg.ollama_model or cfg.ollama_model == "codellama:7b" and p != "ollama":
            # Suggest the default model for the new provider
            print(f"  {DIM}Tip: set model with /model (suggested: {default_model}){RESET}")

        cfg.provider = p
        self.mgr.save(cfg)
        print(f"{GREEN}Provider set to: {cfg.provider}{RESET}")

    # ── Generation parameter commands ─────────────────────────────────────────

    def cmd_temperature(self, args: list[str]) -> None:
        from cli.display import GREEN, RESET, YELLOW
        if not args:
            print(f"  Current temperature: {self.cfg.temperature}")
            print(f"  {YELLOW}Usage: /temperature <0.0-2.0>{RESET}")
            return
        try:
            val = float(args[0])
            if not 0.0 <= val <= 2.0:
                raise ValueError
        except ValueError:
            print(f"  {YELLOW}Temperature must be a float between 0.0 and 2.0{RESET}")
            return
        self.cfg.temperature = val
        self.mgr.save(self.cfg)
        print(f"  {GREEN}Temperature set to {val}{RESET}")

    def cmd_top_p(self, args: list[str]) -> None:
        from cli.display import GREEN, RESET, YELLOW
        if not args:
            print(f"  Current top_p: {self.cfg.top_p}")
            print(f"  {YELLOW}Usage: /top_p <0.0-1.0>{RESET}")
            return
        try:
            val = float(args[0])
            if not 0.0 <= val <= 1.0:
                raise ValueError
        except ValueError:
            print(f"  {YELLOW}top_p must be a float between 0.0 and 1.0{RESET}")
            return
        self.cfg.top_p = val
        self.mgr.save(self.cfg)
        print(f"  {GREEN}top_p set to {val}{RESET}")

    def cmd_max_tokens(self, args: list[str]) -> None:
        from cli.display import GREEN, RESET, YELLOW
        if not args:
            print(f"  Current max_tokens: {self.cfg.max_tokens}")
            print(f"  {YELLOW}Usage: /max_tokens <int, -1 for unlimited>{RESET}")
            return
        try:
            val = int(args[0])
            if val < -1:
                raise ValueError
        except ValueError:
            print(f"  {YELLOW}max_tokens must be an integer >= -1{RESET}")
            return
        self.cfg.max_tokens = val
        self.mgr.save(self.cfg)
        label = "unlimited" if val == -1 else str(val)
        print(f"  {GREEN}max_tokens set to {label}{RESET}")

    def cmd_params(self) -> None:
        from cli.display import BOLD, CYAN, RESET
        print(f"\n{BOLD}Generation Parameters:{RESET}")
        print(f"  {CYAN}provider   {RESET}  {self.cfg.provider}")
        print(f"  {CYAN}model      {RESET}  {self.cfg.ollama_model}")
        print(f"  {CYAN}temperature{RESET}  {self.cfg.temperature}")
        print(f"  {CYAN}top_p      {RESET}  {self.cfg.top_p}")
        print(f"  {CYAN}max_tokens {RESET}  {self.cfg.max_tokens}  (-1 = unlimited)")
        print(f"  {CYAN}num_ctx    {RESET}  {self.cfg.num_ctx}")
        print()

    # ── Tool use ──────────────────────────────────────────────────────────────

    def cmd_tools(self, args: list[str]) -> None:
        from app.core.tool_schema import BUILTIN_TOOL_DEFS
        from cli.display import BOLD, CYAN, GREEN, RESET, YELLOW
        if not args:
            status = "ON" if self.cfg.tool_use_enabled else "OFF"
            color = GREEN if self.cfg.tool_use_enabled else YELLOW
            print(f"\n  Tool use: {color}{status}{RESET}")
            print("  Usage: /tools on | /tools off | /tools list")
            return
        sub = args[0].lower()
        if sub == "on":
            self.cfg.tool_use_enabled = True
            self.mgr.save(self.cfg)
            print(f"  {GREEN}Tool use enabled. LLM can now call read_file, write_file, run_command, etc.{RESET}")
        elif sub == "off":
            self.cfg.tool_use_enabled = False
            self.mgr.save(self.cfg)
            print(f"  {YELLOW}Tool use disabled.{RESET}")
        elif sub == "list":
            print(f"\n  {BOLD}Available tools:{RESET}")
            for t in BUILTIN_TOOL_DEFS:
                print(f"  {CYAN}{t.name:<20}{RESET}  {t.description}")
        else:
            print(f"  {YELLOW}Unknown: /tools {sub}. Use: on | off | list{RESET}")

    # ── Session cost ─────────────────────────────────────────────────────────

    def cmd_cost(self) -> None:
        """Show cumulative session cost and token usage (per-provider breakdown)."""
        from app.core.cost_tracker import tracker
        from cli.display import BOLD, RESET
        print(f"\n{BOLD}Session cost:{RESET}")
        print(tracker.format_session_report())
        print()

    # ── Rich TUI ─────────────────────────────────────────────────────────────

    def cmd_rich(self, args: list[str]) -> None:
        """Handle /rich on|off|status|demo."""
        import cli.rich_display as _rd
        from cli.display import BOLD, CYAN, DIM, GREEN, RESET, YELLOW

        sub = args[0].lower() if args else "status"

        if sub == "on":
            _rd.set_rich_enabled(True)
            print(f"  {GREEN}Rich rendering enabled.{RESET}")

        elif sub == "off":
            _rd.set_rich_enabled(False)
            print(f"  {YELLOW}Rich rendering disabled — plain ANSI output active.{RESET}")

        elif sub == "status":
            installed = _rd.is_rich_available()
            enabled   = _rd.get_rich_enabled()
            inst_str  = f"{GREEN}installed{RESET}" if installed else f"{YELLOW}NOT installed{RESET}"
            enab_str  = f"{GREEN}enabled{RESET}"  if enabled  else f"{YELLOW}disabled{RESET}"
            print(f"\n{BOLD}Rich TUI status:{RESET}")
            print(f"  Package  : {inst_str}")
            print(f"  Rendering: {enab_str}")
            if not installed:
                print(f"  {DIM}Install with: pip install rich>=13.0{RESET}")
            print()

        elif sub == "demo":
            print(f"\n{BOLD}{CYAN}Rich TUI Demo{RESET}\n")

            # Markdown demo
            print(f"{DIM}--- Markdown ---{RESET}")
            _rd.print_markdown(
                "## Demo Heading\n\n"
                "This is **bold** and _italic_ text.\n\n"
                "- Bullet A\n- Bullet B\n"
            )

            # Code demo
            print(f"{DIM}--- Code (Python) ---{RESET}")
            _rd.print_code(
                "def greet(name: str) -> str:\n"
                "    return f'Hello, {name}!'\n",
                language="python",
            )

            # Table demo
            print(f"{DIM}--- Table ---{RESET}")
            _rd.print_table(
                ["Provider", "Model", "Cost/M tokens"],
                [
                    ["ollama",    "codellama:7b",    "FREE"],
                    ["anthropic", "claude-sonnet-4", "$3.00 / $15.00"],
                    ["openai",    "gpt-4o",          "$2.50 / $10.00"],
                ],
                title="Provider Comparison",
            )

            # Diff demo
            print(f"{DIM}--- Diff ---{RESET}")
            _rd.print_diff(
                "--- a/foo.py\n"
                "+++ b/foo.py\n"
                "@@ -1,3 +1,4 @@\n"
                " def main():\n"
                "-    pass\n"
                "+    print('hello')\n"
                "+    return 0\n"
            )

        else:
            print(f"  {YELLOW}Usage: /rich on | off | status | demo{RESET}")

    # ── Classified error log ──────────────────────────────────────────────────

    def cmd_errors(self, args: list[str]) -> None:
        """/errors [clear|stats] — display, clear, or summarise classified API errors."""
        from app.core import crash_db
        from cli.display import BOLD, CYAN, DIM, GREEN, RESET, YELLOW

        sub = args[0].lower() if args else "show"

        if sub == "clear":
            n = crash_db.clear_api_errors()
            print(f"  {GREEN}Cleared {n} API error record(s).{RESET}")
            return

        if sub == "stats":
            stats = crash_db.api_error_stats()
            if not stats:
                print(f"  {DIM}No API errors recorded yet.{RESET}")
                return
            print(f"\n{BOLD}API Error Counts by Class:{RESET}")
            for row in stats:
                cls   = row["error_class"]
                count = row["count"]
                last  = row["last"]
                print(f"  {CYAN}{cls:<20}{RESET}  {count:>4}x   last: {DIM}{last}{RESET}")
            print()
            return

        # Default: show recent errors grouped by class
        errors = crash_db.list_api_errors(limit=40)
        if not errors:
            print(f"  {DIM}No API errors recorded yet.{RESET}")
            return

        from collections import defaultdict
        grouped: dict[str, list[dict]] = defaultdict(list)
        for err in errors:
            grouped[err["error_class"]].append(err)

        print(f"\n{BOLD}Recent API Errors (newest first):{RESET}")
        for cls, items in grouped.items():
            print(f"\n  {YELLOW}{cls}{RESET}  ({len(items)} occurrence(s))")
            for item in items[:5]:
                ts  = item["ts"][:19].replace("T", " ")
                msg = item["message"][:100]
                sug = item["suggestion"][:80]
                ctx = item.get("context", "")
                print(f"    {DIM}{ts}{RESET}  {msg}")
                if sug:
                    print(f"      {DIM}Tip: {sug}{RESET}")
                if ctx:
                    print(f"      {DIM}Context: {ctx}{RESET}")
            if len(items) > 5:
                print(f"    {DIM}… and {len(items) - 5} more (use /errors stats){RESET}")
        print()
        print(f"  {DIM}Use '/errors clear' to wipe history, '/errors stats' for counts.{RESET}\n")

    # ── Provider latency health check ─────────────────────────────────────────

    def cmd_provider_health(self, args: list[str] | None = None) -> None:
        """/health — test the active provider with a minimal request and report latency."""
        import time as _time

        import httpx

        from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
        cfg = self.cfg
        provider = cfg.provider
        model = cfg.ollama_model or "(default)"
        print(f"\n{BOLD}Provider health check{RESET}  {CYAN}{provider}{RESET}  model: {model}")

        start = _time.monotonic()
        status = "OK"
        error_msg = ""
        try:
            if provider in ("ollama", "meta"):
                r = httpx.get(f"{cfg.ollama_url.rstrip('/')}/api/tags", timeout=5.0)
                r.raise_for_status()
            else:
                from codex.app.llm_client_ext import get_llm_client
                client = get_llm_client(cfg)
                client.chat([{"role": "user", "content": "Hello"}], system="")
        except Exception as exc:
            status = "FAIL"
            error_msg = str(exc)[:120]
        latency_ms = (_time.monotonic() - start) * 1000

        if status == "FAIL":
            colour = RED
        elif latency_ms < 500:
            colour = GREEN
        elif latency_ms < 2000:
            colour = YELLOW
        else:
            colour = RED

        print(
            f"  Status   : {colour}{status}{RESET}\n"
            f"  Latency  : {colour}{latency_ms:.0f} ms{RESET}"
        )
        if error_msg:
            print(f"  Error    : {DIM}{error_msg}{RESET}")
        print()

    # ── Health check ──────────────────────────────────────────────────────────

    def cmd_healthcheck(self) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, RESET, YELLOW
        print(f"\n{BOLD}ILX AI CLI Health Check{RESET}")
        results: list[tuple[str, bool, str]] = []

        # 1. Ollama connectivity
        ok, models = self.check_ollama()
        results.append(("Ollama connectivity", ok, f"{len(models)} models" if ok else "unreachable"))

        # 2. Model available
        if ok:
            model_ok = self.cfg.ollama_model in models
            results.append(("Active model listed", model_ok, self.cfg.ollama_model))
        else:
            results.append(("Active model listed", False, "skipped — Ollama offline"))

        # 3. Workspace exists
        import os
        wf = self.cfg.working_folder or ""
        ws_ok = bool(wf) and os.path.isdir(wf)
        results.append(("Workspace directory", ws_ok, wf or "(not set)"))

        # 4. crash_db writable
        try:
            from app.core import crash_db
            crash_db.list_crashes(1)
            db_ok = True
            db_msg = "writable"
        except Exception as exc:
            db_ok = False
            db_msg = str(exc)[:60]
        results.append(("Crash database", db_ok, db_msg))

        # 5. Config file readable
        try:
            self.mgr.load()
            cfg_ok = True
            cfg_msg = "readable"
        except Exception as exc:
            cfg_ok = False
            cfg_msg = str(exc)[:60]
        results.append(("Config file", cfg_ok, cfg_msg))

        for name, passed, detail in results:
            icon = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
            print(f"  [{icon}] {name:<28} {DIM}{detail}{RESET}")
        print()
        all_ok = all(r[1] for r in results)
        if all_ok:
            print(f"  {GREEN}All systems operational.{RESET}\n")
        else:
            fails = [r[0] for r in results if not r[1]]
            print(f"  {YELLOW}{len(fails)} check(s) failed: {', '.join(fails)}{RESET}\n")
