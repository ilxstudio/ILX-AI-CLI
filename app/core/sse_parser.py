# DEPRECATED: SSE parsing is now inline in codex/app/llm_client.py — kept for reference only
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

_log = logging.getLogger("ilx_cli.sse")
_MAX_EVENT_BYTES = 4 * 1024 * 1024


@dataclass
class SSEEvent:
    data:       str
    event_type: str = "message"
    id:         str | None = None


def parse_event_data(raw: str) -> dict:
    if not raw:
        return {}
    if len(raw) > _MAX_EVENT_BYTES:
        _log.warning("dropping oversized SSE event (%d bytes)", len(raw))
        return {}
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return decoded


def classify_event(parsed: dict) -> Literal["token", "done", "error", "info"]:
    if "error" in parsed:
        return "error"
    if parsed.get("done"):
        return "done"
    if "content" in parsed:
        return "token"
    return "info"
