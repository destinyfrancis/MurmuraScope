"""Comprehensive tests for DecisionEngine, decision_rules, and macro adjustments.

Tests cover:
- Eligibility filters (all 8 decision types)
- Sampling cap and rate
- Batch parallel execution
- Macro feedback derivation
- Error handling and edge cases
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.decision import AgentDecision, DecisionType
from backend.app.services.agent_factory import AgentProfile
from backend.app.services.decision_engine import (
    DecisionEngine,
    _build_summary,
    _derive_macro_adjustments,
)
from backend.app.services.decision_rules import (
    _loan_tenor_years,
    _monthly_mortgage_payment,
    filter_eligible_agents,
    is_eligible_adjust_spending,
    is_eligible_buy_property,
    is_eligible_change_job,
    is_eligible_emigrate,
    is_eligible_employment_change,
    is_eligible_have_child,
    is_eligible_invest,
    is_eligible_relocate,
)
from backend.app.services.macro_state import (
    BASELINE_AVG_SQFT_PRICE,
    BASELINE_STAMP_DUTY,
    MacroState,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def baseline_macro() -> MacroState:
    """Return a baseline MacroState for testing."""
    return MacroState(
        hibor_1m=0.040,
        prime_rate=0.055,
        unemployment_rate=0.032,
        median_monthly_income=20_800,
        ccl_index=150.0,
        avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
        mortgage_cap=0.70,
        stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
        gdp_growth=0.025,
        cpi_yoy=0.019,
        hsi_level=20_060.0,
        consumer_confidence=45.0,
        net_migration=2_000,
        birth_rate=5.3,
        policy_flags={"辣招撤銷": True},
    )


def _make_profile(
    id: int = 1,
    age: int = 35,
    sex: str = "M",
    district: str = "沙田",
    occupation: str = "專業人員",
    income_bracket: str = "30000-39999",
    education_level: str = "學位或以上",
    marital_status: str = "已婚",
    housing_type: str = "私人住宅",
    monthly_income: int = 42_000,
    savings: int = 800_000,
    openness: float = 0.6,
    conscientiousness: float = 0.5,
    extraversion: float = 0.6,
    agreeableness: float = 0.5,
    neuroticism: float = 0.4,
    political_stance: float = 0.5,
) -> AgentProfile:
    """Create a test AgentProfile with sensible defaults."""
    return AgentProfile(
        id=id,
        agent_type="npc",
        age=age,
        sex=sex,
        district=district,
        occupation=occupation,
        income_bracket=income_bracket,
        education_level=education_level,
        marital_status=marital_status,
        housing_type=housing_type,
        openness=openness,
        conscientiousness=conscientiousness,
        extraversion=extraversion,
        agreeableness=agreeableness,
        neuroticism=neuroticism,
        monthly_income=monthly_income,
        savings=savings,
        political_stance=political_stance,
    )


# ---------------------------------------------------------------------------
# Eligibility filter tests
# ---------------------------------------------------------------------------


class TestEligibilityBuyProperty:
    """Tests for is_eligible_buy_property."""

    def test_eligible_professional_with_savings(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(savings=2_000_000, monthly_income=50_000)
        assert is_eligible_buy_property(profile, baseline_macro) is True

    def test_ineligible_no_income(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(monthly_income=0)
        assert is_eligible_buy_property(profile, baseline_macro) is False

    def test_ineligible_temporary_housing(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(housing_type="臨時／其他")
        assert is_eligible_buy_property(profile, baseline_macro) is False

    def test_ineligible_public_housing(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(housing_type="公屋")
        assert is_eligible_buy_property(profile, baseline_macro) is False

    def test_ineligible_insufficient_savings(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(savings=50_000, monthly_income=15_000)
        assert is_eligible_buy_property(profile, baseline_macro) is False


class TestEligibilityEmigrate:
    """Tests for is_eligible_emigrate."""

    def test_eligible_with_adequate_savings(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=35, savings=500_000, neuroticism=0.4)
        assert is_eligible_emigrate(profile, baseline_macro) is True

    def test_ineligible_over_65(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=70, savings=1_000_000)
        assert is_eligible_emigrate(profile, baseline_macro) is False

    def test_ineligible_low_savings(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(savings=50_000, neuroticism=0.3)
        assert is_eligible_emigrate(profile, baseline_macro) is False

    def test_geopolitical_stress_path(self, baseline_macro: MacroState) -> None:
        macro = replace(baseline_macro, taiwan_strait_risk=0.8)
        profile = _make_profile(neuroticism=0.7, savings=250_000)
        assert is_eligible_emigrate(profile, macro) is True

    def test_geopolitical_stress_requires_minimum_savings(self, baseline_macro: MacroState) -> None:
        macro = replace(baseline_macro, taiwan_strait_risk=0.8)
        profile = _make_profile(neuroticism=0.7, savings=100_000)
        assert is_eligible_emigrate(profile, macro) is False


class TestEligibilityChangeJob:
    """Tests for is_eligible_change_job."""

    def test_eligible_proactive_worker(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=30, extraversion=0.6, monthly_income=25_000)
        assert is_eligible_change_job(profile, baseline_macro) is True

    def test_ineligible_retired(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(occupation="退休", monthly_income=0)
        assert is_eligible_change_job(profile, baseline_macro) is False

    def test_ineligible_too_young(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=18)
        assert is_eligible_change_job(profile, baseline_macro) is False

    def test_eligible_high_unemployment_stress(self, baseline_macro: MacroState) -> None:
        macro = replace(baseline_macro, unemployment_rate=0.08)
        profile = _make_profile(age=30, extraversion=0.3, monthly_income=20_000)
        assert is_eligible_change_job(profile, macro) is True


class TestEligibilityInvest:
    """Tests for is_eligible_invest."""

    def test_eligible_with_savings_and_openness(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(savings=200_000, openness=0.6, monthly_income=30_000)
        assert is_eligible_invest(profile, baseline_macro) is True

    def test_ineligible_low_savings(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(savings=50_000)
        assert is_eligible_invest(profile, baseline_macro) is False

    def test_ineligible_low_openness(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(savings=200_000, openness=0.2)
        assert is_eligible_invest(profile, baseline_macro) is False


class TestEligibilityHaveChild:
    """Tests for is_eligible_have_child."""

    def test_eligible_married_in_age_range(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=32, marital_status="已婚", monthly_income=25_000)
        assert is_eligible_have_child(profile, baseline_macro) is True

    def test_ineligible_unmarried(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(marital_status="未婚")
        assert is_eligible_have_child(profile, baseline_macro) is False

    def test_ineligible_too_old(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=50, marital_status="已婚")
        assert is_eligible_have_child(profile, baseline_macro) is False

    def test_ineligible_low_income(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=30, marital_status="已婚", monthly_income=15_000)
        assert is_eligible_have_child(profile, baseline_macro) is False


class TestEligibilityAdjustSpending:
    """Tests for is_eligible_adjust_spending."""

    def test_eligible_high_inflation(self, baseline_macro: MacroState) -> None:
        macro = replace(baseline_macro, cpi_yoy=0.04)
        profile = _make_profile(monthly_income=20_000)
        assert is_eligible_adjust_spending(profile, macro) is True

    def test_eligible_low_confidence(self, baseline_macro: MacroState) -> None:
        macro = replace(baseline_macro, consumer_confidence=30.0)
        profile = _make_profile(monthly_income=20_000)
        assert is_eligible_adjust_spending(profile, macro) is True

    def test_ineligible_no_income(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(monthly_income=0)
        assert is_eligible_adjust_spending(profile, baseline_macro) is False

    def test_ineligible_normal_conditions(self, baseline_macro: MacroState) -> None:
        # CPI 1.9% (< 2.5%), confidence 50 (between 45 and 75)
        macro = replace(baseline_macro, consumer_confidence=50.0, cpi_yoy=0.019)
        profile = _make_profile(monthly_income=20_000)
        assert is_eligible_adjust_spending(profile, macro) is False


class TestEligibilityEmploymentChange:
    """Tests for is_eligible_employment_change."""

    def test_quit_path_high_neuroticism(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=30, neuroticism=0.7, monthly_income=25_000, savings=400_000)
        assert is_eligible_employment_change(profile, baseline_macro) is True

    def test_strike_path(self, baseline_macro: MacroState) -> None:
        macro = replace(baseline_macro, consumer_confidence=30.0)
        profile = _make_profile(age=35, political_stance=0.8, monthly_income=25_000)
        assert is_eligible_employment_change(profile, macro) is True

    def test_lie_flat_path(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=28, openness=0.3, conscientiousness=0.3, monthly_income=20_000)
        assert is_eligible_employment_change(profile, baseline_macro) is True

    def test_ineligible_student(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(occupation="學生", age=20, monthly_income=0)
        assert is_eligible_employment_change(profile, baseline_macro) is False


class TestEligibilityRelocate:
    """Tests for is_eligible_relocate."""

    def test_eligible_rent_pressure(self, baseline_macro: MacroState) -> None:
        # District price 18_500, income 1_000 → 18_500 > 1_000 * 15
        profile = _make_profile(district="中西區", monthly_income=1_000, housing_type="私人住宅")
        assert is_eligible_relocate(profile, baseline_macro) is True

    def test_eligible_school_need(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(age=35, marital_status="已婚", housing_type="私人住宅")
        assert is_eligible_relocate(profile, baseline_macro) is True

    def test_ineligible_public_housing(self, baseline_macro: MacroState) -> None:
        profile = _make_profile(housing_type="公屋")
        assert is_eligible_relocate(profile, baseline_macro) is False


# ---------------------------------------------------------------------------
# Filter + sampling tests
# ---------------------------------------------------------------------------


class TestFilterEligibleAgents:
    """Tests for filter_eligible_agents dispatcher."""

    def test_unknown_decision_type_returns_empty(self, baseline_macro: MacroState) -> None:
        profiles = [_make_profile()]
        result = filter_eligible_agents(profiles, baseline_macro, "unknown_type")
        assert result == []

    def test_no_eligible_agents_returns_empty(self, baseline_macro: MacroState) -> None:
        profiles = [_make_profile(monthly_income=0)]
        result = filter_eligible_agents(profiles, baseline_macro, DecisionType.CHANGE_JOB)
        assert result == []

    def test_sampling_cap_respected(self, baseline_macro: MacroState) -> None:
        macro = replace(baseline_macro, cpi_yoy=0.04)
        profiles = [_make_profile(id=i, monthly_income=25_000) for i in range(200)]
        result = filter_eligible_agents(profiles, macro, DecisionType.ADJUST_SPENDING, max_agents=10, rng_seed=42)
        assert len(result) <= 10

    def test_sample_rate_controls_size(self, baseline_macro: MacroState) -> None:
        macro = replace(baseline_macro, cpi_yoy=0.04)
        profiles = [_make_profile(id=i, monthly_income=25_000) for i in range(100)]
        result = filter_eligible_agents(
            profiles,
            macro,
            DecisionType.ADJUST_SPENDING,
            sample_rate=0.05,
            max_agents=50,
            rng_seed=42,
        )
        # 100 eligible * 0.05 = 5 agents
        assert len(result) == 5

    def test_deterministic_with_seed(self, baseline_macro: MacroState) -> None:
        macro = replace(baseline_macro, cpi_yoy=0.04)
        profiles = [_make_profile(id=i, monthly_income=25_000) for i in range(50)]
        r1 = filter_eligible_agents(profiles, macro, DecisionType.ADJUST_SPENDING, rng_seed=99)
        r2 = filter_eligible_agents(profiles, macro, DecisionType.ADJUST_SPENDING, rng_seed=99)
        assert [p.id for p in r1] == [p.id for p in r2]


# ---------------------------------------------------------------------------
# Mortgage helper tests
# ---------------------------------------------------------------------------


class TestMortgageHelpers:
    """Tests for loan tenor and mortgage payment calculations."""

    def test_loan_tenor_young_borrower(self) -> None:
        assert _loan_tenor_years(30) == 25  # 75 - 30 = 45, capped at 25

    def test_loan_tenor_old_borrower(self) -> None:
        assert _loan_tenor_years(55) == 20  # 75 - 55 = 20

    def test_monthly_payment_positive(self) -> None:
        pmt = _monthly_mortgage_payment(5_000_000, 0.70, 0.0475, 35)
        assert pmt > 0
        # ~HK$5M * 0.7 = $3.5M principal, ~$20K/month seems reasonable
        assert 15_000 < pmt < 30_000


# ---------------------------------------------------------------------------
# Summary and macro adjustment tests
# ---------------------------------------------------------------------------


class TestBuildSummary:
    """Tests for _build_summary helper."""

    def test_empty_decisions(self) -> None:
        summary = _build_summary("s1", 1, [])
        assert summary["total_decisions"] == 0
        assert summary["counts_by_type"] == {}

    def test_counts_grouped_correctly(self) -> None:
        decisions = [
            AgentDecision("s1", 1, 1, "buy_property", "buy", "reason", 0.8),
            AgentDecision("s1", 2, 1, "buy_property", "wait", "reason", 0.6),
            AgentDecision("s1", 3, 1, "emigrate", "emigrate", "reason", 0.9),
        ]
        summary = _build_summary("s1", 1, decisions)
        assert summary["total_decisions"] == 3
        assert summary["counts_by_type"]["buy_property"] == {"buy": 1, "wait": 1}
        assert summary["counts_by_type"]["emigrate"] == {"emigrate": 1}


class TestDeriveMacroAdjustments:
    """Tests for _derive_macro_adjustments."""

    def test_no_decisions_returns_empty(self) -> None:
        result = _derive_macro_adjustments([])
        assert result == {}

    def test_net_buyers_increase_ccl(self) -> None:
        decisions = [AgentDecision("s1", i, 1, "buy_property", "buy", "r", 0.8) for i in range(10)]
        result = _derive_macro_adjustments(decisions)
        assert "ccl_index" in result
        assert result["ccl_index"] > 0

    def test_net_emigrants_decrease_migration(self) -> None:
        decisions = [AgentDecision("s1", i, 1, "emigrate", "emigrate", "r", 0.9) for i in range(10)]
        result = _derive_macro_adjustments(decisions)
        assert "net_migration" in result
        assert result["net_migration"] < 0

    def test_net_cutters_decrease_confidence(self) -> None:
        decisions = [AgentDecision("s1", i, 1, "adjust_spending", "cut_spending", "r", 0.7) for i in range(10)]
        result = _derive_macro_adjustments(decisions)
        assert "consumer_confidence" in result
        assert result["consumer_confidence"] < 0

    def test_births_increase_confidence(self) -> None:
        decisions = [AgentDecision("s1", i, 1, "have_child", "have_child", "r", 0.8) for i in range(10)]
        result = _derive_macro_adjustments(decisions)
        assert "consumer_confidence" in result
        assert result["consumer_confidence"] > 0

    def test_quit_increases_unemployment(self) -> None:
        decisions = [AgentDecision("s1", i, 1, "employment_change", "quit", "r", 0.6) for i in range(5)]
        result = _derive_macro_adjustments(decisions)
        assert "unemployment_rate" in result
        assert result["unemployment_rate"] > 0

    def test_gba_relocation_decreases_migration(self) -> None:
        decisions = [AgentDecision("s1", i, 1, "relocate", "relocate_gba", "r", 0.7) for i in range(10)]
        result = _derive_macro_adjustments(decisions)
        assert "net_migration" in result
        assert result["net_migration"] < 0

    def test_retail_investor_has_zero_hsi_impact(self) -> None:
        decisions = [AgentDecision("s1", i, 1, "invest", "invest_stocks", "r", 0.8) for i in range(20)]
        result = _derive_macro_adjustments(decisions)
        assert "hsi_level" not in result  # delta is 0.0


# ---------------------------------------------------------------------------
# DecisionEngine integration tests
# ---------------------------------------------------------------------------


class TestDecisionEngine:
    """Integration tests for the full decision pipeline."""

    @pytest.mark.asyncio
    async def test_process_round_no_eligible_agents(self, baseline_macro: MacroState) -> None:
        """No eligible agents should produce zero decisions."""
        engine = DecisionEngine(llm_client=MagicMock())
        # All profiles are students with no income — ineligible for most types
        profiles = {i: _make_profile(id=i, occupation="學生", monthly_income=0, savings=0, age=18) for i in range(5)}
        with patch("backend.app.services.decision_engine.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            summary = await engine.process_round_decisions(
                session_id="test-session",
                round_number=1,
                profiles_by_id=profiles,
                macro_state=baseline_macro,
            )

        assert summary["total_decisions"] == 0

    @pytest.mark.asyncio
    async def test_process_round_with_decisions(self, baseline_macro: MacroState) -> None:
        """When deliberator returns decisions, they are counted in summary."""
        mock_decisions = [
            AgentDecision("s1", 1, 1, "buy_property", "buy", "good price", 0.8),
            AgentDecision("s1", 2, 1, "buy_property", "wait", "too expensive", 0.6),
        ]

        engine = DecisionEngine(llm_client=MagicMock())
        engine._deliberator = MagicMock()
        engine._deliberator.deliberate_batch = AsyncMock(return_value=mock_decisions)

        macro_high_inflation = replace(baseline_macro, cpi_yoy=0.04)
        profiles = {i: _make_profile(id=i, monthly_income=50_000, savings=2_000_000) for i in range(5)}

        with patch("backend.app.services.decision_engine.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            summary = await engine.process_round_decisions(
                session_id="s1",
                round_number=1,
                profiles_by_id=profiles,
                macro_state=macro_high_inflation,
            )

        assert summary["total_decisions"] >= 2

    @pytest.mark.asyncio
    async def test_process_round_handles_deliberation_error(self, baseline_macro: MacroState) -> None:
        """If deliberation raises, it should be caught (not crash the engine)."""
        engine = DecisionEngine(llm_client=MagicMock())
        engine._deliberator = MagicMock()
        engine._deliberator.deliberate_batch = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        macro = replace(baseline_macro, cpi_yoy=0.04)
        profiles = {i: _make_profile(id=i, monthly_income=30_000) for i in range(5)}

        with patch("backend.app.services.decision_engine.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise
            summary = await engine.process_round_decisions(
                session_id="s1",
                round_number=1,
                profiles_by_id=profiles,
                macro_state=macro,
            )

        # Error logged, 0 decisions
        assert summary["total_decisions"] == 0

    @pytest.mark.asyncio
    async def test_macro_updater_called_when_adjustments_exist(self, baseline_macro: MacroState) -> None:
        """If decisions produce macro adjustments, the updater callback fires."""
        mock_decisions = [AgentDecision("s1", i, 1, "emigrate", "emigrate", "leaving", 0.9) for i in range(10)]

        engine = DecisionEngine(llm_client=MagicMock())
        engine._deliberator = MagicMock()
        engine._deliberator.deliberate_batch = AsyncMock(return_value=mock_decisions)

        updater = AsyncMock()

        with patch("backend.app.services.decision_engine.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

            await engine.process_round_decisions(
                session_id="s1",
                round_number=1,
                profiles_by_id={1: _make_profile()},
                macro_state=baseline_macro,
                macro_state_updater=updater,
            )

        updater.assert_awaited_once()
        call_args = updater.call_args[0][0]
        assert isinstance(call_args, dict)


# ---------------------------------------------------------------------------
# Task 4: topic_tags + emotional_reaction persistence
# ---------------------------------------------------------------------------


class TestTopicTagsPersistence:
    """Tests for persisting topic_tags and emotional_reaction to agent_decisions."""

    @pytest.mark.asyncio
    async def test_stakeholder_decision_persists_topic_tags(self, test_db) -> None:
        """topic_tags and emotional_reaction can be persisted to agent_decisions."""
        import json

        from backend.app.services.cognitive_agent_engine import DeliberationResult

        deliberation = DeliberationResult(
            agent_id="1",
            decision="emigrate",
            reasoning="I fear instability",
            belief_updates={},
            stance_statement="Will leave",
            topic_tags=("移民", "就業"),
            emotional_reaction="焦慮，對前途感到迷茫",
        )

        await test_db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, seed_text, agent_count, round_count,
                llm_provider, llm_model, oasis_db_path)
               VALUES ('sess1','test','kg_driven','seed',10,5,'openrouter','deepseek','')"""
        )
        await test_db.execute(
            """INSERT INTO agent_decisions
               (session_id, agent_id, round_number, decision_type, action, reasoning,
                topic_tags, emotional_reaction)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                "sess1",
                1,
                1,
                deliberation.decision,
                deliberation.decision,
                deliberation.reasoning,
                json.dumps(list(deliberation.topic_tags)),
                deliberation.emotional_reaction,
            ),
        )
        await test_db.commit()

        row = await (
            await test_db.execute("SELECT topic_tags, emotional_reaction FROM agent_decisions WHERE agent_id=1")
        ).fetchone()

        import json as _json_check

        assert _json_check.loads(row["topic_tags"]) == ["移民", "就業"]
        assert row["emotional_reaction"] == "焦慮，對前途感到迷茫"

    @pytest.mark.asyncio
    async def test_store_decisions_includes_topic_tags(self, test_db) -> None:
        """DecisionEngine._store_decisions persists topic_tags and emotional_reaction."""
        import contextlib
        import json
        from unittest.mock import patch as _patch

        from backend.app.models.decision import AgentDecision
        from backend.app.services.decision_engine import DecisionEngine

        decision = AgentDecision(
            session_id="sess2",
            agent_id=42,
            round_number=3,
            decision_type="emigrate",
            action="emigrate",
            reasoning="instability",
            confidence=0.8,
            topic_tags=("移民", "自由"),
            emotional_reaction="擔憂",
        )

        await test_db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, seed_text, agent_count, round_count,
                llm_provider, llm_model, oasis_db_path)
               VALUES ('sess2','test2','hk_demographic','seed',10,5,'openrouter','deepseek','')"""
        )
        await test_db.commit()

        engine = DecisionEngine()
        engine._schema_initialised = True

        @contextlib.asynccontextmanager
        async def _fake_get_db():
            yield test_db

        with _patch("backend.app.services.decision_engine.get_db", side_effect=_fake_get_db):
            await engine._store_decisions([decision])

        row = await (
            await test_db.execute("SELECT topic_tags, emotional_reaction FROM agent_decisions WHERE agent_id=42")
        ).fetchone()

        assert row is not None
        assert json.loads(row["topic_tags"]) == ["移民", "自由"]
        assert row["emotional_reaction"] == "擔憂"

    @pytest.mark.asyncio
    async def test_store_decisions_null_topic_tags_for_passive_agents(self, test_db) -> None:
        """Passive agents (no topic_tags) store NULL in agent_decisions."""
        import contextlib
        from unittest.mock import patch as _patch

        from backend.app.models.decision import AgentDecision
        from backend.app.services.decision_engine import DecisionEngine

        decision = AgentDecision(
            session_id="sess3",
            agent_id=99,
            round_number=1,
            decision_type="stay",
            action="stay",
            reasoning="comfortable here",
            confidence=0.7,
        )

        await test_db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, seed_text, agent_count, round_count,
                llm_provider, llm_model, oasis_db_path)
               VALUES ('sess3','test3','hk_demographic','seed',10,5,'openrouter','deepseek','')"""
        )
        await test_db.commit()

        engine = DecisionEngine()
        engine._schema_initialised = True

        @contextlib.asynccontextmanager
        async def _fake_get_db():
            yield test_db

        with _patch("backend.app.services.decision_engine.get_db", side_effect=_fake_get_db):
            await engine._store_decisions([decision])

        row = await (
            await test_db.execute("SELECT topic_tags, emotional_reaction FROM agent_decisions WHERE agent_id=99")
        ).fetchone()

        assert row is not None
        assert row["topic_tags"] is None
        assert row["emotional_reaction"] is None
