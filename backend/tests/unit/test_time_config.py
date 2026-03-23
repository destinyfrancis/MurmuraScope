"""Tests for TimeConfig model."""

from backend.app.models.time_config import TimeConfig


def test_time_config_creation():
    tc = TimeConfig(
        total_simulated_hours=720,
        minutes_per_round=1440,
        round_label_unit="day",
        rationale="Geopolitical conflict: 30 days, 1 day per round",
    )
    assert tc.total_simulated_hours == 720
    assert tc.minutes_per_round == 1440
    assert tc.round_label_unit == "day"


def test_time_config_frozen():
    tc = TimeConfig(
        total_simulated_hours=72,
        minutes_per_round=60,
        round_label_unit="hour",
        rationale="Social media: 72 hours, 1 hour per round",
    )
    try:
        tc.total_simulated_hours = 100
        assert False, "Should raise FrozenInstanceError"
    except AttributeError:
        pass


def test_time_config_round_label():
    tc = TimeConfig(
        total_simulated_hours=720,
        minutes_per_round=1440,
        round_label_unit="day",
        rationale="test",
    )
    assert tc.round_label(1) == "Day 1"
    assert tc.round_label(30) == "Day 30"


def test_time_config_round_label_hour():
    tc = TimeConfig(
        total_simulated_hours=72,
        minutes_per_round=60,
        round_label_unit="hour",
        rationale="test",
    )
    assert tc.round_label(1) == "Hour 1"


from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_infer_time_config_geopolitical():
    """LLM suggests daily granularity for geopolitical scenarios."""
    from backend.app.services.zero_config import ZeroConfigService

    mock_llm = AsyncMock()
    mock_llm.chat.return_value = type(
        "R",
        (),
        {
            "content": '{"total_simulated_hours": 720, "minutes_per_round": 1440, "round_label_unit": "day", "rationale": "30-day geopolitical conflict"}'
        },
    )()

    zc = ZeroConfigService()
    tc = await zc.infer_time_config("USA-Israel-Iran military conflict", round_count=30, llm=mock_llm)
    assert tc.round_label_unit == "day"
    assert tc.minutes_per_round == 1440


@pytest.mark.asyncio
async def test_infer_time_config_fallback_on_error():
    """Falls back to 1-day-per-round when LLM fails."""
    from backend.app.services.zero_config import ZeroConfigService

    mock_llm = AsyncMock()
    mock_llm.chat.side_effect = Exception("LLM down")

    zc = ZeroConfigService()
    tc = await zc.infer_time_config("anything", round_count=20, llm=mock_llm)
    assert tc.minutes_per_round == 1440
    assert tc.round_label_unit == "day"
