"""Agent social network builder with echo chamber detection.

Constructs a social network from agent profiles at session creation time:
- Same district → neighbor relationship
- Same occupation → colleague relationship
- High extraversion → opinion_leader

Influence weights are updated dynamically as opinion leaders post.

Echo chamber detection uses trust-weighted Louvain-style community detection
to partition agents into clusters. Cross-cluster posts from distrusted agents
receive dampened salience to simulate algorithmic filter bubbles.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import aiosqlite

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("social_network")

_EXTRAVERSION_OPINION_LEADER_THRESHOLD = 0.7
_NEIGHBOR_INFLUENCE_WEIGHT = 0.8
_COLLEAGUE_INFLUENCE_WEIGHT = 0.7
_FOLLOWER_INFLUENCE_WEIGHT = 0.5

# Echo chamber constants
_MODULARITY_RESOLUTION = 1.0  # Louvain resolution parameter
_MAX_LOUVAIN_ITERATIONS = 50
_CROSS_CLUSTER_DAMPENING = 0.3  # Salience multiplier for cross-cluster distrusted posts


@dataclass(frozen=True)
class AgentRelationship:
    """Immutable relationship between two agents."""

    session_id: str
    agent_a_id: int
    agent_b_id: int
    relationship_type: str
    influence_weight: float
    trust_score: float = 0.0  # Dynamic trust score [-1.0, +1.0]


@dataclass(frozen=True)
class EchoChamber:
    """Immutable echo chamber cluster."""

    cluster_id: int
    agent_ids: tuple[int, ...]
    avg_trust: float
    size: int


@dataclass(frozen=True)
class EchoChamberResult:
    """Immutable result of echo chamber detection."""

    session_id: str
    chambers: tuple[EchoChamber, ...]
    agent_to_cluster: dict[int, int]
    modularity: float
    num_clusters: int


@dataclass(frozen=True)
class PolarizationResult:
    """Immutable polarization measurement."""

    polarization_index: float  # 0-1, higher = more polarized
    modularity: float
    opinion_variance: float
    cross_cluster_hostility: float
    cluster_stances: dict[str, float]  # cluster_id → avg political stance
    round_number: int


@dataclass(frozen=True)
class SocialNetwork:
    """Immutable snapshot of a session's social network."""

    session_id: str
    relationships: tuple[AgentRelationship, ...]
    opinion_leaders: tuple[int, ...]
    total_agents: int

    @property
    def edge_count(self) -> int:
        return len(self.relationships)


class SocialNetworkBuilder:
    """Build and manage agent social networks."""

    async def build_network(
        self,
        session_id: str,
        profiles: list[dict],
    ) -> SocialNetwork:
        """Build social network from agent profiles.

        Rules:
        1. Same district → neighbor (bidirectional)
        2. Same occupation → colleague (bidirectional)
        3. High extraversion (>= 0.7) → opinion_leader (one-to-many follow)

        Args:
            session_id: Session UUID.
            profiles: List of agent profile dicts (from agent_profiles table).

        Returns:
            Immutable SocialNetwork.
        """
        if not profiles:
            return SocialNetwork(
                session_id=session_id,
                relationships=(),
                opinion_leaders=(),
                total_agents=0,
            )

        relationships: list[AgentRelationship] = []
        opinion_leaders: list[int] = []

        # Index profiles by id
        by_district: dict[str, list[int]] = {}
        by_occupation: dict[str, list[int]] = {}

        for p in profiles:
            agent_id = p.get("id") or p.get("agent_id")
            district = p.get("district", "")
            occupation = p.get("occupation", "")
            extraversion = float(p.get("extraversion", 0.5))

            if district:
                by_district.setdefault(district, []).append(agent_id)
            if occupation:
                by_occupation.setdefault(occupation, []).append(agent_id)
            if extraversion >= _EXTRAVERSION_OPINION_LEADER_THRESHOLD:
                opinion_leaders.append(agent_id)

        # Build neighbor relationships (same district)
        for district, agent_ids in by_district.items():
            for i in range(len(agent_ids)):
                for j in range(i + 1, min(i + 11, len(agent_ids))):
                    # Limit neighbors to 10 per agent for performance
                    a, b = agent_ids[i], agent_ids[j]
                    relationships.append(
                        AgentRelationship(
                            session_id=session_id,
                            agent_a_id=a,
                            agent_b_id=b,
                            relationship_type="neighbor",
                            influence_weight=_NEIGHBOR_INFLUENCE_WEIGHT,
                        )
                    )

        # Build colleague relationships (same occupation, max 15 per agent)
        for occupation, agent_ids in by_occupation.items():
            for i in range(len(agent_ids)):
                for j in range(i + 1, min(i + 16, len(agent_ids))):
                    a, b = agent_ids[i], agent_ids[j]
                    # Avoid duplicating neighbor relationships
                    relationships.append(
                        AgentRelationship(
                            session_id=session_id,
                            agent_a_id=a,
                            agent_b_id=b,
                            relationship_type="colleague",
                            influence_weight=_COLLEAGUE_INFLUENCE_WEIGHT,
                        )
                    )

        # Opinion leader follow relationships (others follow leaders)
        non_leaders = [
            p.get("id") or p.get("agent_id")
            for p in profiles
            if (p.get("id") or p.get("agent_id")) not in set(opinion_leaders)
        ]
        for leader_id in opinion_leaders:
            # Each opinion leader is followed by up to 20 non-leaders
            for follower_id in non_leaders[:20]:
                relationships.append(
                    AgentRelationship(
                        session_id=session_id,
                        agent_a_id=leader_id,
                        agent_b_id=follower_id,
                        relationship_type="opinion_leader",
                        influence_weight=_FOLLOWER_INFLUENCE_WEIGHT,
                    )
                )

        # Persist to DB
        rows = [
            (r.session_id, r.agent_a_id, r.agent_b_id, r.relationship_type, r.influence_weight) for r in relationships
        ]
        if rows:
            try:
                async with get_db() as db:
                    # Ignore duplicate pairs (unique index)
                    await db.executemany(
                        """
                        INSERT OR IGNORE INTO agent_relationships
                            (session_id, agent_a_id, agent_b_id,
                             relationship_type, influence_weight)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    await db.commit()
                logger.info(
                    "Social network built: session=%s, %d relationships, %d leaders",
                    session_id,
                    len(rows),
                    len(opinion_leaders),
                )
            except Exception:
                logger.exception("build_network DB insert failed session=%s", session_id)

        return SocialNetwork(
            session_id=session_id,
            relationships=tuple(relationships),
            opinion_leaders=tuple(opinion_leaders),
            total_agents=len(profiles),
        )

    async def propagate_influence(
        self,
        session_id: str,
        round_number: int,
        opinion_leader_posts: dict[int, list[str]],
    ) -> int:
        """Boost memory salience for followers of active opinion leaders.

        Args:
            session_id: Session UUID.
            round_number: Current round.
            opinion_leader_posts: Dict mapping leader agent_id → list of posts.

        Returns:
            Number of follower memories boosted.
        """
        if not opinion_leader_posts:
            return 0

        try:
            async with get_db() as db:
                # Batch-load all follower relationships for all leaders at once
                # instead of one SELECT per leader (N+1 → 1 query)
                if not opinion_leader_posts:
                    return 0

                placeholders = ",".join("?" for _ in opinion_leader_posts)
                cursor = await db.execute(
                    f"""
                    SELECT agent_a_id, agent_b_id,
                           COALESCE(trust_score, 0.0) AS trust_score
                    FROM agent_relationships
                    WHERE session_id = ?
                      AND agent_a_id IN ({placeholders})
                      AND relationship_type = 'opinion_leader'
                    """,
                    (session_id, *opinion_leader_posts),
                )
                follower_rows = await cursor.fetchall()

                # Compute boost factors per follower (in Python, zero extra queries)
                follower_ids = [int(row[1]) for row in follower_rows]

                # Pre-query MAX(round_number) per follower agent in one batch query
                # to eliminate the per-row subquery in the UPDATE.
                max_round_map: dict[int, int] = {}
                if follower_ids:
                    placeholders = ",".join("?" for _ in follower_ids)
                    max_cursor = await db.execute(
                        f"""
                        SELECT agent_id, MAX(round_number) AS max_round
                        FROM agent_memories
                        WHERE session_id = ? AND agent_id IN ({placeholders})
                        GROUP BY agent_id
                        """,
                        (session_id, *follower_ids),
                    )
                    for mr_row in await max_cursor.fetchall():
                        max_round_map[int(mr_row[0])] = int(mr_row[1])

                update_rows: list[tuple] = []
                for row in follower_rows:
                    follower_id = int(row[1])
                    trust = float(row[2]) if row[2] is not None else 0.0
                    # Scale salience boost by trust:
                    #   trust=0.0 → 1.2x (unchanged baseline)
                    #   trust=1.0 → 1.56x (more trusted leader)
                    #   trust=-1.0 → 0.84x (distrusted leader)
                    boost_factor = 1.2 * (1.0 + trust * 0.3)
                    max_round = max_round_map.get(follower_id)
                    if max_round is None:
                        continue  # No memories for this follower yet — skip
                    update_rows.append((boost_factor, session_id, follower_id, max_round))

                if update_rows:
                    await db.executemany(
                        """
                        UPDATE agent_memories
                        SET salience_score = MIN(1.0, salience_score * ?)
                        WHERE session_id = ?
                          AND agent_id = ?
                          AND round_number = ?
                        """,
                        update_rows,
                    )
                await db.commit()
                return len(update_rows)
        except Exception:
            logger.exception("propagate_influence failed session=%s round=%d", session_id, round_number)
            return 0

    async def detect_echo_chambers(
        self,
        session_id: str,
    ) -> EchoChamberResult:
        """Detect echo chambers using trust-weighted Louvain community detection.

        Uses trust_score as edge weights to partition agents into clusters.
        Positive trust strengthens intra-community bonds; negative trust signals
        community boundaries.

        Args:
            session_id: Session UUID.

        Returns:
            Immutable EchoChamberResult with cluster assignments and modularity.
        """
        try:
            async with get_db() as db:
                # Load all relationships with trust scores
                cursor = await db.execute(
                    """
                    SELECT agent_a_id, agent_b_id,
                           COALESCE(trust_score, 0.0) AS trust_score,
                           influence_weight
                    FROM agent_relationships
                    WHERE session_id = ?
                    """,
                    (session_id,),
                )
                edge_rows = await cursor.fetchall()

                # Load all agent IDs for this session
                cursor = await db.execute(
                    "SELECT DISTINCT id FROM agent_profiles WHERE session_id = ?",
                    (session_id,),
                )
                agent_rows = await cursor.fetchall()
        except Exception:
            logger.exception("detect_echo_chambers DB read failed session=%s", session_id)
            return EchoChamberResult(
                session_id=session_id,
                chambers=(),
                agent_to_cluster={},
                modularity=0.0,
                num_clusters=0,
            )

        agent_ids = [r[0] for r in agent_rows]
        if not agent_ids:
            return EchoChamberResult(
                session_id=session_id,
                chambers=(),
                agent_to_cluster={},
                modularity=0.0,
                num_clusters=0,
            )

        # Build adjacency structure: {node: {neighbour: weight}}
        # Phase 4A sparse Louvain: only include edges where trust_score > 0.1
        # This filters out weak/neutral relationships, reducing adjacency density
        # from O(N²) to O(N × meaningful_connections) and speeding up Louvain.
        _SPARSE_TRUST_THRESHOLD = 0.1
        adjacency: dict[int, dict[int, float]] = {aid: {} for aid in agent_ids}
        total_weight = 0.0
        node_strength: dict[int, float] = {aid: 0.0 for aid in agent_ids}

        for row in edge_rows:
            a, b, trust, inf_weight = row[0], row[1], float(row[2]), float(row[3])
            # Phase 4A: skip edges below trust threshold (sparse Louvain)
            if trust <= _SPARSE_TRUST_THRESHOLD:
                continue
            # Edge weight = influence_weight * (1 + trust), clamped > 0
            w = max(0.01, inf_weight * (1.0 + trust))
            if a in adjacency:
                adjacency[a][b] = adjacency[a].get(b, 0.0) + w
            if b in adjacency:
                adjacency[b][a] = adjacency[b].get(a, 0.0) + w
            total_weight += w
            node_strength[a] = node_strength.get(a, 0.0) + w
            node_strength[b] = node_strength.get(b, 0.0) + w

        if total_weight == 0.0:
            # No edges — each agent is its own cluster
            agent_to_cluster = {aid: i for i, aid in enumerate(agent_ids)}
            chambers = tuple(
                EchoChamber(cluster_id=i, agent_ids=(aid,), avg_trust=0.0, size=1) for i, aid in enumerate(agent_ids)
            )
            return EchoChamberResult(
                session_id=session_id,
                chambers=chambers,
                agent_to_cluster=agent_to_cluster,
                modularity=0.0,
                num_clusters=len(agent_ids),
            )

        # Louvain Phase 1: greedy modularity optimisation
        community: dict[int, int] = {aid: aid for aid in agent_ids}
        m2 = total_weight  # sum of all weights (already 2x due to bidirectional)

        rng = random.Random(42)
        improved = True
        iteration = 0
        while improved and iteration < _MAX_LOUVAIN_ITERATIONS:
            improved = False
            iteration += 1
            nodes_order = list(agent_ids)
            rng.shuffle(nodes_order)

            for node in nodes_order:
                current_comm = community[node]

                # Sum of weights to each neighbouring community
                comm_weights: dict[int, float] = {}
                for neighbour, w in adjacency.get(node, {}).items():
                    nc = community[neighbour]
                    comm_weights[nc] = comm_weights.get(nc, 0.0) + w

                # Sum of node strengths per community
                comm_totals: dict[int, float] = {}
                for aid in agent_ids:
                    c = community[aid]
                    comm_totals[c] = comm_totals.get(c, 0.0) + node_strength.get(aid, 0.0)

                k_i = node_strength.get(node, 0.0)
                best_comm = current_comm
                best_delta = 0.0

                for target_comm, w_to_c in comm_weights.items():
                    if target_comm == current_comm:
                        continue
                    # Modularity gain of moving node to target_comm
                    sigma_tot = comm_totals.get(target_comm, 0.0)
                    sigma_in_current = comm_totals.get(current_comm, 0.0) - k_i
                    w_to_current = comm_weights.get(current_comm, 0.0)

                    delta_q = (w_to_c - w_to_current) / m2 - _MODULARITY_RESOLUTION * k_i * (
                        sigma_tot - sigma_in_current
                    ) / (m2 * m2)

                    if delta_q > best_delta:
                        best_delta = delta_q
                        best_comm = target_comm

                if best_comm != current_comm:
                    community[node] = best_comm
                    improved = True

        # Renumber communities to 0..N-1
        unique_comms = sorted(set(community.values()))
        comm_remap = {old: new for new, old in enumerate(unique_comms)}
        agent_to_cluster = {aid: comm_remap[community[aid]] for aid in agent_ids}

        # Build EchoChamber objects
        cluster_agents: dict[int, list[int]] = {}
        for aid, cid in agent_to_cluster.items():
            cluster_agents.setdefault(cid, []).append(aid)

        # Compute avg trust within each cluster
        chambers_list: list[EchoChamber] = []
        for cid, members in sorted(cluster_agents.items()):
            member_set = set(members)
            trust_sum = 0.0
            trust_count = 0
            for row in edge_rows:
                a, b, trust = row[0], row[1], float(row[2])
                if a in member_set and b in member_set:
                    trust_sum += trust
                    trust_count += 1
            avg_trust = trust_sum / trust_count if trust_count > 0 else 0.0
            chambers_list.append(
                EchoChamber(
                    cluster_id=cid,
                    agent_ids=tuple(sorted(members)),
                    avg_trust=round(avg_trust, 4),
                    size=len(members),
                )
            )

        # Compute modularity Q
        modularity = _compute_modularity(agent_to_cluster, adjacency, node_strength, m2)

        logger.info(
            "Echo chambers detected session=%s: %d clusters, modularity=%.4f, iterations=%d",
            session_id,
            len(chambers_list),
            modularity,
            iteration,
        )

        return EchoChamberResult(
            session_id=session_id,
            chambers=tuple(chambers_list),
            agent_to_cluster=agent_to_cluster,
            modularity=round(modularity, 4),
            num_clusters=len(chambers_list),
        )

    async def get_cross_cluster_dampening(
        self,
        session_id: str,
        author_agent_id: int,
        target_agent_id: int,
        echo_result: EchoChamberResult | None = None,
    ) -> float:
        """Compute salience dampening factor for cross-cluster distrusted posts.

        If author and target are in different clusters AND have negative mutual
        trust, returns a dampening factor (0.3). Otherwise returns 1.0 (no dampening).

        Args:
            session_id: Session UUID.
            author_agent_id: The post author's agent ID.
            target_agent_id: The memory-receiving agent's ID.
            echo_result: Pre-computed echo chamber result (avoids re-detection).

        Returns:
            Dampening factor (0.0–1.0). Multiply with salience_score.
        """
        if echo_result is None:
            return 1.0  # No echo chamber data → no filter bubble

        author_cluster = echo_result.agent_to_cluster.get(author_agent_id)
        target_cluster = echo_result.agent_to_cluster.get(target_agent_id)

        if author_cluster is None or target_cluster is None:
            return 1.0
        if author_cluster == target_cluster:
            return 1.0  # Same cluster → full salience

        # Different clusters — check mutual trust
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT COALESCE(trust_score, 0.0) FROM agent_relationships
                    WHERE session_id = ?
                      AND agent_a_id = ? AND agent_b_id = ?
                    LIMIT 1
                    """,
                    (session_id, target_agent_id, author_agent_id),
                )
                row = await cursor.fetchone()
                trust = float(row[0]) if row else 0.0
        except Exception:
            return 1.0

        if trust < 0.0:
            # Negative trust + different cluster → filter bubble dampening
            return _CROSS_CLUSTER_DAMPENING
        return 1.0

    async def apply_echo_chamber_dampening(
        self,
        session_id: str,
        round_number: int,
        echo_result: EchoChamberResult,
    ) -> int:
        """Apply filter-bubble dampening to cross-cluster memories.

        For each agent memory in this round, if the memory was derived from a
        post by an agent in a different cluster with negative trust, reduce
        the salience by _CROSS_CLUSTER_DAMPENING.

        Args:
            session_id: Session UUID.
            round_number: The round to apply dampening to.
            echo_result: Pre-computed echo chamber detection result.

        Returns:
            Number of memories dampened.
        """
        if not echo_result.chambers or echo_result.num_clusters <= 1:
            return 0

        dampened = 0
        try:
            async with get_db() as db:
                # Batch-load ALL trust scores for this session in one query.
                # This eliminates the per-(memory_agent, author) DB query in the loop.
                trust_cursor = await db.execute(
                    """
                    SELECT agent_a_id, agent_b_id, COALESCE(trust_score, 0.0) AS trust_score
                    FROM agent_relationships
                    WHERE session_id = ?
                    """,
                    (session_id,),
                )
                trust_rows = await trust_cursor.fetchall()
                trust_cache: dict[tuple[int, int], float] = {(int(r[0]), int(r[1])): float(r[2]) for r in trust_rows}

                # Get all memories for this round with their agent_ids
                cursor = await db.execute(
                    """
                    SELECT am.id, am.agent_id, am.memory_text
                    FROM agent_memories am
                    WHERE am.session_id = ? AND am.round_number = ?
                    """,
                    (session_id, round_number),
                )
                memory_rows = await cursor.fetchall()

                # Get all posts from this round with usernames
                cursor = await db.execute(
                    """
                    SELECT sa.agent_id, sa.oasis_username
                    FROM simulation_actions sa
                    WHERE sa.session_id = ? AND sa.round_number = ?
                    """,
                    (session_id, round_number),
                )
                post_rows = await cursor.fetchall()

                # Build set of posting agents this round
                posting_agents = set()
                for r in post_rows:
                    if r[0] is not None:
                        posting_agents.add(int(r[0]))

                # Compute which memory IDs need dampening (no per-pair DB queries)
                ids_to_dampen: list[int] = []
                for mem_row in memory_rows:
                    mem_id, mem_agent_id = mem_row[0], mem_row[1]
                    target_cluster = echo_result.agent_to_cluster.get(mem_agent_id)
                    if target_cluster is None:
                        continue

                    # Check if any cross-cluster distrusted author posted
                    should_dampen = False
                    for author_id in posting_agents:
                        if author_id == mem_agent_id:
                            continue
                        author_cluster = echo_result.agent_to_cluster.get(author_id)
                        if author_cluster is None or author_cluster == target_cluster:
                            continue

                        # Look up trust from trust_cache instead of DB query
                        trust = trust_cache.get((mem_agent_id, author_id), 0.0)
                        if trust < 0.0:
                            should_dampen = True
                            break

                    if should_dampen:
                        ids_to_dampen.append(mem_id)

                # Batch UPDATE using executemany instead of individual UPDATEs
                if ids_to_dampen:
                    await db.executemany(
                        """
                        UPDATE agent_memories
                        SET salience_score = salience_score * ?
                        WHERE id = ?
                        """,
                        [(_CROSS_CLUSTER_DAMPENING, mem_id) for mem_id in ids_to_dampen],
                    )
                    dampened = len(ids_to_dampen)
                    await db.commit()

            logger.info(
                "Echo chamber dampening: %d memories dampened session=%s round=%d",
                dampened,
                session_id,
                round_number,
            )
        except Exception:
            logger.exception(
                "apply_echo_chamber_dampening failed session=%s round=%d",
                session_id,
                round_number,
            )

        return dampened

    async def compute_polarization_index(self, session_id: str, round_number: int) -> PolarizationResult:
        """Compute network polarization combining structural + opinion metrics.

        Formula:
          PI = 0.4 × modularity + 0.35 × opinion_variance + 0.25 × cross_cluster_hostility
        """
        # 1. Get echo chamber result (reuse existing Louvain)
        echo = await self.detect_echo_chambers(session_id)
        modularity = echo.modularity

        if echo.num_clusters <= 1:
            return PolarizationResult(
                polarization_index=0.0,
                modularity=modularity,
                opinion_variance=0.0,
                cross_cluster_hostility=0.0,
                cluster_stances={},
                round_number=round_number,
            )

        # 2. Compute opinion variance across clusters
        cluster_stances: dict[str, float] = {}
        try:
            async with get_db() as db:
                for chamber in echo.chambers:
                    if not chamber.agent_ids:
                        continue
                    placeholders = ",".join("?" * len(chamber.agent_ids))
                    cursor = await db.execute(
                        f"""SELECT AVG(COALESCE(political_stance, 0.5))
                            FROM agent_profiles
                            WHERE session_id = ? AND id IN ({placeholders})""",
                        (session_id, *chamber.agent_ids),
                    )
                    row = await cursor.fetchone()
                    avg_stance = float(row[0]) if row and row[0] is not None else 0.5
                    cluster_stances[str(chamber.cluster_id)] = round(avg_stance, 4)
        except Exception:
            logger.exception("Failed to compute cluster stances session=%s", session_id)

        stance_values = list(cluster_stances.values())
        if len(stance_values) >= 2:
            mean = sum(stance_values) / len(stance_values)
            opinion_var = sum((v - mean) ** 2 for v in stance_values) / len(stance_values)
        else:
            opinion_var = 0.0

        # 3. Cross-cluster hostility (avg negative trust for inter-cluster edges)
        hostility = 0.0
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT agent_a_id, agent_b_id, COALESCE(trust_score, 0.0) as trust
                       FROM agent_relationships
                       WHERE session_id = ? AND COALESCE(trust_score, 0.0) < 0""",
                    (session_id,),
                )
                neg_rows = await cursor.fetchall()

            cross_neg_count = 0
            cross_neg_sum = 0.0
            for r in neg_rows:
                a_cluster = echo.agent_to_cluster.get(r[0])
                b_cluster = echo.agent_to_cluster.get(r[1])
                if a_cluster is not None and b_cluster is not None and a_cluster != b_cluster:
                    cross_neg_count += 1
                    cross_neg_sum += abs(float(r[2]))

            if cross_neg_count > 0:
                hostility = min(1.0, cross_neg_sum / cross_neg_count)
        except Exception:
            logger.exception("Failed to compute cross-cluster hostility session=%s", session_id)

        # 4. Weighted combination
        pi = 0.4 * modularity + 0.35 * opinion_var + 0.25 * hostility

        return PolarizationResult(
            polarization_index=round(min(1.0, pi), 4),
            modularity=modularity,
            opinion_variance=round(opinion_var, 4),
            cross_cluster_hostility=round(hostility, 4),
            cluster_stances=cluster_stances,
            round_number=round_number,
        )

    async def persist_polarization_result(
        self,
        session_id: str,
        result: PolarizationResult,
    ) -> None:
        """Persist polarization snapshot to DB."""
        import json as _json  # noqa: PLC0415

        try:
            async with get_db() as db:
                await db.execute(
                    """CREATE TABLE IF NOT EXISTS polarization_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        round_number INTEGER NOT NULL,
                        polarization_index REAL NOT NULL,
                        modularity REAL NOT NULL,
                        opinion_variance REAL NOT NULL,
                        cross_cluster_hostility REAL NOT NULL,
                        cluster_stances_json TEXT NOT NULL DEFAULT '{}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(session_id, round_number)
                    )"""
                )
                await db.execute(
                    """INSERT OR REPLACE INTO polarization_snapshots
                        (session_id, round_number, polarization_index, modularity,
                         opinion_variance, cross_cluster_hostility, cluster_stances_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        result.round_number,
                        result.polarization_index,
                        result.modularity,
                        result.opinion_variance,
                        result.cross_cluster_hostility,
                        _json.dumps(result.cluster_stances, ensure_ascii=False),
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "persist_polarization_result failed session=%s round=%d",
                session_id,
                result.round_number,
            )

    async def persist_echo_chamber_result(
        self,
        session_id: str,
        round_number: int,
        result: EchoChamberResult,
    ) -> None:
        """Persist an echo chamber detection result to DB for frontend consumption.

        Serialises clusters and agent-to-cluster mapping as JSON and writes to
        the ``echo_chamber_snapshots`` table.  Uses INSERT OR REPLACE keyed on
        (session_id, round_number) so repeated calls are idempotent.

        Args:
            session_id: Simulation session UUID.
            round_number: The round these clusters correspond to.
            result: Immutable EchoChamberResult from detect_echo_chambers().
        """
        import json as _json  # noqa: PLC0415

        try:
            cluster_data = [
                {
                    "cluster_id": c.cluster_id,
                    "agent_ids": list(c.agent_ids),
                    "avg_trust": c.avg_trust,
                    "size": c.size,
                }
                for c in result.chambers
            ]
            agent_to_cluster = {str(k): v for k, v in result.agent_to_cluster.items()}

            async with get_db() as db:
                # Ensure table exists (idempotent)
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS echo_chamber_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        round_number INTEGER NOT NULL,
                        num_clusters INTEGER NOT NULL DEFAULT 0,
                        modularity REAL NOT NULL DEFAULT 0.0,
                        cluster_data_json TEXT NOT NULL DEFAULT '[]',
                        agent_to_cluster_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                    """
                )
                # Delete any existing row for this session+round, then insert
                await db.execute(
                    "DELETE FROM echo_chamber_snapshots WHERE session_id = ? AND round_number = ?",
                    (session_id, round_number),
                )
                await db.execute(
                    """
                    INSERT INTO echo_chamber_snapshots
                        (session_id, round_number, num_clusters, modularity,
                         cluster_data_json, agent_to_cluster_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        round_number,
                        result.num_clusters,
                        result.modularity,
                        _json.dumps(cluster_data, ensure_ascii=False),
                        _json.dumps(agent_to_cluster, ensure_ascii=False),
                    ),
                )
                await db.commit()

            logger.info(
                "Persisted echo chamber snapshot session=%s round=%d clusters=%d",
                session_id,
                round_number,
                result.num_clusters,
            )
        except Exception:
            logger.exception(
                "persist_echo_chamber_result failed session=%s round=%d",
                session_id,
                round_number,
            )

    async def get_network(
        self,
        session_id: str,
    ) -> list[dict]:
        """Retrieve all relationships for a session.

        Returns:
            List of relationship dicts.
        """
        try:
            async with get_db() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT id, agent_a_id, agent_b_id,
                           relationship_type, influence_weight, created_at
                    FROM agent_relationships
                    WHERE session_id = ?
                    ORDER BY relationship_type, agent_a_id
                    """,
                    (session_id,),
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            logger.exception("get_network failed session=%s", session_id)
            return []


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _compute_modularity(
    agent_to_cluster: dict[int, int],
    adjacency: dict[int, dict[int, float]],
    node_strength: dict[int, float],
    m2: float,
) -> float:
    """Compute Newman modularity Q for the given partition.

    Q = (1/m2) * sum_ij [ A_ij - (k_i * k_j) / m2 ] * delta(c_i, c_j)
    """
    if m2 == 0.0:
        return 0.0

    q = 0.0
    for i, neighbours in adjacency.items():
        ci = agent_to_cluster.get(i)
        ki = node_strength.get(i, 0.0)
        for j, w_ij in neighbours.items():
            cj = agent_to_cluster.get(j)
            if ci == cj:
                kj = node_strength.get(j, 0.0)
                q += w_ij - (ki * kj) / m2

    return q / m2
