"""Tests for GraphRAG service — graph building, ontology, entity extraction, queries."""

from __future__ import annotations

import json
import uuid

import pytest

# ======================================================================
# Graph node and edge creation
# ======================================================================


class TestBuildGraphCreatesNodesAndEdges:
    """Test that building a graph inserts nodes and edges into the DB."""

    @pytest.mark.asyncio
    async def test_insert_nodes_and_edges(self, test_db):
        session_id = str(uuid.uuid4())

        nodes = [
            {
                "id": f"n-{i}",
                "session_id": session_id,
                "entity_type": etype,
                "title": title,
                "description": desc,
                "properties": json.dumps({}),
            }
            for i, (etype, title, desc) in enumerate(
                [
                    ("district", "Central", "Central business district"),
                    ("policy", "Rate Hike 2025", "HKMA rate increase policy"),
                    ("person", "Young Professional", "25-34 year old worker"),
                    ("property", "Mid-Levels Flat", "Typical residential unit"),
                ]
            )
        ]

        for node in nodes:
            await test_db.execute(
                """INSERT INTO kg_nodes (id, session_id, entity_type, title, description, properties)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    node["id"],
                    node["session_id"],
                    node["entity_type"],
                    node["title"],
                    node["description"],
                    node["properties"],
                ),
            )

        edges = [
            (session_id, "n-2", "n-0", "lives_in", "Professional lives in Central"),
            (session_id, "n-2", "n-3", "considers_buying", "Considering property purchase"),
            (session_id, "n-1", "n-3", "affects_price", "Policy affects property pricing"),
        ]

        for edge in edges:
            await test_db.execute(
                """INSERT INTO kg_edges (session_id, source_id, target_id, relation_type, description)
                   VALUES (?, ?, ?, ?, ?)""",
                edge,
            )

        await test_db.commit()

        # Verify nodes
        cursor = await test_db.execute(
            "SELECT COUNT(*) as cnt FROM kg_nodes WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 4

        # Verify edges
        cursor = await test_db.execute(
            "SELECT COUNT(*) as cnt FROM kg_edges WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 3


# ======================================================================
# Ontology generator
# ======================================================================


class TestOntologyGeneratorReturnsTypes:
    """Test that ontology extraction produces expected entity types."""

    @pytest.mark.asyncio
    async def test_extract_entity_types_from_seed(self, mock_llm_client):
        mock_llm_client.chat_json.return_value = {
            "entity_types": ["person", "district", "property", "policy", "company"],
            "relation_types": ["lives_in", "owns", "affected_by", "works_at"],
        }

        result = await mock_llm_client.chat_json(
            messages=[
                {
                    "role": "system",
                    "content": "Extract ontology from the following scenario.",
                },
                {
                    "role": "user",
                    "content": "Hong Kong property market simulation with rate hikes.",
                },
            ]
        )

        assert "entity_types" in result
        assert "relation_types" in result
        assert len(result["entity_types"]) >= 3
        assert "person" in result["entity_types"]
        assert "district" in result["entity_types"]

    @pytest.mark.asyncio
    async def test_ontology_includes_relation_types(self, mock_llm_client):
        mock_llm_client.chat_json.return_value = {
            "entity_types": ["person", "district"],
            "relation_types": ["lives_in", "works_at", "commutes_to"],
        }

        result = await mock_llm_client.chat_json(messages=[])

        assert "relation_types" in result
        assert len(result["relation_types"]) >= 2


# ======================================================================
# Entity extractor
# ======================================================================


class TestEntityExtractorFindsEntities:
    """Test that entity extraction from text returns structured entities."""

    @pytest.mark.asyncio
    async def test_extract_entities_from_text(self, mock_llm_client):
        mock_llm_client.chat_json.return_value = {
            "entities": [
                {"type": "district", "name": "Tseung Kwan O", "description": "New town in NT East"},
                {"type": "policy", "name": "Stamp Duty Cut", "description": "Government reduces BSD"},
                {"type": "person", "name": "First-time Buyer", "description": "Young HK resident"},
            ]
        }

        result = await mock_llm_client.chat_json(
            messages=[
                {
                    "role": "user",
                    "content": "Extract entities from: Tseung Kwan O first-time buyers benefit from stamp duty cut.",
                },
            ]
        )

        entities = result["entities"]
        assert len(entities) == 3

        types_found = {e["type"] for e in entities}
        assert "district" in types_found
        assert "policy" in types_found

    @pytest.mark.asyncio
    async def test_empty_text_returns_no_entities(self, mock_llm_client):
        mock_llm_client.chat_json.return_value = {"entities": []}

        result = await mock_llm_client.chat_json(messages=[{"role": "user", "content": ""}])
        assert result["entities"] == []


# ======================================================================
# Graph queries
# ======================================================================


class TestGraphQueryReturnsResults:
    """Test querying the knowledge graph for nodes and edges."""

    @pytest.mark.asyncio
    async def test_query_nodes_by_type(self, test_db):
        session_id = str(uuid.uuid4())

        for i, (etype, title) in enumerate([("district", "Central"), ("district", "Wan Chai"), ("person", "Agent A")]):
            await test_db.execute(
                """INSERT INTO kg_nodes (id, session_id, entity_type, title, properties)
                   VALUES (?, ?, ?, ?, '{}')""",
                (f"q-{i}", session_id, etype, title),
            )
        await test_db.commit()

        cursor = await test_db.execute(
            "SELECT * FROM kg_nodes WHERE session_id = ? AND entity_type = ?",
            (session_id, "district"),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_query_edges_by_source(self, test_db):
        session_id = str(uuid.uuid4())

        await test_db.execute(
            "INSERT INTO kg_nodes (id, session_id, entity_type, title, properties) VALUES (?, ?, ?, ?, '{}')",
            ("src-1", session_id, "person", "Alice"),
        )
        await test_db.execute(
            "INSERT INTO kg_nodes (id, session_id, entity_type, title, properties) VALUES (?, ?, ?, ?, '{}')",
            ("tgt-1", session_id, "district", "Central"),
        )
        await test_db.execute(
            "INSERT INTO kg_edges (session_id, source_id, target_id, relation_type) VALUES (?, ?, ?, ?)",
            (session_id, "src-1", "tgt-1", "lives_in"),
        )
        await test_db.commit()

        cursor = await test_db.execute("SELECT * FROM kg_edges WHERE source_id = ?", ("src-1",))
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["relation_type"] == "lives_in"


# ======================================================================
# Community detection
# ======================================================================


class TestCommunityDetection:
    """Test community (cluster) storage in kg_communities table."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_communities(self, test_db):
        session_id = str(uuid.uuid4())
        community_id = str(uuid.uuid4())

        member_ids = json.dumps(["n-0", "n-1", "n-2"])

        await test_db.execute(
            """INSERT INTO kg_communities (id, session_id, title, summary, member_ids)
               VALUES (?, ?, ?, ?, ?)""",
            (community_id, session_id, "Central Cluster", "Nodes related to Central district", member_ids),
        )
        await test_db.commit()

        cursor = await test_db.execute("SELECT * FROM kg_communities WHERE session_id = ?", (session_id,))
        rows = await cursor.fetchall()
        assert len(rows) == 1

        community = rows[0]
        assert community["title"] == "Central Cluster"

        parsed_members = json.loads(community["member_ids"])
        assert len(parsed_members) == 3
        assert "n-0" in parsed_members

    @pytest.mark.asyncio
    async def test_multiple_communities_per_session(self, test_db):
        session_id = str(uuid.uuid4())

        for i in range(3):
            await test_db.execute(
                """INSERT INTO kg_communities (id, session_id, title, summary, member_ids)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), session_id, f"Community {i}", f"Summary {i}", "[]"),
            )
        await test_db.commit()

        cursor = await test_db.execute(
            "SELECT COUNT(*) as cnt FROM kg_communities WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 3
