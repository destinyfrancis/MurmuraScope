"""Calibration parameter configuration for MurmuraScope macro feedback loop.

All magic numbers from ``macro_controller.update_from_actions()`` are
centralised here as a frozen dataclass.  Pass a ``CalibrationParams``
instance into ``update_from_actions()`` to override defaults without
mutating shared state.

Usage::

    from backend.app.services.calibration_config import DEFAULT_CALIBRATION, CalibrationParams
    import dataclasses

    # Use defaults
    params = DEFAULT_CALIBRATION

    # Override a single value (immutable pattern)
    tighter = dataclasses.replace(params, neg_threshold=0.70)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationParams:
    """Immutable set of calibration parameters for the macro feedback loop.

    Sentiment thresholds determine when the negative / positive signal is
    strong enough to trigger macro adjustments.  Delta values control the
    magnitude of each adjustment per feedback cycle (every 5 rounds).
    Clamp ranges prevent runaway drift of the macro indicators.

    Attributes:
        neg_threshold: Fraction of negative posts required to trigger
            pessimism adjustments.  Default 0.60 (60%).
        pos_threshold: Fraction of positive posts required to trigger
            optimism adjustments.  Default 0.60 (60%).
        property_topic_threshold: Minimum property-topic frequency (fraction
            of total posts) to treat property sentiment as significant.
            Default 0.0 (any mention triggers).
        employment_topic_threshold: Minimum employment-topic frequency.
            Default 0.0 (any mention triggers).
        emigration_threshold: Minimum emigration-topic frequency that triggers
            net-migration adjustment.  Default 0.20 (20%).
        stock_topic_threshold: Minimum stock-topic frequency.
            Default 0.0 (any mention triggers).
        secondary_sentiment_threshold: Sentiment level used for topic-specific
            adjustments (property / employment / stock sub-rules).
            Default 0.50 (50%).

        confidence_delta_neg: Decrease in consumer_confidence when neg_ratio
            exceeds neg_threshold.  Default 0.3.
        confidence_delta_pos: Increase in consumer_confidence when pos_ratio
            exceeds pos_threshold.  Default 0.2.
        gdp_delta_neg: Decrease in gdp_growth when neg_ratio exceeds
            neg_threshold.  Default 0.001.
        property_neg_ccl_factor: Multiplicative factor applied to ccl_index
            when property topic is heavily negative.  Default 0.999 (−0.1%).
        employment_neg_unemployment_delta: Additive increase to
            unemployment_rate when employment topic is negative.
            Default 0.001.
        emigration_net_migration_delta: Absolute decrease applied to
            net_migration when emigration topic is highly discussed.
            Default 100 (people).
        hsi_pos_factor: Multiplicative factor applied to hsi_level when
            sentiment is positive.  Default 1.001 (+0.1%).
        stock_pos_hsi_factor: Additional multiplicative factor on hsi_level
            when stock topic is discussed positively.  Default 1.002 (+0.2%).

        clamp_confidence_min: Floor for consumer_confidence.  Default 20.0.
        clamp_confidence_max: Ceiling for consumer_confidence.  Default 120.0.
        clamp_gdp_min: Floor for gdp_growth.  Default -0.15 (−15%).
        clamp_gdp_max: Ceiling for gdp_growth.  Default 0.20 (+20%).
        clamp_hsi_min: Floor for hsi_level (HSI points).  Default 5_000.
        clamp_hsi_max: Ceiling for hsi_level.  Default 60_000.
        clamp_ccl_min: Floor for ccl_index.  Default 50.0.
        clamp_ccl_max: Ceiling for ccl_index.  Default 300.0.
        clamp_unemployment_min: Floor for unemployment_rate.  Default 0.01.
        clamp_unemployment_max: Ceiling for unemployment_rate.  Default 0.25.
        clamp_net_migration_min: Floor for net_migration.  Default -200_000.
        clamp_net_migration_max: Ceiling for net_migration.  Default 100_000.
    """

    # ---- Sentiment thresholds ----
    neg_threshold: float = 0.60
    pos_threshold: float = 0.60
    property_topic_threshold: float = 0.0
    employment_topic_threshold: float = 0.0
    emigration_threshold: float = 0.20
    stock_topic_threshold: float = 0.0
    secondary_sentiment_threshold: float = 0.50

    # ---- Adjustment deltas ----
    confidence_delta_neg: float = 0.3
    confidence_delta_pos: float = 0.2
    gdp_delta_neg: float = 0.001
    property_neg_ccl_factor: float = 0.999
    employment_neg_unemployment_delta: float = 0.001
    emigration_net_migration_delta: int = 100
    hsi_pos_factor: float = 1.001
    stock_pos_hsi_factor: float = 1.002

    # ---- Clamp ranges ----
    clamp_confidence_min: float = 20.0
    clamp_confidence_max: float = 120.0
    clamp_gdp_min: float = -0.15
    clamp_gdp_max: float = 0.20
    clamp_hsi_min: float = 5_000.0
    clamp_hsi_max: float = 60_000.0
    clamp_ccl_min: float = 50.0
    clamp_ccl_max: float = 300.0
    clamp_unemployment_min: float = 0.01
    clamp_unemployment_max: float = 0.25
    clamp_net_migration_min: int = -200_000
    clamp_net_migration_max: int = 100_000

    def to_dict(self) -> dict[str, float | int]:
        """Return all parameters as a plain dict for serialisation."""
        import dataclasses  # noqa: PLC0415

        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}


# Module-level singleton — import and use directly; never mutate.
DEFAULT_CALIBRATION: CalibrationParams = CalibrationParams()
