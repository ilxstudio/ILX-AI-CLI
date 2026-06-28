# Roadmap

This document describes the planned direction for ILX AI CLI. Items marked **[community]**
are good opportunities for external contributors. Dates are targets, not guarantees.

---

## Current: v0.3.x (Beta)

ILX AI CLI is in active beta. The core feature set is complete and stable enough for daily
use by terminal developers. The focus for 0.3.x patch releases is hardening, bug fixes, and
test coverage — not new features.

What is already shipped:

- Multi-provider routing (Ollama, Gemini, GPT-4o, Groq, OpenRouter) with hot-swap
- RAG-based codebase indexing with BM25 retrieval
- Permission profiles and per-session sandbox controls
- Audit logging to JSONL with secret redaction
- MCP tool support with PermissionEngine gating
- Automated test-fix loop (`/fix` command)
- Code review mode (`/review` command)
- Docker and project scaffolding commands
- Architecture fitness tests enforced in CI
- GitHub issue templates and CI pipeline

---

## Near Term: v0.4.0 (Q3 2026)

v0.4.0 focuses on security hardening and the contributor ecosystem. The goal is to make ILX
a project that external teams can build on and that enterprises can deploy with confidence.

- **OS-level sandboxing** — bubblewrap on Linux, Job Objects on Windows; restrict file system
  access for AI-initiated subprocesses without requiring Docker
- **Plugin marketplace** — a registry of community MCP tool packs installable with
  `ilx plugin install <name>`; versioned, signed packages **[community]**
- **VS Code extension** — a thin wrapper that opens ILX in a terminal panel and surfaces
  review comments as editor diagnostics **[community]**
- **Streaming interruption** — clean Ctrl-C handling during streamed responses; resume or
  discard the partial output
- **Performance budgets in CI** — latency and token-count assertions checked in the test
  suite so regressions are caught before merge
- **Windows installer** — an NSIS or WiX installer for Windows users who do not want to
  use pip **[community]**

---

## Medium Term: v0.5.0 (Q4 2026)

v0.5.0 raises the ceiling for multi-agent workflows and enterprise adoption.

- **Multi-agent orchestration** — spawn sub-agents for parallel tasks (e.g. write tests
  while refactoring the implementation); coordinate results in a single session
- **Semantic diffs** — surface what changed in meaning, not just in text, when reviewing
  a PR or a large edit
- **Workspace snapshots** — save and restore the full session state (conversation, RAG
  index, open files) so you can context-switch between projects instantly **[community]**
- **Enterprise SSO / SAML** — authenticate to cloud providers via organizational IdP
  rather than personal API keys
- **Audit compliance export** — export audit logs in formats suitable for SOC 2 evidence
  collection; structured JSON schema, redaction guarantees, tamper-evident hashing

---

## Long Term: v1.0 (2027)

v1.0 marks API stability and production-grade packaging. The project will commit to a
stable public API and a defined deprecation policy from this point forward.

- **Stable public API** — `ilx` becomes a library as well as a CLI; the Python API is
  versioned and documented; breaking changes follow a formal deprecation process
- **Plugin marketplace GA** — the plugin registry becomes officially supported with
  automated security scanning and maintainer vetting
- **Windows Store and Mac App Store packaging** — sandboxed app-store distributions for
  users who want system-managed updates **[community]**
- **WASM sandbox** — run AI-generated code in a WebAssembly sandbox for the highest
  isolation level without requiring OS-level privilege
- **Multi-model conversations** — route different parts of a task to different models in
  a single session (e.g. fast local model for file reads, cloud model for synthesis)
- **Comprehensive documentation site** — versioned docs, tutorials, and plugin
  development guides hosted at a stable URL **[community]**

---

## What Is Not on the Roadmap

- A GUI application or web UI (use the VS Code extension or a terminal emulator)
- Telemetry or usage analytics of any kind
- Mandatory cloud account or subscription
- Vendor-specific features that only work with one LLM provider

If you want to propose an addition to this roadmap, open a GitHub Discussion.
