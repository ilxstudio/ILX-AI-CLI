# ILX AI CLI v1.0.0 — Launch Posts

Copyright 2026 ILX Studio. MIT License.

---

## Reddit Post

**Title:** I built a free, local-first AI coding assistant that runs entirely in the terminal — no IDE, no cloud required

---

I got tired of every AI coding tool assuming you want a GUI, a subscription, or to pipe your source code through someone else's servers. So I built ILX AI CLI: a terminal REPL for AI-assisted coding that defaults to running completely on your machine via Ollama, with zero data leaving unless you explicitly opt into a cloud provider.

The core idea is simple. You open a terminal, run `ilx`, and you get a persistent session with slash commands for the things you actually do: `/chat` for conversation, `/code` for an agentic loop that reads and edits files, `/review` for code review, `/plan` for breaking down tasks, `/test` for a test-fix loop, `/debug` for running programs interactively with stdin passthrough and AI error analysis on failures, and `/research` for pulling in external context. There is also a hybrid retrieval system (`/rag`) that combines BM25 and semantic search so you can ask questions against your own codebase without shipping it anywhere.

If you want to switch providers mid-session, one command does it: `/provider ollama`, `/provider anthropic`, `/provider openai`, `/provider groq`, `/provider gemini`. The conversation continues uninterrupted. This matters for people who want local models for most work but occasionally need a larger cloud model for a hard problem.

A few things I tried to get right that most tools skip: persistent project memory backed by SQLite that survives restarts and gets injected into every prompt automatically; a sandbox and permission profile system so the agent cannot touch paths or run commands you have not approved; an audit log in JSONL format for every action the agent takes; and MCP tool support if you want to extend it. The test suite is 1102 automated tests at 85%+ coverage, which caught a lot of edge cases I would have shipped otherwise.

It runs on Python 3.12+, works on Windows, macOS, and Linux, and is MIT licensed. No account required, no telemetry, no subscription tier. The GitHub is at github.com/ilxstudio/ilx-ai-cli — issues and PRs welcome. Would be curious what commands or workflows people think are missing.

---

## HN Post

**Title:** Show HN: ILX AI CLI — free, local-first AI coding assistant for the terminal (MIT)

---

ILX AI CLI is a terminal REPL for AI-assisted coding built on three layers: a provider abstraction that routes to Ollama (local), Anthropic, OpenAI, Groq, or Gemini interchangeably via `/provider <name>`; a set of task-specific slash commands that compose that provider layer; and a retrieval layer (BM25 + semantic hybrid, `/rag`) for grounding responses in local codebase context without sending files to a cloud endpoint.

A few design decisions worth calling out:

The default backend is Ollama. Nothing leaves the machine unless you switch providers. This is not a privacy checkbox — it is the default path.

The `/debug` command runs programs interactively with full stdin passthrough, venv detection, and session logging to `~/.ilx_cli/debug/`. When a program errors, the AI gets the full stderr and a snapshot of the run context. This handles the common case where you want to iterate on a failing script without copy-pasting stack traces.

Persistent project memory is SQLite-backed and injected into every prompt automatically. It survives restarts and accumulates context about the project over time without manual maintenance.

The sandbox model requires explicit permission profiles before the agent can write files or execute commands outside approved paths. All agent actions are written to an append-only JSONL audit log.

MCP tool support is included for extending the command set without forking.

Stack: Python 3.12+. 1102 automated tests, 85%+ coverage. Runs on Windows, macOS, Linux. MIT licensed.

Source: github.com/ilxstudio/ilx-ai-cli

Happy to answer questions about the architecture or the provider routing layer specifically.
