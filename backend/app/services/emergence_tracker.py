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
    """Run Louvain community detection on agent interaction graph."""

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
            from community import best_partition  # python-louvain
        except ImportError:
            logger.warning("FactionMapper: networkx/community not installed — returning single faction")
            return self._single_faction(simulation_id, round_number, agent_beliefs)

        G = nx.Graph()
        for agent_id, neighbours in interaction_graph.items():
            G.add_node(agent_id)
            for n in neighbours:
                G.add_edge(agent_id, n)

        if G.number_of_edges() == 0:
            return self._single_faction(simulation_id, round_number, agent_beliefs)

        partition = best_partition(G)
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

    def _compute_modularity(self, G: Any, partition: dict[str, int]) -> float:
        try:
            from community import modularity
            return modularity(partition, G)
        except Exception:
            return 0.0


# ---------------------------------------------------------------------------
# TippingPointDetector
# ---------------------------------------------------------------------------

class TippingPointDetector:
    """Detect sudden shifts in population-wide belief distribution."""

    def __init__(self, kl_threshold: float = 0.15) -> None:
        self._threshold = kl_threshold

    def detect(
        self,
        simulation_id: str,
        round_number: int,
        current_beliefs: dict[str, dict[str, float]],
        belief_history: list[dict[str, dict[str, float]]],
        last_event_id: str | None,
    ) -> TippingPoint | None:
        """Return TippingPoint if KL divergence exceeds threshold, else None."""
        if len(belief_history) < 1:
            return None

        # Compare to 3 rounds prior if available; else use earliest available
        prev = belief_history[-3] if len(belief_history) >= 3 else belief_history[0]
        kl = self._kl_divergence(current_beliefs, prev)

        if kl < self._threshold:
            return None

        direction = self._classify_direction(current_beliefs, prev)
        logger.info(
            "TippingPoint detected: round=%d kl=%.3f direction=%s",
            round_number, kl, direction,
        )
        return TippingPoint(
            simulation_id=simulation_id,
            round_number=round_number,
            trigger_event_id=last_event_id,
            kl_divergence=kl,
            change_direction=direction,
            affected_faction_ids=(),
        )

    def _kl_divergence(
        self,
        current: dict[str, dict[str, float]],
        prev: dict[str, dict[str, float]],
    ) -> float:
        """Compute average KL divergence across all metrics and agents."""
        all_metrics: set[str] = set()
        for beliefs in current.values():
            all_metrics.update(beliefs.keys())

        if not all_metrics:
            return 0.0

        total_kl = 0.0
        count = 0
        for metric in all_metrics:
            curr_vals = [b.get(metric, 0.5) for b in current.values()]
            prev_vals = [b.get(metric, 0.5) for b in prev.values() if metric in b]
            if not prev_vals:
                continue
            curr_mean = sum(curr_vals) / len(curr_vals)
            prev_mean = sum(prev_vals) / len(prev_vals)
            # Simple approximation: KL ~ squared difference of means
            total_kl += (curr_mean - prev_mean) ** 2
            count += 1

        return math.sqrt(total_kl / count) if count > 0 else 0.0

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


def _std_dev(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
