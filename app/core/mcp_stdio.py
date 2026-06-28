"""Real MCP (Model Context Protocol) stdio server connections.

Implements the Anthropic MCP spec over stdio transport:
  JSON-RPC 2.0 initialize → tools/list → tools/call

Usage:
    servers = StdioMCPManager.from_config()   # reads ~/.ilx_cli/mcp_servers.json
    tools   = servers.all_tools()             # list[dict] — LLM tool schemas
    result  = servers.call("github_search", {"query": "..."})
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

_log = logging.getLogger("ilx_cli.mcp_stdio")

_MCP_SERVERS_FILE = Path.home() / ".ilx_cli" / "mcp_servers.json"

# MCP protocol version we advertise
_PROTOCOL_VERSION = "2024-11-05"


class StdioMCPError(Exception):
    """Raised when an MCP server returns an error or the transport fails."""


class StdioMCPConnection:
    """A single live connection to an MCP server over stdio.

    Lifecycle:
        conn = StdioMCPConnection("github", ["npx", "-y", "@modelcontextprotocol/server-github"])
        tools = conn.list_tools()          # [{"name": ..., "description": ..., "inputSchema": ...}]
        result = conn.call_tool("search_repositories", {"query": "ilx"})
        conn.close()
    """

    def __init__(self, name: str, command: list[str]) -> None:
        self.name = name
        self._command = command
        self._proc: subprocess.Popen | None = None
        self._id = 0
        self._tools_cache: list[dict] | None = None
        self._connect()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        """Return tool schemas from this server (cached after first call)."""
        if self._tools_cache is not None:
            return self._tools_cache
        resp = self._rpc("tools/list", {})
        tools = resp.get("result", {}).get("tools", [])
        self._tools_cache = tools
        return tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Invoke a tool and return its text content."""
        resp = self._rpc("tools/call", {"name": tool_name, "arguments": arguments})
        result = resp.get("result", {})
        if "error" in resp:
            err = resp["error"]
            raise StdioMCPError(f"MCP error {err.get('code')}: {err.get('message')}")
        content = result.get("content", [])
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    parts.append(f"[image: {item.get('mimeType', 'unknown')}]")
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else json.dumps(result)

    def close(self) -> None:
        """Terminate the server process."""
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        import platform
        kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if platform.system() == "Windows":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = si
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["close_fds"] = True

        try:
            self._proc = subprocess.Popen(self._command, **kwargs)
        except FileNotFoundError as exc:
            raise StdioMCPError(
                f"Cannot start MCP server '{self.name}': {exc}. "
                "Is the server command installed? (e.g. npx, node)"
            ) from exc

        # Send initialize
        self._rpc_raw(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "ilx-ai-cli", "version": "0.3.0"},
            },
        )
        # Send initialized notification (no response expected)
        self._notify("notifications/initialized", {})

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _write(self, obj: dict) -> None:
        if not self._proc or not self._proc.stdin:
            raise StdioMCPError(f"MCP server '{self.name}' is not running")
        line = json.dumps(obj, ensure_ascii=False)
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except BrokenPipeError as exc:
            raise StdioMCPError(f"MCP server '{self.name}' pipe broken: {exc}") from exc

    def _read(self) -> dict:
        if not self._proc or not self._proc.stdout:
            raise StdioMCPError(f"MCP server '{self.name}' is not running")
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise StdioMCPError(f"MCP server '{self.name}' closed stdout unexpectedly")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                # Some servers emit non-JSON lines (startup banners) — skip them
                _log.debug("MCP server '%s' non-JSON line: %s", self.name, line[:120])

    def _rpc_raw(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and read exactly one response."""
        req_id = self._next_id()
        self._write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        resp = self._read()
        return resp

    def _rpc(self, method: str, params: dict) -> dict:
        """Send a request and return the response, logging errors."""
        resp = self._rpc_raw(method, params)
        if "error" in resp:
            err = resp["error"]
            _log.warning(
                "MCP server '%s' returned error for %s: %s",
                self.name, method, err
            )
        return resp

    def _notify(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        self._write({"jsonrpc": "2.0", "method": method, "params": params})


class StdioMCPManager:
    """Manages a collection of StdioMCPConnection instances.

    Reads ~/.ilx_cli/mcp_servers.json on construction:
        {
          "github":     {"command": ["npx", "-y", "@modelcontextprotocol/server-github"]},
          "filesystem": {"command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/workspace"]},
          "brave":      {"command": ["npx", "-y", "@modelcontextprotocol/server-brave-search"]}
        }
    """

    def __init__(self, server_specs: dict[str, dict]) -> None:
        self._specs = server_specs
        self._connections: dict[str, StdioMCPConnection] = {}

    @classmethod
    def from_config(cls, config_path: Path = _MCP_SERVERS_FILE) -> StdioMCPManager:
        """Load server specs from disk. Returns an empty manager if file absent."""
        if not config_path.exists():
            return cls({})
        try:
            specs = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(specs, dict):
                _log.warning("mcp_servers.json must be a JSON object, got %s", type(specs))
                return cls({})
            return cls(specs)
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("Cannot load mcp_servers.json: %s", exc)
            return cls({})

    def connect(self, server_name: str) -> StdioMCPConnection | None:
        """Connect to a named server (lazy, cached). Returns None on failure."""
        if server_name in self._connections and self._connections[server_name].alive:
            return self._connections[server_name]
        spec = self._specs.get(server_name)
        if spec is None:
            _log.warning("Unknown MCP server: %s", server_name)
            return None
        command = spec.get("command", [])
        if not command:
            _log.warning("MCP server '%s' has no command", server_name)
            return None
        try:
            conn = StdioMCPConnection(server_name, command)
            self._connections[server_name] = conn
            _log.info("Connected to MCP server '%s'", server_name)
            return conn
        except StdioMCPError as exc:
            _log.warning("Failed to connect to MCP server '%s': %s", server_name, exc)
            return None

    def connect_all(self) -> list[str]:
        """Connect to all configured servers. Returns list of connected names."""
        connected = []
        for name in self._specs:
            if self.connect(name):
                connected.append(name)
        return connected

    def all_tools(self) -> list[dict]:
        """Return tool schemas from all connected servers, prefixed with server name."""
        result = []
        for name, conn in self._connections.items():
            if not conn.alive:
                continue
            try:
                for tool in conn.list_tools():
                    # Prefix tool name to avoid collisions: "github__search_repositories"
                    prefixed = dict(tool)
                    prefixed["name"] = f"{name}__{tool['name']}"
                    prefixed["_mcp_server"] = name
                    prefixed["_mcp_tool"] = tool["name"]
                    result.append(prefixed)
            except StdioMCPError as exc:
                _log.warning("Cannot list tools from '%s': %s", name, exc)
        return result

    def call(self, prefixed_name: str, arguments: dict) -> str:
        """Dispatch a tool call. prefixed_name is 'servername__toolname'."""
        if "__" not in prefixed_name:
            raise StdioMCPError(
                f"Invalid MCP tool name '{prefixed_name}'. "
                "Expected format: 'servername__toolname'"
            )
        server_name, tool_name = prefixed_name.split("__", 1)
        conn = self.connect(server_name)
        if conn is None:
            raise StdioMCPError(f"MCP server '{server_name}' is unavailable")
        return conn.call_tool(tool_name, arguments)

    def server_names(self) -> list[str]:
        return list(self._specs.keys())

    def status(self) -> list[str]:
        """Human-readable status lines for /mcp servers."""
        if not self._specs:
            return [
                "  No MCP servers configured.",
                f"  Add servers to: {_MCP_SERVERS_FILE}",
                '  Format: {"github": {"command": ["npx", "-y", "@modelcontextprotocol/server-github"]}}',
            ]
        lines = [f"  {len(self._specs)} server(s) configured:"]
        for name, spec in self._specs.items():
            conn = self._connections.get(name)
            if conn and conn.alive:
                try:
                    tool_count = len(conn.list_tools())
                    lines.append(f"    {name}  [connected]  {tool_count} tool(s)")
                except StdioMCPError:
                    lines.append(f"    {name}  [connected — tools unavailable]")
            else:
                cmd = " ".join(spec.get("command", []))[:60]
                lines.append(f"    {name}  [not connected]  cmd: {cmd}")
        return lines

    def close_all(self) -> None:
        """Terminate all server processes."""
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()
