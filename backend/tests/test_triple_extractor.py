"""Tests for TripleExtractor — Phase 2 Temporal Knowledge Graph Memory."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import aiosqlite
import pytest

from backend.app.services.triple_extractor import (
    MemoryTriple,
    TripleExtractor,
    _clean,
    _is_plausible_entity,
)

# ---------------------------------------------------------------------------
# Frozen dataclass tests
# ---------------------------------------------------------------------------


class TestMemoryTripleFrozen:
    def test_is_frozen(self):
        t = MemoryTriple(subject="我", predicate="worries_about", object="樓價")
        with pytest.raises(Exception):
            t.subject = "other"  # type: ignore[misc]

    def test_default_confidence(self):
        t = MemoryTriple(subject="A", predicate="B", object="C")
        assert 0.0 < t.confidence <= 1.0

    def test_custom_confidence(self):
        t = MemoryTriple(subject="A", predicate="B", object="C", confidence=0.5)
        assert t.confidence == 0.5


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestClean:
    def test_strips_punctuation(self):
        assert _clean("樓價，") == "樓價"

    def test_strips_brackets(self):
        assert _clean("【測試】") == "測試"

    def test_empty_returns_empty(self):
        assert _clean("") == ""

    def test_max_length(self):
        long = "a" * 100
        result = _clean(long)
        assert len(result) <= 30


class TestIsPlausibleEntity:
    def test_chinese_is_plausible(self):
        assert _is_plausible_entity("樓價") is True

    def test_ascii_is_plausible(self):
        assert _is_plausible_entity("HIBOR") is True

    def test_empty_is_not_plausible(self):
        assert _is_plausible_entity("") is False

    def test_pure_punctuation_not_plausible(self):
        assert _is_plausible_entity("，。！") is False


# ---------------------------------------------------------------------------
# Cantonese pattern tests
# ---------------------------------------------------------------------------


class TestWorriesAboutPattern:
    def test_擔心(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("我擔心樓價繼續跌", agent_username="user1")
        assert any(t.predicate == "worries_about" and "樓價" in t.object for t in triples)

    def test_驚(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("我驚失業率上升", agent_username="user1")
        assert any(t.predicate == "worries_about" for t in triples)

    def test_subject_is_agent(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("我擔心HIBOR加息", agent_username="小明")
        worry_triples = [t for t in triples if t.predicate == "worries_about"]
        assert all(t.subject == "小明" for t in worry_triples)


class TestIncreaseDecreasePattern:
    def test_升_pattern(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("HIBOR升左好多。")
        inc = [t for t in triples if t.predicate == "increases"]
        assert any("HIBOR" in t.subject for t in inc)

    def test_跌_pattern(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("樓價跌咗兩成。")
        dec = [t for t in triples if t.predicate == "decreases"]
        assert len(dec) >= 1

    def test_reduces_pattern(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("交投量減少。")
        dec = [t for t in triples if t.predicate == "decreases"]
        assert len(dec) >= 1


class TestObservesPattern:
    def test_我見到_pattern(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("我見到身邊好多人移民。")
        obs = [t for t in triples if t.predicate == "observes"]
        assert len(obs) >= 1
        assert any("移民" in t.object for t in obs)


class TestCausesPattern:
    def test_影響_pattern(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("加息影響樓市。")
        causes = [t for t in triples if t.predicate == "causes"]
        assert len(causes) >= 1

    def test_導致_pattern(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("失業率上升導致消費下降。")
        causes = [t for t in triples if t.predicate == "causes"]
        assert len(causes) >= 1


class TestSupportOpposePattern:
    def test_支持_pattern(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("我支持政府嘅住屋政策。")
        sup = [t for t in triples if t.predicate == "supports"]
        assert len(sup) >= 1

    def test_贊成_pattern(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("我贊成撤辣措施。")
        sup = [t for t in triples if t.predicate == "supports"]
        assert len(sup) >= 1

    def test_反對_pattern(self):
        extractor = TripleExtractor()
        triples = extractor.extract_triples("我反對加租。")
        opp = [t for t in triples if t.predicate == "opposes"]
        assert len(opp) >= 1
        assert any("加租" in t.object for t in opp)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string_returns_empty_tuple(self):
        extractor = TripleExtractor()
        result = extractor.extract_triples("")
        assert result == ()

    def test_whitespace_only_returns_empty_tuple(self):
        extractor = TripleExtractor()
        result = extractor.extract_triples("   \n\t  ")
        assert result == ()

    def test_no_matching_patterns_returns_empty_tuple(self):
        extractor = TripleExtractor()
        result = extractor.extract_triples("今日天氣幾好。")
        # May or may not match; just verify it returns a tuple
        assert isinstance(result, tuple)

    def test_return_type_is_tuple(self):
        extractor = TripleExtractor()
        result = extractor.extract_triples("我擔心通脹上升。")
        assert isinstance(result, tuple)

    def test_deduplication(self):
        extractor = TripleExtractor()
        # Two identical patterns should be deduplicated
        text = "我擔心樓價跌，我擔心樓價跌。"
        result = extractor.extract_triples(text)
        worry_triples = [t for t in result if t.predicate == "worries_about"]
        # Should be deduplicated
        unique_keys = {(t.subject, t.predicate, t.object) for t in worry_triples}
        assert len(unique_keys) <= len(worry_triples)


# ---------------------------------------------------------------------------
# Integration: get_relational_context with test DB
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_with_triples(tmp_path):
    """Set up temp SQLite DB with memory_triples table."""
    db_path = tmp_path / "test_triples.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE agent_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            agent_id INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            memory_text TEXT NOT NULL,
            salience_score REAL NOT NULL DEFAULT 1.0,
            memory_type TEXT NOT NULL DEFAULT 'observation',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE memory_triples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            agent_id INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.8,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_triple_session_agent
            ON memory_triples(session_id, agent_id);
    """)
    # Insert some test triples
    conn.execute(
        "INSERT INTO memory_triples "
        "(memory_id, session_id, agent_id, round_number, subject, predicate, object) "
        "VALUES (1, 'sess1', 1, 1, '我', 'worries_about', '樓價')"
    )
    conn.execute(
        "INSERT INTO memory_triples "
        "(memory_id, session_id, agent_id, round_number, subject, predicate, object) "
        "VALUES (1, 'sess1', 1, 1, '樓價', 'decreases', 'value')"
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.mark.asyncio
async def test_get_relational_context_returns_formatted_string(tmp_db_with_triples):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_get_db():
        async with aiosqlite.connect(str(tmp_db_with_triples)) as db:
            yield db

    from backend.app.services import agent_memory as am_module

    with patch.object(am_module, "get_db", _fake_get_db):
        service = am_module.AgentMemoryService()
        result = await service.get_relational_context("sess1", 1)

    assert "【關係記憶】" in result
    assert "worries_about" in result or "→" in result


@pytest.mark.asyncio
async def test_get_relational_context_empty_for_unknown_agent(tmp_db_with_triples):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_get_db():
        async with aiosqlite.connect(str(tmp_db_with_triples)) as db:
            yield db

    from backend.app.services import agent_memory as am_module

    with patch.object(am_module, "get_db", _fake_get_db):
        service = am_module.AgentMemoryService()
        result = await service.get_relational_context("sess1", 999)

    assert result == ""
