"""Virality scorer for Phase 2 Recommendation Engine.

Computes cascade depth, breadth, velocity, R₀, and cross-cluster reach
for each root post in a simulation session, then persists virality scores.
"""
from __future__ import annotations

import json
from typing import Any

from backend.app.models.recommendation import ViralityScore
from backend.app.utils.logger import get_logger

logger = get_logger("virality_scorer")


class ViralityScorer:
    """Computes virality metrics for posts using cascade tracking data.

    Uses the parent_action_id / spread_depth columns that were added in
    Phase 17 (action_logger.py).  Falls back gracefully when cascade data
    is absent.
    """

    async def score_posts(
        self,
        session_id: str,
        round_number: int,
        db: Any,
    ) -> list[ViralityScore]:
        """Score all root posts with cascade virality metrics.

        Args:
            session_id: Simulation session UUID.
            round_number: Current simulation round (upper bound for search).
            db: Aiosqlite database connection.

        Returns:
            List of ViralityScore objects for all root posts.
        """
        # Load root posts (parent_action_id IS NULL)
        cursor = await db.execute(
            """SELECT id, agent_id, round_number
               FROM simulation_actions
               WHERE session_id = ?
                 AND (parent_action_id IS NULL OR parent_action_id = 0)
                 AND action_type IN ('create_post','post')
               ORDER BY id""",
            (session_id,),
        )
        root_rows = await cursor.fetchall()

        if not root_rows:
            return []

        # Load all cascade data in one query: all actions with parent chain info
        cursor = await db.execute(
            """SELECT id, agent_id, round_number,
                      COALESCE(parent_action_id, 0) AS parent_id,
                      COALESCE(spread_depth, 0) AS depth
               FROM simulation_actions
               WHERE session_id = ?
                 AND action_type IN ('create_post','post','repost','quote_post')
               ORDER BY id""",
            (session_id,),
        )
        all_rows = await cursor.fetchall()

        # Build parent→children map and action details
        children: dict[int, list[int]] = {}
        action_details: dict[int, dict[str, Any]] = {}
        for row in all_rows:
            action_id = int(row[0])
            agent_id = int(row[1])
            rnd = int(row[2])
            parent_id = int(row[3])
            depth = int(row[4])
            action_details[action_id] = {
                "agent_id": agent_id,
                "round_number": rnd,
                "depth": depth,
            }
            if parent_id > 0:
                children.setdefault(parent_id, []).append(action_id)

        # Load cluster assignments from latest echo chamber snapshot
        cluster_map = await self._load_clusters(session_id, db)
        total_clusters = max(1, len(set(cluster_map.values())))

        scores: list[ViralityScore] = []
        for root_row in root_rows:
            root_id = int(root_row[0])
            root_round = int(root_row[2])

            if root_id not in action_details:
                continue

            # BFS to gather all cascade nodes
            cascade_agents: set[int] = set()
            cascade_agents.add(int(root_row[1]))
            max_depth = 0

            queue = [root_id]
            visited: set[int] = {root_id}
            while queue:
                current = queue.pop(0)
                for child_id in children.get(current, []):
                    if child_id not in visited:
                        visited.add(child_id)
                        child = action_details.get(child_id, {})
                        if child:
                            cascade_agents.add(child["agent_id"])
                            max_depth = max(max_depth, child["depth"])
                        queue.append(child_id)

            cascade_breadth = len(cascade_agents) - 1  # exclude root author
            cascade_breadth = max(0, cascade_breadth)
            cascade_depth = max_depth

            # Velocity: breadth / rounds elapsed
            rounds_elapsed = max(1, round_number - root_round)
            velocity = cascade_breadth / rounds_elapsed

            # Reproduction number: breadth / exposed count (estimate)
            # Use cascade breadth / total agents in session as R₀ proxy
            total_agents_cursor = await db.execute(
                "SELECT COUNT(*) FROM agent_profiles WHERE session_id = ?",
                (session_id,),
            )
            total_row = await total_agents_cursor.fetchone()
            total_agents = int(total_row[0]) if total_row else 1
            reproduction_number = cascade_breadth / max(1, total_agents) * 10.0

            # Cross-cluster reach: distinct clusters among cascade agents
            reached_clusters: set[int] = set()
            for agent_id in cascade_agents:
                username = str(agent_id)
                if username in cluster_map:
                    reached_clusters.add(cluster_map[username])
            cross_cluster_reach = len(reached_clusters) / total_clusters

            # Virality index composite formula
            # Normalize velocity (cap at 10 breadth/round → 1.0)
            velocity_norm = min(1.0, velocity / 10.0)
            # Normalize R₀ (cap at 1.0)
            r0_norm = min(1.0, reproduction_number)
            virality_index = (
                0.3 * velocity_norm
                + 0.3 * r0_norm
                + 0.4 * cross_cluster_reach
            )

            scores.append(ViralityScore(
                post_id=str(root_id),
                session_id=session_id,
                cascade_depth=cascade_depth,
                cascade_breadth=cascade_breadth,
                velocity=round(velocity, 4),
                reproduction_number=round(reproduction_number, 4),
                cross_cluster_reach=round(cross_cluster_reach, 4),
                virality_index=round(virality_index, 4),
            ))

        return scores

    async def persist_scores(
        self,
        session_id: str,
        scores: list[ViralityScore],
        db: Any,
    ) -> None:
        """Upsert virality scores into the DB.

        Uses ON CONFLICT to update metrics on re-run so scores are always
        current without creating duplicates.

        Args:
            session_id: Simulation session UUID.
            scores: List of ViralityScore objects.
            db: Aiosqlite database connection.
        """
        if not scores:
            return

        rows = [
            (
                s.session_id,
                s.post_id,
                s.cascade_depth,
                s.cascade_breadth,
                s.velocity,
                s.reproduction_number,
                s.cross_cluster_reach,
                s.virality_index,
            )
            for s in scores
        ]
        await db.executemany(
            """INSERT INTO virality_scores
               (session_id, post_id, cascade_depth, cascade_breadth,
                velocity, reproduction_number, cross_cluster_reach, virality_index)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(session_id, post_id) DO UPDATE SET
                 cascade_depth=excluded.cascade_depth,
                 cascade_breadth=excluded.cascade_breadth,
                 velocity=excluded.velocity,
                 reproduction_number=excluded.reproduction_number,
                 cross_cluster_reach=excluded.cross_cluster_reach,
                 virality_index=excluded.virality_index""",
            rows,
        )
        await db.commit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_clusters(
        self, session_id: str, db: Any
    ) -> dict[str, int]:
        """Load agent → cluster mapping from latest echo chamber snapshot."""
        try:
            cursor = await db.execute(
                "SELECT agent_to_cluster_json FROM echo_chamber_snapshots "
                "WHERE session_id = ? ORDER BY round_number DESC LIMIT 1",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row and row[0]:
                data = json.loads(row[0])
                return {str(k): int(v) for k, v in data.items()}
        except Exception:
            pass
        return {}
