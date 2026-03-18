"""Zep-style dynamic knowledge graph evolution from agent activities.

Inspired by MiroFish's ZepGraphMemoryUpdater, this service:
1. Converts agent actions (posts, likes, follows, decisions) into
   natural-language activity descriptions.
2. Batches descriptions and extracts new entities + relationships via LLM.
3. Injects discovered entities/edges into the local kg_nodes/kg_edges tables.

Unlike MiroFish (which delegates to Zep Cloud), we do everything locally:
- Entity extraction via LLM (same provider as other services)
- Storage in SQLite (kg_nodes, kg_edges)
- Deduplication via node title matching + edge UPSERT

Usage::

    updater = KGGraphUpdater()
    stats = await updater.process_round(session_id, round_number)
    # stats = KGEvolutionStats(nodes_added=3, edges_added=5, ...)
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("kg_graph_updater")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Max actions to process per round (avoid LLM overload)
_MAX_ACTIONS_PER_ROUND = 50

# Batch size for LLM entity extraction (group N descriptions per call)
_LLM_BATCH_SIZE = 10

# Minimum content length to consider for entity extraction
_MIN_CONTENT_LENGTH = 15

# Action types that produce meaningful activity descriptions
_CONTENT_ACTIONS = frozenset({
    "post", "create_post", "repost", "quote_post", "create_comment",
})
_SOCIAL_ACTIONS = frozenset({
    "follow", "unfollow", "like_post", "like", "dislike_post",
    "mute", "unmute",
})
_DECISION_ACTIONS = frozenset({
    "buy_property", "emigrate", "invest", "have_child",
    "adjust_spending", "employment_change",
})

# Relation types discoverable from agent activities
_ACTIVITY_RELATION_TYPES = (
    "AGREES_WITH",
    "DISAGREES_WITH",
    "RESPONDS_TO",
    "MENTIONS",
    "SUPPORTS",
    "OPPOSES",
    "INFLUENCED_BY",
    "CONCERNED_ABOUT",
    "ADVOCATES_FOR",
    "CRITICISES",
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivityDescription:
    """A natural-language description of an agent activity."""

    agent_username: str
    agent_id: int | None
    round_number: int
    action_type: str
    description: str
    sentiment: str
    topics: list[str]


@dataclass(frozen=True)
class KGEvolutionStats:
    """Statistics from a single round of KG evolution."""

    round_number: int
    actions_processed: int
    descriptions_generated: int
    nodes_added: int
    nodes_updated: int
    edges_added: int
    edges_updated: int


# ---------------------------------------------------------------------------
# Activity description generators (Zep-style)
# ---------------------------------------------------------------------------


def _describe_post(username: str, content: str, sentiment: str, topics: list[str]) -> str:
    """Generate natural-language description of a post activity."""
    topic_str = "、".join(topics) if topics else "一般話題"
    sentiment_zh = {"positive": "正面", "negative": "負面", "neutral": "中立"}.get(
        sentiment, "中立"
    )
    # Truncate content for LLM context efficiency
    short_content = content[:200] + "..." if len(content) > 200 else content
    return (
        f"{username} 發佈了一則{sentiment_zh}帖文，"
        f"討論{topic_str}：「{short_content}」"
    )


def _describe_social_action(
    username: str,
    action_type: str,
    target_username: str | None,
    content: str,
) -> str:
    """Generate natural-language description of a social action."""
    action_zh = {
        "follow": "關注了",
        "unfollow": "取消關注了",
        "like_post": "讚好了",
        "like": "讚好了",
        "dislike_post": "反對了",
        "mute": "封鎖了",
        "unmute": "解除封鎖了",
    }.get(action_type, "互動了")

    target = target_username or "某用戶"

    if action_type in ("like_post", "like", "dislike_post") and content:
        short = content[:100] + "..." if len(content) > 100 else content
        return f"{username} {action_zh}{target}的帖文：「{short}」"
    return f"{username} {action_zh}{target}"


def _describe_decision(
    username: str,
    decision_type: str,
    action_taken: str,
    reasoning: str,
) -> str:
    """Generate natural-language description of a life decision."""
    decision_zh = {
        "buy_property": "置業決策",
        "emigrate": "移民決策",
        "invest": "投資決策",
        "have_child": "生育決策",
        "adjust_spending": "消費調整",
        "employment_change": "就業變動",
    }.get(decision_type, "生活決策")

    action_zh = {
        "buy": "決定買樓", "wait": "決定觀望", "sell": "決定賣樓",
        "rent_more": "決定繼續租樓",
        "emigrate": "決定移民", "stay": "決定留港",
        "invest_stocks": "決定投資股票", "diversify": "決定分散投資",
        "hold_cash": "決定持有現金",
        "have_child": "決定生育", "delay": "決定推遲生育",
        "no_child": "決定不生育",
        "cut_spending": "決定減少開支", "save_more": "決定增加儲蓄",
        "spend_more": "決定增加消費", "upgrade": "決定消費升級",
        "quit": "決定辭職", "strike": "決定罷工",
        "lie_flat": "決定躺平", "seek_promotion": "決定爭取晉升",
    }.get(action_taken, action_taken)

    short_reason = reasoning[:150] + "..." if len(reasoning) > 150 else reasoning
    return f"{username} 作出了{decision_zh}：{action_zh}。原因：{short_reason}"


# ---------------------------------------------------------------------------
# LLM prompt for entity/relation extraction from activities
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM_PROMPT = """\
你是一個知識圖譜實體提取專家。從社交模擬中的代理人活動描述中，提取：
1. 新出現的實體（人物、機構、事件、議題、地點、政策）
2. 實體之間的關係

規則：
- 只提取明確出現在文本中的實體，不要猜測
- 實體類型限制為：Person, Organization, Event, Issue, Location, Policy
- 關係類型限制為：AGREES_WITH, DISAGREES_WITH, RESPONDS_TO, MENTIONS, \
SUPPORTS, OPPOSES, INFLUENCED_BY, CONCERNED_ABOUT, ADVOCATES_FOR, CRITICISES
- 每個實體必須有 id（英文小寫+下劃線）、title（原文名稱）、entity_type、description
- 每條邊必須有 source_id、target_id、relation_type、description、weight (0.1-1.0)
- 如果某個實體已存在於既有圖譜中，用 existing_id 引用它而非創建新節點
- weight 反映關係強度：偶然提及=0.2, 明確立場=0.5, 強烈互動=0.8

回覆格式（JSON）：
{
  "new_nodes": [{"id": "...", "entity_type": "...", "title": "...", "description": "..."}],
  "new_edges": [{"source_id": "...", "target_id": "...", "relation_type": "...", "description": "...", "weight": 0.5}],
  "updated_edges": [{"source_id": "...", "target_id": "...", "relation_type": "...", "new_weight": 0.7}]
}

如果活動描述中沒有可提取的實體或關係，返回空列表。"""

_EXTRACTION_USER_TEMPLATE = """\
既有圖譜節點：
{existing_nodes_json}

本回合代理人活動描述：
{activity_descriptions}

請從活動描述中提取新實體和關係。"""


# ---------------------------------------------------------------------------
# KGGraphUpdater
# ---------------------------------------------------------------------------


class KGGraphUpdater:
    """Converts agent activities into KG entities and relationships.

    Mirrors MiroFish's ZepGraphMemoryUpdater pattern but operates entirely
    locally with SQLite + LLM extraction.
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        provider: str = "fireworks",
    ) -> None:
        self._llm = llm_client
        self._provider = provider

    def _get_llm(self) -> Any:
        """Lazy-load LLM client to avoid circular imports."""
        if self._llm is None:
            from backend.app.utils.llm_client import LLMClient  # noqa: PLC0415
            self._llm = LLMClient()
        return self._llm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_round(
        self,
        session_id: str,
        round_number: int,
    ) -> KGEvolutionStats:
        """Process all agent activities from a round and evolve the KG.

        Steps:
            1. Load actions from simulation_actions for this round.
            2. Load decisions from agent_decisions for this round.
            3. Convert to natural-language activity descriptions.
            4. Batch-extract entities/relations via LLM.
            5. Deduplicate against existing kg_nodes.
            6. INSERT new nodes + edges; UPDATE existing edge weights.

        Returns:
            KGEvolutionStats with counts of nodes/edges added/updated.
        """
        # Step 1+2: Load round data
        actions = await self._load_round_actions(session_id, round_number)
        decisions = await self._load_round_decisions(session_id, round_number)

        # Step 3: Generate activity descriptions
        descriptions = self._generate_descriptions(actions, decisions, round_number)

        if not descriptions:
            return KGEvolutionStats(
                round_number=round_number,
                actions_processed=len(actions) + len(decisions),
                descriptions_generated=0,
                nodes_added=0,
                nodes_updated=0,
                edges_added=0,
                edges_updated=0,
            )

        # Step 4: Load existing nodes for dedup context
        existing_nodes = await self._load_existing_nodes(session_id)

        # Step 5: Batch LLM extraction
        all_new_nodes: list[dict[str, Any]] = []
        all_new_edges: list[dict[str, Any]] = []
        all_updated_edges: list[dict[str, Any]] = []

        for batch_start in range(0, len(descriptions), _LLM_BATCH_SIZE):
            batch = descriptions[batch_start:batch_start + _LLM_BATCH_SIZE]
            batch_text = "\n".join(
                f"- {d.description}" for d in batch
            )

            try:
                result = await self._extract_entities(
                    existing_nodes, batch_text, session_id
                )
                all_new_nodes.extend(result.get("new_nodes", []))
                all_new_edges.extend(result.get("new_edges", []))
                all_updated_edges.extend(result.get("updated_edges", []))
            except Exception:
                logger.exception(
                    "LLM extraction failed for batch session=%s round=%d",
                    session_id, round_number,
                )

        # Step 6: Persist to DB
        nodes_added, nodes_updated = await self._persist_nodes(
            session_id, all_new_nodes, existing_nodes
        )
        edges_added = await self._persist_new_edges(session_id, all_new_edges, round_number=round_number)
        edges_updated = await self._persist_edge_updates(
            session_id, all_updated_edges
        )

        stats = KGEvolutionStats(
            round_number=round_number,
            actions_processed=len(actions) + len(decisions),
            descriptions_generated=len(descriptions),
            nodes_added=nodes_added,
            nodes_updated=nodes_updated,
            edges_added=edges_added,
            edges_updated=edges_updated,
        )

        logger.info(
            "KG evolution session=%s round=%d: +%d nodes, +%d edges, ~%d edge updates",
            session_id, round_number, nodes_added, edges_added, edges_updated,
        )

        return stats

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_round_actions(
        self, session_id: str, round_number: int
    ) -> list[dict[str, Any]]:
        """Load simulation_actions for the given round."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT oasis_username, action_type, content,
                              sentiment, topics, target_agent_username, agent_id
                       FROM simulation_actions
                       WHERE session_id = ? AND round_number = ?
                       ORDER BY id
                       LIMIT ?""",
                    (session_id, round_number, _MAX_ACTIONS_PER_ROUND),
                )
                rows = await cursor.fetchall()
            return [
                {
                    "username": r[0],
                    "action_type": r[1],
                    "content": r[2] or "",
                    "sentiment": r[3] or "neutral",
                    "topics": json.loads(r[4]) if r[4] else [],
                    "target_username": r[5],
                    "agent_id": r[6],
                }
                for r in rows
            ]
        except Exception:
            logger.exception(
                "_load_round_actions failed session=%s round=%d",
                session_id, round_number,
            )
            return []

    async def _load_round_decisions(
        self, session_id: str, round_number: int
    ) -> list[dict[str, Any]]:
        """Load agent_decisions for the given round."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT agent_id, decision_type, action, reasoning, oasis_username
                       FROM agent_decisions
                       WHERE session_id = ? AND round_number = ?""",
                    (session_id, round_number),
                )
                rows = await cursor.fetchall()
            return [
                {
                    "agent_id": r[0],
                    "decision_type": r[1],
                    "action": r[2],
                    "reasoning": r[3] or "",
                    "username": r[4] or f"agent_{r[0]}",
                }
                for r in rows
            ]
        except Exception:
            logger.debug(
                "_load_round_decisions failed (table may not exist) session=%s round=%d",
                session_id, round_number,
            )
            return []

    async def _load_existing_nodes(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """Load all existing kg_nodes for dedup context."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT id, entity_type, title, description "
                    "FROM kg_nodes WHERE session_id = ? LIMIT 200",
                    (session_id,),
                )
                rows = await cursor.fetchall()
            return [
                {"id": r[0], "entity_type": r[1], "title": r[2], "description": r[3] or ""}
                for r in rows
            ]
        except Exception:
            logger.exception(
                "_load_existing_nodes failed session=%s", session_id,
            )
            return []

    # ------------------------------------------------------------------
    # Description generation (Zep-style)
    # ------------------------------------------------------------------

    def _generate_descriptions(
        self,
        actions: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        round_number: int,
    ) -> list[ActivityDescription]:
        """Convert raw actions + decisions into natural-language descriptions."""
        descriptions: list[ActivityDescription] = []

        for action in actions:
            username = action["username"]
            action_type = action["action_type"]
            content = action["content"]
            sentiment = action["sentiment"]
            topics = action["topics"]
            target = action.get("target_username")

            if action_type in _CONTENT_ACTIONS and len(content) >= _MIN_CONTENT_LENGTH:
                desc_text = _describe_post(username, content, sentiment, topics)
                descriptions.append(ActivityDescription(
                    agent_username=username,
                    agent_id=action.get("agent_id"),
                    round_number=round_number,
                    action_type=action_type,
                    description=desc_text,
                    sentiment=sentiment,
                    topics=topics,
                ))
            elif action_type in _SOCIAL_ACTIONS and target:
                desc_text = _describe_social_action(
                    username, action_type, target, content
                )
                descriptions.append(ActivityDescription(
                    agent_username=username,
                    agent_id=action.get("agent_id"),
                    round_number=round_number,
                    action_type=action_type,
                    description=desc_text,
                    sentiment=sentiment,
                    topics=topics,
                ))

        for decision in decisions:
            desc_text = _describe_decision(
                decision["username"],
                decision["decision_type"],
                decision["action"],
                decision["reasoning"],
            )
            descriptions.append(ActivityDescription(
                agent_username=decision["username"],
                agent_id=decision["agent_id"],
                round_number=round_number,
                action_type=decision["decision_type"],
                description=desc_text,
                sentiment="neutral",
                topics=[decision["decision_type"]],
            ))

        return descriptions

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    async def _extract_entities(
        self,
        existing_nodes: list[dict[str, Any]],
        activity_text: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Call LLM to extract entities and relations from activity descriptions."""
        existing_summary = [
            {"id": n["id"], "title": n["title"], "entity_type": n["entity_type"]}
            for n in existing_nodes[:100]  # Cap context size
        ]

        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _EXTRACTION_USER_TEMPLATE.format(
                    existing_nodes_json=json.dumps(
                        existing_summary, ensure_ascii=False, indent=2
                    ),
                    activity_descriptions=activity_text,
                ),
            },
        ]

        llm = self._get_llm()
        result = await llm.chat_json(
            messages,
            provider=self._provider,
            temperature=0.3,
            max_tokens=2048,
        )

        # Validate + prefix node IDs
        prefix = session_id[:8] + "_"
        new_nodes = result.get("new_nodes", [])
        for node in new_nodes:
            if not node.get("id", "").startswith(prefix):
                node["id"] = prefix + node.get("id", uuid.uuid4().hex[:8])

        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_nodes(
        self,
        session_id: str,
        new_nodes: list[dict[str, Any]],
        existing_nodes: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Persist new nodes with deduplication by title.

        Returns (nodes_added, nodes_updated) counts.
        """
        if not new_nodes:
            return 0, 0

        existing_titles = {n["title"].lower().strip() for n in existing_nodes}
        existing_ids = {n["id"] for n in existing_nodes}

        to_insert: list[dict[str, Any]] = []
        updated = 0

        for node in new_nodes:
            title = node.get("title", "").strip()
            if not title:
                continue

            node_id = node.get("id", "")
            entity_type = node.get("entity_type", "Entity")
            description = node.get("description", "")

            if title.lower() in existing_titles:
                # Update existing node description if new info available
                if description:
                    try:
                        async with get_db() as db:
                            await db.execute(
                                """UPDATE kg_nodes
                                   SET description = description || ' | ' || ?
                                   WHERE session_id = ? AND LOWER(title) = ?""",
                                (description[:200], session_id, title.lower()),
                            )
                            await db.commit()
                        updated += 1
                    except Exception:
                        logger.debug("Node description update failed for %s", title)
                continue

            if node_id in existing_ids:
                node_id = f"{node_id}_{uuid.uuid4().hex[:6]}"

            to_insert.append({
                "id": node_id,
                "entity_type": entity_type,
                "title": title,
                "description": description,
            })
            existing_titles.add(title.lower())
            existing_ids.add(node_id)

        if to_insert:
            try:
                async with get_db() as db:
                    await db.executemany(
                        """INSERT OR IGNORE INTO kg_nodes
                           (id, session_id, entity_type, title, description, properties)
                           VALUES (?, ?, ?, ?, ?, '{}')""",
                        [
                            (n["id"], session_id, n["entity_type"],
                             n["title"], n["description"])
                            for n in to_insert
                        ],
                    )
                    await db.commit()
            except Exception:
                logger.exception("_persist_nodes INSERT failed session=%s", session_id)
                return 0, updated

        return len(to_insert), updated

    async def _persist_new_edges(
        self,
        session_id: str,
        new_edges: list[dict[str, Any]],
        round_number: int = 0,
    ) -> int:
        """Persist new edges with validation.

        Args:
            session_id: The simulation session owning these edges.
            new_edges: Raw edge dicts from LLM extraction.
            round_number: The simulation round that produced these edges.
                          Stored on each row for temporal topic evolution queries.
        """
        if not new_edges:
            return 0

        # Load valid node IDs for validation
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT id FROM kg_nodes WHERE session_id = ?",
                    (session_id,),
                )
                valid_ids = {r[0] for r in await cursor.fetchall()}
        except Exception:
            logger.exception("_persist_new_edges: failed to load node IDs")
            return 0

        validated: list[tuple[str, str, str, str, str, float, int]] = []
        for edge in new_edges:
            src = edge.get("source_id", "")
            tgt = edge.get("target_id", "")
            rel = edge.get("relation_type", "")

            if src not in valid_ids or tgt not in valid_ids:
                continue
            if rel not in _ACTIVITY_RELATION_TYPES:
                continue

            weight = edge.get("weight", 0.5)
            if not isinstance(weight, (int, float)):
                weight = 0.5
            weight = max(0.1, min(1.0, float(weight)))

            validated.append((
                session_id, src, tgt, rel,
                edge.get("description", ""), weight, round_number,
            ))

        if not validated:
            return 0

        try:
            async with get_db() as db:
                await db.executemany(
                    """INSERT INTO kg_edges
                       (session_id, source_id, target_id, relation_type, description, weight, round_number)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    validated,
                )
                await db.commit()
            return len(validated)
        except Exception:
            logger.exception("_persist_new_edges INSERT failed session=%s", session_id)
            return 0

    async def _persist_edge_updates(
        self,
        session_id: str,
        updated_edges: list[dict[str, Any]],
    ) -> int:
        """Update existing edge weights."""
        if not updated_edges:
            return 0

        count = 0
        try:
            async with get_db() as db:
                for edge in updated_edges:
                    new_weight = edge.get("new_weight", 0.5)
                    if not isinstance(new_weight, (int, float)):
                        continue
                    new_weight = max(0.1, min(1.0, float(new_weight)))

                    result = await db.execute(
                        """UPDATE kg_edges SET weight = ?
                           WHERE session_id = ? AND source_id = ?
                           AND target_id = ? AND relation_type = ?""",
                        (
                            new_weight,
                            session_id,
                            edge.get("source_id", ""),
                            edge.get("target_id", ""),
                            edge.get("relation_type", ""),
                        ),
                    )
                    if result.rowcount and result.rowcount > 0:
                        count += 1
                await db.commit()
        except Exception:
            logger.exception(
                "_persist_edge_updates failed session=%s", session_id
            )

        return count
