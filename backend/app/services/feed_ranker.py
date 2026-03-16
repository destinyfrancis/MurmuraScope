"""Feed ranking engine for Phase 2 Recommendation Engine.

Ranks posts for each agent using configurable algorithms, computes
filter bubble indices, and persists feed snapshots.
"""
from __future__ import annotations

import math
from statistics import median as _median
from typing import Any

from backend.app.models.recommendation import (
    ALGORITHM_WEIGHTS,
    FeedAlgorithm,
    FilterBubbleIndex,
    FilterBubbleReport,
)
from backend.app.utils.logger import get_logger

logger = get_logger("feed_ranker")


class FeedRankingEngine:
    """Ranks posts per agent and measures filter bubble intensity.

    Uses configurable algorithm weights so the same code path supports
    chronological, engagement-first, and echo-chamber algorithms.
    """

    FEED_SIZE: int = 20
    RECENCY_HALF_LIFE: float = 3.0     # rounds
    MAX_CANDIDATES: int = 100

    # Stance bucket boundaries for Shannon entropy computation
    STANCE_BUCKETS: list[float] = [-1.0, -0.6, -0.2, 0.2, 0.6, 1.0]
    MAX_ENTROPY: float = math.log2(5)  # max entropy for 5 equal buckets

    async def rank_feed(
        self,
        session_id: str,
        agent_id: int,
        agent_stance: float,
        round_number: int,
        algorithm: FeedAlgorithm,
        db: Any,
    ) -> list[dict[str, Any]]:
        """Rank posts for one agent using the specified algorithm.

        Loads candidate posts from trusted/followed authors and scores
        each one according to the algorithm weights.

        Args:
            session_id: Simulation session UUID.
            agent_id: Primary key of the agent whose feed is being ranked.
            agent_stance: Agent's political stance [-1, 1].
            round_number: Current simulation round.
            algorithm: Feed algorithm to apply.
            db: Aiosqlite connection (passed from caller).

        Returns:
            Sorted list of scored post dicts (up to FEED_SIZE).
        """
        # Load candidate posts from trusted / followed authors
        cursor = await db.execute(
            """SELECT sa.id, sa.agent_id, sa.round_number,
                      sa.content, sa.sentiment, sa.topics,
                      COALESCE(ar.trust_score, 0.1) AS trust_score
               FROM simulation_actions sa
               JOIN agent_relationships ar
                 ON ar.agent_b_id = sa.agent_id
                AND ar.session_id = sa.session_id
               WHERE sa.session_id = ?
                 AND ar.agent_a_id = ?
                 AND ar.trust_score > 0.1
                 AND sa.action_type IN ('create_post','post','repost','quote_post')
               ORDER BY sa.round_number DESC
               LIMIT ?""",
            (session_id, agent_id, self.MAX_CANDIDATES),
        )
        rows = await cursor.fetchall()

        if not rows:
            return []

        weights = ALGORITHM_WEIGHTS[algorithm]
        scored: list[tuple[float, dict[str, Any]]] = []

        for row in rows:
            post_dict = {
                "id": row[0],
                "agent_id": row[1],
                "round_number": row[2],
                "content": row[3] or "",
                "sentiment": row[4] or "neutral",
                "topics": row[5] or "",
                "trust_score": float(row[6]),
            }

            score = self._score_post(
                post=post_dict,
                agent_stance=agent_stance,
                round_number=round_number,
                weights=weights,
            )
            post_dict["score"] = round(score, 6)
            scored.append((score, post_dict))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[: self.FEED_SIZE]]

    def _score_post(
        self,
        post: dict[str, Any],
        agent_stance: float,
        round_number: int,
        weights: dict[str, float],
    ) -> float:
        """Compute weighted score for one post.

        Signals:
        - relevance: Jaccard similarity between agent interests and post topics.
        - recency: Exponential decay with half-life RECENCY_HALF_LIFE.
        - engagement: log(1 + engagement_proxy) normalised to [0,1].
        - social_affinity: trust score (already 0-1).
        - controversy: abs(sentiment - 0.5) * 2.
        """
        # Recency
        age = max(0, round_number - int(post["round_number"]))
        recency = math.exp(-math.log(2) / self.RECENCY_HALF_LIFE * age)

        # Engagement proxy (content length as simple proxy, normalised)
        content_len = len(post.get("content") or "")
        engagement = math.log1p(content_len / 20) / math.log1p(50)
        engagement = min(1.0, engagement)

        # Social affinity = trust score
        social_affinity = max(0.0, min(1.0, float(post.get("trust_score", 0.1))))

        # Controversy = sentiment polarity
        sentiment_str = str(post.get("sentiment") or "neutral").lower()
        if sentiment_str == "positive":
            sentiment_val = 1.0
        elif sentiment_str == "negative":
            sentiment_val = 0.0
        else:
            sentiment_val = 0.5
        controversy = abs(sentiment_val - 0.5) * 2.0

        # Relevance: simple stance-based affinity (same sign → relevant)
        # Post sentiment maps: positive→+0.8, negative→-0.8, neutral→0
        post_stance = (sentiment_val - 0.5) * 1.6
        relevance = max(0.0, 1.0 - abs(agent_stance - post_stance))

        score = (
            weights["relevance"] * relevance
            + weights["recency"] * recency
            + weights["engagement"] * engagement
            + weights["social_affinity"] * social_affinity
            + weights["controversy"] * controversy
        )
        return score

    async def compute_bubble_index(
        self,
        agent_id: int,
        agent_stance: float,
        feed_posts: list[dict[str, Any]],
        round_number: int,
    ) -> FilterBubbleIndex:
        """Compute filter bubble metrics for one agent's ranked feed.

        Args:
            agent_id: Agent primary key.
            agent_stance: Agent's political stance [-1, 1].
            feed_posts: Ranked feed posts (output of rank_feed).
            round_number: Current simulation round.

        Returns:
            FilterBubbleIndex with diversity / bubble metrics.
        """
        if not feed_posts:
            return FilterBubbleIndex(
                agent_id=agent_id,
                round_number=round_number,
                exposure_diversity=0.0,
                stance_divergence=0.0,
                source_concentration=0.0,
                bubble_score=1.0,
            )

        # Map sentiment to stance float
        def _to_stance(post: dict[str, Any]) -> float:
            s = str(post.get("sentiment") or "neutral").lower()
            if s == "positive":
                return 0.8
            if s == "negative":
                return -0.8
            return 0.0

        post_stances = [_to_stance(p) for p in feed_posts]

        # Exposure diversity: Shannon entropy over 5 stance buckets
        bucket_counts = [0] * 5
        for st in post_stances:
            idx = _stance_to_bucket(st)
            bucket_counts[idx] += 1

        n = len(post_stances)
        entropy = 0.0
        for cnt in bucket_counts:
            if cnt > 0:
                p = cnt / n
                entropy -= p * math.log2(p)

        exposure_diversity = round(entropy, 4)

        # Stance divergence: avg |agent_stance - post_stance|
        stance_divergence = sum(abs(agent_stance - st) for st in post_stances) / n
        stance_divergence = round(stance_divergence, 4)

        # Source concentration: Herfindahl index over authors
        author_counts: dict[int, int] = {}
        for p in feed_posts:
            aid = int(p.get("agent_id") or 0)
            author_counts[aid] = author_counts.get(aid, 0) + 1

        source_concentration = 0.0
        for cnt in author_counts.values():
            share = cnt / n
            source_concentration += share * share
        source_concentration = round(source_concentration, 4)

        # Bubble score: 1 - normalised entropy
        normalised_entropy = exposure_diversity / self.MAX_ENTROPY if self.MAX_ENTROPY > 0 else 0.0
        bubble_score = round(max(0.0, 1.0 - normalised_entropy), 4)

        return FilterBubbleIndex(
            agent_id=agent_id,
            round_number=round_number,
            exposure_diversity=exposure_diversity,
            stance_divergence=stance_divergence,
            source_concentration=source_concentration,
            bubble_score=bubble_score,
        )

    async def compute_bubble_report(
        self,
        session_id: str,
        round_number: int,
        algorithm: FeedAlgorithm,
        bubble_indices: list[FilterBubbleIndex],
    ) -> FilterBubbleReport:
        """Aggregate individual bubble indices into a session-level report.

        Args:
            session_id: Simulation session UUID.
            round_number: Current simulation round.
            algorithm: Feed algorithm used.
            bubble_indices: Per-agent filter bubble indices.

        Returns:
            FilterBubbleReport with aggregate statistics.
        """
        if not bubble_indices:
            return FilterBubbleReport(
                session_id=session_id,
                round_number=round_number,
                avg_bubble_score=0.0,
                median_bubble_score=0.0,
                pct_in_bubble=0.0,
                algorithm_name=algorithm.value,
                gini_coefficient=0.0,
            )

        scores = [b.bubble_score for b in bubble_indices]
        n = len(scores)
        avg = round(sum(scores) / n, 4)
        med = round(_median(scores), 4)
        pct = round(sum(1 for s in scores if s > 0.7) / n, 4)
        gini = round(_gini_coefficient(scores), 4)

        return FilterBubbleReport(
            session_id=session_id,
            round_number=round_number,
            avg_bubble_score=avg,
            median_bubble_score=med,
            pct_in_bubble=pct,
            algorithm_name=algorithm.value,
            gini_coefficient=gini,
        )

    async def persist_feeds(
        self,
        session_id: str,
        feeds: dict[int, list[dict[str, Any]]],
        db: Any,
    ) -> None:
        """Batch insert agent feed rows.

        Args:
            session_id: Simulation session UUID.
            feeds: Mapping agent_id → ranked post list.
            db: Aiosqlite connection.
        """
        rows = []
        for agent_id, posts in feeds.items():
            for rank, post in enumerate(posts):
                rows.append((
                    session_id,
                    agent_id,
                    post.get("round_number", 0),
                    str(post.get("id", "")),
                    rank + 1,
                    float(post.get("score", 0.0)),
                ))

        if rows:
            await db.executemany(
                "INSERT INTO agent_feeds "
                "(session_id, agent_id, round_number, post_id, rank, score) "
                "VALUES (?,?,?,?,?,?)",
                rows,
            )
            await db.commit()

    async def persist_bubble_report(
        self,
        report: FilterBubbleReport,
        db: Any,
    ) -> None:
        """Persist filter bubble snapshot (upsert on session+round).

        Args:
            report: FilterBubbleReport to persist.
            db: Aiosqlite connection.
        """
        await db.execute(
            """INSERT INTO filter_bubble_snapshots
               (session_id, round_number, avg_bubble_score, median_bubble_score,
                pct_in_bubble, algorithm, gini_coefficient)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(session_id, round_number) DO UPDATE SET
                 avg_bubble_score=excluded.avg_bubble_score,
                 median_bubble_score=excluded.median_bubble_score,
                 pct_in_bubble=excluded.pct_in_bubble,
                 algorithm=excluded.algorithm,
                 gini_coefficient=excluded.gini_coefficient""",
            (
                report.session_id,
                report.round_number,
                report.avg_bubble_score,
                report.median_bubble_score,
                report.pct_in_bubble,
                report.algorithm_name,
                report.gini_coefficient,
            ),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _stance_to_bucket(stance: float) -> int:
    """Map stance float to one of 5 buckets (0–4)."""
    if stance < -0.6:
        return 0
    if stance < -0.2:
        return 1
    if stance < 0.2:
        return 2
    if stance < 0.6:
        return 3
    return 4


def _gini_coefficient(values: list[float]) -> float:
    """Compute Gini coefficient for a list of values.

    Uses the standard sorted-absolute-difference formula.
    Returns 0.0 for empty or all-equal distributions.
    """
    n = len(values)
    if n == 0:
        return 0.0
    sorted_vals = sorted(values)
    total = sum(sorted_vals)
    if total == 0:
        return 0.0
    cumulative = 0.0
    gini_sum = 0.0
    for i, v in enumerate(sorted_vals):
        cumulative += v
        gini_sum += (2 * (i + 1) - n - 1) * v
    return gini_sum / (n * total)
