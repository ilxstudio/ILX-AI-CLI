"""Workspace commands — /add, /drop, /paste, /rules, /init, /scaffold, /diag.

Media/web commands (/readme, /convert, /fetch, /tool) are implemented in the
``WorkspaceMediaMixin`` (workspace_media_cmds.py) and mixed in here to keep
this file under the 700-line limit.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig
    from cli.context import ContextManager

_log = logging.getLogger("ilx_cli.workspace")

# Merge extra templates from the scaffold extension module
from cli.commands.workspace_scaffold import EXTRA_INIT_TEMPLATES as _EXTRA
from cli.commands.workspace_media_cmds import WorkspaceMediaMixin

_INIT_TEMPLATES: dict[str, dict[str, str]] = {
    **_EXTRA,
    "python": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        ".gitignore":    "__pycache__/\n*.pyc\n.venv/\nvenv/\ndist/\nbuild/\n*.egg-info/\n.env\n",
        "pyproject.toml": '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "myproject"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
        "src/__init__.py":   "",
        "tests/__init__.py": "",
        "tests/test_smoke.py": 'import importlib\n\ndef test_import():\n    assert importlib.import_module("src")\n',
        "README.md": (
            "# My Project\n\n"
            "![Python](https://img.shields.io/badge/python-3.11+-blue)\n\n"
            "## Overview\n\nA Python project.\n\n"
            "## Setup\n\n```bash\npip install -e .\n```\n\n"
            "## Usage\n\n```python\nimport src\n```\n\n"
            "## Testing\n\n```bash\npytest\n```\n"
        ),
    },
    "node": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        ".gitignore":    "node_modules/\ndist/\n.env\n.cache/\n",
        "package.json":  '{\n  "name": "myproject",\n  "version": "1.0.0",\n  "main": "src/index.js",\n  "scripts": {\n    "start": "node src/index.js",\n    "test": "node --test"\n  }\n}\n',
        "src/index.js":  "// Entry point\nconsole.log('Hello, world!');\n",
        "README.md":     "# My Project\n\nA Node.js project.\n\n## Setup\n\n```bash\nnpm install\n```\n\n## Run\n\n```bash\nnpm start\n```\n",
    },
    "react": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        ".gitignore":    "node_modules/\ndist/\n.env\n.cache/\n",
        "package.json": (
            '{\n  "name": "myapp",\n  "version": "0.1.0",\n  "private": true,\n'
            '  "scripts": {\n    "dev": "vite",\n    "build": "vite build",\n    "preview": "vite preview"\n  },\n'
            '  "dependencies": {\n    "react": "^18.2.0",\n    "react-dom": "^18.2.0"\n  },\n'
            '  "devDependencies": {\n    "vite": "^5.0.0",\n    "@vitejs/plugin-react": "^4.0.0"\n  }\n}\n'
        ),
        "vite.config.js": (
            'import { defineConfig } from "vite";\n'
            'import react from "@vitejs/plugin-react";\n\n'
            'export default defineConfig({\n  plugins: [react()],\n});\n'
        ),
        "index.html": (
            '<!DOCTYPE html>\n<html lang="en">\n  <head>\n    <meta charset="UTF-8" />\n'
            '    <title>My App</title>\n  </head>\n  <body>\n    <div id="root"></div>\n'
            '    <script type="module" src="/src/main.jsx"></script>\n  </body>\n</html>\n'
        ),
        "src/main.jsx": (
            'import React from "react";\n'
            'import ReactDOM from "react-dom/client";\n'
            'import App from "./App";\n\n'
            'ReactDOM.createRoot(document.getElementById("root")).render(\n'
            '  <React.StrictMode><App /></React.StrictMode>\n);\n'
        ),
        "src/App.jsx": (
            'import React from "react";\n\n'
            'export default function App() {\n'
            '  return <h1>Hello from ILX AI React App!</h1>;\n'
            '}\n'
        ),
        "README.md": "# My React App\n\n## Setup\n\n```bash\nnpm install\nnpm run dev\n```\n",
    },
    "fastapi": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        ".gitignore":    "__pycache__/\n*.pyc\n.venv/\nvenv/\n.env\n",
        "requirements.txt": "fastapi>=0.110\nuvicorn[standard]>=0.27\nhttpx>=0.27\npytest>=8\n",
        "main.py": (
            'from fastapi import FastAPI\n\n'
            'app = FastAPI(title="My API", version="0.1.0")\n\n\n'
            '@app.get("/health")\ndef health() -> dict:\n    return {"status": "ok"}\n\n\n'
            'if __name__ == "__main__":\n'
            '    import uvicorn\n'
            '    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)\n'
        ),
        "tests/__init__.py": "",
        "tests/test_main.py": (
            'from fastapi.testclient import TestClient\nfrom main import app\n\n'
            'client = TestClient(app)\n\n\n'
            'def test_health():\n    r = client.get("/health")\n    assert r.status_code == 200\n    assert r.json()["status"] == "ok"\n'
        ),
        "README.md": "# My FastAPI App\n\n## Run\n\n```bash\nuvicorn main:app --reload\n```\n\n## Test\n\n```bash\npytest\n```\n",
    },
    "django": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        ".gitignore":    "__pycache__/\n*.pyc\n.venv/\nvenv/\n.env\ndb.sqlite3\n",
        "requirements.txt": "django>=5.0\npytest-django>=4.7\n",
        "manage.py": (
            '#!/usr/bin/env python\nimport os\nimport sys\n\n\n'
            'def main():\n'
            '    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")\n'
            '    from django.core.management import execute_from_command_line\n'
            '    execute_from_command_line(sys.argv)\n\n\n'
            'if __name__ == "__main__":\n    main()\n'
        ),
        "README.md": "# My Django Project\n\n## Setup\n\n```bash\npip install -r requirements.txt\npython manage.py migrate\npython manage.py runserver\n```\n",
    },
    "rust": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        ".gitignore":    "target/\nCargo.lock\n",
        "Cargo.toml":    '[package]\nname = "myproject"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\n',
        "src/main.rs":   'fn main() {\n    println!("Hello, world!");\n}\n',
        "README.md":     "# My Rust Project\n\n## Build\n\n```bash\ncargo build\ncargo run\n```\n",
    },
    "go": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        ".gitignore":    "*.exe\n*.test\n/vendor/\n",
        "go.mod":        "module myproject\n\ngo 1.21\n",
        "main.go":       'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, world!")\n}\n',
        "README.md":     "# My Go Project\n\n## Run\n\n```bash\ngo run main.go\n```\n",
    },
}

_SCAFFOLD_PROMPTS: dict[str, str] = {
    "route":       "Write a FastAPI router file for the '{name}' resource. Include GET /list, GET /{id}, POST /, PUT /{id}, DELETE /{id} endpoints with Pydantic models. Return only the Python code.",
    "component":   "Write a React functional component named '{name}'. Include PropTypes, a default export, and minimal CSS-in-JS or inline styles. Return only the JSX code.",
    "model":       "Write a Python dataclass or Pydantic BaseModel named '{name}' with 4-6 realistic fields, validators where appropriate. Return only the Python code.",
    "test":        "Write pytest unit tests for a module named '{name}'. Include at least 5 test functions covering happy path, edge cases, and error handling. Return only the Python code.",
    "middleware":  "Write a FastAPI middleware class named '{name}Middleware' that logs request method, path, and response time. Return only the Python code.",
    "schema":      "Write a Pydantic v2 schema file for '{name}' with Create, Read, and Update variants. Return only the Python code.",
    "service":     "Write a Python service class named '{name}Service' with async CRUD methods (create, get, list, update, delete) that operate on an in-memory dict store. Return only the Python code.",
    "hook":        "Write a React custom hook named 'use{name}' that fetches data from an API endpoint and returns {{data, loading, error}}. Return only the TypeScript/JSX code.",
    "dockerfile": (
        "Write a production-ready multi-stage Dockerfile for a '{name}' application. "
        "Include a build stage and a minimal runtime stage. Use best practices: "
        "non-root user, .dockerignore hints, HEALTHCHECK. Return only the Dockerfile content."
    ),
    "github-actions": (
        "Write a GitHub Actions CI workflow YAML file for a '{name}' project. "
        "Include jobs for: lint (ruff + mypy), test (pytest --cov), and build. "
        "Use ubuntu-latest, Python 3.11, and cache pip dependencies. "
        "Return only the YAML content."
    ),
}


class WorkspaceCommands(WorkspaceMediaMixin):
    """Handles /add, /drop, /paste, /rules, /init, /scaffold, /diag.

    /readme, /convert, /fetch, and /tool are provided by WorkspaceMediaMixin.
    """

    def __init__(self, cfg: "AppConfig", ctx: "ContextManager") -> None:
        self.cfg = cfg
        self.ctx = ctx

    def cmd_add(self, rest: str, pinned: list[dict]) -> None:
        from cli.display import BOLD, DIM, GREEN, YELLOW, RESET
        rest = rest.strip().strip('"').strip("'")
        if not rest:
            if not pinned:
                print(f"  {DIM}No pinned context. Use /add <path>.{RESET}")
            else:
                print(f"  {BOLD}Pinned context ({len(pinned)} entries):{RESET}")
                for pc in pinned:
                    snippet = pc["content"][:60].replace("\n", " ")
                    print(f"    * {snippet}...")
            return
        p = Path(rest).expanduser()
        ctx_block = self.ctx.read_path(p, label=rest)
        content = f"[Pinned context: {rest}]\n{ctx_block}"
        pinned.append({"role": "user", "content": content})
        print(f"  {GREEN}Pinned:{RESET} {rest}  ({len(ctx_block)} chars)")

    def cmd_drop(self, args: list[str], pinned: list[dict]) -> None:
        from cli.display import GREEN, YELLOW, RESET
        if not args:
            print(f"  {YELLOW}Usage: /drop <path-substring>{RESET}")
            return
        needle = " ".join(args).lower()
        before = len(pinned)
        pinned[:] = [pc for pc in pinned if needle not in pc["content"].lower()]
        removed = before - len(pinned)
        if removed:
            print(f"  {GREEN}Removed {removed} pinned entry(s).{RESET}")
        else:
            print(f"  {YELLOW}No matching pinned entries found.{RESET}")

    def cmd_paste(self) -> str | None:
        from cli.display import DIM, GREEN, RESET
        print(f"  {DIM}Paste your content. Type ### on its own line when done:{RESET}")
        lines: list[str] = []
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                break
            if line.strip() == "###":
                break
            lines.append(line)
        result = "\n".join(lines)
        if result:
            print(f"  {GREEN}Ready — your next message will include the pasted content.{RESET}")
            return result
        print(f"  {DIM}Empty paste — cancelled.{RESET}")
        return None

    def cmd_rules(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, YELLOW, RESET
        from app.core import project_rules
        if args and args[0] == "edit":
            wf = self.cfg.working_folder
            if not wf:
                print(f"  {YELLOW}No workspace set.{RESET}")
                return
            rules_path = Path(wf) / ".ilx_rules.md"
            print(f"  Rules file: {rules_path}")
            if not rules_path.exists():
                rules_path.write_text("# Project Rules\n\n", encoding="utf-8")
                print(f"  {GREEN}Created:{RESET} {rules_path}")
            editor = (
                os.environ.get("EDITOR") or os.environ.get("VISUAL") or
                ("code"    if shutil.which("code")    else None) or
                ("cursor"  if shutil.which("cursor")  else None) or
                ("notepad" if os.name == "nt" else "nano")
            )
            try:
                import subprocess
                subprocess.Popen([editor, str(rules_path)])
                print(f"  {DIM}Opening in {editor}...{RESET}")
            except Exception as exc:
                print(f"  {YELLOW}Could not open editor: {exc}{RESET}")
        else:
            r = project_rules.load(self.cfg.working_folder)
            if r.is_empty:
                print(f"  {DIM}No project rules found.{RESET}")
                print(f"  {DIM}Create .ilx_rules.md in your workspace, or use /init to scaffold.{RESET}")
            else:
                print(f"\n{BOLD}Active project rules:{RESET}  (from {', '.join(r.sources)})")
                print(r.text[:2000] + ("..." if len(r.text) > 2000 else ""))
                print()

    def cmd_init(self, args: list[str]) -> None:
        from cli.display import DIM, GREEN, YELLOW, CYAN, RESET
        wf = self.cfg.working_folder
        if not wf:
            print(f"{YELLOW}No workspace set. Use /workspace to set one first.{RESET}")
            return
        dry_run = "--dry-run" in args
        if dry_run:
            args = [a for a in args if a != "--dry-run"]
        template = args[0].lower() if args else "python"
        # Optional second arg is the project name (used by "library" template)
        proj_name = args[1] if len(args) > 1 else Path(wf).name
        proj_name_cap = proj_name.capitalize()

        tpl = _INIT_TEMPLATES.get(template)
        if tpl is None:
            avail = ", ".join(_INIT_TEMPLATES)
            print(f"{YELLOW}Unknown template '{template}'. Available: {avail}{RESET}")
            return
        root = Path(wf)
        created = 0
        if dry_run:
            print(f"  {DIM}[dry-run] Would create in {wf}:{RESET}")
        for rel_raw, content_raw in tpl.items():
            # Substitute {name} / {Name} placeholders (used by "library" template)
            rel = rel_raw.replace("{name}", proj_name)
            content = (
                content_raw
                .replace("{name}", proj_name)
                .replace("{Name}", proj_name_cap)
            )
            dest = root / rel
            if dest.exists():
                print(f"  {DIM}skip (exists): {rel}{RESET}")
                continue
            if dry_run:
                print(f"  {CYAN}[dry-run] would create:{RESET} {rel}  ({len(content)} chars)")
                created += 1
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                print(f"  {GREEN}created:{RESET} {rel}")
                created += 1
        if dry_run:
            print(f"{CYAN}{created} file(s) would be created (dry-run — nothing written){RESET}")
        else:
            print(f"{GREEN}{created} file(s) created in {wf}{RESET}")
            # Offer Dockerfile generation if the project type is Docker-supported
            from cli.commands.docker_cmds import BEST_PRACTICE_DOCKERFILES
            if template in BEST_PRACTICE_DOCKERFILES:
                dockerfile_path = root / "Dockerfile"
                if not dockerfile_path.exists():
                    try:
                        ans = input(f"  {CYAN}Add Dockerfile? [y/N]: {RESET}").strip().lower()
                    except (EOFError, KeyboardInterrupt, OSError):
                        ans = "n"
                    if ans in ("y", "yes"):
                        from cli.commands.docker_cmds import DockerCommands
                        DockerCommands(self.cfg).scaffold_dockerfile(template, root)

    def cmd_scaffold(self, args: list[str]) -> None:
        from cli.display import BOLD, DIM, GREEN, RED, YELLOW, CYAN, RESET
        from codex.app.llm_client import get_llm_client
        from cli.commands.workspace_scaffold import ScaffoldExtensions

        # ── dry-run flag ────────────────────────────────────────────────────
        dry_run = "--dry-run" in args
        if dry_run:
            args = [a for a in args if a != "--dry-run"]

        if not args:
            from cli.commands.workspace_scaffold import SCAFFOLD_TYPE_DESCRIPTIONS
            avail = ", ".join(SCAFFOLD_TYPE_DESCRIPTIONS)
            print(f"{YELLOW}Usage: /scaffold <type> <name>{RESET}")
            print(f"  Types: {avail}")
            print(f"  Example: /scaffold route users")
            print(f"  Example: /scaffold component Button")
            return

        scaffold_type = args[0].lower()
        name          = args[1] if len(args) > 1 else ""
        wf            = self.cfg.working_folder

        if dry_run:
            path_hint = wf or "<workspace>"
            print(f"  {DIM}[dry-run] Would scaffold {scaffold_type} '{name}' in {path_hint}{RESET}")
            return

        if not wf:
            print(f"{YELLOW}No workspace set. Use /workspace first.{RESET}")
            return

        # ── static scaffold types (no LLM needed) ───────────────────────────
        ext = ScaffoldExtensions(self.cfg)
        if scaffold_type == "env":
            ext.cmd_scaffold_env()
            return
        if scaffold_type == "pre-commit":
            ext.cmd_scaffold_precommit()
            return
        if scaffold_type == "compose":
            ext.cmd_scaffold_compose()
            return

        if len(args) < 2:
            avail = ", ".join(_SCAFFOLD_PROMPTS)
            print(f"{YELLOW}Usage: /scaffold <type> <name>{RESET}")
            print(f"  Types: {avail}")
            print(f"  Example: /scaffold route users")
            print(f"  Example: /scaffold component Button")
            return

        prompt_template = _SCAFFOLD_PROMPTS.get(scaffold_type)
        if not prompt_template:
            from cli.commands.workspace_scaffold import SCAFFOLD_TYPE_DESCRIPTIONS
            avail = ", ".join(SCAFFOLD_TYPE_DESCRIPTIONS)
            print(f"{YELLOW}Unknown scaffold type '{scaffold_type}'. Available: {avail}{RESET}")
            return

        prompt = prompt_template.format(name=name)
        print(f"  {DIM}Generating {scaffold_type} '{name}'...{RESET}")

        client = get_llm_client(self.cfg)
        import concurrent.futures as _cf
        try:
            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                fut = _ex.submit(client.chat, [{"role": "user", "content": prompt}])
                response = fut.result(timeout=60)
        except _cf.TimeoutError:
            print(f"  {RED}Scaffold LLM call timed out after 60s.{RESET}")
            return
        except Exception as exc:
            print(f"  {RED}LLM error: {exc}{RESET}")
            return

        # Strip fenced code blocks if present
        import re
        m = re.search(r"```(?:\w+)?\s*\n(.*?)```", response, re.DOTALL)
        code = m.group(1).strip() if m else response.strip()

        # Determine output path
        ext_map = {
            "route": ("routes", ".py"), "model": ("models", ".py"),
            "test": ("tests", ".py"), "middleware": ("middleware", ".py"),
            "schema": ("schemas", ".py"), "service": ("services", ".py"),
            "component": ("src/components", ".jsx"), "hook": ("src/hooks", ".ts"),
            "dockerfile":      ("", "Dockerfile"),
            "github-actions":  (".github/workflows", ".yml"),
        }
        subdir, ext = ext_map.get(scaffold_type, ("", ".py"))
        file_name   = f"{name.lower()}{ext}" if scaffold_type != "hook" else f"use{name}{ext}"
        out_dir     = Path(wf) / subdir if subdir else Path(wf)
        out_path    = out_dir / file_name

        # Special cases where file name doesn't follow name+ext pattern
        if scaffold_type == "dockerfile":
            file_name = "Dockerfile"
        elif scaffold_type == "github-actions":
            file_name = f"{name.lower()}.yml"
        out_path = out_dir / file_name

        # --output <dir> override
        if "--output" in args:
            try:
                out_idx = args.index("--output")
                out_dir = Path(wf) / args[out_idx + 1]
                out_path = out_dir / file_name
            except (IndexError, ValueError):
                pass

        print(f"\n{BOLD}Generated {scaffold_type}:{RESET} {out_path.relative_to(Path(wf))}")
        print(f"  {DIM}{code[:300]}{'...' if len(code) > 300 else ''}{RESET}\n")

        try:
            ans = input(f"  {CYAN}Write this file? [y/N] {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"

        if ans in ("y", "yes"):
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(code + "\n", encoding="utf-8")
            print(f"  {GREEN}Written:{RESET} {out_path}")
        else:
            print(f"  {DIM}Cancelled.{RESET}")

    def cmd_diag(self) -> None:
        from cli.display import GREEN, RED, RESET
        from app.core.diagnostics import export, default_export_filename
        out_path = Path.home() / "Desktop" / default_export_filename()
        try:
            result_path = export(out_path)
            print(f"{GREEN}Diagnostic bundle saved:{RESET} {result_path}")
        except OSError as exc:
            print(f"{RED}Failed to export diagnostics: {exc}{RESET}")

