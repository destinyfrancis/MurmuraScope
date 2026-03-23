# backend/app/services/cross_domain_validator.py
"""Cross-domain validation harness for universal prediction credibility.

Phase 4 addition.  Tests the prediction engine against 3 pre-configured
domains with measurable historical outcomes:

  1. hk_macro   — HK economic indicators (ccl_index, hsi_level, etc.)
  2. us_markets — US macro (fed_rate, GDP growth, unemployment)
  3. geopolitical — Taiwan Strait risk proxy, US-China tension index

Each domain runs a RetrospectiveValidator pass and returns a validation
report dict.  Aggregate grades across domains indicate whether the engine
has genuine cross-domain predictive capacity.

Usage::

    validator = CrossDomainValidator()
    report = await validator.validate_all("2021-Q1", "2023-Q4")
    for domain, result in report["domains"].items():
        print(domain, result["overall_grade"])
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.services.validation_reporter import ValidationReporter
from backend.app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Domain configurations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainConfig:
    """Configuration for one cross-domain validation run."""

    domain_id: str
    display_name: str
    metrics: list[str]
    min_metrics_required: int  # minimum metrics that must have data


_DOMAIN_CONFIGS: list[DomainConfig] = [
    DomainConfig(
        domain_id="hk_macro",
        display_name="HK Macro Economy",
        metrics=[
            "ccl_index",
            "unemployment_rate",
            "hsi_level",
            "gdp_growth",
            "consumer_confidence",
            "net_migration",
        ],
        min_metrics_required=3,
    ),
    DomainConfig(
        domain_id="us_markets",
        display_name="US Financial Markets",
        metrics=[
            # These map to hk_data_snapshots external category
            # fed_rate is stored as external/fed_rate in the DB
            "hibor_1m",  # proxy for interest rate environment
            "hsi_level",  # US-linked market sentiment
            "retail_sales_index",
            "tourist_arrivals",
            "cpi_yoy",
        ],
        min_metrics_required=2,
    ),
    DomainConfig(
        domain_id="geopolitical",
        display_name="Geopolitical Risk",
        metrics=[
            # These indicators are influenced by geopolitical events
            "consumer_confidence",  # sentiment proxy
            "hsi_level",  # market reaction to geo-risk
            "net_migration",  # emigration as risk response
            "hibor_1m",  # rate premium under tension
        ],
        min_metrics_required=2,
    ),
]


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class CrossDomainValidator:
    """Run validation across multiple pre-configured domains."""

    def __init__(self) -> None:
        self._reporter = ValidationReporter()

    async def validate_all(
        self,
        period_start: str,
        period_end: str,
    ) -> dict[str, Any]:
        """Run validation across all 3 domains for the given period.

        Args:
            period_start: Start quarter (e.g. '2021-Q1').
            period_end: End quarter (e.g. '2023-Q4').

        Returns:
            Dict with:
              - period_start, period_end
              - domains: dict[domain_id → ValidationReporter report dict]
              - aggregate_grade: str (A-F) — worst grade across domains
              - aggregate_score: float — mean score across domains
              - domains_passed: int — domains with grade A, B, or C
              - credibility_summary: str
        """
        domain_reports: dict[str, dict[str, Any]] = {}

        for config in _DOMAIN_CONFIGS:
            logger.info(
                "CrossDomainValidator: running domain=%s period=%s→%s",
                config.domain_id,
                period_start,
                period_end,
            )
            try:
                report = await self._reporter.generate(
                    period_start=period_start,
                    period_end=period_end,
                    metrics=config.metrics,
                )
            except Exception as exc:
                logger.warning("CrossDomainValidator: domain=%s failed: %s", config.domain_id, exc)
                report = {
                    "period_start": period_start,
                    "period_end": period_end,
                    "metrics_validated": 0,
                    "overall_grade": "N/A",
                    "overall_score": 0.0,
                    "summary": f"Validation failed: {exc}",
                    "results": [],
                }

            # Enforce domain-level minimum metrics
            if report["metrics_validated"] < config.min_metrics_required:
                report["overall_grade"] = "N/A"
                report["overall_score"] = 0.0
                report["summary"] = (
                    f"Insufficient data for {config.display_name}: "
                    f"{report['metrics_validated']}/{config.min_metrics_required} metrics available."
                )

            domain_reports[config.domain_id] = {
                "display_name": config.display_name,
                **report,
            }

        return _aggregate(domain_reports, period_start, period_end)

    async def validate_domain(
        self,
        domain_id: str,
        period_start: str,
        period_end: str,
    ) -> dict[str, Any]:
        """Run validation for a single domain by ID.

        Args:
            domain_id: One of 'hk_macro', 'us_markets', 'geopolitical'.
            period_start: Start quarter.
            period_end: End quarter.

        Returns:
            Report dict from ValidationReporter.

        Raises:
            ValueError: If domain_id is not recognised.
        """
        config = next((d for d in _DOMAIN_CONFIGS if d.domain_id == domain_id), None)
        if config is None:
            raise ValueError(f"Unknown domain '{domain_id}'. Available: {[d.domain_id for d in _DOMAIN_CONFIGS]}")
        return await self._reporter.generate(
            period_start=period_start,
            period_end=period_end,
            metrics=config.metrics,
        )

    @staticmethod
    def list_domains() -> list[dict[str, Any]]:
        """Return a list of available domain configs."""
        return [
            {
                "domain_id": d.domain_id,
                "display_name": d.display_name,
                "metrics": d.metrics,
                "min_metrics_required": d.min_metrics_required,
            }
            for d in _DOMAIN_CONFIGS
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GRADE_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1, "N/A": 0}


def _aggregate(
    domain_reports: dict[str, dict[str, Any]],
    period_start: str,
    period_end: str,
) -> dict[str, Any]:
    """Compute aggregate stats across domain reports."""
    scores = [r["overall_score"] for r in domain_reports.values() if r["overall_grade"] != "N/A"]
    grades = [r["overall_grade"] for r in domain_reports.values() if r["overall_grade"] != "N/A"]

    if not scores:
        aggregate_score = 0.0
        aggregate_grade = "N/A"
        domains_passed = 0
    else:
        aggregate_score = round(sum(scores) / len(scores), 4)
        # Aggregate grade = worst grade (most conservative)
        aggregate_grade = min(grades, key=lambda g: _GRADE_ORDER.get(g, 0))
        domains_passed = sum(1 for g in grades if _GRADE_ORDER.get(g, 0) >= 3)

    summary = _build_summary(domain_reports, aggregate_grade, aggregate_score, domains_passed, period_start, period_end)

    logger.info(
        "CrossDomainValidator: aggregate grade=%s score=%.2f domains_passed=%d/%d",
        aggregate_grade,
        aggregate_score,
        domains_passed,
        len(_DOMAIN_CONFIGS),
    )

    return {
        "period_start": period_start,
        "period_end": period_end,
        "domains": domain_reports,
        "aggregate_grade": aggregate_grade,
        "aggregate_score": aggregate_score,
        "domains_passed": domains_passed,
        "total_domains": len(_DOMAIN_CONFIGS),
        "credibility_summary": summary,
    }


def _build_summary(
    domain_reports: dict[str, dict[str, Any]],
    aggregate_grade: str,
    aggregate_score: float,
    domains_passed: int,
    period_start: str,
    period_end: str,
) -> str:
    parts = [
        f"Cross-domain validation ({period_start}–{period_end}): "
        f"aggregate grade {aggregate_grade} (score={aggregate_score:.2f}).",
        f"{domains_passed}/{len(_DOMAIN_CONFIGS)} domains passed (grade C or above).",
    ]

    if domains_passed == len(_DOMAIN_CONFIGS):
        parts.append(
            "Engine demonstrates genuine cross-domain predictive capacity — suitable for universal scenario analysis."
        )
    elif domains_passed >= 2:
        parts.append(
            "Moderate cross-domain capacity — predictions credible for most scenarios, "
            "with some domain-specific calibration needed."
        )
    elif domains_passed == 1:
        parts.append(
            "Limited cross-domain capacity — predictions reliable for one domain only. "
            "Expand training data or recalibrate before multi-domain deployment."
        )
    else:
        parts.append(
            "Insufficient cross-domain evidence — do not make public predictions "
            "until more historical data is available for validation."
        )

    failed = [
        domain_reports[d]["display_name"]
        for d in domain_reports
        if _GRADE_ORDER.get(domain_reports[d]["overall_grade"], 0) < 3
    ]
    if failed:
        parts.append(f"Domains needing improvement: {', '.join(failed)}.")

    return " ".join(parts)
