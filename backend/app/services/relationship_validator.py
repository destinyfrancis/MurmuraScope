# backend/app/services/relationship_validator.py
"""Relationship network structural validator.

Checks two network-science constraints on the agent relationship graph:

1. **Dunbar constraint** — Cognitive capacity limits meaningful relationships to
   ~150 (Dunbar's number), with ~15 close ties.  We check that the *average*
   degree of "meaningful" relationships (interaction_count ≥ threshold) stays
   at or below 15.

2. **Small-world property** — Real social networks exhibit clustering coefficients
   far higher than random graphs of the same size and density, combined with
   short average path lengths comparable to random graphs.  We compare against
   an Erdős-Rényi baseline with the same n and p.

Usage::

    validator = RelationshipValidator()
    result = await validator.validate(session_id)
    if result.dunbar_violation:
        logger.warning("Avg meaningful degree %s exceeds Dunbar limit", result.avg_meaningful_degree)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger(__name__)

_DUNBAR_MEANINGFUL_MIN_INTERACTIONS = 3   # edges with count >= this are "meaningful"
_DUNBAR_LIMIT = 15.0                       # avg meaningful degree threshold
_SMALL_WORLD_CC_RATIO = 2.0               # CC must be ≥ 2× random baseline
_SMALL_WORLD_APL_RATIO = 2.0              # APL must be ≤ 2× random baseline


@dataclass(frozen=True)
class RelationshipValidationResult:
    """Result of relationship network structural validation."""
    session_id: str
    n_agents: int
    n_edges: int
    avg_meaningful_degree: float
    dunbar_violation: bool           # True when avg_meaningful_degree > _DUNBAR_LIMIT
    clustering_coefficient: float    # global transitivity of the relationship graph
    avg_path_length: float           # mean shortest path length (sampled if large)
    random_cc_baseline: float        # expected CC for Erdős-Rényi(n, p)
    random_apl_baseline: float       # expected APL for Erdős-Rényi(n, p)
    small_world_cc_ok: bool          # True when CC ≥ 2× random baseline
    small_world_apl_ok: bool         # True when APL ≤ 2× random baseline
    summary: str


class RelationshipValidator:
    """Validate structural properties of the agent relationship network."""

    async def validate(
        self,
        session_id: str,
        meaningful_min_interactions: int = _DUNBAR_MEANINGFUL_MIN_INTERACTIONS,
        dunbar_limit: float = _DUNBAR_LIMIT,
    ) -> RelationshipValidationResult:
        """Run Dunbar + small-world checks on the relationship network.

        Args:
            session_id: Simulation session to validate.
            meaningful_min_interactions: Minimum interaction_count for an edge
                to count as "meaningful" in the Dunbar check.
            dunbar_limit: Maximum allowed average meaningful degree.

        Returns:
            RelationshipValidationResult with all metrics and flags.
        """
        edges = await self._load_edges(session_id)
        return self._compute(
            session_id, edges,
            meaningful_min_interactions=meaningful_min_interactions,
            dunbar_limit=dunbar_limit,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_edges(
        self, session_id: str
    ) -> list[tuple[str, str, int]]:
        """Load (agent_id_a, agent_id_b, interaction_count) from DB."""
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT agent_id_a, agent_id_b, interaction_count
                FROM agent_relationships
                WHERE session_id = ?
                  AND round_number = -1
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()
        return [(r[0], r[1], int(r[2])) for r in rows]

    def _compute(
        self,
        session_id: str,
        edges: list[tuple[str, str, int]],
        meaningful_min_interactions: int,
        dunbar_limit: float,
    ) -> RelationshipValidationResult:
        """Pure computation — no DB calls."""
        try:
            import networkx as nx  # noqa: PLC0415
        except ImportError:
            logger.error("networkx not installed — RelationshipValidator unavailable")
            return _empty_result(session_id, "networkx not installed")

        # Build undirected graph
        G = nx.Graph()
        for a, b, count in edges:
            G.add_edge(a, b, weight=count)

        n = G.number_of_nodes()
        m = G.number_of_edges()

        if n == 0:
            return _empty_result(session_id, "No relationship data found.")

        # --- Dunbar check ---
        meaningful_degrees = [
            sum(1 for _, _, d in G.edges(node, data=True)
                if d.get("weight", 0) >= meaningful_min_interactions)
            for node in G.nodes()
        ]
        avg_meaningful = sum(meaningful_degrees) / n if n > 0 else 0.0
        dunbar_violation = avg_meaningful > dunbar_limit

        # --- Clustering coefficient ---
        cc = nx.transitivity(G)  # global triangles-based clustering

        # --- Average path length (sample if large) ---
        apl = _sampled_avg_path_length(G, sample_size=500)

        # --- Erdős-Rényi baselines ---
        p_random = (2 * m) / (n * (n - 1)) if n > 1 else 0.0
        random_cc = p_random                                      # E[CC] ≈ p for ER
        # E[APL] ≈ ln(n) / ln(n*p) for connected ER
        random_apl = (
            math.log(n) / math.log(max(n * p_random, 2))
            if n > 1 and p_random > 0
            else 1.0
        )

        # --- Small-world checks ---
        sw_cc_ok = cc >= _SMALL_WORLD_CC_RATIO * random_cc if random_cc > 0 else False
        sw_apl_ok = apl <= _SMALL_WORLD_APL_RATIO * random_apl if apl > 0 else True

        summary_parts = [
            f"n={n} agents, {m} edges.",
            f"Avg meaningful degree={avg_meaningful:.2f} "
            f"({'VIOLATION' if dunbar_violation else 'ok'}, limit={dunbar_limit}).",
            f"CC={cc:.3f} (random={random_cc:.3f}, {'ok' if sw_cc_ok else 'low'}).",
            f"APL={apl:.2f} (random={random_apl:.2f}, {'ok' if sw_apl_ok else 'high'}).",
        ]
        summary = " ".join(summary_parts)

        return RelationshipValidationResult(
            session_id=session_id,
            n_agents=n,
            n_edges=m,
            avg_meaningful_degree=round(avg_meaningful, 3),
            dunbar_violation=dunbar_violation,
            clustering_coefficient=round(cc, 4),
            avg_path_length=round(apl, 4),
            random_cc_baseline=round(random_cc, 4),
            random_apl_baseline=round(random_apl, 4),
            small_world_cc_ok=sw_cc_ok,
            small_world_apl_ok=sw_apl_ok,
            summary=summary,
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _sampled_avg_path_length(G, sample_size: int = 500) -> float:
    """Estimate average shortest path length via random node sampling.

    For disconnected graphs, only considers the largest connected component.
    """
    import networkx as nx  # noqa: PLC0415

    if G.number_of_nodes() == 0:
        return 0.0

    # Use largest connected component
    largest_cc = max(nx.connected_components(G), key=len)
    sub = G.subgraph(largest_cc)

    if sub.number_of_nodes() <= 1:
        return 0.0

    import random as _random  # noqa: PLC0415

    nodes = list(sub.nodes())
    if len(nodes) <= sample_size:
        # Small graph — compute exactly
        try:
            return nx.average_shortest_path_length(sub)
        except nx.NetworkXError:
            return 0.0

    # Sample node pairs
    total = 0.0
    count = 0
    sampled_nodes = _random.sample(nodes, min(sample_size, len(nodes)))
    for src in sampled_nodes:
        lengths = nx.single_source_shortest_path_length(sub, src)
        for tgt, d in lengths.items():
            if tgt != src:
                total += d
                count += 1

    return total / count if count > 0 else 0.0


def _empty_result(session_id: str, reason: str) -> RelationshipValidationResult:
    return RelationshipValidationResult(
        session_id=session_id,
        n_agents=0,
        n_edges=0,
        avg_meaningful_degree=0.0,
        dunbar_violation=False,
        clustering_coefficient=0.0,
        avg_path_length=0.0,
        random_cc_baseline=0.0,
        random_apl_baseline=0.0,
        small_world_cc_ok=False,
        small_world_apl_ok=False,
        summary=reason,
    )
