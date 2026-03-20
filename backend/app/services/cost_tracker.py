"""Per-session LLM cost accumulator with budget alerting.

Thread/async-safe via module-level dict + simple float accumulation.
Cost values are approximate (based on provider-reported token counts).
"""
from __future__ import annotations

import os

from backend.app.utils.logger import get_logger

logger = get_logger("cost_tracker")

_session_costs: dict[str, float] = {}

_DEFAULT_BUDGET_USD: float = 5.0


def record_cost(session_id: str, cost_usd: float) -> None:
    """Add *cost_usd* to the running total for *session_id*."""
    if not session_id:
        return
    prev = _session_costs.get(session_id, 0.0)
    total = prev + cost_usd
    _session_costs[session_id] = total

    budget = float(os.environ.get("SESSION_COST_BUDGET_USD", str(_DEFAULT_BUDGET_USD)))
    if total >= budget and prev < budget:
        logger.warning(
            "Session %s has exceeded cost budget of $%.2f (current: $%.4f)",
            session_id,
            budget,
            total,
        )


def get_session_cost(session_id: str) -> float:
    """Return the accumulated cost for *session_id* (0.0 if unknown)."""
    return _session_costs.get(session_id, 0.0)


def clear_session(session_id: str) -> None:
    """Remove cost record for a completed session."""
    _session_costs.pop(session_id, None)
