"""LLM cost estimation for simulation sessions.

Provides pre-run cost estimates based on provider pricing,
agent count, and round count.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.utils.llm_client import _PROVIDERS


@dataclass(frozen=True)
class CostBreakdown:
    """Immutable cost estimate for a simulation run."""

    provider: str
    model: str
    agent_count: int
    round_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    currency: str = "USD"


# Average tokens per agent per round (empirical from HK simulations)
_AVG_INPUT_TOKENS_PER_AGENT_ROUND = 800
_AVG_OUTPUT_TOKENS_PER_AGENT_ROUND = 200


def estimate_cost(
    provider: str,
    model: str | None,
    agent_count: int,
    round_count: int,
) -> CostBreakdown:
    """Estimate LLM cost for a simulation run.

    Args:
        provider: LLM provider name (openrouter, fireworks, etc.)
        model: Model name override (uses provider default if None).
        agent_count: Number of agents.
        round_count: Number of simulation rounds.

    Returns:
        Immutable CostBreakdown with token and cost estimates.
    """
    cfg = _PROVIDERS.get(provider, _PROVIDERS["openrouter"])
    resolved_model = model or cfg.get("default_model", "unknown")

    total_interactions = agent_count * round_count
    est_input = total_interactions * _AVG_INPUT_TOKENS_PER_AGENT_ROUND
    est_output = total_interactions * _AVG_OUTPUT_TOKENS_PER_AGENT_ROUND

    input_cost = (est_input / 1000) * cfg.get("cost_per_1k_input", 0.0)
    output_cost = (est_output / 1000) * cfg.get("cost_per_1k_output", 0.0)
    total_cost = round(input_cost + output_cost, 4)

    return CostBreakdown(
        provider=provider,
        model=resolved_model,
        agent_count=agent_count,
        round_count=round_count,
        estimated_input_tokens=est_input,
        estimated_output_tokens=est_output,
        estimated_cost_usd=total_cost,
    )
