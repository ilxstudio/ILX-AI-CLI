"""Session cost tracker for ILX AI CLI.

Tracks cumulative token usage and USD cost across all LLM calls in a session.
Per-provider breakdown is tracked via ``SessionUsage`` dataclasses so that the
``/cost`` command can show a detailed table.

A module-level singleton ``tracker`` is used by chat_session.py and the
/cost command.

Pricing table (USD per million tokens):
  (input_per_million, output_per_million)

MIT License 2026 ILX Studio
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

_log = logging.getLogger("ilx_cli.cost_tracker")

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
    for prefix in sorted(provider_table.keys(), key=len, reverse=True):
        if prefix == "default":
            continue
        if model_lower.startswith(prefix):
            return provider_table[prefix]
    return provider_table.get("default", (0.0, 0.0))


@dataclass
class SessionUsage:
    """Per-provider/model token and cost accumulator for one session."""
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0

    @property
    def cost_usd(self) -> float:
        """Compute USD cost from the PRICING table."""
        input_rate, output_rate = _lookup_rates(self.provider, self.model)
        return (
            self.input_tokens * input_rate + self.output_tokens * output_rate
        ) / 1_000_000


class CostTracker:
    """Accumulates token usage and USD cost for a CLI session."""

    def __init__(self) -> None:
        self._session_cost_usd: float = 0.0
        self._session_prompt_tokens: int = 0
        self._session_completion_tokens: int = 0
        # Keyed by (provider_lower, model_lower) for per-provider breakdown
        self._usage: dict[tuple[str, str], SessionUsage] = {}

    def add(self, provider: str, model: str,
            prompt_tokens: int, completion_tokens: int) -> float:
        """Record a call's usage and return its cost in USD."""
        cost = self.estimate(provider, model, prompt_tokens, completion_tokens)
        self._session_cost_usd += cost
        self._session_prompt_tokens += prompt_tokens
        self._session_completion_tokens += completion_tokens
        return cost

    def record_usage(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record token usage for *provider*/*model* and update running totals.

        Writes per-(provider, model) breakdown used by ``format_session_report``
        and also updates the legacy aggregate counters via ``add()``.
        """
        key = (provider.lower(), model.lower())
        if key not in self._usage:
            self._usage[key] = SessionUsage(provider=provider, model=model)
        entry = self._usage[key]
        entry.input_tokens += input_tokens
        entry.output_tokens += output_tokens
        entry.requests += 1
        self.add(provider, model, input_tokens, output_tokens)
        _log.debug(
            "record_usage: provider=%s model=%s in=%d out=%d cost=$%.6f",
            provider, model, input_tokens, output_tokens, entry.cost_usd,
        )

    def estimate(self, provider: str, model: str,
                 prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost without modifying session totals."""
        input_rate, output_rate = _lookup_rates(provider, model)
        return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000

    def session_summary(self) -> dict:
        """Return aggregate totals plus per-provider breakdown list."""
        breakdown = []
        for (prov, mdl), entry in sorted(self._usage.items()):
            breakdown.append({
                "provider":      entry.provider,
                "model":         entry.model,
                "requests":      entry.requests,
                "input_tokens":  entry.input_tokens,
                "output_tokens": entry.output_tokens,
                "cost_usd":      entry.cost_usd,
            })
        return {
            "total_usd":          self._session_cost_usd,
            "prompt_tokens":      self._session_prompt_tokens,
            "completion_tokens":  self._session_completion_tokens,
            "breakdown":          breakdown,
        }

    def format_cost(self, usd: float) -> str:
        """Format a USD amount for display.

        Returns '<$0.01' for negligibly small amounts, '$X.XXXX' otherwise.
        """
        if usd < 0.01:
            return "<$0.01"
        return f"${usd:.4f}"

    def format_session_report(self) -> str:
        """Return a human-readable table: provider | model | requests | tokens | cost."""
        summary = self.session_summary()
        total_usd  = summary["total_usd"]
        prompt_tok = summary["prompt_tokens"]
        comp_tok   = summary["completion_tokens"]
        breakdown  = summary["breakdown"]

        if not breakdown:
            cost_str  = self.format_cost(total_usd)
            total_tok = prompt_tok + comp_tok
            return (
                f"Session cost: {cost_str}  "
                f"({total_tok:,} tokens: {prompt_tok:,} prompt + {comp_tok:,} completion)"
            )

        col_p = max(len("Provider"), max(len(r["provider"]) for r in breakdown))
        col_m = max(len("Model"),    max(len(r["model"])    for r in breakdown))
        header = (
            f"  {'Provider':<{col_p}}  {'Model':<{col_m}}"
            f"  {'Req':>5}  {'Input':>9}  {'Output':>9}  {'Cost':>10}"
        )
        sep = "  " + "-" * (col_p + col_m + 44)
        lines = [header, sep]
        for row in breakdown:
            lines.append(
                f"  {row['provider']:<{col_p}}  {row['model']:<{col_m}}"
                f"  {row['requests']:>5}  {row['input_tokens']:>9,}"
                f"  {row['output_tokens']:>9,}  {self.format_cost(row['cost_usd']):>10}"
            )
        lines.append(sep)
        lines.append(
            f"  {'TOTAL':<{col_p + col_m + 2}}"
            f"  {sum(r['requests'] for r in breakdown):>5}"
            f"  {prompt_tok:>9,}  {comp_tok:>9,}"
            f"  {self.format_cost(total_usd):>10}"
        )
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all session counters (e.g. after /clear)."""
        self._session_cost_usd = 0.0
        self._session_prompt_tokens = 0
        self._session_completion_tokens = 0
        self._usage.clear()


# Module-level singleton used throughout the application.
tracker = CostTracker()
