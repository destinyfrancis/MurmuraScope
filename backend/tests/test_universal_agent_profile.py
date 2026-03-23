# backend/tests/test_universal_agent_profile.py
"""Tests for UniversalAgentProfile frozen dataclass."""

from __future__ import annotations

import dataclasses

import pytest

from backend.app.models.universal_agent_profile import UniversalAgentProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_profile(**overrides) -> UniversalAgentProfile:
    """Construct a minimal valid UniversalAgentProfile."""
    defaults = dict(
        id="test_agent",
        name="Test Agent",
        role="Tester",
        entity_type="Person",
        persona="A test persona for unit testing.",
        goals=(),
        capabilities=(),
        stance_axes=(),
        relationships=(),
        kg_node_id="graph1234_test_agent",
    )
    defaults.update(overrides)
    return UniversalAgentProfile(**defaults)


# ---------------------------------------------------------------------------
# Existing field tests (sanity)
# ---------------------------------------------------------------------------


def test_universal_agent_profile_minimal_construction():
    """A minimal profile constructs without error."""
    profile = _make_minimal_profile()
    assert profile.id == "test_agent"
    assert profile.name == "Test Agent"


def test_universal_agent_profile_is_frozen():
    """Mutations must raise FrozenInstanceError."""
    profile = _make_minimal_profile()
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.name = "changed"  # type: ignore


def test_universal_agent_profile_get_stance_missing_returns_default():
    profile = _make_minimal_profile(stance_axes=(("hawkish", 0.8),))
    assert profile.get_stance("dovish") == 0.5
    assert profile.get_stance("hawkish") == 0.8


def test_universal_agent_profile_to_oasis_row_keys():
    profile = _make_minimal_profile()
    row = profile.to_oasis_row()
    assert set(row.keys()) == {"userid", "user_char", "username"}


# ---------------------------------------------------------------------------
# NEW FIELD TESTS (Task 2) — expected to FAIL before implementation
# ---------------------------------------------------------------------------


def test_universal_agent_profile_new_fields_have_defaults():
    """New fields default to empty — backward compat for existing code."""
    profile = UniversalAgentProfile(
        id="test",
        name="Test",
        role="Tester",
        entity_type="Person",
        persona="A test persona.",
        goals=(),
        capabilities=(),
        stance_axes=(),
        relationships=(),
        kg_node_id="graph1234_test",
    )
    assert profile.communication_style == ""
    assert profile.vocabulary_hints == ()
    assert profile.platform_persona == ""


def test_universal_agent_profile_new_fields_set():
    """New fields accept and store provided values."""
    profile = UniversalAgentProfile(
        id="test",
        name="Test",
        role="Student",
        entity_type="Student",
        persona="A student.",
        goals=(),
        capabilities=(),
        stance_axes=(),
        relationships=(),
        kg_node_id="graph1234_test",
        communication_style="casual_gen_z",
        vocabulary_hints=("遊戲比喻", "不公平"),
        platform_persona="Facebook: 長文; Instagram: 短句",
    )
    assert profile.communication_style == "casual_gen_z"
    assert "遊戲比喻" in profile.vocabulary_hints
    assert profile.platform_persona == "Facebook: 長文; Instagram: 短句"


def test_universal_agent_profile_new_fields_are_frozen():
    """New fields participate in immutability — cannot be mutated."""
    profile = _make_minimal_profile(
        communication_style="formal_academic",
        vocabulary_hints=("程序正義",),
        platform_persona="Twitter: 短句",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.communication_style = "changed"  # type: ignore


def test_universal_agent_profile_vocabulary_hints_is_tuple():
    """vocabulary_hints must be a tuple (not list) for immutability."""
    profile = _make_minimal_profile(vocabulary_hints=("申訴機制", "法律程序"))
    assert isinstance(profile.vocabulary_hints, tuple)
