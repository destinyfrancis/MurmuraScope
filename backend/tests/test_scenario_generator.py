"""Tests for UniversalScenarioConfig model and ScenarioGenerator service.

Coverage:
- Frozen dataclass immutability for all model types
- Field validation in __post_init__ (empty ids, confidence ranges, etc.)
- UniversalScenarioConfig cross-validation (impact rules reference valid ids)
- ScenarioGenerator.generate() with mocked LLM returns valid config
- Error handling: invalid JSON → RuntimeError
- Error handling: empty decision_types → RuntimeError
- Edge case: minimal valid response (1 decision, 1 metric, 1 shock, 1 rule)
- Slug validation (no spaces, lowercase)
- Lookup helpers on UniversalScenarioConfig
- Prompt strings are domain-agnostic (no HK references)
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_DECISION = {
    "id": "form_alliance",
    "label": "結盟",
    "description": "Two entities agree to cooperate.",
    "possible_actions": ["ally", "refuse", "negotiate"],
    "applicable_entity_types": ["Person"],
}

_MINIMAL_METRIC = {
    "id": "power_balance",
    "label": "勢力均衡",
    "description": "Relative power distribution.",
    "initial_value": 50.0,
    "unit": "",
}

_MINIMAL_SHOCK = {
    "id": "imperial_decree",
    "label": "皇帝旨意",
    "description": "Emperor issues a decree.",
    "affected_metrics": ["power_balance"],
    "severity_range": [0.2, 0.8],
}

_MINIMAL_RULE = {
    "decision_type_id": "form_alliance",
    "action": "ally",
    "metric_id": "power_balance",
    "delta_per_10": 5.0,
    "description": "Alliances shift power balance.",
}

_MINIMAL_LLM_RESPONSE = {
    "scenario_name": "紅樓夢模擬",
    "scenario_description": "模擬大觀園內各家族的權力博弈。",
    "time_scale": "rounds",
    "language_hint": "zh-HK",
    "decision_types": [_MINIMAL_DECISION],
    "metrics": [_MINIMAL_METRIC],
    "shock_types": [_MINIMAL_SHOCK],
    "impact_rules": [_MINIMAL_RULE],
}


def _make_agent_profile(agent_id: str = "jia_baoyu"):
    """Return a minimal UniversalAgentProfile for testing."""
    from backend.app.models.universal_agent_profile import UniversalAgentProfile

    return UniversalAgentProfile(
        id=agent_id,
        name="賈寶玉",
        role="富家公子",
        entity_type="Person",
        persona="A sensitive young nobleman.",
        goals=("maintain_status",),
        capabilities=("social_influence",),
        stance_axes=(("loyalty", 0.7),),
        relationships=(),
        kg_node_id="node_001",
    )


# ===========================================================================
# Model: UniversalDecisionType
# ===========================================================================


class TestUniversalDecisionType:
    def test_is_frozen(self) -> None:
        from backend.app.models.universal_scenario import UniversalDecisionType

        dt = UniversalDecisionType(
            id="betray",
            label="背叛",
            description="Betray an ally.",
            possible_actions=("betray", "stay_loyal"),
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            dt.id = "new_id"  # type: ignore[misc]

    def test_empty_id_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalDecisionType

        with pytest.raises(ValueError, match="id must not be empty"):
            UniversalDecisionType(
                id="",
                label="Test",
                description="desc",
                possible_actions=("act",),
            )

    def test_empty_possible_actions_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalDecisionType

        with pytest.raises(ValueError, match="possible_action"):
            UniversalDecisionType(
                id="test",
                label="Test",
                description="desc",
                possible_actions=(),
            )

    def test_default_applicable_entity_types_is_empty_tuple(self) -> None:
        from backend.app.models.universal_scenario import UniversalDecisionType

        dt = UniversalDecisionType(
            id="test",
            label="Test",
            description="desc",
            possible_actions=("act",),
        )
        assert dt.applicable_entity_types == ()

    def test_fields_accessible(self) -> None:
        from backend.app.models.universal_scenario import UniversalDecisionType

        dt = UniversalDecisionType(
            id="form_alliance",
            label="結盟",
            description="Two entities cooperate.",
            possible_actions=("ally", "refuse"),
            applicable_entity_types=("Country", "Military"),
        )
        assert dt.id == "form_alliance"
        assert dt.label == "結盟"
        assert "ally" in dt.possible_actions
        assert "Country" in dt.applicable_entity_types


# ===========================================================================
# Model: UniversalMetric
# ===========================================================================


class TestUniversalMetric:
    def test_is_frozen(self) -> None:
        from backend.app.models.universal_scenario import UniversalMetric

        m = UniversalMetric(id="tension", label="緊張程度", description="d", initial_value=50.0)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            m.id = "other"  # type: ignore[misc]

    def test_empty_id_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalMetric

        with pytest.raises(ValueError, match="id must not be empty"):
            UniversalMetric(id="", label="L", description="d", initial_value=10.0)

    def test_default_unit_is_empty_string(self) -> None:
        from backend.app.models.universal_scenario import UniversalMetric

        m = UniversalMetric(id="tension", label="緊張", description="d", initial_value=50.0)
        assert m.unit == ""

    def test_fields_accessible(self) -> None:
        from backend.app.models.universal_scenario import UniversalMetric

        m = UniversalMetric(id="oil_price", label="油價", description="crude oil", initial_value=75.0, unit="USD")
        assert m.id == "oil_price"
        assert m.initial_value == 75.0
        assert m.unit == "USD"


# ===========================================================================
# Model: UniversalShockType
# ===========================================================================


class TestUniversalShockType:
    def test_is_frozen(self) -> None:
        from backend.app.models.universal_scenario import UniversalShockType

        s = UniversalShockType(
            id="decree",
            label="旨意",
            description="Emperor speaks.",
            affected_metrics=("power_balance",),
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            s.id = "other"  # type: ignore[misc]

    def test_empty_id_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalShockType

        with pytest.raises(ValueError, match="id must not be empty"):
            UniversalShockType(id="", label="L", description="d", affected_metrics=())

    def test_invalid_severity_range_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalShockType

        with pytest.raises(ValueError, match="severity_range"):
            UniversalShockType(
                id="shock",
                label="S",
                description="d",
                affected_metrics=(),
                severity_range=(-1.0, 0.5),
            )

    def test_inverted_range_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalShockType

        with pytest.raises(ValueError, match="severity_range"):
            UniversalShockType(
                id="shock",
                label="S",
                description="d",
                affected_metrics=(),
                severity_range=(0.9, 0.1),
            )

    def test_default_severity_range(self) -> None:
        from backend.app.models.universal_scenario import UniversalShockType

        s = UniversalShockType(id="s", label="L", description="d", affected_metrics=())
        assert s.severity_range == (0.1, 1.0)


# ===========================================================================
# Model: UniversalImpactRule
# ===========================================================================


class TestUniversalImpactRule:
    def test_is_frozen(self) -> None:
        from backend.app.models.universal_scenario import UniversalImpactRule

        r = UniversalImpactRule(
            decision_type_id="form_alliance",
            action="ally",
            metric_id="power_balance",
            delta_per_10=5.0,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            r.delta_per_10 = 99.0  # type: ignore[misc]

    def test_empty_decision_type_id_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalImpactRule

        with pytest.raises(ValueError, match="decision_type_id"):
            UniversalImpactRule(
                decision_type_id="",
                action="act",
                metric_id="m",
                delta_per_10=1.0,
            )

    def test_empty_action_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalImpactRule

        with pytest.raises(ValueError, match="action"):
            UniversalImpactRule(
                decision_type_id="dt",
                action="",
                metric_id="m",
                delta_per_10=1.0,
            )

    def test_empty_metric_id_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalImpactRule

        with pytest.raises(ValueError, match="metric_id"):
            UniversalImpactRule(
                decision_type_id="dt",
                action="act",
                metric_id="",
                delta_per_10=1.0,
            )

    def test_negative_delta_allowed(self) -> None:
        from backend.app.models.universal_scenario import UniversalImpactRule

        r = UniversalImpactRule(
            decision_type_id="cease_fire",
            action="stand_down",
            metric_id="military_tension",
            delta_per_10=-10.0,
        )
        assert r.delta_per_10 == -10.0


# ===========================================================================
# Model: UniversalScenarioConfig
# ===========================================================================


class TestUniversalScenarioConfig:
    def _make_config(self, **overrides):
        from backend.app.models.universal_scenario import (
            UniversalDecisionType,
            UniversalImpactRule,
            UniversalMetric,
            UniversalScenarioConfig,
            UniversalShockType,
        )

        dt = UniversalDecisionType(
            id="form_alliance",
            label="結盟",
            description="form alliances",
            possible_actions=("ally", "refuse"),
        )
        metric = UniversalMetric(id="power_balance", label="勢力", description="power", initial_value=50.0)
        shock = UniversalShockType(
            id="imperial_decree",
            label="旨意",
            description="decree",
            affected_metrics=("power_balance",),
        )
        rule = UniversalImpactRule(
            decision_type_id="form_alliance",
            action="ally",
            metric_id="power_balance",
            delta_per_10=5.0,
        )
        kwargs = dict(
            scenario_id="test_id",
            scenario_name="Test",
            scenario_description="A test scenario.",
            decision_types=(dt,),
            metrics=(metric,),
            shock_types=(shock,),
            impact_rules=(rule,),
        )
        kwargs.update(overrides)
        return UniversalScenarioConfig(**kwargs)

    def test_is_frozen(self) -> None:
        config = self._make_config()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            config.scenario_name = "changed"  # type: ignore[misc]

    def test_contains_all_sub_objects(self) -> None:
        config = self._make_config()
        assert len(config.decision_types) == 1
        assert len(config.metrics) == 1
        assert len(config.shock_types) == 1
        assert len(config.impact_rules) == 1

    def test_empty_decision_types_raises(self) -> None:
        from backend.app.models.universal_scenario import UniversalScenarioConfig

        with pytest.raises(ValueError, match="decision_type"):
            UniversalScenarioConfig(
                scenario_id="x",
                scenario_name="X",
                scenario_description="X",
                decision_types=(),
                metrics=(
                    MagicMock(id="m"),  # won't reach validation
                ),
                shock_types=(),
                impact_rules=(),
            )

    def test_cross_validation_bad_decision_id(self) -> None:
        from backend.app.models.universal_scenario import (
            UniversalDecisionType,
            UniversalImpactRule,
            UniversalMetric,
            UniversalScenarioConfig,
        )

        dt = UniversalDecisionType(id="real_decision", label="L", description="d", possible_actions=("act",))
        metric = UniversalMetric(id="m", label="L", description="d", initial_value=50.0)
        bad_rule = UniversalImpactRule(
            decision_type_id="nonexistent_decision",
            action="act",
            metric_id="m",
            delta_per_10=1.0,
        )
        with pytest.raises(ValueError, match="unknown decision_type_id"):
            UniversalScenarioConfig(
                scenario_id="x",
                scenario_name="X",
                scenario_description="X",
                decision_types=(dt,),
                metrics=(metric,),
                shock_types=(),
                impact_rules=(bad_rule,),
            )

    def test_cross_validation_bad_metric_id(self) -> None:
        from backend.app.models.universal_scenario import (
            UniversalDecisionType,
            UniversalImpactRule,
            UniversalMetric,
            UniversalScenarioConfig,
        )

        dt = UniversalDecisionType(id="dt", label="L", description="d", possible_actions=("act",))
        metric = UniversalMetric(id="real_metric", label="L", description="d", initial_value=50.0)
        bad_rule = UniversalImpactRule(
            decision_type_id="dt",
            action="act",
            metric_id="nonexistent_metric",
            delta_per_10=1.0,
        )
        with pytest.raises(ValueError, match="unknown metric_id"):
            UniversalScenarioConfig(
                scenario_id="x",
                scenario_name="X",
                scenario_description="X",
                decision_types=(dt,),
                metrics=(metric,),
                shock_types=(),
                impact_rules=(bad_rule,),
            )

    def test_cross_validation_bad_action(self) -> None:
        from backend.app.models.universal_scenario import (
            UniversalDecisionType,
            UniversalImpactRule,
            UniversalMetric,
            UniversalScenarioConfig,
        )

        dt = UniversalDecisionType(id="dt", label="L", description="d", possible_actions=("real_action",))
        metric = UniversalMetric(id="m", label="L", description="d", initial_value=50.0)
        bad_rule = UniversalImpactRule(
            decision_type_id="dt",
            action="nonexistent_action",
            metric_id="m",
            delta_per_10=1.0,
        )
        with pytest.raises(ValueError, match="action"):
            UniversalScenarioConfig(
                scenario_id="x",
                scenario_name="X",
                scenario_description="X",
                decision_types=(dt,),
                metrics=(metric,),
                shock_types=(),
                impact_rules=(bad_rule,),
            )

    def test_get_decision_type_found(self) -> None:
        config = self._make_config()
        dt = config.get_decision_type("form_alliance")
        assert dt is not None
        assert dt.id == "form_alliance"

    def test_get_decision_type_not_found(self) -> None:
        config = self._make_config()
        assert config.get_decision_type("nonexistent") is None

    def test_get_metric_found(self) -> None:
        config = self._make_config()
        m = config.get_metric("power_balance")
        assert m is not None
        assert m.id == "power_balance"

    def test_get_metric_not_found(self) -> None:
        config = self._make_config()
        assert config.get_metric("nonexistent") is None

    def test_rules_for_action_returns_matching(self) -> None:
        config = self._make_config()
        rules = config.rules_for_action("form_alliance", "ally")
        assert len(rules) == 1
        assert rules[0].delta_per_10 == 5.0

    def test_rules_for_action_empty_when_no_match(self) -> None:
        config = self._make_config()
        rules = config.rules_for_action("form_alliance", "refuse")
        assert rules == ()


# ===========================================================================
# Service: ScenarioGenerator
# ===========================================================================


class TestScenarioGeneratorGenerate:
    """Tests for ScenarioGenerator.generate() with mocked LLM."""

    @pytest.mark.asyncio
    async def test_generate_returns_valid_config(self) -> None:
        from backend.app.services.scenario_generator import ScenarioGenerator

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value=_MINIMAL_LLM_RESPONSE)

        gen = ScenarioGenerator(llm_client=mock_llm)
        config = await gen.generate(
            seed_text="紅樓夢中的家族紛爭",
            kg_nodes=[{"id": "node_1", "label": "賈寶玉", "entity_type": "Person"}],
            kg_edges=[{"source": "node_1", "target": "node_2", "relation": "loves"}],
            agent_profiles=[_make_agent_profile()],
        )

        assert config.scenario_name == "紅樓夢模擬"
        assert config.language_hint == "zh-HK"
        assert len(config.decision_types) == 1
        assert len(config.metrics) == 1
        assert len(config.shock_types) == 1
        assert len(config.impact_rules) == 1

    @pytest.mark.asyncio
    async def test_generate_llm_json_error_raises_runtime(self) -> None:
        """LLM returning non-JSON should raise RuntimeError, not JSONDecodeError."""
        import json

        from backend.app.services.scenario_generator import ScenarioGenerator

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))

        gen = ScenarioGenerator(llm_client=mock_llm)
        with pytest.raises(RuntimeError, match="non-JSON"):
            await gen.generate(
                seed_text="any seed",
                kg_nodes=[],
                kg_edges=[],
                agent_profiles=[],
            )

    @pytest.mark.asyncio
    async def test_generate_llm_network_error_raises_runtime(self) -> None:
        """Network failures should be wrapped in RuntimeError."""
        from backend.app.services.scenario_generator import ScenarioGenerator

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=ConnectionError("timeout"))

        gen = ScenarioGenerator(llm_client=mock_llm)
        with pytest.raises(RuntimeError, match="LLM call failed"):
            await gen.generate(
                seed_text="any seed",
                kg_nodes=[],
                kg_edges=[],
                agent_profiles=[],
            )

    @pytest.mark.asyncio
    async def test_generate_empty_decision_types_raises(self) -> None:
        from backend.app.services.scenario_generator import ScenarioGenerator

        bad_response = {**_MINIMAL_LLM_RESPONSE, "decision_types": []}

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value=bad_response)

        gen = ScenarioGenerator(llm_client=mock_llm)
        with pytest.raises(RuntimeError):
            await gen.generate("seed", [], [], [])

    @pytest.mark.asyncio
    async def test_generate_empty_metrics_raises(self) -> None:
        from backend.app.services.scenario_generator import ScenarioGenerator

        bad_response = {**_MINIMAL_LLM_RESPONSE, "metrics": []}

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value=bad_response)

        gen = ScenarioGenerator(llm_client=mock_llm)
        with pytest.raises(RuntimeError):
            await gen.generate("seed", [], [], [])

    @pytest.mark.asyncio
    async def test_generate_missing_scenario_name_raises(self) -> None:
        from backend.app.services.scenario_generator import ScenarioGenerator

        bad_response = {k: v for k, v in _MINIMAL_LLM_RESPONSE.items() if k != "scenario_name"}
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value=bad_response)

        gen = ScenarioGenerator(llm_client=mock_llm)
        with pytest.raises(RuntimeError):
            await gen.generate("seed", [], [], [])

    @pytest.mark.asyncio
    async def test_generate_minimal_response(self) -> None:
        """Minimal valid response: 1 decision, 1 metric, 1 shock, 1 rule."""
        from backend.app.services.scenario_generator import ScenarioGenerator

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value=_MINIMAL_LLM_RESPONSE)

        gen = ScenarioGenerator(llm_client=mock_llm)
        config = await gen.generate("seed", [], [], [])

        assert config.scenario_id  # uuid assigned
        assert config.decision_types[0].id == "form_alliance"
        assert config.metrics[0].id == "power_balance"
        assert config.shock_types[0].id == "imperial_decree"
        assert config.impact_rules[0].decision_type_id == "form_alliance"

    @pytest.mark.asyncio
    async def test_generate_assigns_unique_scenario_id(self) -> None:
        """Each call should produce a unique scenario_id."""
        from backend.app.services.scenario_generator import ScenarioGenerator

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value=_MINIMAL_LLM_RESPONSE)

        gen = ScenarioGenerator(llm_client=mock_llm)
        config_a = await gen.generate("seed", [], [], [])
        config_b = await gen.generate("seed", [], [], [])

        assert config_a.scenario_id != config_b.scenario_id

    @pytest.mark.asyncio
    async def test_generate_impact_rules_cross_validated(self) -> None:
        """Impact rules referencing bad metric IDs should raise RuntimeError."""
        from backend.app.services.scenario_generator import ScenarioGenerator

        bad_rule = {
            "decision_type_id": "form_alliance",
            "action": "ally",
            "metric_id": "nonexistent_metric_xyz",
            "delta_per_10": 5.0,
        }
        bad_response = {**_MINIMAL_LLM_RESPONSE, "impact_rules": [bad_rule]}

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value=bad_response)

        gen = ScenarioGenerator(llm_client=mock_llm)
        with pytest.raises(RuntimeError):
            await gen.generate("seed", [], [], [])

    @pytest.mark.asyncio
    async def test_generate_slugifies_dirty_ids(self) -> None:
        """IDs with spaces or uppercase should be sanitised to valid slugs."""
        from backend.app.services.scenario_generator import ScenarioGenerator

        dirty_response = {
            **_MINIMAL_LLM_RESPONSE,
            "decision_types": [
                {
                    **_MINIMAL_DECISION,
                    "id": "Form Alliance",  # has space and uppercase
                    "possible_actions": ["ally", "refuse", "negotiate"],
                }
            ],
            "impact_rules": [
                {
                    **_MINIMAL_RULE,
                    "decision_type_id": "form_alliance",  # already sanitised by generator
                }
            ],
        }

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value=dirty_response)

        gen = ScenarioGenerator(llm_client=mock_llm)
        config = await gen.generate("seed", [], [], [])

        # After sanitisation, id should be a valid slug
        dt_id = config.decision_types[0].id
        assert " " not in dt_id
        assert dt_id == dt_id.lower()


# ===========================================================================
# Slug validation helpers
# ===========================================================================


class TestSlugValidation:
    def test_sanitise_slug_removes_spaces(self) -> None:
        from backend.app.services.scenario_generator import _sanitise_slug

        assert " " not in _sanitise_slug("form alliance")

    def test_sanitise_slug_lowercases(self) -> None:
        from backend.app.services.scenario_generator import _sanitise_slug

        assert _sanitise_slug("FormAlliance") == "formalliance"

    def test_sanitise_slug_replaces_special_chars(self) -> None:
        from backend.app.services.scenario_generator import _sanitise_slug

        result = _sanitise_slug("oil-price (USD)")
        assert " " not in result
        assert "(" not in result
        assert result == result.lower()

    def test_sanitise_slug_fallback_for_empty(self) -> None:
        from backend.app.services.scenario_generator import _sanitise_slug

        assert _sanitise_slug("") == "unknown"

    def test_sanitise_slug_cjk_becomes_underscores(self) -> None:
        from backend.app.services.scenario_generator import _sanitise_slug

        result = _sanitise_slug("軍事打擊")
        # CJK characters are not valid slug chars — result should be non-empty
        assert result
        assert result == result.lower()
        assert " " not in result


# ===========================================================================
# Prompt domain-agnosticism
# ===========================================================================


class TestScenarioPromptsDomainAgnostic:
    def test_system_prompt_no_hong_kong(self) -> None:
        from backend.prompts.scenario_generation_prompts import SCENARIO_GENERATION_SYSTEM

        assert "hong kong" not in SCENARIO_GENERATION_SYSTEM.lower()

    def test_user_prompt_no_hong_kong(self) -> None:
        from backend.prompts.scenario_generation_prompts import SCENARIO_GENERATION_USER

        assert "hong kong" not in SCENARIO_GENERATION_USER.lower()

    def test_system_prompt_has_schema_keys(self) -> None:
        from backend.prompts.scenario_generation_prompts import SCENARIO_GENERATION_SYSTEM

        for key in ("decision_types", "metrics", "shock_types", "impact_rules"):
            assert key in SCENARIO_GENERATION_SYSTEM

    def test_user_prompt_has_required_placeholders(self) -> None:
        from backend.prompts.scenario_generation_prompts import SCENARIO_GENERATION_USER

        for placeholder in (
            "{seed_text}",
            "{kg_nodes_json}",
            "{kg_edges_json}",
            "{agent_summaries_json}",
        ):
            assert placeholder in SCENARIO_GENERATION_USER


# ===========================================================================
# Model: ImpliedActor
# ===========================================================================


def test_implied_actor_is_frozen():
    from backend.app.models.universal_scenario import ImpliedActor

    actor = ImpliedActor(
        id="eu",
        name="歐盟",
        entity_type="Organization",
        role="energy policy",
        relevance_reason="gas supply cut",
    )
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        actor.id = "other"  # type: ignore[misc]


def test_universal_scenario_config_has_implied_actors_field():
    from backend.app.models.universal_scenario import (
        ImpliedActor,
        UniversalDecisionType,
        UniversalImpactRule,
        UniversalMetric,
        UniversalScenarioConfig,
        UniversalShockType,
    )

    actor = ImpliedActor(
        id="eu",
        name="歐盟",
        entity_type="Organization",
        role="energy policy",
        relevance_reason="gas supply cut",
    )
    config = UniversalScenarioConfig(
        scenario_id="test",
        scenario_name="test",
        scenario_description="test",
        decision_types=(UniversalDecisionType(**_MINIMAL_DECISION),),
        metrics=(UniversalMetric(**_MINIMAL_METRIC),),
        shock_types=(UniversalShockType(**_MINIMAL_SHOCK),),
        impact_rules=(UniversalImpactRule(**_MINIMAL_RULE),),
        implied_actors=(actor,),
    )
    assert len(config.implied_actors) == 1
    assert config.implied_actors[0].id == "eu"


def test_universal_scenario_config_implied_actors_defaults_empty():
    from backend.app.models.universal_scenario import (
        UniversalDecisionType,
        UniversalImpactRule,
        UniversalMetric,
        UniversalScenarioConfig,
        UniversalShockType,
    )

    config = UniversalScenarioConfig(
        scenario_id="x",
        scenario_name="x",
        scenario_description="x",
        decision_types=(UniversalDecisionType(**_MINIMAL_DECISION),),
        metrics=(UniversalMetric(**_MINIMAL_METRIC),),
        shock_types=(UniversalShockType(**_MINIMAL_SHOCK),),
        impact_rules=(UniversalImpactRule(**_MINIMAL_RULE),),
    )
    assert config.implied_actors == ()


# ===========================================================================
# Service: ScenarioGenerator — implied_actors
# ===========================================================================

_MINIMAL_RESPONSE_WITH_IMPLIED = {
    "scenario_name": "Iran War",
    "scenario_description": "US-Israel military strikes on Iran.",
    "time_scale": "days",
    "language_hint": "en-US",
    "decision_types": [_MINIMAL_DECISION],
    "metrics": [_MINIMAL_METRIC],
    "shock_types": [_MINIMAL_SHOCK],
    "impact_rules": [_MINIMAL_RULE],
    "implied_actors": [
        {
            "id": "european_union",
            "name": "European Union",
            "entity_type": "Organization",
            "role": "Coordinates EU energy policy response",
            "relevance_reason": "Hormuz closure disrupts EU gas supply",
        }
    ],
}


@pytest.mark.asyncio
async def test_generate_parses_implied_actors():
    from backend.app.models.universal_scenario import ImpliedActor
    from backend.app.services.scenario_generator import ScenarioGenerator

    llm = MagicMock()
    llm.chat_json = AsyncMock(return_value=_MINIMAL_RESPONSE_WITH_IMPLIED)
    gen = ScenarioGenerator(llm_client=llm)

    config = await gen.generate("test seed", [], [], [])

    assert len(config.implied_actors) == 1
    assert isinstance(config.implied_actors[0], ImpliedActor)
    assert config.implied_actors[0].id == "european_union"


@pytest.mark.asyncio
async def test_generate_handles_missing_implied_actors_key():
    """LLM responses without implied_actors key should not fail."""
    from backend.app.services.scenario_generator import ScenarioGenerator

    response_without_key = {k: v for k, v in _MINIMAL_RESPONSE_WITH_IMPLIED.items() if k != "implied_actors"}
    llm = MagicMock()
    llm.chat_json = AsyncMock(return_value=response_without_key)
    gen = ScenarioGenerator(llm_client=llm)

    config = await gen.generate("test seed", [], [], [])
    assert config.implied_actors == ()


def test_scenario_generation_system_prompt_includes_implied_actors_schema():
    from backend.prompts.scenario_generation_prompts import SCENARIO_GENERATION_SYSTEM

    assert "implied_actors" in SCENARIO_GENERATION_SYSTEM
    assert "relevance_reason" in SCENARIO_GENERATION_SYSTEM
