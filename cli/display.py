"""Terminal display helpers — ANSI colors, banner, cost estimation, and formatted output."""
from __future__ import annotations

import os
import re
import sys


def _enable_ansi() -> None:
    # Windows needs the VT processing flag set or ANSI codes print as literal text
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
        except Exception:
            pass


_enable_ansi()

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
CYAN    = "\033[36m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
WHITE   = "\033[37m"

BANNER = (
    f"{BOLD}{CYAN}"
    "\n"
    "  ██╗██╗     ██╗  ██╗     █████╗ ██╗      ██████╗██╗     ██╗\n"
    "  ██║██║     ╚██╗██╔╝    ██╔══██╗██║     ██╔════╝██║     ██║\n"
    "  ██║██║      ╚███╔╝     ███████║██║     ██║     ██║     ██║\n"
    "  ██║██║      ██╔██╗     ██╔══██║██║     ██║     ██║     ██║\n"
    "  ██║███████╗██╔╝ ██╗    ██║  ██║██║     ╚██████╗███████╗██║\n"
    "  ╚═╝╚══════╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝      ╚═════╝╚══════╝╚═╝\n"
    f"{RESET}"
    f"{DIM}              ILX AI CLI  ·  v1.0.0  ·  chat • code • build • test{RESET}\n"
)


# cost per 1 million tokens (input, output) in USD, keyed by model substring
PROVIDER_PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {
        "claude-opus-4":        (15.00, 75.00),
        "claude-sonnet-4":      (3.00,  15.00),
        "claude-haiku-4":       (0.80,   4.00),
        "claude-3-7-sonnet":    (3.00,  15.00),
        "claude-3-5-sonnet":    (3.00,  15.00),
        "claude-3-5-haiku":     (0.80,   4.00),
        "claude-3-opus":        (15.00, 75.00),
        "claude-3-sonnet":      (3.00,  15.00),
        "claude-3-haiku":       (0.25,   1.25),
        "claude":               (3.00,  15.00),  # fallback for unknown claude models
    },
    "openai": {
        "gpt-4o-mini":          (0.15,   0.60),
        "gpt-4o":               (2.50,  10.00),
        "gpt-4-turbo":          (10.00, 30.00),
        "gpt-4":                (30.00, 60.00),
        "gpt-3.5-turbo":        (0.50,   1.50),
        "o1-mini":              (3.00,  12.00),
        "o1":                   (15.00, 60.00),
        "gpt":                  (2.50,  10.00),  # fallback
    },
    "groq": {
        "llama-3.3-70b":        (0.59,   0.79),
        "llama-3.1-70b":        (0.59,   0.79),
        "llama-3.1-8b":         (0.05,   0.08),
        "llama-3-70b":          (0.59,   0.79),
        "llama-3-8b":           (0.05,   0.08),
        "mixtral-8x7b":         (0.24,   0.24),
        "gemma2-9b":            (0.20,   0.20),
        "llama":                (0.59,   0.79),  # fallback
    },
    "gemini": {
        "gemini-2.0-flash":     (0.10,   0.40),
        "gemini-1.5-pro":       (3.50,  10.50),
        "gemini-1.5-flash":     (0.075,  0.30),
        "gemini-1.0-pro":       (0.50,   1.50),
        "gemini":               (0.10,   0.40),  # fallback
    },
    "ollama": {},  # always free
}


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Return estimated cost in USD, or None if provider/model isn't in the pricing table."""
    if provider == "ollama":
        return 0.0
    provider_table = PROVIDER_PRICING.get(provider, {})
    if not provider_table:
        return None
    model_lower = model.lower()
    # pick the most specific key that appears in the model name
    best_key = ""
    best_rate: tuple[float, float] | None = None
    for key, rates in provider_table.items():
        if key in model_lower and len(key) > len(best_key):
            best_key = key
            best_rate = rates
    if best_rate is None:
        return None
    input_cost  = (prompt_tokens     / 1_000_000) * best_rate[0]
    output_cost = (completion_tokens / 1_000_000) * best_rate[1]
    return input_cost + output_cost


def format_cost(cost: float | None, provider: str) -> str:
    """Format a cost float as a human-readable string."""
    if provider == "ollama":
        return "FREE (local)"
    if cost is None:
        return ""
    if cost == 0.0:
        return "$0.0000"
    if cost < 0.001:
        return f"~${cost:.5f}"
    return f"~${cost:.4f}"


def hr(char: str = "─", width: int = 60) -> str:
    return DIM + char * width + RESET


def print_hr(char: str = "─", width: int = 60) -> None:
    print(hr(char, width))


def dim(text: str) -> str:
    return f"{DIM}{text}{RESET}"


def bold(text: str) -> str:
    return f"{BOLD}{text}{RESET}"


def color(text: str, col: str) -> str:
    return f"{col}{text}{RESET}"


def print_diff_line(line: str) -> None:
    if line.startswith("+") and not line.startswith("+++"):
        print(f"  {GREEN}{line}{RESET}")
    elif line.startswith("-") and not line.startswith("---"):
        print(f"  {RED}{line}{RESET}")
    elif line.startswith("@@"):
        print(f"  {CYAN}{line}{RESET}")
    elif line.startswith("+++") or line.startswith("---"):
        print(f"  {BOLD}{line}{RESET}")
    else:
        print(f"  {DIM}{line}{RESET}")


def highlight_code(text: str, language: str = "") -> str:
    """Apply Pygments syntax highlighting if available, else return plain text."""
    try:
        from pygments import highlight
        from pygments.formatters import Terminal256Formatter
        from pygments.lexers import get_lexer_by_name, guess_lexer

        try:
            lexer = get_lexer_by_name(language, stripall=True) if language else guess_lexer(text)
        except Exception:
            return text

        try:
            return highlight(text, lexer, Terminal256Formatter(style="monokai"))
        except Exception:
            return text
    except ImportError:
        return text


def render_chat_response(text: str) -> None:
    """Print an assistant response, syntax-highlighting fenced code blocks."""
    fence_re = re.compile(r"^```(\w*)\s*$", re.MULTILINE)
    parts = fence_re.split(text)

    # fence_re.split produces [prose, lang, code, prose, lang, code, ...] so step by 3
    i = 0
    while i < len(parts):
        sys.stdout.write(parts[i])
        if i + 2 < len(parts):
            lang = parts[i + 1]
            sys.stdout.write(highlight_code(parts[i + 2], lang))
            i += 3
        else:
            i += 1  # trailing prose with no closing fence
    sys.stdout.flush()


def print_banner() -> None:
    """Print the startup banner. Set ILX_NO_BANNER=1 to suppress it in CI."""
    if os.environ.get("ILX_NO_BANNER", "").strip() == "1":
        return
    try:
        from cli.rich_display import _use_rich
        if _use_rich():
            from rich.console import Console
            from rich.panel import Panel
            from rich.text import Text

            console = Console()
            inner = Text.from_ansi(BANNER)
            console.print(Panel(inner, border_style="cyan", expand=False))
            return
    except Exception:
        pass
    print(BANNER)


def print_help() -> None:
    print(f"""
{BOLD}ILX AI CLI — Quick Reference{RESET}

  {BOLD}MODES{RESET}       {CYAN}/chat{RESET}  {CYAN}/code{RESET}
  {BOLD}CONTEXT{RESET}     {CYAN}/add <path>{RESET}  {CYAN}/drop <path>{RESET}  {CYAN}/clear{RESET}  {CYAN}/undo{RESET}  {CYAN}/paste{RESET}  {CYAN}/context{RESET}
  {BOLD}SESSION{RESET}     {CYAN}/history{RESET}  {CYAN}/resume [N]{RESET}  {CYAN}/session list|name|search{RESET}  {CYAN}/compact{RESET}
  {BOLD}MODEL{RESET}       {CYAN}/model{RESET}  {CYAN}/provider{RESET}  {CYAN}/route [auto|free-only|local-only|quality]{RESET}  {CYAN}/status{RESET}
  {BOLD}WORKSPACE{RESET}   {CYAN}/workspace{RESET}  {CYAN}/init [template]{RESET}  {CYAN}/rules{RESET}  {CYAN}/branch{RESET}
  {BOLD}CONTROL{RESET}     {CYAN}/permission [safe|coding|review|ci|locked]{RESET}  {CYAN}/sandbox [workspace|read-only|off]{RESET}
  {BOLD}ALLOW/DENY{RESET}  {CYAN}/allow <cmd>{RESET}  {CYAN}/deny <cmd>{RESET}  {CYAN}/allowlist{RESET}
  {BOLD}GIT{RESET}         {CYAN}/git status|diff|log|commit|pull|push|stash|revert|ai-commit{RESET}   {CYAN}/diff [file]{RESET}   {CYAN}/diffexplain{RESET}
  {BOLD}RUN & TEST{RESET}  {CYAN}/run [cmd]{RESET}  {CYAN}/test [--cov]{RESET}  {CYAN}/lint [fix]{RESET}  {CYAN}/ci{RESET}  {CYAN}/watch{RESET}  {CYAN}/timings{RESET}
  {BOLD}TASKS{RESET}       {CYAN}/tasks{RESET}  {CYAN}/kill [ID]{RESET}  {CYAN}/attach [ID]{RESET}
  {BOLD}SCAFFOLD{RESET}    {CYAN}/scaffold <type> <name>{RESET}  {CYAN}/readme{RESET}  {CYAN}/mcp{RESET}
  {BOLD}USER TOOLS{RESET}  {CYAN}/tool list|create|run{RESET}
  {BOLD}LOCAL AI{RESET}    {CYAN}/setup local{RESET}  {CYAN}/benchmark{RESET}  {CYAN}/free{RESET}
  {BOLD}WORKFLOW{RESET}    {CYAN}/plan <task>{RESET}  {CYAN}/plan approve{RESET}  {CYAN}/review{RESET}  {CYAN}/fix-tests{RESET}
  {BOLD}INDEX{RESET}       {CYAN}/index build{RESET}  {CYAN}/index explain <q>{RESET}  {CYAN}/index status{RESET}
  {BOLD}UTILITIES{RESET}   {CYAN}/version{RESET}  {CYAN}/export [file]{RESET}  {CYAN}/copy{RESET}  {CYAN}/alias{RESET}  {CYAN}/completions{RESET}  {CYAN}/search <q>{RESET}  {CYAN}/env{RESET}  {CYAN}/profile{RESET}  {CYAN}/notify on|off{RESET}
  {BOLD}AUDIT{RESET}       {CYAN}/audit [full|security|quality|replay|explain|export|diff]{RESET}

  {CYAN}/help dev{RESET}  — show full developer command reference
  {CYAN}/quit{RESET}      — save and exit
""")


def print_help_dev() -> None:
    print(f"""
{BOLD}ILX AI CLI — Full Developer Reference{RESET}  {DIM}(/help for quick reference){RESET}

{BOLD}Conversation & Context:{RESET}
  {CYAN}/chat{RESET}                    — switch to chat mode (Q&A, default)
  {CYAN}/code{RESET}                    — switch to code-agent mode (creates/edits files)
  {CYAN}/add <path>{RESET}              — pin a file or folder into context
  {CYAN}/drop <path>{RESET}             — remove a pinned context entry
  {CYAN}/context [clear]{RESET}         — show context window usage estimate; clear RAG entries
  {CYAN}/paste{RESET}                   — paste multi-line content (end with ###)
  {CYAN}/clear{RESET}                   — clear conversation history and pins
  {CYAN}/undo{RESET}                    — remove last user+assistant exchange from history
  {CYAN}/compact{RESET}                 — summarize conversation history to save context space
  {CYAN}/history{RESET}                 — list saved sessions
  {CYAN}/resume [N]{RESET}              — resume a saved session
  {CYAN}/session list|name|search{RESET} — manage sessions: list, name current, search content

{BOLD}LLM, Model & Routing:{RESET}
  {CYAN}/provider <name>{RESET}         — switch provider (ollama / anthropic / openai / gemini)
  {CYAN}/server{RESET}                  — change the Ollama server URL
  {CYAN}/model{RESET}                   — change the active model
  {CYAN}/models{RESET}                  — list available models on current server
  {CYAN}/route [strategy]{RESET}        — set model routing strategy:
  {CYAN}/route auto{RESET}              —   ILX picks best available per task (default)
  {CYAN}/route free-only{RESET}         —   local Ollama + free-tier cloud only, never paid
  {CYAN}/route local-only{RESET}        —   Ollama only, fully offline
  {CYAN}/route quality{RESET}           —   always use highest-capability available provider
  {CYAN}/route status{RESET}            —   show current strategy
  {CYAN}/route explain{RESET}           —   show which model runs each task type
  {CYAN}/numctx <N>{RESET}              — set context window size (e.g. /numctx 32768)
  {CYAN}/temperature [val]{RESET}       — get or set generation temperature (0.0–2.0)
  {CYAN}/top_p [val]{RESET}             — get or set top-p sampling (0.0–1.0)
  {CYAN}/max_tokens [n]{RESET}          — get or set max response tokens (-1 = unlimited)
  {CYAN}/params{RESET}                  — show all active generation parameters
  {CYAN}/healthcheck{RESET}             — test Ollama, model, workspace, crash DB, config
  {CYAN}/status{RESET}                  — show current settings and server status

{BOLD}Local AI & Setup:{RESET}
  {CYAN}/setup local{RESET}             — wizard: detect RAM, recommend + pull Ollama models
  {CYAN}/setup status{RESET}            — show Ollama status and installed models
  {CYAN}/setup models{RESET}            — show model recommendations for your RAM
  {CYAN}/benchmark{RESET}               — run 6 coding tasks and score the current model (0–100)
  {CYAN}/benchmark --json{RESET}        — machine-readable benchmark output
  {CYAN}/free{RESET}                    — privacy trust page: telemetry, keys, network calls
  {CYAN}/free calls{RESET}              — show recent network calls from audit log
  {CYAN}/free export{RESET}             — export full session audit as JSON

{BOLD}Workspace & Rules:{RESET}
  {CYAN}/workspace{RESET}               — set the working folder
  {CYAN}/rules [edit]{RESET}            — show or edit project rules (.ilx_rules.md)
  {CYAN}/init [template]{RESET}         — scaffold a project (python / node / rust / go)
  {CYAN}/init --dry-run [tmpl]{RESET}   — preview what /init would create without writing files
  {CYAN}/branch{RESET}                  — create a git branch before coding (ilx/task-<ts>)
  {CYAN}/readme{RESET}                  — generate a README.md for the current workspace via LLM

{BOLD}Permissions & Safety:{RESET}
  {CYAN}/permission status{RESET}       — show current permission profile and behavior per category
  {CYAN}/permission list{RESET}         — list all named profiles
  {CYAN}/permission safe{RESET}         — ask before every read, write, command, and network call
  {CYAN}/permission coding{RESET}       — auto-read files, ask before writes/commands (default)
  {CYAN}/permission review{RESET}       — read-only: no writes or commands allowed
  {CYAN}/permission ci{RESET}           — CI mode: auto-approve all tool use
  {CYAN}/permission locked{RESET}       — no tool use at all — chat only
  {CYAN}/perms{RESET}                   — legacy: set raw permission mode (ask / auto / deny)
  {CYAN}/sandbox status{RESET}          — show filesystem sandbox boundary
  {CYAN}/sandbox workspace{RESET}       — contain all writes to working_folder (default)
  {CYAN}/sandbox read-only{RESET}       — no writes anywhere
  {CYAN}/sandbox off --i-understand{RESET} — disable sandbox (explicit consent required)
  {CYAN}/allow <command>{RESET}         — auto-approve a command without prompting (e.g. /allow pytest)
  {CYAN}/deny <command>{RESET}          — always block a command (e.g. /deny rm)
  {CYAN}/allowlist{RESET}               — show current allow/deny lists
  {CYAN}/allowlist remove <cmd>{RESET}  — remove a command from either list
  {CYAN}/allowlist clear{RESET}         — clear both lists

{BOLD}Plan, Review & Fix:{RESET}
  {CYAN}/plan <task>{RESET}             — inspect repo and generate a numbered implementation plan
  {CYAN}/plan approve{RESET}            — execute the approved plan step by step
  {CYAN}/plan cancel{RESET}             — discard the current plan
  {CYAN}/plan status{RESET}             — show plan progress
  {CYAN}/review{RESET}                  — review all uncommitted changes (bugs, security, style)
  {CYAN}/review staged{RESET}           — review only staged (git add) changes
  {CYAN}/review security{RESET}         — security-only pass: secrets, injection, auth bypass
  {CYAN}/review security <file>{RESET}  — security review a specific file
  {CYAN}/review pr <N>{RESET}           — review GitHub PR by number (requires gh CLI)
  {CYAN}/review <file>{RESET}           — review a specific file
  {CYAN}/fix-tests{RESET}               — run tests, fix failures with LLM, repeat up to max
  {CYAN}/fix-tests --max 10{RESET}      — set max fix attempts
  {CYAN}/fix-tests --only <pat>{RESET}  — run only tests matching pattern
  {CYAN}/fix-tests --dry-run{RESET}     — preview test runner without running

{BOLD}Repo Index & Research:{RESET}
  {CYAN}/index build{RESET}              — build semantic+BM25 index for current workspace
  {CYAN}/index build <path>{RESET}       — index a specific folder
  {CYAN}/index status{RESET}             — show index health (files, chunks, DB size)
  {CYAN}/index explain <question>{RESET} — semantic search: "how does auth work?"
  {CYAN}/index clear{RESET}              — clear in-memory index

{BOLD}Git:{RESET}
  {CYAN}/git status{RESET}              — show working tree status
  {CYAN}/git diff [--staged]{RESET}     — show unstaged (or staged) diff
  {CYAN}/git log [-N]{RESET}            — show last N commits (default 10)
  {CYAN}/git commit -m "<msg>"{RESET}   — stage all changes and commit with message
  {CYAN}/git commit{RESET}              — show changed files, prompt for message interactively
  {CYAN}/git pull{RESET}                — pull from origin (shows conflicts if any)
  {CYAN}/git push{RESET}                — push current branch to origin
  {CYAN}/git push --force{RESET}        — force-push (requires typed confirmation)
  {CYAN}/git stash{RESET}               — stash current changes
  {CYAN}/git stash pop{RESET}           — restore most recent stash
  {CYAN}/git stash list{RESET}          — list all stashes
  {CYAN}/git revert <hash>{RESET}       — create a safe revert commit (shows preview, asks confirmation)
  {CYAN}/git reset HEAD <file>{RESET}   — unstage a specific file (safe)
  {CYAN}/git ai-commit{RESET}           — LLM generates commit message from diff; review before committing
  {CYAN}/diff [file]{RESET}             — show git diff HEAD with syntax highlighting
  {CYAN}/diffexplain [--staged]{RESET}  — ask LLM to explain the current diff in plain English

{BOLD}Dev Tools:{RESET}
  {CYAN}/run [cmd]{RESET}               — run a command in the workspace
  {CYAN}/test [args]{RESET}             — run pytest in the workspace
  {CYAN}/lint [tool]{RESET}             — run ruff / black / mypy
  {CYAN}/ci{RESET}                      — run full CI pipeline (ruff, mypy, pytest, bandit)
  {CYAN}/watch [--glob pattern]{RESET}  — watch files and auto-run tests (default: *.py)
  {CYAN}/format{RESET}                  — auto-format workspace code (ruff / black)
  {CYAN}/profile [--json]{RESET}         — system profile for bug reports (Python, platform, deps, errors)
  {CYAN}/build [entry]{RESET}           — PyInstaller build (bumps patch version)
  {CYAN}/deps [install|outdated]{RESET} — pip package management
  {CYAN}/env [--json]{RESET}            — show ILX environment: Python, platform, API keys, opt deps
  {CYAN}/timings [reset]{RESET}         — show a table of recorded operation timings (last 20)

{BOLD}Analysis & Quality:{RESET}
  {CYAN}/stats [--json]{RESET}          — codebase stats (--json for machine-readable output)
  {CYAN}/complexity [threshold]{RESET}  — cyclomatic complexity report via radon (default: 10)
  {CYAN}/deadcode [confidence%]{RESET}  — unused code detection via vulture (default: 60%)
  {CYAN}/bandit [path]{RESET}           — security linting via bandit
  {CYAN}/precommit init|run{RESET}      — generate .pre-commit-config.yaml and install hooks
  {CYAN}/metrics{RESET}                 — show aggregate usage stats from audit log
  {CYAN}/crashes [summary|clear]{RESET} — crash history from /run
  {CYAN}/audit full{RESET}             — run all audits: security + quality + deps with scores
  {CYAN}/audit security{RESET}         — secrets, shell=True, eval(), bandit, pip-audit
  {CYAN}/audit quality{RESET}          — LOC, complexity, linting, TODO markers
  {CYAN}/audit deps{RESET}             — dependency CVEs, outdated packages
  {CYAN}/audit compare [tool]{RESET}   — LLM competitive analysis vs Claude Code, Aider, Copilot
  {CYAN}/audit replay [N|today]{RESET} — color-coded timeline of recent session actions
  {CYAN}/audit explain [N]{RESET}      — LLM summary of what the AI did this session
  {CYAN}/audit export [file|--csv]{RESET} — export audit log as JSON or CSV
  {CYAN}/audit diff{RESET}             — show net file writes/deletes this session

{BOLD}Tasks & Processes:{RESET}
  {CYAN}/tasks [tail ID|killall]{RESET} — show all running and recent tasks; tail output or kill all
  {CYAN}/kill [TASK_ID]{RESET}          — kill a running task (or the most recent one)
  {CYAN}/attach [TASK_ID]{RESET}        — tail live output of a running task (Ctrl+C to detach)
  {CYAN}/logs [N]{RESET}                — tail the last N lines of the run log

{BOLD}Scaffold & Generation:{RESET}
  {CYAN}/scaffold <type> <name>{RESET}  — generate boilerplate files in the workspace
  {CYAN}/scaffold dockerfile{RESET}     — generate a multi-stage Dockerfile
  {CYAN}/scaffold github-actions{RESET} — generate a GitHub Actions CI workflow
  {CYAN}/readme{RESET}                  — generate a README.md for the current workspace via LLM
  {CYAN}/convert <file> [out]{RESET}   — read/convert PDF, DOCX, XLSX, PNG files

{BOLD}User Tools (Self-Improvement):{RESET}
  {CYAN}/tool list{RESET}               — list all user-created tools
  {CYAN}/tool create <name> <desc>{RESET} — let LLM generate a new tool, validate & register it
  {CYAN}/tool run <name> [args]{RESET}  — run a user tool in a safe background thread
  {CYAN}/tool remove <name>{RESET}      — delete a user tool
  {CYAN}/tool info <name>{RESET}        — show tool details and source preview
  {CYAN}/tool validate <name>{RESET}    — re-run safety checks on a tool
  {CYAN}/tool enable|disable <name>{RESET} — toggle a tool on/off without deleting it
  {CYAN}/<name>{RESET}                  — invoke a registered user tool directly
  {DIM}User tools run in isolated threads — the main program is always protected.{RESET}
  {DIM}Tools are saved in workspace/user_tools/ and persist across sessions.{RESET}

{BOLD}Tool Use (Function Calling):{RESET}
  {CYAN}/tools{RESET}                   — show current tool-use status (on/off)
  {CYAN}/tools on{RESET}                — enable function calling (non-streaming, up to 5 rounds)
  {CYAN}/tools off{RESET}               — disable function calling (back to streaming mode)
  {CYAN}/tools list{RESET}              — list all built-in tools (read_file, write_file, etc.)
  {DIM}When enabled, the LLM can call read_file, write_file, list_dir, run_command, fetch_url.{RESET}
  {DIM}Supports: ollama, anthropic, openai, groq, gemini providers.{RESET}

{BOLD}MCP Tools:{RESET}
  {CYAN}/mcp status{RESET}              — show registered MCP tools and config path
  {CYAN}/mcp list{RESET}                — list all tools with signatures
  {CYAN}/mcp init{RESET}                — register built-in tools and save to disk
  {CYAN}/mcp reload{RESET}              — reload tool definitions from disk
  {CYAN}/mcp call <tool> [json]{RESET}  — invoke a tool directly with JSON args

{BOLD}Utilities:{RESET}
  {CYAN}/version{RESET}                 — show CLI version, Python, platform, active provider/model
  {CYAN}/export [filename]{RESET}       — export conversation to Markdown (auto-named if no file given)
  {CYAN}/copy{RESET}                    — copy last AI response to clipboard (requires pyperclip)
  {CYAN}/alias list{RESET}              — list all defined aliases
  {CYAN}/alias <name> <cmd>{RESET}      — create a slash-command alias (e.g. /alias hi /chat hi!)
  {CYAN}/alias remove <name>{RESET}     — remove an alias
  {CYAN}/completions [--print]{RESET}   — generate bash/zsh tab-completion scripts for ilx
  {CYAN}/search <query>{RESET}          — search saved session history for a keyword
  {CYAN}/notify on|off|test{RESET}      — toggle desktop notifications for long-running tasks
  {CYAN}/ssh <user@host>{RESET}         — connect to remote machine via SSH
  {CYAN}/ssh help{RESET}                — show SSH setup guide (keys & password files)
  {CYAN}/fetch <url>{RESET}             — fetch a URL and show readable text
  {CYAN}/convert <file>{RESET}          — read PDF, DOCX, XLSX, PNG files
  {CYAN}/tool list|create|run{RESET}    — manage and run dynamic Python tools
  {CYAN}/diag{RESET}                    — export diagnostic ZIP to Desktop
  {CYAN}/help{RESET}                    — show quick reference
  {CYAN}/help dev{RESET}                — show this full developer reference
  {CYAN}/quit{RESET}                    — save session and exit

{BOLD}Inline context:{RESET}
  Use @path or quoted paths to attach files inline:
    explain @src/main.py
    what is wrong with "D:\\\\MyProject\\\\app.py"?

{BOLD}One-shot (from shell):{RESET}
  ilx --code "add unit tests to auth.py"
  ilx --chat "what does this error mean?"
  git diff | ilx "summarize this diff"
""")
