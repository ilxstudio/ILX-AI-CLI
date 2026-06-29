# ILX AI CLI

[![CI](https://github.com/ilxstudio/ilx-ai-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/ilxstudio/ilx-ai-cli/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/ilx-ai-cli?color=blue)](https://pypi.org/project/ilx-ai-cli/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Coverage](https://img.shields.io/badge/coverage-85%25-brightgreen)](https://github.com/ilxstudio/ilx-ai-cli/actions)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/ilxstudio/ilx-ai-cli/releases/tag/v1.0.0)

**Free. Open source. No subscriptions. No vendor lock-in. Works with any LLM — local or cloud.**

Run a full-featured AI coding assistant entirely on your machine using Ollama and Llama 3, Qwen, or Mistral.
Switch to Gemini, GPT-4o, or Groq in one command when you need more firepower.
Your keys, your models, your data — none of it touches a third-party server unless you say so.

This is the coding assistant that terminal developers actually want: persistent project memory,
an interactive debug runner with AI error analysis, audit logs, sandbox controls,
a real code-agent loop, test-fix automation, and MCP tool support — without a monthly bill or an IDE.

---

## Why ILX AI CLI Instead of the Others?

You have options. Here is why developers who try ILX tend to stop looking.

### The short version

Every mainstream AI coding tool either costs money, requires an IDE, locks you to one provider,
or ships your code to a vendor's server. ILX does none of those things.

### Comparison

| Feature | ILX AI CLI | GitHub Copilot | Cursor | Aider | OpenHands |
|---|:---:|:---:|:---:|:---:|:---:|
| Free and open source | Yes | No | No | Yes | Yes |
| Local / offline mode | Yes | No | No | Partial | No |
| Multi-provider (swap freely) | Yes | No | Partial | Yes | Partial |
| Terminal native (no IDE) | Yes | No | No | Yes | No |
| Code review mode | Yes | No | Partial | No | No |
| Automated test-fix loop | Yes | No | No | Partial | Yes |
| Persistent project memory | Yes | No | No | No | No |
| Interactive debug runner | Yes | No | No | No | No |
| Permission and sandbox controls | Yes | No | No | No | Partial |
| Audit logging (JSONL) | Yes | No | No | No | No |
| MCP tool support | Yes | No | No | No | No |
| No IDE required | Yes | No | No | Yes | No |

### Why not Aider?

Aider is solid. It pioneered the edit-loop pattern. ILX adds: persistent project memory,
an interactive debug runner with AI error analysis, permission profiles,
sandbox containment, a semantic codebase index, MCP tool integration, a test-fix loop,
project scaffolding, Docker scaffolding, audit replay, and multi-provider routing — all in one REPL.

### Why not Cursor?

Cursor is a fork of VS Code. If you live in the terminal, it is the wrong tool.
It requires a subscription for the models that matter and does not support local models for most workflows.

### Why not GitHub Copilot?

Copilot is autocomplete with a chat tab bolted on. It has no code-agent loop, no test automation,
no audit trail, no permission model, and no local mode. It costs money every month.

### Why not OpenHands?

OpenHands runs in Docker and in a browser UI. It is impressive for agent tasks but
requires a container runtime, has no terminal REPL, and does not give you the per-command
granularity that production engineers need when they want to know exactly what the AI touched.

---

## Privacy and Local-First Operation

When you run ILX with an Ollama provider, nothing leaves your machine.

- No telemetry. No usage analytics. No call-home.
- Model inference runs on your hardware via Ollama.
- File reads, patches, and test runs are local processes.
- API keys, when used, are stored in the OS keychain — not in config files.
- The audit log records what happened locally. You control it.

The `/free` command shows you the current mode and which operations, if any, would touch a network.
The `/route local-only` and `/route free-only` commands enforce that nothing goes to a cloud provider.

---

## Installation

### From PyPI (recommended)

```bash
pip install ilx-ai-cli
ilx
```

> **Linux:** If `ilx` is not found after install, add `~/.local/bin` to your PATH:
> ```bash
> echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
> ```

### From Source

```bash
git clone https://github.com/ilxstudio/ilx-ai-cli
cd ilx-ai-cli
pip install -e ".[all]"
python main.py
```

### Requirements

- Python 3.12 or later
- Windows, macOS, or Linux
- Ollama (optional but recommended for local/free operation)

### Optional extras

```bash
pip install "ilx-ai-cli[all]"      # everything
pip install "ilx-ai-cli[pdf]"      # PDF file support
pip install "ilx-ai-cli[docx]"     # Word document support
pip install "ilx-ai-cli[xlsx]"     # Spreadsheet support
pip install "ilx-ai-cli[image]"    # Image file support
```

---

## Quick Start

### Zero-config local session (no API key, no cost)

Pull a local model with Ollama, then start ILX:

```bash
ollama pull qwen2.5-coder:7b
pip install ilx-ai-cli
ilx
```

```
ILX AI CLI v1.0.0 — type /help for commands
[ollama/qwen2.5-coder:7b] > /workspace ~/projects/my-api
Workspace set: /home/user/projects/my-api (42 files indexed)

[ollama/qwen2.5-coder:7b] > explain the auth flow in @src/auth.py
Reading src/auth.py (187 lines)...

The module uses JWT with a rotating secret. Tokens are issued at /auth/login,
validated by a middleware decorator, and refreshed via /auth/refresh. The
blacklist is an in-memory set — not suitable for multi-process deployments.

[ollama/qwen2.5-coder:7b] > _
```

### Switch to cloud when you need it

```
[ollama/qwen2.5-coder:7b] > /provider gemini
Provider set: gemini

[gemini/gemini-2.5-pro] > /apikey set
Enter API key: ****
Key stored in OS keychain.

[gemini/gemini-2.5-pro] > _
```

### Non-interactive (CI / scripting)

```bash
ilx --chat "explain main.py" --file main.py --quiet
ilx --code "add unit tests for src/auth.py" --yes
git diff | ilx --chat "summarize this diff" --quiet
ilx --chat "list risks in this file @app.py" --json
```

---

## Core Workflows

### Chat mode

Ask questions about your codebase. Add files to context. Summarize and continue.

```
[ollama/qwen2.5:14b] > /chat
Chat mode active.

[ollama/qwen2.5:14b] > /add src/payments/validator.py
Added src/payments/validator.py to context (3,241 tokens)

[ollama/qwen2.5:14b] > what edge cases are we missing in the card validator?
Analyzing validator.py...

Missing edge cases:
  1. Luhn check is skipped when card length < 13 — attacker could pass
     a 12-digit number with any last digit.
  2. Expiry comparison uses local time, not UTC — fails across midnight
     in some timezones.
  3. CVV length is hardcoded to 3; Amex uses 4.

[ollama/qwen2.5:14b] > /compact
Conversation summarized. Context freed.

[ollama/qwen2.5:14b] > _
```

### Code agent mode

The agent reads files, edits code, runs commands, and iterates — with your approval at each step.

```
[ollama/qwen2.5-coder:7b] > /code
Code agent mode active. Tools: on

[ollama/qwen2.5-coder:7b] > refactor the CSV parser and add tests
Planning...
  1. Read src/csv_parser.py
  2. Identify refactoring opportunities
  3. Write refactored version
  4. Generate tests in tests/test_csv_parser.py
  5. Run pytest

Approve plan? [Y/n]: y

[read] src/csv_parser.py ... done
[edit] src/csv_parser.py ... done
[write] tests/test_csv_parser.py ... done
[exec] pytest tests/test_csv_parser.py -q
  5 passed in 0.43s

Done. 3 files changed, 47 lines added.

[ollama/qwen2.5-coder:7b] > _
```

### Persistent project memory

ILX remembers facts, decisions, and fix history across sessions. No need to re-explain your
project conventions every time.

```
[ollama/qwen2.5-coder:7b] > /memory add auth-token-ttl "access tokens expire in 15 minutes, refresh in 7 days"
Remembered: auth-token-ttl = access tokens expire in 15 minutes, refresh in 7 days

[ollama/qwen2.5-coder:7b] > /memory show
Project Memory  (3 facts)

  2026-06-28  fact    auth-token-ttl  access tokens expire in 15 minutes, refresh in 7 days
  2026-06-27  fact    db-engine       PostgreSQL 16, connection pool size 20
  2026-06-25  fix     src/auth.py     CVV hardcoded to 3 digits — corrected to length check

[ollama/qwen2.5-coder:7b] > /memory search auth
Facts matching 'auth':
  auth-token-ttl  access tokens expire in 15 minutes, refresh in 7 days

Symbols matching 'auth':
  function   validate_token   src/auth.py
  class      AuthMiddleware   src/auth.py
```

### Interactive debug runner

Run any Python script interactively inside ILX. Standard input passes through to the process.
All output is captured and logged. When the program exits with an error, one command sends
the error output to the active model for analysis.

```
[ollama/qwen2.5-coder:7b] > /debug src/process_orders.py --env staging
Debug: src/process_orders.py --env staging
  Session : debug_20260628_143201
  Python  : .venv/bin/python
  Log     : ~/.ilx_cli/debug/debug_20260628_143201.log

  Connecting to staging database...
  Loaded 1,204 orders.
  Processing batch 1...
  Traceback (most recent call last):
    File "src/process_orders.py", line 87, in process_batch
      total = sum(o["amount"] for o in orders)
  TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'

  Exited 1  2.3s
  Log saved: ~/.ilx_cli/debug/debug_20260628_143201.log
  1 error line(s) detected.
  Run /debug analyze to get AI suggestions for these errors.

[ollama/qwen2.5-coder:7b] > /debug analyze
Analyzing session: debug_20260628_143201

AI Analysis:
  The error occurs at process_orders.py line 87. The orders list contains
  records where the "amount" field is None. The fix is to filter or coerce:

      total = sum(o["amount"] or 0 for o in orders)

  If None is unexpected, add a validation step when loading orders to surface
  the root cause earlier.
```

### Plan, review, then act

```
[ollama/qwen2.5-coder:7b] > /plan add rate limiting to the API
Generating plan...

Step 1: Add slowapi dependency to pyproject.toml
Step 2: Initialize limiter in app/__init__.py
Step 3: Apply @limiter.limit decorator to /auth/login, /api/search
Step 4: Add 429 error handler with Retry-After header
Step 5: Add tests in tests/test_rate_limiting.py

Review the plan:
  /plan approve   — execute all steps
  /plan edit      — modify before executing
  /plan cancel    — discard

[ollama/qwen2.5-coder:7b] > /plan approve
Executing...
```

### Code review

```
[ollama/qwen2.5:14b] > /review staged
Reviewing 3 staged files...

src/auth.py
  LINE 47  — bcrypt.checkpw called with string, not bytes. This will raise
             TypeError at runtime on Python 3.12+.
  LINE 83  — JWT expiry is set to 30 days. Consider 15 minutes + refresh.

src/api/users.py
  LINE 112 — SQL query uses f-string interpolation. Use parameterized queries.

src/tests/test_auth.py
  No issues found.

2 files with findings. Run /review security for a deeper pass.

[ollama/qwen2.5:14b] > _
```

### Automated test-fix loop

```
[ollama/qwen2.5-coder:7b] > /fix-tests
Running pytest...
  12 passed, 3 failed

Fixing failures...

  FAIL tests/test_validator.py::test_amex_cvv
  Root cause: CVV length check hardcoded to 3
  Fix: src/payments/validator.py line 34 — updated length check
  Re-run: PASS

  FAIL tests/test_auth.py::test_token_expiry
  Root cause: comparison uses local time
  Fix: src/auth.py line 83 — switched to datetime.utcnow()
  Re-run: PASS

  FAIL tests/test_csv.py::test_empty_file
  Root cause: IndexError on empty input
  Fix: src/csv_parser.py line 12 — added early return
  Re-run: PASS

All tests passing. 15 passed in 1.2s.

[ollama/qwen2.5-coder:7b] > _
```

### Semantic codebase index and research

```
[ollama/qwen2.5:14b] > /index build
Indexing workspace: ~/projects/my-api
  Files: 87   Chunks: 1,204   Embeddings: done

[ollama/qwen2.5:14b] > /research "how does the retry logic work?"
Searching index...

Relevant files:
  src/http_client.py:42   — RetryConfig dataclass, max_retries, backoff_factor
  src/http_client.py:89   — _retry_request() with exponential backoff
  tests/test_http.py:201  — tests for retry on 429 and 503

Summary: HTTP client uses exponential backoff with jitter. Default is
3 retries, 0.5s base delay, max 30s. 5xx errors retry; 4xx (except 429)
do not. 429 respects Retry-After header when present.

[ollama/qwen2.5:14b] > _
```

---

## All Commands

### Model and provider

```text
/provider <name>           switch provider: ollama, anthropic, openai, groq, gemini
/model <name>              set active model (e.g. qwen2.5-coder:7b, gpt-4o, llama3.3)
/models                    list available models for current provider
/apikey set                store API key in OS keychain
/apikey get                show masked key status
/route auto                route tasks by capability automatically
/route free-only           block all paid/cloud calls
/route local-only          block all network model calls
/route quality             always use highest-quality configured model
/benchmark [quick|full]    benchmark current model for speed and quality
```

### Modes

```text
/chat                      enter conversational chat mode
/code                      enter code-agent mode (file tools active)
```

### Context and files

```text
/workspace <path>          set project workspace root
/add <file>                add file to conversation context
/index [build|status|clear] manage semantic codebase index
/index explain <query>     search index and show scored results
/research <question>       search indexed codebase with a question
/symbol <name>             search the symbol index for matching names
/rag status                show current RAG retrieval weights
/rag bm25 <0.0-1.0>        set BM25 retrieval weight
/rag semantic <0.0-1.0>    set semantic similarity weight
/context                   show current context window usage
/compact                   summarize conversation to free context window
/export                    export conversation to file
```

### Project memory

```text
/memory show [query]       list stored facts, optionally filtered
/memory add <key> <value>  remember a fact for this project
/memory forget <key>       delete facts with the given key
/memory fixes [file]       show past fix decisions
/memory search <query>     search across all facts and symbols
/memory stats              show memory database statistics
```

### Debug runner

```text
/debug <script.py> [args]  run a script interactively with stdin passthrough
/debug log                 show output from the last debug session
/debug logs                list recent debug sessions
/debug analyze             AI analysis of errors from the last session
/debug analyze <id>        AI analysis of a specific session by ID
```

### Planning and execution

```text
/plan <task>               generate and review a step-by-step plan
/plan approve              execute the current plan
/plan cancel               discard the current plan
```

### Review and testing

```text
/review                    review current working changes
/review staged             review git staged files
/review security           security-focused review pass
/review <file>             review a specific file
/fix-tests [--max N]       run tests, auto-fix failures, repeat up to N rounds
/fix-tests --only <path>   restrict fix-tests to a specific test file or directory
```

### Safety and permissions

```text
/permission status         show current permission profile
/permission list           list all profiles
/permission safe           activate conservative read-only profile
/permission coding         activate standard coding profile
/permission review         activate review-only profile
/permission ci             activate CI-safe profile
/permission locked         lock down all file write and exec
/sandbox status            show sandbox containment mode
/sandbox workspace         contain to workspace directory
/sandbox read-only         no writes allowed
/sandbox off --i-understand disable sandboxing (you accept the risk)
/allow command <cmd>       add command to allowlist
/deny command <cmd>        add command to denylist
/allowlist                 show current allow and deny lists
```

### Audit and observability

```text
/audit                     run full audit of current workspace state
/audit security            security-focused audit pass
/audit quality             code quality audit
/audit deps                dependency audit (known CVEs, outdated)
/audit replay              replay the session audit log
/audit explain             explain each logged event in plain language
/audit export --csv        export audit log to CSV
/audit diff                show audit diff from last session
/metrics                   show session metrics: tokens, calls, cost estimate
/status                    show full current configuration
/free                      show local/free mode status and what would go to network
```

### Git

```text
/git status                git status in workspace
/git diff                  git diff in workspace
/git ai-commit             generate AI commit message from staged diff
/git push                  push current branch
/branch                    list or switch branches
```

### Scaffolding and project setup

```text
/init python               scaffold a Python project structure
/init fastapi              scaffold a FastAPI project
/init react                scaffold a React project
/template list             list available project templates
/scaffold dockerfile       generate a Dockerfile for current project
/readme                    generate or update README from codebase
/upgrade                   check for ILX CLI updates
```

### MCP tools

```text
/mcp init                  initialize MCP tool registry
/mcp list                  list all registered MCP tools
/mcp call <tool> <json>    call an MCP tool directly
/mcp servers status        show connected MCP stdio servers
/mcp servers connect       connect to an MCP stdio server
/mcp servers tools         list tools from connected servers
/mcp servers call <t> <j>  call a tool on a connected server
```

### User-defined tools

```text
/tool new                  create a new user-defined tool
/tool list                 list user-defined tools
/tool validate <name>      validate a tool definition
/tool run <name> --help    run a tool with help output
/tool remove <name>        remove a user-defined tool
```

### Rules and configuration

```text
/rules                     view active project rules
/rules edit                open rules file for editing
/help                      show full command list
```

---

## Providers

| Provider | Notes |
|---|---|
| `ollama` | Runs locally. Free. Supports Llama 3, Qwen, Mistral, Phi, Gemma, DeepSeek, and any Ollama-compatible model. |
| `openai` | GPT-4o, o3-mini, and other OpenAI models. BYO API key. |
| `anthropic` | Frontier-class language models. BYO API key. Prompt caching supported. |
| `groq` | Fast inference on open-weight models (Llama 3, Mixtral). BYO API key. |
| `gemini` | Gemini models including free-tier access. BYO API key. |

API keys are stored in the OS keychain where supported. They are never written to config files on disk.

---

## Safety and Sandboxing

ILX is built for real codebases and real consequences. The permission and sandbox system exists
so you can let the agent run further without babysitting every keystroke — while still having
a clear record of what it did.

Current sandbox modes control path containment and prevent writes or execs outside the workspace.
Full OS-level process isolation (namespaces, seccomp) is on the roadmap. For now: review commands
before approving network access or exec outside your workspace, especially on untrusted code.

---

## Audit Log

Every session writes a JSONL audit log under `~/.ilx_cli`. The log records:

- File reads and writes (path, byte count, hash)
- Permission decisions (approved, denied, auto-approved)
- Commands executed (command, exit code, stdout truncated)
- Model calls (provider, model, token counts, latency)
- Network requests (URL, method, status)

Secret-shaped fields are redacted before writing. The log never leaves your machine.

---

## Project Rules

Rules files let you inject standing instructions into every prompt — project conventions,
style guides, off-limit patterns, team preferences.

| File | Scope |
|---|---|
| `.ilx_rules.md` | Project rules. Commit this to your repo. |
| `.ilx_rules.local.md` | Personal overrides. Add to `.gitignore`. |
| `~/.ilx_cli/rules.md` | Global rules applied to every workspace. |

---

## Once You Learn It, You Do Not Need Another Tool

The proposition is simple: ILX is the last AI coding tool you add to your terminal workflow.

- You do not switch tools when you switch models. `/provider` and `/model` handle it.
- You do not switch tools when you go offline. Ollama keeps running.
- You do not switch tools for review vs. chat vs. code-agent. `/review`, `/chat`, `/code` are modes.
- You do not switch tools when you need to check what the AI did. `/audit replay` shows everything.
- You do not switch tools when you move to a new project. `/workspace` and `/index build` take 10 seconds.
- You do not re-explain project context every session. `/memory` persists what matters.
- You do not lose debug context between runs. `/debug` logs everything and `/debug analyze` explains it.

The learning cost is one REPL, one set of slash commands, and one mental model. The payoff
is a consistent, auditable, provider-agnostic AI assistant that works in every project and every
environment you deploy to.

---

## Development and Testing

Run the test suite:

```bash
pip install -e ".[dev,all]"
python -m pytest tests -q
```

Current coverage: 85%. The test suite covers all core workflows, provider adapters,
permission and sandbox logic, the RAG pipeline, project memory, and the debug runner.

Live provider/model tests should be gated from CI runs where no API keys are present.

---

## Community and Contributing

ILX AI CLI is MIT-licensed and community-driven. We want your pull requests,
your bug reports, your model recommendations, and your workflow ideas.

**Getting involved:**

- Report bugs and request features: [GitHub Issues](https://github.com/ilxstudio/ilx-ai-cli/issues)
- Read the full command guide: [docs/USER_MANUAL.md](docs/USER_MANUAL.md)
- Submit pull requests: fork the repo, branch off `main`, open a PR with a clear description
- Test with local models: the more models people test, the better the routing and prompting get

**Contribution areas most needed right now:**

- OS-level sandbox support (Linux namespaces, macOS sandbox-exec, Windows AppContainer)
- Additional project scaffold templates
- MCP server integrations and tool definitions
- Embedding model coverage for codebase indexing
- Test coverage for edge cases in provider adapters

All contributors retain credit in the changelog. There is no CLA.

---

## License

MIT License. Copyright 2026 ILX Studio, LLC. See [LICENSE](LICENSE) for the full text.

This software is provided as-is. Use it in production at your own judgment.
The audit log and permission system exist precisely because AI agents make mistakes —
keep them engaged and review what the agent proposes before approving destructive operations.
