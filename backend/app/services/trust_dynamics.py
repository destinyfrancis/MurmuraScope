"""Dynamic trust evolution service for agent social network.

Models how agents build or lose trust in each other based on:
- Sentiment alignment: same sentiment → trust++, opposite → trust--
- Political stance proximity: similar stance → trust bonus

Trust scores are stored in the ``agent_relationships.trust_score`` column
(added via ALTER TABLE at startup) and range from -1.0 to +1.0.

Decay factor: 0.95 per round (relationships naturally fade without interaction).

Phase 1 integration note:
    ``update_trust_from_round()`` now also writes back trust_score changes into
    ``relationship_states`` via ``RelationshipEngine`` when the session is running
    in kg_driven mode and relationship states have been initialized.
    The agent_relationships.trust_score column continues to be the authoritative
    source of truth for backward-compatible consumers (hk_demographic mode is
    completely unchanged).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiosqlite

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("trust_dynamics")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRUST_DECAY_FACTOR = 0.95
_TRUST_MIN = -1.0
_TRUST_MAX = 1.0
_DELTA_MAX = 0.15
_DELTA_MIN = -0.15

# Sentiment alignment scores
_SAME_SENTIMENT_SCORE = 1.0
_OPPOSITE_SENTIMENT_SCORE = -0.5
_NEUTRAL_SENTIMENT_SCORE = 0.0

# Weighting of alignment vs stance in delta computation
_ALIGNMENT_WEIGHT = 0.7
_STANCE_WEIGHT = 0.3

# Sensitivity of stance difference → bonus
_STANCE_SCALE = 0.1  # delta contribution per round per interaction


# ---------------------------------------------------------------------------
# Frozen dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrustUpdate:
    """Immutable record of a single trust score change."""

    agent_a_id: int
    agent_b_id: int
    old_score: float
    new_score: float
    reason: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TrustDynamicsService:
    """Manage dynamic trust scores between agents."""

    async def ensure_column(self, db: Any) -> None:
        """Idempotently add trust_score column to agent_relationships.

        Uses ALTER TABLE ... ADD COLUMN with try/except to ignore
        OperationalError when the column already exists.

        Args:
            db: An open aiosqlite connection.
        """
        try:
            await db.execute("ALTER TABLE agent_relationships ADD COLUMN trust_score REAL DEFAULT 0.0")
            await db.commit()
            logger.info("Added trust_score column to agent_relationships")
        except Exception:
            # Column already exists — safe to ignore
            pass

    async def update_trust_from_round(
        self,
        session_id: str,
        round_number: int,
        active_usernames: set[str] | None = None,
    ) -> tuple[TrustUpdate, ...]:
        """Compute and apply trust score changes from this round's interactions.

        For each (author, target) interaction pair in simulation_actions:
          1. Compute sentiment_alignment score.
          2. Compute stance_bonus from political_stance similarity.
          3. delta = clamp(alignment * 0.7 + stance_bonus * 0.3, -0.15, +0.15) * 0.1
          4. UPDATE trust_score in agent_relationships (both directions).

        Args:
            session_id: Session UUID.
            round_number: The round that just completed.
            active_usernames: Optional set of usernames that were active this
                round.  When provided, only interactions where the author is in
                this set are processed (sparse update optimisation for Phase 4A).
                Pass None to process all interactions (original behaviour).

        Returns:
            Tuple of TrustUpdate records (immutable).
        """
        updates: list[TrustUpdate] = []

        try:
            async with get_db() as db:
                # Ensure column exists (idempotent)
                await self.ensure_column(db)

                # 1. Load interactions: (username_a, username_b, sentiment_a)
                # Phase 4A sparse optimisation: filter to active authors only.
                if active_usernames:
                    placeholders = ",".join("?" for _ in active_usernames)
                    cursor = await db.execute(
                        f"""
                        SELECT oasis_username, target_agent_username, sentiment
                        FROM simulation_actions
                        WHERE session_id = ?
                          AND round_number = ?
                          AND target_agent_username IS NOT NULL
                          AND target_agent_username != ''
                          AND oasis_username IN ({placeholders})
                        """,
                        (session_id, round_number, *active_usernames),
                    )
                else:
                    cursor = await db.execute(
                        """
                        SELECT oasis_username, target_agent_username, sentiment
                        FROM simulation_actions
                        WHERE session_id = ?
                          AND round_number = ?
                          AND target_agent_username IS NOT NULL
                          AND target_agent_username != ''
                        """,
                        (session_id, round_number),
                    )
                interaction_rows = await cursor.fetchall()

                if not interaction_rows:
                    return ()

                # 2. Load agent profiles for username → (id, political_stance) lookup
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT id, oasis_username,
                           COALESCE(
                               (SELECT political_stance FROM agent_profiles ap2
                                WHERE ap2.id = agent_profiles.id LIMIT 1),
                               0.5
                           ) AS stance
                    FROM agent_profiles
                    WHERE session_id = ?
                    """,
                    (session_id,),
                )
                profile_rows = await cursor.fetchall()
                db.row_factory = None  # reset

                username_to_id: dict[str, int] = {}
                username_to_stance: dict[str, float] = {}
                for p in profile_rows:
                    uname = p["oasis_username"]
                    username_to_id[uname] = p["id"]
                    # Stance may not be a column; default 0.5
                    try:
                        stance = float(p["stance"]) if p["stance"] is not None else 0.5
                    except (TypeError, ValueError):
                        stance = 0.5
                    username_to_stance[uname] = stance

                # 3. Resolve interaction pairs to (aid, bid) — skip unknowns eagerly
                pair_data: list[tuple[int, int, str]] = []
                for uname_a, uname_b, sentiment_a in interaction_rows:
                    aid = username_to_id.get(uname_a)
                    bid = username_to_id.get(uname_b)
                    if aid is not None and bid is not None:
                        pair_data.append((aid, bid, str(sentiment_a)))

                if not pair_data:
                    return ()

                # 4. Batch-load existing trust scores in ONE query (eliminates N+1)
                pair_ids = list({(aid, bid) for aid, bid, _ in pair_data})
                # Build a VALUES list for a single SELECT … JOIN rather than N selects
                placeholders = ",".join("(?,?)" for _ in pair_ids)
                flat_ids = [v for aid, bid in pair_ids for v in (aid, bid)]
                trust_cur = await db.execute(
                    f"""
                    SELECT agent_a_id, agent_b_id, COALESCE(trust_score, 0.0)
                    FROM agent_relationships
                    WHERE session_id = ?
                      AND (agent_a_id, agent_b_id) IN ({placeholders})
                    """,
                    (session_id, *flat_ids),
                )
                trust_map: dict[tuple[int, int], float] = {
                    (int(r[0]), int(r[1])): float(r[2]) for r in await trust_cur.fetchall()
                }

                # 5. Compute new scores in Python (zero DB round-trips)
                # Pre-build reverse lookup to avoid O(n) scan per pair
                id_to_username: dict[int, str] = {v: k for k, v in username_to_id.items()}
                upsert_rows: list[tuple[str, int, int, str, float, float]] = []
                for aid, bid, sentiment_a in pair_data:
                    uname_a = id_to_username.get(aid, "")
                    uname_b = id_to_username.get(bid, "")
                    alignment = _sentiment_alignment_score(sentiment_a)
                    stance_a = username_to_stance.get(uname_a, 0.5)
                    stance_b = username_to_stance.get(uname_b, 0.5)
                    stance_bonus = 1.0 - abs(stance_a - stance_b)

                    raw_delta = (alignment * _ALIGNMENT_WEIGHT + stance_bonus * _STANCE_WEIGHT) * _STANCE_SCALE
                    delta = max(_DELTA_MIN, min(_DELTA_MAX, raw_delta))

                    old_score = trust_map.get((aid, bid), 0.0)
                    new_score = max(_TRUST_MIN, min(_TRUST_MAX, old_score + delta))

                    upsert_rows.append(
                        (
                            session_id,
                            aid,
                            bid,
                            "interaction",
                            0.5,
                            new_score,
                        )
                    )
                    updates.append(
                        TrustUpdate(
                            agent_a_id=aid,
                            agent_b_id=bid,
                            old_score=round(old_score, 4),
                            new_score=round(new_score, 4),
                            reason=f"sentiment={sentiment_a} alignment={alignment:.2f} stance_bonus={stance_bonus:.2f}",
                        )
                    )

                # 6. Batch UPSERT — single executemany replaces N×3 queries
                await db.executemany(
                    """
                    INSERT INTO agent_relationships
                        (session_id, agent_a_id, agent_b_id,
                         relationship_type, influence_weight, trust_score)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, agent_a_id, agent_b_id)
                    DO UPDATE SET trust_score = excluded.trust_score
                    """,
                    upsert_rows,
                )
                await db.commit()

        except Exception:
            logger.exception(
                "update_trust_from_round failed session=%s round=%d",
                session_id,
                round_number,
            )

        return tuple(updates)

    async def decay_trust(self, session_id: str) -> int:
        """Apply decay to all trust scores for this session.

        trust_score = trust_score * 0.95

        Only rows where |trust_score| > 0.01 are decayed to avoid
        floating-point noise accumulation on zero-trust relationships.

        Args:
            session_id: Session UUID.

        Returns:
            Number of rows updated.
        """
        try:
            async with get_db() as db:
                await self.ensure_column(db)
                cursor = await db.execute(
                    """
                    UPDATE agent_relationships
                    SET trust_score = trust_score * ?
                    WHERE session_id = ?
                      AND ABS(trust_score) > 0.01
                    """,
                    (_TRUST_DECAY_FACTOR, session_id),
                )
                count = cursor.rowcount
                await db.commit()
            return count
        except Exception:
            logger.exception("decay_trust failed session=%s", session_id)
            return 0

    async def get_trust_context(
        self,
        session_id: str,
        agent_id: int,
    ) -> str:
        """Build a formatted trust context string for persona enrichment.

        Returns top-3 trusted and top-3 distrusted relationships.

        Args:
            session_id: Session UUID.
            agent_id: The agent whose trust relationships to retrieve.

        Returns:
            Formatted string like:
            「【信任關係】信任: @user_a (0.7), @user_b (0.5) | 不信任: @user_c (-0.4)」
            or empty string if no significant trust relationships.
        """
        try:
            async with get_db() as db:
                await self.ensure_column(db)

                # Query relationships where this agent is agent_a
                cursor = await db.execute(
                    """
                    SELECT ar.agent_b_id, ar.trust_score, ap.oasis_username
                    FROM agent_relationships ar
                    LEFT JOIN agent_profiles ap
                           ON ap.id = ar.agent_b_id
                          AND ap.session_id = ar.session_id
                    WHERE ar.session_id = ?
                      AND ar.agent_a_id = ?
                      AND ar.trust_score IS NOT NULL
                      AND ABS(ar.trust_score) > 0.1
                    ORDER BY ar.trust_score DESC
                    """,
                    (session_id, agent_id),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception("get_trust_context failed session=%s agent=%d", session_id, agent_id)
            return ""

        if not rows:
            return ""

        trusted = [(r[2] or f"agent_{r[0]}", round(float(r[1]), 2)) for r in rows if r[1] > 0.1][:3]
        distrusted = [(r[2] or f"agent_{r[0]}", round(float(r[1]), 2)) for r in rows if r[1] < -0.1][-3:]

        if not trusted and not distrusted:
            return ""

        parts: list[str] = []
        if trusted:
            trusted_str = ", ".join(f"@{name} ({score})" for name, score in trusted)
            parts.append(f"信任: {trusted_str}")
        if distrusted:
            dist_str = ", ".join(f"@{name} ({score})" for name, score in distrusted)
            parts.append(f"不信任: {dist_str}")

        return "【信任關係】" + " | ".join(parts)

    async def sync_trust_to_relationship_states(
        self,
        session_id: str,
        round_number: int,
        updates: tuple[TrustUpdate, ...],
    ) -> None:
        """Write trust_score changes from TrustUpdates into relationship_states table.

        Called optionally by SimulationRunner after update_trust_from_round()
        when relationship_states rows exist (kg_driven mode with Phase 1 enabled).
        Completely no-ops if relationship_states has no rows for this session — so
        hk_demographic mode is unaffected.

        Uses UPDATE only (does not INSERT) to avoid creating relationship_states
        rows for pairs that were never initialized.

        Args:
            session_id: Session UUID.
            round_number: Current round number.
            updates: TrustUpdate tuples from update_trust_from_round().
        """
        if not updates:
            return
        try:
            async with get_db() as db:
                for upd in updates:
                    await db.execute(
                        """
                        UPDATE relationship_states
                        SET trust = ?, updated_at = datetime('now')
                        WHERE session_id = ?
                          AND agent_a_id = CAST(? AS TEXT)
                          AND agent_b_id = CAST(? AS TEXT)
                          AND round_number = ?
                        """,
                        (upd.new_score, session_id, upd.agent_a_id, upd.agent_b_id, round_number),
                    )
                await db.commit()
        except Exception:
            logger.debug(
                "sync_trust_to_relationship_states failed (non-critical) session=%s",
                session_id,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sentiment_alignment_score(sentiment: str) -> float:
    """Map sentiment label to alignment score.

    positive vs positive / negative vs negative → +1.0 (same polarity)
    positive vs negative (or vice versa) → -0.5  (opposite polarity)
    neutral → 0.0
    """
    # For the author sentiment — we count same-sentiment with "positive/negative"
    # interactions as trust-building; opposite as trust-eroding.
    s = sentiment.lower().strip()
    if s == "positive":
        return _SAME_SENTIMENT_SCORE
    if s == "negative":
        return _OPPOSITE_SENTIMENT_SCORE
    return _NEUTRAL_SENTIMENT_SCORE
