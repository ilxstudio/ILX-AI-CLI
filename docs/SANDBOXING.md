# Sandboxing and Containment

## Overview

ILX AI CLI v0.3 implements a **policy-level sandbox** — not OS-level containment. This document explains what protection is provided and its current limitations.

## Sandbox Modes

Set with `/sandbox <mode>` or via config:

| Mode | File Tools | Commands | Description |
|------|-----------|----------|-------------|
| `workspace` (default) | Workspace-scoped | Permission-gated | File ops confined to workspace path; commands go through permission flow |
| `read_only` | Read-only | **Blocked** | No file writes; no command execution at all |
| `disabled` | Unrestricted | Permission-gated | No path restrictions on file tools; commands still permission-gated |

## What Policy Sandbox Protects

- AI tool file writes outside the workspace (blocked by path check)
- Commands on the denylist (always blocked regardless of mode)
- Commands requiring approval when in `ask` permission mode
- Network requests to private/internal IPs (SSRF guard, always active)
- API keys written to disk (always stored in OS keychain)

## What Policy Sandbox Does NOT Protect

- A **permitted command** (e.g., `python script.py`) that internally writes outside the workspace
- A permitted command that makes its own network requests
- Code executed inside a permitted subprocess

## Permission Layers (Deepest-First)

1. **Sandbox mode** — `read_only` blocks all execute operations regardless of other settings
2. **Command denylist** — specific commands always blocked
3. **Command allowlist** — specific commands always allowed without prompt
4. **Permission profile** — category-level allow/deny (reads, writes, commands, network)
5. **Permission mode** — global `ask` / `auto_approve` / `deny_all`

## Planned OS-Level Containment (Future)

- **Linux:** `bubblewrap` (rootless container) for full filesystem/network isolation
- **macOS:** `sandbox-exec` profile-based containment
- **Windows:** Job Objects + restricted token process creation

Until then: for maximum safety, use `permission_mode = ask` combined with `sandbox_mode = read_only` when running AI on untrusted code.

## Example: Maximum Safety Configuration

```
/permission mode ask
/sandbox read_only
/deny python
/deny rm
```

This configuration requires you to approve every action and blocks all command execution.
