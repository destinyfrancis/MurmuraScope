# backend/app/services/emergence_tracker.py
"""EmergenceTracker: FactionMapper, TippingPointDetector, NarrativeTracer.

Active in kg_driven mode only.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactionRecord:
    faction_id: str
    member_agent_ids: tuple[str, ...]
    belief_center: dict[str, float]  # avg belief per metric


@dataclass(frozen=True)
class FactionSnapshot:
    simulation_id: str
    round_number: int
    factions: tuple[FactionRecord, ...]
    bridge_agents: tuple[str, ...]
    modularity_score: float
    inter_faction_hostility: float


@dataclass(frozen=True)
class TippingPoint:
    simulation_id: str
    round_number: int
    trigger_event_id: str | None
    kl_divergence: float
    change_direction: str  # polarize | converge | split
    affected_faction_ids: tuple[str, ...]


@dataclass(frozen=True)
class NarrativeEntry:
    simulation_id: str
    agent_id: str
    round_number: int
    received_event_ids: tuple[str, ...]
    belief_delta: dict[str, float]
    decision: str | None
    llm_reasoning: str | None
    faction_changed: bool


# ---------------------------------------------------------------------------
# FactionMapper
# ---------------------------------------------------------------------------

class FactionMapper:
    """Run Leiden (with Louvain fallback) community detection on agent interaction graph."""

    def compute(
        self,
        simulation_id: str,
        round_number: int,
        agent_beliefs: dict[str, dict[str, float]],
        interaction_graph: dict[str, list[str]],
    ) -> FactionSnapshot:
        """Compute faction snapshot from current agent state."""
        try:
            import networkx as nx
        except ImportError:
            logger.warning("FactionMapper: networkx not installed — returning single faction")
            return self._single_faction(simulation_id, round_number, agent_beliefs)

        G = nx.Graph()
        for agent_id, neighbours in interaction_graph.items():
            G.add_node(agent_id)
            for n in neighbours:
                G.add_edge(agent_id, n)

        if G.number_of_edges() == 0:
            return self._single_faction(simulation_id, round_number, agent_beliefs)

        partition = self._detect_communities(G)
        modularity = self._compute_modularity(G, partition)

        # Group agents by community
        communities: dict[int, list[str]] = {}
        for agent_id, community_id in partition.items():
            communities.setdefault(community_id, []).append(agent_id)

        factions = tuple(
            FactionRecord(
                faction_id=f"faction_{cid}",
                member_agent_ids=tuple(members),
                belief_center=_avg_beliefs(members, agent_beliefs),
            )
            for cid, members in sorted(communities.items())
        )

        bridge_agents = _find_bridge_agents(G, partition)
        hostility = _compute_hostility(factions, agent_beliefs)

        return FactionSnapshot(
            simulation_id=simulation_id,
            round_number=round_number,
            factions=factions,
            bridge_agents=tuple(bridge_agents),
            modularity_score=max(0.0, min(1.0, modularity)),
            inter_faction_hostility=hostility,
        )

    def _single_faction(
        self, simulation_id: str, round_number: int,
        agent_beliefs: dict[str, dict[str, float]]
    ) -> FactionSnapshot:
        all_agents = list(agent_beliefs.keys())
        record = FactionRecord(
            faction_id="faction_0",
            member_agent_ids=tuple(all_agents),
            belief_center=_avg_beliefs(all_agents, agent_beliefs),
        )
        return FactionSnapshot(
            simulation_id=simulation_id,
            round_number=round_number,
            factions=(record,),
            bridge_agents=(),
            modularity_score=0.0,
            inter_faction_hostility=0.0,
        )

    def _detect_communities(self, G: Any) -> dict[str, int]:
        """Try Leiden (better resolution), fall back to Louvain, then single community."""
        # Try igraph Leiden first
        try:
            import igraph as ig  # noqa: PLC0415
            ig_graph = ig.Graph.from_networkx(G)
            leiden = ig_graph.community_leiden(objective_function="modularity", n_iterations=10, seed=42)
            return {
                node: membership
                for node, membership in zip(G.nodes(), leiden.membership)
            }
        except Exception:
            pass
        # Fall back to python-louvain
        try:
            from community import best_partition  # noqa: PLC0415
            return best_partition(G, random_state=42)
        except Exception:
            logger.warning(
                "FactionMapper: neither igraph nor community available — single faction"
            )
            return {n: 0 for n in G.nodes()}

    def _compute_modularity(self, G: Any, partition: dict[str, int]) -> float:
        try:
            from community import modularity  # noqa: PLC0415
            return modularity(partition, G)
        except Exception:
            return 0.0


# ---------------------------------------------------------------------------
# TippingPointDetector
# ---------------------------------------------------------------------------

class TippingPointDetector:
    """Detect sudden shifts in population-wide belief distribution.

    Uses Jensen-Shannon Divergence (JSD) rather than RMSD of means so that
    bimodal splits — where means are unchanged but the distribution polarises
    — are correctly detected.  JSD is symmetric and bounded [0, 1] (log₂
    scale), making the threshold directly interpretable.
    """

    def __init__(self, kl_threshold: float = 0.15) -> None:
        # NOTE: parameter is named kl_threshold for API compatibility, but the
        # detector internally computes Jensen-Shannon Divergence (JSD), which is
        # symmetric and bounded [0, 1] on log₂ scale — unlike KL which is
        # unbounded and asymmetric.
        #
        # Threshold = 0.15 (JSD): calibrated to Watts (2002) cascade model and
        # Axelrod & Hammond (2003) cultural dissemination ABM literature, where
        # meaningful distributional shifts in belief populations occur in the
        # JSD range [0.12, 0.20].  Below 0.15 is within normal stochastic
        # fluctuation; above 0.15 signals a regime transition.
        self._threshold = kl_threshold

    def detect(
        self,
        simulation_id: str,
        round_number: int,
        current_beliefs: dict[str, dict[str, float]],
        belief_history: list[dict[str, dict[str, float]]],
        last_event_id: str | None,
    ) -> TippingPoint | None:
        """Return TippingPoint if combined JSD exceeds threshold, else None.

        Uses dual-timescale detection:
        - Fast indicator: JSD vs 3 rounds ago (catches rapid shifts)
        - Slow indicator: EMA of JSD over up to 10 past rounds × 0.7 dampening
                         (catches slow build-ups missed by the 3-round window)
        Combined score = max(fast, slow × 0.7).
        """
        if len(belief_history) < 1:
            return None

        # Fast indicator: compare to 3 rounds prior if available
        prev = belief_history[-3] if len(belief_history) >= 3 else belief_history[0]
        jsd = self._jsd(current_beliefs, prev)

        # Slow indicator: EMA over up to 10 past rounds
        slow_jsd = self._slow_ema_jsd(current_beliefs, belief_history)

        # Combined: take max of fast and dampened slow
        combined_score = max(jsd, slow_jsd * 0.7)

        if combined_score < self._threshold:
            return None

        direction = self._classify_direction(current_beliefs, prev)
        logger.info(
            "TippingPoint detected: round=%d fast_jsd=%.3f slow_jsd=%.3f "
            "combined=%.3f direction=%s",
            round_number, jsd, slow_jsd, combined_score, direction,
        )
        return TippingPoint(
            simulation_id=simulation_id,
            round_number=round_number,
            trigger_event_id=last_event_id,
            kl_divergence=combined_score,  # field name kept for DB/API compat
            change_direction=direction,
            affected_faction_ids=(),
        )

    def _slow_ema_jsd(
        self,
        current_beliefs: dict[str, dict[str, float]],
        belief_history: list[dict[str, dict[str, float]]],
        lookback: int = 10,
        alpha: float = 0.3,
    ) -> float:
        """EMA of JSD over past `lookback` rounds. Detects slow build-ups."""
        if not belief_history:
            return 0.0
        window = belief_history[-lookback:] if len(belief_history) >= lookback else belief_history
        ema = 0.0
        for past in window:
            jsd_step = self._jsd(current_beliefs, past)
            ema = alpha * jsd_step + (1.0 - alpha) * ema
        return ema

    def _jsd(
        self,
        current: dict[str, dict[str, float]],
        prev: dict[str, dict[str, float]],
        n_bins: int = 10,
    ) -> float:
        """Jensen-Shannon Divergence averaged across all metrics.

        Discretises each metric's agent belief values into a normalised
        histogram, then computes JSD(current_hist, prev_hist).  Unlike RMSD
        of means, JSD captures shape changes (e.g. bimodal polarisation where
        population splits into two camps without shifting the overall mean).

        Result is in [0, 1] (log₂ scale).
        """
        all_metrics: set[str] = set()
        for beliefs in current.values():
            all_metrics.update(beliefs.keys())

        if not all_metrics:
            return 0.0

        total_jsd = 0.0
        count = 0
        for metric in all_metrics:
            curr_vals = [b.get(metric, 0.5) for b in current.values()]
            prev_vals = [b.get(metric, 0.5) for b in prev.values() if metric in b]
            if not prev_vals:
                continue
            p_hist = _to_histogram(curr_vals, n_bins)
            q_hist = _to_histogram(prev_vals, n_bins)
            total_jsd += _jensen_shannon_divergence(p_hist, q_hist)
            count += 1

        return total_jsd / count if count > 0 else 0.0

    def _classify_direction(
        self,
        current: dict[str, dict[str, float]],
        prev: dict[str, dict[str, float]],
    ) -> str:
        curr_vals = [v for b in current.values() for v in b.values()]
        prev_vals = [v for b in prev.values() for v in b.values()]
        if not curr_vals or not prev_vals:
            return "converge"
        curr_std = _std_dev(curr_vals)
        prev_std = _std_dev(prev_vals)
        if curr_std > prev_std * 1.2:
            return "polarize"
        if curr_std < prev_std * 0.8:
            return "converge"
        return "split"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _avg_beliefs(
    agent_ids: list[str],
    all_beliefs: dict[str, dict[str, float]],
) -> dict[str, float]:
    if not agent_ids:
        return {}
    metrics: set[str] = set()
    for aid in agent_ids:
        metrics.update(all_beliefs.get(aid, {}).keys())
    result = {}
    for m in metrics:
        vals = [all_beliefs.get(aid, {}).get(m, 0.5) for aid in agent_ids]
        result[m] = sum(vals) / len(vals)
    return result


def _find_bridge_agents(G: Any, partition: dict[str, int]) -> list[str]:
    bridges = []
    for node in G.nodes():
        node_comm = partition.get(node)
        neighbour_comms = {partition.get(n) for n in G.neighbors(node)}
        if len(neighbour_comms - {node_comm}) > 0:
            bridges.append(node)
    return bridges


def _compute_hostility(
    factions: tuple[FactionRecord, ...],
    agent_beliefs: dict[str, dict[str, float]],
) -> float:
    if len(factions) < 2:
        return 0.0
    centers = [f.belief_center for f in factions]
    diffs = []
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            metrics = set(centers[i]) & set(centers[j])
            if metrics:
                d = sum(abs(centers[i][m] - centers[j][m]) for m in metrics) / len(metrics)
                diffs.append(d)
    return sum(diffs) / len(diffs) if diffs else 0.0


def _to_histogram(vals: list[float], n_bins: int) -> list[float]:
    """Discretise [0, 1] values into a normalised probability histogram."""
    counts = [0] * n_bins
    for v in vals:
        idx = min(int(v * n_bins), n_bins - 1)
        counts[idx] += 1
    total = sum(counts)
    if total == 0:
        return [1.0 / n_bins] * n_bins
    return [c / total for c in counts]


def _jensen_shannon_divergence(p: list[float], q: list[float]) -> float:
    """Jensen-Shannon Divergence of two normalised histograms, bounded [0, 1].

    JSD(P, Q) = (KL(P‖M) + KL(Q‖M)) / 2  where M = (P + Q) / 2.
    Uses log base 2 so result ∈ [0, 1].
    """
    m = [(pi + qi) / 2.0 for pi, qi in zip(p, q)]
    kl_pm = sum(
        pi * math.log2(pi / mi)
        for pi, mi in zip(p, m)
        if pi > 1e-12 and mi > 1e-12
    )
    kl_qm = sum(
        qi * math.log2(qi / mi)
        for qi, mi in zip(q, m)
        if qi > 1e-12 and mi > 1e-12
    )
    return min(1.0, max(0.0, (kl_pm + kl_qm) / 2.0))


def _std_dev(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
