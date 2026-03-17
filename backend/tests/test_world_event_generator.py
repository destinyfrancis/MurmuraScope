# backend/tests/test_world_event_generator.py
"""Tests for WorldEventGenerator service."""
from __future__ import annotations
from unittest.mock import AsyncMock, patch
import pytest
from backend.app.models.world_event import WorldEvent
from backend.app.services.world_event_generator import WorldEventGenerator


_MOCK_LLM_RESPONSE = {
    "events": [
        {
            "event_id": "evt_r3_001",
            "content": "Iran announces suspension of nuclear talks.",
            "event_type": "official",
            "reach": ["ALL"],
            "impact_vector": {"escalation_index": 0.15},
            "credibility": 0.9,
        },
        {
            "event_id": "evt_r3_002",
            "content": "Leaked memo suggests US is divided on sanctions.",
            "event_type": "rumor",
            "reach": ["intelligence_media"],
            "impact_vector": {"diplomatic_pressure": -0.05},
            "credibility": 0.5,
        },
    ]
}


@pytest.mark.asyncio
async def test_generate_returns_world_events():
    gen = WorldEventGenerator()
    with patch.object(gen._llm, "chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _MOCK_LLM_RESPONSE
        events = await gen.generate(
            scenario_description="US-Iran conflict 2026",
            round_number=3,
            active_metrics=("escalation_index", "diplomatic_pressure"),
            prev_dominant_stance={"escalation_index": 0.6},
            event_history=[],
        )
    assert len(events) == 2
    assert all(isinstance(e, WorldEvent) for e in events)
    assert events[0].event_type == "official"


@pytest.mark.asyncio
async def test_generate_filters_unknown_metric_keys():
    """impact_vector keys not in active_metrics are silently dropped."""
    response = {"events": [{
        "event_id": "x", "content": "test", "event_type": "shock",
        "reach": ["ALL"],
        "impact_vector": {"known_metric": 0.1, "unknown_metric": 0.9},
        "credibility": 0.8,
    }]}
    gen = WorldEventGenerator()
    with patch.object(gen._llm, "chat_json", new_callable=AsyncMock) as m:
        m.return_value = response
        events = await gen.generate(
            scenario_description="test",
            round_number=1,
            active_metrics=("known_metric",),
            prev_dominant_stance={},
            event_history=[],
        )
    assert "unknown_metric" not in events[0].impact_vector
    assert "known_metric" in events[0].impact_vector


@pytest.mark.asyncio
async def test_generate_returns_empty_on_llm_failure():
    gen = WorldEventGenerator()
    with patch.object(gen._llm, "chat_json", side_effect=RuntimeError("LLM down")):
        events = await gen.generate(
            scenario_description="test", round_number=1,
            active_metrics=("m1",), prev_dominant_stance={}, event_history=[],
        )
    assert events == []
