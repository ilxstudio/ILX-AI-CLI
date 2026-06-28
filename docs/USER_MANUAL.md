# ILX AI CLI User Manual

Version: 0.3.0 beta
Updated: 2026-06-28

ILX AI CLI is a free, local-first AI developer CLI. It supports chat, code-agent workflows, file and command tools, repo context, project scaffolding, review, test repair, audit logging, model routing, and local/cloud provider switching.

This manual describes the current project stage. Some advanced features are beta-quality, especially MCP stdio interoperability and sandboxing beyond workspace/path policy.

---

## Contents

1. Installation
2. First Run
3. Providers And Models
4. Free/Local-First Workflow
5. Chat Mode
6. Code Agent Mode
7. Planning, Review, And Test Repair
8. Context, Indexing, And Research
9. Permissions, Sandbox, And Command Policies
10. Audit, Metrics, And Diagnostics
11. Git, Dev Tools, And Docker
12. Project Scaffolding
13. User Tools And MCP
14. One-Shot And Automation Mode
15. Settings Reference
16. Troubleshooting
17. Full Command Reference

---

## 1. Installation

### Install From pip

```bash
pip install ilx-ai-cli
ilx
```

### Install From Source

```bash
git clone https://github.com/ilxstudio/ilx-ai-cli
cd ilx-ai-cli
pip install -e ".[all]"
python main.py
```

### Requirements

- Python 3.11 or newer
- Ollama for local models, recommended
- Windows, macOS, or Linux

### Optional Dependencies

```bash
pip install "ilx-ai-cli[all]"
pip install "ilx-ai-cli[pdf]"
pip install "ilx-ai-cli[docx]"
pip install "ilx-ai-cli[xlsx]"
pip install "ilx-ai-cli[image]"
pip install rich
pip install bandit radon pip-audit
```

The core package intentionally has a small dependency footprint. Optional packages unlock richer rendering, file conversion, and deeper audit checks.

---

## 2. First Run

Start the CLI:

```bash
ilx
```

Set a workspace:

```text
/workspace D:\Projects\my-app
```

Check status:

```text
/status
/version
/healthcheck
```

The startup screen shows the current trust summary:

```text
Provider  : ollama / qwen2.5-coder:7b
Workspace : D:\Projects\my-app
Permission: ask
Sandbox   : workspace
Network   : ask
Tools     : disabled
Audit     : enabled
```

If the workspace path does not exist, set a valid one before using code-agent tools.

---

## 3. Providers And Models

ILX supports local and cloud model providers.

| Provider | Command | Notes |
|---|---|---|
| Ollama | `/provider ollama` | Free local models, no API key |
| Meta via Ollama | `/provider meta` | Uses local Ollama Llama models |
| Anthropic | `/provider anthropic` | BYO API key |
| OpenAI | `/provider openai` | BYO API key |
| Groq | `/provider groq` | BYO API key |
| Gemini | `/provider gemini` | BYO API key |

### Local Ollama Setup

```bash
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

Then:

```text
/provider ollama
/model qwen2.5-coder:7b
```

Recommended local coding models depend on your hardware. Use:

```text
/setup local
```

to inspect the local environment and receive model suggestions.

### API Keys

```text
/provider anthropic
/apikey set
/apikey get
```

Keys are stored through the OS keychain where available. They are not intended to be written into project config files.

### Models

```text
/models
/model
/model qwen2.5-coder:7b
/server http://localhost:11434
```

### Model Routing

The router helps choose local, free, or higher-quality providers by task.

```text
/route status
/route explain
/route auto
/route free-only
/route local-only
/route quality
/route reset
```

Strategies:

| Strategy | Behavior |
|---|---|
| `auto` | Prefer local, then free, then paid if configured |
| `free-only` | Local plus free-tier style workflows only |
| `local-only` | Ollama only, no cloud model calls |
| `quality` | Prefer highest-capability configured provider |

---

## 4. Free/Local-First Workflow

ILX is designed to be useful without a subscription.

Useful commands:

```text
/free
/setup local
/benchmark
/route local-only
/route free-only
```

`/free` explains the current privacy/free posture, local/cloud provider state, audit log location, and network/model-use implications.

`/benchmark` runs small local tasks and reports how well the configured model performs for editing, bug fixing, tests, summarization, and documentation.

---

## 5. Chat Mode

Chat mode is the default. It answers questions and can use attached files for context.

```text
/chat
explain the architecture of @src/app.py
```

### Conversation Commands

```text
/clear
/undo
/compact
/history
/resume 2
/session list
/session name auth-investigation
/session search auth
/export
/copy
```

### Multi-Line Input

```text
/paste
```

Paste content, then end with `###` on its own line.

### Attach Files Inline

```text
explain @src/auth.py
compare @"old version.py" and @"new version.py"
```

Images can be attached the same way for vision-capable providers:

```text
describe @screenshot.png
```

Ollama vision support depends on the selected local model. Text-only local models receive the text prompt and show a warning.

---

## 6. Code Agent Mode

Code mode is for file edits, tests, and multi-step development tasks.

```text
/code
add validation to the user signup endpoint and run tests
```

Recommended setup:

```text
/workspace D:\Projects\my-app
/permission coding
/sandbox workspace
/tools on
/code
```

### Tool Use

```text
/tools
/tools on
/tools off
/tools list
```

Built-in tools include:

- `read_file`
- `write_file`
- `list_dir`
- `run_command`
- `fetch_url`
- `apply_patch`
- file conversion tools for PDF, DOCX, XLSX, and PNG when extras are installed

### Patch Editing

`apply_patch` is available for targeted file edits. It supports:

- conflict-style blocks:

```text
<<<<<<< ORIGINAL
old text
=======
new text
>>>>>>> MODIFIED
```

- unified diff format

Patch writes are sandbox checked and written atomically.

### Background Tasks

```text
/tasks
/attach T0001
/kill T0001
/logs 100
```

---

## 7. Planning, Review, And Test Repair

### Plan Then Act

Use plan mode when you want the assistant to inspect first and act only after approval.

```text
/plan add rate limiting to the API
/plan approve
/plan cancel
```

The plan workflow is useful for larger changes, risky refactors, and architecture-sensitive edits.

### Review Mode

```text
/review
/review staged
/review security
/review src/auth.py
```

Review mode focuses on:

- bugs,
- security issues,
- behavioral regressions,
- maintainability risks,
- missing tests.

### Test-Fix Loop

```text
/fix-tests
/fix-tests --max 10
/fix-tests --only tests/test_auth.py
```

The loop runs tests, parses failures, asks the model for targeted fixes, applies changes, and repeats until tests pass or the attempt limit is reached.

---

## 8. Context, Indexing, And Research

### Add And Drop Context

```text
/add src/auth.py
/add src/
/drop src/auth.py
/context
/context clear
```

### Conversation Compaction

```text
/compact
```

Summarizes old conversation turns to reduce context usage.

### Repo Index

```text
/index build
/index status
/index explain "how auth works"
/index clear
```

The repo index is used for persistent workspace understanding and retrieval-oriented workflows.

### Research

```text
/research "how does authentication work?"
/research "where are database writes?"
/fetch https://docs.python.org/3/library/asyncio.html
```

Research mode uses retrieval and summarization for codebase exploration or external documentation review.

### Semantic RAG

For local semantic retrieval:

```bash
ollama pull nomic-embed-text
```

ILX falls back to BM25-style retrieval if embeddings are unavailable.

---

## 9. Permissions, Sandbox, And Command Policies

### Permission Profiles

```text
/permission status
/permission list
/permission safe
/permission coding
/permission review
/permission ci
/permission locked
```

Profiles:

| Profile | Reads | Writes | Commands | Network |
|---|---|---|---|---|
| `safe` | ask | ask | ask | ask |
| `coding` | auto | ask | ask | deny |
| `review` | auto | deny | deny | deny |
| `ci` | auto | auto | auto | deny |
| `locked` | deny | deny | deny | deny |

### Raw Permission Mode

Older commands are still supported through `/perms` and mode settings:

```text
/perms
/permission status
```

### Sandbox Modes

```text
/sandbox status
/sandbox workspace
/sandbox read-only
/sandbox off --i-understand
```

Important limitation: current sandboxing is primarily workspace/path policy. It is not yet guaranteed OS-level containment for every subprocess on every platform. A permitted command may still have the operating-system permissions of your user account.

### Command Allow/Deny Lists

```text
/allow command pytest
/allow command npm test
/allow command ruff
/deny command rm
/deny command git push
/allowlist
```

Allow/deny lists reduce prompt fatigue while keeping dangerous commands blocked.

---

## 10. Audit, Metrics, And Diagnostics

### Workspace Audit

```text
/audit
/audit security
/audit quality
/audit deps
/audit compare
/audit compare aider
```

Audit checks cover:

- hardcoded secrets,
- `shell=True`,
- dynamic `eval`/`exec`,
- optional `bandit`,
- optional `pip-audit`,
- line count and complexity,
- dependency health.

### Audit Log

```text
/audit replay
/audit replay today
/audit replay 100
/audit explain
/audit explain 50
/audit export
/audit export --csv
/audit diff
/metrics
```

The audit log records actions under `~/.ilx_cli`. Secret-shaped fields are redacted.

### Diagnostics

```text
/diag
/crashes
/crashes summary
/crashes clear
/errors
```

`/diag` exports diagnostic files to help debug environment issues.

---

## 11. Git, Dev Tools, And Docker

### Git

```text
/git status
/git diff
/git diff --staged
/git log
/git commit
/git commit -m "message"
/git ai-commit
/git pull
/git push
/git stash
/git stash pop
/git revert <hash>
/branch
/diff
```

### Dev Tools

```text
/run python -m pytest
/test
/test --cov
/lint
/lint --fix
/format
/ci
/watch
/profile script.py
/build
/deps
/deps outdated
/env
/stats
/complexity
/deadcode
/bandit
/precommit
```

### Docker

```text
/docker help
/scaffold dockerfile
```

Docker scaffolding favors multi-stage builds and non-root runtime users where templates support it.

---

## 12. Project Scaffolding

```text
/init python
/init node
/init react
/init fastapi
/init django
/init rust
/init go
/init flask
/init express
/init nextjs
/init vue
/init svelte
/init electron
/init cli-tool
/init library
/template list
/upgrade
/readme
/scaffold dockerfile
/scaffold github-actions
/convert file.pdf
```

Use dry-run preview where supported:

```text
/init --dry-run fastapi
```

---

## 13. User Tools And MCP

### User Tools

```text
/tool new
/tool list
/tool info my_tool
/tool validate my_tool
/tool run my_tool arg1 arg2
/tool enable my_tool
/tool disable my_tool
/tool remove my_tool
/my_tool
```

Generated tools are validated before registration. The tool builder uses a reflection/retry loop when generated code fails validation.

### Built-In MCP-Style Tool Registry

```text
/mcp status
/mcp init
/mcp list
/mcp reload
/mcp call read_file {"path":"README.md"}
```

### Stdio MCP Servers

Configure servers in:

```text
~/.ilx_cli/mcp_servers.json
```

Example:

```json
{
  "filesystem": {
    "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
  }
}
```

Commands:

```text
/mcp servers status
/mcp servers example
/mcp servers connect
/mcp servers connect filesystem
/mcp servers tools
/mcp servers call filesystem__read_file {"path":"README.md"}
```

MCP stdio support is beta. Test each real MCP server before relying on it for production workflows.

---

## 14. One-Shot And Automation Mode

```bash
ilx --chat "explain this error"
ilx --code "fix failing tests" --yes
ilx --chat "summarize" --quiet
ilx --chat "summarize @README.md" --json
git diff | ilx --chat "write a commit summary"
```

Flags:

| Flag | Behavior |
|---|---|
| `--chat` | Run one chat prompt and exit |
| `--code`, `-c` | Run one code-agent task and exit |
| `--yes` | Auto-approve permission prompts |
| `--dry-run` | Preview behavior without writing |
| `--json` | Use machine-readable output path where supported |
| `--quiet` | Reduce decoration |
| `--no-color` | Disable color-oriented output |

Environment:

```bash
ILX_YES=1 ilx --code "run formatting"
```

Automation recommendation:

- Use `/permission ci` or `--yes` only in trusted workspaces.
- Keep `/sandbox workspace` enabled.
- Use `/allow` and `/deny` for predictable CI behavior.

---

## 15. Settings Reference

```text
/settings
/status
/version
/provider <name>
/model [name]
/models
/server <url>
/apikey set
/apikey get
/numctx 32768
/temperature 0.2
/top_p 0.9
/max_tokens 4096
/params
/cost
/rich on
/rich off
/no-color
```

### Rules Files

| File | Scope |
|---|---|
| `.ilx_rules.md` | Project rules |
| `.ilx_rules.local.md` | Personal project rules |
| `~/.ilx_cli/rules.md` | Global rules |

Commands:

```text
/rules
/rules edit
```

### Aliases

```text
/alias list
/alias set t /test
/alias remove t
```

---

## 16. Troubleshooting

### Ollama Is Not Running

```bash
ollama serve
```

Then:

```text
/healthcheck
/server http://localhost:11434
```

### Model Not Found

For Ollama:

```bash
ollama pull qwen2.5-coder:7b
```

In ILX:

```text
/models
/model qwen2.5-coder:7b
```

### API Key Error

```text
/provider openai
/apikey set
/apikey get
```

### Context Too Large

```text
/compact
/drop large_file.py
/context clear
/numctx 8192
```

### Permission Prompts Are Too Frequent

```text
/permission coding
/allow command pytest
/allow command ruff
```

### Tools Are Too Powerful

```text
/permission review
/sandbox read-only
/tools off
```

### Rich Output Looks Wrong

```text
/no-color
/rich off
```

Make sure the terminal is using UTF-8 if you want full box/Unicode rendering.

### Tests Fail Due To Live Model Quality

Some tests use a configured local/live model. For release gating, separate deterministic tests from provider-live/model-quality tests.

---

## 17. Full Command Reference

### Conversation

```text
/chat
/code
/paste
/clear
/undo
/compact
/history
/resume [N]
/session list
/session name <title>
/session search <query>
/export [file]
/copy
/quit
```

### Context

```text
/add <path>
/drop <path>
/context
/context stats
/context clear
/fetch <url>
/research <query>
/index build
/index status
/index explain <query>
/index clear
```

### Provider And Model

```text
/provider <ollama|anthropic|openai|groq|gemini|meta>
/model [name]
/models
/server <url>
/apikey set
/apikey get
/route status
/route explain
/route auto
/route free-only
/route local-only
/route quality
/route reset
```

### Coding Workflows

```text
/tools
/tools on
/tools off
/tools list
/plan <task>
/plan approve
/plan cancel
/review
/review staged
/review security
/review <file>
/fix-tests
/fix-tests --max <N>
/fix-tests --only <path>
```

### Safety

```text
/permission status
/permission list
/permission safe
/permission coding
/permission review
/permission ci
/permission locked
/perms
/sandbox status
/sandbox workspace
/sandbox read-only
/sandbox off --i-understand
/allow command <cmd>
/deny command <cmd>
/allowlist
```

### Audit And Diagnostics

```text
/audit
/audit full
/audit security
/audit quality
/audit deps
/audit compare
/audit replay [N|today]
/audit explain [N]
/audit export [file|--csv]
/audit diff
/metrics
/diag
/crashes
/crashes summary
/crashes clear
/errors
```

### Git

```text
/git status
/git diff
/git diff --staged
/git log
/git commit
/git commit -m "message"
/git ai-commit
/git pull
/git push
/git stash
/git stash pop
/git stash list
/git revert <hash>
/branch
/diff [file]
```

### Dev Tools

```text
/run <cmd>
/test [args]
/lint [args]
/format
/ci
/watch
/profile [script]
/build [entry]
/deps
/deps outdated
/env
/stats
/complexity
/deadcode
/bandit
/precommit
/tasks
/attach [task_id]
/kill [task_id]
/logs [N]
```

### Scaffolding And Files

```text
/workspace [path]
/rules
/rules edit
/init <template>
/init --dry-run <template>
/template list
/upgrade
/readme
/scaffold <type>
/scaffold dockerfile
/scaffold github-actions
/convert <file>
/docker help
```

### User Tools And MCP

```text
/tool new
/tool list
/tool info <name>
/tool validate <name>
/tool run <name> [args]
/tool enable <name>
/tool disable <name>
/tool remove <name>
/<registered-tool>
/mcp status
/mcp init
/mcp list
/mcp reload
/mcp call <tool> <json>
/mcp servers status
/mcp servers example
/mcp servers connect [name]
/mcp servers tools
/mcp servers call <server__tool> <json>
```

### Free/Local And Setup

```text
/free
/setup local
/benchmark
```

### Display And Misc

```text
/help
/help dev
/version
/settings
/status
/healthcheck
/temperature [value]
/top_p [value]
/max_tokens [value]
/numctx <tokens>
/params
/cost
/rich on
/rich off
/no-color
/alias list
/alias set <name> <command>
/alias remove <name>
/ssh <user@host>
/ssh help
```

---

## Beta Notes

ILX is currently suitable for controlled beta use and local-first workflows. Before using it on sensitive or production codebases:

- keep `/permission coding` or `/permission safe`,
- keep `/sandbox workspace`,
- use Git branches,
- review diffs,
- keep `/tools off` unless tool execution is needed,
- prefer local models for private code,
- run `/audit replay` after agent sessions.

Known beta limitations:

- OS-level command sandboxing is not complete across all platforms.
- MCP stdio support is still being hardened against real-world servers.
- Live model quality varies by configured model.
- Some output modes are still being applied command by command.

