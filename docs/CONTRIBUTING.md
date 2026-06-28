# Contributing to ILX AI CLI

Thank you for your interest in contributing. This document covers the essentials.

## Getting Started

1. Fork the repository and clone your fork.
2. Create a Python 3.11+ virtual environment and install dependencies:
   ```
   pip install -e ".[dev]"
   ```
3. Run the test suite to confirm everything passes:
   ```
   pytest tests/ -v
   ```

## Development Guidelines

- **No file over 700 lines.** Split into modules if needed.
- **No procedural god-files.** Use proper OOP — one class per concern.
- **No comments explaining what the code does.** Name things well instead. Only comment *why* when it's non-obvious.
- **No shell=True** in subprocess calls.
- **No hardcoded secrets.** Use the keychain via `app.core.secret_store`.
- All new features need tests in `tests/`.

## Submitting Changes

1. Create a branch: `git checkout -b feature/my-feature`
2. Write tests for any new functionality.
3. Ensure all tests pass: `pytest tests/ -v`
4. Open a pull request with a clear description of the change and why it was made.

## Reporting Issues

Open a GitHub issue. Include:
- OS and Python version
- Steps to reproduce
- Expected vs actual behavior
- Any relevant output or error messages

## Coding Standards

The following rules are enforced by `tests/test_36_architecture_fitness.py`
and must be respected in all contributions.

### File length
No source file may exceed **700 lines**. If a module grows beyond that, split
it into focused sub-modules (e.g. `foo.py` → `foo_base.py` + `foo_impl.py`).

### No `shell=True`
Every `subprocess.run()` or `subprocess.Popen()` call must pass `shell=False`
(the default). Use `app.core.process_runner.run()` for simple commands and
`app.core.supervisor.ProcessSupervisor` for long-running tasks.

### No hardcoded paths
Never write literal OS paths such as `C:\Users\...` or `/home/user/...` in
production code. Use `Path.home()`, `sys.executable`, or a value from
`AppConfig` instead.

### OOP patterns
One class per concern. Avoid procedural god-files. Pass `AppConfig` by
reference — do not read environment variables in business logic.

### No LLM provider name in comments or docs
Do not reference specific LLM provider names (e.g. model brand names) in
`.md`, `.txt`, or source comments unless the code literally connects to that
provider's API. Use the generic terms "LLM", "model", or "AI provider".

### Layer dependency rules
Dependencies only flow **downward**:
```
cli/  →  app/core/  →  codex/app/
```
`app/core/` and `codex/app/` must never import from `cli/`.

## Code of Conduct

Be respectful. Constructive criticism is welcome; personal attacks are not.
