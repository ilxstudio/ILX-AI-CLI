"""Setup commands -- /setup local: local model setup wizard."""
from __future__ import annotations

import logging
import platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from app.core import process_runner
from cli.display import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW
from cli.display_compat import out, out_error

_log = logging.getLogger("ilx_cli.setup_cmds")

# Model tiers by RAM
_MODEL_TIERS = [
    {"min_gb": 24, "coder": "qwen2.5-coder:14b", "chat": "qwen2.5:14b",   "embed": "nomic-embed-text"},
    {"min_gb": 12, "coder": "qwen2.5-coder:7b",  "chat": "qwen2.5:7b",    "embed": "nomic-embed-text"},
    {"min_gb":  6, "coder": "qwen2.5-coder:3b",  "chat": "qwen2.5:3b",    "embed": "nomic-embed-text"},
    {"min_gb":  0, "coder": "qwen2.5-coder:1.5b","chat": "tinyllama",      "embed": "nomic-embed-text"},
]

_OK  = "[ok]"
_ERR = "[x]"
_DOT = " . "
_CIR = " o "
_STAR = "*"


class SetupCommands:
    """/setup command handler."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def cmd_setup(self, args: list[str]) -> None:
        """/setup local | /setup status | /setup models"""
        sub = args[0].lower() if args else "help"
        dispatch = {
            "local":  self._setup_local,
            "status": self._setup_status,
            "models": self._setup_models,
            "help":   self._setup_help,
        }
        fn = dispatch.get(sub, self._setup_help)
        fn(args[1:] if len(args) > 1 else [])

    # ── subcommands ───────────────────────────────────────────────────────

    def _setup_local(self, _args: list[str]) -> None:
        """Interactive local model setup wizard."""
        out(f"\n{BOLD}ILX AI -- Local Model Setup Wizard{RESET}\n")

        # Step 1: Check Ollama
        out(f"  {BOLD}Step 1/4:{RESET} Detecting Ollama...")
        ollama_url = self._cfg.ollama_url
        ollama_ok, installed_models = self._check_ollama(ollama_url)
        if not ollama_ok:
            out(f"  {RED}{_ERR}{RESET} Ollama not running at {ollama_url}")
            out("\n  To install Ollama: https://ollama.com/download")
            out(f"  Then run: {CYAN}ollama serve{RESET}")
            out(f"  Then retry: {CYAN}/setup local{RESET}\n")
            return
        out(f"  {GREEN}{_OK}{RESET} Ollama running at {ollama_url}  ({len(installed_models)} model(s) installed)\n")

        # Step 2: Detect RAM
        out(f"  {BOLD}Step 2/4:{RESET} Detecting available RAM...")
        ram_gb = self._detect_ram_gb()
        out(f"  {GREEN}{_OK}{RESET} Available RAM: {ram_gb:.1f} GB\n")

        # Step 3: Recommend models
        out(f"  {BOLD}Step 3/4:{RESET} Model recommendations for {ram_gb:.0f} GB RAM:")
        tier = self._pick_tier(ram_gb)
        coder_model = tier["coder"]
        embed_model = tier["embed"]

        coder_installed = any(coder_model.split(":")[0] in m for m in installed_models)
        embed_installed = any(embed_model in m for m in installed_models)

        c_marker = f"{GREEN}{_OK}{RESET}" if coder_installed else f"{YELLOW}{_CIR}{RESET}"
        e_marker = f"{GREEN}{_OK}{RESET}" if embed_installed else f"{YELLOW}{_CIR}{RESET}"
        c_note = f"  {DIM}(already installed){RESET}" if coder_installed else ""
        e_note = f"  {DIM}(already installed){RESET}" if embed_installed else ""
        out(f"  {c_marker}  Coding model:    {CYAN}{coder_model}{RESET}{c_note}")
        out(f"  {e_marker}  Embedding model: {CYAN}{embed_model}{RESET}{e_note}")
        out("")

        # Step 4: Pull missing models
        from app.core.permissions import confirm
        to_pull = []
        if not coder_installed:
            to_pull.append(coder_model)
        if not embed_installed:
            to_pull.append(embed_model)

        if to_pull:
            out(f"  {BOLD}Step 4/4:{RESET} Pull missing models?")
            for m in to_pull:
                out(f"    {YELLOW}{_CIR}{RESET} {m}")
            out("")
            if confirm(f"  Pull {len(to_pull)} model(s) via ollama? [y/N] ", self._cfg):
                for model in to_pull:
                    self._pull_model(model)
            else:
                out(f"  {DIM}Skipped. Run 'ollama pull {to_pull[0]}' manually.{RESET}\n")
                return
        else:
            out(f"  {BOLD}Step 4/4:{RESET} {GREEN}All recommended models already installed.{RESET}\n")

        # Set as default
        out(f"  Setting {CYAN}{coder_model}{RESET} as default coding model...")
        self._cfg.ollama_model = coder_model
        self._cfg.provider = "ollama"
        try:
            from app.core.config import ConfigManager
            ConfigManager().save(self._cfg)
            out(f"  {GREEN}{_OK}{RESET} Config saved.\n")
        except Exception as exc:
            out_error(f"  {YELLOW}Warning: could not save config: {exc}{RESET}\n")

        # Quick smoke test
        out(f"  Running quick smoke test on {coder_model}...")
        self._smoke_test(coder_model)

    def _setup_status(self, _args: list[str]) -> None:
        """Show current Ollama status and installed models."""
        ollama_url = self._cfg.ollama_url
        ok, models = self._check_ollama(ollama_url)
        out(f"\n{BOLD}Ollama Status{RESET}")
        if ok:
            out(f"  {GREEN}{_OK}{RESET} Running at {ollama_url}")
            out(f"  {len(models)} model(s) installed:")
            for m in models[:20]:
                marker = GREEN + _OK + RESET if m == self._cfg.ollama_model else DIM + _DOT + RESET
                out(f"    {marker} {m}")
        else:
            out(f"  {RED}{_ERR}{RESET} Not running at {ollama_url}")
        out("")

    def _setup_models(self, _args: list[str]) -> None:
        """Show model recommendations for current RAM."""
        ram_gb = self._detect_ram_gb()
        out(f"\n{BOLD}Model Recommendations{RESET} (RAM: {ram_gb:.1f} GB)")
        for tier in _MODEL_TIERS:
            marker = GREEN + _STAR + RESET if tier == self._pick_tier(ram_gb) else DIM + " " + RESET
            out(f"  {marker} >={tier['min_gb']:>2}GB  coder:{CYAN}{tier['coder']:<28}{RESET} embed:{DIM}{tier['embed']}{RESET}")
        out("")

    def _setup_help(self, _args: list[str]) -> None:
        out(f"\n{BOLD}/setup{RESET} -- local model setup")
        out(f"  {CYAN}/setup local{RESET}    Interactive wizard: detect RAM, recommend + pull models")
        out(f"  {CYAN}/setup status{RESET}   Show Ollama status and installed models")
        out(f"  {CYAN}/setup models{RESET}   Show model recommendations for your RAM\n")

    # ── helpers ───────────────────────────────────────────────────────────

    def _check_ollama(self, url: str) -> tuple[bool, list[str]]:
        try:
            import httpx
            r = httpx.get(f"{url}/api/tags", timeout=3.0)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                return True, models
            return False, []
        except Exception:
            return False, []

    def _detect_ram_gb(self) -> float:
        try:
            import psutil
            return psutil.virtual_memory().total / (1024 ** 3)
        except ImportError:
            pass
        if platform.system() == "Windows":
            try:
                import ctypes
                class _MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength",                ctypes.c_ulong),
                        ("dwMemoryLoad",             ctypes.c_ulong),
                        ("ullTotalPhys",             ctypes.c_ulonglong),
                        ("ullAvailPhys",             ctypes.c_ulonglong),
                        ("ullTotalPageFile",         ctypes.c_ulonglong),
                        ("ullAvailPageFile",         ctypes.c_ulonglong),
                        ("ullTotalVirtual",          ctypes.c_ulonglong),
                        ("ullAvailVirtual",          ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                st = _MEMORYSTATUSEX()
                st.dwLength = ctypes.sizeof(st)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
                return st.ullTotalPhys / (1024 ** 3)
            except Exception:
                pass
        return 8.0  # conservative fallback

    def _pick_tier(self, ram_gb: float) -> dict:
        for tier in _MODEL_TIERS:
            if ram_gb >= tier["min_gb"]:
                return tier
        return _MODEL_TIERS[-1]

    def _pull_model(self, model: str) -> None:
        out(f"  Pulling {CYAN}{model}{RESET}...")
        r = process_runner.run(["ollama", "pull", model], timeout=600)
        if r.ok:
            out(f"  {GREEN}{_OK}{RESET} Pulled {model}")
        else:
            if "already" in r.stdout.lower() or "already" in r.stderr.lower():
                out(f"  {GREEN}{_OK}{RESET} {model} already up to date")
            else:
                out_error(f"  {YELLOW}Warning: ollama pull {model} returned non-zero. It may still have downloaded.{RESET}")
                if r.stderr:
                    out_error(f"    {DIM}{r.stderr[:200]}{RESET}")

    def _smoke_test(self, model: str) -> None:
        """Send a tiny prompt to verify the model responds."""
        try:
            import httpx
            payload = {
                "model": model,
                "prompt": "Reply with only the word: READY",
                "stream": False,
                "options": {"num_predict": 5, "temperature": 0},
            }
            r = httpx.post(
                f"{self._cfg.ollama_url}/api/generate",
                json=payload,
                timeout=30.0,
            )
            if r.status_code == 200:
                resp = r.json().get("response", "").strip()
                out(f"  {GREEN}{_OK}{RESET} Model responded: {DIM}{resp[:40]}{RESET}")
            else:
                out(f"  {YELLOW}[!]{RESET} Smoke test got HTTP {r.status_code}")
        except Exception as exc:
            out(f"  {YELLOW}[!]{RESET} Smoke test failed: {exc}")
        out(f"\n  {GREEN}Setup complete!{RESET} Try: {CYAN}/chat{RESET} to start coding.\n")
