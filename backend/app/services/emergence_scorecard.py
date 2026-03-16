"""Emergence scorecard generator.

Aggregates cascade, polarization, diversity, bias, and phase transition
metrics into a single per-simulation summary with a letter grade (A-F).
"""
from __future__ import annotations

import json
import math
from typing import Any

from backend.app.models.emergence import EmergenceScorecard
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("emergence_scorecard")


class EmergenceScorecardGenerator:
    """Generate per-simulation emergence quality scorecard."""

    async def generate(self, session_id: str) -> EmergenceScorecard:
        """Generate scorecard at simulation completion.

        Aggregates metrics from multiple tables and computes a letter grade.
        """
        cascade = await self._cascade_metrics(session_id)
        polarization = await self._polarization_metrics(session_id)
        entropy_trend = await self._opinion_entropy_trend(session_id)
        bimodality_p = await self._stance_bimodality(session_id)
        emergence_ratio = await self._emergence_ratio(session_id)
        bias_contamination = await self._bias_contamination(session_id)
        transition_count = await self._transition_count(session_id)
        action_diversity = await self._action_diversity(session_id)
        network_volatility = await self._network_volatility(session_id)
        filter_bubble_delta = await self._filter_bubble_delta(session_id)
        info_flow = await self._information_flow_efficiency(session_id)
        # Phase 3 metrics
        emotional_convergence = await self._emotional_convergence(session_id)
        belief_revision_rate = await self._belief_revision_rate(session_id)
        dissonance_prevalence = await self._dissonance_prevalence(session_id)

        grade = _compute_grade(
            emergence_ratio=emergence_ratio,
            bias_contamination=bias_contamination,
            max_cascade_depth=cascade["max_depth"],
            action_diversity=action_diversity,
            network_volatility=network_volatility,
            belief_revision_rate=belief_revision_rate,
        )

        scorecard = EmergenceScorecard(
            session_id=session_id,
            max_cascade_depth=cascade["max_depth"],
            cascade_count=cascade["count"],
            avg_cascade_breadth=cascade["avg_breadth"],
            polarization_delta=polarization["delta"],
            echo_chamber_count_delta=polarization["echo_delta"],
            opinion_entropy_trend=entropy_trend,
            stance_bimodality_p=bimodality_p,
            emergence_ratio=emergence_ratio,
            bias_contamination=bias_contamination,
            transition_count=transition_count,
            action_diversity_score=action_diversity,
            network_volatility=network_volatility,
            filter_bubble_delta=filter_bubble_delta,
            information_flow_efficiency=info_flow,
            emotional_convergence=emotional_convergence,
            belief_revision_rate=belief_revision_rate,
            dissonance_prevalence=dissonance_prevalence,
            grade=grade,
        )

        await self._persist(session_id, scorecard)
        return scorecard

    # ------------------------------------------------------------------
    # Private metric collectors
    # ------------------------------------------------------------------

    async def _cascade_metrics(self, session_id: str) -> dict[str, Any]:
        """Cascade depth and breadth from simulation_actions."""
        result: dict[str, Any] = {"max_depth": 0, "count": 0, "avg_breadth": 0.0}
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT MAX(spread_depth), "
                    "COUNT(DISTINCT parent_action_id), "
                    "AVG(spread_depth) "
                    "FROM simulation_actions "
                    "WHERE session_id = ? AND spread_depth > 0",
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row and row[0] is not None:
                    result["max_depth"] = int(row[0])
                    result["count"] = int(row[1]) if row[1] else 0
                    result["avg_breadth"] = round(float(row[2]), 2) if row[2] else 0.0
        except Exception:
            logger.debug("cascade_metrics: spread_depth column may not exist")
        return result

    async def _polarization_metrics(self, session_id: str) -> dict[str, Any]:
        """Polarization delta and echo chamber count delta."""
        result: dict[str, Any] = {"delta": 0.0, "echo_delta": 0}
        try:
            async with get_db() as db:
                # Polarization: first vs last
                cursor = await db.execute(
                    "SELECT polarization_index, round_number "
                    "FROM polarization_snapshots WHERE session_id = ? "
                    "ORDER BY round_number ASC",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                if len(rows) >= 2:
                    result["delta"] = round(float(rows[-1][0]) - float(rows[0][0]), 4)

                # Echo chambers: first vs last
                cursor = await db.execute(
                    "SELECT num_clusters, round_number "
                    "FROM echo_chamber_snapshots WHERE session_id = ? "
                    "ORDER BY round_number ASC",
                    (session_id,),
                )
                echo_rows = await cursor.fetchall()
                if len(echo_rows) >= 2:
                    result["echo_delta"] = int(echo_rows[-1][0]) - int(echo_rows[0][0])
        except Exception:
            logger.debug("polarization_metrics failed session=%s", session_id)
        return result

    async def _opinion_entropy_trend(self, session_id: str) -> str:
        """Compare Shannon entropy of political stances: first vs last third."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT political_stance FROM agent_profiles "
                    "WHERE session_id = ? AND political_stance IS NOT NULL",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                if len(rows) < 10:
                    return "stable"

                stances = [float(r[0]) for r in rows]

                # Discretise into 5 bins
                def _entropy(values: list[float]) -> float:
                    bins = [0] * 5
                    for v in values:
                        idx = min(4, int(v * 5))
                        bins[idx] += 1
                    n = len(values)
                    return -sum(
                        (c / n) * math.log2(c / n) for c in bins if c > 0
                    )

                # Compare early snapshot polarization vs late
                cursor = await db.execute(
                    "SELECT opinion_variance FROM polarization_snapshots "
                    "WHERE session_id = ? ORDER BY round_number ASC",
                    (session_id,),
                )
                pol_rows = await cursor.fetchall()
                if len(pol_rows) >= 3:
                    third = len(pol_rows) // 3
                    early_avg = sum(float(r[0]) for r in pol_rows[:third]) / max(1, third)
                    late_avg = sum(float(r[0]) for r in pol_rows[-third:]) / max(1, third)
                    diff = late_avg - early_avg
                    if diff > 0.02:
                        return "increasing"
                    elif diff < -0.02:
                        return "decreasing"
                return "stable"
        except Exception:
            logger.debug("opinion_entropy_trend failed session=%s", session_id)
            return "stable"

    async def _stance_bimodality(self, session_id: str) -> float:
        """Hartigan dip test p-value for political stance bimodality.

        Falls back to a variance-ratio heuristic if scipy unavailable.
        """
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT political_stance FROM agent_profiles "
                    "WHERE session_id = ? AND political_stance IS NOT NULL",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            if len(rows) < 10:
                return 1.0

            values = sorted(float(r[0]) for r in rows)

            # Try scipy diptest
            try:
                from scipy.stats import gaussian_kde  # noqa: PLC0415
                import numpy as np  # noqa: PLC0415

                arr = np.array(values)
                # Simple bimodality coefficient: (skewness^2 + 1) / kurtosis
                n = len(arr)
                mean = arr.mean()
                std = arr.std()
                if std < 1e-10:
                    return 1.0
                skew = float(((arr - mean) ** 3).sum() / (n * std ** 3))
                kurt = float(((arr - mean) ** 4).sum() / (n * std ** 4))
                # Bimodality coefficient (Pfister et al., 2013)
                bc = (skew ** 2 + 1) / kurt
                # BC > 0.555 suggests bimodality
                return round(1.0 - bc, 4) if bc < 1.0 else 0.0
            except ImportError:
                # Fallback: variance ratio between halves
                mid = len(values) // 2
                lower = values[:mid]
                upper = values[mid:]
                var_lower = sum((v - sum(lower) / len(lower)) ** 2 for v in lower) / len(lower) if lower else 0
                var_upper = sum((v - sum(upper) / len(upper)) ** 2 for v in upper) / len(upper) if upper else 0
                total_var = sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values)
                if total_var < 1e-10:
                    return 1.0
                within = (var_lower + var_upper) / 2
                ratio = within / total_var
                return round(ratio, 4)
        except Exception:
            logger.debug("stance_bimodality failed session=%s", session_id)
            return 1.0

    async def _emergence_ratio(self, session_id: str) -> float:
        """Average emergence ratio from EmergenceAttributor.

        If no attribution data exists, estimate from polarization change.
        """
        try:
            from backend.app.services.emergence_guards import EmergenceAttributor  # noqa: PLC0415

            # Load bias probe result for this session
            bias_result = None
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT agreement_rate FROM bias_probe_results "
                    "WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row:
                    from backend.app.models.emergence import BiasProbeResult  # noqa: PLC0415
                    bias_result = BiasProbeResult(
                        session_id=session_id,
                        scenario="",
                        sample_size=0,
                        agreement_rate=float(row[0]),
                        stance_kurtosis=0.0,
                        persona_compliance=0.0,
                        diversity_index=0.0,
                        bias_detected=False,
                    )

                # Get round range
                cursor = await db.execute(
                    "SELECT MIN(round_number), MAX(round_number) "
                    "FROM polarization_snapshots WHERE session_id = ?",
                    (session_id,),
                )
                rng = await cursor.fetchone()

            if not rng or rng[0] is None:
                return 0.0

            attributor = EmergenceAttributor()
            ratios: list[float] = []
            for metric in ("modularity", "opinion_variance"):
                attr = await attributor.compute_attribution(
                    session_id, metric, int(rng[0]), int(rng[1]),
                    bias_probe_result=bias_result,
                )
                ratios.append(attr.emergence_ratio)

            return round(sum(ratios) / len(ratios), 4) if ratios else 0.0
        except Exception:
            logger.debug("emergence_ratio failed session=%s", session_id)
            return 0.0

    async def _bias_contamination(self, session_id: str) -> float:
        """Aggregate bias score from BiasProbe results."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT agreement_rate FROM bias_probe_results "
                    "WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row:
                    return round(float(row[0]), 4)
        except Exception:
            pass
        return 0.0

    async def _transition_count(self, session_id: str) -> int:
        """Count critical phase transition alerts."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM emergence_alerts "
                    "WHERE session_id = ? AND severity = 'critical'",
                    (session_id,),
                )
                row = await cursor.fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return 0

    async def _action_diversity(self, session_id: str) -> float:
        """Shannon entropy of action type distribution.

        Higher values indicate more diverse agent behaviour.
        A simulation using only 'post' actions has entropy 0.0.
        12 equally distributed action types yields ~3.58.
        """
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT action_type, COUNT(*) as cnt "
                    "FROM simulation_actions "
                    "WHERE session_id = ? "
                    "GROUP BY action_type",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            if not rows:
                return 0.0

            total = sum(r[1] for r in rows)
            if total == 0:
                return 0.0

            entropy = 0.0
            for row in rows:
                p = row[1] / total
                if p > 0:
                    entropy -= p * math.log2(p)

            return round(entropy, 4)
        except Exception:
            logger.debug("action_diversity failed session=%s", session_id)
            return 0.0

    async def _network_volatility(self, session_id: str) -> float:
        """Phase 1C: compute avg (TIE_FORMED + TIE_DISSOLVED) events per round / agent count.

        Returns:
            Normalised network volatility score (0.0 if no data).
        """
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT round_number, COUNT(*) as cnt
                       FROM network_events
                       WHERE session_id = ?
                         AND event_type IN ('TIE_FORMED','TIE_DISSOLVED')
                       GROUP BY round_number""",
                    (session_id,),
                )
                rows = await cursor.fetchall()

                # Agent count for normalisation
                a_cursor = await db.execute(
                    "SELECT COUNT(*) FROM agent_profiles WHERE session_id = ?",
                    (session_id,),
                )
                a_row = await a_cursor.fetchone()
                agent_count = int(a_row[0]) if a_row and a_row[0] else 1

            if not rows:
                return 0.0

            avg_events_per_round = sum(int(r[1]) for r in rows) / len(rows)
            return round(avg_events_per_round / max(1, agent_count), 6)
        except Exception:
            logger.debug("network_volatility failed session=%s", session_id)
            return 0.0

    async def _filter_bubble_delta(self, session_id: str) -> float:
        """Phase 2: change in avg_bubble_score from first to last round.

        Positive delta means filter bubbles intensified over time.
        """
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT avg_bubble_score, round_number
                       FROM filter_bubble_snapshots
                       WHERE session_id = ?
                       ORDER BY round_number ASC""",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            if len(rows) < 2:
                return 0.0

            first = float(rows[0][0])
            last = float(rows[-1][0])
            return round(last - first, 4)
        except Exception:
            logger.debug("filter_bubble_delta failed session=%s", session_id)
            return 0.0

    async def _information_flow_efficiency(self, session_id: str) -> float:
        """Phase 2: avg cross_cluster_reach of top-10 viral posts.

        Higher values indicate information flows well across community boundaries.
        """
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT cross_cluster_reach
                       FROM virality_scores
                       WHERE session_id = ?
                       ORDER BY virality_index DESC
                       LIMIT 10""",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            if not rows:
                return 0.0

            values = [float(r[0]) for r in rows]
            return round(sum(values) / len(values), 4)
        except Exception:
            logger.debug("information_flow_efficiency failed session=%s", session_id)
            return 0.0

    # ------------------------------------------------------------------
    # Phase 3: Emotional state metric collectors
    # ------------------------------------------------------------------

    async def _emotional_convergence(self, session_id: str) -> float:
        """Compute valence variance reduction from first to last round."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT round_number, AVG(valence), AVG(valence*valence)
                    FROM emotional_states
                    WHERE session_id = ?
                    GROUP BY round_number
                    ORDER BY round_number ASC""",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            if len(rows) < 2:
                return 0.0

            def _variance(avg_v: float, avg_v2: float) -> float:
                return max(0.0, avg_v2 - avg_v * avg_v)

            first_var = _variance(float(rows[0][1]), float(rows[0][2]))
            last_var = _variance(float(rows[-1][1]), float(rows[-1][2]))
            return round(first_var - last_var, 4)
        except Exception:
            logger.debug("emotional_convergence failed session=%s", session_id)
            return 0.0

    async def _belief_revision_rate(self, session_id: str) -> float:
        """Fraction of beliefs with stance change > 0.1 / total beliefs / rounds."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT COUNT(*), COUNT(*) AS total
                    FROM (
                        SELECT b1.agent_id, b1.topic
                        FROM belief_states b1
                        JOIN belief_states b2
                          ON b1.session_id = b2.session_id
                         AND b1.agent_id = b2.agent_id
                         AND b1.topic = b2.topic
                        WHERE b1.session_id = ?
                          AND b1.round_number = (SELECT MIN(round_number) FROM belief_states WHERE session_id = ?)
                          AND b2.round_number = (SELECT MAX(round_number) FROM belief_states WHERE session_id = ?)
                          AND ABS(b2.stance - b1.stance) > 0.1
                    )""",
                    (session_id, session_id, session_id),
                )
                revised_row = await cursor.fetchone()

                cursor2 = await db.execute(
                    """SELECT COUNT(*) FROM belief_states WHERE session_id = ?
                    AND round_number = (SELECT MIN(round_number) FROM belief_states WHERE session_id = ?)""",
                    (session_id, session_id),
                )
                total_row = await cursor2.fetchone()

                cursor3 = await db.execute(
                    """SELECT COUNT(DISTINCT round_number) FROM belief_states WHERE session_id = ?""",
                    (session_id,),
                )
                rounds_row = await cursor3.fetchone()

            revised = int(revised_row[0]) if revised_row and revised_row[0] else 0
            total = int(total_row[0]) if total_row and total_row[0] else 0
            rounds = max(1, int(rounds_row[0]) if rounds_row and rounds_row[0] else 1)

            if total == 0:
                return 0.0
            return round(revised / total / rounds, 6)
        except Exception:
            logger.debug("belief_revision_rate failed session=%s", session_id)
            return 0.0

    async def _dissonance_prevalence(self, session_id: str) -> float:
        """Average dissonance score across all agents at the last round."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT AVG(dissonance_score)
                    FROM cognitive_dissonance
                    WHERE session_id = ?
                      AND round_number = (
                          SELECT MAX(round_number) FROM cognitive_dissonance WHERE session_id = ?
                      )""",
                    (session_id, session_id),
                )
                row = await cursor.fetchone()

            if row and row[0] is not None:
                return round(float(row[0]), 4)
            return 0.0
        except Exception:
            logger.debug("dissonance_prevalence failed session=%s", session_id)
            return 0.0

    async def _persist(self, session_id: str, sc: EmergenceScorecard) -> None:
        """Store scorecard in DB."""
        try:
            async with get_db() as db:
                await db.execute(
                    """CREATE TABLE IF NOT EXISTS emergence_scorecards (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL UNIQUE,
                        max_cascade_depth INTEGER NOT NULL DEFAULT 0,
                        cascade_count INTEGER NOT NULL DEFAULT 0,
                        avg_cascade_breadth REAL NOT NULL DEFAULT 0.0,
                        polarization_delta REAL NOT NULL DEFAULT 0.0,
                        echo_chamber_count_delta INTEGER NOT NULL DEFAULT 0,
                        opinion_entropy_trend TEXT NOT NULL DEFAULT 'stable',
                        stance_bimodality_p REAL NOT NULL DEFAULT 1.0,
                        emergence_ratio REAL NOT NULL DEFAULT 0.0,
                        bias_contamination REAL NOT NULL DEFAULT 0.0,
                        transition_count INTEGER NOT NULL DEFAULT 0,
                        action_diversity_score REAL NOT NULL DEFAULT 0.0,
                        network_volatility REAL NOT NULL DEFAULT 0.0,
                        filter_bubble_delta REAL NOT NULL DEFAULT 0.0,
                        information_flow_efficiency REAL NOT NULL DEFAULT 0.0,
                        grade TEXT NOT NULL DEFAULT 'F',
                        details_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT DEFAULT (datetime('now'))
                    )"""
                )
                # Idempotent runtime migrations for new columns
                for col_def in [
                    ("network_volatility", "REAL NOT NULL DEFAULT 0.0"),
                    ("filter_bubble_delta", "REAL NOT NULL DEFAULT 0.0"),
                    ("information_flow_efficiency", "REAL NOT NULL DEFAULT 0.0"),
                    ("emotional_convergence", "REAL NOT NULL DEFAULT 0.0"),
                    ("belief_revision_rate", "REAL NOT NULL DEFAULT 0.0"),
                    ("dissonance_prevalence", "REAL NOT NULL DEFAULT 0.0"),
                ]:
                    try:
                        await db.execute(
                            f"ALTER TABLE emergence_scorecards ADD COLUMN {col_def[0]} {col_def[1]}"
                        )
                    except Exception:
                        pass  # Column already exists
                await db.execute(
                    "INSERT OR REPLACE INTO emergence_scorecards "
                    "(session_id, max_cascade_depth, cascade_count, "
                    "avg_cascade_breadth, polarization_delta, "
                    "echo_chamber_count_delta, opinion_entropy_trend, "
                    "stance_bimodality_p, emergence_ratio, "
                    "bias_contamination, transition_count, "
                    "action_diversity_score, network_volatility, "
                    "filter_bubble_delta, information_flow_efficiency, "
                    "emotional_convergence, belief_revision_rate, "
                    "dissonance_prevalence, grade) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        session_id, sc.max_cascade_depth, sc.cascade_count,
                        sc.avg_cascade_breadth, sc.polarization_delta,
                        sc.echo_chamber_count_delta, sc.opinion_entropy_trend,
                        sc.stance_bimodality_p, sc.emergence_ratio,
                        sc.bias_contamination, sc.transition_count,
                        sc.action_diversity_score, sc.network_volatility,
                        sc.filter_bubble_delta, sc.information_flow_efficiency,
                        sc.emotional_convergence, sc.belief_revision_rate,
                        sc.dissonance_prevalence, sc.grade,
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "EmergenceScorecardGenerator._persist failed session=%s", session_id
            )


# ---------------------------------------------------------------------------
# Grading rubric
# ---------------------------------------------------------------------------


def _compute_grade(
    emergence_ratio: float,
    bias_contamination: float,
    max_cascade_depth: int,
    action_diversity: float = 0.0,
    network_volatility: float = 0.0,
    belief_revision_rate: float = 0.0,
) -> str:
    """Compute letter grade based on rubric.

    A: emergence_ratio > 0.7, bias < 0.3, cascade_depth > 3,
       action_diversity > 2.0, network_volatility > 0.05
    B: emergence_ratio > 0.5, bias < 0.5, action_diversity > 1.5
    C: emergence_ratio > 0.3
    D: emergence_ratio > 0.1
    F: otherwise or bias > 0.7
    """
    if bias_contamination > 0.7:
        return "F"
    if emergence_ratio <= 0.1:
        return "F"
    if (
        emergence_ratio > 0.7
        and bias_contamination < 0.3
        and max_cascade_depth > 3
        and action_diversity > 2.0
        and network_volatility > 0.05
        and belief_revision_rate > 0.05  # Phase 3: active belief updating required for A grade
    ):
        return "A"
    if emergence_ratio > 0.5 and bias_contamination < 0.5 and action_diversity > 1.5:
        return "B"
    if emergence_ratio > 0.3:
        return "C"
    return "D"
