"""Company profile and decision models for B2B enterprise simulation (Phase 5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CompanyType(str, Enum):
    MANUFACTURER = "manufacturer"
    TRADER = "trader"
    LOGISTICS = "logistics"
    DISTRIBUTOR = "distributor"
    FINANCE = "finance"
    TECH = "tech"


class IndustrySector(str, Enum):
    MANUFACTURING = "manufacturing"
    IMPORT_EXPORT = "import_export"
    FINANCE = "finance"
    RETAIL = "retail"
    LOGISTICS = "logistics"
    TECH = "tech"
    REAL_ESTATE = "real_estate"


class CompanySize(str, Enum):
    SME = "sme"
    MNC = "mnc"
    STARTUP = "startup"


class SupplyChainPosition(str, Enum):
    UPSTREAM = "upstream"
    MIDSTREAM = "midstream"
    DOWNSTREAM = "downstream"


class CompanyDecisionType(str, Enum):
    EXPAND = "expand"
    CONTRACT = "contract"
    RELOCATE = "relocate"
    HIRE = "hire"
    LAYOFF = "layoff"
    ENTER_MARKET = "enter_market"
    EXIT_MARKET = "exit_market"
    STOCKPILE = "stockpile"


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompanyProfile:
    """Immutable company profile for a simulation session.

    Attributes:
        id: Auto-assigned database primary key (0 before insert).
        session_id: Owning simulation session UUID.
        company_name: Localised company name in Traditional Chinese.
        company_type: One of CompanyType values.
        industry_sector: One of IndustrySector values.
        company_size: sme / mnc / startup.
        district: One of the 18 HK administrative districts.
        supply_chain_position: upstream / midstream / downstream.
        annual_revenue_hkd: Annual revenue in HKD (integer).
        employee_count: Total headcount.
        china_exposure: 0–1 fraction of revenue/costs tied to mainland China.
        export_ratio: 0–1 fraction of revenue from exports (vs. domestic).
    """

    id: int
    session_id: str
    company_name: str
    company_type: str
    industry_sector: str
    company_size: str  # sme / mnc / startup
    district: str
    supply_chain_position: str  # upstream / midstream / downstream
    annual_revenue_hkd: int
    employee_count: int
    china_exposure: float  # 0–1
    export_ratio: float  # 0–1


@dataclass(frozen=True)
class CompanyDecision:
    """Immutable record of an enterprise decision taken in one simulation round.

    Attributes:
        session_id: Owning simulation session UUID.
        company_id: FK to company_profiles.id.
        round_number: Simulation round when the decision was made.
        decision_type: One of CompanyDecisionType values.
        action: Short action label (e.g. "expand_local", "hire_100").
        reasoning: Human-readable LLM / rule-based justification.
        confidence: Decision confidence score 0–1.
        impact_employees: Projected net headcount change (can be negative).
        impact_revenue_pct: Projected revenue change as a fraction (e.g. 0.05).
    """

    session_id: str
    company_id: int
    round_number: int
    decision_type: str
    action: str
    reasoning: str
    confidence: float
    impact_employees: int
    impact_revenue_pct: float


@dataclass(frozen=True)
class CompanyDecisionSummary:
    """Aggregate decision counts for a session.

    Attributes:
        session_id: Simulation session UUID.
        round_number: If set, summary is for that round only.
        counts_by_type: Nested dict {decision_type: {action: count}}.
        total_decisions: Total decisions across all types.
        net_employment_impact: Sum of impact_employees across all decisions.
    """

    session_id: str
    round_number: int | None
    counts_by_type: dict[str, dict[str, int]]
    total_decisions: int
    net_employment_impact: int
