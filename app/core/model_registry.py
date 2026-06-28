"""Model capability registry for ILX AI CLI.

Provides a static registry of known model capabilities across providers,
with longest-prefix matching for version-agnostic lookups.

MIT License 2026 ILX Studio
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

_log = logging.getLogger("ilx_cli.model_registry")


@dataclass
class ModelCapabilities:
    context_window: int          # max input tokens
    max_output: int              # max output tokens
    supports_vision: bool = False
    supports_tools: bool = False
    supports_streaming: bool = True
    provider: str = ""


MODEL_REGISTRY: dict[str, ModelCapabilities] = {
    # Anthropic
    "claude-opus-4-8":          ModelCapabilities(200000, 32000, True,  True,  True,  "anthropic"),
    "claude-sonnet-4-6":        ModelCapabilities(200000, 16000, True,  True,  True,  "anthropic"),
    "claude-haiku-4-5":         ModelCapabilities(200000,  8000, True,  True,  True,  "anthropic"),
    # OpenAI
    "gpt-4o":                   ModelCapabilities(128000, 16384, True,  True,  True,  "openai"),
    "gpt-4o-mini":              ModelCapabilities(128000, 16384, True,  True,  True,  "openai"),
    "o3":                       ModelCapabilities(200000, 100000, False, True,  False, "openai"),
    # Groq
    "llama-3.3-70b-versatile":  ModelCapabilities(128000, 32768, False, True,  True,  "groq"),
    "llama-3.1-8b-instant":     ModelCapabilities(128000,  8192, False, False, True,  "groq"),
    "gemma2-9b-it":             ModelCapabilities(8192,    8192, False, False, True,  "groq"),
    # Gemini
    "gemini-2.0-flash":         ModelCapabilities(1048576, 8192, True,  True,  True,  "gemini"),
    "gemini-1.5-flash-latest":  ModelCapabilities(1048576, 8192, True,  True,  True,  "gemini"),
    "gemini-1.5-pro-latest":    ModelCapabilities(2097152, 8192, True,  True,  True,  "gemini"),
    # Ollama (conservative defaults)
    "codellama:7b":             ModelCapabilities(4096,   2048, False, False, True,  "ollama"),
    "qwen2.5:14b":              ModelCapabilities(8192,   4096, False, False, True,  "ollama"),
    "llama3.2:latest":          ModelCapabilities(8192,   4096, False, False, True,  "ollama"),
}

# Generous defaults for unrecognised models
_UNKNOWN_CAPABILITIES = ModelCapabilities(
    context_window=4096,
    max_output=2048,
    supports_vision=False,
    supports_tools=False,
    supports_streaming=True,
    provider="",
)


def _normalise(model: str) -> str:
    """Lower-case and strip common version date suffixes (e.g. -20251001)."""
    import re
    return re.sub(r"-\d{8}$", "", model.lower().strip())


def get_capabilities(model: str) -> ModelCapabilities:
    """Return capabilities for *model* using longest-prefix matching.

    Strips trailing date-version suffixes before matching so that
    ``claude-haiku-4-5-20251001`` resolves to the ``claude-haiku-4-5`` entry.
    Returns conservative defaults for unknown models.
    """
    normalised = _normalise(model)
    # Exact match first
    if normalised in MODEL_REGISTRY:
        return MODEL_REGISTRY[normalised]
    # Longest-prefix match
    best_key: str = ""
    for key in MODEL_REGISTRY:
        if normalised.startswith(key) and len(key) > len(best_key):
            best_key = key
    if best_key:
        _log.debug("model_registry: '%s' matched prefix '%s'", model, best_key)
        return MODEL_REGISTRY[best_key]
    _log.debug("model_registry: '%s' unknown — returning defaults", model)
    return _UNKNOWN_CAPABILITIES


def get_context_window(model: str, default: int = 4096) -> int:
    """Return the context window size for *model*, or *default* if unknown."""
    caps = get_capabilities(model)
    return caps.context_window if caps is not _UNKNOWN_CAPABILITIES else default


def supports_vision(model: str) -> bool:
    """Return True if *model* is known to support image inputs."""
    return get_capabilities(model).supports_vision


def supports_tools(model: str) -> bool:
    """Return True if *model* is known to support tool/function calling."""
    return get_capabilities(model).supports_tools
