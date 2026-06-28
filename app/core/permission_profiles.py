"""Permission profile definitions — shared between PermissionEngine and perm_cmds."""
from __future__ import annotations

PROFILES: dict[str, dict[str, str]] = {
    "safe": {
        "reads":    "ask",
        "writes":   "ask",
        "commands": "ask",
        "network":  "ask",
        "desc":     "Ask before everything — maximum control",
    },
    "coding": {
        "reads":    "auto",
        "writes":   "ask",
        "commands": "ask",
        "network":  "deny",
        "desc":     "Auto-read files, ask before writes/commands, no network",
    },
    "review": {
        "reads":    "auto",
        "writes":   "deny",
        "commands": "deny",
        "network":  "deny",
        "desc":     "Read-only — no writes, no commands, no network",
    },
    "ci": {
        "reads":    "auto",
        "writes":   "auto",
        "commands": "auto",
        "network":  "deny",
        "desc":     "CI mode — auto-approve reads/writes/commands from allowlist; no network",
    },
    "locked": {
        "reads":    "deny",
        "writes":   "deny",
        "commands": "deny",
        "network":  "deny",
        "desc":     "No tool use at all — chat only",
    },
}

VALID_PROFILES = list(PROFILES.keys())
