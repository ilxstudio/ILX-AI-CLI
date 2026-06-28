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

## Code of Conduct

Be respectful. Constructive criticism is welcome; personal attacks are not.
