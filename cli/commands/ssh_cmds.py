"""SSH commands — /ssh connect, run, upload, download, close."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig
    from app.core.ssh_client import SSHClient

_log = logging.getLogger("ilx_cli.ssh_cmds")


class SSHCommands:
    """Handles all /ssh sub-commands."""

    def __init__(self, cfg: "AppConfig") -> None:
        self.cfg = cfg
        self._client: "SSHClient | None" = None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def cmd_ssh(self, args: list[str]) -> None:
        """Dispatch /ssh sub-commands.

        /ssh help                          — print SSH setup guide
        /ssh <user@host> [--key <path>] [--pass-file <path>] [--port N]
                                           — connect to remote machine
        /ssh run <command>                 — run command on connected host
        /ssh upload <local> <remote>       — upload a file
        /ssh download <remote> <local>     — download a file
        /ssh close                         — disconnect
        """
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET

        if not args:
            self._print_usage()
            return

        sub = args[0].lower()

        if sub == "help":
            from app.core.ssh_client import SSHClient
            SSHClient.print_setup_help()
            return

        if sub == "close":
            self._do_close()
            return

        if sub == "run":
            if len(args) < 2:
                print(f"  {YELLOW}Usage: /ssh run <command>{RESET}")
                return
            command = " ".join(args[1:])
            self._do_run(command)
            return

        if sub == "upload":
            if len(args) < 3:
                print(f"  {YELLOW}Usage: /ssh upload <local_path> <remote_path>{RESET}")
                return
            self._do_upload(args[1], args[2])
            return

        if sub == "download":
            if len(args) < 3:
                print(f"  {YELLOW}Usage: /ssh download <remote_path> <local_path>{RESET}")
                return
            self._do_download(args[1], args[2])
            return

        # Otherwise treat the first argument as user@host
        self._do_connect(args)

    # ------------------------------------------------------------------
    # Sub-command implementations
    # ------------------------------------------------------------------

    def _do_connect(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, RESET
        from app.core.ssh_client import SSHClient

        target = args[0]
        if "@" not in target:
            print(f"  {YELLOW}Expected user@host, got: {target}{RESET}")
            self._print_usage()
            return

        user, host = target.split("@", 1)
        port      = 22
        key_path  = None
        pass_file = None

        # Parse optional flags
        i = 1
        while i < len(args):
            flag = args[i].lower()
            if flag == "--port" and i + 1 < len(args):
                try:
                    port = int(args[i + 1])
                except ValueError:
                    print(f"  {YELLOW}Invalid port: {args[i+1]}{RESET}")
                    return
                i += 2
            elif flag == "--key" and i + 1 < len(args):
                key_path = args[i + 1]
                i += 2
            elif flag in ("--pass-file", "--passfile") and i + 1 < len(args):
                pass_file = args[i + 1]
                i += 2
            else:
                i += 1

        # Close existing session if open
        if self._client is not None:
            self._client.close()
            self._client = None

        print(f"  {DIM}Connecting to {user}@{host}:{port} ...{RESET}")
        client = SSHClient(host, user, port=port, key_path=key_path, pass_file=pass_file)
        result = client.connect()

        if result["ok"]:
            self._client = client
            print(f"  {GREEN}Connected to {user}@{host}:{port}{RESET}")
            print(f"  {DIM}Use /ssh run <command> to execute commands.{RESET}")
        else:
            print(f"  {RED}Connection failed:{RESET} {result['error']}")
            print(f"  {DIM}Run /ssh help for setup instructions.{RESET}")

    def _do_run(self, command: str) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, RESET

        if self._client is None:
            print(f"  {YELLOW}Not connected. Use /ssh user@host to connect first.{RESET}")
            return

        print(f"  {DIM}$ {command}{RESET}")
        result = self._client.run(command)

        if result["stdout"]:
            print(result["stdout"], end="" if result["stdout"].endswith("\n") else "\n")
        if result["stderr"]:
            print(f"  {RED}stderr:{RESET} {result['stderr']}", end="")
            if not result["stderr"].endswith("\n"):
                print()

        if not result["ok"]:
            exit_code = result.get("exit_code", -1)
            print(f"  {RED}Exit code {exit_code}{RESET}")

    def _do_upload(self, local_path: str, remote_path: str) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, RESET

        if self._client is None:
            print(f"  {YELLOW}Not connected. Use /ssh user@host to connect first.{RESET}")
            return

        print(f"  {DIM}Uploading {local_path} -> {remote_path} ...{RESET}")
        result = self._client.upload(local_path, remote_path)
        if result["ok"]:
            print(f"  {GREEN}Uploaded:{RESET} {remote_path}")
        else:
            print(f"  {RED}Upload failed:{RESET} {result['error']}")

    def _do_download(self, remote_path: str, local_path: str) -> None:
        from cli.display import DIM, GREEN, RED, YELLOW, RESET

        if self._client is None:
            print(f"  {YELLOW}Not connected. Use /ssh user@host to connect first.{RESET}")
            return

        print(f"  {DIM}Downloading {remote_path} -> {local_path} ...{RESET}")
        result = self._client.download(remote_path, local_path)
        if result["ok"]:
            print(f"  {GREEN}Downloaded:{RESET} {local_path}")
        else:
            print(f"  {RED}Download failed:{RESET} {result['error']}")

    def _do_close(self) -> None:
        from cli.display import DIM, GREEN, YELLOW, RESET

        if self._client is None:
            print(f"  {YELLOW}No active SSH connection.{RESET}")
            return
        host = self._client.host
        self._client.close()
        self._client = None
        print(f"  {GREEN}Disconnected from {host}.{RESET}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _print_usage(self) -> None:
        from cli.display import CYAN, YELLOW, RESET

        print(f"""
  {YELLOW}SSH Commands:{RESET}
    {CYAN}/ssh help{RESET}                          — show SSH setup guide
    {CYAN}/ssh <user@host>{RESET} [options]          — connect to remote machine
      Options:
        --port N            custom port (default 22)
        --key <path>        SSH private key file
        --pass-file <path>  file containing the password
    {CYAN}/ssh run <command>{RESET}                 — run command on connected host
    {CYAN}/ssh upload <local> <remote>{RESET}       — upload a file
    {CYAN}/ssh download <remote> <local>{RESET}     — download a file
    {CYAN}/ssh close{RESET}                         — disconnect
""")
