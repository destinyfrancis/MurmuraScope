"""Tests for ProfileGenerator and AgentFactory — persona generation, demographics, usernames."""

from __future__ import annotations

import csv
import io
import json

import pytest

from backend.app.services.agent_factory import (
    AGE_BRACKET_RANGES,
    AgentFactory,
    AgentProfile,
    DISTRICT_WEIGHTS,
    HOUSING_WEIGHTS,
)
from backend.app.services.profile_generator import (
    ProfileGenerator,
    _describe_personality,
    _get_personal_concerns,
    _political_stance_desc,
    _property_concern,
    _trait_level,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def factory():
    return AgentFactory(seed=42)


@pytest.fixture()
def generator(factory):
    return ProfileGenerator(agent_factory=factory)


@pytest.fixture()
def sample_profile():
    return AgentProfile(
        id=1,
        agent_type="npc",
        age=35,
        sex="M",
        district="沙田",
        occupation="輔助專業人員",
        income_bracket="$25,000-$39,999",
        education_level="學位或以上",
        marital_status="已婚",
        housing_type="私人住宅",
        openness=0.7,
        conscientiousness=0.5,
        extraversion=0.3,
        agreeableness=0.8,
        neuroticism=0.2,
        monthly_income=28_000,
        savings=350_000,
        political_stance=0.5,
    )


# ---------------------------------------------------------------------------
# _trait_level
# ---------------------------------------------------------------------------


class TestTraitLevel:
    def test_high(self):
        assert _trait_level(0.65) == "high"
        assert _trait_level(0.99) == "high"

    def test_mid(self):
        assert _trait_level(0.35) == "mid"
        assert _trait_level(0.64) == "mid"

    def test_low(self):
        assert _trait_level(0.0) == "low"
        assert _trait_level(0.34) == "low"


# ---------------------------------------------------------------------------
# _describe_personality
# ---------------------------------------------------------------------------


class TestDescribePersonality:
    def test_returns_chinese_description(self, sample_profile):
        desc = _describe_personality(sample_profile)
        assert isinstance(desc, str)
        assert len(desc) > 10
        # Should contain Chinese semicolons joining parts
        assert "；" in desc

    def test_all_five_traits_represented(self, sample_profile):
        desc = _describe_personality(sample_profile)
        parts = desc.split("；")
        assert len(parts) == 5


# ---------------------------------------------------------------------------
# _political_stance_desc
# ---------------------------------------------------------------------------


class TestPoliticalStanceDesc:
    def test_pro_establishment(self):
        profile = AgentProfile(
            id=1, agent_type="npc", age=50, sex="M", district="沙田",
            occupation="文員", income_bracket="$15,000-$24,999",
            education_level="中學", marital_status="已婚",
            housing_type="公屋", openness=0.5, conscientiousness=0.5,
            extraversion=0.5, agreeableness=0.5, neuroticism=0.5,
            monthly_income=16_000, savings=100_000, political_stance=0.1,
        )
        desc = _political_stance_desc(profile)
        assert "建制" in desc

    def test_pro_democracy(self):
        profile = AgentProfile(
            id=2, agent_type="npc", age=25, sex="F", district="灣仔",
            occupation="專業人員", income_bracket="$40,000-$59,999",
            education_level="學位或以上", marital_status="未婚",
            housing_type="私人住宅", openness=0.8, conscientiousness=0.6,
            extraversion=0.7, agreeableness=0.5, neuroticism=0.4,
            monthly_income=45_000, savings=200_000, political_stance=0.9,
        )
        desc = _political_stance_desc(profile)
        assert "民主" in desc

    def test_neutral(self):
        profile = AgentProfile(
            id=3, agent_type="npc", age=40, sex="M", district="觀塘",
            occupation="文員", income_bracket="$15,000-$24,999",
            education_level="中學", marital_status="已婚",
            housing_type="公屋", openness=0.5, conscientiousness=0.5,
            extraversion=0.5, agreeableness=0.5, neuroticism=0.5,
            monthly_income=16_000, savings=80_000, political_stance=0.5,
        )
        desc = _political_stance_desc(profile)
        assert "中立" in desc


# ---------------------------------------------------------------------------
# AgentFactory.generate_population
# ---------------------------------------------------------------------------


class TestGeneratePopulation:
    def test_generates_correct_count(self, factory):
        profiles = factory.generate_population(50)
        assert len(profiles) == 50

    def test_all_profiles_frozen(self, factory):
        profiles = factory.generate_population(10)
        for p in profiles:
            with pytest.raises(AttributeError):
                p.age = 99  # type: ignore[misc]

    def test_raises_on_zero_count(self, factory):
        with pytest.raises(ValueError, match="positive"):
            factory.generate_population(0)

    def test_districts_from_hk_set(self, factory):
        profiles = factory.generate_population(100)
        valid_districts = set(DISTRICT_WEIGHTS.keys())
        for p in profiles:
            assert p.district in valid_districts

    def test_big_five_in_range(self, factory):
        profiles = factory.generate_population(100)
        for p in profiles:
            for trait in (p.openness, p.conscientiousness, p.extraversion, p.agreeableness, p.neuroticism):
                assert 0.0 <= trait <= 1.0

    def test_age_constraints(self, factory):
        profiles = factory.generate_population(200)
        for p in profiles:
            assert 15 <= p.age <= 85
            # Minors must be students
            if p.age < 18:
                assert p.occupation == "學生"
            # 65+ must be retired
            if p.age >= 65:
                assert p.occupation == "退休"

    def test_unique_ids(self, factory):
        profiles = factory.generate_population(50)
        ids = [p.id for p in profiles]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# AgentFactory.generate_username
# ---------------------------------------------------------------------------


class TestGenerateUsername:
    def test_deterministic(self, factory, sample_profile):
        u1 = factory.generate_username(sample_profile)
        u2 = factory.generate_username(sample_profile)
        assert u1 == u2

    def test_different_for_different_profiles(self, factory):
        p1 = AgentProfile(
            id=1, agent_type="npc", age=30, sex="M", district="沙田",
            occupation="文員", income_bracket="$15,000-$24,999",
            education_level="中學", marital_status="未婚",
            housing_type="公屋", openness=0.5, conscientiousness=0.5,
            extraversion=0.5, agreeableness=0.5, neuroticism=0.5,
            monthly_income=16_000, savings=50_000,
        )
        p2 = AgentProfile(
            id=2, agent_type="npc", age=30, sex="M", district="觀塘",
            occupation="文員", income_bracket="$15,000-$24,999",
            education_level="中學", marital_status="未婚",
            housing_type="公屋", openness=0.5, conscientiousness=0.5,
            extraversion=0.5, agreeableness=0.5, neuroticism=0.5,
            monthly_income=16_000, savings=50_000,
        )
        assert factory.generate_username(p1) != factory.generate_username(p2)

    def test_contains_underscore_and_suffix(self, factory, sample_profile):
        username = factory.generate_username(sample_profile)
        assert "_" in username
        # Suffix is a 4-char hex
        suffix = username.split("_")[-1]
        assert len(suffix) == 4


# ---------------------------------------------------------------------------
# ProfileGenerator.to_persona_string
# ---------------------------------------------------------------------------


class TestToPersonaString:
    def test_contains_traditional_chinese(self, generator, sample_profile):
        persona = generator.to_persona_string(sample_profile)
        assert "香港" in persona
        assert "沙田" in persona

    def test_contains_demographics(self, generator, sample_profile):
        persona = generator.to_persona_string(sample_profile)
        assert "35歲" in persona
        assert "男" in persona
        assert "輔助專業人員" in persona

    def test_contains_income(self, generator, sample_profile):
        persona = generator.to_persona_string(sample_profile)
        assert "HK$28,000" in persona

    def test_contains_personality(self, generator, sample_profile):
        persona = generator.to_persona_string(sample_profile)
        assert "性格" in persona


# ---------------------------------------------------------------------------
# ProfileGenerator.to_user_info
# ---------------------------------------------------------------------------


class TestToUserInfo:
    def test_has_required_keys(self, generator, sample_profile):
        info = generator.to_user_info(sample_profile)
        assert info["id"] == 1
        assert "username" in info
        assert "persona" in info
        assert "demographics" in info
        assert "personality" in info
        assert "financial" in info

    def test_demographics_match_profile(self, generator, sample_profile):
        info = generator.to_user_info(sample_profile)
        demo = info["demographics"]
        assert demo["age"] == 35
        assert demo["sex"] == "M"
        assert demo["district"] == "沙田"


# ---------------------------------------------------------------------------
# ProfileGenerator.to_oasis_csv
# ---------------------------------------------------------------------------


class TestToOasisCsv:
    def test_csv_has_header_and_rows(self, generator, sample_profile):
        csv_str = generator.to_oasis_csv([sample_profile])
        reader = csv.reader(io.StringIO(csv_str))
        rows = list(reader)
        assert rows[0] == ["username", "description", "user_char"]
        assert len(rows) == 2  # header + 1 data row

    def test_csv_user_char_contains_language_rule(self, generator, sample_profile):
        csv_str = generator.to_oasis_csv([sample_profile])
        # user_char column should contain language rule
        assert "語言要求" in csv_str or "LANGUAGE RULE" in csv_str


# ---------------------------------------------------------------------------
# ProfileGenerator.to_oasis_json
# ---------------------------------------------------------------------------


class TestToOasisJson:
    def test_valid_json(self, generator, sample_profile):
        json_str = generator.to_oasis_json([sample_profile])
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)
        assert len(parsed) == 1


# ---------------------------------------------------------------------------
# _get_personal_concerns
# ---------------------------------------------------------------------------


class TestGetPersonalConcerns:
    def test_public_housing_low_income(self):
        profile = AgentProfile(
            id=1, agent_type="npc", age=55, sex="F", district="黃大仙",
            occupation="非技術工人", income_bracket="<$8,000",
            education_level="小學或以下", marital_status="已婚",
            housing_type="公屋", openness=0.4, conscientiousness=0.5,
            extraversion=0.3, agreeableness=0.6, neuroticism=0.7,
            monthly_income=7_500, savings=30_000,
        )
        concerns = _get_personal_concerns(profile)
        assert "公屋" in concerns or "街市" in concerns or "生活費" in concerns

    def test_private_housing_high_income(self):
        profile = AgentProfile(
            id=2, agent_type="npc", age=42, sex="M", district="中西區",
            occupation="經理及行政人員", income_bracket="$60,000+",
            education_level="學位或以上", marital_status="已婚",
            housing_type="私人住宅", openness=0.6, conscientiousness=0.7,
            extraversion=0.5, agreeableness=0.5, neuroticism=0.3,
            monthly_income=65_000, savings=1_200_000,
        )
        concerns = _get_personal_concerns(profile)
        assert isinstance(concerns, str)
        assert len(concerns) > 20

    def test_temporary_housing(self):
        profile = AgentProfile(
            id=3, agent_type="npc", age=30, sex="M", district="深水埗",
            occupation="非技術工人", income_bracket="<$8,000",
            education_level="中學", marital_status="未婚",
            housing_type="臨時／其他", openness=0.4, conscientiousness=0.4,
            extraversion=0.5, agreeableness=0.5, neuroticism=0.6,
            monthly_income=7_000, savings=5_000,
        )
        concerns = _get_personal_concerns(profile)
        assert "劏房" in concerns or "上樓" in concerns


# ---------------------------------------------------------------------------
# _property_concern
# ---------------------------------------------------------------------------


class TestPropertyConcern:
    def test_all_housing_types_covered(self):
        for housing in HOUSING_WEIGHTS:
            profile = AgentProfile(
                id=99, agent_type="npc", age=40, sex="M", district="沙田",
                occupation="文員", income_bracket="$15,000-$24,999",
                education_level="中學", marital_status="已婚",
                housing_type=housing, openness=0.5, conscientiousness=0.5,
                extraversion=0.5, agreeableness=0.5, neuroticism=0.5,
                monthly_income=16_000, savings=80_000,
            )
            concern = _property_concern(profile)
            assert isinstance(concern, str)
            assert len(concern) > 10
