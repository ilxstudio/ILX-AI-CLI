"""LLM client package — unified import surface.

The implementation is split across three modules to keep each file under 700 lines:

  llm_client_base.py       — BaseLLMClient, TokenUsage, OllamaClient, helpers
  llm_client_providers.py  — AnthropicClient, OpenAIClient
  llm_client_ext.py        — GroqClient, GeminiClient, get_client, get_llm_client,
                             get_chat_llm_client

All public symbols are re-exported here so that every existing import of the form
``from codex.app.llm_client import XYZ`` continues to work without change.
"""
from __future__ import annotations

# Re-export ``time`` so that test patches of ``codex.app.llm_client.time.sleep``
# continue to work after the module was split into sub-modules.
import time  # noqa: F401

# ── Base layer ────────────────────────────────────────────────────────────────
from codex.app.llm_client_base import (  # noqa: F401
    BaseLLMClient,
    TokenUsage,
    OllamaClient,
    _handle_rate_limit,
    _retry_with_backoff,
    _CODEX_SYSTEM,
    _OLLAMA_RETRYABLE,
)

# ── Provider clients ──────────────────────────────────────────────────────────
from codex.app.llm_client_providers import (  # noqa: F401
    AnthropicClient,
    OpenAIClient,
)

# ── Extended clients + factory functions ──────────────────────────────────────
from codex.app.llm_client_ext import (  # noqa: F401
    GroqClient,
    GeminiClient,
    get_client,
    get_llm_client,
    get_chat_llm_client,
)
