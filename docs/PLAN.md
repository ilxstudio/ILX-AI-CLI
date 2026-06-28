# ILX AI CLI — Strategic Roadmap

**Mission:** The free, local-first AI CLI for developers who want control, privacy, and no subscription lock-in.

---

## Market Position

ILX is not competing with Claude Code on model quality. It is competing on:

- **Free forever** with local models (Ollama / Qwen / DeepSeek)
- **No telemetry, no subscription, no vendor lock-in**
- **Audit everything** — every file read, every command run, every model call
- **Multi-provider** — route intelligently across local, free-tier, and BYO-key cloud
- **Developer utility CLI** — not just chat, but real workflow tools

The wedge: users already stack Claude Code + Aider + Gemini manually. ILX automates that stack and makes it free.

---

## Why Users Switch (Competitor Pain Points)

| Competitor | What Users Like | What Makes Them Leave |
|---|---|---|
| Claude Code | Best flow, strong UI, plans before acting | Expensive, limits, permission fatigue |
| Codex CLI | Backend/review work, sandbox story | Subscription/API cost, not free |
| Gemini CLI | Free, huge context, open source | Inconsistent code quality, over-editing |
| Aider | Git-native, efficient tokens, repo map | Requires micromanagement |
| OpenCode / local tools | Open, local-friendly | Fragmented, less polished |

Key insight from Reddit/HN: **"No single tool wins — people are stacking."** ILX wins by being the free control layer that routes between them.

---

## Implementation Plan

### Priority 1 — Free Tool Differentiators

#### P1-A: Model Router (`/route`)
**Why:** Users manually pick models per task. ILX should automate this.

```
/route auto         — ILX picks best available model for the task
/route free-only    — local + Gemini free tier only, never paid
/route local-only   — Ollama only, fully offline
/route quality      — best available (local + BYO cloud)
```

Implementation:
- Add `router.py` in `app/core/` with a `TaskRouter` class
- Task classification: `chat`, `edit`, `review`, `research`, `embed`
- Routing table: `{task_type: [(provider, model, condition)]}`
- `/route` command in `cli/commands/route_cmds.py`

#### P1-B: Free/Trust Page (`/free`)
**Why:** Users skeptical of "free" need explicit reassurance.

```
/free
```

Shows:
- No telemetry (with audit log path)
- No subscription required
- No vendor lock-in (export history any time)
- Local models supported
- BYO keys optional — only used if configured
- What network calls happened this session
- Model cost estimate (tokens × rate)

Implementation:
- Add `_cmd_free()` in `cli/commands/trust_cmds.py`
- Pull from audit log for "calls made this session"
- Pull from config for provider/key status

#### P1-C: Local Model Setup Wizard (`/setup local`)
**Why:** Most free users struggle with Ollama setup. ILX should own this onramp.

```
/setup local
```

Flow:
1. Detect Ollama (`ollama list`)
2. Detect available VRAM/RAM (via `psutil` or platform APIs)
3. Suggest models by RAM tier:
   - ≤8 GB → `qwen2.5-coder:3b`
   - 8–16 GB → `qwen2.5-coder:7b`
   - ≥16 GB → `qwen2.5-coder:14b`
   - Embeddings → `nomic-embed-text`
4. Pull selected model via `ollama pull`
5. Run a quick coding test (generate hello-world, verify output)
6. Set as default in config

Implementation:
- Add `setup_wizard.py` in `app/core/`
- Add `/setup` command in `cli/commands/setup_cmds.py`

#### P1-D: Free Benchmark (`/benchmark`)
**Why:** Users ask "which CLI is best?" — give them a local, objective answer.

```
/benchmark
```

Tasks:
1. Edit a file (small surgical change)
2. Fix a planted bug
3. Run a test suite
4. Summarize a repo
5. Generate a docstring

Output:
```
Local model (qwen2.5-coder:7b) benchmark:
  Edit accuracy:     8/10
  Bug fix:           7/10
  Test awareness:    9/10
  Summarization:    85%
  Overall score:    72/100

Best for:  small edits, docs, tests
Weak for:  large refactors
Suggested route:  local for edits, Gemini for planning
```

Implementation:
- Add `benchmark.py` in `app/core/`
- Benchmark tasks are self-contained (no network required)
- Add `/benchmark` command in `cli/commands/bench_cmds.py`

---

### Priority 2 — Beat Paid Tools on Control

#### P2-A: Permission Profiles (`/permission <profile>`)
**Why:** Users hate constant prompts but fear unsafe auto mode. Named profiles solve this.

| Profile | Reads | Writes | Commands | Network |
|---|---|---|---|---|
| `safe` | ask | ask | ask | ask |
| `coding` | auto | ask | ask | deny |
| `review` | auto | deny | deny | deny |
| `ci` | allowlist | allowlist | allowlist | deny |
| `locked` | deny | deny | deny | deny |

```
/permission safe
/permission coding
/permission ci
/permission locked
```

Implementation:
- Add `profiles` dict to `app/core/permissions.py`
- `/permission` command applies profile to current session config
- Profile persists per working-folder in `~/.ilx_cli/permissions.json`

#### P2-B: Sandbox Status and Controls (`/sandbox`)
**Why:** Auto-approve must never escape the workspace. Users need to see and control sandbox boundaries.

```
/sandbox status
/sandbox workspace          — contain all writes to working_folder
/sandbox read-only          — allow reads anywhere, no writes
/sandbox off --i-understand — disable (explicit consent required)
```

Implementation:
- Expose `sandbox_mode` config field (already added in `AppConfig`)
- Add `_cmd_sandbox()` in `cli/commands/sandbox_cmds.py`
- `--i-understand` flag required to disable (prevents accidents)

#### P2-C: Command Allowlist (`/allow`, `/deny`)
**Why:** Users want tests to run automatically but don't want `rm -rf` ever auto-approved.

```
/allow command pytest
/allow command npm test
/allow command ruff
/deny command rm
/deny command git push
```

Implementation:
- Add `command_allowlist` and `command_denylist` to `AppConfig`
- Modify `permissions.py` `confirm()` to check lists before prompting
- Add `_cmd_allow()` / `_cmd_deny()` in `cli/commands/perm_cmds.py`
- Persist per working-folder

#### P2-D: Audit Replay (`/audit replay`, `/audit explain`)
**Why:** ILX already has audit logging — surface it as a feature, not just a record.

```
/audit replay last          — re-show what happened in last session
/audit explain              — natural language summary of actions
/audit export               — export to JSON/CSV
/audit diff                 — show net file changes this session
```

Output includes:
- Files read / written / deleted
- Commands executed (with exit codes)
- URLs fetched
- Model used per call
- Cost/free status
- Permission decisions made

Implementation:
- Extend `cli/commands/audit_cmds.py` with `replay`, `explain`, `export`, `diff` subcommands
- `explain` sends the audit log to the active model for summarization

---

### Priority 3 — Better Coding Workflow

#### P3-A: Patch-First Editing (apply_patch improvements)
**Why:** Gemini/GPT over-rewrite whole files. Aider users prefer surgical diffs. ILX should default to minimal patches.

Enhancements:
- **Diff preview before apply:** show colored diff, ask to proceed
- **Failed-patch recovery:** if context lines don't match, offer fuzzy match or abort cleanly
- **Small-change preference:** if LLM returns a whole file but only N lines changed, auto-convert to patch

Implementation:
- Extend `app/core/mcp_client.py` `_apply_patch_blocks()` with fuzzy line matching
- Add `_preview_diff(original, patched)` → prints colored diff via `difflib`
- Add `prefer_patches` config flag (default `True`)

#### P3-B: Plan-Then-Act Mode (`/plan`)
**Why:** Claude Code is praised for confirming architecture before implementing. ILX should make this a first-class visible mode.

```
/plan                       — inspect repo, propose implementation plan
/plan approve               — approve and begin implementation
/plan edit                  — open plan in editor before approving
/plan cancel                — discard
```

Flow:
1. Inspect repo (RAG + file tree)
2. Propose numbered steps with file references
3. Wait for `/plan approve`
4. Execute steps with tool calls
5. Run tests
6. Show summary diff

Implementation:
- Add `PlanSession` class in `cli/plan_session.py`
- Extend `cli/app.py` to route `/plan` to `PlanSession`
- Plans stored in `~/.ilx_cli/plans/<hash>.json` for replay

#### P3-C: Review Mode (`/review`)
**Why:** Codex gets praised for code review. ILX should offer a structured free review workflow.

```
/review                     — review all uncommitted changes
/review staged              — review only staged changes
/review pr                  — review a GitHub PR (needs gh CLI)
/review security            — security-focused pass only
/review <file>              — review a specific file
```

Output format:
```
RISK: HIGH  auth/session.py:42  — Session token stored in plain text
RISK: MED   api/users.py:18    — Missing input validation on email field
MISSING:    tests/test_auth.py — No tests for token refresh flow
```

Implementation:
- Add `review_runner.py` in `app/core/`
- Reads git diff or specified file(s)
- Structured prompt with categories: bugs, security, maintainability, missing tests
- Output parseable for piping: `ilx review --json | jq '.[] | select(.risk=="HIGH")'`

#### P3-D: Test-Fix Loop (`/fix-tests`)
**Why:** Users switch tools when they reliably finish the task. A test-fix loop is high signal that the tool actually works.

```
/fix-tests                  — run tests, fix failures, repeat up to 5x
/fix-tests --max 10
/fix-tests --only test_auth.py
```

Flow:
1. Run test suite (detect pytest / jest / cargo test automatically)
2. Parse failure output
3. Send failures to LLM with file context
4. Apply patches
5. Re-run tests
6. Stop at max attempts or all green
7. Show final report: attempts, tests fixed, tests still failing

Implementation:
- Add `test_fix_loop.py` in `app/core/`
- Test runner detection: check `pyproject.toml`, `package.json`, `Cargo.toml`
- Failure parser per framework
- Add `/fix-tests` command in `cli/commands/fix_cmds.py`

---

### Priority 4 — Context and Repo Intelligence

#### P4-A: Persistent Repo Index (`/index`)
**Why:** RAG already works but re-indexes every session. Users want a persistent "repo brain."

```
/index build                — index current repo
/index status               — show index freshness, file count, size
/index explain              — "what does this index know about auth?"
/index clear
```

Stores (already partially implemented):
- File content hashes + embeddings (SQLite at `~/.ilx_cli/embeddings.db`) ✓
- Symbol index (classes, functions, exports)
- Dependency graph
- Project rules (`AGENTS.md`, `.ilxrules`)
- Recent failure patterns

Implementation:
- `/index` command in `cli/commands/index_cmds.py`
- Symbol indexer using `ast` module for Python, `tree-sitter` for others
- Expose via `SemanticRAG.explain(query)` method

#### P4-B: Context Inspector (`/context`)
**Why:** Users hate not knowing what the model saw. Transparency builds trust.

```
/context why "how auth works"   — show why these chunks were selected
/context used                   — what's currently in the model's context
/context budget                 — token estimate breakdown
```

Output:
```
Context budget: 8,420 / 32,000 tokens
  System prompt:     1,200
  Chat history:      3,100
  RAG (5 chunks):    2,800
    auth/session.py   640
    auth/token.py     580
    tests/test_auth.py 480
    ...
  Tool schemas:      1,320
Remaining:         23,580
```

Implementation:
- Add `_cmd_context()` in `cli/commands/context_cmds.py`
- `ChatSession` already tracks messages — expose token estimates

#### P4-C: Big Repo Research Mode (`/research`)
**Why:** Competes with Gemini's huge-context appeal for codebase exploration.

```
/research "how does auth work"
/research "where are all database calls"
/research "what could break if I change the User model"
```

Flow:
1. Run multi-pass RAG (BM25 + semantic + symbol search)
2. Build file map of relevant code
3. Send to model with "research" system prompt (not coding prompt)
4. Output: architecture map, data flow, risks, follow-up prompts

Implementation:
- Add `research_runner.py` in `app/core/`
- Leverages existing `SemanticRAG` + `HybridRetriever`
- Output Markdown map suitable for piping or saving

---

### Priority 5 — Extensions and Community

#### P5-A: Real MCP Support (already in progress ✓)
Status: `StdioMCPManager` / `StdioMCPConnection` implemented and tested.

Remaining:
- User-facing `/mcp servers connect` feedback polish
- MCP tool discovery surfaced in `/status`
- Auto-connect configured servers on startup

#### P5-B: Plugin/Tool Marketplace (`/plugin`)
**Why:** Since ILX is free forever, community extensibility multiplies its value.

```
/plugin install github      — install from curated list
/plugin install <url>       — install from Git repo URL
/plugin list
/plugin remove <name>
/tool publish               — scaffold a publishable tool manifest
```

Format: Git repo with `ilx-manifest.json`:
```json
{
  "name": "postgres",
  "version": "1.0.0",
  "tools": ["query", "schema", "migrate"],
  "entry": "tools/postgres_tool.py"
}
```

Implementation:
- Add `plugin_manager.py` in `app/core/`
- Installs to `~/.ilx_cli/plugins/<name>/`
- Loads at startup alongside user-defined tools
- Curated list hosted at `ilxstudio/ilx-plugins` GitHub

#### P5-C: Recipes (`/recipe`)
**Why:** Users love copy-paste workflows for common tasks.

```
/recipe list
/recipe run harden-python-package
/recipe run add-docker
/recipe run migrate-flask-fastapi
/recipe run add-ci-github-actions
```

Recipe format: YAML with steps that can be:
- Prompts sent to the active model
- Built-in commands (git, docker, etc.)
- File templates to scaffold

Implementation:
- Add `recipe_runner.py` in `app/core/`
- Recipes stored in `~/.ilx_cli/recipes/` and built-in `app/recipes/`
- Add `/recipe` command in `cli/commands/recipe_cmds.py`

---

## Implementation Order

| Phase | Features | Switch-Worth? |
|---|---|---|
| **Now** | Error handling hardening (done ✓), test suite green (done ✓) | Foundation |
| **v0.4** | P1-B (`/free`), P1-C (`/setup local`), P2-A (`/permission profiles`), P2-C (command allowlist), P2-D (`/audit replay`) | Yes — trust + control story |
| **v0.5** | P3-B (`/plan`), P3-C (`/review`), P3-D (`/fix-tests`), P1-A (`/route`) | Yes — workflow story |
| **v0.6** | P1-D (`/benchmark`), P4-A (`/index`), P4-B (`/context`), P4-C (`/research`) | Yes — intelligence story |
| **v0.7** | P5-A (MCP polish), P5-B (plugins), P5-C (recipes), P3-A (patch-first) | Yes — community + ecosystem |

---

## The Positioning Statement

> **ILX AI** — the free, local-first AI CLI for developers who want control, privacy, and no subscription lock-in.
> Use local models by default. Route to free or cloud models when useful. Audit every action. Keep your workflow portable.
> No telemetry. No subscription. No lock-in. Your code, your models, your rules.

This is not "Claude Code lite." It is the free control layer that sits between you and every model.
