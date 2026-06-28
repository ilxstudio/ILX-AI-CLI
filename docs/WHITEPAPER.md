# ILX AI CLI: A Local-First, Provider-Agnostic AI Coding Assistant for Professional Developers

**ILX Studio, LLC**
Copyright 2026 ILX Studio, LLC. All rights reserved.
MIT License — Free to use, modify, and distribute.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Problem: AI Coding Tools and the Missing Middle](#2-the-problem-ai-coding-tools-and-the-missing-middle)
3. [Market Landscape Analysis](#3-market-landscape-analysis)
4. [The ILX AI CLI Solution](#4-the-ilx-ai-cli-solution)
5. [Security and Privacy Architecture](#5-security-and-privacy-architecture)
6. [Performance Engineering](#6-performance-engineering)
7. [Developer Experience Design](#7-developer-experience-design)
8. [Technical Architecture Overview](#8-technical-architecture-overview)
9. [Community and Open-Source Model](#9-community-and-open-source-model)
10. [Getting Started](#10-getting-started)
11. [Conclusion and Roadmap](#11-conclusion-and-roadmap)

---

## 1. Executive Summary

The AI-assisted development landscape has matured rapidly, but a significant gap remains: most tools force developers to choose between capability and control. Cloud-hosted tools deliver powerful models but require sending source code to third-party servers. Local tools preserve privacy but offer a narrow feature set tied to a single provider. Neither option serves the growing class of professional developers who need the full spectrum — chat, code generation, code review, test repair, research, workspace indexing, persistent project memory, and process supervision — without sacrificing data sovereignty or being locked into a single vendor or pricing model.

ILX AI CLI is a terminal-first, open-source AI coding assistant built to close that gap. It operates local-first by default through deep Ollama integration, while simultaneously supporting Anthropic, OpenAI, Groq, and Gemini as switchable providers through a single unified interface. Every capability — from BM25+semantic hybrid retrieval-augmented generation (RAG) to sandboxed command execution with audit logging, to persistent project memory and interactive debug sessions with AI error analysis — runs identically regardless of which model or provider is active. The tool is written in Python 3.12, runs on Windows, macOS, and Linux, and is released under the MIT License with no usage tiers, no seats, and no telemetry.

ILX Studio, LLC built ILX AI CLI because the team needed it. Working on projects with strict data-handling requirements, the team evaluated the leading tools and found each one wanting in at least one critical dimension. This white paper describes the problem in detail, places ILX AI CLI in the competitive landscape, explains the architectural decisions that make it viable for regulated and security-conscious environments, and outlines the roadmap for the community-driven development model going forward.

---

## 2. The Problem: AI Coding Tools and the Missing Middle

### 2.1 The Cloud Dependency Problem

The dominant AI coding assistants — GitHub Copilot, Cursor, and similar tools — are fundamentally cloud services. Code, comments, file context, and in many cases full repository content are transmitted to remote inference endpoints on every interaction. For the vast majority of consumer projects this is an acceptable trade-off. For a meaningful segment of the professional market it is not.

Regulated industries present the clearest constraint. Financial services firms operating under SOC 2, PCI DSS, or internal data classification policies cannot authorize unrestricted transmission of proprietary trading logic or client-handling code to third-party APIs. Healthcare organizations governed by HIPAA face equivalent restrictions when any code touches patient data pipelines, even indirectly. Defense contractors and government software teams operate under classification frameworks that make cloud-only tooling a non-starter by policy. These are not edge cases. They represent a substantial portion of enterprise software development activity.

Beyond regulated industries, data sovereignty concerns are spreading into the broader engineering community. Developers are becoming more deliberate about what leaves their machines. Proprietary algorithms, competitive differentiators embedded in code, and unreleased product logic all represent intellectual property that, once transmitted, is subject to the data handling practices of the receiving vendor — practices that can change.

### 2.2 The IDE Dependency Problem

A second structural constraint is IDE coupling. Tools like Cursor and Continue.dev are extensions of a specific editor environment. Developers who live in the terminal — system programmers, DevOps engineers, data engineers, embedded developers, and anyone working over SSH on remote hosts — have no natural integration point with editor-centric tools. A coding assistant that requires a running GUI editor is not usable in a headless CI environment, on a remote server, or in a team workflow where engineers use different editors.

### 2.3 The Cost and Lock-In Problem

Per-seat enterprise pricing compounds the accessibility problem. GitHub Copilot Enterprise is priced in ways that make sense for large organizations amortizing cost across hundreds of engineers, but is prohibitive for small teams and individual developers who need professional-grade tooling. The per-seat model also introduces organizational friction: tool adoption must be approved and budgeted rather than evaluated and adopted organically.

Provider lock-in is a related concern. A team that builds workflows around a single closed-source tool — its specific command structure, its context management, its output format — accumulates switching costs over time. If pricing changes, the provider discontinues a feature, or a better model becomes available from a different vendor, migration is disruptive.

### 2.4 The Feature Fragmentation Problem

Even among tools that address some of these concerns, no single solution covers the complete developer workflow. Code completion is one activity. Code review, iterative test repair, structured research across documentation and code, workspace-wide semantic indexing, persistent project context across sessions, and multi-step agent workflows are distinct activities that current tools handle inconsistently or not at all. Developers end up stitching together multiple tools, each with its own context model and output format, to approximate the coverage they need.

---

## 3. Market Landscape Analysis

The table below summarizes how the leading tools compare across dimensions that matter to professional developers.

| Tool | Open Source | Local Model Support | IDE Required | Multi-Provider | Full Command Set | No-Cost Tier | Sandbox/Permissions |
|------|------------|---------------------|-------------|---------------|-----------------|-------------|---------------------|
| GitHub Copilot | No | No | Yes (extension) | No (OpenAI) | No | No | No |
| Cursor | No | No | Yes (Electron) | Limited | No | Limited | No |
| Continue.dev | Yes | Yes (Ollama) | Yes (extension) | Yes | No | Yes | No |
| Aider | Yes | Partial | No | Limited | Partial | Yes | No |
| OpenHands | Yes | Yes | No | Yes | Yes | Yes | Partial |
| ILX AI CLI | Yes | Yes (native) | No | Yes (5 providers) | Yes | Yes (MIT) | Yes |

### 3.1 GitHub Copilot

GitHub Copilot is the market leader in AI-assisted code completion. Its tight integration with GitHub and VS Code gives it distribution advantages that no independent tool can replicate. However, it is fundamentally a completion engine, not a general coding assistant. There is no structured code review command, no test-fixing loop, no research capability, no persistent project memory, and no offline mode. All inference is cloud-bound, and the product is closed-source. For the use cases described in Section 2, Copilot is not a viable option.

### 3.2 Cursor

Cursor delivers a polished experience for developers willing to adopt it as their primary editor. The integrated chat, multi-file context management, and agentic editing are genuinely useful. The constraints are significant: it requires running the Cursor Electron application, it is closed-source, all inference routes through cloud APIs, and local model support is limited. Developers who work in terminals, Vim, Emacs, or on remote servers have no path to adoption.

### 3.3 Continue.dev

Continue.dev is the most direct open-source competitor in the IDE-integrated space. It supports Ollama and multiple providers, which makes it meaningfully more flexible than Copilot or Cursor. However, it remains an IDE extension: its primary interface is a sidebar in VS Code or JetBrains. Terminal-first workflows are not served. The command set is limited to completions and basic chat; there is no structured review, research, project memory, or test-repair workflow.

### 3.4 Aider

Aider is the strongest open-source terminal-based option currently available. It has a dedicated user base, active development, and a coherent philosophy around pair-programming in the terminal. Its limitations are real: the provider set is narrower, the permission and security model is minimal, there is no persistent project memory, no interactive debug runner, and the command set, while growing, does not cover the full workflow described in this paper. Aider is a strong single-task tool; ILX AI CLI is designed as a complete developer workflow platform.

### 3.5 OpenHands

OpenHands (formerly OpenDevin) takes an ambitious approach: a full agent execution environment with Docker-based sandboxing. It is genuinely capable for complex agentic tasks. The operational requirements are the constraint — Docker must be running, the system is resource-intensive, and the architecture is designed for longer-horizon automated tasks rather than interactive developer sessions. For a developer who wants to ask a quick question, review a diff, or fix a failing test, OpenHands is overbuilt.

---

## 4. The ILX AI CLI Solution

ILX AI CLI is designed around a single core principle: the developer's workflow should not be constrained by the tool's architecture. Local or cloud, online or offline, simple chat or multi-step agent — the interface is the same.

### 4.1 Provider-Agnostic Multi-Model Routing

The tool supports five LLM providers through a unified interface:

- **Ollama** — Local inference; no data leaves the machine
- **Anthropic** — Access to frontier-class language models via API
- **OpenAI** — GPT-family models; broadly compatible ecosystem
- **Groq** — High-throughput inference for latency-sensitive workflows
- **Gemini** — Google's model family for multimodal and long-context tasks

Switching providers requires a single command. Context, session history, and tool configuration are preserved across the switch. The `/route` command provides intelligent model routing — sending tasks to the most appropriate model based on task type, cost constraints, and configured preferences — without requiring manual selection every time.

### 4.2 The Command Set

ILX AI CLI exposes a structured command interface covering the full development workflow:

| Command | Function |
|---------|----------|
| `/review` | Structured code review against a diff or file set |
| `/fix-tests` | Iterative test repair loop: run tests, analyze failures, propose fixes, iterate |
| `/research` | Combined web and codebase research with cited synthesis |
| `/plan` | Structured implementation planning from a natural-language objective |
| `/index` | Workspace indexing for semantic search across the full codebase |
| `/symbol` | Symbol-level search across the indexed codebase |
| `/rag` | Tune the RAG retrieval pipeline weights |
| `/memory` | Persistent project knowledge: facts, fix history, and symbol records |
| `/debug` | Interactive debug runner with AI-assisted error analysis |
| `/audit` | Replay and inspect logged actions from a session |
| `/benchmark` | Model performance comparison across defined tasks |
| `/route` | Intelligent routing to the best available model for a task |

These commands are not thin wrappers around a chat interface. Each is implemented as a structured workflow with distinct stages, prompting strategies, and output formats tuned to the task.

### 4.3 Retrieval-Augmented Generation

The workspace indexing system combines BM25 keyword retrieval with dense semantic embeddings to produce a hybrid RAG pipeline. When a developer asks a question about their codebase, the system retrieves the most relevant files and code sections using both lexical matching (which handles exact identifiers, function names, and error messages well) and semantic similarity (which handles conceptual queries and paraphrased descriptions). The combined ranking feeds context into the active model's prompt window, giving the LLM accurate grounding in the actual code rather than relying on training data that may be stale or simply wrong about the project.

The `/rag` command exposes the retrieval weights directly, allowing developers and teams to tune BM25 and semantic thresholds for their specific codebase characteristics. The `/symbol` command provides direct symbol-level lookup without requiring a full semantic query.

### 4.4 Persistent Project Memory

Standard AI coding tools start each session with no knowledge of the project. Conventions, architectural decisions, past bug fixes, and team preferences must be re-established through context injection every time. This is wasteful and error-prone.

ILX AI CLI addresses this with a persistent project memory system backed by a local SQLite database stored in the project workspace. The memory system stores three categories of information:

**Facts** are developer-supplied key-value pairs that remain available across all sessions. A team can record that `auth-token-ttl = access tokens expire in 15 minutes`, that `db-engine = PostgreSQL 16 with pool size 20`, or that a specific pattern is prohibited in the codebase. These facts are retrieved automatically when relevant and can be searched explicitly with `/memory search`.

**Fix records** are written automatically whenever the `/fix-tests` loop repairs a failing test or the code agent resolves an error. Each record captures the file path, a description of the problem, the solution applied, and the outcome. Developers and the AI can consult this history to avoid repeating past mistakes and to understand why a particular approach was chosen.

**Symbol records** are written during workspace indexing. The `/symbol` command searches the symbol index for matching function names, class names, and identifiers, with file path and signature. This gives the AI accurate grounding in the actual structure of the codebase rather than guessing from context alone.

The memory database never leaves the developer's machine. It is stored under the workspace root in `.ilx_cli/memory.db` and can be committed to version control to share project knowledge across a team, or excluded via `.gitignore` for personal-only use. The `/memory stats` command shows database size and record counts.

### 4.5 Interactive Debug Runner with AI Error Analysis

Debugging interactive programs — scripts that read from stdin, prompt the user, or run multi-stage pipelines — is poorly served by existing AI coding tools. Most tools operate at the level of static code analysis or completed outputs; they cannot observe a program running interactively in real time.

The ILX AI CLI debug runner addresses this directly. The `/debug` command launches a Python script in a subprocess with full stdin passthrough, meaning the developer's terminal input reaches the program as if ILX were not present. All output — stdout, stderr, and user input — is captured to a structured session log under `~/.ilx_cli/debug/`. The session ID is displayed at launch and associated with all subsequent analysis commands.

When the program exits with a non-zero code or produces error output, the developer runs `/debug analyze`. ILX extracts the relevant error lines — tracebacks, exception messages, file references — and constructs a structured prompt that includes the command, exit code, user input, and error context. This prompt is submitted to the active LLM, which returns a specific diagnosis and fix: the corrected line of code, the `pip install` command for a missing dependency, or the configuration change required. The session log is preserved so the developer can re-run analysis against the same session or compare multiple sessions with `/debug logs`.

Venv detection is automatic: if the workspace contains a `.venv` or `venv` directory, the debug runner uses that environment's Python binary rather than the system Python, matching the environment the code was written for.

This capability eliminates the copy-paste cycle of running a program, capturing its error output, switching to an AI chat window, pasting the error, and reading a response. The debug runner keeps the developer in a single tool and a single context throughout the diagnostic cycle.

---

## 5. Security and Privacy Architecture

Security is not a feature in ILX AI CLI — it is a design constraint applied from the ground up.

### 5.1 Local-First by Default

The default configuration routes all inference through Ollama, running entirely on the local machine. No network connections to external APIs are made unless the developer explicitly configures and selects a cloud provider. This is the correct default for professional use: the safe path requires no configuration, and the less-safe path requires deliberate action.

### 5.2 Permission Engine

Every action the tool can take — reading files, executing commands, writing output — is governed by a permission engine with three modes:

- **deny_all** — No actions taken without explicit per-action approval. Suitable for untrusted environments or when reviewing what the tool would do before authorizing it.
- **ask** — The default. The tool requests approval before each consequential action. The developer sees exactly what will happen and approves or denies individually.
- **auto** — Actions on the configured allow-list proceed without prompting. Actions outside the allow-list fall back to ask mode.

Command allow-lists and deny-lists are configurable at the project level. A team can define which shell commands the tool is permitted to run automatically and which require human approval. The deny-list enforces hard stops regardless of allow-list contents.

### 5.3 Sandbox Mode

Sandbox mode restricts the tool to read-only operations and blocks all shell execution. It is designed for environments where the tool should be able to analyze and advise but not act — code review in a CI pipeline, for example, or initial evaluation by a security team before broader deployment.

### 5.4 Audit Logging

Every action taken — commands run, files read, files modified, prompts sent, responses received — is written to a structured audit log. The `/audit` command replays sessions with full fidelity, allowing developers to review what happened in any prior session. Audit logs are stored locally; nothing is transmitted to ILX Studio or any third party.

### 5.5 Secrets Management

API keys are stored exclusively in the operating system keychain — the Windows Credential Manager, macOS Keychain, or the Linux Secret Service. No credentials are written to configuration files, environment variable exports, or any file that could be committed to version control. The tool explicitly refuses to accept keys as command-line arguments to prevent exposure in shell history.

### 5.6 Process Isolation

The tool does not use `shell=True` in any subprocess invocation. All external commands are executed with explicit argument lists, preventing shell injection vulnerabilities. Paths are never hardcoded; all filesystem access is relative to the project root or explicit user-provided paths.

---

## 6. Performance Engineering

A terminal tool must feel fast. Latency introduced by the tool itself — independent of model inference time — should be imperceptible. ILX AI CLI is engineered with this constraint in mind throughout.

### 6.1 Hybrid RAG Pipeline

The BM25+semantic retrieval system is built for low-latency operation on developer hardware. BM25 indexing is incremental: only modified files are re-indexed on workspace updates. Semantic embeddings are computed in batches using numpy with SIMD-optimized cosine similarity calculation. The two retrieval paths run in parallel where hardware permits, and results are merged using reciprocal rank fusion before being passed to the model.

### 6.2 Parallel File Indexing

Workspace indexing uses Python's `ThreadPoolExecutor` to parallelize file reading, tokenization, and embedding computation. On a typical developer machine with an SSD, a 50,000-line codebase indexes in under ten seconds on first run. Subsequent runs are incremental and typically complete in under two seconds.

### 6.3 Query Result Caching

Frequently repeated queries — asking about the same function or module across a session — are served from an in-memory LRU cache. Cache entries are invalidated when the indexed files change. This eliminates redundant embedding computation and retrieval overhead for common patterns.

### 6.4 Bounded Output Buffers

Streaming model output is managed through `deque`-based bounded buffers that prevent memory growth during long-running sessions with large output volumes. The buffer size is configurable; the default is tuned to balance responsiveness with memory efficiency on developer hardware ranging from 8 GB to 64 GB RAM.

### 6.5 Startup Performance

The CLI is designed for fast startup. Imports are deferred where possible, the configuration is loaded lazily, and the provider client is not initialized until the first request is made. Cold start to interactive prompt takes under one second on representative developer hardware.

### 6.6 Project Memory Performance

The persistent project memory system uses SQLite with indexed columns on key and kind fields. Lookups for facts and symbols are sub-millisecond on typical project memory databases. The full-text search across facts uses SQLite's FTS5 extension where available, with fallback to LIKE-based search on older SQLite builds. Database size for a large active project with thousands of facts and symbols remains under 10 MB on disk.

---

## 7. Developer Experience Design

### 7.1 Terminal-Native Interface

ILX AI CLI is designed for the terminal, not adapted to it. The interface uses structured prompts, clear output formatting, and color-coded output that degrades gracefully in environments that do not support ANSI color codes. Pipe-friendly output modes are available for integration with shell scripts and CI pipelines.

### 7.2 Session Continuity

Context is maintained across the full session. The tool tracks the conversation history, the active files, and the state of any ongoing workflow (test-fix loop, review, research) and makes all of it available to subsequent commands without requiring the developer to re-establish context. Sessions can be named and resumed across terminal sessions. Persistent project memory extends this continuity across all sessions indefinitely.

### 7.3 Zero-Configuration Start

A developer with Ollama installed can run ILX AI CLI without any additional configuration. The default model, the default permission mode, and the default output format are all set to reasonable values. The tool discovers the local Ollama installation automatically. Reaching for cloud providers requires adding an API key to the keychain, which the tool guides the user through interactively.

### 7.4 Composability

Commands can be composed. The output of `/research` can feed into `/plan`; the output of `/plan` can feed into `/review`; the results of `/fix-tests` feed back into the same session context, and fix records are written to project memory automatically. The debug runner's session logs feed directly into `/debug analyze`. This composability enables multi-step workflows that would otherwise require manual copy-paste between tool invocations.

### 7.5 MCP Tool Integration

The Model Context Protocol (MCP) integration allows external tools and data sources to be wired into the ILX AI CLI context. Custom tools — database query interfaces, documentation systems, internal APIs — can be registered and made available to the model during any session. This extensibility point allows teams to adapt the tool to their specific environments without forking the codebase.

---

## 8. Technical Architecture Overview

### 8.1 Layer Structure

The codebase is organized into three distinct layers with explicit dependency boundaries:

- **`cli/`** — Command parsing, argument validation, output formatting, and user interaction. This layer has no direct dependency on model providers; it communicates with the application layer through defined interfaces.
- **`app/core/`** — Session management, permission engine, audit logging, provider routing, RAG orchestration, project memory, and debug session management. This is the central application layer; it depends on providers and the indexing system but not on the CLI layer.
- **`codex/app/`** — Workspace indexing, embedding computation, and retrieval. This layer is independently testable and can be used programmatically without the CLI.

This separation ensures that adding a new provider requires changes only in `app/core/`, adding a new command requires changes only in `cli/`, and indexing improvements can be developed and tested in isolation.

### 8.2 Provider Abstraction

Each LLM provider is implemented behind a common interface that exposes: streaming chat completion, non-streaming completion, embedding generation, and model enumeration. The routing layer selects a provider implementation at session start (or on `/route` command) and the rest of the system is unaware of which provider is active. New providers can be added by implementing the interface without modifying any existing code.

### 8.3 Python 3.12

The tool targets Python 3.12 specifically to take advantage of improved performance characteristics in the interpreter, better error messages during development, and the stable asyncio improvements that make streaming model output efficient. The dependency footprint is intentionally minimal: core functionality has no external dependencies beyond the provider SDKs. The RAG pipeline adds numpy and a sentence-transformers-compatible embedding library. Project memory uses SQLite from the Python standard library.

### 8.4 Configuration System

Configuration is hierarchical: system defaults are overridden by user-level configuration, which is overridden by project-level configuration. Project-level configuration lives in a `.ilx/` directory in the project root and can be committed to version control to share settings across a team. Secrets are never part of any configuration file at any level.

### 8.5 Project Memory Storage

Project memory is stored in a SQLite database at `<workspace>/.ilx_cli/memory.db`. The schema contains three tables: `facts` (key-value records with timestamps and session IDs), `fixes` (file path, problem description, solution, and outcome), and `symbols` (name, kind, file path, and signature). Writes are synchronous and immediate; there is no background flush that could lose data on crash. The database file is created on first write and requires no initialization step.

### 8.6 Debug Session Storage

Debug session logs are stored as structured text files under `~/.ilx_cli/debug/`. Each session file records timestamped entries for stdout, stderr, and stdin, tagged by stream type. Session IDs are derived from the launch timestamp and are stable across analyze commands. The runner uses Python's `subprocess.Popen` with `stdin=subprocess.PIPE` and separate stdout/stderr pipes, reading output in a dedicated thread to prevent blocking while the developer types input.

---

## 9. Community and Open-Source Model

### 9.1 MIT License

ILX AI CLI is released under the MIT License. This is the least restrictive widely-used open-source license. There are no usage restrictions, no attribution requirements beyond the license notice, no copyleft obligations, and no commercial use restrictions. Organizations can deploy the tool internally, modify it, and integrate it into commercial products without licensing fees or approval from ILX Studio.

### 9.2 No Commercial Tiers

There is no paid tier, no enterprise tier, and no feature gating. Every feature described in this paper is available to every user. ILX Studio's business model does not depend on restricting open-source functionality to drive commercial conversions.

### 9.3 No Telemetry

The tool collects no usage data, no crash reports, and no analytics. Nothing is transmitted to ILX Studio's servers. The audit log and project memory database live entirely on the developer's machine and are never uploaded.

### 9.4 Contribution Model

The project follows standard open-source contribution practices: issues, pull requests, and community discussion on the public repository. The architecture's layer separation makes it straightforward for contributors to add new providers, commands, or retrieval strategies without needing deep familiarity with the full codebase.

---

## 10. Getting Started

### 10.1 Prerequisites

- Python 3.12 or later
- Ollama (for local inference — recommended) or API keys for cloud providers
- Windows 10/11, macOS 12+, or a modern Linux distribution

### 10.2 Installation

```bash
pip install ilx-ai-cli
```

Or from source:

```bash
git clone https://github.com/ilxstudio/ilx-cli
cd ilx-cli
pip install -e .
```

### 10.3 First Run

```bash
ilx
```

On first run, the tool detects whether Ollama is available and, if so, begins routing to a local model immediately. No configuration is required.

### 10.4 Adding a Cloud Provider

```bash
/provider openai
/apikey set
```

The tool prompts for the key, stores it in the OS keychain, and makes the provider available for the current and future sessions.

### 10.5 Switching Providers

Within a session:

```
/provider groq
```

Or at launch:

```bash
ilx --provider groq
```

### 10.6 Indexing a Workspace

```text
/workspace ~/projects/my-api
/index build
```

After indexing, all chat and command sessions have access to semantic search across the full codebase, and `/symbol` lookups are available.

### 10.7 Starting Project Memory

```text
/memory add team-convention "all API responses use snake_case JSON keys"
/memory add test-runner "pytest with --tb=short; coverage threshold 80%"
```

These facts are available in all future sessions without requiring re-injection into context.

### 10.8 Running the Debug Runner

```text
/debug src/my_script.py --arg value
```

After the script exits, run:

```text
/debug analyze
```

to get AI-powered diagnosis of any errors in the session log.

---

## 11. Conclusion and Roadmap

### 11.1 Summary

ILX AI CLI v1.0.0 addresses a genuine and underserved need in the developer tooling ecosystem. The combination of local-first inference, multi-provider routing, a complete command set covering the full development workflow, persistent project memory, an interactive debug runner with AI error analysis, a rigorous security and permission model, and an MIT-licensed open-source foundation makes it uniquely positioned for professional developers, regulated-industry teams, and organizations that cannot or will not accept the trade-offs of cloud-only, IDE-coupled, or single-provider tools.

The tool was built because the team at ILX Studio needed it. That origin ensures that design decisions are grounded in real usage rather than market positioning. The features that exist are the features that were needed; the features that are absent were not yet needed or not yet ready.

### 11.2 Roadmap

The following capabilities are under active development or planned for near-term releases:

**Near-term (next two releases)**
- Additional MCP tool integrations (database query, internal documentation systems)
- Expanded `/fix-tests` heuristics for more testing frameworks and languages
- Improved session resume with named session management
- `--output json` flag across all commands for pipeline integration
- `/memory import` and `/memory export` for team-shared project memory

**Medium-term**
- Multi-file agentic editing with conflict detection
- Plugin API for community-contributed commands
- Configurable RAG chunk strategies (file-level, function-level, line-range)
- Team-shared session replay for collaborative code review
- Debug runner support for non-Python runtimes (Node.js, Ruby, Go)

**Long-term**
- Local fine-tuning integration for project-specific model adaptation
- CI/CD integration manifests for GitHub Actions and GitLab CI
- Web UI companion for teams who want a browser interface alongside the terminal

### 11.3 A Note on Philosophy

The development philosophy behind ILX AI CLI can be summarized simply: a developer tool should be in the developer's control. It should run where they work, use the model they choose, keep their data on their hardware, remember what matters across sessions, show them exactly what it is doing, and never require them to pay a subscription to access capabilities they already have on their machine.

The open-source model is not incidental to this philosophy. It is the mechanism that makes it durable. Any developer who uses ILX AI CLI can read every line of code it executes, audit every decision it makes, and modify any behavior they disagree with. That is the standard the tool is held to, and it is the standard the team intends to maintain.

---

*ILX AI CLI is developed and maintained by ILX Studio, LLC.*
*Copyright 2026 ILX Studio, LLC. Released under the MIT License.*
*Source code and documentation: https://github.com/ilxstudio/ilx-cli*
