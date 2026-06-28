# ILX AI CLI

Free, local-first AI CLI for developers who want control, privacy, auditability, and no subscription lock-in.

ILX AI CLI is a terminal coding assistant that can chat, inspect a workspace, edit files, run tests, review diffs, scaffold projects, build Docker assets, use local or cloud models, and keep an audit trail of what happened. It is designed to work well with local Ollama models first, while still supporting BYO API keys for major cloud providers.

Current stage: **beta / active development**. The tool is usable for local-first workflows, controlled beta testing, and developer automation. Some advanced areas, especially OS-level sandboxing and MCP server interoperability, are still maturing.

---

## Why ILX?

| Need | ILX answer |
|---|---|
| Free forever | Local Ollama path, no subscription required |
| Privacy | Local-first design and no telemetry-oriented workflow |
| Model flexibility | Ollama, Anthropic, OpenAI, Groq, Gemini, Meta via Ollama |
| Control | Permission profiles, command allow/deny lists, sandbox modes |
| Auditability | JSONL audit log, replay/export/explain commands |
| Practical coding | Code agent, patch tool, review mode, test-fix loop, scaffolding |
| Portability | Pure terminal CLI, no IDE required |

---

## Installation

```bash
pip install ilx-ai-cli
ilx
```

From source:

```bash
git clone https://github.com/ilxstudio/ilx-ai-cli
cd ilx-ai-cli
pip install -e ".[all]"
python main.py
```

Requirements:

- Python 3.11+
- Ollama for local models, optional but recommended
- Windows, macOS, or Linux

Optional extras:

```bash
pip install "ilx-ai-cli[all]"
pip install "ilx-ai-cli[pdf]"
pip install "ilx-ai-cli[docx]"
pip install "ilx-ai-cli[xlsx]"
pip install "ilx-ai-cli[image]"
pip install rich
```

---

## Quick Start

### Local-Only (Zero Data Leaves Your Machine)

```bash
pip install ilx-ai-cli
ilx
```

Then in the REPL:

```
/model codellama:7b
/code
```

### With Cloud Provider

```
/provider anthropic
/apikey set
/chat
```

### Non-Interactive (CI / Scripting)

```bash
ilx --chat "explain main.py" --file main.py --quiet
ilx --chat "list functions" --json
```

### Interactive Setup

Start ILX:

```bash
ilx
```

Set your workspace:

```text
/workspace path/to/project
```

Use local models:

```bash
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

```text
/provider ollama
/model qwen2.5-coder:7b
```

Ask a question:

```text
explain the auth flow in @src/auth.py
```

Switch to code-agent mode:

```text
/code
add tests for the payment validator
```

Run a review:

```text
/review staged
```

Fix failing tests:

```text
/fix-tests
```

---

## Commands

Key v0.3 commands available in the ILX REPL:

| Command | Description |
|---------|-------------|
| `/plan <task>` | Plan a coding task step by step, then execute |
| `/fix-tests [--max N] [--only P]` | Run tests, auto-fix failures with LLM, repeat |
| `/index [build\|status\|clear]` | Build/manage the semantic codebase index |
| `/review [staged\|security\|<file>]` | AI-powered code review |
| `/research <question>` | Research using indexed codebase context |
| `/route [status\|set <strategy>]` | Configure automatic model routing |
| `/benchmark [quick\|full]` | Run LLM performance benchmarks |
| `/audit [security\|quality\|deps]` | Workspace audit passes |
| `/sandbox [mode]` | Configure sandbox containment mode |
| `/permission [profile <name>]` | Manage permission profiles |
| `/allow <cmd>` / `/deny <cmd>` | Add commands to allowlist or denylist |
| `/provider <name>` | Switch active model provider |
| `/model <name>` | Set the active model |
| `/chat` | Enter chat mode |
| `/code` | Enter code-agent mode |
| `/add <file>` | Add a file to conversation context |
| `/compact` | Summarize conversation to free context |
| `/export` | Export conversation history |
| `/git ai-commit` | Generate an AI commit message |
| `/mcp list` | List registered MCP tools |
| `/tool list` | List user-defined tools |
| `/rules` | View/edit project rules |
| `/status` | Show current configuration status |
| `/free` | Show free/local mode status |
| `/help` | Show all commands |

---

## One-Shot Mode

Use ILX in scripts or shell pipelines:

```bash
ilx --chat "explain this error"
ilx --code "add unit tests for src/auth.py" --yes
git diff | ilx --chat "summarize this diff" --quiet
ilx --chat "list risks in this file @app.py" --json
```

Supported flags:

```text
--chat       run one chat prompt and exit
--code, -c   run one code-agent task and exit
--yes        auto-approve permission prompts
--dry-run    show proposed work without writing
--json       machine-readable JSON-style output path
--quiet      reduce terminal decoration
--no-color   disable color-oriented output
```

---

## Providers

| Provider | Use case | Notes |
|---|---|---|
| `ollama` | Free local development | No API key |
| `meta` | Meta Llama via Ollama | No API key |
| `anthropic` | Claude models | BYO key, prompt caching support |
| `openai` | OpenAI models | BYO key |
| `groq` | Fast hosted open-weight models | BYO key |
| `gemini` | Gemini models/free-tier workflows | BYO key |

Commands:

```text
/provider ollama
/provider anthropic
/apikey set
/apikey get
/model qwen2.5-coder:7b
/models
/route auto
/route free-only
/route local-only
/route quality
```

API keys are stored in the OS keychain where available.

---

## Core Workflows

### Chat

```text
/chat
/add src/auth.py
explain this module
/compact
/export
```

### Code Agent

```text
/code
/tools on
refactor the CSV parser and run tests
```

Built-in tools include file read/write, directory listing, command execution, URL fetch, file conversion tools, and `apply_patch`.

### Plan Then Act

```text
/plan add rate limiting to the API
/plan approve
/plan cancel
```

### Review

```text
/review
/review staged
/review security
/review src/auth.py
```

### Test-Fix Loop

```text
/fix-tests
/fix-tests --max 10
/fix-tests --only tests/test_auth.py
```

### Repo Index And Research

```text
/index build
/index status
/research "how does authentication work?"
/context
```

### Project Scaffolding

```text
/init python
/init fastapi
/init react
/template list
/upgrade
/readme
/scaffold dockerfile
```

### Docker

```text
/docker help
/scaffold dockerfile
```

### Git

```text
/git status
/git diff
/git ai-commit
/git push
/branch
```

---

## Safety And Control

ILX separates permission behavior from workspace policy as much as possible.

Permission profiles:

```text
/permission status
/permission list
/permission safe
/permission coding
/permission review
/permission ci
/permission locked
```

Sandbox modes:

```text
/sandbox status
/sandbox workspace
/sandbox read-only
/sandbox off --i-understand
```

Command allow/deny lists:

```text
/allow command pytest
/allow command npm test
/deny command rm
/deny command git push
/allowlist
```

Important beta limitation: current sandboxing is primarily policy/path based. It is not yet a complete OS-level containment layer for every command on every platform. Review commands before running untrusted code.

---

## Audit Log

ILX records file operations, permission decisions, commands, model calls, and network-related events in an audit log under `~/.ilx_cli`.

```text
/audit
/audit security
/audit quality
/audit deps
/audit replay
/audit explain
/audit export --csv
/audit diff
/metrics
```

Secret-shaped fields are redacted before logging.

---

## MCP And User Tools

Built-in MCP-style tool registry:

```text
/mcp init
/mcp list
/mcp call read_file {"path":"README.md"}
```

Stdio MCP server support:

```text
/mcp servers status
/mcp servers example
/mcp servers connect
/mcp servers tools
/mcp servers call server__tool {"arg":"value"}
```

User-defined tools:

```text
/tool new
/tool list
/tool validate my_tool
/tool run my_tool --help
/tool remove my_tool
```

---

## Free/Local Onboarding

Commands designed for the free/local-first workflow:

```text
/free
/setup local
/benchmark
/route free-only
/route local-only
```

Use these to verify what is local, what may call a cloud provider, and how well your configured local model performs.

---

## Current Test Status

Latest local audit run:

```text
677 passed, 1 failed, 1 skipped
```

The remaining observed failure was a live/local LLM quality test, not a deterministic infrastructure failure. For release workflows, live provider/model tests should be run separately from deterministic unit and integration tests.

Run tests:

```bash
pip install -e ".[dev,all]"
python -m pytest tests -q
```

---

## Project Rules

Rules files are injected into prompts:

| File | Scope |
|---|---|
| `.ilx_rules.md` | Project rules, commit to repo |
| `.ilx_rules.local.md` | Personal local rules |
| `~/.ilx_cli/rules.md` | Global rules |

Use:

```text
/rules
/rules edit
```

---

## Documentation

See [USER_MANUAL.md](USER_MANUAL.md) for the full command guide and operating manual.

Recent audit files in this repository document the current release-readiness assessment and recommended hardening path.

---

## License

MIT. See [LICENSE](LICENSE).

