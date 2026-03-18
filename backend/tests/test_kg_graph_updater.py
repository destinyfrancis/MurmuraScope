"""Tests for KGGraphUpdater service.

Tests cover:
- Activity description generators (_describe_post, _describe_social_action, _describe_decision)
- _generate_descriptions filtering logic
- _persist_nodes deduplication
- _persist_new_edges validation (relation_type guard, weight clamping)
- KGEvolutionStats frozen dataclass

Uses an in-memory aiosqlite database patched into get_db.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import aiosqlite
import pytest
import pytest_asyncio

from backend.app.services.kg_graph_updater import (
    KGEvolutionStats,
    KGGraphUpdater,
    ActivityDescription,
    _describe_decision,
    _describe_post,
    _describe_social_action,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CREATE_KG_NODES = """
CREATE TABLE IF NOT EXISTS kg_nodes (
    id TEXT,
    session_id TEXT,
    entity_type TEXT,
    title TEXT,
    description TEXT,
    properties TEXT
)
"""

_CREATE_KG_EDGES = """
CREATE TABLE IF NOT EXISTS kg_edges (
    session_id TEXT,
    source_id TEXT,
    target_id TEXT,
    relation_type TEXT,
    description TEXT,
    weight REAL,
    round_number INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_SIMULATION_ACTIONS = """
CREATE TABLE IF NOT EXISTS simulation_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    round_number INT,
    agent_id INT,
    oasis_username TEXT,
    action_type TEXT,
    platform TEXT,
    content TEXT,
    target_agent_username TEXT,
    sentiment TEXT,
    topics TEXT,
    post_id TEXT,
    parent_action_id INT,
    spread_depth INT
)
"""

_CREATE_AGENT_DECISIONS = """
CREATE TABLE IF NOT EXISTS agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    round_number INT,
    agent_id INT,
    decision_type TEXT,
    action TEXT,
    reasoning TEXT,
    oasis_username TEXT
)
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_setup():
    """Create an in-memory aiosqlite DB and patch get_db to use it."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    await conn.execute(_CREATE_KG_NODES)
    await conn.execute(_CREATE_KG_EDGES)
    await conn.execute(_CREATE_SIMULATION_ACTIONS)
    await conn.execute(_CREATE_AGENT_DECISIONS)
    await conn.commit()

    @asynccontextmanager
    async def _mock_get_db():
        yield conn

    with patch("backend.app.services.kg_graph_updater.get_db", _mock_get_db):
        yield conn

    await conn.close()


# ---------------------------------------------------------------------------
# _describe_post
# ---------------------------------------------------------------------------


def test_describe_post_positive():
    result = _describe_post("alice", "樓市大升", "positive", ["樓市"])
    assert "正面" in result


def test_describe_post_negative():
    result = _describe_post("bob", "股市急跌令人憂慮", "negative", ["股市"])
    assert "負面" in result


def test_describe_post_truncates_long_content():
    long_content = "香" * 250
    result = _describe_post("charlie", long_content, "neutral", [])
    assert "..." in result


# ---------------------------------------------------------------------------
# _describe_social_action
# ---------------------------------------------------------------------------


def test_describe_social_action_follow():
    result = _describe_social_action("alice", "follow", "bob", "")
    assert "關注了" in result


def test_describe_social_action_like_with_content():
    content = "政府宣布新措施應對樓市"
    result = _describe_social_action("alice", "like_post", "bob", content)
    # Should contain an excerpt of the content
    assert "政府宣布新措施" in result


# ---------------------------------------------------------------------------
# _describe_decision
# ---------------------------------------------------------------------------


def test_describe_decision_emigrate():
    result = _describe_decision("dave", "emigrate", "emigrate", "前景不明朗")
    assert "移民決策" in result


def test_describe_decision_buy_property():
    result = _describe_decision("eve", "buy_property", "buy", "利率低適合入市")
    assert "置業決策" in result


# ---------------------------------------------------------------------------
# _generate_descriptions
# ---------------------------------------------------------------------------


def test_generate_descriptions_filters_short_content():
    """Content actions with content < 15 chars must be excluded."""
    updater = KGGraphUpdater(llm_client=None)
    actions = [
        {
            "username": "user1",
            "action_type": "post",
            "content": "短",  # 1 char — below threshold
            "sentiment": "neutral",
            "topics": [],
            "target_username": None,
            "agent_id": 1,
        }
    ]
    descriptions = updater._generate_descriptions(actions, [], round_number=1)
    assert len(descriptions) == 0


def test_generate_descriptions_includes_decisions():
    """Decisions are always included regardless of content length."""
    updater = KGGraphUpdater(llm_client=None)
    decisions = [
        {
            "username": "user2",
            "decision_type": "emigrate",
            "action": "emigrate",
            "reasoning": "未來唔明朗",
            "agent_id": 2,
        }
    ]
    descriptions = updater._generate_descriptions([], decisions, round_number=1)
    assert len(descriptions) == 1
    assert descriptions[0].action_type == "emigrate"


# ---------------------------------------------------------------------------
# _persist_nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_nodes_deduplication(db_setup):
    """Inserting a node with the same title twice — second is skipped."""
    conn = db_setup
    session_id = "sess_dedup"

    updater = KGGraphUpdater(llm_client=None)

    # Seed existing node
    existing_nodes = [
        {"id": "sess_ddu_node1", "entity_type": "Person", "title": "李小明", "description": ""}
    ]

    # Try to insert same title again
    new_nodes = [
        {"id": "sess_ddu_node2", "entity_type": "Person", "title": "李小明", "description": "更多資料"}
    ]

    nodes_added, nodes_updated = await updater._persist_nodes(
        session_id, new_nodes, existing_nodes
    )

    # Node with duplicate title must not be inserted
    assert nodes_added == 0
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM kg_nodes WHERE session_id = ?", (session_id,)
    )
    row = await cursor.fetchone()
    assert row[0] == 0  # Nothing was inserted


# ---------------------------------------------------------------------------
# _persist_new_edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_new_edges_validates_relation_type(db_setup):
    """Edges with an invalid relation_type must be rejected."""
    conn = db_setup
    session_id = "sess_edge_val"

    # Insert two valid nodes first
    await conn.execute(
        "INSERT INTO kg_nodes (id, session_id, entity_type, title, description, properties) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("node_a", session_id, "Person", "Node A", "", "{}"),
    )
    await conn.execute(
        "INSERT INTO kg_nodes (id, session_id, entity_type, title, description, properties) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("node_b", session_id, "Person", "Node B", "", "{}"),
    )
    await conn.commit()

    updater = KGGraphUpdater(llm_client=None)

    invalid_edges = [
        {
            "source_id": "node_a",
            "target_id": "node_b",
            "relation_type": "INVALID_TYPE",
            "description": "bad edge",
            "weight": 0.5,
        }
    ]
    edges_added = await updater._persist_new_edges(session_id, invalid_edges)
    assert edges_added == 0

    cursor = await conn.execute(
        "SELECT COUNT(*) FROM kg_edges WHERE session_id = ?", (session_id,)
    )
    row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_persist_new_edges_clamps_weight(db_setup):
    """Weights outside [0.1, 1.0] must be clamped before insertion."""
    conn = db_setup
    session_id = "sess_edge_clamp"

    await conn.execute(
        "INSERT INTO kg_nodes (id, session_id, entity_type, title, description, properties) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("node_x", session_id, "Issue", "Node X", "", "{}"),
    )
    await conn.execute(
        "INSERT INTO kg_nodes (id, session_id, entity_type, title, description, properties) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("node_y", session_id, "Issue", "Node Y", "", "{}"),
    )
    await conn.commit()

    updater = KGGraphUpdater(llm_client=None)

    edges = [
        # weight > 1.0 → clamped to 1.0
        {
            "source_id": "node_x",
            "target_id": "node_y",
            "relation_type": "AGREES_WITH",
            "description": "strong agreement",
            "weight": 5.0,
        },
        # weight < 0.1 → clamped to 0.1
        {
            "source_id": "node_y",
            "target_id": "node_x",
            "relation_type": "MENTIONS",
            "description": "weak mention",
            "weight": 0.0,
        },
    ]

    edges_added = await updater._persist_new_edges(session_id, edges)
    assert edges_added == 2

    cursor = await conn.execute(
        "SELECT weight FROM kg_edges WHERE session_id = ? ORDER BY weight DESC",
        (session_id,),
    )
    rows = await cursor.fetchall()
    weights = [r[0] for r in rows]

    assert weights[0] == pytest.approx(1.0)
    assert weights[1] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# KGEvolutionStats frozen
# ---------------------------------------------------------------------------


def test_kg_evolution_stats_frozen():
    """KGEvolutionStats must be immutable — assignment raises FrozenInstanceError."""
    stats = KGEvolutionStats(
        round_number=1,
        actions_processed=10,
        descriptions_generated=5,
        nodes_added=3,
        nodes_updated=1,
        edges_added=4,
        edges_updated=2,
    )
    with pytest.raises(FrozenInstanceError):
        stats.nodes_added = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# round_number propagation — Task 3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_new_edges_writes_round_number(db_setup):
    """_persist_new_edges must store the supplied round_number on each inserted edge."""
    conn = db_setup
    session_id = "sess_rn"

    await conn.execute(
        "INSERT INTO kg_nodes (id, session_id, entity_type, title, description, properties) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("node_p", session_id, "Person", "Person P", "", "{}"),
    )
    await conn.execute(
        "INSERT INTO kg_nodes (id, session_id, entity_type, title, description, properties) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("node_q", session_id, "Person", "Person Q", "", "{}"),
    )
    await conn.commit()

    updater = KGGraphUpdater(llm_client=None)

    edges = [
        {
            "source_id": "node_p",
            "target_id": "node_q",
            "relation_type": "AGREES_WITH",
            "description": "they agree",
            "weight": 0.6,
        }
    ]
    edges_added = await updater._persist_new_edges(session_id, edges, round_number=7)
    assert edges_added == 1

    cursor = await conn.execute(
        "SELECT round_number FROM kg_edges WHERE session_id = ?", (session_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 7
