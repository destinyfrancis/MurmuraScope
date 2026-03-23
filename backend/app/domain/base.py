"""Base types for the DomainPack abstraction layer.

A DomainPack bundles all domain-specific constants (shock types, metrics,
decision thresholds, baselines, etc.) into a single frozen dataclass so
the core engine can remain domain-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Spec types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShockTypeSpec:
    """Describes one shock type that can be injected into a simulation."""

    id: str
    label_zh: str
    label_en: str


@dataclass(frozen=True)
class MetricSpec:
    """Maps a forecast metric name to its DB location."""

    name: str  # e.g. "ccl_index"
    db_category: str  # e.g. "property"
    db_metric: str  # e.g. "ccl_index"
    seasonal_period: int = 4


# ---------------------------------------------------------------------------
# Threshold / delta containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionThresholds:
    """All decision-rule constants that vary by domain."""

    # Property purchase
    min_months_down_payment: int = 24
    stress_test_dti: float = 0.50
    max_borrower_age_plus_tenor: int = 75

    # Emigration
    emigration_savings_by_destination: tuple[tuple[str, int], ...] = ()
    emigration_savings_default: int = 350_000

    # Investment
    invest_min_savings: int = 100_000
    invest_min_openness: float = 0.40

    # Child-bearing
    child_min_age: int = 25
    child_max_age: int = 45
    child_min_income: int = 20_000

    # Job change
    job_min_age: int = 22
    job_max_age: int = 60
    job_min_extraversion: float = 0.50
    job_change_unemploy_threshold: float = 0.06

    # Spending
    spending_adjust_cpi_threshold: float = 0.025
    spending_adjust_confidence_low: float = 45.0

    # Employment change
    employment_quit_neuroticism: float = 0.6
    employment_quit_savings_alt: int = 300_000
    employment_quit_unemploy_cap: float = 0.05
    employment_strike_stance: float = 0.6
    employment_strike_confidence: float = 40.0
    employment_lie_flat_max_age: int = 35
    employment_lie_flat_min_age: int = 22
    employment_lie_flat_openness: float = 0.4
    employment_lie_flat_conscien: float = 0.4
    employment_sample_rate: float = 0.05
    employment_max_per_round: int = 30

    # Relocate
    relocate_price_income_ratio: int = 15
    relocate_school_min_age: int = 30
    relocate_school_max_age: int = 50
    relocate_gentrify_income_cap: int = 25_000
    relocate_gentrify_price_floor: int = 15_000
    relocate_sample_rate: float = 0.08
    relocate_max_per_round: int = 40


@dataclass(frozen=True)
class MacroImpactDeltas:
    """How aggregate decisions shift macro indicators each round."""

    buy_property_ccl_delta: float = 0.3
    emigrate_net_mig_delta: int = -50
    invest_stocks_hsi_delta: float = 0.0
    have_child_confidence_delta: float = 0.2
    adjust_spending_confidence_delta: float = -0.3


# ---------------------------------------------------------------------------
# Phase 6 spec types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DemographicsSpec:
    """Demographics configuration for agent generation."""

    regions: dict[str, float]
    occupations: dict[str, float]
    income_by_occupation: dict[str, dict[str, Any]]
    region_income_modifier: dict[str, float]
    education_levels: dict[str, float]
    housing_types: dict[str, float]
    age_brackets: dict[str, float]
    sex_weights: dict[str, float]
    marital_statuses: dict[str, float]
    surnames: tuple[str, ...]
    username_parts: tuple[str, ...]
    currency_symbol: str = "HK$"
    currency_code: str = "HKD"


@dataclass(frozen=True)
class DataSourceSpec:
    """Describes one data source for a domain pack."""

    id: str
    downloader: str
    function: str
    params: dict[str, Any] = field(default_factory=dict)
    category: str = ""
    schedule: str = "daily"


@dataclass(frozen=True)
class PromptLocale:
    """Locale-specific prompt templates and language rules."""

    language_code: str
    language_rule: str
    personality_descriptions: dict[str, dict[str, str]]
    housing_context: dict[str, str]
    concern_templates: dict[str, str]
    posting_guidelines: str


@dataclass(frozen=True)
class SentimentLexicon:
    """Locale-specific sentiment analysis keywords."""

    positive_keywords: frozenset[str]
    negative_keywords: frozenset[str]
    intensifiers: frozenset[str] = frozenset()
    particle_modifiers: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MacroFieldSpec:
    """Defines one macro-economic field for a domain."""

    name: str
    label: str
    default_value: float = 0.0
    unit: str = ""


# ---------------------------------------------------------------------------
# DomainPack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainPack:
    """Immutable bundle of all domain-specific constants."""

    id: str
    name_zh: str
    name_en: str
    locale: str

    # Shock types
    valid_shock_types: frozenset[str]
    shock_specs: tuple[ShockTypeSpec, ...]

    # Forecast metrics
    metrics: tuple[MetricSpec, ...]
    default_forecast_metrics: tuple[str, ...]

    # Monte Carlo
    correlated_vars: tuple[str, ...]
    mc_default_metrics: tuple[str, ...]

    # Baselines (frozen by convention — dict for JSON compat)
    macro_baselines: dict[str, Any] = field(default_factory=dict)
    baseline_district_prices: dict[str, int] = field(default_factory=dict)
    baseline_stamp_duty: dict[str, float] = field(default_factory=dict)

    # Decision config
    decision_thresholds: DecisionThresholds = field(default_factory=DecisionThresholds)
    macro_impact_deltas: MacroImpactDeltas = field(default_factory=MacroImpactDeltas)

    # Persona helpers
    housing_context_map: dict[str, str] = field(default_factory=dict)
    entity_type_map: dict[str, str] = field(default_factory=dict)

    # Phase 6 additions (all optional for backward compat)
    demographics: DemographicsSpec | None = None
    data_sources: tuple[DataSourceSpec, ...] = ()
    prompt_locale: PromptLocale | None = None
    sentiment_lexicon: SentimentLexicon | None = None
    macro_fields: tuple[MacroFieldSpec, ...] = ()
    decision_types: tuple[str, ...] = ()
    scenarios: tuple[dict[str, str], ...] = ()

    # Universal Prediction Engine additions
    keywords: tuple[str, ...] = ()  # zero-config domain inference keywords
    scenario_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    topic_metric_mapping: dict[str, str] = field(default_factory=dict)
    retirement_age: int = 65
    education_income_multiplier: dict[str, float] = field(default_factory=dict)
    consensus_weights: dict[str, float] = field(
        default_factory=lambda: {
            "belief": 0.40,
            "decision": 0.35,
            "sentiment": 0.25,
        }
    )
    topic_groups: tuple[tuple[str, ...], ...] = ()  # for scenario matching


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class DomainPackRegistry:
    """Global registry of available domain packs."""

    _packs: dict[str, DomainPack] = {}
    _custom_loaded: bool = False

    @classmethod
    def register(cls, pack: DomainPack) -> None:
        """Register a domain pack by its id."""
        cls._packs[pack.id] = pack

    @classmethod
    def get(cls, pack_id: str) -> DomainPack:
        """Retrieve a registered pack by id. Raises KeyError if not found."""
        if pack_id not in cls._packs:
            raise KeyError(f"Unknown domain pack '{pack_id}'. Available: {sorted(cls._packs)}")
        return cls._packs[pack_id]

    @classmethod
    def list_packs(cls) -> list[str]:
        """Return sorted list of registered pack IDs."""
        return sorted(cls._packs)

    @classmethod
    async def load_custom_from_db(cls) -> int:
        """Load custom domain packs from DB into the in-memory registry.

        Called once at startup. Returns the number of packs loaded.
        Safe to call multiple times (idempotent).
        """
        if cls._custom_loaded:
            return 0

        import json as _json  # noqa: PLC0415
        import logging as _logging  # noqa: PLC0415

        _logger = _logging.getLogger("domain_pack_registry")

        try:
            from backend.app.utils.db import get_db  # noqa: PLC0415

            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT id, name, description, regions, occupations, "
                    "income_brackets, shocks, metrics, persona_template, "
                    "sentiment_keywords, locale, source FROM custom_domain_packs"
                )
                rows = await cursor.fetchall()
        except Exception:
            _logger.debug("load_custom_from_db: DB not available yet, skipping")
            return 0

        loaded = 0
        for row in rows:
            pack_id = row[0]
            if pack_id in cls._packs:
                continue  # builtin takes precedence

            try:
                shocks_raw = _json.loads(row[6]) if row[6] else []
                metrics_raw = _json.loads(row[7]) if row[7] else []

                shock_specs = tuple(
                    ShockTypeSpec(
                        id=s.get("id", s.get("name", "")),
                        label_zh=s.get("label_zh", s.get("name", "")),
                        label_en=s.get("label_en", s.get("name", "")),
                    )
                    for s in shocks_raw
                    if isinstance(s, dict)
                )
                metric_specs = tuple(
                    MetricSpec(
                        name=m.get("name", m.get("id", "")),
                        label=m.get("label", m.get("name", "")),
                    )
                    for m in metrics_raw
                    if isinstance(m, dict)
                )

                pack = DomainPack(
                    id=pack_id,
                    name_zh=row[1] or pack_id,
                    name_en=row[1] or pack_id,
                    locale=row[10] or "en-US",
                    valid_shock_types=frozenset(s.id for s in shock_specs),
                    shock_specs=shock_specs,
                    metrics=metric_specs,
                    default_forecast_metrics=tuple(m.name for m in metric_specs),
                    correlated_vars=(),
                    mc_default_metrics=(),
                    macro_baselines={},
                    baseline_district_prices={},
                    baseline_stamp_duty={},
                )
                cls.register(pack)
                loaded += 1
            except Exception:
                _logger.warning("Failed to load custom domain pack '%s'", pack_id, exc_info=True)

        cls._custom_loaded = True
        if loaded:
            _logger.info("Loaded %d custom domain pack(s) from DB", loaded)
        return loaded
