"""Scaffold expansion — new /init templates, /scaffold env|pre-commit|compose, /template list, /upgrade."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.scaffold")

# ---------------------------------------------------------------------------
# New /init template entries (merged into _INIT_TEMPLATES in workspace_cmds)
# ---------------------------------------------------------------------------

EXTRA_INIT_TEMPLATES: dict[str, dict[str, str]] = {
    "flask": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        "app.py": (
            'from flask import Flask, jsonify\n'
            'from dotenv import load_dotenv\nimport os\n\n'
            'load_dotenv()\n\n'
            'app = Flask(__name__)\n'
            'app.secret_key = os.getenv("SECRET_KEY", "dev-secret")\n\n\n'
            '@app.route("/")\ndef index():\n'
            '    return jsonify({"message": "Hello from Flask!", "status": "ok"})\n\n\n'
            'if __name__ == "__main__":\n'
            '    port = int(os.getenv("PORT", 5000))\n'
            '    app.run(debug=True, host="0.0.0.0", port=port)\n'
        ),
        "requirements.txt": "flask>=3.0\npython-dotenv>=1.0\npytest>=8\n",
        ".gitignore": (
            "__pycache__/\n*.pyc\n.venv/\nvenv/\n.env\ndist/\nbuild/\n*.egg-info/\n"
            "instance/\n.pytest_cache/\n"
        ),
        ".env.example": "PORT=5000\nSECRET_KEY=\n",
        "tests/__init__.py": "",
        "tests/test_app.py": (
            'import pytest\nfrom app import app as flask_app\n\n\n'
            '@pytest.fixture\ndef client():\n'
            '    flask_app.config["TESTING"] = True\n'
            '    with flask_app.test_client() as c:\n'
            '        yield c\n\n\n'
            'def test_index_returns_ok(client):\n'
            '    r = client.get("/")\n'
            '    assert r.status_code == 200\n'
            '    data = r.get_json()\n'
            '    assert data["status"] == "ok"\n'
        ),
    },
    "express": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        "index.js": (
            'import express from "express";\nimport "dotenv/config";\n\n'
            'const app = express();\n'
            'const PORT = process.env.PORT ?? 3000;\n\n'
            'app.use(express.json());\n\n'
            'app.get("/", (_req, res) => {\n'
            '  res.json({ message: "Hello from Express!", status: "ok" });\n'
            '});\n\n'
            'app.listen(PORT, () => {\n'
            '  console.log(`Server running on http://localhost:${PORT}`);\n'
            '});\n\n'
            'export default app;\n'
        ),
        "package.json": (
            '{\n  "name": "myapp",\n  "version": "1.0.0",\n'
            '  "type": "module",\n'
            '  "scripts": {\n'
            '    "start": "node index.js",\n'
            '    "dev": "node --watch index.js",\n'
            '    "test": "node --test"\n'
            '  },\n'
            '  "dependencies": {\n'
            '    "express": "^4.18.0",\n'
            '    "dotenv": "^16.0.0"\n'
            '  }\n'
            '}\n'
        ),
        ".gitignore": "node_modules/\ndist/\n.env\n.cache/\n",
        ".env.example": "PORT=3000\n",
    },
    "nextjs": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        "package.json": (
            '{\n  "name": "myapp",\n  "version": "0.1.0",\n  "private": true,\n'
            '  "scripts": {\n'
            '    "dev": "next dev",\n'
            '    "build": "next build",\n'
            '    "start": "next start",\n'
            '    "lint": "next lint"\n'
            '  },\n'
            '  "dependencies": {\n'
            '    "next": "^14.0.0",\n'
            '    "react": "^18.2.0",\n'
            '    "react-dom": "^18.2.0"\n'
            '  }\n'
            '}\n'
        ),
        "next.config.js": (
            '/** @type {import("next").NextConfig} */\n'
            'const nextConfig = {\n  reactStrictMode: true,\n};\n\n'
            'export default nextConfig;\n'
        ),
        ".gitignore": ".next/\nnode_modules/\n.env*.local\ndist/\nout/\n",
        ".env.local.example": "NEXT_PUBLIC_API_URL=http://localhost:3000\n",
        "pages/index.jsx": (
            'export default function Home() {\n'
            '  return (\n'
            '    <main style={{ padding: "2rem", fontFamily: "sans-serif" }}>\n'
            '      <h1>Welcome to My Next.js App</h1>\n'
            '      <p>Edit <code>pages/index.jsx</code> to get started.</p>\n'
            '    </main>\n'
            '  );\n'
            '}\n'
        ),
        "pages/_app.jsx": (
            'export default function App({ Component, pageProps }) {\n'
            '  return <Component {...pageProps} />;\n'
            '}\n'
        ),
    },
    "vue": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        "package.json": (
            '{\n  "name": "myapp",\n  "version": "0.0.0",\n  "private": true,\n'
            '  "scripts": {\n'
            '    "dev": "vite",\n'
            '    "build": "vite build",\n'
            '    "preview": "vite preview"\n'
            '  },\n'
            '  "dependencies": {\n'
            '    "vue": "^3.4.0"\n'
            '  },\n'
            '  "devDependencies": {\n'
            '    "@vitejs/plugin-vue": "^5.0.0",\n'
            '    "vite": "^5.0.0"\n'
            '  }\n'
            '}\n'
        ),
        "vite.config.js": (
            'import { defineConfig } from "vite";\nimport vue from "@vitejs/plugin-vue";\n\n'
            'export default defineConfig({\n  plugins: [vue()],\n});\n'
        ),
        ".gitignore": "dist/\nnode_modules/\n.env\n",
        "src/App.vue": (
            '<template>\n'
            '  <div id="app">\n'
            '    <h1>{{ greeting }}</h1>\n'
            '    <button @click="count++">Clicked {{ count }} time(s)</button>\n'
            '  </div>\n'
            '</template>\n\n'
            '<script setup>\nimport { ref } from "vue";\n\n'
            'const greeting = "Hello from Vue 3!";\n'
            'const count = ref(0);\n'
            '</script>\n\n'
            '<style scoped>\n#app { font-family: sans-serif; text-align: center; padding: 2rem; }\n</style>\n'
        ),
        "src/main.js": (
            'import { createApp } from "vue";\nimport App from "./App.vue";\n\n'
            'createApp(App).mount("#app");\n'
        ),
        "index.html": (
            '<!DOCTYPE html>\n<html lang="en">\n  <head>\n'
            '    <meta charset="UTF-8" />\n'
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
            '    <title>My Vue App</title>\n'
            '  </head>\n'
            '  <body>\n    <div id="app"></div>\n'
            '    <script type="module" src="/src/main.js"></script>\n'
            '  </body>\n</html>\n'
        ),
    },
    "svelte": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        "package.json": (
            '{\n  "name": "myapp",\n  "version": "0.0.1",\n  "private": true,\n'
            '  "scripts": {\n'
            '    "dev": "vite dev",\n'
            '    "build": "vite build",\n'
            '    "preview": "vite preview"\n'
            '  },\n'
            '  "devDependencies": {\n'
            '    "@sveltejs/vite-plugin-svelte": "^3.0.0",\n'
            '    "svelte": "^4.0.0",\n'
            '    "vite": "^5.0.0"\n'
            '  }\n'
            '}\n'
        ),
        "svelte.config.js": (
            'import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";\n\n'
            'export default {\n  preprocess: vitePreprocess(),\n};\n'
        ),
        ".gitignore": "build/\n.svelte-kit/\nnode_modules/\n.env\ndist/\n",
        "src/routes/+page.svelte": (
            '<script>\n  let count = 0;\n</script>\n\n'
            '<main>\n'
            '  <h1>Hello from SvelteKit!</h1>\n'
            '  <button on:click={() => count++}>Clicked {count} time(s)</button>\n'
            '</main>\n\n'
            '<style>\n  main { font-family: sans-serif; text-align: center; padding: 2rem; }\n</style>\n'
        ),
    },
    "electron": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        "package.json": (
            '{\n  "name": "myapp",\n  "version": "1.0.0",\n'
            '  "description": "An Electron desktop app",\n'
            '  "main": "main.js",\n'
            '  "scripts": {\n'
            '    "start": "electron .",\n'
            '    "build": "electron-builder"\n'
            '  },\n'
            '  "devDependencies": {\n'
            '    "electron": "^29.0.0"\n'
            '  }\n'
            '}\n'
        ),
        "main.js": (
            'const { app, BrowserWindow } = require("electron");\nconst path = require("path");\n\n'
            'function createWindow() {\n'
            '  const win = new BrowserWindow({\n'
            '    width: 1024,\n    height: 768,\n'
            '    webPreferences: {\n'
            '      preload: path.join(__dirname, "preload.js"),\n'
            '      contextIsolation: true,\n'
            '      nodeIntegration: false,\n'
            '    },\n'
            '  });\n'
            '  win.loadFile(path.join(__dirname, "renderer", "index.html"));\n'
            '}\n\n'
            'app.whenReady().then(createWindow);\n\n'
            'app.on("window-all-closed", () => {\n'
            '  if (process.platform !== "darwin") app.quit();\n'
            '});\n\n'
            'app.on("activate", () => {\n'
            '  if (BrowserWindow.getAllWindows().length === 0) createWindow();\n'
            '});\n'
        ),
        "preload.js": (
            'const { contextBridge } = require("electron");\n\n'
            '// Expose safe APIs to the renderer\n'
            'contextBridge.exposeInMainWorld("api", {\n'
            '  version: () => process.versions.electron,\n'
            '});\n'
        ),
        "renderer/index.html": (
            '<!DOCTYPE html>\n<html lang="en">\n  <head>\n'
            '    <meta charset="UTF-8" />\n'
            '    <meta http-equiv="Content-Security-Policy"\n'
            '          content="default-src \'self\'; script-src \'self\'" />\n'
            '    <title>My Electron App</title>\n'
            '  </head>\n'
            '  <body>\n'
            '    <h1>Hello from Electron!</h1>\n'
            '    <p id="version"></p>\n'
            '    <script>\n'
            '      document.getElementById("version").textContent =\n'
            '        "Electron v" + window.api.version();\n'
            '    </script>\n'
            '  </body>\n'
            '</html>\n'
        ),
        ".gitignore": "node_modules/\ndist/\nout/\n",
    },
    "cli-tool": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        "pyproject.toml": (
            '[build-system]\n'
            'requires = ["setuptools>=68"]\n'
            'build-backend = "setuptools.build_meta"\n\n'
            '[project]\n'
            'name = "mycli"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.11"\n'
            'dependencies = ["click>=8.0"]\n\n'
            '[project.scripts]\n'
            'mycli = "cli.main:cli"\n\n'
            '[tool.ruff.lint]\n'
            'select = ["E", "F", "I"]\n'
        ),
        "src/cli/__init__.py": "",
        "src/cli/main.py": (
            '"""CLI entry point."""\nfrom __future__ import annotations\n\nimport click\n\n\n'
            '@click.group()\n@click.version_option()\ndef cli() -> None:\n'
            '    """mycli — a command-line tool."""\n\n\n'
            '@cli.command()\n@click.argument("name", default="world")\ndef hello(name: str) -> None:\n'
            '    """Say hello."""\n    click.echo(f"Hello, {name}!")\n\n\n'
            'if __name__ == "__main__":\n    cli()\n'
        ),
        "tests/__init__.py": "",
        "tests/test_cli.py": (
            'from click.testing import CliRunner\nfrom src.cli.main import cli\n\n\n'
            'def test_hello_default():\n'
            '    runner = CliRunner()\n'
            '    result = runner.invoke(cli, ["hello"])\n'
            '    assert result.exit_code == 0\n'
            '    assert "Hello, world!" in result.output\n\n\n'
            'def test_hello_with_name():\n'
            '    runner = CliRunner()\n'
            '    result = runner.invoke(cli, ["hello", "Alice"])\n'
            '    assert result.exit_code == 0\n'
            '    assert "Hello, Alice!" in result.output\n'
        ),
        ".gitignore": (
            "__pycache__/\n*.pyc\n.venv/\nvenv/\ndist/\nbuild/\n*.egg-info/\n.env\n"
        ),
    },
    "library": {
        ".ilx_rules.md": "# Project Rules\n\n<!-- Add project-specific AI behavior rules here -->\n",
        "pyproject.toml": (
            '[build-system]\n'
            'requires = ["setuptools>=68"]\n'
            'build-backend = "setuptools.build_meta"\n\n'
            '[project]\n'
            'name = "{name}"\n'
            'version = "0.1.0"\n'
            'description = "A Python library"\n'
            'requires-python = ">=3.11"\n'
            'dependencies = []\n\n'
            '[tool.pytest.ini_options]\n'
            'testpaths = ["tests"]\n\n'
            '[tool.ruff.lint]\n'
            'select = ["E", "F", "I"]\n'
        ),
        "src/{name}/__init__.py": (
            '__version__ = "0.1.0"\n\n'
            '__all__ = ["__version__"]\n'
        ),
        "src/{name}/core.py": (
            '"""Core module for {name}."""\nfrom __future__ import annotations\n\n\n'
            'class {Name}:\n'
            '    """Primary class for {name}."""\n\n'
            '    def __init__(self, name: str = "{name}") -> None:\n'
            '        self.name = name\n\n'
            '    def greet(self) -> str:\n'
            '        """Return a greeting string."""\n'
            '        return f"Hello from {self.name}!"\n'
        ),
        "tests/__init__.py": "",
        "tests/test_core.py": (
            'from src.{name}.core import {Name}\n\n\n'
            'def test_greet_returns_string():\n'
            '    obj = {Name}()\n'
            '    result = obj.greet()\n'
            '    assert isinstance(result, str)\n'
            '    assert len(result) > 0\n\n\n'
            'def test_greet_contains_name():\n'
            '    obj = {Name}("mylib")\n'
            '    assert "mylib" in obj.greet()\n'
        ),
        ".gitignore": (
            "__pycache__/\n*.pyc\n.venv/\nvenv/\ndist/\nbuild/\n*.egg-info/\n.env\n"
        ),
    },
}

# ---------------------------------------------------------------------------
# Static scaffold types (written directly, no LLM)
# ---------------------------------------------------------------------------

_PRE_COMMIT_YAML = """\
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
"""

_COMPOSE_YAML = """\
version: "3.9"
services:
  app:
    build: .
    ports:
      - "${PORT:-8000}:8000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${DB_NAME:-appdb}
      POSTGRES_USER: ${DB_USER:-appuser}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-changeme}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "${DB_USER:-appuser}"]
      interval: 5s
      timeout: 3s
      retries: 5
volumes:
  pgdata:
"""

# ---------------------------------------------------------------------------
# Template metadata for /template list
# ---------------------------------------------------------------------------

INIT_TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "python":   "Python package with pyproject.toml, src/ layout, and pytest",
    "node":     "Bare Node.js project with src/index.js and npm scripts",
    "react":    "React + Vite SPA with JSX components",
    "fastapi":  "FastAPI REST API with uvicorn and test client",
    "django":   "Django project with manage.py and pytest-django",
    "rust":     "Rust binary crate with Cargo.toml",
    "go":       "Go module with main.go",
    "flask":    "Flask web app with routes, .env support, and pytest",
    "express":  "Express.js REST API with dotenv",
    "nextjs":   "Next.js 14 app with Pages Router",
    "vue":      "Vue 3 + Vite SPA with Composition API",
    "svelte":   "SvelteKit project with a starter page",
    "electron": "Electron desktop app with preload + renderer",
    "cli-tool": "Click-based Python CLI with pyproject.toml scripts entry",
    "library":  "Python library with src/ layout, versioned __init__.py",
}

SCAFFOLD_TYPE_DESCRIPTIONS: dict[str, str] = {
    "route":          "FastAPI router file with CRUD endpoints",
    "component":      "React functional component with PropTypes",
    "model":          "Python dataclass or Pydantic BaseModel",
    "test":           "pytest test suite (5+ test functions)",
    "middleware":      "FastAPI middleware with request logging",
    "schema":         "Pydantic v2 schema (Create / Read / Update)",
    "service":        "Python async service class with in-memory CRUD",
    "hook":           "React custom hook with data-fetching pattern",
    "dockerfile":     "Multi-stage production Dockerfile",
    "github-actions": "GitHub Actions CI workflow (lint + test + build)",
    "env":            "Generate .env.example from existing .env (or detect stack)",
    "pre-commit":     "Write .pre-commit-config.yaml with ruff hooks",
    "compose":        "Write docker-compose.yml with app + postgres",
}


# ---------------------------------------------------------------------------
# ScaffoldExtensions — extra /scaffold sub-commands
# ---------------------------------------------------------------------------

class ScaffoldExtensions:
    """Handles /scaffold env, /scaffold pre-commit, /scaffold compose."""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    # ── /scaffold env ──────────────────────────────────────────────────────

    def cmd_scaffold_env(self) -> None:
        from cli.display import CYAN, DIM, GREEN, RESET, YELLOW

        wf = self.cfg.working_folder
        if not wf:
            print(f"{YELLOW}No workspace set. Use /workspace first.{RESET}")
            return
        root = Path(wf)
        env_path = root / ".env"
        example_path = root / ".env.example"

        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
            keys: list[str] = []
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key:
                        keys.append(key)
            if not keys:
                print(f"  {YELLOW}.env found but no KEY=VALUE pairs detected.{RESET}")
                return
            content = "\n".join(f"{k}=" for k in keys) + "\n"
            example_path.write_text(content, encoding="utf-8")
            print(f"  {GREEN}Created:{RESET} .env.example  ({len(keys)} key(s))")
            for k in keys:
                print(f"    {CYAN}{k}{RESET}=")
        else:
            # No .env — detect stack and emit sensible defaults
            content = self._detect_stack_env(root)
            example_path.write_text(content, encoding="utf-8")
            print(f"  {DIM}No .env found — generated .env.example from detected stack.{RESET}")
            print(f"  {GREEN}Created:{RESET} .env.example")
            print(f"  {DIM}{content.strip()}{RESET}")

    def _detect_stack_env(self, root: Path) -> str:
        """Return sensible .env.example content based on detected project files."""
        if (root / "requirements.txt").exists() or (root / "pyproject.toml").exists():
            # Python stack
            reqs = ""
            for f in ("requirements.txt",):
                p = root / f
                if p.exists():
                    reqs = p.read_text(encoding="utf-8", errors="replace").lower()
            if "flask" in reqs:
                return "PORT=5000\nSECRET_KEY=\nDEBUG=false\nDATABASE_URL=\n"
            if "fastapi" in reqs or "uvicorn" in reqs:
                return "PORT=8000\nDEBUG=false\nDATABASE_URL=\nSECRET_KEY=\n"
            if "django" in reqs:
                return "SECRET_KEY=\nDEBUG=false\nDATABASE_URL=\nALLOWED_HOSTS=localhost\n"
            return "PORT=8000\nDEBUG=false\nSECRET_KEY=\n"
        if (root / "package.json").exists():
            try:
                import json
                pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            except Exception:
                deps = {}
            if "next" in deps:
                return "NEXT_PUBLIC_API_URL=http://localhost:3000\nDATABASE_URL=\n"
            if "express" in deps:
                return "PORT=3000\nDATABASE_URL=\nSECRET=\n"
            return "PORT=3000\n"
        if (root / "Cargo.toml").exists():
            return "RUST_LOG=info\n"
        if (root / "go.mod").exists():
            return "PORT=8080\nGIN_MODE=release\n"
        return "PORT=8000\nSECRET_KEY=\n"

    # ── /scaffold pre-commit ───────────────────────────────────────────────

    def cmd_scaffold_precommit(self) -> None:
        from cli.display import DIM, GREEN, RESET, YELLOW
        wf = self.cfg.working_folder
        if not wf:
            print(f"{YELLOW}No workspace set. Use /workspace first.{RESET}")
            return
        out = Path(wf) / ".pre-commit-config.yaml"
        if out.exists():
            print(f"  {DIM}.pre-commit-config.yaml already exists — skipping.{RESET}")
            return
        out.write_text(_PRE_COMMIT_YAML, encoding="utf-8")
        print(f"  {GREEN}Created:{RESET} .pre-commit-config.yaml")
        print(f"  {DIM}Run: pip install pre-commit && pre-commit install{RESET}")

    # ── /scaffold compose ──────────────────────────────────────────────────

    def cmd_scaffold_compose(self) -> None:
        from cli.display import DIM, GREEN, RESET, YELLOW
        wf = self.cfg.working_folder
        if not wf:
            print(f"{YELLOW}No workspace set. Use /workspace first.{RESET}")
            return
        out = Path(wf) / "docker-compose.yml"
        if out.exists():
            print(f"  {DIM}docker-compose.yml already exists — skipping.{RESET}")
            return
        out.write_text(_COMPOSE_YAML, encoding="utf-8")
        print(f"  {GREEN}Created:{RESET} docker-compose.yml")
        print(f"  {DIM}Run: docker compose up -d{RESET}")


# ---------------------------------------------------------------------------
# TemplateListCommand — /template list
# ---------------------------------------------------------------------------

class TemplateListCommand:
    """Prints a formatted table of all /init and /scaffold types."""

    def cmd_template_list(self) -> None:
        from cli.display import BOLD, CYAN, DIM, GREEN, RESET

        print(f"\n{BOLD}/init templates{RESET}  {DIM}(usage: /init <type>){RESET}\n")
        print(f"  {'Type':<15} {'Description'}")
        print(f"  {'-'*15} {'-'*50}")
        for name, desc in INIT_TEMPLATE_DESCRIPTIONS.items():
            print(f"  {CYAN}{name:<15}{RESET} {desc}")

        print(f"\n{BOLD}/scaffold types{RESET}  {DIM}(usage: /scaffold <type> <name>){RESET}\n")
        print(f"  {'Type':<18} {'Description'}")
        print(f"  {'-'*18} {'-'*50}")
        for name, desc in SCAFFOLD_TYPE_DESCRIPTIONS.items():
            prefix = "" if name in ("env", "pre-commit", "compose") else "<name> "
            print(f"  {GREEN}{name:<18}{RESET} {desc}  {DIM}{prefix}{RESET}")
        print()


# ---------------------------------------------------------------------------
# UpgradeCommand — moved to workspace_upgrade.py; re-exported for compatibility
# ---------------------------------------------------------------------------

from cli.commands.workspace_upgrade import UpgradeCommand as UpgradeCommand  # noqa: F401
