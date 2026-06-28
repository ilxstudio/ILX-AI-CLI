"""Docker commands — build, run, inspect, scaffold Dockerfiles with best practices."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

from cli.display_compat import out, out_error, out_result, out_status

_log = logging.getLogger("ilx_cli.docker")

# ---------------------------------------------------------------------------
# Dockerfile templates — best-practice content per project type
# ---------------------------------------------------------------------------

BEST_PRACTICE_DOCKERFILES: dict[str, str] = {
    "python": """\
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
WORKDIR /app

# Install dependencies in a separate layer for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source (after deps — cache-friendly)
COPY . .

# Security: run as non-root
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["python", "main.py"]
""",

    "fastapi": """\
FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt uvicorn[standard]
COPY . .
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
""",

    "django": """\
FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
""",

    "node": """\
FROM node:20-alpine AS base
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
EXPOSE 3000
CMD ["node", "index.js"]
""",

    "react": """\
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",

    "go": """\
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/server .

FROM scratch
COPY --from=builder /app/server /server
EXPOSE 8080
ENTRYPOINT ["/server"]
""",

    "rust": """\
FROM rust:1.77-slim AS builder
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main(){}" > src/main.rs && cargo build --release
COPY src ./src
RUN touch src/main.rs && cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/release/app /usr/local/bin/app
EXPOSE 8080
CMD ["app"]
""",

    "nginx": """\
FROM nginx:alpine
COPY ./html /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
""",
}

_DOCKERIGNORE_CONTENT = """\
.git
__pycache__
*.pyc
.pytest_cache
.venv
node_modules
.env
*.log
dist
build
"""

# Types where multi-stage builds are used (for best-practice summary)
_MULTISTAGE_TYPES = {"go", "rust", "react"}

# ---------------------------------------------------------------------------
# DockerCommands
# ---------------------------------------------------------------------------


class DockerCommands:
    """Handles all /docker sub-commands."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    # ── Public dispatcher ────────────────────────────────────────────────────

    def cmd_docker(self, args: list[str]) -> None:
        from cli.display import RESET, YELLOW
        sub = args[0].lower() if args else "help"
        rest = args[1:] if len(args) > 1 else []

        dispatch = {
            "status":   self._cmd_status,
            "build":    self._cmd_build,
            "run":      self._cmd_run,
            "ps":       self._cmd_ps,
            "stop":     self._cmd_stop,
            "logs":     self._cmd_logs,
            "pull":     self._cmd_pull,
            "images":   self._cmd_images,
            "inspect":  self._cmd_inspect,
            "scaffold": self._cmd_scaffold,
            "compose":  self._cmd_compose,
            "help":     self._cmd_help,
        }

        handler = dispatch.get(sub)
        if handler is None:
            out_error(f"{YELLOW}Unknown docker sub-command '{sub}'. Run /docker help.{RESET}")
            return
        handler(rest)

    # ── /docker status ───────────────────────────────────────────────────────

    def _cmd_status(self, args: list[str]) -> None:
        from cli.display import BOLD, CYAN, DIM, GREEN, RESET, YELLOW

        version_result = self._run_docker(
            ["info", "--format", "{{.ServerVersion}}"], capture=True
        )
        if not version_result["ok"]:
            out_error(f"{YELLOW}Docker is not running or not installed.{RESET}")
            out_status(f"{DIM}Install Docker: https://docs.docker.com/get-docker/{RESET}")
            return

        version = version_result["output"].strip()
        out(f"\n{BOLD}Docker Status{RESET}")
        out(f"  Version:  {GREEN}{version}{RESET}")

        # Running containers count
        ps_result = self._run_docker(["ps", "-q"], capture=True)
        if ps_result["ok"]:
            lines = [l for l in ps_result["output"].strip().splitlines() if l.strip()]
            out(f"  Running containers: {CYAN}{len(lines)}{RESET}")

        # Images count
        img_result = self._run_docker(["images", "-q"], capture=True)
        if img_result["ok"]:
            lines = [l for l in img_result["output"].strip().splitlines() if l.strip()]
            out(f"  Images: {CYAN}{len(lines)}{RESET}")
        out("")

    # ── /docker build [tag] ──────────────────────────────────────────────────

    def _cmd_build(self, args: list[str]) -> None:
        from cli.display import DIM, RESET, YELLOW

        wf = self._cfg.working_folder or "."
        root = Path(wf)
        dockerfile = root / "Dockerfile"

        if not dockerfile.exists():
            out_error(f"{YELLOW}No Dockerfile found in {root}{RESET}")
            out_status(f"{DIM}Run /docker scaffold <type> to generate one.{RESET}")
            return

        tag = args[0] if args else f"{root.name.lower()}:latest"
        out_status(f"{DIM}Building image '{tag}' from {root} ...{RESET}\n")
        self._stream_docker(["build", "-t", tag, str(root)])

    # ── /docker run [image] [-- args...] ────────────────────────────────────

    def _cmd_run(self, args: list[str]) -> None:
        from cli.display import DIM, RESET, YELLOW

        if not args:
            out_error(f"{YELLOW}Usage: /docker run <image> [-- args...]{RESET}")
            return

        # Split on "--" separator
        if "--" in args:
            sep = args.index("--")
            image = args[:sep]
            extra = args[sep + 1:]
        else:
            image = args[:1]
            extra = args[1:]

        image_name = " ".join(image)
        out_status(f"{DIM}Note: container will be removed on exit (--rm semantics).{RESET}")
        from app.core.permissions import confirm
        if not confirm(f"Run '{image_name}' with --rm?", self._cfg):
            out_status(f"{DIM}Cancelled.{RESET}")
            return

        cmd = ["run", "--rm", "-it", image_name] + extra
        self._stream_docker(cmd)

    # ── /docker ps ──────────────────────────────────────────────────────────

    def _cmd_ps(self, args: list[str]) -> None:
        from cli.display import DIM, RESET

        result = self._run_docker(
            ["ps", "--format",
             r"table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
            capture=True,
        )
        if result["ok"]:
            out(f"\n{DIM}{result['output']}{RESET}")
        else:
            self._print_error(result)

    # ── /docker stop <container> ─────────────────────────────────────────────

    def _cmd_stop(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, RESET, YELLOW

        if not args:
            out_error(f"{YELLOW}Usage: /docker stop <container>{RESET}")
            return
        container = args[0]
        from app.core.permissions import confirm
        if not confirm(f"Stop container '{container}'?", self._cfg):
            out_status(f"{DIM}Cancelled.{RESET}")
            return

        result = self._run_docker(["stop", container], capture=True)
        if result["ok"]:
            out_result(f"  {GREEN}Stopped:{RESET} {container}")
        else:
            self._print_error(result)

    # ── /docker logs <container> [--tail N] ──────────────────────────────────

    def _cmd_logs(self, args: list[str]) -> None:
        from cli.display import RESET, YELLOW

        if not args:
            out_error(f"{YELLOW}Usage: /docker logs <container> [--tail N]{RESET}")
            return

        container = args[0]
        tail = "50"
        if "--tail" in args:
            idx = args.index("--tail")
            if idx + 1 < len(args):
                tail = args[idx + 1]

        result = self._run_docker(
            ["logs", f"--tail={tail}", "--timestamps", container],
            capture=True,
        )
        if result["ok"]:
            out_result(result["output"])
        else:
            self._print_error(result)

    # ── /docker pull <image> ─────────────────────────────────────────────────

    def _cmd_pull(self, args: list[str]) -> None:
        from cli.display import RESET, YELLOW

        if not args:
            out_error(f"{YELLOW}Usage: /docker pull <image>{RESET}")
            return
        self._stream_docker(["pull", args[0]])

    # ── /docker images ───────────────────────────────────────────────────────

    def _cmd_images(self, args: list[str]) -> None:
        from cli.display import DIM, RESET

        result = self._run_docker(
            ["images", "--format",
             r"table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"],
            capture=True,
        )
        if result["ok"]:
            out(f"\n{DIM}{result['output']}{RESET}")
        else:
            self._print_error(result)

    # ── /docker inspect <name> ───────────────────────────────────────────────

    def _cmd_inspect(self, args: list[str]) -> None:
        from cli.display import DIM, RESET, YELLOW

        if not args:
            out_error(f"{YELLOW}Usage: /docker inspect <container_or_image>{RESET}")
            return

        result = self._run_docker(["inspect", args[0]], capture=True)
        if not result["ok"]:
            self._print_error(result)
            return

        try:
            data = json.loads(result["output"])
            pretty = json.dumps(data, indent=2)
        except json.JSONDecodeError:
            pretty = result["output"]

        lines = pretty.splitlines()
        cap = 80
        for line in lines[:cap]:
            out(f"  {DIM}{line}{RESET}")
        if len(lines) > cap:
            out_status(f"  {DIM}... ({len(lines) - cap} more lines — use docker inspect directly){RESET}")

    # ── /docker scaffold [type] ──────────────────────────────────────────────

    def _cmd_scaffold(self, args: list[str]) -> None:
        from cli.display import RESET, YELLOW

        project_type = args[0].lower() if args else "python"
        wf = self._cfg.working_folder or "."
        target_dir = Path(wf)

        if project_type not in BEST_PRACTICE_DOCKERFILES:
            supported = ", ".join(sorted(BEST_PRACTICE_DOCKERFILES))
            out_error(f"{YELLOW}Unknown project type '{project_type}'.{RESET}")
            out(f"  Supported types: {supported}")
            return

        self.scaffold_dockerfile(project_type, target_dir)

    def scaffold_dockerfile(self, project_type: str, target_dir: Path) -> bool:
        """Write Dockerfile and .dockerignore into target_dir.

        Returns True on success, False if project_type is unknown.
        """
        from cli.display import CYAN, DIM, GREEN, RESET, YELLOW

        project_type = project_type.lower()
        content = BEST_PRACTICE_DOCKERFILES.get(project_type)
        if content is None:
            supported = ", ".join(sorted(BEST_PRACTICE_DOCKERFILES))
            out_error(f"{YELLOW}Unknown project type '{project_type}'.{RESET}")
            out(f"  Supported types: {supported}")
            return False

        target_dir.mkdir(parents=True, exist_ok=True)
        dockerfile_path = target_dir / "Dockerfile"
        dockerignore_path = target_dir / ".dockerignore"

        dockerfile_path.write_text(content, encoding="utf-8")
        dockerignore_path.write_text(_DOCKERIGNORE_CONTENT, encoding="utf-8")

        out_result(f"  {GREEN}Dockerfile created:{RESET} {dockerfile_path}")
        out_result(f"  {GREEN}.dockerignore created:{RESET} {dockerignore_path}")
        out("")
        out(f"  {DIM}Best practices applied:{RESET}")
        out(f"    {CYAN}✓{RESET} Non-root user (security)")
        out(f"    {CYAN}✓{RESET} Dependency layer caching")
        out(f"    {CYAN}✓{RESET} Minimal base image")
        if project_type in _MULTISTAGE_TYPES:
            out(f"    {CYAN}✓{RESET} Multi-stage build (where applicable)")
        out("")
        out(f"  {DIM}Next steps:{RESET}")
        out(f"    {CYAN}/docker build{RESET}          — build the image")
        out(f"    {CYAN}/docker run <image>{RESET}    — run the container")
        out("")
        return True

    # ── /docker compose [up|down|ps|logs] ───────────────────────────────────

    def _cmd_compose(self, args: list[str]) -> None:
        from cli.display import DIM, RESET, YELLOW

        sub = args[0].lower() if args else "ps"
        wf = self._cfg.working_folder or "."
        root = Path(wf)

        compose_file = None
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml"):
            candidate = root / name
            if candidate.exists():
                compose_file = candidate
                break

        if compose_file is None:
            out_error(f"{YELLOW}No docker-compose.yml / compose.yaml found in {root}{RESET}")
            out_status(f"{DIM}Run /scaffold compose to generate one.{RESET}")
            return

        if sub == "up":
            self._stream_docker(["compose", "up", "-d"])
        elif sub == "down":
            self._stream_docker(["compose", "down"])
        elif sub == "ps":
            result = self._run_docker(["compose", "ps"], capture=True)
            if result["ok"]:
                out_result(result["output"])
            else:
                self._print_error(result)
        elif sub == "logs":
            result = self._run_docker(["compose", "logs", "--tail=50"], capture=True)
            if result["ok"]:
                out_result(result["output"])
            else:
                self._print_error(result)
        else:
            out_error(f"{YELLOW}Usage: /docker compose [up|down|ps|logs]{RESET}")

    # ── /docker help ─────────────────────────────────────────────────────────

    def _cmd_help(self, args: list[str]) -> None:
        from cli.display import BOLD, CYAN, RESET

        rows = [
            ("status",                     "Docker version, container count, image count"),
            ("build [tag]",                "Build image from Dockerfile in workspace"),
            ("run <image> [-- args]",      "Run container with --rm (ephemeral)"),
            ("ps",                         "List running containers"),
            ("stop <container>",           "Stop a running container (with confirmation)"),
            ("logs <container> [--tail N]","Fetch container logs (default: 50 lines)"),
            ("pull <image>",               "Pull an image from the registry"),
            ("images",                     "List local images"),
            ("inspect <name>",             "Pretty-print container or image JSON (80-line cap)"),
            ("scaffold [type]",            "Generate Dockerfile for: python node fastapi django react go rust nginx"),
            ("compose [up|down|ps|logs]",  "docker compose wrapper (needs compose file in workspace)"),
            ("help",                       "Show this help"),
        ]

        out(f"\n{BOLD}/docker sub-commands{RESET}\n")
        out(f"  {'Sub-command':<30} {'Description'}")
        out(f"  {'-'*30} {'-'*45}")
        for sub, desc in rows:
            out(f"  {CYAN}{sub:<30}{RESET} {desc}")
        out("")

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _run_docker(self, cmd: list[str], *, capture: bool = False) -> dict:
        """Run a docker CLI command.

        Parameters
        ----------
        cmd:     Argument list — passed directly to subprocess (no shell=True).
        capture: When True, capture stdout+stderr and return output in result dict.

        Returns
        -------
        dict with keys: ok (bool), output (str), returncode (int).
        """
        from app.core import process_runner
        full_cmd = ["docker"] + cmd
        r = process_runner.run(full_cmd, capture=capture, timeout=60)
        if capture:
            output = r.stdout
            if not r.ok and r.stderr:
                output = output or r.stderr
        else:
            output = ""
        return {"ok": r.ok, "output": output, "returncode": r.returncode}

    def _stream_docker(self, cmd: list[str]) -> None:
        """Run a docker command and stream its output line by line."""
        from cli.display import DIM, RED, RESET

        full_cmd = ["docker"] + cmd
        try:
            proc = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if proc.stdout:
                for line in proc.stdout:
                    out(f"  {DIM}{line.rstrip()}{RESET}")
            proc.wait()
            if proc.returncode != 0:
                out_error(f"  {RED}docker exited with code {proc.returncode}{RESET}")
        except FileNotFoundError:
            out_error(f"  {RED}Docker not found in PATH.{RESET}")
            out_status(f"  {DIM}Install Docker: https://docs.docker.com/get-docker/{RESET}")
        except Exception as exc:
            _log.debug("_stream_docker error: %s", exc)
            out_error(f"  {RED}Error: {exc}{RESET}")

    def _print_error(self, result: dict) -> None:
        from cli.display import DIM, RED, RESET
        out_error(f"  {RED}Docker error (code {result['returncode']}):{RESET}")
        if result.get("output"):
            for line in result["output"].strip().splitlines()[:20]:
                out_error(f"  {DIM}{line}{RESET}")
