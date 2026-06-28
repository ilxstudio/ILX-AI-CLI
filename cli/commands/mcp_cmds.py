"""MCP command handler — /mcp status|list|init|reload|call|servers."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.mcp_client import MCPClient


def cmd_mcp(mcp: "MCPClient", args: list[str]) -> None:
    """/mcp status|list|init|reload|call <tool> [json-args]|servers [connect|call]"""
    from cli.display import BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET

    sub = args[0].lower() if args else "status"

    if sub == "status":
        print(f"\n{BOLD}MCP Tool Status:{RESET}")
        for line in mcp.status_lines():
            print(line)
        print()

    elif sub == "list":
        tools = mcp.tools
        if not tools:
            print(f"  {DIM}No MCP tools registered. Use /mcp init to add built-in tools.{RESET}")
        else:
            print(f"\n{BOLD}Registered MCP tools:{RESET}")
            for t in tools:
                params = ", ".join(t.parameters.get("properties", {}).keys())
                print(f"  {CYAN}{t.name}{RESET}({params})  [{t.executor}]  {t.description}")
            print()

    elif sub == "init":
        mcp.register_builtin_tools()
        mcp.save_tools()
        print(f"{GREEN}Registered {len(mcp.tools)} built-in MCP tools and saved to disk.{RESET}")

    elif sub == "reload":
        n = mcp.reload()
        print(f"{GREEN}Reloaded MCP tools: {n} tool(s) registered.{RESET}")

    elif sub == "call" and len(args) >= 2:
        tool_name = args[1]
        raw_args: dict = {}
        if len(args) >= 3:
            try:
                import json
                raw_args = json.loads(" ".join(args[2:]))
            except Exception:
                print(
                    f"{YELLOW}Could not parse args as JSON. "
                    f'Pass args as: /mcp call <tool> {{"key": "val"}}{RESET}'
                )
                return

        def _perm(kind: str, target: str, detail: str) -> bool:
            try:
                ans = input(
                    f"  {YELLOW}Allow MCP tool call '{target}'? [y/N]{RESET} "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            return ans in ("y", "yes")

        result = mcp.call(tool_name, raw_args, permission_cb=_perm)
        if result["success"]:
            print(f"{GREEN}Result:{RESET}\n{result['result']}")
        else:
            print(f"{RED}Error:{RESET} {result['error']}")

    # ── Real MCP stdio server protocol ──────────────────────────────────────
    elif sub == "servers":
        _cmd_mcp_servers(args[1:])

    else:
        print(
            f"{YELLOW}Usage: /mcp status | list | init | reload | "
            f"call <tool> [json-args] | servers [connect|list|call]{RESET}"
        )


def _cmd_mcp_servers(args: list[str]) -> None:
    """/mcp servers — manage real MCP stdio server connections."""
    from cli.display import BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET
    from app.core.mcp_stdio import StdioMCPManager

    mgr = StdioMCPManager.from_config()
    sub = args[0].lower() if args else "status"

    if sub in ("status", "list", ""):
        print(f"\n{BOLD}MCP Stdio Servers:{RESET}")
        for line in mgr.status():
            print(line)
        print()

    elif sub == "connect":
        # Connect to all configured servers and report tool counts
        target = args[1] if len(args) >= 2 else None
        if target:
            conn = mgr.connect(target)
            if conn:
                tools = conn.list_tools()
                print(f"{GREEN}Connected to '{target}' — {len(tools)} tool(s) available:{RESET}")
                for t in tools[:20]:
                    print(f"  {CYAN}{t['name']}{RESET}  {t.get('description', '')[:60]}")
            else:
                print(f"{RED}Failed to connect to '{target}'. Check mcp_servers.json.{RESET}")
        else:
            connected = mgr.connect_all()
            if connected:
                print(f"{GREEN}Connected to {len(connected)} server(s): {', '.join(connected)}{RESET}")
                all_tools = mgr.all_tools()
                print(f"  {len(all_tools)} total tool(s) available across all servers.")
            else:
                print(f"{YELLOW}No servers connected. Add servers to ~/.ilx_cli/mcp_servers.json{RESET}")
                _print_mcp_servers_example()

    elif sub == "tools":
        mgr.connect_all()
        tools = mgr.all_tools()
        if not tools:
            print(f"  {DIM}No tools available. Run /mcp servers connect first.{RESET}")
        else:
            print(f"\n{BOLD}{len(tools)} MCP server tool(s):{RESET}")
            for t in tools:
                server = t.get("_mcp_server", "?")
                name = t.get("_mcp_tool", t["name"])
                desc = t.get("description", "")[:70]
                print(f"  {CYAN}{server}{RESET}/{name}  {DIM}{desc}{RESET}")
        print()

    elif sub == "call" and len(args) >= 3:
        # /mcp servers call servername__toolname {"arg": "val"}
        prefixed = args[1]
        import json
        try:
            call_args = json.loads(" ".join(args[2:]))
        except Exception:
            print(f"{YELLOW}Args must be valid JSON. Example: /mcp servers call github__search {{\"query\": \"test\"}}{RESET}")
            return
        mgr.connect_all()
        try:
            result = mgr.call(prefixed, call_args)
            print(f"{GREEN}Result:{RESET}\n{result}")
        except Exception as exc:
            print(f"{RED}Error:{RESET} {exc}")

    elif sub == "example":
        _print_mcp_servers_example()

    else:
        print(
            f"{YELLOW}Usage: /mcp servers [status|connect [name]|tools|"
            f"call <server__tool> {{args}}|example]{RESET}"
        )


def _print_mcp_servers_example() -> None:
    from cli.display import DIM, RESET
    from pathlib import Path
    config_path = Path.home() / ".ilx_cli" / "mcp_servers.json"
    print(f"\n{DIM}Add MCP servers to: {config_path}")
    print('Example mcp_servers.json:')
    print('{')
    print('  "github":     {"command": ["npx", "-y", "@modelcontextprotocol/server-github"]},')
    print('  "filesystem": {"command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/workspace"]},')
    print('  "brave":      {"command": ["npx", "-y", "@modelcontextprotocol/server-brave-search"]}')
    print(f'}}{RESET}')
    print()
