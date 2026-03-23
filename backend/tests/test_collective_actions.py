"""Tests for Phase 18 collective actions — group formation and momentum tracking."""

from __future__ import annotations

import dataclasses

import pytest

from backend.app.models.decision import DECISION_ACTIONS, DecisionType
from backend.app.services.agent_factory import AgentProfile
from backend.app.services.attention_economy import (
    AttentionBudget,
    _compute_sensitivity,
    _extract_topics,
    _post_cost,
    allocate_attention,
    compute_topic_sensitivity,
)
from backend.app.services.collective_actions import (
    AgentGroup,
    CollectiveAction,
)
from backend.app.services.decision_rules import (
    is_eligible_employment_change,
    is_eligible_relocate,
)
from backend.app.services.macro_state import MacroState
from backend.app.services.wealth_transfer import WealthTransfer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_profile(**kwargs) -> AgentProfile:
    """Create a minimal AgentProfile with sensible defaults."""
    defaults = dict(
        id=1,
        agent_type="npc",
        age=30,
        sex="M",
        district="沙田",
        occupation="文員",
        income_bracket="$15,000-$24,999",
        education_level="中學",
        marital_status="未婚",
        housing_type="私人住宅",
        openness=0.5,
        conscientiousness=0.5,
        extraversion=0.5,
        agreeableness=0.5,
        neuroticism=0.5,
        monthly_income=18_000,
        savings=100_000,
        political_stance=0.5,
    )
    defaults.update(kwargs)
    return AgentProfile(**defaults)


def _make_macro(**kwargs) -> MacroState:
    """Create a MacroState with sensible HK defaults."""
    from backend.app.services.macro_state import (
        BASELINE_AVG_SQFT_PRICE,
        BASELINE_STAMP_DUTY,
    )

    defaults = dict(
        hibor_1m=0.045,
        prime_rate=0.0625,
        unemployment_rate=0.04,
        median_monthly_income=20_800,
        ccl_index=150.0,
        avg_sqft_price=BASELINE_AVG_SQFT_PRICE,
        mortgage_cap=0.6,
        stamp_duty_rates=BASELINE_STAMP_DUTY,
        gdp_growth=0.03,
        cpi_yoy=0.02,
        hsi_level=16_000.0,
        consumer_confidence=55.0,
        net_migration=-5,
        birth_rate=6.5,
        policy_flags={},
    )
    defaults.update(kwargs)
    return MacroState(**defaults)


# ---------------------------------------------------------------------------
# Attention Budget Tests
# ---------------------------------------------------------------------------


class TestAttentionBudget:
    def test_frozen_dataclass(self):
        budget = AttentionBudget(
            session_id="sess1",
            agent_id=1,
            round_number=1,
            total_points=24,
            allocations=(("政治", 3), ("金融", 2)),
            remaining=19,
        )
        assert budget.total_points == 24
        assert budget.remaining == 19
        with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
            budget.remaining = 10  # type: ignore[misc]

    def test_post_cost_short(self):
        assert _post_cost("短帖文") == 1

    def test_post_cost_medium(self):
        content = "a" * 200
        assert _post_cost(content) == 2

    def test_post_cost_long(self):
        content = "a" * 400
        assert _post_cost(content) == 3

    def test_extract_topics_hashtag(self):
        content = "#政治改革 大家怎麼看？ #移民 熱潮"
        topics = _extract_topics(content)
        assert "政治改革" in topics or "移民" in topics

    def test_extract_topics_keyword(self):
        content = "今日恒指大升，炒股好時機！"
        topics = _extract_topics(content)
        assert "金融" in topics

    def test_extract_topics_fallback(self):
        content = "hello world"
        topics = _extract_topics(content)
        assert topics == ["general"]

    def test_compute_sensitivity_zero_spend(self):
        sens = _compute_sensitivity(0)
        assert sens == 1.0

    def test_compute_sensitivity_heavy_engagement(self):
        sens = _compute_sensitivity(20)
        assert sens >= 0.3
        assert sens < 1.0

    def test_compute_sensitivity_diminishing(self):
        s1 = _compute_sensitivity(5)
        s2 = _compute_sensitivity(15)
        assert s1 > s2

    def test_compute_sensitivity_floor(self):
        # Even with very heavy engagement, sensitivity stays above floor
        s = _compute_sensitivity(1000)
        assert s >= 0.3

    @pytest.mark.asyncio
    async def test_allocate_attention_basic(self):
        posts = [
            {"content": "今日恒指大升！"},
            {"content": "#移民 問題 越嚟越多"},
            {"content": "x" * 200},  # medium cost
        ]
        budget = await allocate_attention(
            session_id="test_sess",
            round_num=1,
            agent_id=99,
            posts_this_round=posts,
        )
        assert isinstance(budget, AttentionBudget)
        assert budget.total_points == 24
        assert budget.remaining >= 0
        assert budget.remaining <= 24

    @pytest.mark.asyncio
    async def test_allocate_attention_fatigue(self):
        # Many posts should deplete budget
        posts = [{"content": "a" * 400} for _ in range(20)]  # all long posts
        budget = await allocate_attention(
            session_id="test_sess",
            round_num=1,
            agent_id=99,
            posts_this_round=posts,
        )
        # Should have hit fatigue threshold (remaining < 5) at some point
        assert budget.remaining >= 0

    def test_compute_topic_sensitivity_from_budget(self):
        budget = AttentionBudget(
            session_id="s",
            agent_id=1,
            round_number=1,
            total_points=24,
            allocations=(("政治", 6), ("金融", 1)),
            remaining=17,
        )
        sens = compute_topic_sensitivity(budget)
        assert "政治" in sens
        assert "金融" in sens
        # High engagement → lower sensitivity
        assert sens["政治"] < sens["金融"]


# ---------------------------------------------------------------------------
# Wealth Transfer Tests
# ---------------------------------------------------------------------------


class TestWealthTransfer:
    def test_frozen_dataclass(self):
        wt = WealthTransfer(
            session_id="s",
            from_agent_id=1,
            to_agent_id=2,
            to_entity=None,
            amount=5000,
            reason="KOL support",
            round_number=3,
        )
        assert wt.amount == 5000
        with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
            wt.amount = 9999  # type: ignore[misc]

    def test_wealth_transfer_fields(self):
        wt = WealthTransfer(
            session_id="sess_x",
            from_agent_id=10,
            to_agent_id=None,
            to_entity="社區基金",
            amount=2500,
            reason="community fund",
            round_number=7,
        )
        assert wt.to_agent_id is None
        assert wt.to_entity == "社區基金"
        assert wt.round_number == 7


# ---------------------------------------------------------------------------
# Employment Change Eligibility Tests
# ---------------------------------------------------------------------------


class TestEmploymentChangeEligibility:
    def test_quit_eligible_low_unemployment(self):
        profile = _make_profile(
            neuroticism=0.75,
            monthly_income=20_000,
            savings=50_000,
            occupation="文員",
            age=35,
        )
        macro = _make_macro(unemployment_rate=0.03)  # low unemployment
        assert is_eligible_employment_change(profile, macro) is True

    def test_quit_eligible_high_savings(self):
        profile = _make_profile(
            neuroticism=0.65,
            monthly_income=20_000,
            savings=400_000,  # high savings
            occupation="文員",
            age=35,
        )
        macro = _make_macro(unemployment_rate=0.08)  # high unemployment normally blocks
        assert is_eligible_employment_change(profile, macro) is True

    def test_strike_eligible(self):
        profile = _make_profile(
            political_stance=0.8,
            monthly_income=15_000,
            occupation="服務及銷售人員",
            age=28,
        )
        macro = _make_macro(consumer_confidence=35.0)  # very low confidence
        assert is_eligible_employment_change(profile, macro) is True

    def test_lie_flat_eligible(self):
        profile = _make_profile(
            age=28,
            openness=0.3,
            conscientiousness=0.3,
            occupation="非技術工人",
            monthly_income=10_000,
        )
        macro = _make_macro()
        assert is_eligible_employment_change(profile, macro) is True

    def test_seek_employment_eligible(self):
        profile = _make_profile(
            monthly_income=0,
            age=32,
            occupation="文員",
        )
        macro = _make_macro()
        assert is_eligible_employment_change(profile, macro) is True

    def test_retired_not_eligible(self):
        profile = _make_profile(
            occupation="退休",
            age=67,
            monthly_income=0,
        )
        macro = _make_macro()
        assert is_eligible_employment_change(profile, macro) is False

    def test_student_not_eligible(self):
        profile = _make_profile(
            occupation="學生",
            age=20,
            monthly_income=0,
        )
        macro = _make_macro()
        assert is_eligible_employment_change(profile, macro) is False

    def test_wrong_age_not_eligible(self):
        profile = _make_profile(
            age=70,
            occupation="文員",
            monthly_income=10_000,
        )
        macro = _make_macro()
        assert is_eligible_employment_change(profile, macro) is False

    def test_normal_worker_no_trigger(self):
        """Normal worker with no triggers → not eligible."""
        profile = _make_profile(
            neuroticism=0.3,  # low neuroticism
            political_stance=0.4,  # moderate stance
            openness=0.6,  # high openness (not lie-flat)
            conscientiousness=0.6,  # high conscientiousness
            monthly_income=25_000,
            savings=50_000,
            occupation="輔助專業人員",
            age=40,
        )
        macro = _make_macro(
            unemployment_rate=0.07,  # high unemployment → won't quit
            consumer_confidence=60.0,  # decent confidence → won't strike
        )
        assert is_eligible_employment_change(profile, macro) is False


# ---------------------------------------------------------------------------
# Relocate Eligibility Tests
# ---------------------------------------------------------------------------


class TestRelocateEligibility:
    def test_rent_pressure_eligible(self):
        # 沙田 avg_sqft_price ~12,800 → 12,800 > 18,000 × 15? No, 12,800 < 270,000
        # Use 中西區 (18,500) and low income
        profile = _make_profile(
            district="中西區",
            monthly_income=1_000,  # very low income
            housing_type="私人住宅",
        )
        macro = _make_macro()
        # 18,500 > 1,000 × 15 = 15,000 → True
        assert is_eligible_relocate(profile, macro) is True

    def test_school_need_eligible(self):
        profile = _make_profile(
            marital_status="已婚",
            age=38,
            housing_type="資助出售房屋",
            monthly_income=25_000,
            district="觀塘",
        )
        macro = _make_macro()
        assert is_eligible_relocate(profile, macro) is True

    def test_gentrification_eligible(self):
        profile = _make_profile(
            monthly_income=20_000,  # below 25K threshold
            district="中西區",  # high price district
            housing_type="私人住宅",
        )
        macro = _make_macro()
        # 中西區 price = 18,500 > 15,000 → gentrification eligible
        assert is_eligible_relocate(profile, macro) is True

    def test_public_housing_not_eligible(self):
        profile = _make_profile(
            housing_type="公屋",
            marital_status="已婚",
            age=38,
        )
        macro = _make_macro()
        assert is_eligible_relocate(profile, macro) is False

    def test_wealthy_low_price_district_not_eligible(self):
        profile = _make_profile(
            district="屯門",  # low price ~9,200/sqft
            monthly_income=50_000,  # high income
            marital_status="未婚",  # not married
            age=25,  # young (not school need age)
            housing_type="私人住宅",
        )
        macro = _make_macro()
        # 9,200 > 50,000 × 15 = 750,000? No → rent pressure fails
        # Not married → school need fails
        # 50,000 > 25,000 → gentrification fails
        assert is_eligible_relocate(profile, macro) is False


# ---------------------------------------------------------------------------
# Decision model extension tests
# ---------------------------------------------------------------------------


class TestDecisionModelExtensions:
    def test_employment_change_in_enum(self):
        assert DecisionType.EMPLOYMENT_CHANGE == "employment_change"

    def test_relocate_in_enum(self):
        assert DecisionType.RELOCATE == "relocate"

    def test_employment_actions_valid(self):
        actions = DECISION_ACTIONS[DecisionType.EMPLOYMENT_CHANGE]
        assert "quit" in actions
        assert "strike" in actions
        assert "lie_flat" in actions
        assert "seek_employment" in actions
        assert "maintain" in actions

    def test_relocate_actions_valid(self):
        actions = DECISION_ACTIONS[DecisionType.RELOCATE]
        assert "relocate_nt" in actions
        assert "relocate_kln" in actions
        assert "relocate_hk_island" in actions
        assert "relocate_gba" in actions
        assert "stay" in actions

    def test_employment_change_frozen(self):
        """DecisionType values are immutable strings."""
        assert isinstance(DecisionType.EMPLOYMENT_CHANGE, str)

    def test_decision_actions_frozenset(self):
        """DECISION_ACTIONS values are frozensets (immutable)."""
        for dt, actions in DECISION_ACTIONS.items():
            assert isinstance(actions, frozenset)


# ---------------------------------------------------------------------------
# Collective Action dataclass tests
# ---------------------------------------------------------------------------


class TestCollectiveActionDataclasses:
    def test_agent_group_frozen(self):
        grp = AgentGroup(
            id=1,
            session_id="s",
            group_name="市民聯盟",
            agenda="民主改革倡議",
            leader_agent_id=42,
            member_count=8,
            shared_resources=20_000,
            formed_round=3,
            status="active",
        )
        assert grp.status == "active"
        with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
            grp.status = "dissolved"  # type: ignore[misc]

    def test_collective_action_frozen(self):
        action = CollectiveAction(
            id=1,
            session_id="s",
            group_id=None,
            initiator_agent_id=10,
            action_type="protest",
            target="政府土地政策",
            participant_count=15,
            momentum=0.45,
            round_initiated=5,
            status="active",
        )
        assert action.momentum == 0.45
        with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
            action.momentum = 0.9  # type: ignore[misc]

    def test_group_id_can_be_none(self):
        action = CollectiveAction(
            id=None,
            session_id="s",
            group_id=None,
            initiator_agent_id=1,
            action_type="petition",
            target="HDB",
            participant_count=1,
            momentum=0.1,
            round_initiated=1,
            status="building",
        )
        assert action.id is None
        assert action.group_id is None
