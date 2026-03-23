"""Network evolution engine: detects structural changes in the social network.

Phase 1C: Dynamic Network Evolution.

Analyses trust score deltas between rounds to identify:
- TIE_FORMED: trust crosses the formation threshold
- TIE_DISSOLVED: trust drops below the dissolution threshold
- BRIDGE_DETECTED: agent bridges two or more distinct clusters
- TRIADIC_CLOSURE: A→B + B→C → A→C closure opportunity
- CLUSTER_SHIFT: agent moved to a different cluster
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from backend.app.models.network_evolution import NetworkEvent, NetworkEvolutionStats
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("network_evolution")

# Project root is 4 levels up from this file:
# services → app → backend → project_root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class NetworkEvolutionEngine:
    """Detects structural changes in the social network per round.

    Maintains a per-session cache of previous trust scores so that
    deltas can be computed without an extra DB query.
    """

    TIE_FORM_THRESHOLD: float = 0.3
    TIE_DISSOLVE_THRESHOLD: float = -0.1
    TRIADIC_SAMPLE_LIMIT: int = 50
    STANCE_SIMILARITY_THRESHOLD: float = 0.7

    def __init__(self) -> None:
        # session_id → dict[(agent_a_id, agent_b_id) → trust_score]
        self._prev_trusts: dict[str, dict[tuple[int, int], float]] = {}
        # session_id → dict[agent_username → cluster_id] (previous round)
        self._prev_clusters: dict[str, dict[str, int]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def detect_events(
        self,
        session_id: str,
        round_number: int,
        previous_trusts: dict[tuple[int, int], float],
        current_trusts: dict[tuple[int, int], float],
        cluster_assignments: dict[str, int],
    ) -> tuple[list[NetworkEvent], NetworkEvolutionStats]:
        """Compare trust snapshots to detect structural network events.

        Args:
            session_id: Simulation session UUID.
            round_number: Current simulation round.
            previous_trusts: Trust scores from the previous round.
            current_trusts: Trust scores from the current round.
            cluster_assignments: Mapping of agent_username → cluster_id.

        Returns:
            Tuple of (events list, aggregate stats).
        """
        events: list[NetworkEvent] = []

        # 1. TIE_FORMED / TIE_DISSOLVED from trust deltas
        for pair, curr_score in current_trusts.items():
            prev_score = previous_trusts.get(pair, 0.0)
            agent_a_id, agent_b_id = pair

            if prev_score < self.TIE_FORM_THRESHOLD <= curr_score:
                events.append(
                    NetworkEvent(
                        session_id=session_id,
                        round_number=round_number,
                        event_type="TIE_FORMED",
                        agent_a_username=str(agent_a_id),
                        agent_b_username=str(agent_b_id),
                        trust_delta=round(curr_score - prev_score, 4),
                        details={"prev": prev_score, "curr": curr_score},
                    )
                )
            elif prev_score >= self.TIE_DISSOLVE_THRESHOLD > curr_score:
                events.append(
                    NetworkEvent(
                        session_id=session_id,
                        round_number=round_number,
                        event_type="TIE_DISSOLVED",
                        agent_a_username=str(agent_a_id),
                        agent_b_username=str(agent_b_id),
                        trust_delta=round(curr_score - prev_score, 4),
                        details={"prev": prev_score, "curr": curr_score},
                    )
                )

        # 2. BRIDGE_DETECTED: agent has edges to agents in ≥2 different clusters
        adjacency: dict[str, set[str]] = {}
        for (a_id, b_id), score in current_trusts.items():
            if score >= self.TIE_FORM_THRESHOLD:
                adjacency.setdefault(str(a_id), set()).add(str(b_id))
                adjacency.setdefault(str(b_id), set()).add(str(a_id))

        for agent_name, neighbors in adjacency.items():
            neighbor_clusters = {cluster_assignments[n] for n in neighbors if n in cluster_assignments}
            if len(neighbor_clusters) >= 2:
                events.append(
                    NetworkEvent(
                        session_id=session_id,
                        round_number=round_number,
                        event_type="BRIDGE_DETECTED",
                        agent_a_username=agent_name,
                        details={"clusters_bridged": list(neighbor_clusters)},
                    )
                )

        # 3. TRIADIC_CLOSURE: sample A→B + B→C pairs, suggest A→C
        triadic_events = await self._detect_triadic_closures(
            session_id,
            round_number,
            current_trusts,
            cluster_assignments,
        )
        events.extend(triadic_events)

        # 4. CLUSTER_SHIFT: agent moved to a different cluster
        prev_clusters = self._prev_clusters.get(session_id, {})
        for agent_name, curr_cluster in cluster_assignments.items():
            prev_cluster = prev_clusters.get(agent_name)
            if prev_cluster is not None and prev_cluster != curr_cluster:
                events.append(
                    NetworkEvent(
                        session_id=session_id,
                        round_number=round_number,
                        event_type="CLUSTER_SHIFT",
                        agent_a_username=agent_name,
                        details={"from_cluster": prev_cluster, "to_cluster": curr_cluster},
                    )
                )

        # Update previous cluster cache
        self._prev_clusters[session_id] = dict(cluster_assignments)

        # Compute aggregate stats
        stats = self._compute_stats(
            session_id,
            round_number,
            events,
            current_trusts,
        )
        return events, stats

    async def persist_events(
        self,
        session_id: str,
        events: list[NetworkEvent],
    ) -> None:
        """Persist network events to the DB.

        Args:
            session_id: Simulation session UUID.
            events: List of NetworkEvent objects to persist.
        """
        if not events:
            return

        rows = [
            (
                e.session_id,
                e.round_number,
                e.event_type,
                e.agent_a_username,
                e.agent_b_username,
                e.trust_delta,
                json.dumps(e.details),
            )
            for e in events
        ]
        async with get_db() as db:
            await db.executemany(
                """INSERT INTO network_events
                   (session_id, round_number, event_type,
                    agent_a_username, agent_b_username, trust_delta, details_json)
                   VALUES (?,?,?,?,?,?,?)""",
                rows,
            )
            await db.commit()

    async def get_events(
        self,
        session_id: str,
        round_number: int | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[NetworkEvent]:
        """Retrieve stored network events with optional filters.

        Args:
            session_id: Simulation session UUID.
            round_number: If provided, only return events for that round.
            event_type: If provided, filter by event type.
            limit: Maximum number of events to return.

        Returns:
            List of NetworkEvent objects.
        """
        conditions = ["session_id = ?"]
        params: list[Any] = [session_id]

        if round_number is not None:
            conditions.append("round_number = ?")
            params.append(round_number)
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)

        params.append(limit)
        where = " AND ".join(conditions)
        sql = (
            f"SELECT session_id, round_number, event_type, "
            f"agent_a_username, agent_b_username, trust_delta, details_json "
            f"FROM network_events WHERE {where} "
            f"ORDER BY id DESC LIMIT ?"
        )

        async with get_db() as db:
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()

        return [
            NetworkEvent(
                session_id=r[0],
                round_number=r[1],
                event_type=r[2],
                agent_a_username=r[3],
                agent_b_username=r[4],
                trust_delta=r[5],
                details=json.loads(r[6]) if r[6] else {},
            )
            for r in rows
        ]

    async def write_network_patch(
        self,
        session_id: str,
        triadic_closures: list[NetworkEvent],
    ) -> None:
        """Write suggested follows to data/sessions/{session_id}/network_patch.json.

        The OASIS subprocess reads and deletes this file before the next round
        to inject follow actions into the simulation.

        Args:
            session_id: Simulation session UUID.
            triadic_closures: TRIADIC_CLOSURE events with suggested follows.
        """
        if not triadic_closures:
            return

        session_dir = _PROJECT_ROOT / "data" / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        patch_path = session_dir / "network_patch.json"

        suggested = [
            {
                "follower": e.agent_a_username,
                "followee": e.details.get("suggested_followee", e.agent_b_username),
                "round_number": e.round_number,
            }
            for e in triadic_closures
        ]
        patch_data = {"suggested_follows": suggested}
        patch_path.write_text(json.dumps(patch_data, ensure_ascii=False), encoding="utf-8")
        logger.debug(
            "write_network_patch: %d suggestions for session=%s",
            len(suggested),
            session_id,
        )

    async def load_current_trusts(self, session_id: str) -> dict[tuple[int, int], float]:
        """Load current trust scores from DB for a session.

        Args:
            session_id: Simulation session UUID.

        Returns:
            Dict mapping (agent_a_id, agent_b_id) → trust_score.
        """
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT agent_a_id, agent_b_id, trust_score FROM agent_relationships WHERE session_id = ?",
                (session_id,),
            )
            rows = await cursor.fetchall()

        return {(int(r[0]), int(r[1])): float(r[2]) for r in rows}

    async def load_cluster_assignments(self, session_id: str) -> dict[str, int]:
        """Load cluster assignments from latest echo_chamber_snapshots row.

        Args:
            session_id: Simulation session UUID.

        Returns:
            Dict mapping agent_username → cluster_id.
        """
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT agent_to_cluster_json FROM echo_chamber_snapshots "
                "WHERE session_id = ? ORDER BY round_number DESC LIMIT 1",
                (session_id,),
            )
            row = await cursor.fetchone()

        if not row or not row[0]:
            return {}

        try:
            data = json.loads(row[0])
            return {str(k): int(v) for k, v in data.items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _detect_triadic_closures(
        self,
        session_id: str,
        round_number: int,
        current_trusts: dict[tuple[int, int], float],
        cluster_assignments: dict[str, int],
    ) -> list[NetworkEvent]:
        """Detect triadic closure opportunities (A→B + B→C, A→C missing).

        Samples up to TRIADIC_SAMPLE_LIMIT pairs to avoid O(n³) complexity.
        """
        # Build strong positive edges set
        strong_edges: set[tuple[str, str]] = set()
        for (a_id, b_id), score in current_trusts.items():
            if score >= self.TIE_FORM_THRESHOLD:
                strong_edges.add((str(a_id), str(b_id)))

        # Enumerate all A→B + B→C paths
        candidates: list[tuple[str, str, str]] = []
        for a, b in strong_edges:
            for bb, c in strong_edges:
                if bb == b and c != a and (a, c) not in strong_edges:
                    candidates.append((a, b, c))
                    if len(candidates) >= self.TRIADIC_SAMPLE_LIMIT * 3:
                        break
            if len(candidates) >= self.TRIADIC_SAMPLE_LIMIT * 3:
                break

        # Sample
        if len(candidates) > self.TRIADIC_SAMPLE_LIMIT:
            candidates = random.sample(candidates, self.TRIADIC_SAMPLE_LIMIT)

        # Load political stances for stance similarity check
        stances = await self._load_stances(session_id)

        events: list[NetworkEvent] = []
        for a, b, c in candidates:
            stance_a = stances.get(a, 0.5)
            stance_c = stances.get(c, 0.5)
            similarity = 1.0 - abs(stance_a - stance_c)
            if similarity >= self.STANCE_SIMILARITY_THRESHOLD:
                events.append(
                    NetworkEvent(
                        session_id=session_id,
                        round_number=round_number,
                        event_type="TRIADIC_CLOSURE",
                        agent_a_username=a,
                        agent_b_username=b,
                        details={
                            "suggested_followee": c,
                            "stance_similarity": round(similarity, 4),
                            "via_agent": b,
                        },
                    )
                )

        return events

    async def _load_stances(self, session_id: str) -> dict[str, float]:
        """Load agent political stances keyed by agent_id string."""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, political_stance FROM agent_profiles WHERE session_id = ? AND political_stance IS NOT NULL",
                (session_id,),
            )
            rows = await cursor.fetchall()
        return {str(r[0]): float(r[1]) for r in rows}

    def _compute_stats(
        self,
        session_id: str,
        round_number: int,
        events: list[NetworkEvent],
        current_trusts: dict[tuple[int, int], float],
    ) -> NetworkEvolutionStats:
        """Compute aggregate statistics from the detected events."""
        ties_formed = sum(1 for e in events if e.event_type == "TIE_FORMED")
        ties_dissolved = sum(1 for e in events if e.event_type == "TIE_DISSOLVED")
        bridges = sum(1 for e in events if e.event_type == "BRIDGE_DETECTED")
        triadic = sum(1 for e in events if e.event_type == "TRIADIC_CLOSURE")
        shifts = sum(1 for e in events if e.event_type == "CLUSTER_SHIFT")

        n_edges = len(current_trusts)
        avg_trust = sum(current_trusts.values()) / n_edges if n_edges > 0 else 0.0

        # Compute density: unique agent IDs
        agent_ids: set[int] = set()
        for a_id, b_id in current_trusts:
            agent_ids.add(a_id)
            agent_ids.add(b_id)
        n_agents = len(agent_ids)
        max_edges = n_agents * (n_agents - 1) if n_agents > 1 else 1
        density = n_edges / max_edges if max_edges > 0 else 0.0

        return NetworkEvolutionStats(
            session_id=session_id,
            round_number=round_number,
            ties_formed=ties_formed,
            ties_dissolved=ties_dissolved,
            bridges_detected=bridges,
            triadic_closures=triadic,
            cluster_shifts=shifts,
            density=round(density, 6),
            avg_trust=round(avg_trust, 4),
        )
