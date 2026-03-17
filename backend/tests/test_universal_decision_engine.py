"""Tests for UniversalDecisionEngine, UniversalAgentDecision, UniversalRoundResult,
and the get_decision_engine factory.

All LLM calls and DB operations are mocked.  Mock versions of
UniversalScenarioConfig / UniversalDecisionType / UniversalImpactRule are
defined here so the suite does not depend on the parallel agent's models being
available yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from backend.app.models.universal_agent_profile import UniversalAgentProfile
from backend.app.services.universal_decision_engine import (
    UniversalAgentDecision,
    UniversalDecisionEngine,
    UniversalRoundResult,
    _build_counts_by_type,
    _compute_metric_deltas,
    _filter_by_entity_type,
    _sample_agents,
)


# ---------------------------------------------------------------------------
# Mock scenario model types (stand-ins until parallel agent delivers models)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MockDecisionType:
    id: str
    label: str
    description: str
    possible_actions: tuple[str, ...]
    applicable_entity_types: tuple[str, ...]


@dataclass(frozen=True)
class MockImpactRule:
    decision_type_id: str
    action: str
    metric_id: str
    delta_per_10: float
    description: str = ""


@dataclass(frozen=True)
class MockScenarioConfig:
    scenario_id: str
    scenario_name: str
    decision_types: tuple[MockDecisionType, ...]
    metrics: tuple
    impact_rules: tuple[MockImpactRule, ...]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_agent(
    agent_id: str = "agent_alpha",
    entity_type: str = "Military",
    name: str = "Agent Alpha",
) -> UniversalAgentProfile:
    return UniversalAgentProfile(
        id=agent_id,
        name=name,
        role="Test role",
        entity_type=entity_type,
        persona="A pragmatic strategist who weighs options carefully.",
        goals=("achieve_dominance", "protect_allies"),
        capabilities=("military_strike", "diplomacy", "economic_pressure"),
        stance_axes=(("hawkishness", 0.8), ("risk_tolerance", 0.6)),
        relationships=(("agent_beta", "ally"),),
        kg_node_id=f"kg_{agent_id}",
    )


def _make_scenario(
    decision_type_id: str = "military_action",
    possible_actions: tuple[str, ...] = ("launch_strike", "negotiate", "do_nothing"),
    applicable_entity_types: tuple[str, ...] = ("Military", "Government"),
    impact_rules: tuple[MockImpactRule, ...] = (),
) -> MockScenarioConfig:
    dt = MockDecisionType(
        id=decision_type_id,
        label="Military Action",
        description="Decide on a military response.",
        possible_actions=possible_actions,
        applicable_entity_types=applicable_entity_types,
    )
    return MockScenarioConfig(
        scenario_id="test_scenario",
        scenario_name="Test Scenario",
        decision_types=(dt,),
        metrics=(),
        impact_rules=impact_rules,
    )


@pytest.fixture()
def military_agent() -> UniversalAgentProfile:
    return _make_agent("iran_supreme_leader", "Military")


@pytest.fixture()
def media_agent() -> UniversalAgentProfile:
    return _make_agent("bbc_reporter", "MediaOutlet", "BBC Reporter")


@pytest.fixture()
def scenario() -> MockScenarioConfig:
    return _make_scenario()


@pytest.fixture()
def engine() -> UniversalDecisionEngine:
    mock_llm = MagicMock()
    mock_llm.chat_json = AsyncMock(
        return_value={
            "decisions": [
                {
                    "agent_id": "iran_supreme_leader",
                    "action": "negotiate",
                    "reasoning": "Diplomatic channels still viable.",
                    "confidence": 0.7,
                }
            ]
        }
    )
    return UniversalDecisionEngine(llm_client=mock_llm)


# ---------------------------------------------------------------------------
# UniversalAgentDecision tests
# ---------------------------------------------------------------------------


class TestUniversalAgentDecision:
    def test_is_frozen(self) -> None:
        d = UniversalAgentDecision(
            session_id="s1",
            agent_id="a1",
            round_number=1,
            decision_type_id="dt1",
            action="strike",
            reasoning="reason",
            confidence=0.8,
        )
        with pytest.raises((AttributeError, TypeError)):
            d.confidence = 0.9  # type: ignore[misc]

    def test_valid_confidence_boundary_values(self) -> None:
        for val in (0.0, 0.5, 1.0):
            d = UniversalAgentDecision(
                session_id="s",
                agent_id="a",
                round_number=1,
                decision_type_id="dt",
                action="act",
                reasoning="r",
                confidence=val,
            )
            assert d.confidence == val

    def test_invalid_confidence_too_high_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            UniversalAgentDecision(
                session_id="s",
                agent_id="a",
                round_number=1,
                decision_type_id="dt",
                action="act",
                reasoning="r",
                confidence=1.1,
            )

    def test_invalid_confidence_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            UniversalAgentDecision(
                session_id="s",
                agent_id="a",
                round_number=1,
                decision_type_id="dt",
                action="act",
                reasoning="r",
                confidence=-0.1,
            )


# ---------------------------------------------------------------------------
# UniversalRoundResult tests
# ---------------------------------------------------------------------------


class TestUniversalRoundResult:
    def test_is_frozen(self) -> None:
        r = UniversalRoundResult(
            session_id="s",
            round_number=1,
            decisions=(),
            metric_deltas={},
            total_decisions=0,
            counts_by_type={},
        )
        with pytest.raises((AttributeError, TypeError)):
            r.total_decisions = 99  # type: ignore[misc]

    def test_decisions_field_is_tuple(self) -> None:
        r = UniversalRoundResult(
            session_id="s",
            round_number=2,
            decisions=(),
            metric_deltas={"gdp": -1.5},
            total_decisions=0,
            counts_by_type={},
        )
        assert isinstance(r.decisions, tuple)


# ---------------------------------------------------------------------------
# Entity-type filtering tests
# ---------------------------------------------------------------------------


class TestFilterByEntityType:
    def test_military_agent_eligible_for_military_decision(
        self, military_agent: UniversalAgentProfile
    ) -> None:
        dt = MockDecisionType(
            id="mil",
            label="",
            description="",
            possible_actions=("strike",),
            applicable_entity_types=("Military",),
        )
        result = _filter_by_entity_type([military_agent], dt)
        assert result == [military_agent]

    def test_media_agent_not_eligible_for_military_decision(
        self, media_agent: UniversalAgentProfile
    ) -> None:
        dt = MockDecisionType(
            id="mil",
            label="",
            description="",
            possible_actions=("strike",),
            applicable_entity_types=("Military", "Government"),
        )
        result = _filter_by_entity_type([media_agent], dt)
        assert result == []

    def test_empty_applicable_types_allows_all_agents(
        self,
        military_agent: UniversalAgentProfile,
        media_agent: UniversalAgentProfile,
    ) -> None:
        dt = MockDecisionType(
            id="open",
            label="",
            description="",
            possible_actions=("act",),
            applicable_entity_types=(),   # empty → all eligible
        )
        result = _filter_by_entity_type([military_agent, media_agent], dt)
        assert len(result) == 2

    def test_multiple_entity_types_match(self) -> None:
        gov_agent = _make_agent("pm", "Government")
        mil_agent = _make_agent("general", "Military")
        dt = MockDecisionType(
            id="combined",
            label="",
            description="",
            possible_actions=("act",),
            applicable_entity_types=("Military", "Government"),
        )
        result = _filter_by_entity_type([gov_agent, mil_agent], dt)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Sampling tests
# ---------------------------------------------------------------------------


class TestSampleAgents:
    def test_sampling_caps_at_30(self) -> None:
        agents = [_make_agent(f"agent_{i}") for i in range(200)]
        sampled = _sample_agents(agents, rate=0.20, cap=30)
        assert len(sampled) <= 30

    def test_sampling_returns_subset_of_eligible(self) -> None:
        agents = [_make_agent(f"agent_{i}") for i in range(100)]
        sampled = _sample_agents(agents, rate=0.20, cap=30)
        agent_ids = {a.id for a in agents}
        for s in sampled:
            assert s.id in agent_ids

    def test_sampling_when_fewer_than_cap(self) -> None:
        agents = [_make_agent(f"agent_{i}") for i in range(5)]
        sampled = _sample_agents(agents, rate=0.20, cap=30)
        # 5 * 0.20 = 1, so at least 1 returned
        assert 1 <= len(sampled) <= 5

    def test_sampling_returns_at_least_one(self) -> None:
        agents = [_make_agent("solo")]
        sampled = _sample_agents(agents, rate=0.20, cap=30)
        assert len(sampled) == 1

    def test_empty_list_returns_empty(self) -> None:
        sampled = _sample_agents([], rate=0.20, cap=30)
        assert sampled == []


# ---------------------------------------------------------------------------
# _deliberate_batch tests (mocked LLM)
# ---------------------------------------------------------------------------


class TestDeliberateBatch:
    @pytest.mark.asyncio
    async def test_returns_valid_decisions_for_matching_agents(
        self, military_agent: UniversalAgentProfile
    ) -> None:
        dt = MockDecisionType(
            id="mil_action",
            label="Military Action",
            description="Military decision",
            possible_actions=("launch_strike", "negotiate", "do_nothing"),
            applicable_entity_types=("Military",),
        )
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(
            return_value={
                "decisions": [
                    {
                        "agent_id": military_agent.id,
                        "action": "negotiate",
                        "reasoning": "Diplomacy first.",
                        "confidence": 0.65,
                    }
                ]
            }
        )
        eng = UniversalDecisionEngine(llm_client=mock_llm)

        results = await eng._deliberate_batch(
            agents=[military_agent],
            decision_type=dt,
            current_metrics={"tension_level": 0.7},
            recent_events="Diplomatic talks broke down.",
        )

        assert len(results) == 1
        assert results[0].action == "negotiate"
        assert results[0].agent_id == military_agent.id
        assert results[0].confidence == 0.65

    @pytest.mark.asyncio
    async def test_invalid_action_from_llm_is_filtered_out(
        self, military_agent: UniversalAgentProfile
    ) -> None:
        dt = MockDecisionType(
            id="mil_action",
            label="Military Action",
            description="Decide",
            possible_actions=("strike", "retreat"),
            applicable_entity_types=(),
        )
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(
            return_value={
                "decisions": [
                    {
                        "agent_id": military_agent.id,
                        "action": "INVALID_ACTION_XYZ",
                        "reasoning": "Some invalid reasoning.",
                        "confidence": 0.5,
                    }
                ]
            }
        )
        eng = UniversalDecisionEngine(llm_client=mock_llm)

        results = await eng._deliberate_batch(
            agents=[military_agent],
            decision_type=dt,
            current_metrics={},
            recent_events="",
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_unknown_agent_id_from_llm_is_filtered_out(
        self, military_agent: UniversalAgentProfile
    ) -> None:
        dt = MockDecisionType(
            id="mil_action",
            label="",
            description="",
            possible_actions=("strike",),
            applicable_entity_types=(),
        )
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(
            return_value={
                "decisions": [
                    {
                        "agent_id": "ghost_agent_not_in_batch",
                        "action": "strike",
                        "reasoning": ".",
                        "confidence": 0.5,
                    }
                ]
            }
        )
        eng = UniversalDecisionEngine(llm_client=mock_llm)

        results = await eng._deliberate_batch(
            agents=[military_agent],
            decision_type=dt,
            current_metrics={},
            recent_events="",
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_confidence_is_clamped_to_valid_range(
        self, military_agent: UniversalAgentProfile
    ) -> None:
        dt = MockDecisionType(
            id="dt",
            label="",
            description="",
            possible_actions=("act",),
            applicable_entity_types=(),
        )
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(
            return_value={
                "decisions": [
                    {
                        "agent_id": military_agent.id,
                        "action": "act",
                        "reasoning": "test",
                        "confidence": 99.9,  # out of range — should be clamped
                    }
                ]
            }
        )
        eng = UniversalDecisionEngine(llm_client=mock_llm)

        results = await eng._deliberate_batch(
            agents=[military_agent],
            decision_type=dt,
            current_metrics={},
            recent_events="",
        )

        assert len(results) == 1
        assert results[0].confidence == 1.0


# ---------------------------------------------------------------------------
# Impact aggregation tests
# ---------------------------------------------------------------------------


class TestComputeMetricDeltas:
    def _make_decision(self, decision_type_id: str, action: str) -> UniversalAgentDecision:
        return UniversalAgentDecision(
            session_id="s",
            agent_id="a",
            round_number=1,
            decision_type_id=decision_type_id,
            action=action,
            reasoning="r",
            confidence=0.5,
        )

    def test_single_rule_delta_computed_correctly(self) -> None:
        decisions = [self._make_decision("mil", "strike") for _ in range(10)]
        rules = [
            MockImpactRule(
                decision_type_id="mil",
                action="strike",
                metric_id="tension_level",
                delta_per_10=2.0,
            )
        ]
        deltas = _compute_metric_deltas(decisions, rules)
        # 10 strikes → (10/10) * 2.0 = 2.0
        assert deltas["tension_level"] == pytest.approx(2.0, abs=1e-6)

    def test_multiple_rules_same_metric_are_summed(self) -> None:
        decisions = (
            [self._make_decision("mil", "strike") for _ in range(10)]
            + [self._make_decision("mil", "retreat") for _ in range(5)]
        )
        rules = [
            MockImpactRule("mil", "strike", "tension_level", 2.0),
            MockImpactRule("mil", "retreat", "tension_level", -1.0),
        ]
        deltas = _compute_metric_deltas(decisions, rules)
        # strikes: (10/10)*2.0 = 2.0; retreats: (5/10)*(-1.0) = -0.5 → 1.5
        assert deltas["tension_level"] == pytest.approx(1.5, abs=1e-6)

    def test_no_matching_actions_returns_empty_deltas(self) -> None:
        decisions = [self._make_decision("econ", "sanctions")]
        rules = [MockImpactRule("mil", "strike", "tension_level", 5.0)]
        deltas = _compute_metric_deltas(decisions, rules)
        assert deltas == {}

    def test_empty_decisions_returns_empty_deltas(self) -> None:
        rules = [MockImpactRule("mil", "strike", "tension_level", 5.0)]
        assert _compute_metric_deltas([], rules) == {}

    def test_deltas_rounded_to_4dp(self) -> None:
        decisions = [self._make_decision("dt", "act") for _ in range(3)]
        rules = [MockImpactRule("dt", "act", "metric_x", 1.0)]
        deltas = _compute_metric_deltas(decisions, rules)
        # (3/10)*1.0 = 0.3
        assert deltas["metric_x"] == pytest.approx(0.3, abs=1e-4)


# ---------------------------------------------------------------------------
# process_round_decisions end-to-end tests (mocked LLM + mocked DB)
# ---------------------------------------------------------------------------


class TestProcessRoundDecisions:
    @pytest.mark.asyncio
    async def test_empty_agents_returns_empty_result(self) -> None:
        eng = UniversalDecisionEngine(llm_client=MagicMock())
        scenario = _make_scenario()

        with patch(
            "backend.app.services.universal_decision_engine.get_db",
            return_value=_mock_db_ctx(),
        ):
            result = await eng.process_round_decisions(
                session_id="sess1",
                round_number=1,
                agents=[],
                scenario_config=scenario,
                current_metrics={},
            )

        assert result.total_decisions == 0
        assert result.decisions == ()
        assert result.metric_deltas == {}

    @pytest.mark.asyncio
    async def test_full_pipeline_with_one_agent_and_rule(self) -> None:
        agent = _make_agent("gen_patton", "Military")
        rule = MockImpactRule(
            decision_type_id="military_action",
            action="launch_strike",
            metric_id="conflict_intensity",
            delta_per_10=3.0,
        )
        scenario = _make_scenario(impact_rules=(rule,))

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(
            return_value={
                "decisions": [
                    {
                        "agent_id": "gen_patton",
                        "action": "launch_strike",
                        "reasoning": "Decisive military action required.",
                        "confidence": 0.85,
                    }
                ]
            }
        )
        eng = UniversalDecisionEngine(llm_client=mock_llm)
        eng._schema_initialised = True

        with patch(
            "backend.app.services.universal_decision_engine.get_db",
            return_value=_mock_db_ctx(),
        ):
            result = await eng.process_round_decisions(
                session_id="sess2",
                round_number=3,
                agents=[agent],
                scenario_config=scenario,
                current_metrics={"conflict_intensity": 0.5},
                recent_events="Border clashes escalated.",
            )

        assert result.total_decisions == 1
        assert result.decisions[0].action == "launch_strike"
        assert result.decisions[0].session_id == "sess2"
        assert result.decisions[0].round_number == 3
        # 1 strike: (1/10)*3.0 = 0.3
        assert result.metric_deltas.get("conflict_intensity", 0.0) == pytest.approx(
            0.3, abs=1e-4
        )

    @pytest.mark.asyncio
    async def test_no_eligible_agents_for_entity_type_skips_llm(self) -> None:
        agent = _make_agent("reporter", "MediaOutlet")
        scenario = _make_scenario(applicable_entity_types=("Military",))

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock()
        eng = UniversalDecisionEngine(llm_client=mock_llm)
        eng._schema_initialised = True

        with patch(
            "backend.app.services.universal_decision_engine.get_db",
            return_value=_mock_db_ctx(),
        ):
            result = await eng.process_round_decisions(
                session_id="sess3",
                round_number=1,
                agents=[agent],
                scenario_config=scenario,
                current_metrics={},
            )

        mock_llm.chat_json.assert_not_called()
        assert result.total_decisions == 0

    @pytest.mark.asyncio
    async def test_llm_error_is_logged_not_raised(self) -> None:
        agent = _make_agent("agent_x", "Government")
        scenario = _make_scenario(applicable_entity_types=("Government",))

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        eng = UniversalDecisionEngine(llm_client=mock_llm)
        eng._schema_initialised = True

        with patch(
            "backend.app.services.universal_decision_engine.get_db",
            return_value=_mock_db_ctx(),
        ):
            result = await eng.process_round_decisions(
                session_id="sess4",
                round_number=2,
                agents=[agent],
                scenario_config=scenario,
                current_metrics={},
            )

        # Should not raise — error is logged, result is empty
        assert result.total_decisions == 0


# ---------------------------------------------------------------------------
# get_decision_engine factory tests
# ---------------------------------------------------------------------------


class TestGetDecisionEngine:
    def test_hk_demographic_returns_decision_engine(self) -> None:
        from backend.app.services.decision_engine import (
            DecisionEngine,
            get_decision_engine,
        )

        eng = get_decision_engine("hk_demographic")
        assert isinstance(eng, DecisionEngine)

    def test_kg_driven_returns_universal_decision_engine(self) -> None:
        from backend.app.services.decision_engine import get_decision_engine

        eng = get_decision_engine("kg_driven")
        assert isinstance(eng, UniversalDecisionEngine)

    def test_unknown_mode_raises_value_error(self) -> None:
        from backend.app.services.decision_engine import get_decision_engine

        with pytest.raises(ValueError, match="Unknown decision engine mode"):
            get_decision_engine("unknown_mode")

    def test_kg_driven_accepts_llm_client_kwarg(self) -> None:
        from backend.app.services.decision_engine import get_decision_engine

        mock_llm = MagicMock()
        eng = get_decision_engine("kg_driven", llm_client=mock_llm)
        assert isinstance(eng, UniversalDecisionEngine)
        assert eng._llm is mock_llm


# ---------------------------------------------------------------------------
# DB storage tests (mock get_db)
# ---------------------------------------------------------------------------


class TestStoreDecisions:
    @pytest.mark.asyncio
    async def test_store_decisions_calls_executemany(self) -> None:
        decisions = [
            UniversalAgentDecision(
                session_id="sess5",
                agent_id="agent_a",
                round_number=1,
                decision_type_id="dt1",
                action="act1",
                reasoning="because",
                confidence=0.9,
            )
        ]
        mock_db = AsyncMock()
        mock_db.executemany = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        eng = UniversalDecisionEngine(llm_client=MagicMock())

        with patch(
            "backend.app.services.universal_decision_engine.get_db",
            return_value=mock_db,
        ):
            await eng._store_decisions(decisions)

        mock_db.executemany.assert_called_once()
        call_args = mock_db.executemany.call_args
        rows = call_args[0][1]
        assert len(rows) == 1
        assert rows[0][1] == "agent_a"   # agent_id column
        assert rows[0][4] == "act1"      # action column

    @pytest.mark.asyncio
    async def test_store_decisions_with_empty_list_does_nothing(self) -> None:
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        eng = UniversalDecisionEngine(llm_client=MagicMock())

        with patch(
            "backend.app.services.universal_decision_engine.get_db",
            return_value=mock_db,
        ):
            await eng._store_decisions([])

        mock_db.executemany.assert_called_once()
        rows = mock_db.executemany.call_args[0][1]
        assert rows == []


# ---------------------------------------------------------------------------
# _build_counts_by_type tests
# ---------------------------------------------------------------------------


class TestBuildCountsByType:
    def test_counts_grouped_correctly(self) -> None:
        decisions = [
            UniversalAgentDecision("s", "a1", 1, "dt1", "strike", "r", 0.5),
            UniversalAgentDecision("s", "a2", 1, "dt1", "negotiate", "r", 0.5),
            UniversalAgentDecision("s", "a3", 1, "dt1", "strike", "r", 0.5),
            UniversalAgentDecision("s", "a4", 1, "dt2", "sanction", "r", 0.5),
        ]
        counts = _build_counts_by_type(decisions)
        assert counts["dt1"]["strike"] == 2
        assert counts["dt1"]["negotiate"] == 1
        assert counts["dt2"]["sanction"] == 1

    def test_empty_decisions_returns_empty_dict(self) -> None:
        assert _build_counts_by_type([]) == {}


# ---------------------------------------------------------------------------
# Private helper: mock async context manager for get_db
# ---------------------------------------------------------------------------


def _mock_db_ctx() -> AsyncMock:
    """Return an AsyncMock that works as an async context manager."""
    mock_db = AsyncMock()
    mock_db.executemany = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    return mock_db
