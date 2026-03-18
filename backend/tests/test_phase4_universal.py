# backend/tests/test_phase4_universal.py
"""Unit tests for Phase 4 universal prediction maturity.

Covers:
- ExternalDataFeed: cache, Taiwan risk proxy, DB fallback
- MacroController.apply_agent_actions_feedback
- StrategicPlanner: helpers + default strategy
- CrossDomainValidator: domain listing, aggregation
- KGSessionState.agent_strategies field
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.kg_session_state import KGSessionState
from backend.app.services.cross_domain_validator import (
    CrossDomainValidator,
    _aggregate,
    _DOMAIN_CONFIGS,
)
from backend.app.services.strategic_planner import (
    AgentStrategy,
    StrategicPlanner,
    _check_contested,
    _default_strategy,
    _validated_posture,
)


# ---------------------------------------------------------------------------
# KGSessionState.agent_strategies
# ---------------------------------------------------------------------------

class TestKGSessionStateStrategies:
    def test_agent_strategies_defaults_empty(self) -> None:
        state = KGSessionState()
        assert state.agent_strategies == {}

    def test_agent_strategies_mutable(self) -> None:
        state = KGSessionState()
        state.agent_strategies["agent_1"] = {"plan": "test", "created_round": 3}
        assert state.agent_strategies["agent_1"]["plan"] == "test"


# ---------------------------------------------------------------------------
# ExternalDataFeed helpers
# ---------------------------------------------------------------------------

class TestExternalDataFeed:
    @pytest.mark.asyncio
    async def test_fetch_uses_cache(self) -> None:
        from backend.app.services.external_data_feed import ExternalDataFeed  # noqa: PLC0415
        feed = ExternalDataFeed()
        feed._cache = {"fed_rate": 0.045}
        feed._cache_ts = 1e18  # far future → not expired

        result = await feed.fetch()
        assert result["fed_rate"] == pytest.approx(0.045)

    @pytest.mark.asyncio
    async def test_fetch_returns_dict(self) -> None:
        from backend.app.services.external_data_feed import ExternalDataFeed  # noqa: PLC0415
        feed = ExternalDataFeed()
        # With no API key and no DB, should return empty dict gracefully
        result = await feed.fetch(force_refresh=True)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_taiwan_risk_fallback(self) -> None:
        from backend.app.services.external_data_feed import (  # noqa: PLC0415
            ExternalDataFeed,
            _TAIWAN_RISK_BASE,
        )
        feed = ExternalDataFeed()
        # DB read will fail in test env → should return base risk
        risk = await feed._fetch_taiwan_risk_proxy()
        assert risk == pytest.approx(_TAIWAN_RISK_BASE, abs=0.01)

    @pytest.mark.asyncio
    async def test_db_fallback_returns_dict(self) -> None:
        from backend.app.services.external_data_feed import ExternalDataFeed  # noqa: PLC0415
        result = await ExternalDataFeed._load_db_fallback()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# MacroController.apply_agent_actions_feedback
# ---------------------------------------------------------------------------

def _make_macro_state(**kwargs):
    """Build a MacroState with default values, overriding with kwargs."""
    from backend.app.services.macro_state import (  # noqa: PLC0415
        MacroState, BASELINE_AVG_SQFT_PRICE, BASELINE_STAMP_DUTY,
    )
    defaults = dict(
        hibor_1m=0.04,
        prime_rate=0.055,
        unemployment_rate=0.032,
        median_monthly_income=20800,
        ccl_index=150.0,
        avg_sqft_price=dict(BASELINE_AVG_SQFT_PRICE),
        mortgage_cap=0.70,
        stamp_duty_rates=dict(BASELINE_STAMP_DUTY),
        gdp_growth=0.025,
        cpi_yoy=0.019,
        hsi_level=20060.0,
        consumer_confidence=45.0,
        net_migration=2000,
        birth_rate=5.3,
        policy_flags={},
    )
    defaults.update(kwargs)
    return MacroState(**defaults)


def _make_mock_db(rows):
    """Helper: create a mock get_db context manager returning given rows."""
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)
    mock_conn.execute = AsyncMock(return_value=mock_cursor)
    return mock_conn


class TestMicroMacroFeedback:
    @pytest.mark.asyncio
    async def test_no_rows_returns_unchanged(self) -> None:
        from backend.app.services.macro_controller import MacroController  # noqa: PLC0415

        mc = MacroController()
        state = _make_macro_state()

        with patch("backend.app.utils.db.get_db", return_value=_make_mock_db([])):
            result = await mc.apply_agent_actions_feedback(state, "sess_1", round_number=5)
        assert result is state  # unchanged

    @pytest.mark.asyncio
    async def test_invest_actions_raise_confidence(self) -> None:
        from backend.app.services.macro_controller import MacroController  # noqa: PLC0415

        mc = MacroController()
        state = _make_macro_state(consumer_confidence=45.0)
        rows = [("invest",)] * 50 + [("observe",)] * 50

        with patch("backend.app.utils.db.get_db", return_value=_make_mock_db(rows)):
            result = await mc.apply_agent_actions_feedback(state, "sess_1", round_number=5)

        assert result.consumer_confidence > state.consumer_confidence

    @pytest.mark.asyncio
    async def test_resign_actions_raise_unemployment(self) -> None:
        from backend.app.services.macro_controller import MacroController  # noqa: PLC0415

        mc = MacroController()
        state = _make_macro_state(unemployment_rate=0.030)
        rows = [("resign",)] * 80 + [("observe",)] * 20

        with patch("backend.app.utils.db.get_db", return_value=_make_mock_db(rows)):
            result = await mc.apply_agent_actions_feedback(state, "sess_1", round_number=5)

        assert result.unemployment_rate > state.unemployment_rate


# ---------------------------------------------------------------------------
# StrategicPlanner helpers
# ---------------------------------------------------------------------------

class TestValidatedPosture:
    def test_valid_postures(self) -> None:
        assert _validated_posture("transparent") == "transparent"
        assert _validated_posture("strategic") == "strategic"
        assert _validated_posture("adversarial") == "adversarial"

    def test_invalid_posture_falls_back(self) -> None:
        assert _validated_posture("unknown") == "transparent"
        assert _validated_posture("") == "transparent"


class TestDefaultStrategy:
    def test_default_is_observe(self) -> None:
        s = _default_strategy("agent_1", round_num=3, is_contested=False)
        assert s.round_1_intent == "observe"
        assert s.information_posture == "transparent"
        assert s.is_contested is False

    def test_contested_default(self) -> None:
        s = _default_strategy("agent_1", round_num=3, is_contested=True)
        assert s.is_contested is True


class TestCheckContested:
    def test_no_relationships_not_contested(self) -> None:
        kg_state = KGSessionState()
        result = _check_contested({}, kg_state, "agent_1")
        assert result is False

    def test_low_trust_marks_contested(self) -> None:
        kg_state = KGSessionState()
        rel_mock = MagicMock()
        rel_mock.trust = -0.5
        kg_state.relationship_states[("agent_1", "agent_2")] = rel_mock
        result = _check_contested({}, kg_state, "agent_1")
        assert result is True

    def test_high_trust_not_contested(self) -> None:
        kg_state = KGSessionState()
        rel_mock = MagicMock()
        rel_mock.trust = 0.8
        kg_state.relationship_states[("agent_1", "agent_2")] = rel_mock
        result = _check_contested({}, kg_state, "agent_1")
        assert result is False


class TestStrategicPlannerGetContext:
    def test_no_plan_returns_empty(self) -> None:
        planner = StrategicPlanner.__new__(StrategicPlanner)
        kg_state = KGSessionState()
        result = planner.get_strategy_context(kg_state, "agent_1", current_round=5)
        assert result == ""

    def test_plan_injected_into_context(self) -> None:
        planner = StrategicPlanner.__new__(StrategicPlanner)
        kg_state = KGSessionState()
        kg_state.agent_strategies["agent_1"] = {
            "plan": "build alliances",
            "round_1_intent": "negotiate",
            "information_posture": "strategic",
            "is_contested": False,
            "created_round": 3,
        }
        result = planner.get_strategy_context(kg_state, "agent_1", current_round=4)
        assert "build alliances" in result
        assert "negotiate" in result

    def test_stale_plan_returns_empty(self) -> None:
        planner = StrategicPlanner.__new__(StrategicPlanner)
        kg_state = KGSessionState()
        kg_state.agent_strategies["agent_1"] = {
            "plan": "old plan",
            "round_1_intent": "observe",
            "information_posture": "transparent",
            "is_contested": False,
            "created_round": 1,
        }
        # Round 20 → stale (age = 19 > _PLAN_HORIZON * 2 = 6)
        result = planner.get_strategy_context(kg_state, "agent_1", current_round=20)
        assert result == ""

    def test_contested_note_in_context(self) -> None:
        planner = StrategicPlanner.__new__(StrategicPlanner)
        kg_state = KGSessionState()
        kg_state.agent_strategies["agent_1"] = {
            "plan": "sabotage talks",
            "round_1_intent": "mislead",
            "information_posture": "adversarial",
            "is_contested": True,
            "created_round": 4,
        }
        result = planner.get_strategy_context(kg_state, "agent_1", current_round=5)
        assert "CONTESTED" in result


# ---------------------------------------------------------------------------
# CrossDomainValidator
# ---------------------------------------------------------------------------

class TestCrossDomainValidator:
    def test_list_domains_returns_three(self) -> None:
        domains = CrossDomainValidator.list_domains()
        assert len(domains) == 3
        ids = {d["domain_id"] for d in domains}
        assert "hk_macro" in ids
        assert "us_markets" in ids
        assert "geopolitical" in ids

    def test_validate_domain_unknown_raises(self) -> None:
        v = CrossDomainValidator()
        with pytest.raises(ValueError, match="Unknown domain"):
            import asyncio  # noqa: PLC0415
            asyncio.get_event_loop().run_until_complete(
                v.validate_domain("unknown_domain", "2021-Q1", "2023-Q4")
            )

    @pytest.mark.asyncio
    async def test_validate_all_returns_correct_keys(self) -> None:
        v = CrossDomainValidator()
        # Mock the reporter to return empty results (no DB in tests)
        v._reporter.generate = AsyncMock(return_value={
            "period_start": "2021-Q1",
            "period_end": "2023-Q4",
            "metrics_validated": 0,
            "overall_grade": "N/A",
            "overall_score": 0.0,
            "summary": "No data",
            "results": [],
        })
        result = await v.validate_all("2021-Q1", "2023-Q4")
        assert "domains" in result
        assert "aggregate_grade" in result
        assert "domains_passed" in result
        assert "credibility_summary" in result
        assert len(result["domains"]) == 3

    def test_aggregate_all_na(self) -> None:
        reports = {
            "hk_macro": {"overall_grade": "N/A", "overall_score": 0.0, "display_name": "HK"},
            "us_markets": {"overall_grade": "N/A", "overall_score": 0.0, "display_name": "US"},
            "geopolitical": {"overall_grade": "N/A", "overall_score": 0.0, "display_name": "Geo"},
        }
        result = _aggregate(reports, "2021-Q1", "2023-Q4")
        assert result["aggregate_grade"] == "N/A"
        assert result["domains_passed"] == 0

    def test_aggregate_all_pass(self) -> None:
        reports = {
            "hk_macro": {"overall_grade": "A", "overall_score": 0.85, "display_name": "HK"},
            "us_markets": {"overall_grade": "B", "overall_score": 0.70, "display_name": "US"},
            "geopolitical": {"overall_grade": "C", "overall_score": 0.55, "display_name": "Geo"},
        }
        result = _aggregate(reports, "2021-Q1", "2023-Q4")
        assert result["domains_passed"] == 3
        assert result["aggregate_grade"] == "C"  # worst grade
        assert result["aggregate_score"] == pytest.approx((0.85 + 0.70 + 0.55) / 3, abs=0.01)


# ---------------------------------------------------------------------------
# CognitiveAgentEngine: strategy_block injected into prompt
# ---------------------------------------------------------------------------

class TestCognitiveEngineStrategyBlock:
    def test_strategy_block_in_prompt(self) -> None:
        from backend.app.services.cognitive_agent_engine import _build_deliberation_prompt  # noqa: PLC0415
        ctx = {
            "agent_id": "a1",
            "name": "Alice",
            "role": "diplomat",
            "strategic_context": "\nYour current strategic plan: build coalition (This round intent: negotiate; posture: strategic)",
        }
        prompt = _build_deliberation_prompt(ctx, "Test scenario", ("trust", "stability"))
        assert "build coalition" in prompt

    def test_no_strategy_block_absent_from_prompt(self) -> None:
        from backend.app.services.cognitive_agent_engine import _build_deliberation_prompt  # noqa: PLC0415
        ctx = {
            "agent_id": "a1",
            "name": "Bob",
            "role": "activist",
        }
        prompt = _build_deliberation_prompt(ctx, "Test scenario", ("trust",))
        assert "strategic plan" not in prompt
