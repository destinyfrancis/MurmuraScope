"""Per-session LLM cost accumulator with budget alerting and hard cap.

Async-safe via module-level asyncio.Lock to prevent concurrent cost loss.
Cost values are approximate (based on provider-reported token counts).
"""
from __future__ import annotations

import asyncio
import os

from backend.app.utils.logger import get_logger

logger = get_logger("cost_tracker")

_cost_lock = asyncio.Lock()
_session_costs: dict[str, float] = {}
_session_paused: dict[str, bool] = {}
# Per-session asyncio.Event used by the simulation loop to wait for resume
_resume_events: dict[str, asyncio.Event] = {}

_DEFAULT_BUDGET_USD: float = 5.0
_DEFAULT_HARD_CAP_USD: float = 10.0


async def record_cost(session_id: str, cost_usd: float) -> None:
    """Add *cost_usd* to the running total for *session_id*.

    Fires a WARNING alert when the soft budget is crossed.
    Sets the session to paused state when the hard cap is crossed.
    """
    if not session_id:
        return
    async with _cost_lock:
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

    hard_cap = float(
        os.environ.get("SESSION_COST_HARD_CAP_USD", str(_DEFAULT_HARD_CAP_USD))
    )
    prev_paused = _session_paused.get(session_id, False)
    if total >= hard_cap and not prev_paused:
        _session_paused[session_id] = True
        # Ensure a resume event exists so the simulation loop can wait on it
        if session_id not in _resume_events:
            _resume_events[session_id] = asyncio.Event()
        logger.warning(
            "Session %s has hit the hard cost cap of $%.2f (current: $%.4f) — simulation paused",
            session_id,
            hard_cap,
            total,
        )


def is_paused(session_id: str) -> bool:
    """Return True if the session has been paused due to exceeding the hard cap."""
    return _session_paused.get(session_id, False)


def resume(session_id: str) -> None:
    """Resume a paused session.

    Clears the paused flag and signals the asyncio.Event so that any
    simulation loop awaiting ``wait_for_resume()`` can proceed.
    """
    _session_paused[session_id] = False
    event = _resume_events.get(session_id)
    if event is not None:
        event.set()
    logger.info("Session %s resumed after cost pause", session_id)


async def wait_for_resume(session_id: str, timeout_s: float = 1800.0) -> bool:
    """Wait up to *timeout_s* seconds for the session to be resumed.

    Returns True if resumed within the timeout, False if timed out.
    Called by the simulation loop when ``is_paused()`` returns True.
    """
    if session_id not in _resume_events:
        _resume_events[session_id] = asyncio.Event()
    event = _resume_events[session_id]
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
        return True
    except asyncio.TimeoutError:
        return False


def get_cost_estimate(
    rounds_completed: int,
    total_rounds: int,
    session_id: str,
) -> float:
    """Project final cost based on the current spend rate.

    Args:
        rounds_completed: Number of rounds finished so far.
        total_rounds: Total rounds planned for the session.
        session_id: Session identifier.

    Returns:
        Projected total cost in USD.  Returns current cost when
        ``rounds_completed`` is 0 to avoid division by zero.
    """
    current = _session_costs.get(session_id, 0.0)
    if rounds_completed <= 0 or total_rounds <= 0:
        return current
    rate_per_round = current / rounds_completed
    return rate_per_round * total_rounds


def get_session_cost(session_id: str) -> float:
    """Return the accumulated cost for *session_id* (0.0 if unknown)."""
    return _session_costs.get(session_id, 0.0)


def clear_session(session_id: str) -> None:
    """Remove cost record for a completed session."""
    _session_costs.pop(session_id, None)
    _session_paused.pop(session_id, None)
    event = _resume_events.pop(session_id, None)
    if event is not None:
        event.set()  # Unblock any waiter so it does not leak
