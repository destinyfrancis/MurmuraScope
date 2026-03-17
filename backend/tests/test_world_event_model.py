# backend/tests/test_world_event_model.py
"""Tests for WorldEvent model."""
from __future__ import annotations
import dataclasses
import pytest
from backend.app.models.world_event import WorldEvent


def _make_valid() -> WorldEvent:
    return WorldEvent(
        event_id="evt_001",
        round_number=3,
        content="Iran announces suspension of nuclear talks.",
        event_type="official",
        reach=("ALL",),
        impact_vector={"escalation_index": 0.15, "diplomatic_pressure": -0.10},
        credibility=0.9,
    )


def test_frozen():
    ev = _make_valid()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.credibility = 0.5  # type: ignore


def test_valid_creation():
    ev = _make_valid()
    assert ev.event_id == "evt_001"
    assert ev.round_number == 3


def test_invalid_event_type():
    with pytest.raises(ValueError, match="event_type must be one of"):
        WorldEvent(
            event_id="x", round_number=1, content="test",
            event_type="unknown", reach=("ALL",),
            impact_vector={}, credibility=0.5,
        )


def test_empty_reach():
    with pytest.raises(ValueError, match="reach must not be empty"):
        WorldEvent(
            event_id="x", round_number=1, content="test",
            event_type="shock", reach=(),
            impact_vector={}, credibility=0.5,
        )


def test_credibility_range():
    with pytest.raises(ValueError, match="credibility must be in"):
        WorldEvent(
            event_id="x", round_number=1, content="test",
            event_type="shock", reach=("ALL",),
            impact_vector={}, credibility=1.5,
        )


def test_reaches_agent_matching_diet():
    ev = WorldEvent(
        event_id="x", round_number=1, content="test",
        event_type="rumor", reach=("state_media", "religious_channels"),
        impact_vector={}, credibility=0.7,
    )
    assert ev.reaches_agent(info_diet=("state_media",))
    assert not ev.reaches_agent(info_diet=("opposition_press",))


def test_reaches_agent_all_broadcast():
    ev = _make_valid()  # reach=("ALL",)
    assert ev.reaches_agent(info_diet=("anything",))
    assert ev.reaches_agent(info_diet=())
