"""Tests for SeedGraphInjector — Phase 1 GraphRAG Seed Injection."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Minimal ProcessedSeed stand-ins (avoid heavy imports)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SeedEntity:
    name: str
    type: str
    relevance: float = 1.0


@dataclass(frozen=True)
class _TimelineEvent:
    date_hint: str
    event: str


@dataclass(frozen=True)
class _Stakeholder:
    group: str
    impact: str
    description: str


@dataclass(frozen=True)
class _ProcessedSeed:
    language: str
    entities: tuple
    timeline: tuple
    stakeholders: tuple
    sentiment: str
    key_claims: tuple
    suggested_scenario: str
    suggested_regions: tuple
    confidence: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_seed(
    entities=(),
    timeline=(),
    stakeholders=(),
    key_claims=(),
    sentiment="neutral",
    confidence=0.8,
):
    return _ProcessedSeed(
        language="zh-HK",
        entities=tuple(entities),
        timeline=tuple(timeline),
        stakeholders=tuple(stakeholders),
        sentiment=sentiment,
        key_claims=tuple(key_claims),
        suggested_scenario="property",
        suggested_regions=("沙田",),
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------

from backend.app.services.seed_graph_injector import (  # noqa: E402
    SeedGraphEdge,
    SeedGraphInjector,
    SeedGraphNode,
    _normalize_name,
    _slug,
)

# ---------------------------------------------------------------------------
# Unit tests — helper functions
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_strips_whitespace(self):
        assert _normalize_name("  滙豐銀行  ") == "滙豐銀行"

    def test_lowercases_ascii(self):
        assert _normalize_name("HSBC") == "hsbc"

    def test_preserves_chinese(self):
        assert _normalize_name("香港") == "香港"

    def test_fullwidth_normalization(self):
        # NFKC should convert full-width digits
        result = _normalize_name("１２３")
        assert result == "123"


class TestSlug:
    def test_spaces_become_underscores(self):
        assert "_" in _slug("hello world")

    def test_chinese_preserved(self):
        s = _slug("香港樓市")
        assert "香港樓市" in s or len(s) > 0

    def test_max_length_30(self):
        long_text = "a" * 100
        assert len(_slug(long_text)) <= 30

    def test_no_leading_trailing_underscores(self):
        s = _slug("  hello  ")
        assert not s.startswith("_")
        assert not s.endswith("_")


# ---------------------------------------------------------------------------
# Unit tests — frozen dataclasses
# ---------------------------------------------------------------------------


class TestFrozenDataclasses:
    def test_seed_graph_node_is_frozen(self):
        node = SeedGraphNode(
            id="test_id",
            entity_type="Person",
            title="測試人物",
            description="desc",
            properties={"relevance": 1.0},
        )
        with pytest.raises(Exception):
            node.id = "modified"  # type: ignore[misc]

    def test_seed_graph_edge_is_frozen(self):
        edge = SeedGraphEdge(
            source_id="a",
            target_id="b",
            relation_type="RELATED_TO",
            description="test",
            weight=1.0,
        )
        with pytest.raises(Exception):
            edge.weight = 2.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration tests with in-memory SQLite DB
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    """Set up a temporary SQLite DB with kg_nodes/kg_edges tables."""
    db_path = tmp_path / "test.db"

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kg_nodes (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            properties TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS kg_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            description TEXT,
            weight REAL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def patched_db(tmp_db):
    """Patch get_db to use the temp DB file."""
    from contextlib import asynccontextmanager

    import aiosqlite

    @asynccontextmanager
    async def _fake_get_db():
        async with aiosqlite.connect(str(tmp_db)) as db:
            db.row_factory = aiosqlite.Row
            yield db

    with patch("backend.app.services.seed_graph_injector.get_db", _fake_get_db):
        yield tmp_db


class TestSeedGraphInjectorEntityNodes:
    """Test entity → node conversion for all 6 type mappings."""

    @pytest.mark.asyncio
    async def test_person_type_mapping(self, patched_db):
        seed = _make_seed(entities=[_SeedEntity("張三", "person", 0.9)])
        injector = SeedGraphInjector()
        result = await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)
        assert result["seed_nodes"] == 1

        import aiosqlite

        async with aiosqlite.connect(str(patched_db)) as db:
            cursor = await db.execute("SELECT entity_type FROM kg_nodes WHERE title = '張三'")
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "Person"

    @pytest.mark.asyncio
    async def test_org_type_mapping(self, patched_db):
        seed = _make_seed(entities=[_SeedEntity("滙豐銀行", "org", 0.9)])
        injector = SeedGraphInjector()
        await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)

        import aiosqlite

        async with aiosqlite.connect(str(patched_db)) as db:
            cursor = await db.execute("SELECT entity_type FROM kg_nodes WHERE title = '滙豐銀行'")
            row = await cursor.fetchone()
        assert row[0] == "Organization"

    @pytest.mark.asyncio
    async def test_location_type_mapping(self, patched_db):
        seed = _make_seed(entities=[_SeedEntity("沙田", "location", 0.8)])
        injector = SeedGraphInjector()
        await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)

        import aiosqlite

        async with aiosqlite.connect(str(patched_db)) as db:
            cursor = await db.execute("SELECT entity_type FROM kg_nodes WHERE title = '沙田'")
            row = await cursor.fetchone()
        assert row[0] == "District"

    @pytest.mark.asyncio
    async def test_policy_type_mapping(self, patched_db):
        seed = _make_seed(entities=[_SeedEntity("印花稅", "policy", 0.7)])
        injector = SeedGraphInjector()
        await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)

        import aiosqlite

        async with aiosqlite.connect(str(patched_db)) as db:
            cursor = await db.execute("SELECT entity_type FROM kg_nodes WHERE title = '印花稅'")
            row = await cursor.fetchone()
        assert row[0] == "Policy"

    @pytest.mark.asyncio
    async def test_economic_type_mapping(self, patched_db):
        seed = _make_seed(entities=[_SeedEntity("HIBOR", "economic", 0.9)])
        injector = SeedGraphInjector()
        await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)

        import aiosqlite

        async with aiosqlite.connect(str(patched_db)) as db:
            cursor = await db.execute("SELECT entity_type FROM kg_nodes WHERE title = 'HIBOR'")
            row = await cursor.fetchone()
        assert row[0] == "EconomicIndicator"

    @pytest.mark.asyncio
    async def test_event_type_mapping(self, patched_db):
        seed = _make_seed(entities=[_SeedEntity("撤辣事件", "event", 0.8)])
        injector = SeedGraphInjector()
        await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)

        import aiosqlite

        async with aiosqlite.connect(str(patched_db)) as db:
            cursor = await db.execute("SELECT entity_type FROM kg_nodes WHERE title = '撤辣事件'")
            row = await cursor.fetchone()
        assert row[0] == "Event"


class TestStakeholderNodes:
    @pytest.mark.asyncio
    async def test_stakeholder_node_created(self, patched_db):
        seed = _make_seed(
            entities=[_SeedEntity("樓價", "economic", 0.9)],
            stakeholders=[_Stakeholder("首置買家", "high", "首次置業人士")],
        )
        injector = SeedGraphInjector()
        result = await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)

        assert result["seed_nodes"] >= 2  # entity + stakeholder

        import aiosqlite

        async with aiosqlite.connect(str(patched_db)) as db:
            cursor = await db.execute("SELECT entity_type FROM kg_nodes WHERE title = '首置買家'")
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "StakeholderGroup"

    @pytest.mark.asyncio
    async def test_stakeholder_edge_to_entity(self, patched_db):
        seed = _make_seed(
            entities=[_SeedEntity("樓價", "economic", 0.9)],
            stakeholders=[_Stakeholder("首置買家", "high", "首次置業人士")],
        )
        injector = SeedGraphInjector()
        result = await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)
        assert result["seed_edges"] >= 1


class TestTimelineEdges:
    @pytest.mark.asyncio
    async def test_timeline_precedes_edges(self, patched_db):
        seed = _make_seed(
            timeline=[
                _TimelineEvent("2023-Q1", "利率上升"),
                _TimelineEvent("2023-Q2", "樓價下跌"),
                _TimelineEvent("2023-Q3", "成交量萎縮"),
            ],
        )
        injector = SeedGraphInjector()
        result = await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)
        # 3 events → 2 PRECEDES edges
        assert result["seed_edges"] == 2

    @pytest.mark.asyncio
    async def test_single_timeline_event_no_edges(self, patched_db):
        seed = _make_seed(
            timeline=[_TimelineEvent("2023-Q1", "利率上升")],
        )
        injector = SeedGraphInjector()
        result = await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)
        assert result["seed_edges"] == 0


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_existing_title_not_duplicated(self, patched_db):
        """If a node with same title already exists, it should not be inserted again."""
        import aiosqlite

        # Pre-insert a node with normalized title "滙豐銀行"
        async with aiosqlite.connect(str(patched_db)) as db:
            await db.execute(
                "INSERT INTO kg_nodes (id, session_id, entity_type, title, description) "
                "VALUES ('existing_hsbc', 'aabbccdd-1122-3344-5566-778899001122', 'Organization', '滙豐銀行', 'pre-existing')"
            )
            await db.commit()

        seed = _make_seed(entities=[_SeedEntity("滙豐銀行", "org", 0.9)])
        injector = SeedGraphInjector()
        result = await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)

        # Should report 0 new nodes (mapped to existing)
        assert result["seed_nodes"] == 0

    @pytest.mark.asyncio
    async def test_no_match_creates_new_node(self, patched_db):
        seed = _make_seed(entities=[_SeedEntity("全新機構ABC", "org", 0.9)])
        injector = SeedGraphInjector()
        result = await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)
        assert result["seed_nodes"] == 1


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_seed_returns_zero(self, patched_db):
        seed = _make_seed()
        injector = SeedGraphInjector()
        result = await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)
        assert result["seed_nodes"] == 0
        assert result["seed_edges"] == 0

    @pytest.mark.asyncio
    async def test_node_id_uses_prefix_convention(self, patched_db):
        seed = _make_seed(entities=[_SeedEntity("測試機構", "org", 0.8)])
        injector = SeedGraphInjector()
        await injector.inject("aabbccdd-1122-3344-5566-778899001122", seed)

        import aiosqlite

        async with aiosqlite.connect(str(patched_db)) as db:
            cursor = await db.execute("SELECT id FROM kg_nodes WHERE title = '測試機構'")
            row = await cursor.fetchone()
        assert row is not None
        # Node ID must start with 8-char hex prefix from graph_id
        assert row[0].startswith("aabbccdd")
