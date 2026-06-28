"""User tools CLI commands — create, list, run, update, remove user-defined tools."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.user_tools_cmds")


class UserToolsCommands:
    """Handles /tool ... and user tool (/<name>) dispatching."""

    def __init__(self, cfg: "AppConfig", llm_client=None) -> None:
        self.cfg = cfg
        self.llm = llm_client
        # Lazy imports — avoid circular deps and slow startup
        self._registry = None
        self._builder = None
        self._validator = None
        self._runner = None

    # ------------------------------------------------------------------
    # Lazy accessors
    # ------------------------------------------------------------------

    def _get_registry(self):
        if self._registry is None:
            from app.core.user_tools.registry import UserToolRegistry
            self._registry = UserToolRegistry()
        return self._registry

    def _get_builder(self):
        if self._builder is None:
            from app.core.user_tools.builder import ToolBuilder
            self._builder = ToolBuilder(self.cfg, self.llm)
        return self._builder

    def _get_validator(self):
        if self._validator is None:
            from app.core.user_tools.validator import ToolValidator
            self._validator = ToolValidator()
        return self._validator

    def _get_runner(self):
        if self._runner is None:
            from app.core.user_tools.runner import ToolRunner
            self._runner = ToolRunner()
        return self._runner

    # ------------------------------------------------------------------
    # /tool dispatcher
    # ------------------------------------------------------------------

    def cmd_tool(self, args: list[str], permission_callback=None) -> None:
        """
        /tool                         — same as /tool list
        /tool list                    — show all user tools
        /tool create <name> <desc>    — create a new tool (LLM generates code)
        /tool new <name> <desc>       — alias for create
        /tool run <name> [args...]    — run a user tool synchronously
        /tool remove <name>           — delete a user tool (asks confirmation)
        /tool enable <name>           — re-enable a disabled tool
        /tool disable <name>          — temporarily disable without deleting
        /tool info <name>             — show tool details, path, last run
        /tool validate <name>         — re-run validation checks on existing tool
        """
        sub = args[0].lower() if args else "list"

        if sub == "list":
            self._cmd_list()
        elif sub in ("create", "new"):
            self._cmd_create(args[1:], permission_callback)
        elif sub == "run":
            self._cmd_run(args[1:], permission_callback)
        elif sub == "remove":
            self._cmd_remove(args[1:])
        elif sub == "enable":
            self._cmd_set_enabled(args[1:], enabled=True)
        elif sub == "disable":
            self._cmd_set_enabled(args[1:], enabled=False)
        elif sub in ("info", "show"):
            self._cmd_info(args[1:])
        elif sub == "validate":
            self._cmd_validate(args[1:])
        elif sub == "find":
            self._cmd_find(args[1:])
        else:
            self._print_usage()

    # ------------------------------------------------------------------
    # Sub-command implementations
    # ------------------------------------------------------------------

    def _cmd_list(self) -> None:
        from cli.display import BOLD, DIM, GREEN, YELLOW, CYAN, RESET
        tools = self._get_registry().list_tools()
        print(f"\n{BOLD}User Tools:{RESET}")
        if not tools:
            print(
                f"  {DIM}No user tools yet. "
                f"Use /tool create <name> <description> to add one.{RESET}"
            )
        else:
            for t in tools:
                status = f"{GREEN}enabled{RESET}" if t.enabled else f"{YELLOW}disabled{RESET}"
                print(f"  {CYAN}/{t.name}{RESET}  {DIM}{t.description}{RESET}  [{status}]")
        print()

    def _cmd_create(self, args: list[str], permission_callback=None) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET
        from cli.display import highlight_code

        if len(args) < 2:
            print(
                f"  {YELLOW}Usage: /tool create <name> <description of what the tool does>{RESET}"
            )
            return

        name = args[0].lower().strip()
        desc = " ".join(args[1:])

        # Validate name
        registry = self._get_registry()
        valid, err_msg = registry.check_name(name)
        if not valid:
            print(f"  {RED}Invalid tool name:{RESET} {err_msg}")
            return

        # Ask whether to fetch research docs
        use_research = False
        try:
            research_ans = input(
                f"  {CYAN}Fetch research docs to improve code quality? [Y/n]: {RESET}"
            ).strip().lower()
            use_research = research_ans not in ("n", "no")
        except (EOFError, KeyboardInterrupt):
            use_research = True  # default yes

        # Generate code
        print(f"  {DIM}Generating code with LLM...{RESET}")
        builder = self._get_builder()
        code = builder.generate_code(name, desc, desc, use_research=use_research)

        # Show research summary if research was fetched
        if use_research and builder._last_research:
            self._print_research_summary(builder._last_research)

        # Show generated code
        print(f"\n{BOLD}Generated code for /{name}:{RESET}")
        print(highlight_code(code, "python"))

        # Ask user to confirm, cancel, or edit
        while True:
            try:
                ans = input(
                    f"  {CYAN}Save this tool as /{name}? [y/N/e(dit)] {RESET}"
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"

            if ans in ("e", "edit"):
                code = self._editor_loop(code)
                print(f"\n{BOLD}Edited code:{RESET}")
                print(highlight_code(code, "python"))
                continue
            break

        if ans not in ("y", "yes"):
            print(f"  {DIM}Cancelled.{RESET}")
            return

        # Write the file
        result = builder.create_tool(name, desc, code, permission_callback)
        if not result["ok"]:
            print(f"  {RED}Failed to write tool:{RESET} {result['error']}")
            return

        tool_path = result["path"]
        print(f"  {GREEN}Tool file written:{RESET} {tool_path}")

        # Validate
        self._run_validation_and_register(name, desc, tool_path)

    def _cmd_run(self, args: list[str], permission_callback=None) -> None:
        from cli.display import DIM, GREEN, YELLOW, CYAN, RESET

        if not args:
            print(f"  {YELLOW}Usage: /tool run <name> [args...]{RESET}")
            return

        name = args[0].lower()
        run_args = args[1:]
        registry = self._get_registry()
        tool = registry.get(name)

        if tool is None:
            print(f"  {YELLOW}Tool '/{name}' not found. Use /tool list to see available tools.{RESET}")
            return

        if not tool.enabled:
            print(f"  {YELLOW}Tool '/{name}' is disabled. Use /tool enable {name} to re-enable it.{RESET}")
            return

        # Ask permission
        try:
            ans = input(f"  {CYAN}Run user tool /{name}? [y/N] {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans not in ("y", "yes"):
            print(f"  {DIM}Cancelled.{RESET}")
            return

        # Run in background thread
        runner = self._get_runner()
        runner.run_async(
            tool.path,
            run_args,
            on_output=print,
            on_done=lambda r: print(
                f"  {GREEN}[done exit={r['exit_code']}]{RESET}"
                if r["ok"]
                else f"  {YELLOW}[done exit={r['exit_code']} error={r['error']}]{RESET}"
            ),
        )
        print(f"  {DIM}Running /{name} in background thread (safe — won't crash ILX){RESET}")

        # Update last_run timestamp
        import datetime
        registry.update_last_run(name, datetime.datetime.now().isoformat(timespec="seconds"))

    def _cmd_remove(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, CYAN, RESET

        if not args:
            print(f"  {YELLOW}Usage: /tool remove <name>{RESET}")
            return

        name = args[0].lower()
        registry = self._get_registry()
        tool = registry.get(name)

        if tool is None:
            print(f"  {YELLOW}Tool '/{name}' not found.{RESET}")
            return

        print(f"  Tool: {CYAN}/{name}{RESET}  {DIM}{tool.description}{RESET}")
        print(f"  Path: {DIM}{tool.path}{RESET}")

        try:
            ans = input(
                f"  {RED}Permanently delete /{name}? [y/N] {RESET}"
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"

        if ans not in ("y", "yes"):
            print(f"  {DIM}Cancelled.{RESET}")
            return

        # Delete source file
        tool_path = Path(tool.path)
        if tool_path.exists():
            try:
                tool_path.unlink()
            except OSError as exc:
                print(f"  {RED}Could not delete file:{RESET} {exc}")
                return

        registry.unregister(name)
        print(f"  {GREEN}Tool /{name} removed.{RESET}")

    def _cmd_set_enabled(self, args: list[str], *, enabled: bool) -> None:
        from cli.display import DIM, GREEN, YELLOW, RESET

        verb = "enable" if enabled else "disable"
        if not args:
            print(f"  {YELLOW}Usage: /tool {verb} <name>{RESET}")
            return

        name = args[0].lower()
        registry = self._get_registry()
        ok = registry.set_enabled(name, enabled)
        if ok:
            state = f"{GREEN}enabled{RESET}" if enabled else f"{YELLOW}disabled{RESET}"
            print(f"  Tool /{name} is now {state}.")
        else:
            print(f"  {YELLOW}Tool '/{name}' not found.{RESET}")

    def _cmd_info(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, YELLOW, CYAN, RESET

        if not args:
            print(f"  {YELLOW}Usage: /tool info <name>{RESET}")
            return

        name = args[0].lower()
        registry = self._get_registry()
        tool = registry.get(name)

        if tool is None:
            print(f"  {YELLOW}Tool '/{name}' not found.{RESET}")
            return

        status = f"{GREEN}enabled{RESET}" if tool.enabled else f"{YELLOW}disabled{RESET}"
        gen_attempts = getattr(tool, "generation_attempts", 1)

        print(f"\n{BOLD}Tool: /{tool.name}{RESET}")
        print(f"  Description         : {tool.description}")
        print(f"  Path                : {DIM}{tool.path}{RESET}")
        print(f"  Version             : {tool.version}")
        print(f"  Created             : {tool.created_at or DIM + '(unknown)' + RESET}")
        print(f"  Last run            : {tool.last_run or DIM + '(never)' + RESET}")
        print(f"  Status              : {status}")
        reflexion_note = (
            f"{DIM}(succeeded first try){RESET}"
            if gen_attempts == 1
            else f"{YELLOW}({gen_attempts} Reflexion attempts){RESET}"
        )
        print(f"  Generation attempts : {gen_attempts}  {reflexion_note}")

        # Preview first 20 lines
        tool_path = Path(tool.path)
        if tool_path.exists():
            lines = tool_path.read_text(encoding="utf-8", errors="replace").splitlines()
            preview = lines[:20]
            print(f"\n{BOLD}Source preview (first 20 lines):{RESET}")
            for i, line in enumerate(preview, 1):
                print(f"  {DIM}{i:3d}{RESET}  {CYAN}{line}{RESET}")
            if len(lines) > 20:
                print(f"  {DIM}... ({len(lines) - 20} more lines){RESET}")
        else:
            print(f"  {YELLOW}Warning: source file not found at path above.{RESET}")
        print()

    def _cmd_find(self, args: list[str]) -> None:
        """Search for tools by keyword: /tool find <query>."""
        from cli.display import BOLD, DIM, GREEN, YELLOW, CYAN, RESET

        if not args:
            print(f"  {YELLOW}Usage: /tool find <query>{RESET}")
            return

        query = " ".join(args)
        registry = self._get_registry()
        results = registry.search(query)

        print(f"\n{BOLD}Tools matching '{query}':{RESET}")
        if not results:
            print(f"  {DIM}No tools found for '{query}'.{RESET}")
        else:
            for t in results:
                status = f"{GREEN}enabled{RESET}" if t.enabled else f"{YELLOW}disabled{RESET}"
                print(f"  {CYAN}/{t.name}{RESET}  {DIM}{t.description}{RESET}  [{status}]")
        print()

    def _cmd_validate(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET

        if not args:
            print(f"  {YELLOW}Usage: /tool validate <name>{RESET}")
            return

        name = args[0].lower()
        registry = self._get_registry()
        tool = registry.get(name)

        if tool is None:
            print(f"  {YELLOW}Tool '/{name}' not found.{RESET}")
            return

        print(f"  {DIM}Validating /{name} ...{RESET}")
        self._print_validation(tool.path)

    # ------------------------------------------------------------------
    # User command dispatch (/<name> shortcuts)
    # ------------------------------------------------------------------

    def is_user_command(self, name: str) -> bool:
        """Return True when *name* is a registered, enabled user tool."""
        return self._get_registry().is_user_command(name)

    def run_user_command(
        self,
        name: str,
        args: list[str],
        permission_callback=None,
    ) -> None:
        """Invoke a registered user tool by name (called from app dispatch)."""
        from cli.display import DIM, GREEN, YELLOW, CYAN, RESET

        registry = self._get_registry()
        tool = registry.get(name)
        if tool is None:
            print(f"  {YELLOW}User tool '/{name}' not found in registry.{RESET}")
            return

        if not tool.enabled:
            print(f"  {YELLOW}Tool '/{name}' is disabled. Use /tool enable {name}.{RESET}")
            return

        # Explicit permission for every invocation
        try:
            ans = input(f"  {CYAN}Run user tool /{name}? [y/N] {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans not in ("y", "yes"):
            print(f"  {DIM}Cancelled.{RESET}")
            return

        runner = self._get_runner()
        runner.run_async(
            tool.path,
            args,
            on_output=print,
            on_done=lambda r: print(
                f"  {GREEN}[done exit={r['exit_code']}]{RESET}"
                if r["ok"]
                else f"  {YELLOW}[done exit={r['exit_code']} error={r['error']}]{RESET}"
            ),
        )
        print(f"  {DIM}Running /{name} in background thread (safe — won't crash ILX){RESET}")

        import datetime
        registry.update_last_run(name, datetime.datetime.now().isoformat(timespec="seconds"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _print_research_summary(self, research_context: str) -> None:
        """Print a brief summary of which research sources were consulted."""
        from cli.display import DIM, CYAN, RESET
        import re
        # Extract [Topic: X — Source: Y] lines from the context block
        pattern = re.compile(r"\[Topic:\s*(.+?)\s*—\s*Source:\s*(.+?)\]")
        matches = pattern.findall(research_context)
        if not matches:
            return
        print(f"  [research] Consulted {len(matches)} source(s):")
        for topic, source in matches:
            print(f"    {CYAN}•{RESET} {DIM}{source}{RESET} ({topic})")

    def _print_usage(self) -> None:
        from cli.display import CYAN, YELLOW, DIM, RESET
        print(
            f"  {YELLOW}Usage:{RESET}\n"
            f"    {CYAN}/tool list{RESET}                  — list all user tools\n"
            f"    {CYAN}/tool create <name> <desc>{RESET}  — create a new tool via LLM\n"
            f"    {CYAN}/tool run <name> [args]{RESET}     — run a tool in a background thread\n"
            f"    {CYAN}/tool remove <name>{RESET}         — permanently delete a tool\n"
            f"    {CYAN}/tool enable <name>{RESET}         — re-enable a disabled tool\n"
            f"    {CYAN}/tool disable <name>{RESET}        — temporarily disable a tool\n"
            f"    {CYAN}/tool info <name>{RESET}           — show tool details and source preview\n"
            f"    {CYAN}/tool show <name>{RESET}           — alias for info\n"
            f"    {CYAN}/tool validate <name>{RESET}       — re-run safety checks on a tool\n"
            f"    {CYAN}/tool find <query>{RESET}          — search tools by keyword\n"
            f"  {DIM}Registered tools can also be invoked as /<name> directly.{RESET}"
        )

    def _editor_loop(self, current_code: str) -> str:
        """Let the user paste corrected code interactively."""
        from cli.display import DIM, RESET
        print(
            f"  {DIM}Paste corrected code below. "
            f"Type ### on its own line when done:{RESET}"
        )
        lines: list[str] = []
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                break
            if line.strip() == "###":
                break
            lines.append(line)
        return "\n".join(lines) if lines else current_code

    def _run_validation_and_register(
        self,
        name: str,
        desc: str,
        tool_path: str,
    ) -> None:
        """Validate the tool file and register it if validation passes."""
        from cli.display import DIM, GREEN, RED, YELLOW, CYAN, RESET
        from app.core.user_tools.registry import UserTool
        import datetime

        validator = self._get_validator()
        print(f"  {DIM}Running validation checks...{RESET}")
        result = validator.validate(tool_path)
        self._print_validation_result(result)

        if result.ok:
            tool = UserTool(
                name=name,
                description=desc,
                path=tool_path,
                enabled=True,
                version=1,
                created_at=datetime.datetime.now().isoformat(timespec="seconds"),
                last_run="",
            )
            self._get_registry().register(tool)
            print(
                f"  {GREEN}Tool /{name} registered!{RESET}  "
                f"{DIM}Type /{name} to run it.{RESET}"
            )
        else:
            print(f"  {YELLOW}Validation issues detected (see above).{RESET}")
            try:
                ans = input(
                    f"  {CYAN}Register /{name} anyway? [y/N] {RESET}"
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"

            if ans in ("y", "yes"):
                tool = UserTool(
                    name=name,
                    description=desc,
                    path=tool_path,
                    enabled=True,
                    version=1,
                    created_at=datetime.datetime.now().isoformat(timespec="seconds"),
                    last_run="",
                )
                self._get_registry().register(tool)
                print(f"  {YELLOW}Tool /{name} registered (validation warnings present).{RESET}")
            else:
                print(f"  {DIM}Tool file kept on disk but not registered. "
                      f"Use /tool validate {name} after fixing issues.{RESET}")

    def _print_validation(self, tool_path: str) -> None:
        """Validate *tool_path* and print stage results."""
        validator = self._get_validator()
        result = validator.validate(tool_path)
        self._print_validation_result(result)

    def _print_validation_result(self, result) -> None:
        """Print stage-by-stage validation output."""
        from cli.display import DIM, GREEN, RED, YELLOW, RESET

        tick = f"{GREEN}✓{RESET}"
        cross = f"{RED}✗{RESET}"

        # The existing validator uses ok/syntax_ok/import_ok/smoke_ok attributes
        stages = [
            ("syntax",  result.syntax_ok),
            ("imports", result.import_ok),
            ("smoke",   result.smoke_ok),
        ]
        for stage_name, ok in stages:
            marker = tick if ok else cross
            print(f"    {marker} {stage_name}")

        for err in result.errors:
            print(f"    {RED}{err}{RESET}")
        for warn in result.warnings:
            print(f"    {YELLOW}Warning:{RESET} {warn}")

        if result.output:
            print(f"    {DIM}Output: {result.output[:200]}{RESET}")
