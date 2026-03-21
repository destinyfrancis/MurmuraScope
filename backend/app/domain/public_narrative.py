"""Public Narrative DomainPack for MurmuraScope."""
from __future__ import annotations

from backend.app.domain.base import (
    DomainPack,
    DomainPackRegistry,
    DecisionThresholds,
    MacroImpactDeltas,
    MetricSpec,
    ShockTypeSpec,
)

# ---------------------------------------------------------------------------
# Shock type specs
# ---------------------------------------------------------------------------

_PN_SHOCK_SPECS: tuple[ShockTypeSpec, ...] = (
    ShockTypeSpec("misinformation_spread", "謠言爆發", "Misinformation Spread"),
    ShockTypeSpec("viral_moment", "病毒式傳播事件", "Viral Moment"),
    ShockTypeSpec("policy_announcement", "政策公告", "Policy Announcement"),
    ShockTypeSpec("celebrity_scandal", "名人醜聞", "Celebrity Scandal"),
    ShockTypeSpec("official_denial", "官方否認", "Official Denial"),
    ShockTypeSpec("whistleblower_leak", "揭密泄露", "Whistleblower Leak"),
)

_PN_VALID_SHOCK_TYPES: frozenset[str] = frozenset(
    spec.id for spec in _PN_SHOCK_SPECS
)

# ---------------------------------------------------------------------------
# Metric specs
# ---------------------------------------------------------------------------

_PN_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("narrative_dominance", "sentiment", "narrative_dominance", 4),
    MetricSpec("public_trust", "sentiment", "public_trust", 4),
    MetricSpec("polarization_index", "sentiment", "polarization_index", 4),
)

_PN_DEFAULT_FORECAST_METRICS: tuple[str, ...] = tuple(
    m.name for m in _PN_METRICS
)

# ---------------------------------------------------------------------------
# Monte Carlo constants
# ---------------------------------------------------------------------------

_PN_CORRELATED_VARS: tuple[str, ...] = (
    "narrative_dominance",
    "public_trust",
    "polarization_index",
)

_PN_MC_DEFAULT_METRICS: tuple[str, ...] = (
    "narrative_dominance",
    "public_trust",
    "polarization_index",
)

# ---------------------------------------------------------------------------
# Macro baselines — public narrative defaults
# ---------------------------------------------------------------------------

_NARRATIVE_MACRO_BASELINES: dict[str, float] = {
    "consumer_confidence": 50.0,
    "gdp_growth": 0.020,
    "cpi_yoy": 0.030,
    "supply_chain_disruption": 0.25,
}

# ---------------------------------------------------------------------------
# Pack construction + registration
# ---------------------------------------------------------------------------

PUBLIC_NARRATIVE_PACK = DomainPack(
    id="public_narrative",
    name_zh="公共輿論",
    name_en="Public Narrative",
    locale="zh-HK",
    macro_baselines=_NARRATIVE_MACRO_BASELINES,
    valid_shock_types=_PN_VALID_SHOCK_TYPES,
    shock_specs=_PN_SHOCK_SPECS,
    metrics=_PN_METRICS,
    default_forecast_metrics=_PN_DEFAULT_FORECAST_METRICS,
    correlated_vars=_PN_CORRELATED_VARS,
    mc_default_metrics=_PN_MC_DEFAULT_METRICS,
    keywords=(
        "輿論", "narrative", "media", "民意", "protest",
        "public opinion", "social media", "misinformation",
    ),
)

DomainPackRegistry.register(PUBLIC_NARRATIVE_PACK)
