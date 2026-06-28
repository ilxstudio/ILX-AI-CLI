# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.3.x   | Yes       |
| < 0.3   | No        |

## Reporting a Vulnerability

Email: arivera@riveraeng.com

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested mitigations (optional)

We will acknowledge within 48 hours and aim to resolve critical issues within 7 days.

**Do not open public GitHub issues for security vulnerabilities.**

## Security Model

### Secret Handling

- API keys are stored in the OS keychain via `keyring` — never in config files or plaintext on disk.
- Audit logs automatically redact fields named `api_key`, `password`, `secret`, `token`, and similar patterns (12 keyword patterns, case-insensitive).

### Subprocess Safety

- All subprocess calls use `shell=False` — shell injection via metacharacters is not possible.
- Commands are always passed as lists, never as strings to a shell interpreter.

### SSRF Protection

- The web fetch tool rejects requests to private IP ranges (RFC-1918: 10.x, 172.16–31.x, 192.168.x), localhost (127.x, ::1), and cloud metadata endpoints (169.254.x).
- Override requires explicit `ILX_ALLOW_LOCAL_HTTP=1` environment variable.

### Permission Gating

- File writes and command executions are gated behind interactive approval (`ask` mode), auto-approved (`auto_approve`), or fully blocked (`deny_all`).
- Per-command allowlists and denylists provide fine-grained control.
- Permission profiles (safe, coding, review, ci, locked) provide category-level presets.

### Audit Logging

- All permission decisions, command executions, file operations, and LLM calls are written to `~/.ilx_cli/logs/audit.log` in JSONL format.
- Log rotation: 5 MB per file, 5 generations retained.
- Thread-safe writes with a global lock.

## Sandbox Limitations (v0.3)

ILX AI CLI v0.3 implements a **policy-level sandbox**, not OS-level containment.

A permitted command (e.g., `python -c "..."`) can still access the filesystem outside the workspace. Full OS-level sandboxing is planned for a future release.

See [SANDBOXING.md](SANDBOXING.md) for details.

## Telemetry

ILX AI CLI collects **no telemetry**. No usage data, prompts, or code are sent to ILX Studio servers.
