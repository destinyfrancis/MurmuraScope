"""SimulationSignalExtractor — extracts 32 numeric signals from a completed simulation session.

These signals feed into StockForecaster as sentiment/behavioural overlays.

Signal groups:
  1. Sentiment (8) — from simulation_actions, emotional_states, virality_scores
  2. Behavioural (6) — from agent_decisions
  3. Network (5) — from polarization_snapshots, echo_chamber_snapshots,
                    filter_bubble_snapshots, virality_scores, agent_relationships
  4. Macro (6) — from macro_snapshots
  5. Consumption (3) — from agent_decisions (spending categories)
  6. Forward (4) — from ensemble_results
"""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timezone
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("signal_extractor")


# ---------------------------------------------------------------------------
# SimulationSignals — frozen dataclass with 32 float signal fields
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SimulationSignals:
    """All extracted simulation signals for one session."""

    session_id: str
    extraction_ts: str

    # --- Group 1: Sentiment (8) ---
    sentiment_net: float = 0.0  # net positive ratio across all rounds
    sentiment_momentum: float = 0.0  # late-round minus early-round sentiment
    negative_virality: float = 0.0  # avg virality index of negative posts
    property_sentiment: float = 0.0  # net sentiment on property-topic posts
    finance_sentiment: float = 0.0  # net sentiment on finance-topic posts
    emotional_valence: float = 0.0  # avg valence from emotional_states
    arousal_concentration: float = 0.0  # avg arousal (high = volatile)
    contagion_velocity: float = 0.0  # avg virality velocity

    # --- Group 2: Behavioural (6) ---
    buy_property_ratio: float = 0.0  # fraction of agents deciding to buy property
    emigration_rate: float = 0.0  # fraction choosing to emigrate
    invest_ratio: float = 0.0  # fraction making investment decisions
    spending_cut_ratio: float = 0.0  # fraction cutting spending
    employment_quit_ratio: float = 0.0  # fraction quitting employment
    decision_entropy: float = 0.0  # Shannon entropy of decision distribution

    # --- Group 3: Network (5) ---
    polarization_index: float = 0.0  # latest polarization score [0,1]
    echo_chamber_modularity: float = 0.0  # latest Louvain modularity
    filter_bubble_severity: float = 0.0  # avg bubble score
    cross_cluster_reach: float = 0.0  # avg cross-cluster reach of viral posts
    trust_erosion_rate: float = 0.0  # negative trust delta rate

    # --- Group 4: Macro (6) ---
    hsi_sim_change: float = 0.0  # simulated HSI level change %
    ccl_sim_change: float = 0.0  # simulated CCL change %
    unemployment_sim_delta: float = 0.0  # unemployment change pp
    consumer_confidence_sim: float = 0.0  # final consumer confidence level
    credit_stress: float = 0.0  # credit stress index
    taiwan_strait_risk: float = 0.0  # geopolitical risk level [0,1]

    # --- Group 5: Consumption (3) ---
    discretionary_ratio: float = 0.0  # discretionary vs necessities ratio
    savings_acceleration: float = 0.0  # acceleration in savings rate
    housing_spend_share: float = 0.0  # housing spend as share of total

    # --- Group 6: Forward (4) ---
    ensemble_hsi_p50: float = 0.0  # Monte Carlo median HSI forecast
    ensemble_skew: float = 0.0  # p75 - p25 asymmetry
    ensemble_ci_width: float = 0.0  # p95 - p05 width normalised
    data_integrity_score: float = 1.0  # fraction of signals with real data


# ---------------------------------------------------------------------------
# SimulationSignalExtractor
# ---------------------------------------------------------------------------


class SimulationSignalExtractor:
    """Extracts simulation signals from DB for a given session_id."""

    async def extract(self, session_id: str) -> SimulationSignals:
        """Main entry point. Calls all 6 sub-extractors and merges results."""
        ts = datetime.now(timezone.utc).isoformat()

        results: list[dict[str, float]] = []
        real_signal_count = 0
        total_signal_count = 32

        for extractor_fn in (
            self._extract_sentiment_signals,
            self._extract_behavioral_signals,
            self._extract_network_signals,
            self._extract_macro_signals,
            self._extract_consumption_signals,
            self._extract_forward_signals,
        ):
            try:
                group = await extractor_fn(session_id)
                real_signal_count += sum(1 for v in group.values() if v != 0.0)
                results.append(group)
            except Exception as exc:
                logger.warning("Signal extractor group failed for session %s: %s", session_id, exc)
                results.append({})

        merged: dict[str, float] = {}
        for group in results:
            merged.update(group)

        data_integrity = real_signal_count / max(total_signal_count, 1)

        return SimulationSignals(
            session_id=session_id,
            extraction_ts=ts,
            data_integrity_score=round(data_integrity, 3),
            **{k: merged.get(k, 0.0) for k in _SIGNAL_FIELDS if k != "data_integrity_score"},
        )

    # ------------------------------------------------------------------
    # Group 1: Sentiment signals
    # ------------------------------------------------------------------

    async def _extract_sentiment_signals(self, session_id: str) -> dict[str, float]:
        """Extract 8 sentiment signals from simulation_actions, emotional_states, virality_scores."""
        out: dict[str, float] = {}
        try:
            async with get_db() as db:
                # sentiment_net: overall positive ratio
                row = await db.execute_fetchone(
                    """SELECT AVG(CASE WHEN sentiment > 0 THEN 1.0
                                      WHEN sentiment < 0 THEN -1.0
                                      ELSE 0.0 END)
                       FROM simulation_actions WHERE session_id = ?""",
                    (session_id,),
                )
                out["sentiment_net"] = float(row[0] or 0.0) if row and row[0] is not None else 0.0

                # sentiment_momentum: late vs early rounds
                row_early = await db.execute_fetchone(
                    """SELECT AVG(CASE WHEN sentiment > 0 THEN 1.0
                                      WHEN sentiment < 0 THEN -1.0
                                      ELSE 0.0 END)
                       FROM simulation_actions
                       WHERE session_id = ?
                         AND round_number <= (SELECT MAX(round_number) / 3 FROM simulation_actions WHERE session_id = ?)""",
                    (session_id, session_id),
                )
                row_late = await db.execute_fetchone(
                    """SELECT AVG(CASE WHEN sentiment > 0 THEN 1.0
                                      WHEN sentiment < 0 THEN -1.0
                                      ELSE 0.0 END)
                       FROM simulation_actions
                       WHERE session_id = ?
                         AND round_number > (SELECT 2 * MAX(round_number) / 3 FROM simulation_actions WHERE session_id = ?)""",
                    (session_id, session_id),
                )
                early_val = float(row_early[0] or 0.0) if row_early and row_early[0] is not None else 0.0
                late_val = float(row_late[0] or 0.0) if row_late and row_late[0] is not None else 0.0
                out["sentiment_momentum"] = late_val - early_val

                # negative_virality: avg virality index of negative posts
                row_nv = await db.execute_fetchone(
                    """SELECT AVG(vs.virality_index)
                       FROM virality_scores vs
                       JOIN simulation_actions sa ON sa.post_id = vs.post_id AND sa.session_id = vs.session_id
                       WHERE vs.session_id = ? AND sa.sentiment < 0""",
                    (session_id,),
                )
                out["negative_virality"] = float(row_nv[0] or 0.0) if row_nv and row_nv[0] is not None else 0.0

                # property_sentiment and finance_sentiment via topics
                for field, topic_kw in [("property_sentiment", "property"), ("finance_sentiment", "finance")]:
                    row_t = await db.execute_fetchone(
                        """SELECT AVG(CASE WHEN sentiment > 0 THEN 1.0
                                          WHEN sentiment < 0 THEN -1.0
                                          ELSE 0.0 END)
                           FROM simulation_actions
                           WHERE session_id = ? AND LOWER(topics) LIKE ?""",
                        (session_id, f"%{topic_kw}%"),
                    )
                    out[field] = float(row_t[0] or 0.0) if row_t and row_t[0] is not None else 0.0

                # emotional_valence and arousal_concentration from emotional_states
                row_es = await db.execute_fetchone(
                    "SELECT AVG(valence), AVG(arousal) FROM emotional_states WHERE session_id = ?",
                    (session_id,),
                )
                if row_es and row_es[0] is not None:
                    out["emotional_valence"] = float(row_es[0] or 0.0)
                    out["arousal_concentration"] = float(row_es[1] or 0.0)
                else:
                    out["emotional_valence"] = 0.0
                    out["arousal_concentration"] = 0.0

                # contagion_velocity from virality_scores
                row_vel = await db.execute_fetchone(
                    "SELECT AVG(velocity) FROM virality_scores WHERE session_id = ?",
                    (session_id,),
                )
                out["contagion_velocity"] = float(row_vel[0] or 0.0) if row_vel and row_vel[0] is not None else 0.0

        except Exception as exc:
            logger.warning("Sentiment signal extraction failed for %s: %s", session_id, exc)

        return out

    # ------------------------------------------------------------------
    # Group 2: Behavioural signals
    # ------------------------------------------------------------------

    async def _extract_behavioral_signals(self, session_id: str) -> dict[str, float]:
        """Extract 6 behavioural signals from agent_decisions."""
        out: dict[str, float] = {}
        try:
            async with get_db() as db:
                row_total = await db.execute_fetchone(
                    "SELECT COUNT(*) FROM agent_decisions WHERE session_id = ?",
                    (session_id,),
                )
                total = int(row_total[0] or 0) if row_total else 0
                if total == 0:
                    return {
                        k: 0.0
                        for k in [
                            "buy_property_ratio",
                            "emigration_rate",
                            "invest_ratio",
                            "spending_cut_ratio",
                            "employment_quit_ratio",
                            "decision_entropy",
                        ]
                    }

                # Per-type counts
                rows = await db.execute_fetchall(
                    "SELECT decision_type, COUNT(*) as cnt FROM agent_decisions WHERE session_id = ? GROUP BY decision_type",
                    (session_id,),
                )
                counts: dict[str, int] = {r[0]: int(r[1]) for r in rows}

                out["buy_property_ratio"] = counts.get("buy_property", 0) / total
                out["emigration_rate"] = counts.get("emigrate", 0) / total
                out["invest_ratio"] = counts.get("invest", 0) / total
                out["spending_cut_ratio"] = counts.get("cut_spending", 0) / total
                out["employment_quit_ratio"] = counts.get("quit_job", 0) / total

                # Shannon entropy of decision distribution
                probs = [c / total for c in counts.values() if c > 0]
                entropy = -sum(p * math.log2(p) for p in probs) if probs else 0.0
                max_entropy = math.log2(max(len(counts), 1))
                out["decision_entropy"] = entropy / max_entropy if max_entropy > 0 else 0.0

        except Exception as exc:
            logger.warning("Behavioural signal extraction failed for %s: %s", session_id, exc)

        return out

    # ------------------------------------------------------------------
    # Group 3: Network signals
    # ------------------------------------------------------------------

    async def _extract_network_signals(self, session_id: str) -> dict[str, float]:
        """Extract 5 network signals from polarization, echo chamber, filter bubble, virality, relationships."""
        out: dict[str, float] = {}
        try:
            async with get_db() as db:
                # polarization_index — latest snapshot
                row_pol = await db.execute_fetchone(
                    """SELECT polarization_index FROM polarization_snapshots
                       WHERE session_id = ? ORDER BY round_number DESC LIMIT 1""",
                    (session_id,),
                )
                out["polarization_index"] = float(row_pol[0] or 0.0) if row_pol and row_pol[0] is not None else 0.0

                # echo_chamber_modularity — latest snapshot
                row_ec = await db.execute_fetchone(
                    """SELECT modularity FROM echo_chamber_snapshots
                       WHERE session_id = ? ORDER BY round_number DESC LIMIT 1""",
                    (session_id,),
                )
                out["echo_chamber_modularity"] = float(row_ec[0] or 0.0) if row_ec and row_ec[0] is not None else 0.0

                # filter_bubble_severity — avg bubble score
                row_fb = await db.execute_fetchone(
                    "SELECT AVG(avg_bubble_score) FROM filter_bubble_snapshots WHERE session_id = ?",
                    (session_id,),
                )
                out["filter_bubble_severity"] = float(row_fb[0] or 0.0) if row_fb and row_fb[0] is not None else 0.0

                # cross_cluster_reach — avg from virality_scores
                row_ccr = await db.execute_fetchone(
                    "SELECT AVG(cross_cluster_reach) FROM virality_scores WHERE session_id = ?",
                    (session_id,),
                )
                out["cross_cluster_reach"] = float(row_ccr[0] or 0.0) if row_ccr and row_ccr[0] is not None else 0.0

                # trust_erosion_rate — fraction of negative trust relationships
                row_tr = await db.execute_fetchone(
                    """SELECT AVG(CASE WHEN trust_score < 0 THEN 1.0 ELSE 0.0 END)
                       FROM agent_relationships WHERE session_id = ?""",
                    (session_id,),
                )
                out["trust_erosion_rate"] = float(row_tr[0] or 0.0) if row_tr and row_tr[0] is not None else 0.0

        except Exception as exc:
            logger.warning("Network signal extraction failed for %s: %s", session_id, exc)

        return out

    # ------------------------------------------------------------------
    # Group 4: Macro signals
    # ------------------------------------------------------------------

    async def _extract_macro_signals(self, session_id: str) -> dict[str, float]:
        """Extract 6 macro signals from macro_snapshots."""
        out: dict[str, float] = {}
        try:
            async with get_db() as db:
                # Get first and last macro snapshot
                row_first = await db.execute_fetchone(
                    """SELECT hsi_level, ccl_index, unemployment_rate,
                              consumer_confidence, credit_stress, taiwan_strait_risk
                       FROM macro_snapshots WHERE session_id = ?
                       ORDER BY round_number ASC LIMIT 1""",
                    (session_id,),
                )
                row_last = await db.execute_fetchone(
                    """SELECT hsi_level, ccl_index, unemployment_rate,
                              consumer_confidence, credit_stress, taiwan_strait_risk
                       FROM macro_snapshots WHERE session_id = ?
                       ORDER BY round_number DESC LIMIT 1""",
                    (session_id,),
                )

                if row_first and row_last:

                    def _pct_change(first: Any, last: Any) -> float:
                        f, la = float(first or 0.0), float(last or 0.0)
                        return (la - f) / abs(f) if abs(f) > 1e-9 else 0.0

                    out["hsi_sim_change"] = _pct_change(row_first[0], row_last[0])
                    out["ccl_sim_change"] = _pct_change(row_first[1], row_last[1])
                    out["unemployment_sim_delta"] = float(row_last[2] or 0.0) - float(row_first[2] or 0.0)
                    out["consumer_confidence_sim"] = float(row_last[3] or 0.0)
                    out["credit_stress"] = float(row_last[4] or 0.0)
                    out["taiwan_strait_risk"] = float(row_last[5] or 0.0)
                else:
                    for k in [
                        "hsi_sim_change",
                        "ccl_sim_change",
                        "unemployment_sim_delta",
                        "consumer_confidence_sim",
                        "credit_stress",
                        "taiwan_strait_risk",
                    ]:
                        out[k] = 0.0

        except Exception as exc:
            logger.warning("Macro signal extraction failed for %s: %s", session_id, exc)
            for k in [
                "hsi_sim_change",
                "ccl_sim_change",
                "unemployment_sim_delta",
                "consumer_confidence_sim",
                "credit_stress",
                "taiwan_strait_risk",
            ]:
                out.setdefault(k, 0.0)

        return out

    # ------------------------------------------------------------------
    # Group 5: Consumption signals
    # ------------------------------------------------------------------

    async def _extract_consumption_signals(self, session_id: str) -> dict[str, float]:
        """Extract 3 consumption signals. Returns defaults if no consumer data."""
        out: dict[str, float] = {
            "discretionary_ratio": 0.0,
            "savings_acceleration": 0.0,
            "housing_spend_share": 0.0,
        }
        try:
            async with get_db() as db:
                # Try to read spending data from agent_decisions details
                rows = await db.execute_fetchall(
                    """SELECT decision_type, details_json FROM agent_decisions
                       WHERE session_id = ? AND decision_type IN ('spend', 'save', 'cut_spending')""",
                    (session_id,),
                )
                if not rows:
                    return out

                import json

                housing_total = 0.0
                discretionary_total = 0.0
                necessity_total = 0.0
                savings_list: list[float] = []

                for row in rows:
                    try:
                        details = json.loads(row[1] or "{}")
                        housing_total += float(details.get("housing", 0.0))
                        discretionary_total += float(details.get("discretionary", 0.0))
                        necessity_total += float(details.get("necessities", 0.0))
                        savings_list.append(float(details.get("savings_rate", 0.0)))
                    except Exception:
                        pass

                total_spend = housing_total + discretionary_total + necessity_total
                if total_spend > 0:
                    out["housing_spend_share"] = housing_total / total_spend
                    denom = discretionary_total + necessity_total
                    out["discretionary_ratio"] = discretionary_total / denom if denom > 0 else 0.0

                if len(savings_list) >= 2:
                    mid = len(savings_list) // 2
                    early_avg = sum(savings_list[:mid]) / mid
                    late_avg = sum(savings_list[mid:]) / len(savings_list[mid:])
                    out["savings_acceleration"] = late_avg - early_avg

        except Exception as exc:
            logger.warning("Consumption signal extraction failed for %s: %s", session_id, exc)

        return out

    # ------------------------------------------------------------------
    # Group 6: Forward signals
    # ------------------------------------------------------------------

    async def _extract_forward_signals(self, session_id: str) -> dict[str, float]:
        """Extract 4 forward-looking signals from ensemble_results."""
        out: dict[str, float] = {
            "ensemble_hsi_p50": 0.0,
            "ensemble_skew": 0.0,
            "ensemble_ci_width": 0.0,
        }
        try:
            async with get_db() as db:
                row = await db.execute_fetchone(
                    """SELECT p25, p50, p75, p05, p95 FROM ensemble_results
                       WHERE session_id = ? AND metric = 'hsi_level'
                       ORDER BY id DESC LIMIT 1""",
                    (session_id,),
                )
                if row and row[1] is not None:
                    p05 = float(row[3] or 0.0)
                    p25 = float(row[0] or 0.0)
                    p50 = float(row[1] or 0.0)
                    p75 = float(row[2] or 0.0)
                    p95 = float(row[4] or 0.0)
                    out["ensemble_hsi_p50"] = p50
                    # skew: asymmetry of interquartile range
                    iqr = p75 - p25
                    out["ensemble_skew"] = (p75 - p50 - (p50 - p25)) / iqr if iqr > 1e-9 else 0.0
                    # ci_width: (p95-p05) / p50
                    out["ensemble_ci_width"] = (p95 - p05) / abs(p50) if abs(p50) > 1e-9 else 0.0

        except Exception as exc:
            logger.warning("Forward signal extraction failed for %s: %s", session_id, exc)

        return out


# Fields of SimulationSignals excluding non-signal fields
_SIGNAL_FIELDS: frozenset[str] = frozenset(
    f.name for f in dataclasses.fields(SimulationSignals) if f.name not in ("session_id", "extraction_ts")
)
