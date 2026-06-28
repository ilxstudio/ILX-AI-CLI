"""Route engine — implements the route_strategy config field."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.route_engine")

_CLOUD_PROVIDERS = {"anthropic", "openai", "groq", "gemini", "meta"}
_LOCAL_PROVIDERS = {"ollama"}
_FREE_LABEL = "free / local-only"


def resolve_provider(cfg: AppConfig) -> str:
    """Return the effective provider name after applying route_strategy."""
    strategy = getattr(cfg, "route_strategy", "auto").lower().strip()

    # free-only and local-only are aliases — always force ollama
    if strategy in ("free-only", "local-only"):
        if cfg.provider != "ollama":
            _log.debug("route_strategy=%s → forcing ollama (was %s)", strategy, cfg.provider)
        return "ollama"

    if strategy == "quality":
        if cfg.provider in _CLOUD_PROVIDERS and _has_key(cfg.provider):
            return cfg.provider
        # walk the preferred cloud order until we find one with a key
        for p in ("anthropic", "openai", "groq", "gemini", "meta"):
            if _has_key(p):
                _log.debug("quality route → %s (has key)", p)
                return p
        _log.debug("quality route → ollama (no cloud key found)")
        return "ollama"

    # "auto" and anything unknown: use configured provider
    return cfg.provider


def is_free_tier(cfg: AppConfig) -> bool:
    """Return True when the effective provider is local/free (Ollama)."""
    return resolve_provider(cfg) == "ollama"


def free_tier_label(cfg: AppConfig) -> str:
    """One-line label for display (e.g. startup banner or /free status)."""
    if is_free_tier(cfg):
        return f"ollama  [{_FREE_LABEL}]"
    return cfg.provider


def strategy_description(strategy: str) -> str:
    descs = {
        "auto":       "Use configured provider (default)",
        "free-only":  "Always use local Ollama — zero API cost",
        "local-only": "Always use local Ollama — zero API cost",
        "quality":    "Prefer cloud providers (best output); fall back to Ollama",
    }
    return descs.get(strategy.lower(), f"Unknown strategy '{strategy}'")


# check keyring for a stored key — used by the quality strategy
def _has_key(provider: str) -> bool:
    try:
        import keyring
        return bool(keyring.get_password("ilx_ai_cli", f"{provider}_api_key"))
    except Exception as exc:
        logging.debug("keyring lookup failed for %r: %s", provider, exc)
        return False
