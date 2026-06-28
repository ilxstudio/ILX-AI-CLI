"""Memory commands — /memory for persistent project knowledge.

Subcommands:
  /memory show [query]     — list facts (optionally filtered)
  /memory add <key> <val>  — store a fact
  /memory forget <key>     — delete facts with this key
  /memory fixes [file]     — show past fix decisions
  /memory stats            — database statistics
  /memory search <query>   — search facts and symbols

Copyright 2026 ILX Studio — MIT License
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display import BOLD, CYAN, DIM, GREEN, RESET, YELLOW
from cli.display_compat import out

_log = logging.getLogger("ilx_cli.memory_cmds")

_USAGE = (
    f"  {CYAN}/memory show [query]{RESET}       — list stored facts\n"
    f"  {CYAN}/memory add <key> <value>{RESET}  — remember a fact\n"
    f"  {CYAN}/memory forget <key>{RESET}       — delete facts by key\n"
    f"  {CYAN}/memory fixes [file]{RESET}       — show past fix decisions\n"
    f"  {CYAN}/memory search <query>{RESET}     — search across all memory\n"
    f"  {CYAN}/memory stats{RESET}              — show database statistics"
)


class MemoryCommands:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def _mem(self):
        from app.core.project_memory import get_memory
        from app.core.audit import get_session_id
        return get_memory(self._cfg.working_folder or "", session_id=get_session_id())

    def cmd_memory(self, args: list[str]) -> None:
        sub = args[0].lower() if args else "show"
        rest = args[1:]
        dispatch = {
            "show":   self._show,
            "list":   self._show,
            "add":    self._add,
            "forget": self._forget,
            "delete": self._forget,
            "fixes":  self._fixes,
            "search": self._search,
            "stats":  self._stats,
        }
        fn = dispatch.get(sub, self._show)
        if sub in ("show", "list") and args:
            fn(args[1:])
        else:
            fn(rest)

    # ── subcommands ────────────────────────────────────────────────────────────

    def _show(self, args: list[str]) -> None:
        mem = self._mem()
        query = " ".join(args).strip()
        if query:
            facts = mem.search_facts(query, limit=20)
        else:
            facts = mem.all_facts(limit=30)
        if not facts:
            out(f"\n{DIM}No facts stored yet.  Use /memory add <key> <value> to remember something.{RESET}\n")
            return
        out(f"\n{BOLD}Project Memory{RESET}  ({len(facts)} fact(s){'  matching: ' + query if query else ''})\n")
        for f in facts:
            ts = f.ts[:10]
            out(f"  {DIM}{ts}{RESET}  {CYAN}{f.kind:<8}{RESET}  {GREEN}{f.key}{RESET}  {f.value[:100]}")
        out("")

    def _add(self, args: list[str]) -> None:
        if len(args) < 2:
            out(f"  {YELLOW}Usage: /memory add <key> <value>{RESET}")
            return
        key = args[0]
        value = " ".join(args[1:])
        self._mem().remember(key, value)
        out(f"  {GREEN}Remembered:{RESET} {key} = {value[:80]}")

    def _forget(self, args: list[str]) -> None:
        if not args:
            out(f"  {YELLOW}Usage: /memory forget <key>{RESET}")
            return
        key = args[0]
        n = self._mem().forget(key)
        if n:
            out(f"  {GREEN}Deleted {n} fact(s) for key '{key}'.{RESET}")
        else:
            out(f"  {DIM}No facts found for key '{key}'.{RESET}")

    def _fixes(self, args: list[str]) -> None:
        mem = self._mem()
        file_filter = args[0] if args else None
        fixes = mem.recent_fixes(file_path=file_filter, limit=15)
        if not fixes:
            msg = f"for '{file_filter}'" if file_filter else "yet"
            out(f"\n{DIM}No fix records {msg}.{RESET}\n")
            return
        header = f"Fix history{' for ' + file_filter if file_filter else ''}"
        out(f"\n{BOLD}{header}{RESET}  ({len(fixes)} record(s))\n")
        for fx in fixes:
            ts = fx.ts[:10]
            outcome_col = GREEN if fx.outcome == "success" else YELLOW
            out(f"  {DIM}{ts}{RESET}  {CYAN}{fx.file_path}{RESET}  [{outcome_col}{fx.outcome}{RESET}]")
            out(f"    Problem : {fx.problem[:90]}")
            out(f"    Solution: {fx.solution[:90]}")
        out("")

    def _search(self, args: list[str]) -> None:
        if not args:
            out(f"  {YELLOW}Usage: /memory search <query>{RESET}")
            return
        query = " ".join(args)
        mem = self._mem()
        facts = mem.search_facts(query, limit=10)
        symbols = mem.search_symbols(query, limit=10)
        if not facts and not symbols:
            out(f"\n{DIM}Nothing found for '{query}'.{RESET}\n")
            return
        if facts:
            out(f"\n{BOLD}Facts matching '{query}':{RESET}\n")
            for f in facts:
                out(f"  {CYAN}{f.key}{RESET}  {f.value[:100]}")
        if symbols:
            out(f"\n{BOLD}Symbols matching '{query}':{RESET}\n")
            for s in symbols:
                out(f"  {CYAN}{s.kind:<10}{RESET}  {GREEN}{s.name}{RESET}  {DIM}{s.file_path}{RESET}")
                if s.signature:
                    out(f"    {DIM}{s.signature[:100]}{RESET}")
        out("")

    def _stats(self, _args: list[str]) -> None:
        mem = self._mem()
        s = mem.stats()
        out(f"\n{BOLD}Project Memory Stats{RESET}\n")
        out(f"  {CYAN}Facts   {RESET}  {s['facts']}")
        out(f"  {CYAN}Fixes   {RESET}  {s['fixes']}")
        out(f"  {CYAN}Symbols {RESET}  {s['symbols']}")
        kb = s['db_bytes'] // 1024
        out(f"  {CYAN}DB size {RESET}  {kb} KB")
        out(f"  {DIM}{s['db_path']}{RESET}\n")
