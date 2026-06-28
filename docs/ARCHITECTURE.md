# ILX AI CLI — Architecture

## Overview

The application is organised in three horizontal layers. Each layer has a
single responsibility and dependencies only flow downward.

```
┌─────────────────────────────────────────────────────┐
│  cli/            Command dispatch + REPL            │
├─────────────────────────────────────────────────────┤
│  app/core/       Core services                      │
├─────────────────────────────────────────────────────┤
│  codex/app/      LLM client layer                   │
└─────────────────────────────────────────────────────┘
```

---

## Layer 1 — `cli/` (Command Dispatch and REPL)

**Owns:** everything the user touches directly.

| Module | Responsibility |
|--------|----------------|
| `cli/app.py` | Application shell — starts the REPL loop |
| `cli/command_registry.py` | Maps `/command` names to handler classes |
| `cli/chat_session.py` | Interactive chat loop, history management |
| `cli/code_session.py` | Coding-agent REPL variant |
| `cli/plan_session.py` | Plan generation and approval flow |
| `cli/oneshot.py` | Non-interactive `--chat` / pipe mode |
| `cli/display.py` | Text rendering helpers (diff, cost, HR) |
| `cli/display_compat.py` | Output mode adapter (ansi / json / quiet) |
| `cli/rich_display.py` | Rich-terminal output mode selection |
| `cli/commands/` | One file per command group (`/review`, `/fix-tests`, …) |

**Rules:**
- May import from `app/core/` and `codex/app/`.
- Must not be imported by `app/core/` or `codex/app/`.

---

## Layer 2 — `app/core/` (Core Services)

**Owns:** business logic that has no direct dependency on the LLM client.

| Module | Responsibility |
|--------|----------------|
| `audit.py` | Append-only JSON audit log with automatic rotation |
| `config.py` | `AppConfig` dataclass + `ConfigManager` persistence |
| `permissions.py` | Permission engine — ask / auto / deny modes |
| `process_runner.py` | Centralised `subprocess.run` wrapper (never `shell=True`) |
| `supervisor.py` | Long-running child-process lifecycle manager |
| `executor.py` | Queued file and command operations |
| `git_helper.py` | Git porcelain wrappers |
| `web_fetch.py` | SSRF-guarded URL fetcher |
| `research_fetcher.py` | Web research orchestrator |
| `hybrid_retriever.py` | BM25 + symbol index for codebase Q&A |
| `secret_store.py` | OS keychain adapter |
| `error_classifier.py` | Categorises LLM and tool errors |
| `reflexion.py` | Self-critique loop for multi-step tasks |
| `crash_db.py` | Local crash record store |
| `hooks.py` | Extension hooks for pre/post-command actions |

**Rules:**
- May import from `codex/app/` for LLM calls.
- Must not import from `cli/`.

---

## Layer 3 — `codex/app/` (LLM Client Layer)

**Owns:** all communication with the language model.

| Module | Responsibility |
|--------|----------------|
| `llm_client.py` | Public factory: `get_llm_client()` |
| `llm_client_base.py` | `BaseLLMClient` abstract interface |
| `llm_client_providers.py` | Provider-specific clients (Ollama, …) |
| `llm_client_ext.py` | Extended capabilities (vision, streaming) |
| `controller.py` | Single-turn chat orchestration |
| `controller_streaming.py` | Streaming response handler |
| `prompt_builder.py` | System and user prompt assembly |
| `response_parser.py` | Parse LLM output into structured data |
| `runner.py` | Coding-agent action loop |
| `chunker.py` | Token-safe text chunker |
| `memory.py` | Conversation memory window |
| `workspace.py` | Workspace context collector |
| `validator.py` | Validate LLM-produced actions before execution |
| `logger.py` | Structured request/response logging |

**Rules:**
- Must not import from `cli/`.
- Must not import from `app/core/` except for `audit`, `config`, and
  `process_runner` (read-only use of shared infrastructure).

---

## Data Flow — Chat Request

```
User input
   │
   ▼
cli/chat_session.py          build_message()
   │
   ▼
codex/app/controller.py      chat(messages, cfg)
   │
   ├─► codex/app/prompt_builder.py   assemble system prompt
   ├─► codex/app/memory.py           trim history to token window
   ├─► codex/app/llm_client.py       HTTP call → Ollama / other
   └─► codex/app/response_parser.py  extract text / tool calls
   │
   ▼
cli/display.py               render_chat_response()
   │
   ▼
Terminal
```

## Data Flow — Coding-Agent Action

```
LLM proposes action (file write / command)
   │
   ▼
codex/app/validator.py        validate action fields
   │
   ▼
app/core/permissions.py       request_permission(operation)
   │  ├─ denylist / allowlist check
   │  ├─ sandbox enforcement
   │  └─ user prompt (ASK mode)
   │
   ▼
app/core/executor.py          apply_operation()
   │  ├─ FileOperation  → writes via Path.write_text()
   │  └─ CommandOperation → app/core/process_runner.run()
   │
   ▼
app/core/audit.py             log_event("file_op" | "command_exec")
```

---

## Module Ownership Rules

1. `cli/` is the **only** layer allowed to call `input()` or `print()` directly.
2. All subprocess calls outside `process_runner.py` and `supervisor.py` are
   prohibited in production code. Use `process_runner.run()` instead.
3. Hardcoded filesystem paths (`C:\`, `/home/`, etc.) are banned. Use
   `Path.home()`, `sys.executable`, or values from `AppConfig`.
4. `shell=True` is banned everywhere.
5. No file may exceed 700 lines.
6. All new classes follow the single-responsibility principle — one class per
   concern.

---

## Configuration

`AppConfig` (defined in `app/core/config.py`) is the single source of truth
for all runtime configuration. `ConfigManager` loads it from
`~/.ilx_cli/config.json` and persists changes back. It is passed by reference
to every layer that needs it; nothing reads environment variables directly in
business logic.

## Audit Log

Every significant operation writes a JSON line to
`~/.ilx_cli/logs/audit.log`. The log rotates at 5 MB and keeps the last five
rotations. Secret-shaped field values are redacted before writing. See
`app/core/audit.py` for the full schema.

## License

MIT License — Copyright 2026 ILX Studio
