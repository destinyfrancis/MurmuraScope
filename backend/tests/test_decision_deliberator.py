"""Tests for DecisionDeliberator — LLM batch deliberation, JSON parsing, fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.decision import DECISION_ACTIONS, AgentDecision, DecisionType
from backend.app.services.agent_factory import AgentProfile
from backend.app.services.decision_deliberator import (
    _DEFAULT_ACTION_FALLBACKS,
    _STOCHASTIC_FALLBACK_DIST,
    DecisionDeliberator,
    PeerDistressSignal,
    SocialContagionContext,
    _clamp_float,
    _extract_list,
    _safe_int,
    _validate_action,
)
from backend.app.services.macro_state import BASELINE_AVG_SQFT_PRICE, BASELINE_STAMP_DUTY, MacroState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_macro() -> MacroState:
    return MacroState(
        hibor_1m=4.2,
        prime_rate=5.75,
        unemployment_rate=2.9,
        median_monthly_income=20_000,
        ccl_index=152.3,
        avg_sqft_price=BASELINE_AVG_SQFT_PRICE,
        mortgage_cap=0.7,
        stamp_duty_rates=BASELINE_STAMP_DUTY,
        gdp_growth=3.2,
        cpi_yoy=2.1,
        hsi_level=16_800,
        consumer_confidence=88.5,
        net_migration=-20_000,
        birth_rate=0.77,
        policy_flags={"cool_off_removed": True},
    )


def _make_profile(agent_id: int, age: int = 35, income: int = 25_000) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        agent_type="npc",
        age=age,
        sex="M",
        district="沙田",
        occupation="輔助專業人員",
        income_bracket="$25,000-$39,999",
        education_level="學位或以上",
        marital_status="已婚",
        housing_type="私人住宅",
        openness=0.5,
        conscientiousness=0.5,
        extraversion=0.5,
        agreeableness=0.5,
        neuroticism=0.5,
        monthly_income=income,
        savings=200_000,
    )


@pytest.fixture()
def mock_llm():
    client = MagicMock()
    client.chat_json = AsyncMock()
    return client


@pytest.fixture()
def deliberator(mock_llm):
    return DecisionDeliberator(llm_client=mock_llm, seed=42)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestSafeInt:
    def test_int_value(self):
        assert _safe_int(42) == 42

    def test_string_value(self):
        assert _safe_int("7") == 7

    def test_none_value(self):
        assert _safe_int(None) is None

    def test_invalid_string(self):
        assert _safe_int("abc") is None


class TestClampFloat:
    def test_normal_value(self):
        assert _clamp_float(0.5) == 0.5

    def test_clamp_high(self):
        assert _clamp_float(1.5) == 1.0

    def test_clamp_low(self):
        assert _clamp_float(-0.3) == 0.0

    def test_invalid_returns_default(self):
        assert _clamp_float("bad") == 0.5


class TestValidateAction:
    def test_valid_action(self):
        assert _validate_action("buy", DecisionType.BUY_PROPERTY) == "buy"

    def test_invalid_action_returns_fallback(self):
        result = _validate_action("fly_away", DecisionType.EMIGRATE)
        assert result == "stay"

    def test_all_decision_types_have_fallback(self):
        for dt in (
            DecisionType.BUY_PROPERTY,
            DecisionType.EMIGRATE,
            DecisionType.CHANGE_JOB,
            DecisionType.INVEST,
            DecisionType.HAVE_CHILD,
            DecisionType.ADJUST_SPENDING,
        ):
            assert dt.value in _DEFAULT_ACTION_FALLBACKS


class TestExtractList:
    def test_top_level_list(self):
        assert _extract_list([{"a": 1}]) == [{"a": 1}]

    def test_wrapped_decisions(self):
        assert _extract_list({"decisions": [{"a": 1}]}) == [{"a": 1}]

    def test_wrapped_results(self):
        assert _extract_list({"results": [{"a": 1}]}) == [{"a": 1}]

    def test_no_list_returns_none(self):
        assert _extract_list({"foo": "bar"}) is None

    def test_string_returns_none(self):
        assert _extract_list("not a list") is None


# ---------------------------------------------------------------------------
# SocialContagionContext
# ---------------------------------------------------------------------------


class TestSocialContagionContext:
    def test_inactive_produces_empty_prompt(self):
        ctx = SocialContagionContext(
            agent_id=1,
            distress_signals=(),
            distress_ratio=0.0,
            contagion_active=False,
        )
        assert ctx.to_prompt_section() == ""

    def test_active_produces_prompt(self):
        signals = tuple(
            PeerDistressSignal(
                peer_agent_id=i,
                peer_username=f"user_{i}",
                signal_type="decision",
                detail="emigrate",
                trust_score=0.7,
            )
            for i in range(3)
        )
        ctx = SocialContagionContext(
            agent_id=10,
            distress_signals=signals,
            distress_ratio=0.6,
            contagion_active=True,
        )
        prompt = ctx.to_prompt_section()
        assert "社交傳染" in prompt
        assert "user_0" in prompt

    def test_frozen(self):
        ctx = SocialContagionContext(
            agent_id=1,
            distress_signals=(),
            distress_ratio=0.0,
            contagion_active=False,
        )
        with pytest.raises(AttributeError):
            ctx.agent_id = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DecisionDeliberator.deliberate_batch
# ---------------------------------------------------------------------------


class TestDeliberateBatch:
    @pytest.mark.asyncio
    async def test_empty_agents_returns_empty(self, deliberator):
        result = await deliberator.deliberate_batch(
            [],
            _make_macro(),
            DecisionType.BUY_PROPERTY,
            "sess-1",
            1,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_successful_batch(self, deliberator, mock_llm):
        agents = [_make_profile(1), _make_profile(2)]
        mock_llm.chat_json.return_value = [
            {"agent_id": 1, "action": "buy", "reasoning": "樓價合理", "confidence": 0.8},
            {"agent_id": 2, "action": "wait", "reasoning": "觀望", "confidence": 0.6},
        ]

        with patch.object(deliberator, "query_social_contagion", new_callable=AsyncMock) as mock_contagion:
            mock_contagion.return_value = SocialContagionContext(
                agent_id=0,
                distress_signals=(),
                distress_ratio=0.0,
                contagion_active=False,
            )
            results = await deliberator.deliberate_batch(
                agents,
                _make_macro(),
                DecisionType.BUY_PROPERTY,
                "sess-1",
                1,
            )

        assert len(results) == 2
        assert all(isinstance(d, AgentDecision) for d in results)
        assert results[0].action == "buy"
        assert results[1].action == "wait"

    @pytest.mark.asyncio
    async def test_llm_failure_uses_stochastic_fallback(self, deliberator, mock_llm):
        agents = [_make_profile(1), _make_profile(2)]
        mock_llm.chat_json.side_effect = Exception("API Error")

        with patch.object(deliberator, "query_social_contagion", new_callable=AsyncMock) as mock_contagion:
            mock_contagion.return_value = SocialContagionContext(
                agent_id=0,
                distress_signals=(),
                distress_ratio=0.0,
                contagion_active=False,
            )
            results = await deliberator.deliberate_batch(
                agents,
                _make_macro(),
                DecisionType.BUY_PROPERTY,
                "sess-1",
                1,
            )

        assert len(results) == 2
        # Fallback decisions should have reasoning mentioning fallback
        for d in results:
            assert "隨機保守" in d.reasoning or "LLM" in d.reasoning

    @pytest.mark.asyncio
    async def test_omitted_agents_get_fallback(self, deliberator, mock_llm):
        """When LLM only returns decisions for some agents, others get fallback."""
        agents = [_make_profile(1), _make_profile(2), _make_profile(3)]
        # LLM only returns decision for agent 1
        mock_llm.chat_json.return_value = [
            {"agent_id": 1, "action": "stay", "reasoning": "穩定", "confidence": 0.7},
        ]

        with patch.object(deliberator, "query_social_contagion", new_callable=AsyncMock) as mock_contagion:
            mock_contagion.return_value = SocialContagionContext(
                agent_id=0,
                distress_signals=(),
                distress_ratio=0.0,
                contagion_active=False,
            )
            results = await deliberator.deliberate_batch(
                agents,
                _make_macro(),
                DecisionType.EMIGRATE,
                "sess-1",
                1,
            )

        assert len(results) == 3
        agent_ids = {d.agent_id for d in results}
        assert agent_ids == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_invalid_action_replaced_with_fallback(self, deliberator, mock_llm):
        agents = [_make_profile(1)]
        mock_llm.chat_json.return_value = [
            {"agent_id": 1, "action": "fly_to_mars", "reasoning": "太空", "confidence": 0.5},
        ]

        with patch.object(deliberator, "query_social_contagion", new_callable=AsyncMock) as mock_contagion:
            mock_contagion.return_value = SocialContagionContext(
                agent_id=0,
                distress_signals=(),
                distress_ratio=0.0,
                contagion_active=False,
            )
            results = await deliberator.deliberate_batch(
                agents,
                _make_macro(),
                DecisionType.BUY_PROPERTY,
                "sess-1",
                1,
            )

        assert results[0].action == "wait"  # fallback for buy_property

    @pytest.mark.asyncio
    async def test_duplicate_agent_ids_deduplicated(self, deliberator, mock_llm):
        agents = [_make_profile(1)]
        mock_llm.chat_json.return_value = [
            {"agent_id": 1, "action": "buy", "reasoning": "first", "confidence": 0.8},
            {"agent_id": 1, "action": "wait", "reasoning": "duplicate", "confidence": 0.6},
        ]

        with patch.object(deliberator, "query_social_contagion", new_callable=AsyncMock) as mock_contagion:
            mock_contagion.return_value = SocialContagionContext(
                agent_id=0,
                distress_signals=(),
                distress_ratio=0.0,
                contagion_active=False,
            )
            results = await deliberator.deliberate_batch(
                agents,
                _make_macro(),
                DecisionType.BUY_PROPERTY,
                "sess-1",
                1,
            )

        # Should only have one decision per agent
        assert len(results) == 1
        assert results[0].action == "buy"  # keeps first occurrence

    @pytest.mark.asyncio
    async def test_confidence_clamped(self, deliberator, mock_llm):
        agents = [_make_profile(1)]
        mock_llm.chat_json.return_value = [
            {"agent_id": 1, "action": "buy", "reasoning": "test", "confidence": 2.5},
        ]

        with patch.object(deliberator, "query_social_contagion", new_callable=AsyncMock) as mock_contagion:
            mock_contagion.return_value = SocialContagionContext(
                agent_id=0,
                distress_signals=(),
                distress_ratio=0.0,
                contagion_active=False,
            )
            results = await deliberator.deliberate_batch(
                agents,
                _make_macro(),
                DecisionType.BUY_PROPERTY,
                "sess-1",
                1,
            )

        assert results[0].confidence == 1.0


# ---------------------------------------------------------------------------
# Stochastic fallback
# ---------------------------------------------------------------------------


class TestStochasticFallback:
    def test_all_decision_types_have_distribution(self):
        for dt in (
            DecisionType.BUY_PROPERTY,
            DecisionType.EMIGRATE,
            DecisionType.CHANGE_JOB,
            DecisionType.INVEST,
            DecisionType.HAVE_CHILD,
            DecisionType.ADJUST_SPENDING,
        ):
            assert dt.value in _STOCHASTIC_FALLBACK_DIST

    def test_fallback_returns_valid_action(self, deliberator):
        for dt_val in _STOCHASTIC_FALLBACK_DIST:
            fb = deliberator._stochastic_fallback(dt_val)
            valid = DECISION_ACTIONS.get(dt_val, frozenset())
            assert fb["action"] in valid, f"{fb['action']} not in {valid} for {dt_val}"

    def test_fallback_deterministic_with_seed(self):
        d1 = DecisionDeliberator(seed=123)
        d2 = DecisionDeliberator(seed=123)
        for dt_val in _STOCHASTIC_FALLBACK_DIST:
            fb1 = d1._stochastic_fallback(dt_val)
            fb2 = d2._stochastic_fallback(dt_val)
            assert fb1 == fb2


# ---------------------------------------------------------------------------
# PeerDistressSignal
# ---------------------------------------------------------------------------


class TestPeerDistressSignal:
    def test_frozen(self):
        sig = PeerDistressSignal(
            peer_agent_id=1,
            peer_username="test",
            signal_type="triple",
            detail="worries_about: housing",
            trust_score=0.8,
        )
        with pytest.raises(AttributeError):
            sig.trust_score = 0.9  # type: ignore[misc]
