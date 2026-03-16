"""Ensemble analyzer for HKSimEngine.

Reads final macro snapshots from all trial branch sessions, computes
percentile bands using numpy, and generates user-facing probability
statements in Traditional Chinese.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.app.models.ensemble import DistributionBand, EnsembleResult
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("ensemble_analyzer")

# ---------------------------------------------------------------------------
# Perturbable macro field names (subset of MacroState numeric fields)
# ---------------------------------------------------------------------------
PERTURBABLE_FIELDS: tuple[str, ...] = (
    "hibor_1m",
    "unemployment_rate",
    "ccl_index",
    "hsi_level",
    "consumer_confidence",
    "gdp_growth",
    "net_migration",
    "fed_rate",
    "china_gdp_growth",
    "taiwan_strait_risk",
)

# Human-readable Chinese labels for each metric
_METRIC_LABELS_ZH: dict[str, str] = {
    "hibor_1m": "一個月 HIBOR",
    "unemployment_rate": "失業率",
    "ccl_index": "中原城市領先指數（CCL）",
    "hsi_level": "恒生指數",
    "consumer_confidence": "消費者信心指數",
    "gdp_growth": "GDP 增長率",
    "net_migration": "淨遷移人數",
    "fed_rate": "美聯儲利率",
    "china_gdp_growth": "中國 GDP 增長率",
    "taiwan_strait_risk": "台海風險指數",
}

# Threshold direction: True = higher value triggers the condition (e.g., risk > threshold)
_THRESHOLD_DIRECTION_POSITIVE: frozenset[str] = frozenset({
    "hsi_level",
    "consumer_confidence",
    "gdp_growth",
    "china_gdp_growth",
})


# ---------------------------------------------------------------------------
# Frozen dataclass for a single metric's probability statement
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProbabilityStatement:
    """Probability statement for a single metric threshold crossing.

    Attributes:
        metric: Internal metric name.
        label_zh: Human-readable Chinese label.
        threshold: The numeric threshold used.
        direction: 'above' or 'below'.
        probability: Estimated probability (0.0 – 1.0).
        statement_zh: Full Traditional Chinese probability sentence.
    """

    metric: str
    label_zh: str
    threshold: float
    direction: str
    probability: float
    statement_zh: str


# ---------------------------------------------------------------------------
# EnsembleAnalyzer
# ---------------------------------------------------------------------------


class EnsembleAnalyzer:
    """Analyzes trial results to produce percentile bands and probability statements."""

    async def compute_percentiles(
        self,
        session_id: str,
        trial_session_ids: list[str],
    ) -> EnsembleResult:
        """Compute percentile distribution bands from trial sessions' final macro snapshots.

        For each perturbable field, reads the last macro_snapshot of every trial
        branch session and computes p10/p25/p50/p75/p90 percentiles.

        Args:
            session_id: The parent session UUID (used as the ensemble key).
            trial_session_ids: List of branch session UUIDs (the MC trial runs).

        Returns:
            EnsembleResult containing a DistributionBand per metric.
        """
        trial_macros = await self._load_trial_macros(trial_session_ids)
        logger.info(
            "compute_percentiles session=%s trials=%d loaded=%d",
            session_id,
            len(trial_session_ids),
            len(trial_macros),
        )

        if not trial_macros:
            logger.warning("No macro snapshots found for trials; returning empty result")
            return EnsembleResult(
                session_id=session_id,
                n_trials=len(trial_session_ids),
                distributions=[],
            )

        # Aggregate values per metric
        values_by_metric: dict[str, list[float]] = {
            field: [] for field in PERTURBABLE_FIELDS
        }
        for macro_dict in trial_macros:
            for field in PERTURBABLE_FIELDS:
                raw = macro_dict.get(field)
                if raw is not None:
                    try:
                        values_by_metric[field].append(float(raw))
                    except (TypeError, ValueError):
                        pass

        # Compute percentile bands
        bands: list[DistributionBand] = []
        for field, values in values_by_metric.items():
            if len(values) < 2:
                continue
            arr = np.array(values, dtype=float)
            p10, p25, p50, p75, p90 = np.percentile(arr, [10, 25, 50, 75, 90])
            bands.append(DistributionBand(
                metric_name=field,
                p10=float(p10),
                p25=float(p25),
                p50=float(p50),
                p75=float(p75),
                p90=float(p90),
            ))

        # Persist to ensemble_results table
        await self._persist_bands(session_id, len(trial_session_ids), bands)

        return EnsembleResult(
            session_id=session_id,
            n_trials=len(trial_session_ids),
            distributions=bands,
        )

    def generate_probability_statement(
        self,
        distributions: list[DistributionBand],
        metric: str,
        threshold: float,
    ) -> ProbabilityStatement:
        """Generate a Traditional Chinese probability statement for a metric threshold.

        Uses linear interpolation between percentile anchors to estimate
        the probability that the metric crosses the given threshold.

        Args:
            distributions: List of DistributionBands from compute_percentiles.
            metric: Metric name (must be in PERTURBABLE_FIELDS).
            threshold: Numeric threshold to evaluate.

        Returns:
            ProbabilityStatement with an estimated probability and Chinese sentence.

        Raises:
            ValueError: If the metric has no distribution data.
        """
        band = next((b for b in distributions if b.metric_name == metric), None)
        if band is None:
            raise ValueError(f"No distribution data found for metric '{metric}'")

        label_zh = _METRIC_LABELS_ZH.get(metric, metric)
        probability = _interpolate_probability(band, threshold)
        direction = "above" if metric in _THRESHOLD_DIRECTION_POSITIVE else "below"

        # Format the threshold for display
        formatted_threshold = _format_threshold(metric, threshold)

        if direction == "above":
            statement_zh = (
                f"根據模型集成分析，{label_zh} 超過 {formatted_threshold} 嘅概率約為 "
                f"{probability:.0%}。"
            )
        else:
            statement_zh = (
                f"根據模型集成分析，{label_zh} 跌破 {formatted_threshold} 嘅概率約為 "
                f"{probability:.0%}。"
            )

        return ProbabilityStatement(
            metric=metric,
            label_zh=label_zh,
            threshold=threshold,
            direction=direction,
            probability=probability,
            statement_zh=statement_zh,
        )

    def generate_all_statements(
        self,
        distributions: list[DistributionBand],
    ) -> list[dict[str, Any]]:
        """Generate probability statements for all metrics using median ± 10% thresholds.

        Uses p50 ± (p90-p10) * 0.1 as the threshold for each metric.
        Returns plain dicts for JSON serialization.

        Args:
            distributions: List of DistributionBands from compute_percentiles.

        Returns:
            List of serialised ProbabilityStatement dicts.
        """
        results: list[dict[str, Any]] = []
        for band in distributions:
            spread = band.p90 - band.p10
            # Threshold: 10% of IQR below/above the median
            threshold = band.p50 - spread * 0.1
            try:
                stmt = self.generate_probability_statement(
                    distributions, band.metric_name, threshold
                )
                results.append({
                    "metric": stmt.metric,
                    "label_zh": stmt.label_zh,
                    "threshold": stmt.threshold,
                    "direction": stmt.direction,
                    "probability": stmt.probability,
                    "statement_zh": stmt.statement_zh,
                })
            except ValueError:
                continue
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_trial_macros(
        self,
        trial_session_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Load the final macro_snapshot for each trial session.

        For sessions without a macro_snapshot, falls back to reading
        the session's config_json for any macro overrides.

        Args:
            trial_session_ids: Branch session UUIDs.

        Returns:
            List of macro dicts (one per trial that had data).
        """
        if not trial_session_ids:
            return []

        macros: list[dict[str, Any]] = []

        try:
            async with get_db() as db:
                # Ensure macro_snapshots table exists
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS macro_snapshots (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id  TEXT    NOT NULL,
                        round_number INTEGER NOT NULL,
                        macro_json  TEXT    NOT NULL,
                        created_at  TEXT    DEFAULT (datetime('now')),
                        UNIQUE(session_id, round_number)
                    )
                """)

                placeholders = ",".join("?" * len(trial_session_ids))

                # Get latest macro snapshot per trial using a join to MAX(round_number)
                cursor = await db.execute(
                    f"""
                    SELECT m.session_id, m.macro_json
                    FROM macro_snapshots m
                    INNER JOIN (
                        SELECT session_id, MAX(round_number) AS max_round
                        FROM macro_snapshots
                        WHERE session_id IN ({placeholders})
                        GROUP BY session_id
                    ) latest
                    ON m.session_id = latest.session_id
                    AND m.round_number = latest.max_round
                    """,
                    trial_session_ids,
                )
                rows = await cursor.fetchall()

                found_ids = set()
                for row in rows:
                    try:
                        sid = row["session_id"]
                        raw_json = row["macro_json"]
                    except (TypeError, KeyError, IndexError):
                        sid = row[0]
                        raw_json = row[1]
                    found_ids.add(sid)
                    try:
                        macros.append(json.loads(raw_json))
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Invalid macro_json for trial session=%s", sid)

                # Fallback: sessions with no macro snapshot → read config_json
                missing_ids = [s for s in trial_session_ids if s not in found_ids]
                if missing_ids:
                    placeholders2 = ",".join("?" * len(missing_ids))
                    cursor2 = await db.execute(
                        f"SELECT config_json FROM simulation_sessions WHERE id IN ({placeholders2})",
                        missing_ids,
                    )
                    cfg_rows = await cursor2.fetchall()
                    for cfg_row in cfg_rows:
                        raw = cfg_row[0] if isinstance(cfg_row, (list, tuple)) else cfg_row["config_json"]
                        if not raw:
                            continue
                        try:
                            cfg = json.loads(raw)
                            macro_overrides = cfg.get("macro_overrides", {})
                            if macro_overrides:
                                macros.append(macro_overrides)
                        except (json.JSONDecodeError, TypeError):
                            pass
        except Exception:
            logger.exception("_load_trial_macros failed")

        return macros

    async def _persist_bands(
        self,
        session_id: str,
        n_trials: int,
        bands: list[DistributionBand],
    ) -> None:
        """Persist DistributionBands to ensemble_results table.

        Clears existing rows for this session before inserting to prevent
        stale data accumulation across re-runs.

        Args:
            session_id: Parent session UUID.
            n_trials: Number of trials used.
            bands: Computed distribution bands.
        """
        if not bands:
            return
        try:
            async with get_db() as db:
                await db.execute(
                    "DELETE FROM ensemble_results WHERE session_id = ?",
                    (session_id,),
                )
                rows = [
                    (session_id, n_trials, b.metric_name, b.p10, b.p25, b.p50, b.p75, b.p90)
                    for b in bands
                ]
                await db.executemany(
                    """
                    INSERT INTO ensemble_results
                        (session_id, n_trials, metric_name, p10, p25, p50, p75, p90)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                await db.commit()
            logger.debug(
                "Persisted %d bands for ensemble session=%s n_trials=%d",
                len(bands), session_id, n_trials,
            )
        except Exception:
            logger.exception("_persist_bands failed session=%s", session_id)


# ---------------------------------------------------------------------------
# Private pure helpers
# ---------------------------------------------------------------------------


def _interpolate_probability(band: DistributionBand, threshold: float) -> float:
    """Estimate P(metric > threshold) using linear interpolation between percentile anchors.

    Percentile anchors: p10 → 0.10, p25 → 0.25, p50 → 0.50, p75 → 0.75, p90 → 0.90.
    Values below p10 map to 0.95+ and above p90 map to 0.05-.

    Args:
        band: DistributionBand with p10/p25/p50/p75/p90.
        threshold: Threshold value to evaluate.

    Returns:
        Probability in [0.0, 1.0].
    """
    # Percentile anchors as (value, cumulative_probability) pairs
    anchors: list[tuple[float, float]] = [
        (band.p10, 0.10),
        (band.p25, 0.25),
        (band.p50, 0.50),
        (band.p75, 0.75),
        (band.p90, 0.90),
    ]

    # Below p10: ~90–95% chance of being above
    if threshold <= band.p10:
        return min(0.95, 0.90 + (band.p10 - threshold) / max(band.p10, 1e-9) * 0.05)

    # Above p90: ~5–10% chance of being above
    if threshold >= band.p90:
        spread = max(band.p90 - band.p75, 1e-9)
        return max(0.02, 0.10 - (threshold - band.p90) / spread * 0.05)

    # Linear interpolation between adjacent anchors
    for i in range(len(anchors) - 1):
        lo_val, lo_prob = anchors[i]
        hi_val, hi_prob = anchors[i + 1]
        if lo_val <= threshold <= hi_val:
            span = hi_val - lo_val
            if span < 1e-9:
                cumulative = (lo_prob + hi_prob) / 2.0
            else:
                t = (threshold - lo_val) / span
                cumulative = lo_prob + t * (hi_prob - lo_prob)
            # P(X > threshold) = 1 - CDF(threshold)
            return float(np.clip(1.0 - cumulative, 0.0, 1.0))

    return 0.5


def _format_threshold(metric: str, value: float) -> str:
    """Format a numeric threshold for display in Chinese probability statements.

    Args:
        metric: Metric name, used to select appropriate formatting.
        value: Numeric value.

    Returns:
        Formatted string (e.g., '4.5%', '16,800', '0.35').
    """
    if metric in ("hibor_1m", "unemployment_rate", "gdp_growth",
                  "fed_rate", "china_gdp_growth"):
        return f"{value:.2%}"
    if metric == "taiwan_strait_risk":
        return f"{value:.2f}"
    if metric in ("hsi_level", "net_migration"):
        return f"{value:,.0f}"
    if metric in ("consumer_confidence",):
        return f"{value:.1f}"
    if metric == "ccl_index":
        return f"{value:.1f}"
    return f"{value:.4g}"
