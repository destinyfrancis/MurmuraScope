"""Tests for cost_tracker — async record_cost with lock, budget alerting."""

from __future__ import annotations

import asyncio

import pytest

from backend.app.services.cost_tracker import (
    clear_session,
    get_session_cost,
    record_cost,
)


# ---------------------------------------------------------------------------
# Basic cost accumulation
# ---------------------------------------------------------------------------


class TestRecordCost:
    @pytest.mark.asyncio
    async def test_accumulates_cost(self) -> None:
        sid = "test-cost-001"
        clear_session(sid)
        await record_cost(sid, 0.50)
        await record_cost(sid, 0.25)
        assert get_session_cost(sid) == pytest.approx(0.75)
        clear_session(sid)

    @pytest.mark.asyncio
    async def test_empty_session_id_noop(self) -> None:
        await record_cost("", 1.0)
        assert get_session_cost("") == 0.0

    @pytest.mark.asyncio
    async def test_clear_session_resets(self) -> None:
        sid = "test-cost-002"
        await record_cost(sid, 1.0)
        clear_session(sid)
        assert get_session_cost(sid) == 0.0


# ---------------------------------------------------------------------------
# Concurrent safety (H10)
# ---------------------------------------------------------------------------


class TestConcurrentSafety:
    @pytest.mark.asyncio
    async def test_concurrent_record_cost_no_loss(self) -> None:
        """H10: Many concurrent record_cost calls should not lose any cost."""
        sid = "test-cost-concurrent"
        clear_session(sid)
        n = 100
        cost_per_call = 0.01

        async def add_cost() -> None:
            await record_cost(sid, cost_per_call)

        await asyncio.gather(*(add_cost() for _ in range(n)))

        total = get_session_cost(sid)
        assert total == pytest.approx(n * cost_per_call, abs=1e-9), (
            f"Expected {n * cost_per_call}, got {total} — cost lost to race condition"
        )
        clear_session(sid)
