"""ILXApp — main interactive REPL orchestrator.

Readline setup, alias store, and input helpers live in cli/app_helpers.py to
keep this file under 700 lines.
"""
from __future__ import annotations

import logging
from pathlib import Path

from cli.app_helpers import AliasStore as _AliasStore
from cli.app_helpers import read_input as _read_input
from cli.app_helpers import setup_readline as _setup_readline
from cli.command_registry import CommandRegistry
from cli.display_compat import out_error, out_status

_log = logging.getLogger("ilx_cli.app")


class ILXApp:
    """Interactive CLI application — owns the REPL loop and command dispatch."""

    def __init__(self) -> None:
        from app.core.config import ConfigManager
        self._mgr = ConfigManager()
        self._cfg = self._mgr.load()

        from cli.rich_display import set_output_mode
        set_output_mode(getattr(self._cfg, "output_mode", "ansi"))

        from cli.context import ContextManager
        self._ctx = ContextManager(self._cfg)

        from cli.session import SessionManager
        self._sessions = SessionManager()

        from cli.chat_session import ChatSession
        self._chat = ChatSession(self._cfg, self._ctx)

        from cli.code_session import CodeSession
        self._code = CodeSession(self._cfg, self._ctx)

        from cli.commands.settings import SettingsCommands
        self._settings = SettingsCommands(self._cfg, self._mgr)

        from cli.commands.git_cmds import GitCommands
        self._git = GitCommands(self._cfg)

        from cli.commands.dev_tools import DevToolsCommands
        self._dev = DevToolsCommands(self._cfg)

        from cli.commands.dev_tools_metrics import MetricsCommands
        self._metrics = MetricsCommands(self._cfg)

        from cli.commands.dev_tools_analysis import AnalysisCommands
        self._analysis = AnalysisCommands(self._cfg)

        from cli.commands.workspace_cmds import WorkspaceCommands
        self._ws = WorkspaceCommands(self._cfg, self._ctx)

        from cli.commands.ssh_cmds import SSHCommands
        self._ssh = SSHCommands(self._cfg)
        from cli.commands.user_tools_cmds import UserToolsCommands
        self._user_tools = UserToolsCommands(self._cfg)
        from app.core.mcp_client import MCPClient
        self._mcp = MCPClient(cfg=self._cfg)
        from cli.commands.audit_cmds import AuditCommands
        self._audit = AuditCommands(self._cfg)
        from cli.commands.docker_cmds import DockerCommands
        self._docker = DockerCommands(self._cfg)

        # Shared stateful RAG index — kept in sync with /add and /drop
        from app.core.rag import RAG
        self._rag = RAG()

        from cli.commands.research_cmds import ResearchCommands
        self._research = ResearchCommands(self._rag)

        from cli.commands.route_cmds import RouteCommands
        self._route = RouteCommands(self._cfg)

        from cli.commands.bench_cmds import BenchCommands
        self._bench = BenchCommands(self._cfg)

        from cli.commands.trust_cmds import TrustCommands
        self._trust = TrustCommands(self._cfg)

        from cli.commands.setup_cmds import SetupCommands
        self._setup = SetupCommands(self._cfg)

        from cli.commands.perm_cmds import PermCommands
        self._perm = PermCommands(self._cfg)

        from cli.commands.sandbox_cmds import SandboxCommands
        self._sandbox = SandboxCommands(self._cfg)

        from cli.commands.allowlist_cmds import AllowlistCommands
        self._allowlist = AllowlistCommands(self._cfg)

        from cli.commands.review_cmds import ReviewCommands
        self._review = ReviewCommands(self._cfg)

        from cli.commands.fix_cmds import FixCommands
        self._fix = FixCommands(self._cfg)

        from cli.commands.index_cmds import IndexCommands
        self._index = IndexCommands(self._cfg)

        from cli.plan_session import PlanSession
        self._plan = PlanSession(self._cfg, self._ctx)

        # Restore prior task history from disk
        from app.core.supervisor import supervisor as _supervisor
        _supervisor.load_registry()

        # Alias store
        self._alias_store = _AliasStore()
        self._registry = CommandRegistry()
        self._register_commands()

        self._mode = "chat"

        # Set up readline history + tab completion (best-effort)
        _setup_readline(self._all_commands())

    def _all_commands(self) -> list[str]:
        return sorted(set(self._registry.all_commands()) | {
            "/chat", "/code", "/help", "/quit", "/exit", "/q",
            "/add", "/drop", "/paste", "/clear", "/undo", "/compact",
            "/history", "/resume", "/session", "/status", "/server",
            "/model", "/models", "/provider", "/numctx", "/temperature",
            "/top_p", "/max_tokens", "/params", "/cost", "/healthcheck", "/perms",
            "/workspace", "/rules", "/init", "/diag",
            "/run", "/test", "/lint", "/watch", "/ci", "/diff", "/profile",
            "/build", "/deps", "/stats", "/env", "/crashes", "/complexity",
            "/deadcode", "/bandit", "/precommit", "/format", "/kill", "/tasks",
            "/logs", "/scaffold", "/template", "/upgrade", "/readme", "/convert",
            "/fetch", "/tool", "/ssh", "/tools", "/mcp", "/metrics", "/attach",
            "/context", "/version", "/export", "/alias", "/copy",
            "/errors", "/free", "/setup", "/trust",
            "/plan", "/review", "/fix-tests", "/index", "/research",
            "/route", "/benchmark", "/audit", "/sandbox", "/permission",
            "/allow", "/deny", "/plugins", "/rollback", "/checkpoint", "/memory", "/symbol", "/rag", "/debug",  # noqa: E501
        })

    def _register_commands(self) -> None:
        """Populate the command registry for prefix-match dispatch."""
        r = self._registry
        r.register("/review",    lambda args: self._review.cmd_review(args) or False)
        r.register("/fix-tests", lambda args: self._fix.cmd_fix_tests(args) or False)
        r.register("/index",     lambda args: self._index.cmd_index(args) or False)
        r.register("/plan",      lambda args: self._plan.cmd_plan(args, self._chat.history) or False)
        r.register("/research",  lambda args: self._research.cmd_research(args) or False)
        r.register("/audit",     lambda args: self._audit.cmd_audit(args) or False)
        r.register("/docker",    lambda args: self._docker.cmd_docker(args) or False)
        r.register("/benchmark", lambda args: self._bench.cmd_benchmark(args) or False)
        r.register("/route",     lambda args: self._route.cmd_route(args) or False)
        r.register("/git",       lambda args: self._git.cmd_git(args) or False)
        r.register("/branch",    lambda args: self._git.cmd_branch(args) or False)
        r.register("/sandbox",   lambda args: self._sandbox.cmd_sandbox(args) or False)
        r.register("/permission", lambda args: self._perm.cmd_permission(args) or False)
        r.register("/allow",     lambda args: self._allowlist.cmd_allow(args) or False)
        r.register("/deny",      lambda args: self._allowlist.cmd_deny(args) or False)
        r.register("/allowlist", lambda args: self._allowlist.cmd_allowlist(args) or False)
        r.register("/plugins",    lambda a: __import__("cli.commands.plugin_cmds", fromlist=["cmd_plugins"]).cmd_plugins(a, self._cfg) or False)  # noqa: E501
        r.register("/trust",      lambda a: __import__("cli.commands.trust_dashboard", fromlist=["cmd_trust"]).cmd_trust(a, self._cfg) or False)  # noqa: E501
        r.register("/rollback",   lambda a: __import__("cli.commands.rollback_cmds", fromlist=["cmd_rollback"]).cmd_rollback(a, self._cfg) or False)  # noqa: E501
        r.register("/checkpoint", lambda a: __import__("cli.commands.rollback_cmds", fromlist=["cmd_checkpoint"]).cmd_checkpoint(a, self._cfg) or False)  # noqa: E501
        r.register("/memory",     lambda a: __import__("cli.commands.memory_cmds", fromlist=["MemoryCommands"]).MemoryCommands(self._cfg).cmd_memory(a) or False)  # noqa: E501
        r.register("/symbol",     lambda a: __import__("cli.commands.index_cmds", fromlist=["cmd_symbol"]).cmd_symbol(" ".join(a), self._cfg) or False)  # noqa: E501
        r.register("/rag",        lambda a: __import__("cli.commands.index_cmds", fromlist=["cmd_rag"]).cmd_rag(a, self._cfg) or False)  # noqa: E501
        r.register("/debug",      lambda a: __import__("cli.commands.debug_cmds", fromlist=["DebugCommands"]).DebugCommands(self._cfg).cmd_debug(a) or False)  # noqa: E501

    def _print_trust_summary(self) -> None:
        """Print a one-screen trust/config summary at startup (interactive only)."""
        import sys
        if not sys.stdin.isatty():
            return

        from cli.rich_display import _emit_json, get_output_mode  # noqa: WPS347

        cfg = self._cfg
        try:
            from app.core.route_engine import free_tier_label as _ftl
            provider_label = _ftl(cfg)
        except Exception:
            provider_str = getattr(cfg, "provider", "ollama")
            model_str = getattr(cfg, "ollama_model", "") or getattr(cfg, "chat_model", "")
            provider_label = f"{provider_str} / {model_str}" if model_str else provider_str

        workspace = getattr(cfg, "working_folder", "") or "~"
        perm_obj = getattr(cfg, "permission_mode", None)
        _perm_map = {"ask": "ask", "auto_approve": "auto-approve", "deny_all": "deny-all"}
        if perm_obj is not None:
            perm_val = perm_obj.value if hasattr(perm_obj, "value") else str(perm_obj)
            perm_label = _perm_map.get(perm_val, perm_val)
        else:
            perm_label = "ask"
        sandbox = getattr(cfg, "sandbox_mode", "workspace")
        network = getattr(cfg, "network_mode", "ask")
        tools = "enabled" if getattr(cfg, "tool_use_enabled", False) else "disabled"

        mode = get_output_mode()
        if mode == "quiet":
            return
        if mode == "json":
            _emit_json(
                type="trust_summary",
                provider=provider_label,
                workspace=workspace,
                permission=perm_label,
                sandbox=sandbox,
                network=network,
                tools=tools,
                audit="enabled",
            )
            return

        from cli.display import DIM, RESET
        print(f"{DIM}  Provider  : {provider_label}")
        print(f"  Workspace : {workspace}")
        print(f"  Permission: {perm_label}")
        print(f"  Sandbox   : {sandbox}")
        print(f"  Network   : {network}")
        print(f"  Tools     : {tools}")
        print(f"  Audit     : enabled{RESET}")

    def _print_startup(self) -> None:
        from app.core.spinner import Spinner
        from cli.display import DIM, GREEN, RED, RESET, YELLOW, print_banner
        print_banner()

        if self._cfg.provider == "ollama":
            with Spinner(f"Connecting to {self._cfg.ollama_url}"):
                ok, models = self._settings.check_ollama()
            if ok:
                print(f"{GREEN}Connected to Ollama{RESET}  {DIM}({self._cfg.ollama_url}){RESET}")
                if models and self._cfg.ollama_model not in models:
                    print(f"{YELLOW}Warning: model '{self._cfg.ollama_model}' not in server list.{RESET}")
                    print(f"{DIM}Available: {', '.join(models[:6])}{RESET}")
                    print(f"{DIM}Use /model to switch, or /models to list.{RESET}")
            else:
                print(f"{RED}Cannot reach Ollama at {self._cfg.ollama_url}{RESET}")
                print(f"{YELLOW}Use /server to set a different host, or start Ollama locally.{RESET}")
        else:
            print(f"{DIM}Provider: {self._cfg.provider}  Model: {self._cfg.ollama_model}{RESET}")

        # Warn if repeated crashes detected
        try:
            from app.core import crash_db
            groups = crash_db.group_summary()
            repeated = [g for g in groups if g.get("count", 0) >= 3]
            if repeated:
                print(f"{YELLOW}Warning: {len(repeated)} repeated crash signature(s) detected.{RESET}")
                for g in repeated[:3]:
                    print(f"  {DIM}x{g['count']}  {g['command'][:60]}{RESET}")
                print(f"{DIM}Run /crashes summary for details.{RESET}")
        except Exception as exc:
            _log.debug("crash_db unavailable at startup: %s", exc)

        # Show count of active user tools
        try:
            user_tool_count = len(self._user_tools._get_registry().list_tools())
            if user_tool_count > 0:
                from cli.display import CYAN
                print(f"  {DIM}User tools loaded: {CYAN}{user_tool_count}{RESET}")
        except Exception as exc:
            _log.debug("user tool count unavailable: %s", exc)

        wf = self._cfg.working_folder
        print(f"{DIM}Workspace: {wf}  |  Model: {self._cfg.ollama_model}{RESET}")
        print(f"{DIM}Type /help for commands, /tools on for AI tool use, /version for info.{RESET}\n")

        if wf and not Path(wf).exists():
            print(f"{YELLOW}Warning: workspace '{wf}' does not exist on disk.{RESET}")
            print(f"{DIM}Use /workspace to set a valid path.{RESET}")

        self._print_trust_summary()

    def run(self) -> None:
        self._print_startup()

        while True:
            try:
                prompt_str = (
                    "\033[36mYou:\033[0m " if self._mode == "chat"
                    else "\033[35mTask:\033[0m "
                )
                raw = _read_input(prompt_str)
            except KeyboardInterrupt:
                print("\n\033[2m(Ctrl+C — type /quit to exit)\033[0m")
                continue
            except EOFError:
                break

            if not raw:
                continue

            if raw.startswith("/"):
                if self._dispatch_command(raw):
                    break
                continue

            if self._mode == "chat":
                self._chat.send(raw)
            else:
                self._code.run_task(raw)

    def _dispatch_command(self, raw: str) -> bool:
        """Handle a slash command. Returns True if the app should exit."""
        from cli.display import DIM, GREEN, RESET, YELLOW, print_help

        # ── Alias expansion ──────────────────────────────────────────────────
        parts = raw.split()
        cmd   = parts[0].lower()
        args  = parts[1:]

        expanded_alias = self._alias_store.get(cmd.lstrip("/"))
        if expanded_alias:
            # Replace cmd+args with the expanded alias + any trailing args
            raw = expanded_alias + (" " + " ".join(args) if args else "")
            parts = raw.split()
            cmd   = parts[0].lower()
            args  = parts[1:]

        # Registry-based dispatch (supports prefix abbreviation)
        registry_handler = self._registry.lookup(cmd)
        if registry_handler is not None:
            return registry_handler(args) or False

        if cmd in ("/quit", "/exit", "/q"):
            saved = self._sessions.save(self._chat.history, self._cfg)
            if saved:
                out_status(f"{DIM}Session saved to {saved.name}{RESET}")
            out_status(f"{DIM}Goodbye.{RESET}")
            return True

        elif cmd == "/chat":
            self._mode = "chat"
            out_status(f"{DIM}Switched to chat mode.{RESET}")
        elif cmd == "/code":
            self._mode = "code"
            out_status(
                f"{DIM}Switched to code-agent mode.  Workspace: {self._cfg.working_folder}\n"
                f"Give it a task, e.g.: 'create a REST API' or 'add tests to main.py'\n"
                f"For questions, switch back with /chat.{RESET}"
            )

        elif cmd == "/help":
            if args and args[0].lower() in ("dev", "full", "all"):
                from cli.display import print_help_dev
                print_help_dev()
            else:
                print_help()

        elif cmd == "/add":
            rest = raw[len("/add"):].strip()
            before_count = len(self._chat.pinned)
            self._ws.cmd_add(rest, self._chat.pinned)
            # Sync newly added file into the RAG index
            if rest and len(self._chat.pinned) > before_count:
                new_entry = self._chat.pinned[-1]
                self._rag.add(rest, new_entry.get("content", ""))
        elif cmd == "/drop":
            self._ws.cmd_drop(args, self._chat.pinned)
            # Remove dropped file from RAG index
            if args:
                self._rag.remove(" ".join(args))
        elif cmd == "/paste":
            result = self._ws.cmd_paste()
            self._chat.pending_paste = result
        elif cmd == "/clear":
            self._chat.clear()
            print(f"{DIM}Conversation history and pinned context cleared.{RESET}")
        elif cmd == "/undo":
            removed = self._chat.undo()
            if removed:
                print(f"  {GREEN}Last exchange removed.{RESET}  ({len(self._chat.history)} messages remain)")
            else:
                print(f"  {YELLOW}Nothing to undo — history is empty.{RESET}")

        elif cmd == "/compact":
            self._cmd_compact()

        elif cmd == "/history":
            sessions = self._sessions.list(10)
            print(self._sessions.format_listing(sessions))
        elif cmd == "/resume":
            self._do_resume(args)
        elif cmd == "/session":
            self._cmd_session(args)
        elif cmd == "/status":
            self._settings.cmd_status()
        elif cmd == "/server":
            self._settings.cmd_server()
        elif cmd == "/model":
            self._settings.cmd_model()
        elif cmd == "/models":
            self._settings.cmd_models()
        elif cmd == "/provider":
            self._settings.cmd_provider(args)
        elif cmd == "/numctx":
            self._settings.cmd_numctx(args)
        elif cmd == "/temperature":
            self._settings.cmd_temperature(args)
        elif cmd == "/top_p":
            self._settings.cmd_top_p(args)
        elif cmd == "/max_tokens":
            self._settings.cmd_max_tokens(args)
        elif cmd == "/params":
            self._settings.cmd_params()
        elif cmd == "/cost":
            self._settings.cmd_cost()
        elif cmd == "/rich":
            self._settings.cmd_rich(args)
        elif cmd == "/no-color":
            from cli.rich_display import set_output_mode, set_rich_enabled
            set_rich_enabled(False)
            set_output_mode("ansi")
            print("Color output disabled.")
        elif cmd == "/healthcheck":
            self._settings.cmd_healthcheck()
        elif cmd == "/perms":
            self._settings.cmd_perms()
        elif cmd == "/permission":
            self._perm.cmd_permission(args)
        elif cmd == "/workspace":
            self._settings.cmd_workspace(on_change=self._ctx.set_workspace)
        elif cmd == "/rules":
            self._ws.cmd_rules(args)
        elif cmd == "/init":
            self._ws.cmd_init(args)
        elif cmd == "/diag":
            self._ws.cmd_diag()
        elif cmd == "/git":
            self._git.cmd_git(args)
        elif cmd == "/branch":
            self._git.cmd_branch(args)
        elif cmd == "/run":
            self._dev.cmd_run(args)
        elif cmd == "/test":
            self._dev.cmd_test(args)
        elif cmd == "/lint":
            self._dev.cmd_lint(args)
        elif cmd == "/watch":
            self._dev.cmd_watch(args)
        elif cmd == "/ci":
            self._dev.cmd_ci(args)
        elif cmd == "/diff":
            self._git.cmd_diff(args)
        elif cmd == "/profile":
            self._dev.cmd_profile(args)
        elif cmd == "/build":
            self._dev.cmd_build(args)
        elif cmd == "/deps":
            self._dev.cmd_deps(args)
        elif cmd == "/stats":
            self._dev.cmd_stats(args)
        elif cmd == "/env":
            self._dev.cmd_env()
        elif cmd == "/crashes":
            self._dev.cmd_crashes(args)
        elif cmd == "/complexity":
            self._analysis.cmd_complexity(args)
        elif cmd == "/deadcode":
            self._analysis.cmd_deadcode(args)
        elif cmd == "/bandit":
            self._analysis.cmd_bandit(args)
        elif cmd == "/precommit":
            self._analysis.cmd_precommit(args)
        elif cmd == "/audit":
            self._audit.cmd_audit(args)
        elif cmd == "/docker":
            self._docker.cmd_docker(args)
        elif cmd == "/route":
            self._route.cmd_route(args)
        elif cmd == "/benchmark":
            self._bench.cmd_benchmark(args)
        elif cmd == "/free":
            self._trust.cmd_free(args)
        elif cmd == "/setup":
            self._setup.cmd_setup(args)
        elif cmd == "/errors":
            self._settings.cmd_errors(args)
        elif cmd == "/sandbox":
            self._sandbox.cmd_sandbox(args)
        elif cmd == "/allow":
            self._allowlist.cmd_allow(args)
        elif cmd == "/deny":
            self._allowlist.cmd_deny(args)
        elif cmd == "/allowlist":
            self._allowlist.cmd_allowlist(args)
        elif cmd == "/review":
            self._review.cmd_review(args)
        elif cmd == "/fix-tests":
            self._fix.cmd_fix_tests(args)
        elif cmd == "/index":
            self._index.cmd_index(args)
        elif cmd == "/plan":
            self._plan.cmd_plan(args, self._chat.history)
        elif cmd == "/format":
            self._dev.cmd_format()
        elif cmd == "/kill":
            self._dev.cmd_kill(args)
        elif cmd == "/tasks":
            self._dev.cmd_tasks(args)
        elif cmd == "/logs":
            self._dev.cmd_logs(args)
        elif cmd == "/scaffold":
            self._ws.cmd_scaffold(args)
        elif cmd == "/template":
            self._cmd_template(args)
        elif cmd == "/upgrade":
            from cli.commands.workspace_upgrade import UpgradeCommand
            UpgradeCommand(self._cfg).cmd_upgrade(args)
        elif cmd == "/readme":
            self._ws.cmd_readme()
        elif cmd == "/convert":
            self._ws.cmd_convert(args)
        elif cmd == "/fetch":
            self._ws.cmd_fetch(args)
        elif cmd == "/research":
            self._research.cmd_research(args)
        elif cmd == "/tool":
            self._user_tools.cmd_tool(args, permission_callback=self._permission)
        elif cmd == "/ssh":
            self._ssh.cmd_ssh(args)
        elif cmd == "/tools":
            self._settings.cmd_tools(args)
        elif cmd == "/mcp":
            self._cmd_mcp(args)
        elif cmd == "/metrics":
            self._metrics.cmd_metrics()
        elif cmd == "/attach":
            self._dev.cmd_attach(args)
        elif cmd == "/context":
            self._cmd_context(args)
        elif cmd == "/version":
            self._cmd_version()
        elif cmd == "/export":
            self._cmd_export(args)
        elif cmd == "/alias":
            self._cmd_alias(args)

        elif cmd == "/copy":
            self._cmd_copy()

        elif self._user_tools.is_user_command(cmd.lstrip("/")):
            self._user_tools.run_user_command(
                cmd.lstrip("/"), args, permission_callback=self._permission
            )

        else:
            # Try alias expansion before giving up
            alias_target = self._alias_store.get(cmd.lstrip("/"))
            if alias_target is not None:
                self._dispatch_command(alias_target)
            else:
                out_error(f"{YELLOW}Unknown command '{cmd}'. Type /help for a list.{RESET}")

        return False

    # ── Command implementations (delegated to cli/commands/misc_cmds.py) ────────

    def _cmd_version(self) -> None:
        from cli.commands.misc_cmds import cmd_version
        cmd_version(self._cfg)

    def _cmd_export(self, args: list[str]) -> None:
        from cli.commands.misc_cmds import cmd_export
        cmd_export(self._cfg, self._chat.history, args)

    def _cmd_alias(self, args: list[str]) -> None:
        from cli.commands.misc_cmds import cmd_alias
        cmd_alias(self._alias_store, args)

    def _cmd_copy(self) -> None:
        from cli.commands.misc_cmds import cmd_copy
        cmd_copy(self._chat.history)

    def _cmd_mcp(self, args: list[str]) -> None:
        from cli.commands.mcp_cmds import cmd_mcp
        cmd_mcp(self._mcp, args)

    def _do_resume(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RESET
        sessions = self._sessions.list(10)
        if not sessions:
            print(f"  {DIM}No saved sessions found.{RESET}")
            return
        idx = 0
        if args:
            try:
                idx = int(args[0]) - 1
            except ValueError:
                idx = 0
        idx = max(0, min(idx, len(sessions) - 1))
        if self._chat.history:
            from app.core.permissions import confirm
            if not confirm(f"Replace {len(self._chat.history)} current message(s)?", self._cfg):
                print(f"  {DIM}Cancelled.{RESET}")
                return
        meta, msgs = self._sessions.load(sessions[idx])
        self._chat.history.clear()
        self._chat.history.extend(msgs)
        print(f"  {GREEN}Resumed {sessions[idx].name} ({len(msgs)} messages){RESET}")

    def _permission(self, kind: str, target: str, detail: str) -> bool:
        """Shared permission callback — prompts the user and returns bool."""
        from cli.display import RESET, YELLOW
        label = Path(target).name if target else kind
        try:
            ans = input(
                f"  {YELLOW}Allow '{label}'? [y/N]{RESET} "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        return ans in ("y", "yes")

    def _cmd_compact(self) -> None:
        from app.core.spinner import Spinner
        from cli.display import DIM, GREEN, RESET, YELLOW
        with Spinner("Summarizing conversation..."):
            summary, old_count, savings = self._chat.compact()
        if summary:
            print(f"  {GREEN}Compacted {old_count} messages → 1 summary. Context reduced by ~{savings}t{RESET}")
            print(f"\n  {DIM}Summary:{RESET}")
            for line in summary.splitlines():
                print(f"  {DIM}{line}{RESET}")
            print()
        else:
            print(f"  {YELLOW}Not enough history to compact (need 4+ messages).{RESET}")

    def _cmd_session(self, args: list[str]) -> None:
        from cli.display import GREEN, RESET, YELLOW
        sub = args[0].lower() if args else "list"
        if sub == "list":
            print(self._sessions.format_listing(self._sessions.list(10)))
        elif sub == "name" and len(args) >= 2:
            title = " ".join(args[1:])
            sessions = self._sessions.list(1)
            if sessions:
                self._sessions.set_title(sessions[0], title)
                print(f"  {GREEN}Session named: {title}{RESET}")
            else:
                print(f"  {YELLOW}No saved session to name. Save first with /quit.{RESET}")
        elif sub == "search" and len(args) >= 2:
            self._do_session_search(" ".join(args[1:]).lower())
        else:
            print(f"  {YELLOW}Usage: /session list | name <title> | search <query>{RESET}")

    def _cmd_template(self, args: list[str]) -> None:
        from cli.commands.workspace_scaffold import TemplateListCommand
        if not args or args[0].lower() == "list":
            TemplateListCommand().cmd_template_list()
        else:
            from cli.display import RESET, YELLOW
            print(f"{YELLOW}Usage: /template list{RESET}")

    def _cmd_context(self, args: list[str]) -> None:
        sub = args[0].lower() if args else "show"
        if sub in ("show", "stats") or not args:
            self._ctx.describe_current(self._chat.history, self._chat.pinned, rag=self._rag)
        elif sub == "clear":
            self._chat.clear()
            self._rag.clear()
            from cli.display import DIM, RESET
            print(f"  {DIM}Context cleared: history, pinned files, and RAG index reset.{RESET}")
        else:
            from cli.display import RESET, YELLOW
            print(f"  {YELLOW}Usage: /context [show|stats]  |  /context clear{RESET}")

    def _do_session_search(self, query: str) -> None:
        import json

        from cli.display import BOLD, CYAN, DIM, RESET, YELLOW
        sessions = self._sessions.list(50)
        hits: list[tuple] = []
        for path in sessions:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                meta = json.loads(lines[0]) if lines else {}
                for line in lines[1:]:
                    msg = json.loads(line)
                    content = msg.get("content", "")
                    if query in content.lower():
                        snippet = content[:120].replace("\n", " ")
                        hits.append((path.name, meta.get("title", ""), snippet))
                        break
            except Exception:
                continue
        if not hits:
            print(f"  {YELLOW}No sessions matched '{query}'.{RESET}")
            return
        print(f"\n{BOLD}Sessions matching '{query}':{RESET}")
        for fname, title, snippet in hits[:10]:
            label = f"{fname}  {CYAN}{title}{RESET}" if title else fname
            print(f"  {label}")
            print(f"    {DIM}{snippet}{RESET}")
        print()
