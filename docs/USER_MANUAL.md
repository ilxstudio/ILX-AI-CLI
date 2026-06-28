# ILX AI CLI User Manual

Version: 1.0.0
Released: 2026-06-28

ILX AI CLI is a free, local-first AI developer CLI. It supports chat, code-agent workflows, file and command tools, repo context, project scaffolding, review, test repair, audit logging, model routing, persistent project memory, an interactive debug runner, and local/cloud provider switching.

This is the v1.0.0 public release. The tool is production-ready for local-first workflows. Features noted as beta — MCP stdio interoperability and OS-level process sandboxing — are functional but still being hardened against the full range of real-world environments.

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
9. Symbol Search And RAG Tuning
10. Persistent Project Memory
11. Interactive Debug Runner
12. Permissions, Sandbox, And Command Policies
13. Audit, Metrics, And Diagnostics
14. Git, Dev Tools, And Docker
15. Project Scaffolding
16. User Tools And MCP
17. One-Shot And Automation Mode
18. Settings Reference
19. Troubleshooting
20. Full Command Reference

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

- Python 3.12 or newer
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

The loop runs tests, parses failures, asks the model for targeted fixes, applies changes, and repeats until tests pass or the attempt limit is reached. Each fix is recorded in project memory (see Section 10) for future reference.

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

The repo index powers semantic search, symbol lookup, and retrieval-oriented workflows. Run `/index build` after setting a workspace, and again when files change significantly.

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

## 9. Symbol Search And RAG Tuning

### Symbol Search

After running `/index build`, you can search for symbols — functions, classes, and identifiers — directly by name:

```text
/symbol validate_token
/symbol AuthMiddleware
/symbol process_order
```

Results show the symbol name, kind (py/ts/js), and file path:

```text
Symbols matching 'validate':

  py      validate_token              src/auth.py
  py      validate_card_number        src/payments/validator.py
  py      validate_order_total        src/orders/checkout.py
```

Symbol search requires an up-to-date index. If the index is empty, ILX will prompt you to run `/index build` first.

### RAG Tuning

The `/rag` command exposes the retrieval weights used by the hybrid pipeline. You can tune these for your codebase's characteristics:

```text
/rag status
```

Shows current weights:

```text
RAG Thresholds
  BM25 weight    : 0.60
  Semantic weight: 0.75
```

Set a new BM25 weight (favors exact keyword and identifier matches):

```text
/rag bm25 0.8
```

Set a new semantic weight (favors conceptual and paraphrase matches):

```text
/rag semantic 0.5
```

Values must be between 0.0 and 1.0. Settings are persisted across sessions. For codebases with many exact identifier references (e.g. Python with consistent naming), a higher BM25 weight tends to improve precision. For codebases where questions are phrased conceptually, a higher semantic weight is preferable.

---

## 10. Persistent Project Memory

Project memory stores facts, fix decisions, and symbol records across all sessions. Unlike conversation history, which is per-session and subject to context limits, project memory is persistent, searchable, and available to every future session in the same workspace.

Memory is stored in `.ilx_cli/memory.db` under the workspace root. You can commit this file to version control to share project knowledge with your team, or add it to `.gitignore` for personal-only use.

### Storing And Retrieving Facts

Add a fact:

```text
/memory add <key> <value>
```

Example:

```text
/memory add auth-token-ttl "access tokens expire in 15 minutes; refresh tokens expire in 7 days"
/memory add db-engine "PostgreSQL 16, connection pool size 20, pgBouncer in transaction mode"
/memory add test-command "pytest --tb=short -q; coverage threshold 80%"
```

Show all stored facts:

```text
/memory show
```

Show facts matching a filter:

```text
/memory show auth
```

### Forgetting Facts

Delete all facts with a specific key:

```text
/memory forget auth-token-ttl
```

Confirmation is shown with the count of records deleted.

### Fix History

The `/fix-tests` loop and the code agent write fix records automatically. To view them:

```text
/memory fixes
```

To view fixes for a specific file:

```text
/memory fixes src/auth.py
```

Output shows the date, file, outcome (success or failure), the problem description, and the solution applied. This history helps avoid repeating past mistakes and provides context when revisiting difficult areas of the codebase.

### Searching Memory

Search across both facts and the symbol index:

```text
/memory search <query>
```

Example:

```text
/memory search token
```

Output:

```text
Facts matching 'token':
  auth-token-ttl  access tokens expire in 15 minutes; refresh tokens expire in 7 days

Symbols matching 'token':
  function   validate_token      src/auth.py
  function   refresh_token       src/auth.py
  class      TokenBlacklist      src/auth.py
```

### Memory Statistics

```text
/memory stats
```

Output:

```text
Project Memory Stats
  Facts     12
  Fixes     34
  Symbols   1,847
  DB size   248 KB
  /home/user/projects/my-api/.ilx_cli/memory.db
```

### Summary Of Memory Subcommands

| Subcommand | Description |
|---|---|
| `/memory show [query]` | List stored facts, optionally filtered |
| `/memory add <key> <value>` | Store a fact |
| `/memory forget <key>` | Delete facts with this key |
| `/memory fixes [file]` | Show past fix decisions |
| `/memory search <query>` | Search facts and symbols |
| `/memory stats` | Show database statistics |

---

## 11. Interactive Debug Runner

The debug runner lets you run Python scripts interactively inside ILX with full stdin passthrough. All output is captured and logged. When errors occur, one command sends the error context to the active model for analysis.

### Running A Script

```text
/debug <script.py> [args...]
```

Example:

```text
/debug src/process_orders.py --env staging
```

ILX shows:

```text
Debug: src/process_orders.py --env staging
  Session : debug_20260628_143201
  Python  : .venv/bin/python
  Log     : ~/.ilx_cli/debug/debug_20260628_143201.log
  Type input when prompted. Ctrl+C to stop.
```

- Standard input from your terminal is passed directly to the running script.
- Standard output is shown in white.
- Standard error is shown in red.
- System messages (start, exit code, elapsed time) are shown in dim text.

If the workspace contains a `.venv` or `venv` directory, that environment's Python is used automatically.

When the script exits:

```text
  Exited 1  2.3s
  Log saved: ~/.ilx_cli/debug/debug_20260628_143201.log
  1 error line(s) detected.
  Run /debug analyze to get AI suggestions for these errors.
```

### Viewing The Log

Show the output from the last debug session:

```text
/debug log
```

This displays the last 80 lines of the session log, color-coded by stream type (stdout, stderr, stdin, system).

### Listing Recent Sessions

```text
/debug logs
```

Output:

```text
Recent debug sessions:

  debug_20260628_143201  12 KB  — /debug analyze debug_20260628_143201
  debug_20260628_110045  4 KB   — /debug analyze debug_20260628_110045
  debug_20260627_172233  8 KB   — /debug analyze debug_20260627_172233
```

### AI Error Analysis

Analyze errors from the last session:

```text
/debug analyze
```

Analyze errors from a specific session:

```text
/debug analyze debug_20260628_143201
```

ILX extracts relevant error lines (tracebacks, exception messages, file references), constructs a structured prompt with the command, exit code, user input, and error context, and submits it to the active model. The response includes a specific diagnosis and fix: corrected code, a `pip install` command, or a configuration change — with file and line number references where visible.

Example output:

```text
Analyzing session: debug_20260628_143201

AI Analysis:
  The error occurs at process_orders.py line 87. The orders list contains
  records where the "amount" field is None. The fix is to filter or coerce:

      total = sum(o["amount"] or 0 for o in orders)

  If None is unexpected, add a validation step when loading orders to surface
  the root cause earlier.

  Run /debug debug_20260628_143201 again after applying the fix.
```

If the model cannot be reached (e.g. Ollama is not running), ILX shows the error and suggests checking `/status` or switching providers with `/provider`.

### Summary Of Debug Subcommands

| Subcommand | Description |
|---|---|
| `/debug <script.py> [args]` | Run interactively with stdin passthrough |
| `/debug log` | Show output from the last session |
| `/debug logs` | List recent debug sessions |
| `/debug analyze` | AI analysis of errors from the last session |
| `/debug analyze <id>` | AI analysis of a specific session by ID |

---

## 12. Permissions, Sandbox, And Command Policies

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

## 13. Audit, Metrics, And Diagnostics

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

## 14. Git, Dev Tools, And Docker

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

## 15. Project Scaffolding

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

## 16. User Tools And MCP

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

## 17. One-Shot And Automation Mode

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

## 18. Settings Reference

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

## 19. Troubleshooting

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

### Index Is Empty After /index build

Verify the workspace is set correctly:

```text
/status
/workspace D:\Projects\my-app
/index build
```

If the workspace contains only files with unsupported extensions, the index will report zero files. Supported extensions include `.py`, `.js`, `.ts`, `.md`, `.json`, `.yaml`, `.toml`, and most common source file types.

### /symbol Returns No Results

The symbol index is populated during `/index build`. If you have added new files since the last build, run `/index build` again. Symbol search is case-insensitive substring matching — if you are not finding a symbol, try a shorter or partial name.

### /debug analyze Shows No Errors

If the program exited cleanly (exit code 0) and produced no traceback or error-pattern output, `/debug analyze` will report that the session appears clean. If errors were written to a file rather than stderr, the log may not capture them. Check `/debug log` for the raw session output.

### Tests Fail Due To Live Model Quality

Some tests use a configured local/live model. For release gating, separate deterministic tests from provider-live/model-quality tests.

---

## 20. Full Command Reference

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
/index build <path>
/index status
/index explain <query>
/index clear
```

### Symbol And RAG

```text
/symbol <name>
/rag status
/rag bm25 <0.0-1.0>
/rag semantic <0.0-1.0>
```

### Project Memory

```text
/memory show [query]
/memory add <key> <value>
/memory forget <key>
/memory fixes [file]
/memory search <query>
/memory stats
```

### Debug Runner

```text
/debug <script.py> [args...]
/debug log
/debug logs
/debug analyze
/debug analyze <session_id>
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

## Production Use Notes

ILX AI CLI v1.0.0 is suitable for production use in local-first workflows. Before using it on sensitive or production codebases:

- keep `/permission coding` or `/permission safe`,
- keep `/sandbox workspace`,
- use Git branches,
- review diffs before committing,
- keep `/tools off` unless tool execution is needed,
- prefer local models for private code,
- run `/audit replay` after agent sessions,
- use `/memory` to preserve institutional knowledge across sessions.

Known limitations in this release:

- OS-level command sandboxing is not complete across all platforms. The sandbox enforces workspace path policy but does not use OS-level process isolation (namespaces, seccomp, AppContainer).
- MCP stdio support is still being hardened against real-world servers.
- The debug runner currently supports Python scripts only; Node.js and other runtimes are planned.
- Some output formatting modes are still being applied command by command rather than globally.

MIT License. Copyright 2026 ILX Studio, LLC.
