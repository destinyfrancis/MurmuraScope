"""Time-Delayed Mutual Information (TDMI) temporal belief persistence service.

TDMI(X_t; X_{t+τ}) measures the mutual information between an agent's belief
stance at time t and at time t+τ.  A positive TDMI above the detection
threshold indicates **temporal belief persistence** — the degree to which
current beliefs predict future beliefs within the same population.

.. note::
    TDMI measures temporal autocorrelation of individual stances.  It is a
    *necessary but not sufficient* precondition for collective emergence.
    True collective emergence (e.g. spontaneous norm formation) additionally
    requires PID synergistic information across agents (Williams & Beer 2010).
    This service does not claim to measure emergence directly; it measures
    the temporal information structure that *enables* emergent dynamics.

Both hk_demographic and kg_driven modes are supported because both persist
belief data to the shared ``belief_states`` table.

References:
    Kraskov, Stögbauer & Grassberger (2004) Estimating mutual information.
        Phys Rev E 69, 066138.  (KNN estimator used here, k=5)
    Fraser & Swinney (1986) Independent coordinates for strange attractors
        from time series. Phys Rev A 33(2), 1134.
    Williams & Beer (2010) Nonnegative Decomposition of Multivariate
        Information. arXiv:1004.2515.  (PID framework for true emergence)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("emergence_metrics")

# Lags (in simulation rounds) used for TDMI computation
_DEFAULT_LAGS: tuple[int, ...] = (1, 3, 5)

# Minimum paired samples required for a meaningful MI estimate
_MIN_SAMPLES: int = 10

# Emergence detection threshold (nats): mean TDMI above this → "detected"
# Audit fix (2026-03-20): raised 0.01 → 0.02 to reduce false positives.
# 0.01 nats is near the noise floor of the KNN estimator on small samples;
# 0.02 requires a more meaningful degree of temporal information persistence.
_EMERGENCE_THRESHOLD: float = 0.02


@dataclass(frozen=True)
class TDMIResult:
    """Mutual information between belief stances separated by ``lag`` rounds."""

    session_id: str
    round_number: int
    topic: str
    lag: int
    tdmi_score: float  # mutual information in nats (≥ 0)
    n_samples: int     # number of (x_t, y_{t+lag}) agent-round pairs


@dataclass(frozen=True)
class EmergenceMetricsSummary:
    """Aggregated TDMI summary for a single measurement checkpoint."""

    session_id: str
    round_number: int
    mean_tdmi: float       # mean across all (topic, lag) pairs
    max_tdmi: float        # peak MI observed
    n_topics: int          # number of distinct belief topics measured
    emergence_detected: bool  # True when mean_tdmi > _EMERGENCE_THRESHOLD (temporal persistence signal)
    per_topic: tuple        # tuple[dict] — per-topic breakdown


class EmergenceMetricsCalculator:
    """Compute and persist TDMI from the ``belief_states`` table.

    Usage::

        calc = EmergenceMetricsCalculator()
        summary = await calc.compute_and_persist(session_id, round_number)
    """

    _THRESHOLD: float = _EMERGENCE_THRESHOLD

    async def compute_and_persist(
        self,
        session_id: str,
        round_number: int,
        lags: tuple[int, ...] = _DEFAULT_LAGS,
    ) -> EmergenceMetricsSummary:
        """Compute TDMI for all belief topics and persist results to DB.

        Returns an :class:`EmergenceMetricsSummary` regardless of whether
        belief data is available (returns zero-valued summary on empty data).
        """
        results = await self._compute_all_topics(session_id, round_number, lags)
        await self._persist_results(session_id, round_number, results)
        summary = _build_summary(session_id, round_number, results, self._THRESHOLD)
        logger.info(
            "TDMI session=%s round=%d n_topics=%d mean_tdmi=%.4f detected=%s",
            session_id,
            round_number,
            summary.n_topics,
            summary.mean_tdmi,
            summary.emergence_detected,
        )
        return summary

    # ------------------------------------------------------------------ #
    # Private                                                              #
    # ------------------------------------------------------------------ #

    async def _compute_all_topics(
        self,
        session_id: str,
        round_number: int,
        lags: tuple[int, ...],
    ) -> list[TDMIResult]:
        try:
            import numpy as np  # noqa: PLC0415
        except ImportError:
            logger.warning("numpy unavailable — TDMI computation skipped")
            return []

        async with get_db() as db:
            cursor = await db.execute(
                """SELECT agent_id, topic, stance, round_number
                   FROM belief_states
                   WHERE session_id = ? AND round_number <= ?
                   ORDER BY topic, agent_id, round_number""",
                (session_id, round_number),
            )
            rows = await cursor.fetchall()

        if not rows:
            return []

        # topic → agent_id → sorted [(round, stance)]
        topic_agent_series: dict[str, dict[str, list[tuple[int, float]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for r in rows:
            topic_agent_series[r["topic"]][str(r["agent_id"])].append(
                (int(r["round_number"]), float(r["stance"]))
            )

        results: list[TDMIResult] = []
        for topic, agent_series in topic_agent_series.items():
            for lag in lags:
                x_vals, y_vals = _collect_pairs(agent_series, lag, round_number)
                if len(x_vals) < _MIN_SAMPLES:
                    continue
                score = _histogram_mi(
                    np.asarray(x_vals, dtype=np.float64),
                    np.asarray(y_vals, dtype=np.float64),
                )
                results.append(
                    TDMIResult(
                        session_id=session_id,
                        round_number=round_number,
                        topic=topic,
                        lag=lag,
                        tdmi_score=score,
                        n_samples=len(x_vals),
                    )
                )

        return results

    async def _persist_results(
        self,
        session_id: str,
        round_number: int,
        results: list[TDMIResult],
    ) -> None:
        if not results:
            return
        async with get_db() as db:
            for r in results:
                await db.execute(
                    """INSERT OR REPLACE INTO emergence_metrics
                       (session_id, round_number, topic, lag, tdmi_score, n_samples)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        r.round_number,
                        r.topic,
                        r.lag,
                        r.tdmi_score,
                        r.n_samples,
                    ),
                )
            await db.commit()


# ------------------------------------------------------------------ #
# Pure helper functions                                                #
# ------------------------------------------------------------------ #


def _collect_pairs(
    agent_series: dict[str, list[tuple[int, float]]],
    lag: int,
    up_to_round: int,
) -> tuple[list[float], list[float]]:
    """Collect (stance_t, stance_{t+lag}) pairs across all agents.

    Only rounds <= up_to_round are considered.  Pairs are included only
    when both the base round and the lagged round have recorded stances.
    """
    x_vals: list[float] = []
    y_vals: list[float] = []
    for series in agent_series.values():
        filtered = sorted((rnd, s) for rnd, s in series if rnd <= up_to_round)
        round_to_stance = {rnd: s for rnd, s in filtered}
        for rnd, stance_t in filtered:
            lagged = rnd + lag
            if lagged in round_to_stance:
                x_vals.append(stance_t)
                y_vals.append(round_to_stance[lagged])
    return x_vals, y_vals


def _histogram_mi(x: "np.ndarray", y: "np.ndarray") -> float:  # type: ignore[name-defined]
    """Estimate MI(X;Y) in nats using sklearn's k-nearest-neighbours estimator.

    Uses ``mutual_info_regression`` (Kraskov KNN method) which has much lower
    finite-sample bias than histogram estimators for continuous variables.
    Returns 0.0 on any failure.

    sklearn returns MI in nats when ``n_neighbors`` default is used.
    """
    try:
        from sklearn.feature_selection import mutual_info_regression  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        # n_neighbors=5 per Kraskov (2004) recommendation; k=3 over-estimates
        # on small samples (fewer rounds early in a simulation).
        mi_arr = mutual_info_regression(
            x.reshape(-1, 1), y, random_state=42, n_neighbors=5
        )
        return float(max(0.0, mi_arr[0]))
    except Exception:
        return 0.0


def _build_summary(
    session_id: str,
    round_number: int,
    results: list[TDMIResult],
    threshold: float,
) -> EmergenceMetricsSummary:
    """Build an :class:`EmergenceMetricsSummary` from a list of TDMI results."""
    if not results:
        return EmergenceMetricsSummary(
            session_id=session_id,
            round_number=round_number,
            mean_tdmi=0.0,
            max_tdmi=0.0,
            n_topics=0,
            emergence_detected=False,
            per_topic=(),
        )

    scores = [r.tdmi_score for r in results]
    mean_tdmi = sum(scores) / len(scores)
    max_tdmi = max(scores)
    topics = sorted({r.topic for r in results})

    per_topic = tuple(
        {
            "topic": topic,
            "mean_tdmi": round(
                sum(r.tdmi_score for r in results if r.topic == topic)
                / sum(1 for r in results if r.topic == topic),
                6,
            ),
            "lags": [
                {
                    "lag": r.lag,
                    "tdmi": round(r.tdmi_score, 6),
                    "n_samples": r.n_samples,
                }
                for r in sorted(
                    (r for r in results if r.topic == topic),
                    key=lambda r: r.lag,
                )
            ],
        }
        for topic in topics
    )

    return EmergenceMetricsSummary(
        session_id=session_id,
        round_number=round_number,
        mean_tdmi=round(mean_tdmi, 6),
        max_tdmi=round(max_tdmi, 6),
        n_topics=len(topics),
        emergence_detected=mean_tdmi > threshold,
        per_topic=per_topic,
    )
