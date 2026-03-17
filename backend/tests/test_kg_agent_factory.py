"""Tests for UniversalAgentProfile and KGAgentFactory.

Coverage targets:
  - UniversalAgentProfile: frozen, to_oasis_row(), get_stance(), _make_username()
  - KGAgentFactory._filter_agent_eligible_nodes(): LLM path + heuristic fallback
  - KGAgentFactory.generate_from_kg(): full pipeline with mocked LLM
  - KGAgentFactory.generate_agents_csv(): CSV output format and content
  - KGAgentFactory._parse_agent_dict(): missing fields, bad values
  - Edge cases: empty nodes, no eligible nodes, LLM failure, partial LLM output
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.universal_agent_profile import (
    UniversalAgentProfile,
    _make_username,
)
from backend.app.services.kg_agent_factory import KGAgentFactory, _clamp


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    id: str = "test_agent",
    name: str = "Test Agent",
    role: str = "A test role",
    entity_type: str = "Person",
    persona: str = "This agent is a fixture for testing purposes.",
    goals: tuple[str, ...] = ("goal_a", "goal_b"),
    capabilities: tuple[str, ...] = ("cap_1",),
    stance_axes: tuple[tuple[str, float], ...] = (("militarism", 0.5),),
    relationships: tuple[tuple[str, str], ...] = (),
    kg_node_id: str = "node_001",
    openness: float = 0.5,
    conscientiousness: float = 0.6,
    extraversion: float = 0.4,
    agreeableness: float = 0.3,
    neuroticism: float = 0.7,
) -> UniversalAgentProfile:
    return UniversalAgentProfile(
        id=id,
        name=name,
        role=role,
        entity_type=entity_type,
        persona=persona,
        goals=goals,
        capabilities=capabilities,
        stance_axes=stance_axes,
        relationships=relationships,
        kg_node_id=kg_node_id,
        openness=openness,
        conscientiousness=conscientiousness,
        extraversion=extraversion,
        agreeableness=agreeableness,
        neuroticism=neuroticism,
    )


def _make_factory(llm_response: dict | None = None, *, fail: bool = False) -> tuple[KGAgentFactory, MagicMock]:
    """Return a KGAgentFactory with a mocked LLMClient.

    If ``fail`` is True the LLM always raises RuntimeError.
    Otherwise it returns ``llm_response`` (defaulting to an empty agents list).
    """
    mock_llm = MagicMock()
    if fail:
        mock_llm.chat_json = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    else:
        payload = llm_response if llm_response is not None else {"agents": []}
        mock_llm.chat_json = AsyncMock(return_value=payload)
    return KGAgentFactory(llm_client=mock_llm), mock_llm


_SAMPLE_NODES = [
    {"id": "n1", "label": "Supreme Leader", "entity_type": "PoliticalFigure"},
    {"id": "n2", "label": "Defence Ministry", "entity_type": "Military"},
    {"id": "n3", "label": "Trade War", "entity_type": "Concept"},
]

_SAMPLE_EDGES = [
    {"source": "n1", "target": "n2", "relation": "commands"},
]

_SAMPLE_LLM_AGENT = {
    "id": "supreme_leader",
    "name": "最高領袖",
    "role": "National supreme leader",
    "entity_type": "PoliticalFigure",
    "persona": "A determined leader with strong ideological convictions.",
    "goals": ["Preserve national sovereignty", "Resist foreign interference"],
    "capabilities": ["Issue decrees", "Command armed forces"],
    "stance_axes": {"militarism": 0.85, "diplomacy": 0.2},
    "relationships": {"defence_ministry": "commands"},
    "openness": 0.2,
    "conscientiousness": 0.8,
    "extraversion": 0.4,
    "agreeableness": 0.15,
    "neuroticism": 0.3,
    "kg_node_id": "n1",
}


# ---------------------------------------------------------------------------
# UniversalAgentProfile — immutability
# ---------------------------------------------------------------------------


class TestUniversalAgentProfileImmutability:
    def test_frozen_raises_on_attribute_set(self):
        profile = _make_profile()
        with pytest.raises((AttributeError, TypeError)):
            profile.name = "changed"  # type: ignore[misc]

    def test_frozen_raises_on_goals_mutation(self):
        profile = _make_profile()
        with pytest.raises((AttributeError, TypeError)):
            profile.goals = ("new_goal",)  # type: ignore[misc]

    def test_replace_returns_new_object(self):
        profile = _make_profile(openness=0.3)
        updated = replace(profile, openness=0.9)
        assert profile.openness == 0.3
        assert updated.openness == 0.9
        assert profile is not updated

    def test_tuple_fields_are_immutable(self):
        profile = _make_profile(goals=("g1", "g2"))
        assert isinstance(profile.goals, tuple)
        assert isinstance(profile.stance_axes, tuple)
        assert isinstance(profile.relationships, tuple)
        assert isinstance(profile.capabilities, tuple)


# ---------------------------------------------------------------------------
# UniversalAgentProfile — to_oasis_row()
# ---------------------------------------------------------------------------


class TestToOasisRow:
    def test_returns_required_keys(self):
        profile = _make_profile()
        row = profile.to_oasis_row()
        assert set(row.keys()) == {"userid", "user_char", "username"}

    def test_userid_equals_profile_id(self):
        profile = _make_profile(id="iran_supreme_leader")
        assert profile.to_oasis_row()["userid"] == "iran_supreme_leader"

    def test_user_char_equals_persona(self):
        persona = "This is the persona text used by OASIS."
        profile = _make_profile(persona=persona)
        assert profile.to_oasis_row()["user_char"] == persona

    def test_username_is_deterministic(self):
        profile = _make_profile(id="agent_42", name="Test Agent")
        row1 = profile.to_oasis_row()
        row2 = profile.to_oasis_row()
        assert row1["username"] == row2["username"]

    def test_username_differs_for_different_ids(self):
        p1 = _make_profile(id="agent_1", name="Same Name")
        p2 = _make_profile(id="agent_2", name="Same Name")
        assert p1.to_oasis_row()["username"] != p2.to_oasis_row()["username"]

    def test_username_handles_cjk_name(self):
        profile = _make_profile(id="hk_001", name="香港特首")
        row = profile.to_oasis_row()
        username = row["username"]
        assert isinstance(username, str)
        assert len(username) > 0
        # Should end with 6-char hex suffix
        assert len(username.split("_")[-1]) == 6

    def test_username_handles_ascii_name(self):
        profile = _make_profile(id="us_001", name="Joe Biden")
        username = profile.to_oasis_row()["username"]
        assert "joe" in username.lower() or "biden" in username.lower() or len(username) > 6


# ---------------------------------------------------------------------------
# UniversalAgentProfile — get_stance()
# ---------------------------------------------------------------------------


class TestGetStance:
    def test_returns_correct_value(self):
        profile = _make_profile(stance_axes=(("militarism", 0.85), ("diplomacy", 0.1)))
        assert profile.get_stance("militarism") == pytest.approx(0.85)
        assert profile.get_stance("diplomacy") == pytest.approx(0.1)

    def test_returns_default_for_missing_axis(self):
        profile = _make_profile(stance_axes=(("militarism", 0.5),))
        assert profile.get_stance("nonexistent_axis") == pytest.approx(0.5)

    def test_custom_default_value(self):
        profile = _make_profile(stance_axes=())
        assert profile.get_stance("any_axis", default=0.99) == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# _make_username helper
# ---------------------------------------------------------------------------


class TestMakeUsername:
    def test_ascii_name(self):
        slug = _make_username("Joe Biden", "agent_1")
        assert slug.startswith("joe")
        assert len(slug) > 6

    def test_cjk_name_falls_back_to_id(self):
        slug = _make_username("哈梅內伊", "iran_leader")
        # CJK has no ASCII equivalent, so slug should start with id
        assert "iran_leader" in slug

    def test_suffix_length(self):
        slug = _make_username("Test", "id_123")
        suffix = slug.split("_")[-1]
        assert len(suffix) == 6

    def test_deterministic(self):
        s1 = _make_username("Angela Merkel", "de_leader")
        s2 = _make_username("Angela Merkel", "de_leader")
        assert s1 == s2

    def test_different_ids_same_name(self):
        s1 = _make_username("Overlapping Name", "id_a")
        s2 = _make_username("Overlapping Name", "id_b")
        assert s1 != s2


# ---------------------------------------------------------------------------
# _clamp utility
# ---------------------------------------------------------------------------


class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5) == pytest.approx(0.5)

    def test_clamps_below_zero(self):
        assert _clamp(-0.1) == pytest.approx(0.0)

    def test_clamps_above_one(self):
        assert _clamp(1.5) == pytest.approx(1.0)

    def test_boundary_values(self):
        assert _clamp(0.0) == pytest.approx(0.0)
        assert _clamp(1.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# KGAgentFactory._filter_agent_eligible_nodes()
# ---------------------------------------------------------------------------


class TestFilterAgentEligibleNodes:
    @pytest.mark.asyncio
    async def test_returns_eligible_nodes_from_llm(self):
        llm_response = {
            "eligible": [
                {"node_id": "n1", "label": "Supreme Leader", "entity_type": "PoliticalFigure"},
                {"node_id": "n2", "label": "Defence Ministry", "entity_type": "Military"},
            ],
            "excluded": [
                {"node_id": "n3", "label": "Trade War", "reason": "abstract concept"},
            ],
        }
        # Stage 1 uses chat_json; stage 2 never called in this test
        factory, mock_llm = _make_factory(llm_response)
        result = await factory._filter_agent_eligible_nodes(_SAMPLE_NODES)
        assert len(result) == 2
        ids = {n["id"] for n in result}
        assert "n1" in ids
        assert "n2" in ids
        assert "n3" not in ids

    @pytest.mark.asyncio
    async def test_falls_back_to_heuristic_on_llm_failure(self):
        factory, _ = _make_factory(fail=True)
        result = await factory._filter_agent_eligible_nodes(_SAMPLE_NODES)
        # Heuristic should keep actor nodes (PoliticalFigure, Military) and
        # may or may not include Concept depending on label
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_falls_back_when_llm_returns_empty_eligible(self):
        factory, _ = _make_factory({"eligible": [], "excluded": []})
        result = await factory._filter_agent_eligible_nodes(_SAMPLE_NODES)
        # Should fall back to heuristic and return some nodes
        assert len(result) >= 1

    def test_heuristic_filter_keeps_actor_nodes(self):
        nodes = [
            {"id": "a1", "label": "President", "entity_type": "Person"},
            {"id": "a2", "label": "Army Corps", "entity_type": "Military"},
            {"id": "a3", "label": "GDP Growth", "entity_type": "Metric"},
        ]
        result = KGAgentFactory._heuristic_filter(nodes)
        ids = {n["id"] for n in result}
        assert "a1" in ids
        assert "a2" in ids

    def test_heuristic_fallback_on_all_abstract(self):
        nodes = [
            {"id": "c1", "label": "Inflation Rate", "entity_type": "Metric"},
            {"id": "c2", "label": "Historical Period", "entity_type": "TimeSpan"},
        ]
        # If nothing matches, heuristic returns all nodes rather than empty list
        result = KGAgentFactory._heuristic_filter(nodes)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# KGAgentFactory._parse_agent_dict()
# ---------------------------------------------------------------------------


class TestParseAgentDict:
    def test_valid_dict_returns_profile(self):
        result = KGAgentFactory._parse_agent_dict(_SAMPLE_LLM_AGENT)
        assert result is not None
        assert result.id == "supreme_leader"
        assert result.entity_type == "PoliticalFigure"

    def test_missing_required_field_returns_none(self):
        bad = dict(_SAMPLE_LLM_AGENT)
        del bad["persona"]
        result = KGAgentFactory._parse_agent_dict(bad)
        assert result is None

    def test_stance_axes_dict_to_tuple(self):
        result = KGAgentFactory._parse_agent_dict(_SAMPLE_LLM_AGENT)
        assert result is not None
        assert isinstance(result.stance_axes, tuple)
        assert ("militarism", 0.85) in result.stance_axes

    def test_relationships_dict_to_tuple(self):
        result = KGAgentFactory._parse_agent_dict(_SAMPLE_LLM_AGENT)
        assert result is not None
        assert isinstance(result.relationships, tuple)
        assert ("defence_ministry", "commands") in result.relationships

    def test_relationships_as_list(self):
        raw = dict(_SAMPLE_LLM_AGENT)
        raw["relationships"] = [["agent_b", "ally"], ["agent_c", "rival"]]
        result = KGAgentFactory._parse_agent_dict(raw)
        assert result is not None
        assert ("agent_b", "ally") in result.relationships

    def test_big_five_clamped_to_valid_range(self):
        raw = dict(_SAMPLE_LLM_AGENT)
        raw["openness"] = 2.5  # out of range
        raw["neuroticism"] = -0.3  # out of range
        result = KGAgentFactory._parse_agent_dict(raw)
        assert result is not None
        assert 0.0 <= result.openness <= 1.0
        assert 0.0 <= result.neuroticism <= 1.0

    def test_goals_and_capabilities_are_tuples(self):
        result = KGAgentFactory._parse_agent_dict(_SAMPLE_LLM_AGENT)
        assert result is not None
        assert isinstance(result.goals, tuple)
        assert isinstance(result.capabilities, tuple)

    def test_missing_optional_fields_use_defaults(self):
        minimal = {
            "id": "minimal_agent",
            "name": "Minimal",
            "role": "Test role",
            "entity_type": "Person",
            "persona": "A minimal agent.",
        }
        result = KGAgentFactory._parse_agent_dict(minimal)
        assert result is not None
        assert result.openness == pytest.approx(0.5)
        assert result.goals == ()
        assert result.stance_axes == ()

    def test_kg_node_id_falls_back_to_id(self):
        raw = dict(_SAMPLE_LLM_AGENT)
        del raw["kg_node_id"]
        result = KGAgentFactory._parse_agent_dict(raw)
        assert result is not None
        assert result.kg_node_id == raw["id"]


# ---------------------------------------------------------------------------
# KGAgentFactory.generate_from_kg()
# ---------------------------------------------------------------------------


class TestGenerateFromKg:
    @pytest.mark.asyncio
    async def test_raises_on_empty_nodes(self):
        factory, _ = _make_factory()
        with pytest.raises(ValueError, match="empty"):
            await factory.generate_from_kg(nodes=[], edges=[], seed_text="test")

    @pytest.mark.asyncio
    async def test_returns_profiles_for_valid_input(self):
        # Eligibility filter response then profile generation response
        filter_response = {
            "eligible": [{"node_id": "n1", "label": "Supreme Leader"}],
            "excluded": [],
        }
        generation_response = {"agents": [_SAMPLE_LLM_AGENT]}

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(
            side_effect=[filter_response, generation_response]
        )
        factory = KGAgentFactory(llm_client=mock_llm)

        profiles = await factory.generate_from_kg(
            nodes=_SAMPLE_NODES,
            edges=_SAMPLE_EDGES,
            seed_text="Iran nuclear negotiations",
            target_count=1,
        )
        assert len(profiles) == 1
        assert profiles[0].id == "supreme_leader"
        assert isinstance(profiles[0], UniversalAgentProfile)

    @pytest.mark.asyncio
    async def test_profiles_are_frozen(self):
        filter_response = {"eligible": [{"node_id": "n1", "label": "Leader"}], "excluded": []}
        generation_response = {"agents": [_SAMPLE_LLM_AGENT]}

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=[filter_response, generation_response])
        factory = KGAgentFactory(llm_client=mock_llm)

        profiles = await factory.generate_from_kg(
            nodes=_SAMPLE_NODES,
            edges=_SAMPLE_EDGES,
            seed_text="scenario",
        )
        with pytest.raises((AttributeError, TypeError)):
            profiles[0].name = "mutated"  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_raises_when_llm_generation_fails(self):
        filter_response = {"eligible": [{"node_id": "n1"}], "excluded": []}

        mock_llm = MagicMock()
        # First call (filter) succeeds, second call (generation) fails
        mock_llm.chat_json = AsyncMock(
            side_effect=[filter_response, RuntimeError("LLM down")]
        )
        factory = KGAgentFactory(llm_client=mock_llm)

        with pytest.raises(RuntimeError, match="LLM profile generation failed"):
            await factory.generate_from_kg(
                nodes=_SAMPLE_NODES,
                edges=_SAMPLE_EDGES,
                seed_text="scenario",
            )

    @pytest.mark.asyncio
    async def test_falls_back_to_all_nodes_when_no_eligible(self):
        """When filter returns empty eligible, factory falls back to all nodes."""
        filter_response = {"eligible": [], "excluded": []}
        generation_response = {"agents": [_SAMPLE_LLM_AGENT]}

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=[filter_response, generation_response])
        factory = KGAgentFactory(llm_client=mock_llm)

        profiles = await factory.generate_from_kg(
            nodes=_SAMPLE_NODES,
            edges=_SAMPLE_EDGES,
            seed_text="scenario",
        )
        # Should still produce profiles using fallback nodes
        assert len(profiles) >= 1

    @pytest.mark.asyncio
    async def test_target_count_none_uses_eligible_count(self):
        """When target_count is None, target equals len(eligible_nodes)."""
        filter_response = {
            "eligible": [
                {"node_id": "n1", "label": "A"},
                {"node_id": "n2", "label": "B"},
            ],
            "excluded": [],
        }
        generation_response = {"agents": [_SAMPLE_LLM_AGENT]}

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=[filter_response, generation_response])
        factory = KGAgentFactory(llm_client=mock_llm)

        await factory.generate_from_kg(
            nodes=_SAMPLE_NODES[:2],
            edges=_SAMPLE_EDGES,
            seed_text="scenario",
            target_count=None,
        )
        # Second call (generation) should have been made with target_count=2 in prompt
        second_call_kwargs = mock_llm.chat_json.call_args_list[1]
        user_msg = second_call_kwargs[1]["messages"][-1]["content"]
        assert "2" in user_msg  # target count embedded in prompt


# ---------------------------------------------------------------------------
# KGAgentFactory.generate_agents_csv()
# ---------------------------------------------------------------------------


class TestGenerateAgentsCsv:
    def test_writes_valid_csv(self, tmp_path):
        factory = KGAgentFactory(llm_client=MagicMock())
        profile = _make_profile(
            id="agent_001",
            name="Test Agent",
            persona="Test persona text.",
        )
        output = str(tmp_path / "agents.csv")
        returned_path = factory.generate_agents_csv([profile], output)

        assert returned_path == os.path.abspath(output)
        assert os.path.exists(returned_path)

        with open(returned_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["userid"] == "agent_001"
        assert rows[0]["user_char"] == "Test persona text."
        assert len(rows[0]["username"]) > 0

    def test_csv_has_correct_headers(self, tmp_path):
        factory = KGAgentFactory(llm_client=MagicMock())
        profile = _make_profile()
        output = str(tmp_path / "agents.csv")
        factory.generate_agents_csv([profile], output)

        with open(output, newline="", encoding="utf-8") as fh:
            header_line = fh.readline().strip()

        assert "userid" in header_line
        assert "user_char" in header_line
        assert "username" in header_line

    def test_multiple_profiles_written(self, tmp_path):
        factory = KGAgentFactory(llm_client=MagicMock())
        profiles = [
            _make_profile(id=f"agent_{i}", name=f"Agent {i}")
            for i in range(5)
        ]
        output = str(tmp_path / "multi.csv")
        factory.generate_agents_csv(profiles, output)

        with open(output, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 5

    def test_raises_on_empty_profiles(self, tmp_path):
        factory = KGAgentFactory(llm_client=MagicMock())
        with pytest.raises(ValueError, match="empty"):
            factory.generate_agents_csv([], str(tmp_path / "empty.csv"))

    def test_creates_parent_directory(self, tmp_path):
        factory = KGAgentFactory(llm_client=MagicMock())
        profile = _make_profile()
        nested = str(tmp_path / "deep" / "nested" / "agents.csv")
        factory.generate_agents_csv([profile], nested)
        assert os.path.exists(nested)

    def test_returns_absolute_path(self, tmp_path):
        factory = KGAgentFactory(llm_client=MagicMock())
        profile = _make_profile()
        output = str(tmp_path / "out.csv")
        result = factory.generate_agents_csv([profile], output)
        assert os.path.isabs(result)

    def test_cjk_names_encoded_correctly(self, tmp_path):
        factory = KGAgentFactory(llm_client=MagicMock())
        profile = _make_profile(id="hk_leader", name="行政長官", persona="CJK persona: 你好世界。")
        output = str(tmp_path / "cjk.csv")
        factory.generate_agents_csv([profile], output)

        with open(output, newline="", encoding="utf-8") as fh:
            content = fh.read()

        assert "CJK persona" in content


# ---------------------------------------------------------------------------
# Integration-style: full pipeline with two-stage mocked LLM
# ---------------------------------------------------------------------------


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_produces_oasis_compatible_csv(self, tmp_path):
        filter_response = {
            "eligible": [{"node_id": "n1", "label": "Supreme Leader"}],
            "excluded": [],
        }
        generation_response = {"agents": [_SAMPLE_LLM_AGENT]}

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=[filter_response, generation_response])
        factory = KGAgentFactory(llm_client=mock_llm)

        profiles = await factory.generate_from_kg(
            nodes=_SAMPLE_NODES,
            edges=_SAMPLE_EDGES,
            seed_text="Iran nuclear scenario 2024",
            target_count=5,
        )
        csv_path = factory.generate_agents_csv(profiles, str(tmp_path / "agents.csv"))

        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["userid"] == "supreme_leader"
        assert "determined leader" in rows[0]["user_char"]
        assert len(rows[0]["username"]) > 6

    @pytest.mark.asyncio
    async def test_pipeline_with_multiple_agents(self, tmp_path):
        second_agent = dict(_SAMPLE_LLM_AGENT)
        second_agent["id"] = "defence_ministry"
        second_agent["name"] = "Defence Ministry"
        second_agent["kg_node_id"] = "n2"

        filter_response = {
            "eligible": [
                {"node_id": "n1", "label": "Supreme Leader"},
                {"node_id": "n2", "label": "Defence Ministry"},
            ],
            "excluded": [],
        }
        generation_response = {"agents": [_SAMPLE_LLM_AGENT, second_agent]}

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=[filter_response, generation_response])
        factory = KGAgentFactory(llm_client=mock_llm)

        profiles = await factory.generate_from_kg(
            nodes=_SAMPLE_NODES,
            edges=_SAMPLE_EDGES,
            seed_text="Geopolitical conflict scenario",
        )

        assert len(profiles) == 2
        assert {p.id for p in profiles} == {"supreme_leader", "defence_ministry"}


# ---------------------------------------------------------------------------
# KGAgentFactory.generate_fingerprints()
# ---------------------------------------------------------------------------


class TestGenerateFingerprints:
    @pytest.mark.asyncio
    async def test_generate_fingerprints_returns_one_per_profile(self):
        """generate_fingerprints() returns one CognitiveFingerprint per profile."""
        from backend.app.models.cognitive_fingerprint import CognitiveFingerprint
        factory = KGAgentFactory()
        profiles = [_make_profile(id="agent_1"), _make_profile(id="agent_2")]

        mock_response = {
            "fingerprints": [
                {
                    "agent_id": "agent_1",
                    "values": {"authority": 0.8, "loyalty": 0.7, "fairness": 0.3},
                    "info_diet": ["state_media"],
                    "group_memberships": ["hardliner"],
                    "susceptibility": {"military_escalation": 0.9},
                    "confirmation_bias": 0.8,
                    "conformity": 0.3,
                },
                {
                    "agent_id": "agent_2",
                    "values": {"authority": 0.3, "loyalty": 0.5, "fairness": 0.8},
                    "info_diet": ["independent_media"],
                    "group_memberships": ["moderate"],
                    "susceptibility": {"diplomatic_appeal": 0.7},
                    "confirmation_bias": 0.4,
                    "conformity": 0.6,
                },
            ]
        }

        with patch.object(factory._llm, "chat_json", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            fingerprints = await factory.generate_fingerprints(
                profiles=profiles, seed_text="Iran nuclear scenario", active_metrics=("escalation_index",)
            )

        assert len(fingerprints) == 2
        assert all(isinstance(fp, CognitiveFingerprint) for fp in fingerprints)
        assert fingerprints[0].agent_id == "agent_1"
        assert fingerprints[1].confirmation_bias == 0.4
