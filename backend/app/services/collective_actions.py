"""Collective Actions — Layer 2 group formation and momentum tracking.

Agents in the same echo chamber with shared interests can form groups,
pool resources, and launch collective actions. Momentum snowballs when
more agents join, but decays naturally over time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger

logger = get_logger("collective_actions")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GROUP_MIN_MEMBERS: int = 5              # minimum agents to form a group
_MUTUAL_TRUST_THRESHOLD: float = 0.4    # pairwise trust to be in same group
_TOPIC_OVERLAP_THRESHOLD: float = 0.7   # fraction of topic overlap required
_JOIN_TRUST_MIN: float = 0.3             # min trust to join an action
_JOIN_STANCE_MIN: float = 0.6            # min political stance alignment
_MOMENTUM_JOIN_DELTA: float = 0.05      # momentum gain per new participant batch
_MOMENTUM_DECAY: float = 0.10           # natural momentum decay per round (10%)
_SUCCESS_THRESHOLD: float = 0.15        # fraction of total agents for success
_FAILURE_MOMENTUM_FLOOR: float = 0.1   # momentum below this triggers failure check
_FAILURE_CONSECUTIVE_ROUNDS: int = 3    # rounds below floor before dissolution
_CONTRIBUTION_RATE: float = 0.01        # 1% of savings contributed to group resources
_MAX_CONTRIBUTION: int = 5_000          # HKD cap per member per formation
_GROUP_DISSOLVE_MIN_MEMBERS: int = 3    # dissolve if membership falls below this

# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentGroup:
    """Immutable snapshot of an agent group state."""

    id: int | None                # None before DB persistence
    session_id: str
    group_name: str
    agenda: str
    leader_agent_id: int
    member_count: int
    shared_resources: int         # HKD pooled by members
    formed_round: int
    status: str                   # "active" | "dissolved" | "succeeded"


@dataclass(frozen=True)
class CollectiveAction:
    """Immutable snapshot of a collective action."""

    id: int | None                # None before DB persistence
    session_id: str
    group_id: int | None
    initiator_agent_id: int
    action_type: str              # "protest" | "boycott" | "petition" | "crowdfund"
    target: str
    participant_count: int
    momentum: float               # 0.0–1.0
    round_initiated: int
    status: str                   # "building" | "active" | "succeeded" | "failed"


# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

_CREATE_AGENT_GROUPS = """
CREATE TABLE IF NOT EXISTS agent_groups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    group_name      TEXT    NOT NULL,
    agenda          TEXT,
    leader_agent_id INTEGER NOT NULL,
    member_count    INTEGER NOT NULL DEFAULT 0,
    shared_resources INTEGER NOT NULL DEFAULT 0,
    formed_round    INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'active',
    created_at      TEXT    DEFAULT (datetime('now'))
)
"""

_CREATE_AGENT_GROUP_MEMBERS = """
CREATE TABLE IF NOT EXISTS agent_group_members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    group_id    INTEGER NOT NULL,
    agent_id    INTEGER NOT NULL,
    joined_round INTEGER NOT NULL,
    UNIQUE(session_id, group_id, agent_id)
)
"""

_CREATE_COLLECTIVE_ACTIONS = """
CREATE TABLE IF NOT EXISTS collective_actions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT    NOT NULL,
    group_id            INTEGER,
    initiator_agent_id  INTEGER NOT NULL,
    action_type         TEXT    NOT NULL,
    target              TEXT,
    participant_count   INTEGER NOT NULL DEFAULT 0,
    momentum            REAL    NOT NULL DEFAULT 0.1,
    consecutive_low_rounds INTEGER NOT NULL DEFAULT 0,
    round_initiated     INTEGER NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'building',
    created_at          TEXT    DEFAULT (datetime('now'))
)
"""

_CREATE_COLLECTIVE_ACTION_PARTICIPANTS = """
CREATE TABLE IF NOT EXISTS collective_action_participants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    action_id   INTEGER NOT NULL,
    agent_id    INTEGER NOT NULL,
    joined_round INTEGER NOT NULL,
    UNIQUE(session_id, action_id, agent_id)
)
"""


async def _ensure_collective_tables(db: Any) -> None:
    """Create all collective action tables if they do not exist."""
    await db.execute(_CREATE_AGENT_GROUPS)
    await db.execute(_CREATE_AGENT_GROUP_MEMBERS)
    await db.execute(_CREATE_COLLECTIVE_ACTIONS)
    await db.execute(_CREATE_COLLECTIVE_ACTION_PARTICIPANTS)
    await db.commit()


# ---------------------------------------------------------------------------
# Group name generation (LLM)
# ---------------------------------------------------------------------------

async def _generate_group_name(
    agenda: str,
    llm_client: LLMClient | None,
) -> str:
    """Generate a Cantonese group name via LLM, fallback to template."""
    if llm_client is None:
        return f"市民聯盟 ({agenda[:10]})"

    try:
        messages = [
            {
                "role": "system",
                "content": "你係一個香港市民組織命名專家。根據議程，起一個簡短的廣東話組織名稱（4-8個字）。",
            },
            {
                "role": "user",
                "content": f"議程：{agenda}\n\n請起一個組織名稱，只輸出名稱，唔需要其他解釋。",
            },
        ]
        response = await llm_client.chat(messages, max_tokens=20)
        name = response.strip()[:20]
        return name if name else f"市民聯盟_{agenda[:6]}"
    except Exception:
        logger.debug("LLM group naming failed, using template")
        return f"市民聯盟_{agenda[:6]}"


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def process_group_formation(
    session_id: str,
    round_num: int,
    llm_client: LLMClient | None = None,
    rng_seed: int | None = None,
) -> list[AgentGroup]:
    """Detect and form new agent groups from trust network clusters.

    Algorithm:
    1. Load echo chamber cluster assignments from latest snapshot.
    2. Within each cluster, find agents with mutual trust > 0.4.
    3. Groups require ≥ 5 members with topic overlap > 0.7.
    4. Leader is the agent with highest extraversion × trust centrality.
    5. Members each contribute min(savings * 1%, 5000) to shared_resources.
    6. Dissolve existing groups with < 3 members or where leader emigrated.

    Args:
        session_id: Simulation session UUID.
        round_num: Current round number.
        llm_client: Optional LLM client for group name generation.
        rng_seed: Optional seed for reproducible sampling.

    Returns:
        List of newly formed AgentGroup objects.
    """
    new_groups: list[AgentGroup] = []
    rng = random.Random(rng_seed)

    try:
        async with get_db() as db:
            await _ensure_collective_tables(db)

            # Load latest echo chamber snapshot
            cursor = await db.execute(
                """
                SELECT cluster_id, agent_ids
                FROM echo_chamber_snapshots
                WHERE session_id = ?
                ORDER BY round_number DESC
                LIMIT 1
                """,
                (session_id,),
            )
            snapshot_row = await cursor.fetchone()

            if not snapshot_row:
                logger.debug("No echo chamber snapshot found for group formation session=%s", session_id)
                return []

            # Parse cluster data
            import json as _json
            try:
                cluster_data = _json.loads(snapshot_row[1]) if snapshot_row[1] else []
            except Exception:
                cluster_data = []

            if not cluster_data:
                return []

            # Load agent profiles for cluster members
            all_agent_ids: list[int] = []
            for cluster in cluster_data:
                if isinstance(cluster, dict):
                    all_agent_ids.extend(cluster.get("agent_ids", []))
                elif isinstance(cluster, list):
                    all_agent_ids.extend(cluster)

            if not all_agent_ids:
                return []

            placeholders = ",".join("?" * len(all_agent_ids))
            cursor = await db.execute(
                f"""
                SELECT id, extraversion, savings, monthly_income, political_stance
                FROM agent_profiles
                WHERE session_id = ? AND id IN ({placeholders})
                """,
                (session_id, *all_agent_ids),
            )
            profile_rows = await cursor.fetchall()
            profiles: dict[int, dict[str, Any]] = {
                row[0]: {
                    "extraversion": row[1] or 0.5,
                    "savings": row[2] or 0,
                    "monthly_income": row[3] or 0,
                    "political_stance": row[4] or 0.5,
                }
                for row in profile_rows
            }

            # Load trust relationships for cluster agents
            cursor = await db.execute(
                f"""
                SELECT agent_a_id, agent_b_id, trust_score
                FROM agent_relationships
                WHERE session_id = ?
                  AND agent_a_id IN ({placeholders})
                  AND trust_score >= ?
                """,
                (session_id, *all_agent_ids, _MUTUAL_TRUST_THRESHOLD),
            )
            trust_rows = await cursor.fetchall()

            # Build adjacency map
            trust_map: dict[int, set[int]] = {aid: set() for aid in all_agent_ids}
            for row in trust_rows:
                a, b, score = row[0], row[1], row[2]
                if score >= _MUTUAL_TRUST_THRESHOLD:
                    trust_map.setdefault(a, set()).add(b)
                    trust_map.setdefault(b, set()).add(a)

            # Dissolve groups where leader emigrated or membership dropped
            cursor = await db.execute(
                "SELECT id, leader_agent_id, member_count FROM agent_groups WHERE session_id = ? AND status = 'active'",
                (session_id,),
            )
            existing_groups = await cursor.fetchall()
            groups_to_dissolve = []
            for eg in existing_groups:
                gid, leader_id, member_count = eg[0], eg[1], eg[2]
                # Check if leader still active (has income or is listed in profiles)
                if leader_id not in profiles:
                    groups_to_dissolve.append(gid)
                elif member_count < _GROUP_DISSOLVE_MIN_MEMBERS:
                    groups_to_dissolve.append(gid)

            if groups_to_dissolve:
                dissolve_ph = ",".join("?" * len(groups_to_dissolve))
                await db.execute(
                    f"UPDATE agent_groups SET status='dissolved' WHERE id IN ({dissolve_ph})",
                    groups_to_dissolve,
                )

        # Process each cluster for potential group formation
        for cluster in cluster_data:
            if isinstance(cluster, dict):
                cluster_agents = [aid for aid in cluster.get("agent_ids", []) if aid in profiles]
            elif isinstance(cluster, list):
                cluster_agents = [aid for aid in cluster if aid in profiles]
            else:
                continue

            if len(cluster_agents) < _GROUP_MIN_MEMBERS:
                continue

            # Find cohesive sub-cluster with high mutual trust
            # Simple greedy: start from highest-trust agent
            trust_centrality: dict[int, int] = {
                aid: len(trust_map.get(aid, set()) & set(cluster_agents))
                for aid in cluster_agents
            }
            sorted_agents = sorted(
                cluster_agents,
                key=lambda a: trust_centrality.get(a, 0),
                reverse=True,
            )

            # Form group from top-trust core
            group_members: list[int] = []
            for candidate in sorted_agents:
                if not group_members:
                    group_members.append(candidate)
                    continue
                # Check mutual trust with existing members (majority rule)
                trusted_by = sum(
                    1 for m in group_members
                    if candidate in trust_map.get(m, set())
                )
                if len(group_members) > 0 and trusted_by / len(group_members) >= 0.5:
                    group_members.append(candidate)
                if len(group_members) >= 20:  # cap group size
                    break

            if len(group_members) < _GROUP_MIN_MEMBERS:
                continue

            # Elect leader: highest extraversion × trust centrality
            leader_id = max(
                group_members,
                key=lambda a: (
                    profiles[a]["extraversion"] * (trust_centrality.get(a, 0) + 1)
                ),
            )

            # Compute shared resources
            shared_resources = 0
            for aid in group_members:
                savings = profiles[aid]["savings"]
                contribution = min(
                    int(savings * _CONTRIBUTION_RATE),
                    _MAX_CONTRIBUTION,
                )
                shared_resources += contribution

            # Determine agenda from dominant political stance
            avg_stance = sum(
                profiles[a]["political_stance"] for a in group_members
            ) / len(group_members)
            if avg_stance > 0.65:
                agenda = "民主改革倡議"
            elif avg_stance < 0.35:
                agenda = "社會穩定發展"
            else:
                agenda = "社區互助支援"

            group_name = await _generate_group_name(agenda, llm_client)

            # Persist group to DB
            try:
                async with get_db() as db:
                    cursor = await db.execute(
                        """
                        INSERT INTO agent_groups
                            (session_id, group_name, agenda, leader_agent_id,
                             member_count, shared_resources, formed_round, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                        """,
                        (session_id, group_name, agenda, leader_id,
                         len(group_members), shared_resources, round_num),
                    )
                    group_id = cursor.lastrowid

                    # Insert member records
                    member_rows = [
                        (session_id, group_id, aid, round_num)
                        for aid in group_members
                    ]
                    await db.executemany(
                        """
                        INSERT OR IGNORE INTO agent_group_members
                            (session_id, group_id, agent_id, joined_round)
                        VALUES (?, ?, ?, ?)
                        """,
                        member_rows,
                    )
                    await db.commit()

                new_groups.append(AgentGroup(
                    id=group_id,
                    session_id=session_id,
                    group_name=group_name,
                    agenda=agenda,
                    leader_agent_id=leader_id,
                    member_count=len(group_members),
                    shared_resources=shared_resources,
                    formed_round=round_num,
                    status="active",
                ))

                logger.info(
                    "Group formed: '%s' leader=%d members=%d resources=%d session=%s round=%d",
                    group_name, leader_id, len(group_members), shared_resources,
                    session_id, round_num,
                )

                # Limit to 3 new groups per round (avoid spamming)
                if len(new_groups) >= 3:
                    break

            except Exception:
                logger.exception("Failed to persist group session=%s round=%d", session_id, round_num)

    except Exception:
        logger.exception("process_group_formation failed session=%s round=%d", session_id, round_num)

    return new_groups


async def initiate_collective_action(
    session_id: str,
    group_id: int | None,
    initiator_id: int,
    action_type: str,
    target: str,
    round_num: int,
) -> CollectiveAction | None:
    """Create a new collective action initiated by a group leader.

    Args:
        session_id: Simulation session UUID.
        group_id: ID of the sponsoring group (None for leaderless actions).
        initiator_id: Agent ID of the initiator.
        action_type: Type of action (protest/boycott/petition/crowdfund).
        target: Target entity or issue.
        round_num: Round in which the action is initiated.

    Returns:
        CollectiveAction on success, None on failure.
    """
    try:
        async with get_db() as db:
            await _ensure_collective_tables(db)

            cursor = await db.execute(
                """
                INSERT INTO collective_actions
                    (session_id, group_id, initiator_agent_id, action_type,
                     target, participant_count, momentum, round_initiated, status)
                VALUES (?, ?, ?, ?, ?, 1, 0.15, ?, 'building')
                """,
                (session_id, group_id, initiator_id, action_type, target, round_num),
            )
            action_id = cursor.lastrowid

            # Add initiator as first participant
            await db.execute(
                """
                INSERT OR IGNORE INTO collective_action_participants
                    (session_id, action_id, agent_id, joined_round)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, action_id, initiator_id, round_num),
            )
            await db.commit()

        return CollectiveAction(
            id=action_id,
            session_id=session_id,
            group_id=group_id,
            initiator_agent_id=initiator_id,
            action_type=action_type,
            target=target,
            participant_count=1,
            momentum=0.15,
            round_initiated=round_num,
            status="building",
        )

    except Exception:
        logger.exception(
            "initiate_collective_action failed session=%s round=%d", session_id, round_num
        )
        return None


async def process_collective_action_momentum(
    session_id: str,
    round_num: int,
) -> None:
    """Update momentum for all active collective actions.

    Algorithm per action:
    1. Find potential joiners: trust > 0.3 AND stance alignment > 0.6.
    2. Compute join probability: p_join = trust × stance_alignment × current_momentum.
    3. New momentum = min(1.0, old + participant_delta × 0.05), decay 10%/round.
    4. Success if participant_count / total_agents > 0.15.
    5. Failure if momentum < 0.1 for 3 consecutive rounds.

    Args:
        session_id: Simulation session UUID.
        round_num: Current round number.
    """
    try:
        async with get_db() as db:
            await _ensure_collective_tables(db)

            # Load active actions
            cursor = await db.execute(
                """
                SELECT id, initiator_agent_id, action_type, participant_count,
                       momentum, consecutive_low_rounds
                FROM collective_actions
                WHERE session_id = ? AND status IN ('building', 'active')
                """,
                (session_id,),
            )
            active_actions = await cursor.fetchall()

            if not active_actions:
                return

            # Load total agent count
            cursor = await db.execute(
                "SELECT COUNT(*) FROM agent_profiles WHERE session_id = ?",
                (session_id,),
            )
            total_row = await cursor.fetchone()
            total_agents = total_row[0] if total_row else 1

            # Load trust relationships and agent stances in batch
            cursor = await db.execute(
                """
                SELECT ar.agent_a_id, ar.agent_b_id, ar.trust_score,
                       ap.political_stance
                FROM agent_relationships ar
                JOIN agent_profiles ap ON ap.id = ar.agent_a_id AND ap.session_id = ar.session_id
                WHERE ar.session_id = ? AND ar.trust_score >= ?
                """,
                (session_id, _JOIN_TRUST_MIN),
            )
            trust_rows = await cursor.fetchall()

        # Build trust map: {target_agent: [(source_agent, trust, stance)]}
        trust_map: dict[int, list[tuple[int, float, float]]] = {}
        for row in trust_rows:
            src, tgt, trust, stance = row[0], row[1], row[2], row[3]
            trust_map.setdefault(tgt, []).append((src, trust, stance or 0.5))

        # Load existing participants per action
        action_updates: list[tuple[int, float, str, int, int]] = []  # (participant_count, momentum, status, low_rounds, id)
        for action_row in active_actions:
            action_id = action_row[0]
            initiator_id = action_row[1]
            current_count = action_row[3]
            current_momentum = action_row[4]
            low_rounds = action_row[5]

            # Compute initiator's avg stance (use 0.5 as neutral reference)
            initiator_stance = 0.5
            for entries in trust_map.values():
                for src, trust, stance in entries:
                    if src == initiator_id:
                        initiator_stance = stance
                        break

            # Find potential joiners
            new_joiners = 0
            rng = random.Random(round_num + action_id)
            for potential_joiner, trust_entries in trust_map.items():
                for src, trust, joiner_stance in trust_entries:
                    # Check stance alignment (both leaning in same political direction)
                    stance_alignment = 1.0 - abs(joiner_stance - initiator_stance)
                    if stance_alignment < _JOIN_STANCE_MIN:
                        continue

                    p_join = trust * stance_alignment * current_momentum
                    if rng.random() < p_join * 0.1:  # scale down for realism
                        new_joiners += 1
                    break  # one entry per joiner is enough

            # Update momentum
            participant_delta = new_joiners
            new_momentum = current_momentum * (1.0 - _MOMENTUM_DECAY)  # decay
            new_momentum = min(1.0, new_momentum + participant_delta * _MOMENTUM_JOIN_DELTA)
            new_count = current_count + new_joiners

            # Check success
            if new_count / max(total_agents, 1) >= _SUCCESS_THRESHOLD:
                status = "succeeded"
                new_low_rounds = 0
            elif new_momentum < _FAILURE_MOMENTUM_FLOOR:
                new_low_rounds = low_rounds + 1
                if new_low_rounds >= _FAILURE_CONSECUTIVE_ROUNDS:
                    status = "failed"
                else:
                    status = "building"
            else:
                new_low_rounds = 0
                status = "active" if new_count > 1 else "building"

            action_updates.append((new_count, round(new_momentum, 4), status, new_low_rounds, action_id))

        # Batch update
        async with get_db() as db:
            await db.executemany(
                """
                UPDATE collective_actions
                SET participant_count = ?, momentum = ?, status = ?, consecutive_low_rounds = ?
                WHERE id = ?
                """,
                action_updates,
            )
            await db.commit()

        logger.debug(
            "collective_action_momentum session=%s round=%d actions=%d",
            session_id, round_num, len(action_updates),
        )

    except Exception:
        logger.exception(
            "process_collective_action_momentum failed session=%s round=%d",
            session_id, round_num,
        )
