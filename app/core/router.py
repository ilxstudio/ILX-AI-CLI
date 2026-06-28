"""Model router — selects provider/model based on task type and routing strategy.

Routing strategies:
  auto        — ILX picks the best available provider for each task type
  free-only   — local Ollama + Gemini free tier only; never paid cloud
  local-only  — Ollama only, fully offline
  quality     — always use the highest-capability configured provider
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import AppConfig

_log = logging.getLogger("ilx_cli.router")

# Task types the router understands
TASK_TYPES = ("chat", "code_edit", "code_review", "research", "embed", "plan")

# Routing strategies
STRATEGIES = ("auto", "free-only", "local-only", "quality")


@dataclass
class RouteDecision:
    provider: str
    model: str
    task_type: str
    strategy: str
    reason: str


class ModelRouter:
    """Selects provider/model for a given task type based on strategy.

    Priority tables define preference order per task type.
    Each entry is (provider, model_hint, condition_key).
    condition_key: "local" = requires ollama; "free" = free tier; "paid" = requires API key.
    """

    # Preference order: (provider, model_hint, tier)
    # tier: "local" | "free" | "paid"
    _PRIORITY: dict[str, list[tuple[str, str, str]]] = {
        "chat": [
            ("ollama", "", "local"),
            ("gemini", "gemini-2.0-flash", "free"),
            ("openai", "gpt-4o-mini", "paid"),
            ("anthropic", "claude-haiku-4-5-20251001", "paid"),
        ],
        "code_edit": [
            ("ollama", "qwen2.5-coder", "local"),
            ("gemini", "gemini-2.0-flash", "free"),
            ("anthropic", "claude-sonnet-4-6", "paid"),
            ("openai", "gpt-4o", "paid"),
        ],
        "code_review": [
            ("ollama", "", "local"),
            ("gemini", "gemini-2.0-flash", "free"),
            ("anthropic", "claude-sonnet-4-6", "paid"),
            ("openai", "gpt-4o", "paid"),
        ],
        "research": [
            ("gemini", "gemini-2.0-flash", "free"),   # large context is ideal
            ("ollama", "", "local"),
            ("anthropic", "claude-sonnet-4-6", "paid"),
        ],
        "embed": [
            ("ollama", "nomic-embed-text", "local"),
        ],
        "plan": [
            ("anthropic", "claude-sonnet-4-6", "paid"),
            ("gemini", "gemini-2.0-flash", "free"),
            ("ollama", "", "local"),
        ],
    }

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def route(self, task_type: str = "chat") -> RouteDecision:
        """Return the best (provider, model) for task_type given current strategy."""
        strategy = getattr(self._cfg, "route_strategy", "auto")
        candidates = self._PRIORITY.get(task_type, self._PRIORITY["chat"])

        allowed_tiers = self._allowed_tiers(strategy)
        for provider, model_hint, tier in candidates:
            if tier not in allowed_tiers:
                continue
            if tier == "local" and not self._ollama_available():
                continue
            if tier == "paid" and not self._has_key(provider):
                continue
            model = self._resolve_model(provider, model_hint)
            return RouteDecision(
                provider=provider,
                model=model,
                task_type=task_type,
                strategy=strategy,
                reason=f"{strategy} strategy — {tier} tier selected",
            )

        # Absolute fallback: whatever the config says
        return RouteDecision(
            provider=self._cfg.provider,
            model=self._cfg.ollama_model,
            task_type=task_type,
            strategy=strategy,
            reason="fallback to configured provider",
        )

    def explain(self) -> list[str]:
        """Return human-readable routing table for current strategy."""
        strategy = getattr(self._cfg, "route_strategy", "auto")
        lines = [f"  Strategy: {strategy}"]
        for task in TASK_TYPES:
            dec = self.route(task)
            lines.append(f"  {task:<14} → {dec.provider}/{dec.model}  ({dec.reason})")
        return lines

    # ── internal ──────────────────────────────────────────────────────────

    def _allowed_tiers(self, strategy: str) -> set[str]:
        if strategy == "local-only":
            return {"local"}
        if strategy == "free-only":
            return {"local", "free"}
        if strategy == "quality":
            return {"local", "free", "paid"}
        # auto: prefer local, allow free/paid as needed
        return {"local", "free", "paid"}

    def _ollama_available(self) -> bool:
        try:
            import httpx
            r = httpx.get(
                f"{self._cfg.ollama_url}/api/tags", timeout=2.0
            )
            return r.status_code == 200
        except Exception:
            return False

    def _has_key(self, provider: str) -> bool:
        import keyring
        try:
            key = keyring.get_password("ilx_ai_cli", f"{provider}_api_key")
            return bool(key)
        except Exception:
            return False

    def _resolve_model(self, provider: str, hint: str) -> str:
        """Return the best concrete model name for provider+hint."""
        if provider == "ollama":
            if hint:
                # Try to find a matching local model
                try:
                    import httpx
                    r = httpx.get(f"{self._cfg.ollama_url}/api/tags", timeout=2.0)
                    if r.status_code == 200:
                        models = [m["name"] for m in r.json().get("models", [])]
                        for m in models:
                            if hint.lower() in m.lower():
                                return m
                except Exception:
                    pass
            return self._cfg.ollama_model or "llama3.2"
        if provider == "gemini" and hint:
            return hint
        if provider == "anthropic" and hint:
            return hint
        if provider == "openai" and hint:
            return hint
        return hint or "unknown"
