"""LLM client package — unified import surface.

The implementation is split across three modules to keep each file under 700 lines:

  llm_client_base.py       — BaseLLMClient, TokenUsage, OllamaClient, helpers
  llm_client_providers.py  — AnthropicClient, OpenAIClient
  llm_client_ext.py        — GroqClient, GeminiClient, get_client, get_llm_client,
                             get_chat_llm_client
  llm_client_fallback.py   — FallbackLLMClient (cross-provider fallback chain)

All public symbols are re-exported here so that every existing import of the form
``from codex.app.llm_client import XYZ`` continues to work without change.
"""
from __future__ import annotations

# Re-export ``time`` so that test patches of ``codex.app.llm_client.time.sleep``
# continue to work after the module was split into sub-modules.
import time  # noqa: F401

# ── Base layer ────────────────────────────────────────────────────────────────
from codex.app.llm_client_base import (  # noqa: F401
    _CODEX_SYSTEM,
    _OLLAMA_RETRYABLE,
    BaseLLMClient,
    OllamaClient,
    TokenUsage,
    _handle_rate_limit,
    _retry_with_backoff,
)

# ── Extended clients + factory functions ──────────────────────────────────────
from codex.app.llm_client_ext import (  # noqa: F401
    GeminiClient,
    GroqClient,
    get_chat_llm_client,
    get_client,
    get_llm_client,
)

# ── Fallback chain client ─────────────────────────────────────────────────────
from codex.app.llm_client_fallback import FallbackLLMClient  # noqa: F401

# ── Provider clients ──────────────────────────────────────────────────────────
from codex.app.llm_client_providers import (  # noqa: F401
    AnthropicClient,
    OpenAIClient,
)
