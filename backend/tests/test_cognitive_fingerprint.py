# backend/tests/test_cognitive_fingerprint.py
"""Tests for CognitiveFingerprint model."""
from __future__ import annotations
import dataclasses
import pytest
from backend.app.models.cognitive_fingerprint import CognitiveFingerprint


def _make_valid() -> CognitiveFingerprint:
    return CognitiveFingerprint(
        agent_id="iran_supreme_leader",
        values={"authority": 0.9, "loyalty": 0.8, "fairness": 0.2},
        info_diet=("state_media", "religious_channels"),
        group_memberships=("hardliner_faction",),
        susceptibility={"military_escalation": 0.8, "diplomatic_appeal": 0.1},
        confirmation_bias=0.85,
        conformity=0.3,
    )


def test_frozen():
    fp = _make_valid()
    with pytest.raises(dataclasses.FrozenInstanceError):
        fp.confirmation_bias = 0.5  # type: ignore


def test_valid_creation():
    fp = _make_valid()
    assert fp.agent_id == "iran_supreme_leader"
    assert fp.confirmation_bias == 0.85


def test_values_min_keys():
    with pytest.raises(ValueError, match="values must have 3–12 keys"):
        CognitiveFingerprint(
            agent_id="x", values={"a": 0.5, "b": 0.5},
            info_diet=("x",), group_memberships=(), susceptibility={},
            confirmation_bias=0.5, conformity=0.5,
        )


def test_values_max_keys():
    with pytest.raises(ValueError, match="values must have 3–12 keys"):
        CognitiveFingerprint(
            agent_id="x",
            values={str(i): 0.5 for i in range(13)},
            info_diet=("x",), group_memberships=(), susceptibility={},
            confirmation_bias=0.5, conformity=0.5,
        )


def test_values_range_clamped():
    # Values outside [0,1] should raise
    with pytest.raises(ValueError, match="values must be in"):
        CognitiveFingerprint(
            agent_id="x",
            values={"a": 1.5, "b": 0.5, "c": 0.1},
            info_diet=("x",), group_memberships=(), susceptibility={},
            confirmation_bias=0.5, conformity=0.5,
        )


def test_empty_info_diet():
    with pytest.raises(ValueError, match="info_diet must not be empty"):
        CognitiveFingerprint(
            agent_id="x",
            values={"a": 0.5, "b": 0.4, "c": 0.3},
            info_diet=(),
            group_memberships=(), susceptibility={},
            confirmation_bias=0.5, conformity=0.5,
        )


def test_bias_conformity_clamped():
    with pytest.raises(ValueError, match="confirmation_bias must be in"):
        CognitiveFingerprint(
            agent_id="x",
            values={"a": 0.5, "b": 0.4, "c": 0.3},
            info_diet=("x",), group_memberships=(), susceptibility={},
            confirmation_bias=1.5, conformity=0.5,
        )
