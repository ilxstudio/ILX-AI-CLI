# Changelog

All notable changes to ILX AI CLI are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — 2026-06-28

First public release.

### Added
- `/memory` command with subcommands: `show`, `add`, `forget`, `fixes`, `search`, `stats`
- Persistent project memory backed by SQLite (`<workspace>/.ilx_cli/memory.db`)
- `/fix-tests` loop now writes fix records to project memory automatically
- `/debug` command: interactive script runner with stdin passthrough, venv auto-detection, and session logging
- `/debug log` — view last session output
- `/debug logs` — list recent debug sessions
- `/debug analyze` — AI-powered error analysis of a debug session
- `/symbol <name>` — search the symbol index for matching function and class names
- `/rag` command with `status`, `bm25`, and `semantic` subcommands for tuning retrieval weights
- Symbol records written to project memory during `/index build`
- Python 3.12 as the minimum supported version (previously 3.11)
- Test coverage raised to 85%

### Changed
- Version badge and release artifacts updated to 1.0.0
- USER_MANUAL updated with full sections for `/debug`, `/memory`, `/symbol`, and `/rag`
- WHITEPAPER updated with architecture sections for Persistent Project Memory and Interactive Debug Runner
- README comparison table updated to include Persistent Project Memory and Interactive Debug Runner rows

---

## [0.2.0] — 2026-06-28

### Added
- Multi-provider LLM support: Anthropic, OpenAI, Groq, Gemini, Meta (via Ollama), local Ollama
- Per-provider API key storage in OS keychain
- Token counter displayed after every LLM response
- Cost estimator: per-request and session totals for all cloud providers
- Function calling / tool-use protocol for all providers (`/tools on`)
- 15 `/init` project scaffold templates (python, node, react, fastapi, django, rust, go, flask, express, nextjs, vue, svelte, electron, cli-tool, library)
- `/upgrade` command: detects project type, compares against template
- `/template list` command
- `.env`, pre-commit, and docker-compose scaffold extensions
- `/audit` command: security scan, quality metrics, dependency check, competitive comparison
- `/audit compare` — live web research for competitive scoring against industry tools
- `/git ai-commit` — LLM-generated commit messages from staged diffs
- 3-mode permission gating: Ask / Auto-approve / Deny-all
- JSONL audit log for all file ops, commands, and permission decisions
- RAG context system: BM25 for Ollama, full injection for cloud providers
- Context window usage warnings at 80% and 95%
- Ollama retry with exponential backoff (local only; cloud providers fail fast)
- Process supervisor: queue, warn-before-kill, graceful shutdown
- MCP tool integration (14 built-in tools including file converters)
- User-defined tools (`/tool new`, `/tool list`, `/tool remove`) with 3-stage validation
- SSH session management (`/ssh`)
- Repo map generation for symbol-aware context
- Tab completion and readline history (500 lines)
- `/git` hardening: blocks `--force` push and `--hard` reset without explicit confirmation
- Security: SSRF guard, path traversal prevention, SSH injection protection, secret redaction in audit logs
- 251 tests across 20 test modules

### Fixed
- Child process tree kill on Windows (taskkill /F /T /PID)
- HTML parser void-element handling (meta/link tags no longer corrupt skip depth)
- Rate limit 429 handler parses Retry-After header before sleeping

---

## [0.1.0] — 2026-01-01

### Added
- Initial release: Ollama-only chat and code agent
- Basic workspace scaffolding
- `/settings`, `/help`, `/version` commands

---

[Unreleased]: https://github.com/ilxstudio/ilx-ai-cli/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ilxstudio/ilx-ai-cli/releases/tag/v1.0.0
[0.2.0]: https://github.com/ilxstudio/ilx-ai-cli/releases/tag/v0.2.0
[0.1.0]: https://github.com/ilxstudio/ilx-ai-cli/releases/tag/v0.1.0
