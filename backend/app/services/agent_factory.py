"""Census-calibrated agent profile generator using HK 2021 Census data."""

from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.app.domain.base import DemographicsSpec

logger = logging.getLogger(__name__)

# =========================================================================
# HK 2021 Census — Probability Distributions
# =========================================================================

# 18 Districts with approximate population weights (2021 Census)
DISTRICT_WEIGHTS: dict[str, float] = {
    "中西區": 0.034,
    "灣仔": 0.023,
    "東區": 0.074,
    "南區": 0.035,
    "油尖旺": 0.047,
    "深水埗": 0.055,
    "九龍城": 0.057,
    "黃大仙": 0.054,
    "觀塘": 0.093,
    "葵青": 0.069,
    "荃灣": 0.044,
    "屯門": 0.067,
    "元朗": 0.085,
    "北區": 0.041,
    "大埔": 0.043,
    "沙田": 0.091,
    "西貢": 0.065,
    "離島": 0.024,
}

# Age brackets with weights (working-age + retiree, 15+)
AGE_BRACKET_WEIGHTS: dict[str, float] = {
    "15-19": 0.055,
    "20-24": 0.065,
    "25-29": 0.078,
    "30-34": 0.085,
    "35-39": 0.090,
    "40-44": 0.095,
    "45-49": 0.092,
    "50-54": 0.098,
    "55-59": 0.102,
    "60-64": 0.092,
    "65+": 0.148,
}

AGE_BRACKET_RANGES: dict[str, tuple[int, int]] = {
    "15-19": (15, 19),
    "20-24": (20, 24),
    "25-29": (25, 29),
    "30-34": (30, 34),
    "35-39": (35, 39),
    "40-44": (40, 44),
    "45-49": (45, 49),
    "50-54": (50, 54),
    "55-59": (55, 59),
    "60-64": (60, 64),
    "65+": (65, 85),
}

# Sex distribution
SEX_WEIGHTS: dict[str, float] = {
    "M": 0.467,
    "F": 0.533,
}

# Education levels
EDUCATION_WEIGHTS: dict[str, float] = {
    "小學或以下": 0.142,
    "中學": 0.338,
    "專上非學位": 0.138,
    "學位或以上": 0.382,
}

# Housing types
HOUSING_WEIGHTS: dict[str, float] = {
    "公屋": 0.301,
    "資助出售房屋": 0.152,
    "私人住宅": 0.507,
    "臨時／其他": 0.040,
}

# Occupation categories (among employed, 2021 Census)
OCCUPATION_WEIGHTS: dict[str, float] = {
    "經理及行政人員": 0.115,
    "專業人員": 0.092,
    "輔助專業人員": 0.188,
    "文員": 0.142,
    "服務及銷售人員": 0.168,
    "工藝及有關人員": 0.042,
    "機台及機器操作員": 0.038,
    "非技術工人": 0.108,
    "學生": 0.060,
    "退休": 0.047,
}

# Marital status
MARITAL_WEIGHTS: dict[str, float] = {
    "未婚": 0.335,
    "已婚": 0.542,
    "離婚／分居": 0.078,
    "喪偶": 0.045,
}

# ---------------------------------------------------------------------------
# HK 2021 Census — Income by Occupation (primary determinant)
#
# Source: C&SD 2021 Population Census, Table E102
# median / std: monthly HKD for employed workers in each occupation
# unemployed_pct: proportion of this occupational group currently jobless
# ---------------------------------------------------------------------------
INCOME_BY_OCCUPATION: dict[str, dict[str, Any]] = {
    "經理及行政人員": {"median": 50_000, "std": 22_000, "unemployed_pct": 0.02},
    "專業人員": {"median": 42_000, "std": 18_000, "unemployed_pct": 0.02},
    "輔助專業人員": {"median": 24_000, "std": 8_000, "unemployed_pct": 0.03},
    "文員": {"median": 16_000, "std": 4_000, "unemployed_pct": 0.04},
    "服務及銷售人員": {"median": 14_500, "std": 4_000, "unemployed_pct": 0.05},
    "工藝及有關人員": {"median": 16_500, "std": 5_000, "unemployed_pct": 0.04},
    "機台及機器操作員": {"median": 15_500, "std": 4_000, "unemployed_pct": 0.04},
    "非技術工人": {"median": 12_500, "std": 3_000, "unemployed_pct": 0.07},
    # Non-employed categories — income set by _clamp_income_for_occupation()
    "學生": {"median": 0, "std": 0, "unemployed_pct": 1.0},
    "退休": {"median": 0, "std": 0, "unemployed_pct": 1.0},
}

# ---------------------------------------------------------------------------
# HK 2021 Census — District income modifiers
#
# Source: C&SD 2021 Census, median monthly income by District Council district.
# Values are relative multipliers vs HK median ($20,800).
# Affluent districts (Sai Kung, Central) score higher; working-class
# districts (SSP, WTS, Kwun Tong) score lower.
# ---------------------------------------------------------------------------
DISTRICT_INCOME_MODIFIER: dict[str, float] = {
    "中西區": 1.30,  # commercial/finance hub, many professionals
    "灣仔": 1.25,
    "西貢": 1.20,  # affluent NT East corridor
    "沙田": 1.08,
    "大埔": 1.02,
    "東區": 1.00,
    "南區": 1.05,
    "九龍城": 1.02,
    "荃灣": 0.98,
    "葵青": 0.92,
    "屯門": 0.90,
    "元朗": 0.90,
    "油尖旺": 0.95,
    "北區": 0.88,
    "黃大仙": 0.88,
    "觀塘": 0.87,
    "深水埗": 0.85,  # historically lowest-income urban district
    "離島": 0.93,
}

# ---------------------------------------------------------------------------
# Age experience multiplier — same occupation, different career stage
# Junior (age 22-29) earns less than senior (40-49) in same role.
# ---------------------------------------------------------------------------
_AGE_EXPERIENCE_MULTIPLIER: dict[tuple[int, int], float] = {
    (22, 29): 0.70,
    (30, 34): 0.85,
    (35, 39): 0.95,
    (40, 49): 1.00,  # peak earning years
    (50, 54): 0.98,
    (55, 59): 0.92,
    (60, 64): 0.82,
}

# Education-based income multipliers (within same occupation)
EDUCATION_INCOME_MULTIPLIER: dict[str, float] = {
    "小學或以下": 0.80,
    "中學": 0.90,
    "專上非學位": 1.05,
    "學位或以上": 1.20,
}

# Kept for backward-compatibility (test imports)
INCOME_BY_AGE: dict[str, dict[str, Any]] = {
    "15-19": {"median": 8_000, "std": 2_000, "employed_pct": 0.15},
    "20-24": {"median": 14_500, "std": 4_000, "employed_pct": 0.72},
    "25-29": {"median": 18_000, "std": 5_000, "employed_pct": 0.88},
    "30-34": {"median": 22_000, "std": 7_000, "employed_pct": 0.85},
    "35-39": {"median": 25_000, "std": 9_000, "employed_pct": 0.82},
    "40-44": {"median": 27_000, "std": 10_000, "employed_pct": 0.80},
    "45-49": {"median": 25_000, "std": 10_000, "employed_pct": 0.78},
    "50-54": {"median": 22_000, "std": 9_000, "employed_pct": 0.73},
    "55-59": {"median": 20_000, "std": 8_000, "employed_pct": 0.62},
    "60-64": {"median": 16_000, "std": 6_000, "employed_pct": 0.42},
    "65+": {"median": 10_000, "std": 4_000, "employed_pct": 0.13},
}

# Influence operator configuration (Phase 18)
_OPERATOR_CHANCE: float = 0.03  # 3% of agents are covert influence operators
_OPERATOR_TOPICS: tuple[str, ...] = (
    "政府政策",
    "房地產市場",
    "移民問題",
    "經濟前景",
    "社會穩定",
    "選舉制度",
    "示威抗議",
    "大灣區",
)
_OPERATOR_SENTIMENTS: tuple[str, ...] = ("negative", "positive")

# Cantonese surname pool (common HK surnames)
_SURNAMES: tuple[str, ...] = (
    "陳",
    "李",
    "張",
    "黃",
    "王",
    "林",
    "劉",
    "吳",
    "楊",
    "蔡",
    "鄭",
    "何",
    "梁",
    "曾",
    "許",
    "謝",
    "周",
    "郭",
    "馬",
    "羅",
    "趙",
    "盧",
    "蕭",
    "葉",
    "朱",
    "鄧",
    "徐",
    "方",
    "潘",
    "余",
)

# Cantonese-flavored username parts
_USERNAME_PARTS: tuple[str, ...] = (
    "大佬",
    "靚仔",
    "靚女",
    "港人",
    "打工仔",
    "巴打",
    "師兄",
    "師姐",
    "街坊",
    "業主",
    "租客",
    "炒家",
    "HKer",
    "lihkg",
    "hkgal",
    "kowloon",
    "ntboy",
    "tst",
    "cwb",
    "mk",
    "ssp",
    "yk",
)

# Minimum monthly income floor per occupation (HKD).
# Used by housing-income coherence check: employed adults should not have zero income.
_OCCUPATION_INCOME_FLOOR: dict[str, int] = {
    "非技術工人": 8_000,
    "機台及機器操作員": 9_500,
    "工藝及有關人員": 11_000,
    "服務及銷售人員": 9_000,
    "文員": 13_000,
    "輔助專業人員": 18_000,
    "專業人員": 28_000,
    "經理及行政人員": 28_000,
}


def _parse_age_bracket_ranges(brackets: dict[str, float]) -> dict[str, tuple[int, int]]:
    """Parse age bracket labels like '20-24' or '65+' into (lo, hi) tuples.

    Falls back to AGE_BRACKET_RANGES for any unrecognised labels.
    """
    import re as _re  # noqa: PLC0415

    result: dict[str, tuple[int, int]] = {}
    for label in brackets:
        if label in AGE_BRACKET_RANGES:
            result[label] = AGE_BRACKET_RANGES[label]
            continue
        m = _re.match(r"(\d+)\s*[-–]\s*(\d+)", label)
        if m:
            result[label] = (int(m.group(1)), int(m.group(2)))
            continue
        m = _re.match(r"(\d+)\s*\+", label)
        if m:
            result[label] = (int(m.group(1)), 85)
            continue
        # Fallback: treat as 20-65 range
        result[label] = (20, 65)
    return result


# =========================================================================
# AgentProfile (frozen dataclass)
# =========================================================================


@dataclass(frozen=True)
class AgentProfile:
    """Immutable agent profile for OASIS simulation."""

    id: int
    agent_type: str  # "npc", "twin", "crm_derived", "influence_operator"
    age: int
    sex: str
    district: str
    occupation: str
    income_bracket: str
    education_level: str
    marital_status: str
    housing_type: str
    openness: float
    conscientiousness: float
    extraversion: float
    agreeableness: float
    neuroticism: float
    monthly_income: int
    savings: int
    political_stance: float = 0.5  # Phase 6: 0=建制派, 0.5=中間派, 1=民主派
    target_topic: str = ""  # Phase 18: influence_operator target topic
    target_sentiment: str = ""  # Phase 18: influence_operator target sentiment


# =========================================================================
# Cognitive fingerprint inference (HK demographics → personality-derived)
# =========================================================================


def _infer_fingerprint_from_demographics(
    political_stance: float,
    age: int,
    income: float,
) -> dict[str, float]:
    """Infer cognitive fingerprint values from HK demographic attributes.

    Provides a lightweight approximation of the full cognitive fingerprint
    used in kg_driven mode, derived purely from HK census demographics.

    Args:
        political_stance: 0.0=建制派 to 1.0=民主派.
        age: Agent's age in years.
        income: Monthly income in HKD.

    Returns:
        Dict with authority, loyalty, openness, conformity, security,
        and prestige scores (each 0.0–1.0).
    """
    return {
        "authority": round(0.3 + 0.4 * (1.0 - political_stance), 2),
        "loyalty": round(0.4 + 0.3 * (1.0 - political_stance), 2),
        "openness": round(min(1.0, 0.3 + 0.02 * min(age, 40)), 2),
        "conformity": round(max(0.1, 0.6 - 0.01 * min(age, 40)), 2),
        "security": round(min(1.0, 0.3 + income / 100000), 2) if income else 0.5,
        "prestige": round(min(1.0, income / 80000), 2) if income else 0.3,
    }


# =========================================================================
# Behavioral params inference (HK demographics)
# =========================================================================

# Occupations whose holders are classified as key decision-makers in HK mode
_STAKEHOLDER_OCCUPATIONS: frozenset[str] = frozenset(
    {
        "政府官員",
        "議員",
        "地產商",
        "銀行家",
        "記者",
        "教授",
        "律師",
        "醫生",
        # Census categories that map to these roles
        "經理及行政人員",
        "專業人員",
    }
)


def _infer_behavioral_params(
    age: int,
    income: float,
    occupation: str,
    rng: random.Random | None = None,
) -> dict[str, float | int]:
    """Infer activity_level, influence_weight, is_stakeholder from HK demographics.

    Args:
        age: Agent's age in years.
        income: Monthly income in HKD.
        occupation: Occupation string (HK Census categories).
        rng: Optional seeded RNG for reproducibility.  Falls back to
            ``random`` module if not provided.

    Returns:
        Dict with keys ``activity_level`` (float 0.0-1.0),
        ``influence_weight`` (float 0.0-3.0), and ``is_stakeholder`` (int 0/1).
    """
    _rng = rng if isinstance(rng, random.Random) else random

    # Activity level driven by age bracket
    if age <= 35:
        activity = 0.7 + _rng.random() * 0.2
    elif age <= 55:
        activity = 0.4 + _rng.random() * 0.2
    else:
        activity = 0.2 + _rng.random() * 0.2

    # Influence weight starts at 1.0, boosted by income
    influence = 1.0
    if income and income > 50_000:
        influence *= 1.3
    if income and income > 100_000:
        influence *= 1.2  # further boost for very high earners

    # Stakeholder classification
    is_stakeholder = occupation in _STAKEHOLDER_OCCUPATIONS
    if is_stakeholder:
        activity = max(activity, 0.8)
        influence = max(influence, 1.5)

    return {
        "activity_level": round(min(1.0, activity), 2),
        "influence_weight": round(min(3.0, influence), 2),
        "is_stakeholder": int(is_stakeholder),
    }


# =========================================================================
# AgentFactory
# =========================================================================


class AgentFactory:
    """Generate census-calibrated agent profiles for the HK simulation."""

    def __init__(
        self,
        seed: int | None = None,
        demographics: DemographicsSpec | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        self._next_id = 1
        self._demographics = demographics

        # Use demographics if provided, else module-level HK constants (backward compat).
        if demographics is not None:
            self._regions: dict[str, float] = demographics.regions
            self._occupations: list[str] = list(demographics.occupations.keys())
            self._occupation_weights: list[float] = list(demographics.occupations.values())
            self._education_levels: dict[str, float] = demographics.education_levels
            self._housing_types: dict[str, float] = demographics.housing_types
            self._age_brackets: dict[str, float] = demographics.age_brackets
            self._sex_weights: dict[str, float] = demographics.sex_weights
            self._marital_statuses: dict[str, float] = demographics.marital_statuses
            self._surnames: tuple[str, ...] = demographics.surnames
            self._username_parts: tuple[str, ...] = demographics.username_parts
            self._income_by_occupation: dict[str, dict[str, Any]] = demographics.income_by_occupation
            self._region_income_modifier: dict[str, float] = demographics.region_income_modifier
            # Build age bracket ranges from bracket labels
            self._age_bracket_ranges: dict[str, tuple[int, int]] = getattr(
                demographics, "age_bracket_ranges", {}
            ) or _parse_age_bracket_ranges(demographics.age_brackets)
        else:
            self._regions = DISTRICT_WEIGHTS
            self._occupations = list(OCCUPATION_WEIGHTS.keys())
            self._occupation_weights = list(OCCUPATION_WEIGHTS.values())
            self._education_levels = EDUCATION_WEIGHTS
            self._housing_types = HOUSING_WEIGHTS
            self._age_brackets = AGE_BRACKET_WEIGHTS
            self._sex_weights = SEX_WEIGHTS
            self._marital_statuses = MARITAL_WEIGHTS
            self._surnames = _SURNAMES
            self._username_parts = _USERNAME_PARTS
            self._income_by_occupation = INCOME_BY_OCCUPATION
            self._region_income_modifier = DISTRICT_INCOME_MODIFIER
            self._age_bracket_ranges = AGE_BRACKET_RANGES

    # -- public API --------------------------------------------------------

    def generate_population(
        self,
        count: int,
        distribution_overrides: dict[str, dict[str, float]] | None = None,
    ) -> list[AgentProfile]:
        """Generate *count* census-calibrated NPC agent profiles.

        *distribution_overrides* can replace any of the standard weight dicts:
        ``{"district": {"沙田": 0.5, ...}, "education": {...}, ...}``
        """
        if count <= 0:
            raise ValueError("count must be a positive integer")

        overrides = distribution_overrides or {}
        districts = overrides.get("district", self._regions)
        ages = overrides.get("age", self._age_brackets)
        sexes = overrides.get("sex", self._sex_weights)
        educations = overrides.get("education", self._education_levels)
        housings = overrides.get("housing", self._housing_types)
        occupations = overrides.get("occupation", dict(zip(self._occupations, self._occupation_weights)))
        maritals = overrides.get("marital", self._marital_statuses)

        profiles: list[AgentProfile] = []
        for _ in range(count):
            profile = self._generate_single_npc(
                districts,
                ages,
                sexes,
                educations,
                housings,
                occupations,
                maritals,
            )
            profiles.append(profile)

        logger.info("Generated %d NPC agent profiles", count)
        return profiles

    def generate_twin(self, family_member: dict[str, Any]) -> AgentProfile:
        """Generate a digital twin agent from a user's family member data.

        Expected keys in *family_member*:
        ``name``, ``age``, ``sex``, ``district``, ``occupation``,
        ``education``, ``income``, ``housing``, ``marital_status``
        """
        age = int(family_member.get("age", 35))
        sex = family_member.get("sex", "M")
        district = family_member.get("district", "沙田")
        education = family_member.get("education", "中學")
        income = int(family_member.get("income", 20_000))
        bracket = self._income_to_bracket(income)

        profile_id = self._next_id
        self._next_id += 1

        ocean = self._generate_ocean()

        return AgentProfile(
            id=profile_id,
            agent_type="twin",
            age=age,
            sex=sex,
            district=district,
            occupation=family_member.get("occupation", "文員"),
            income_bracket=bracket,
            education_level=education,
            marital_status=family_member.get("marital_status", "已婚"),
            housing_type=family_member.get("housing", "私人住宅"),
            openness=ocean[0],
            conscientiousness=ocean[1],
            extraversion=ocean[2],
            agreeableness=ocean[3],
            neuroticism=ocean[4],
            monthly_income=income,
            savings=self._estimate_savings(age, income),
        )

    def generate_crm_agents(self, crm_data: list[dict[str, Any]]) -> list[AgentProfile]:
        """Generate agents from CRM customer records.

        Each dict in *crm_data* should contain customer demographic fields.
        Missing fields are filled from census distributions.
        """
        profiles: list[AgentProfile] = []
        for record in crm_data:
            age = int(record.get("age", self._sample_age()))
            sex = record.get("sex", self._weighted_choice(self._sex_weights))
            district = record.get("district", self._weighted_choice(self._regions))
            education = record.get("education", self._weighted_choice(self._education_levels))
            occupation_weights = dict(zip(self._occupations, self._occupation_weights))
            occupation = record.get("occupation", self._weighted_choice(occupation_weights))
            income = int(record.get("income", self._estimate_income(age, education, occupation, district)))
            bracket = self._income_to_bracket(income)
            ocean = self._generate_ocean()

            profile_id = self._next_id
            self._next_id += 1

            profiles.append(
                AgentProfile(
                    id=profile_id,
                    agent_type="crm_derived",
                    age=age,
                    sex=sex,
                    district=district,
                    occupation=record.get("occupation", self._weighted_choice(occupation_weights)),
                    income_bracket=bracket,
                    education_level=education,
                    marital_status=record.get("marital_status", self._weighted_choice(self._marital_statuses)),
                    housing_type=record.get("housing", self._weighted_choice(self._housing_types)),
                    openness=ocean[0],
                    conscientiousness=ocean[1],
                    extraversion=ocean[2],
                    agreeableness=ocean[3],
                    neuroticism=ocean[4],
                    monthly_income=income,
                    savings=self._estimate_savings(age, income),
                )
            )

        logger.info("Generated %d CRM-derived agent profiles", len(profiles))
        return profiles

    def generate_username(self, profile: AgentProfile) -> str:
        """Generate a deterministic Cantonese-flavored username for the agent.

        Username is fully determined by profile.id and profile.district so that
        multiple calls for the same profile always return the same username.
        This is critical for matching agents between agents.csv and agent_profiles.
        """
        seed_val = int(hashlib.md5(f"{profile.id}-{profile.district}".encode()).hexdigest(), 16)
        det_rng = __import__("random").Random(seed_val)
        surname = det_rng.choice(self._surnames)
        part = det_rng.choice(self._username_parts)
        suffix = hashlib.md5(f"{profile.id}-{profile.district}".encode()).hexdigest()[:4]
        return f"{surname}{part}_{suffix}"

    # -- internal helpers --------------------------------------------------

    def _generate_single_npc(
        self,
        districts: dict[str, float],
        ages: dict[str, float],
        sexes: dict[str, float],
        educations: dict[str, float],
        housings: dict[str, float],
        occupations: dict[str, float],
        maritals: dict[str, float],
    ) -> AgentProfile:
        age_bracket = self._weighted_choice(ages)
        lo, hi = self._age_bracket_ranges.get(age_bracket, AGE_BRACKET_RANGES.get(age_bracket, (20, 65)))
        age = self._rng.randint(lo, hi)

        sex = self._weighted_choice(sexes)
        district = self._weighted_choice(districts)
        education = self._weighted_choice(educations)
        housing = self._weighted_choice(housings)
        occupation = self._pick_occupation_for_age(age, occupations)
        marital = self._pick_marital_for_age(age, maritals)

        education = self._clamp_education_for_age(age, education)
        # Income driven by occupation × district × age × education (HK Census)
        income = self._estimate_income(age, education, occupation, district)
        # Post-correction: retired agents must not have a working income.
        # Students under 22 with no plausible income source are also zeroed.
        income = self._clamp_income_for_occupation(occupation, age, income)
        savings = self._estimate_savings(age, income)
        # Housing-income coherence: fix employed adults with zero income and
        # downgrade private housing when no viable means of payment.
        housing, income, savings = self._apply_housing_income_coherence(housing, occupation, age, income, savings)
        bracket = self._income_to_bracket(income)
        ocean = self._generate_ocean()

        profile_id = self._next_id
        self._next_id += 1

        # Phase 18: 3% chance of being an influence operator (covert agent)
        is_operator = self._rng.random() < _OPERATOR_CHANCE
        agent_type = "influence_operator" if is_operator else "npc"
        target_topic = self._rng.choice(_OPERATOR_TOPICS) if is_operator else ""
        target_sentiment = self._rng.choice(_OPERATOR_SENTIMENTS) if is_operator else ""

        return AgentProfile(
            id=profile_id,
            agent_type=agent_type,
            age=age,
            sex=sex,
            district=district,
            occupation=occupation,
            income_bracket=bracket,
            education_level=education,
            marital_status=marital,
            housing_type=housing,
            openness=ocean[0],
            conscientiousness=ocean[1],
            extraversion=ocean[2],
            agreeableness=ocean[3],
            neuroticism=ocean[4],
            monthly_income=income,
            savings=savings,
            target_topic=target_topic,
            target_sentiment=target_sentiment,
        )

    def _weighted_choice(self, weights: dict[str, float]) -> str:
        keys = list(weights.keys())
        vals = list(weights.values())
        return self._rng.choices(keys, weights=vals, k=1)[0]

    def _sample_age(self) -> int:
        bracket = self._weighted_choice(self._age_brackets)
        lo, hi = self._age_bracket_ranges.get(bracket, AGE_BRACKET_RANGES.get(bracket, (20, 65)))
        return self._rng.randint(lo, hi)

    def _generate_ocean(self) -> tuple[float, float, float, float, float]:
        """Generate Big Five personality traits using truncated normal distribution.

        Values are 0.0–1.0.  Mean ~0.5, SD ~0.15 gives realistic spread.
        """

        def _trait() -> float:
            val = self._rng.gauss(0.50, 0.15)
            return round(max(0.0, min(1.0, val)), 2)

        return (_trait(), _trait(), _trait(), _trait(), _trait())

    def _estimate_income(
        self,
        age: int,
        education: str,
        occupation: str,
        district: str,
    ) -> int:
        """Estimate monthly income from occupation × district × age × education.

        Hierarchy (as per HK Census methodology):
        1. Occupation — primary driver of income level
        2. District   — local labour market premium/discount
        3. Age        — experience multiplier within occupation
        4. Education  — human capital premium within occupation

        Non-employed categories (退休, 學生) return 0 here;
        _clamp_income_for_occupation() may assign a small pension/part-time.
        """
        occ_data = self._income_by_occupation.get(occupation)
        if occ_data is None or occ_data["unemployed_pct"] >= 1.0:
            return 0  # 退休 / 學生 — handled by _clamp_income_for_occupation

        # HK Census 2021: ~16% of working-age (22-64) population is
        # economically inactive (homemakers, long-term ill, discouraged workers).
        # This is separate from the unemployment rate within each occupation.
        _NON_WORKING_OCCUPATIONS = frozenset({"退休", "學生"})
        if occupation not in _NON_WORKING_OCCUPATIONS and 22 <= age <= 64:
            if self._rng.random() < 0.22:
                return 0  # Economically inactive (homemaker / carer / other)

        # Probabilistic unemployment within occupation
        if self._rng.random() < occ_data["unemployed_pct"]:
            return 0

        base = self._rng.gauss(occ_data["median"], occ_data["std"])
        base = max(occ_data["median"] * 0.3, base)  # floor at 30% of median

        # Age / experience multiplier
        exp_mult = 1.0
        for (lo, hi), mult in _AGE_EXPERIENCE_MULTIPLIER.items():
            if lo <= age <= hi:
                exp_mult = mult
                break

        # District labour market multiplier
        dist_mult = self._region_income_modifier.get(district, 1.0)

        # Education within-occupation premium
        edu_mult = EDUCATION_INCOME_MULTIPLIER.get(education, 1.0)

        income = int(base * exp_mult * dist_mult * edu_mult)
        # Round to nearest 500
        income = (income // 500) * 500

        # Fix HIGH #5: Enforce occupation income floor even when income > 0.
        # Professionals/managers should never earn below their minimum.
        floor = _OCCUPATION_INCOME_FLOOR.get(occupation, 0)
        if income > 0 and floor > 0:
            income = max(income, floor)

        return income

    def _clamp_income_for_occupation(self, occupation: str, age: int, income: int) -> int:
        """Ensure income is consistent with occupation.

        Rules:
        - 退休: income is 0 (no CSSA/OAA) or a small pension (< HK$6,000).
          Use a 70 % chance of zero, 30 % chance of small pension.
        - 學生 AND age < 23: income is 0 or part-time (<= HK$6,000).
          Use a 60 % chance of zero, 40 % chance of small part-time income.
        - 經理及行政人員 or 專業人員: income should not be 0 (contradictory).
          If somehow 0 was generated, return a sensible floor.
        """
        if occupation == "退休":
            if self._rng.random() < 0.70:
                return 0
            # Small pension / CSSA
            return self._rng.randint(2_000, 5_500)

        if occupation == "學生" and age < 23:
            if self._rng.random() < 0.60:
                return 0
            # Part-time income
            return (self._rng.randint(2_000, 6_000) // 500) * 500

        if occupation in ("經理及行政人員", "專業人員") and income == 0:
            # These roles almost always have income; use a sensible floor
            return 20_000

        return income

    def _estimate_savings(self, age: int, monthly_income: int) -> int:
        """Estimate total savings based on age and income."""
        if monthly_income <= 0:
            return self._rng.randint(0, 50_000)

        # Savings rate increases with age, typical HK range 15-30%
        savings_rate = 0.15 + min(age - 20, 40) * 0.004 if age > 20 else 0.05
        years_working = max(0, age - 22)
        base_savings = int(monthly_income * savings_rate * 12 * years_working)
        # Add noise
        noise = self._rng.gauss(1.0, 0.3)
        return max(0, int(base_savings * noise))

    def _clamp_education_for_age(self, age: int, education: str) -> str:
        """Ensure education level is age-appropriate.

        Hard constraints (HK school system):
        - age < 18:  Must be 小學或以下 or 中學 (still in secondary school)
        - age 18-21: Exclude 學位或以上 (not enough time to complete degree)
        - age >= 22:  No restriction (any education level possible)
        """
        if age < 18:
            if education not in ("小學或以下", "中學"):
                return "中學"
        elif age < 22:
            if education == "學位或以上":
                return "專上非學位"
        return education

    def _apply_housing_income_coherence(
        self,
        housing: str,
        occupation: str,
        age: int,
        income: int,
        savings: int,
    ) -> tuple[str, int, int]:
        """Enforce economic coherence between housing type, income, and savings.

        Rules:
        1. Employed working-age adults (22-64, not 退休/學生) with zero income:
           - ~45% are preserved as zero-income (homemakers, long-term unemployed)
             to match Census 2021 ~28% zero-income working-age population.
           - ~55% receive an occupation-appropriate minimum floor income.
        2. 私人住宅 residents with zero income AND savings < HK$200,000 are
           reassigned to 臨時／其他 (cannot afford private housing).
        3. 公屋 residents with income > HK$30,000 are moved to 資助出售房屋 or
           私人住宅 (PRH富戶 income ceiling enforcement).
        4. 臨時／其他 residents with income > HK$40,000 are moved to 私人住宅
           (high earners would not remain in temp housing).
        """
        _NON_WORKING = frozenset({"退休", "學生"})

        # Rule 1: Apply income floor for employed working-age agents,
        # BUT preserve a fraction as zero-income (homemakers / long-term unemployed).
        if occupation not in _NON_WORKING and income == 0 and 22 <= age <= 64:
            # ~60% chance to remain zero-income (homemaker / long-term unemployed)
            if self._rng.random() < 0.60:
                pass  # keep income = 0 intentionally
            else:
                floor = _OCCUPATION_INCOME_FLOOR.get(occupation, 8_000)
                # Small random variation above the floor
                income = floor + (self._rng.randint(0, 5_000) // 500) * 500
                # Recalculate savings with the corrected income
                savings = self._estimate_savings(age, income)

        # Rule 2: Private housing requires income or substantial savings.
        if housing == "私人住宅" and income == 0 and savings < 200_000:
            housing = "臨時／其他"

        # Rule 3: PRH income ceiling — HK Census PRH富戶政策
        # Single person > HK$30,000 or family > HK$60,000 triggers review.
        # Simplification: use HK$30,000 threshold for all.
        if housing == "公屋" and income > 30_000:
            if income > 50_000:
                housing = "私人住宅"
            else:
                housing = "資助出售房屋"

        # Rule 4: High earners should not stay in temp housing.
        if housing == "臨時／其他" and income > 40_000:
            housing = "私人住宅"

        return housing, income, savings

    # Professional occupations that are inappropriate for very young or very old agents
    _PROFESSIONAL_OCCUPATIONS: frozenset[str] = frozenset(
        {
            "經理及行政人員",
            "專業人員",
            "輔助專業人員",
            "文員",
            "服務及銷售人員",
            "工藝及有關人員",
            "機台及機器操作員",
            "非技術工人",
        }
    )

    def _pick_occupation_for_age(self, age: int, occupations: dict[str, float]) -> str:
        """Pick an occupation consistent with the agent's age.

        Hard constraints (enforced before any weighted sampling):
        - age >= 65: MUST be 退休 (retirement age in HK is 65)
        - age < 18:  MUST be 學生 (compulsory education / senior secondary)
        - age < 22:  MUST be 學生 or low-skilled work; professional
                     categories (管理/專業) are excluded
        - age < 55:  Cannot be 退休

        Soft adjustments (probability boosting) for boundary ages.
        """
        # --- hard constraints ---
        if age >= 65:
            return "退休"

        # Fix HIGH #3: Minors MUST be students (HK compulsory education to 18)
        if age < 18:
            return "學生"

        if age < 22:
            # Exclude all professional/managerial categories + retirement
            allowed = {
                k: v
                for k, v in occupations.items()
                if k
                not in (
                    "經理及行政人員",
                    "專業人員",
                    "輔助專業人員",
                    "文員",
                    "退休",
                )
            }
            # Boost 學生 heavily for teenagers / young adults
            allowed["學生"] = allowed.get("學生", 0.06) * 8
            return self._weighted_choice(allowed)

        # --- soft adjustments for 60-64: nudge toward retirement ---
        adjusted = dict(occupations)
        if age >= 60:
            adjusted["退休"] = adjusted.get("退休", 0.05) * 4
            # Suppress 學生 entirely for working-age adults
            adjusted["學生"] = 0.0
        elif age >= 55:
            # Allow early retirement with moderate probability
            adjusted["退休"] = adjusted.get("退休", 0.05) * 1.5
            adjusted["學生"] = 0.0
        else:
            # Fix MEDIUM #8: Under 55 cannot be retired
            adjusted["學生"] = adjusted.get("學生", 0.06) * 0.1
            adjusted["退休"] = 0.0  # Hard block retirement under 55

        return self._weighted_choice(adjusted)

    def _pick_marital_for_age(self, age: int, maritals: dict[str, float]) -> str:
        """Adjust marital status probabilities based on age.

        Fix HIGH #4: Widowhood is extremely rare under 55 in HK.
        Census 2021 shows < 0.3% widowed under 50, ~1% at 50-59.
        """
        adjusted = dict(maritals)
        if age < 25:
            adjusted["未婚"] = adjusted.get("未婚", 0.33) * 3
            adjusted["已婚"] = adjusted.get("已婚", 0.54) * 0.2
            adjusted["喪偶"] = 0.0  # Effectively impossible
        elif age < 40:
            adjusted["喪偶"] = 0.0  # Extremely rare under 40
        elif age < 55:
            # Very small probability (< 0.5%)
            adjusted["喪偶"] = adjusted.get("喪偶", 0.045) * 0.05
        elif age < 65:
            # Slightly elevated but still uncommon (~2%)
            adjusted["喪偶"] = adjusted.get("喪偶", 0.045) * 0.5
        elif age >= 65:
            adjusted["喪偶"] = adjusted.get("喪偶", 0.045) * 3
        return self._weighted_choice(adjusted)

    @staticmethod
    def _age_to_bracket(age: int) -> str:
        for bracket, (lo, hi) in AGE_BRACKET_RANGES.items():
            if lo <= age <= hi:
                return bracket
        return "65+"

    @staticmethod
    def _income_to_bracket(income: int) -> str:
        if income <= 0:
            return "無收入"
        if income < 8_000:
            return "<$8,000"
        if income < 15_000:
            return "$8,000-$14,999"
        if income < 25_000:
            return "$15,000-$24,999"
        if income < 40_000:
            return "$25,000-$39,999"
        if income < 60_000:
            return "$40,000-$59,999"
        return "$60,000+"
