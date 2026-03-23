"""Attention Economy — Layer 1 resource-bound action tracking.

Each agent has 24 attention points per round. Posts consume 1-3 points
based on content length. Agents prioritise familiar topics and exhibit
fatigue when attention budget is depleted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("attention_economy")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOTAL_POINTS: int = 24  # attention points per agent per round
_FATIGUE_THRESHOLD: int = 5  # stop engaging new topics when below this
_SHORT_POST_COST: int = 1  # ≤ 100 chars
_MEDIUM_POST_COST: int = 2  # 101-300 chars
_LONG_POST_COST: int = 3  # > 300 chars
_NOVELTY_BONUS: float = 1.0  # sensitivity for completely new topics
_DIMINISHING_CAP: float = 0.3  # minimum sensitivity after heavy engagement

# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttentionBudget:
    """Immutable snapshot of an agent's attention allocation for one round."""

    session_id: str
    agent_id: int
    round_number: int
    total_points: int
    allocations: tuple[tuple[str, int], ...]  # (topic, points_spent)
    remaining: int


@dataclass(frozen=True)
class TopicSensitivity:
    """Immutable sensitivity score for a single topic."""

    topic: str
    sensitivity: float  # 0.0–1.0; higher = more receptive


# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

_CREATE_ATTENTION_TABLE = """
CREATE TABLE IF NOT EXISTS agent_attention (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL,
    agent_id     INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    topic        TEXT    NOT NULL,
    points_spent INTEGER NOT NULL DEFAULT 0,
    sensitivity  REAL    NOT NULL DEFAULT 1.0,
    created_at   TEXT    DEFAULT (datetime('now')),
    UNIQUE(session_id, agent_id, round_number, topic)
)
"""

_CREATE_ATTENTION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_attention_session_round
    ON agent_attention(session_id, round_number)
"""


async def _ensure_attention_table(db: Any) -> None:
    """Create agent_attention table and index if they do not exist."""
    await db.execute(_CREATE_ATTENTION_TABLE)
    await db.execute(_CREATE_ATTENTION_INDEX)
    await db.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _post_cost(content: str) -> int:
    """Return attention cost for a post based on content length."""
    length = len(content)
    if length <= 100:
        return _SHORT_POST_COST
    if length <= 300:
        return _MEDIUM_POST_COST
    return _LONG_POST_COST


def _extract_topics(content: str) -> list[str]:
    """Extract simple topic tokens from post content.

    Uses hashtag extraction and keyword heuristics. Returns a list of
    normalised topic strings (up to 3 per post).
    """
    import re

    topics: list[str] = []
    # Hashtag extraction
    hashtags = re.findall(r"#([\u4e00-\u9fa5\w]+)", content)
    topics.extend(t.lower() for t in hashtags[:3])

    # Keyword heuristics for common HK topics
    _KEYWORD_TOPICS: dict[str, str] = {
        "樓": "房地產",
        "租": "房地產",
        "按揭": "房地產",
        "移民": "移民",
        "BNO": "移民",
        "股": "金融",
        "恒指": "金融",
        "HSI": "金融",
        "政府": "政治",
        "選舉": "政治",
        "政黨": "政治",
        "失業": "就業",
        "工作": "就業",
        "招聘": "就業",
        "通脹": "宏觀經濟",
        "GDP": "宏觀經濟",
        "疫情": "健康",
        "醫院": "健康",
    }
    for keyword, topic in _KEYWORD_TOPICS.items():
        if keyword in content and topic not in topics:
            topics.append(topic)
            if len(topics) >= 3:
                break

    return topics[:3] if topics else ["general"]


def _compute_sensitivity(
    points_spent: int,
    prev_sensitivity: float = _NOVELTY_BONUS,
) -> float:
    """Compute diminishing sensitivity from cumulative attention spent.

    Heavy engagement reduces sensitivity (habituation). Fresh topics
    retain full novelty bonus.
    """
    if points_spent == 0:
        return _NOVELTY_BONUS
    # Logarithmic decay: sensitivity = 1 / (1 + 0.3 * log(1 + points_spent))
    decay = 1.0 / (1.0 + 0.3 * math.log1p(points_spent))
    return max(_DIMINISHING_CAP, min(_NOVELTY_BONUS, decay))


# ---------------------------------------------------------------------------
# Core allocation function
# ---------------------------------------------------------------------------


async def allocate_attention(
    session_id: str,
    round_num: int,
    agent_id: int,
    posts_this_round: list[dict[str, Any]],
    prior_topic_points: dict[str, int] | None = None,
) -> AttentionBudget:
    """Allocate attention for one agent across posts in a round.

    Args:
        session_id: Simulation session UUID.
        round_num: Current round number.
        agent_id: Agent ID.
        posts_this_round: List of post dicts with at least a 'content' key.
        prior_topic_points: Optional cumulative topic spend from earlier rounds.
            If None, a fresh budget is used.

    Returns:
        Immutable ``AttentionBudget`` recording allocations and remaining points.
    """
    remaining = _TOTAL_POINTS
    allocations: dict[str, int] = {}
    prior = prior_topic_points or {}

    for post in posts_this_round:
        if remaining < _FATIGUE_THRESHOLD:
            break  # fatigue — stop engaging new topics

        content = post.get("content", "")
        cost = _post_cost(content)

        if cost > remaining:
            continue  # not enough budget for this post

        topics = _extract_topics(content)
        for topic in topics:
            # Novelty check: known topics prioritised if already engaged
            prev_points = prior.get(topic, 0)
            sensitivity = _compute_sensitivity(prev_points)

            # Low sensitivity AND not a familiar topic → skip (fatigue)
            if sensitivity < 0.5 and prev_points == 0 and remaining < 8:
                continue

            allocations[topic] = allocations.get(topic, 0) + cost
            remaining -= cost
            if remaining <= 0:
                break

        if remaining <= 0:
            break

    return AttentionBudget(
        session_id=session_id,
        agent_id=agent_id,
        round_number=round_num,
        total_points=_TOTAL_POINTS,
        allocations=tuple(sorted(allocations.items())),
        remaining=max(0, remaining),
    )


def compute_topic_sensitivity(budget: AttentionBudget) -> dict[str, float]:
    """Derive topic sensitivity map from an AttentionBudget.

    High-attention topics get diminishing sensitivity.
    Untouched topics retain novelty bonus (1.0).

    Args:
        budget: Completed attention budget for an agent.

    Returns:
        Dict mapping topic → sensitivity (0.0–1.0).
    """
    result: dict[str, float] = {}
    total_spent = dict(budget.allocations)
    for topic, points in total_spent.items():
        result[topic] = _compute_sensitivity(points)
    return result


# ---------------------------------------------------------------------------
# Batch allocation
# ---------------------------------------------------------------------------


async def batch_allocate_attention(
    session_id: str,
    round_num: int,
    agent_ids: list[int],
    posts: list[dict[str, Any]],
) -> list[AttentionBudget]:
    """Allocate attention for all agents in one pass with batch DB reads.

    Loads prior topic spending from DB in a single query, then runs
    per-agent allocation. Results are persisted via batch INSERT.

    Args:
        session_id: Simulation session UUID.
        round_num: Current round number.
        agent_ids: List of agent IDs to process.
        posts: List of post dicts with 'content' and optional 'agent_id' keys.

    Returns:
        List of ``AttentionBudget`` objects (one per agent).
    """
    if not agent_ids:
        return []

    budgets: list[AttentionBudget] = []

    try:
        async with get_db() as db:
            await _ensure_attention_table(db)

            # Batch-load prior topic spend for all agents (single query)
            placeholders = ",".join("?" * len(agent_ids))
            cursor = await db.execute(
                f"""
                SELECT agent_id, topic, SUM(points_spent) AS total
                FROM agent_attention
                WHERE session_id = ? AND agent_id IN ({placeholders})
                GROUP BY agent_id, topic
                """,
                (session_id, *agent_ids),
            )
            rows = await cursor.fetchall()

        # Build per-agent prior spend map
        prior_by_agent: dict[int, dict[str, int]] = {aid: {} for aid in agent_ids}
        for row in rows:
            aid = row[0]
            topic = row[1]
            total = row[2]
            if aid in prior_by_agent:
                prior_by_agent[aid][topic] = total

        # Run allocation for each agent
        for agent_id in agent_ids:
            budget = await allocate_attention(
                session_id=session_id,
                round_num=round_num,
                agent_id=agent_id,
                posts_this_round=posts,
                prior_topic_points=prior_by_agent.get(agent_id),
            )
            budgets.append(budget)

        # Persist results with batch INSERT
        rows_to_insert = []
        for budget in budgets:
            alloc_dict = dict(budget.allocations)
            sensitvities = compute_topic_sensitivity(budget)
            for topic, points in alloc_dict.items():
                rows_to_insert.append(
                    (
                        session_id,
                        budget.agent_id,
                        round_num,
                        topic,
                        points,
                        sensitvities.get(topic, 1.0),
                    )
                )

        if rows_to_insert:
            async with get_db() as db:
                await db.executemany(
                    """
                    INSERT OR REPLACE INTO agent_attention
                        (session_id, agent_id, round_number, topic, points_spent, sensitivity)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows_to_insert,
                )
                await db.commit()

        logger.debug(
            "batch_allocate_attention session=%s round=%d agents=%d rows=%d",
            session_id,
            round_num,
            len(agent_ids),
            len(rows_to_insert),
        )

    except Exception:
        logger.exception(
            "batch_allocate_attention failed session=%s round=%d",
            session_id,
            round_num,
        )

    return budgets
