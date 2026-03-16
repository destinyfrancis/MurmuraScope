"""Structured action logger for OASIS simulation posts.

Performs rule-based sentiment detection (keyword matching) and hashtag/topic
extraction without LLM calls — suitable for high-volume per-round logging.

情感偵測和主題提取均委託至 cantonese_lexicon 模組，支援廣東話句末助詞、
否定詞及強化詞處理。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import aiosqlite

from backend.app.utils.cantonese_lexicon import (
    NEUTRAL_BOOSTERS as _NEUTRAL_BOOSTERS,
    detect_sentiment as _detect_sentiment,
    extract_topics as _extract_topics,
)
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("action_logger")

# 保留向後相容的別名，供外部直接引用這些集合的程式碼使用
from backend.app.utils.cantonese_lexicon import (
    NEGATIVE_KEYWORDS as _NEGATIVE_KEYWORDS,
    POSITIVE_KEYWORDS as _POSITIVE_KEYWORDS,
    TOPIC_PATTERNS as _TOPIC_PATTERNS,
)

_HASHTAG_RE = re.compile(r"#(\w+)")


# ---------------------------------------------------------------------------
# ActionLogger
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoggedAction:
    """Immutable record of a logged simulation action."""

    session_id: str
    round_number: int
    oasis_username: str
    content: str
    platform: str
    agent_id: int | None
    target_agent_username: str | None
    sentiment: str
    topics: list[str]
    post_id: str | None


class ActionLogger:
    """Logs simulation actions with sentiment and topic tagging to the DB.

    Supports both content actions (posts, comments, reposts) and non-content
    actions (follow, unfollow, like, lurk, mute) via ``log_action()``.
    """

    _columns_ensured: bool = False

    async def _ensure_contagion_columns(self) -> None:
        """Add parent_action_id and spread_depth columns if missing (idempotent)."""
        if self._columns_ensured:
            return
        try:
            async with get_db() as db:
                # Check if columns exist
                cursor = await db.execute("PRAGMA table_info(simulation_actions)")
                columns = {r[1] for r in await cursor.fetchall()}
                if "parent_action_id" not in columns:
                    await db.execute(
                        "ALTER TABLE simulation_actions ADD COLUMN parent_action_id INTEGER"
                    )
                if "spread_depth" not in columns:
                    await db.execute(
                        "ALTER TABLE simulation_actions ADD COLUMN spread_depth INTEGER DEFAULT 0"
                    )
                await db.commit()
            self._columns_ensured = True
        except Exception:
            logger.exception("_ensure_contagion_columns failed")

    async def _resolve_parent(
        self, session_id: str, target_username: str | None, round_number: int
    ) -> tuple[int | None, int]:
        """Resolve parent action ID and compute spread depth.

        Returns (parent_action_id, spread_depth) tuple.
        """
        if not target_username:
            return None, 0
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT id, COALESCE(spread_depth, 0) as depth
                       FROM simulation_actions
                       WHERE session_id = ? AND oasis_username = ? AND round_number <= ?
                       ORDER BY round_number DESC, id DESC LIMIT 1""",
                    (session_id, target_username, round_number),
                )
                row = await cursor.fetchone()
                if row:
                    return row[0], row[1] + 1
        except Exception:
            logger.exception("_resolve_parent failed session=%s target=%s", session_id, target_username)
        return None, 0

    async def log_post(
        self,
        session_id: str,
        round_number: int,
        oasis_username: str,
        content: str,
        platform: str = "twitter",
        agent_id: int | None = None,
        target_agent_username: str | None = None,
        post_id: str | None = None,
    ) -> LoggedAction:
        """Analyse and persist a single post to simulation_actions.

        Args:
            session_id: Owning simulation session UUID.
            round_number: Current simulation round.
            oasis_username: OASIS username of the posting agent.
            content: Post text.
            platform: "twitter" or "reddit".
            agent_id: Optional internal agent_profiles.id.
            target_agent_username: Username of replied-to agent if any.
            post_id: Optional OASIS post ID for dedup.

        Returns:
            Immutable LoggedAction record.
        """
        sentiment = _detect_sentiment(content)
        topics = _extract_topics(content)

        action = LoggedAction(
            session_id=session_id,
            round_number=round_number,
            oasis_username=oasis_username,
            content=content,
            platform=platform,
            agent_id=agent_id,
            target_agent_username=target_agent_username,
            sentiment=sentiment,
            topics=topics,
            post_id=post_id,
        )

        await self._ensure_contagion_columns()
        parent_id, spread_depth = await self._resolve_parent(
            session_id, target_agent_username, round_number
        )

        try:
            async with get_db() as db:
                await db.execute(
                    """
                    INSERT INTO simulation_actions
                        (session_id, round_number, agent_id, oasis_username,
                         action_type, platform, content, target_agent_username,
                         sentiment, topics, post_id,
                         parent_action_id, spread_depth)
                    VALUES (?, ?, ?, ?, 'post', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        round_number,
                        agent_id,
                        oasis_username,
                        platform,
                        content,
                        target_agent_username,
                        sentiment,
                        json.dumps(topics, ensure_ascii=False),
                        post_id,
                        parent_id,
                        spread_depth,
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to log action for session=%s round=%d user=%s",
                session_id,
                round_number,
                oasis_username,
            )

        return action

    async def log_action(
        self,
        session_id: str,
        round_number: int,
        oasis_username: str,
        action_type: str,
        platform: str = "twitter",
        agent_id: int | None = None,
        target_agent_username: str | None = None,
        content: str = "",
        info: dict | None = None,
    ) -> LoggedAction:
        """Log any action type (follow, like, lurk, etc.) to simulation_actions.

        For content actions (create_post, repost, quote_post, create_comment),
        sentiment and topic analysis is performed on the content.
        For non-content actions, sentiment defaults to 'neutral' and topics
        is empty.

        Args:
            session_id: Owning simulation session UUID.
            round_number: Current simulation round.
            oasis_username: OASIS username of the acting agent.
            action_type: Action type string (e.g. 'follow', 'like_post', 'do_nothing').
            platform: Platform identifier.
            agent_id: Optional internal agent_profiles.id.
            target_agent_username: Username of the target agent (for follow/like).
            content: Post text (empty for non-content actions).
            info: Optional dict of action-specific metadata from OASIS trace.

        Returns:
            Immutable LoggedAction record.
        """
        _content_actions = {"create_post", "repost", "quote_post", "create_comment", "post"}

        if action_type in _content_actions and content:
            sentiment = _detect_sentiment(content)
            topics = _extract_topics(content)
        else:
            sentiment = "neutral"
            topics = []

        # For non-content actions, store info JSON as content if no text
        stored_content = content
        if not stored_content and info:
            stored_content = json.dumps(info, ensure_ascii=False)[:300]

        action = LoggedAction(
            session_id=session_id,
            round_number=round_number,
            oasis_username=oasis_username,
            content=stored_content,
            platform=platform,
            agent_id=agent_id,
            target_agent_username=target_agent_username,
            sentiment=sentiment,
            topics=topics,
            post_id=None,
        )

        await self._ensure_contagion_columns()

        try:
            async with get_db() as db:
                await db.execute(
                    """
                    INSERT INTO simulation_actions
                        (session_id, round_number, agent_id, oasis_username,
                         action_type, platform, content, target_agent_username,
                         sentiment, topics, post_id,
                         parent_action_id, spread_depth)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        round_number,
                        agent_id,
                        oasis_username,
                        action_type,
                        platform,
                        stored_content,
                        target_agent_username,
                        sentiment,
                        json.dumps(topics, ensure_ascii=False),
                        None,
                        None,
                        0,
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to log action %s for session=%s round=%d user=%s",
                action_type,
                session_id,
                round_number,
                oasis_username,
            )

        return action

    async def log_batch(
        self,
        actions: list[dict],
    ) -> int:
        """Batch-insert pre-analysed action records.

        Args:
            actions: List of dicts with keys matching simulation_actions columns.

        Returns:
            Number of rows inserted.
        """
        await self._ensure_contagion_columns()
        if not actions:
            return 0

        rows = []
        for a in actions:
            content = a.get("content", "")
            sentiment = a.get("sentiment") or _detect_sentiment(content)
            topics = a.get("topics") or _extract_topics(content)
            rows.append((
                a["session_id"],
                a["round_number"],
                a.get("agent_id"),
                a["oasis_username"],
                a.get("action_type", "post"),
                a.get("platform", "twitter"),
                content,
                a.get("target_agent_username"),
                sentiment,
                json.dumps(topics if isinstance(topics, list) else [], ensure_ascii=False),
                a.get("post_id"),
                a.get("parent_action_id"),
                a.get("spread_depth", 0),
            ))

        try:
            async with get_db() as db:
                await db.executemany(
                    """
                    INSERT INTO simulation_actions
                        (session_id, round_number, agent_id, oasis_username,
                         action_type, platform, content, target_agent_username,
                         sentiment, topics, post_id,
                         parent_action_id, spread_depth)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                await db.commit()
            return len(rows)
        except Exception:
            logger.exception("batch log_action failed")
            return 0

    async def get_round_actions(
        self,
        session_id: str,
        round_number: int | None = None,
        platform: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Fetch logged actions for a session, optionally filtered.

        Args:
            session_id: Session UUID.
            round_number: If given, only return actions from this round.
            platform: If given, filter by platform.
            limit: Max rows to return.

        Returns:
            List of action dicts.
        """
        conditions = ["session_id = ?"]
        params: list = [session_id]

        if round_number is not None:
            conditions.append("round_number = ?")
            params.append(round_number)

        if platform is not None:
            conditions.append("platform = ?")
            params.append(platform)

        where = " AND ".join(conditions)
        params.append(limit)

        try:
            async with get_db() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    f"SELECT * FROM simulation_actions WHERE {where}"
                    f" ORDER BY round_number, id LIMIT ?",
                    params,
                )
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            logger.exception("get_round_actions failed for session=%s", session_id)
            return []

    async def get_sentiment_summary(
        self,
        session_id: str,
    ) -> dict[str, dict[str, int]]:
        """Return sentiment counts per round for a session.

        Returns:
            Dict mapping round_number str → {"positive": N, "negative": N, "neutral": N}
        """
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT round_number, sentiment, COUNT(*) as cnt
                    FROM simulation_actions
                    WHERE session_id = ?
                    GROUP BY round_number, sentiment
                    ORDER BY round_number
                    """,
                    (session_id,),
                )
                rows = await cursor.fetchall()

            result: dict[str, dict[str, int]] = {}
            for row in rows:
                rn = str(row[0])
                sent = row[1]
                cnt = row[2]
                if rn not in result:
                    result[rn] = {"positive": 0, "negative": 0, "neutral": 0}
                result[rn][sent] = cnt
            return result
        except Exception:
            logger.exception("get_sentiment_summary failed for session=%s", session_id)
            return {}

    async def rescore_batch_with_transformer(
        self,
        session_id: str,
        round_number: int | None = None,
    ) -> int:
        """Post-hoc batch rescore sentiment using Transformer model.

        Runs after each round completes (not in real-time) to improve accuracy.
        Keyword fast-path remains for real-time logging; Transformer corrects
        cases where keyword confidence was low or mixed signals detected.

        Returns number of rows updated.
        """
        try:
            from backend.app.services.sentiment_analyzer import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
        except ImportError:
            logger.debug("SentimentAnalyzer not available — skipping batch rescore")
            return 0

        try:
            async with get_db() as db:
                conditions = ["session_id = ?"]
                params: list = [session_id]
                if round_number is not None:
                    conditions.append("round_number = ?")
                    params.append(round_number)

                cursor = await db.execute(
                    f"SELECT id, content FROM simulation_actions WHERE {' AND '.join(conditions)}",
                    params,
                )
                rows = await cursor.fetchall()

            if not rows:
                return 0

            texts = [r[1] for r in rows]
            ids = [r[0] for r in rows]
            results = analyzer.analyze_batch(texts)

            updated = 0
            async with get_db() as db:
                for row_id, result in zip(ids, results):
                    await db.execute(
                        "UPDATE simulation_actions SET sentiment = ? WHERE id = ?",
                        (result.label, row_id),
                    )
                    updated += 1
                await db.commit()

            logger.info(
                "Transformer rescore: session=%s round=%s updated=%d",
                session_id, round_number, updated,
            )
            return updated

        except Exception:
            logger.exception("rescore_batch_with_transformer failed session=%s", session_id)
            return 0
