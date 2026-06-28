"""Session cost tracker for ILX AI CLI.

Tracks cumulative token usage and USD cost across all LLM calls in a session.
A module-level singleton ``tracker`` is used by chat_session.py and the
/cost command.

Pricing table (USD per million tokens):
  (input_per_million, output_per_million)
"""
from __future__ import annotations

PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {
        "claude-opus":   (15.00, 75.00),
        "claude-sonnet": (3.00,  15.00),
        "claude-haiku":  (0.25,  1.25),
        "default":       (3.00,  15.00),
    },
    "openai": {
        "gpt-4o-mini":  (0.15,  0.60),
        "gpt-4o":       (2.50,  10.00),
        "gpt-4":        (30.00, 60.00),
        "default":      (2.50,  10.00),
    },
    "groq": {
        "llama-3.1-8b":  (0.05, 0.08),
        "llama-3.3-70b": (0.59, 0.79),
        "mixtral-8x7b":  (0.24, 0.24),
        "gemma2-9b":     (0.20, 0.20),
        "default":       (0.59, 0.79),
    },
    "gemini": {
        "gemini-1.5-flash": (0.075, 0.30),
        "gemini-1.5-pro":   (3.50,  10.50),
        "gemini-2.0-flash": (0.10,  0.40),
        "default":          (0.075, 0.30),
    },
    "ollama": {"default": (0.0, 0.0)},
    "meta":   {"default": (0.0, 0.0)},
}


def _lookup_rates(provider: str, model: str) -> tuple[float, float]:
    """Return (input_per_million, output_per_million) for provider/model.

    Matches on model prefix so e.g. "claude-sonnet-4-6" maps to "claude-sonnet".
    Falls back to provider "default" if no prefix matches.
    """
    provider_table = PRICING.get(provider.lower(), PRICING.get("ollama", {}))
    model_lower = model.lower()
    # Try longest-matching prefix first
    for prefix in sorted(provider_table.keys(), key=len, reverse=True):
        if prefix == "default":
            continue
        if model_lower.startswith(prefix):
            return provider_table[prefix]
    return provider_table.get("default", (0.0, 0.0))


class CostTracker:
    """Accumulates token usage and USD cost for a CLI session."""

    def __init__(self) -> None:
        self._session_cost_usd: float = 0.0
        self._session_prompt_tokens: int = 0
        self._session_completion_tokens: int = 0

    def add(self, provider: str, model: str,
            prompt_tokens: int, completion_tokens: int) -> float:
        """Record a call's usage and return its cost in USD."""
        cost = self.estimate(provider, model, prompt_tokens, completion_tokens)
        self._session_cost_usd += cost
        self._session_prompt_tokens += prompt_tokens
        self._session_completion_tokens += completion_tokens
        return cost

    def estimate(self, provider: str, model: str,
                 prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost without modifying session totals."""
        input_rate, output_rate = _lookup_rates(provider, model)
        return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000

    def session_summary(self) -> dict:
        """Return session totals."""
        return {
            "total_usd":          self._session_cost_usd,
            "prompt_tokens":      self._session_prompt_tokens,
            "completion_tokens":  self._session_completion_tokens,
        }

    def format_cost(self, usd: float) -> str:
        """Format a USD amount for display.

        Returns '<$0.01' for negligibly small amounts, '$X.XXXX' otherwise.
        """
        if usd < 0.01:
            return "<$0.01"
        return f"${usd:.4f}"

    def reset(self) -> None:
        """Reset all session counters (e.g. after /clear)."""
        self._session_cost_usd = 0.0
        self._session_prompt_tokens = 0
        self._session_completion_tokens = 0


# Module-level singleton used throughout the application.
tracker = CostTracker()
