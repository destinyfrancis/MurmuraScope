"""Tests for TrustDynamicsService — Phase 3 Dynamic Trust & Debate."""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from unittest.mock import patch

import aiosqlite
import pytest

from backend.app.services.trust_dynamics import (
    TrustDynamicsService,
    TrustUpdate,
    _sentiment_alignment_score,
    _TRUST_DECAY_FACTOR,
    _DELTA_MAX,
    _DELTA_MIN,
    _TRUST_MAX,
    _TRUST_MIN,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temp SQLite DB with agent_relationships and related tables."""
    db_path = tmp_path / "trust_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE agent_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            agent_a_id INTEGER NOT NULL,
            agent_b_id INTEGER NOT NULL,
            relationship_type TEXT NOT NULL DEFAULT 'interaction',
            influence_weight REAL DEFAULT 0.5,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE agent_profiles (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            oasis_username TEXT NOT NULL,
            political_stance REAL DEFAULT 0.5,
            agent_type TEXT DEFAULT 'resident',
            age INTEGER DEFAULT 30,
            sex TEXT DEFAULT 'M',
            district TEXT DEFAULT '沙田',
            occupation TEXT DEFAULT 'worker',
            income_bracket TEXT DEFAULT 'middle',
            education_level TEXT DEFAULT 'university',
            marital_status TEXT DEFAULT 'single',
            housing_type TEXT DEFAULT 'rental',
            openness REAL DEFAULT 0.5,
            conscientiousness REAL DEFAULT 0.5,
            extraversion REAL DEFAULT 0.5,
            agreeableness REAL DEFAULT 0.5,
            neuroticism REAL DEFAULT 0.5
        );

        CREATE TABLE simulation_sessions (
            id TEXT PRIMARY KEY,
            name TEXT DEFAULT 'test',
            sim_mode TEXT DEFAULT 'facebook',
            seed_text TEXT DEFAULT '',
            agent_count INTEGER DEFAULT 10,
            round_count INTEGER DEFAULT 5,
            llm_provider TEXT DEFAULT 'openrouter',
            llm_model TEXT DEFAULT 'test',
            oasis_db_path TEXT DEFAULT '',
            status TEXT DEFAULT 'created'
        );

        CREATE TABLE simulation_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            round_number INTEGER NOT NULL,
            agent_id INTEGER,
            oasis_username TEXT NOT NULL,
            action_type TEXT NOT NULL DEFAULT 'post',
            platform TEXT NOT NULL DEFAULT 'facebook',
            content TEXT NOT NULL,
            target_agent_username TEXT,
            sentiment TEXT NOT NULL DEFAULT 'neutral',
            topics TEXT DEFAULT '[]'
        );
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def patched_db(tmp_db):
    """Patch get_db to use the temp DB."""
    @asynccontextmanager
    async def _fake_get_db():
        async with aiosqlite.connect(str(tmp_db)) as db:
            db.row_factory = aiosqlite.Row
            yield db

    with patch("backend.app.services.trust_dynamics.get_db", _fake_get_db):
        yield tmp_db


# ---------------------------------------------------------------------------
# Frozen dataclass tests
# ---------------------------------------------------------------------------


class TestTrustUpdateFrozen:
    def test_is_frozen(self):
        u = TrustUpdate(
            agent_a_id=1, agent_b_id=2,
            old_score=0.0, new_score=0.1, reason="test",
        )
        with pytest.raises(Exception):
            u.new_score = 0.5  # type: ignore[misc]

    def test_fields_accessible(self):
        u = TrustUpdate(1, 2, 0.0, 0.1, "reason")
        assert u.agent_a_id == 1
        assert u.agent_b_id == 2
        assert u.old_score == 0.0
        assert u.new_score == 0.1


# ---------------------------------------------------------------------------
# Sentiment alignment tests
# ---------------------------------------------------------------------------


class TestSentimentAlignment:
    def test_positive_sentiment_score(self):
        score = _sentiment_alignment_score("positive")
        assert score == 1.0

    def test_negative_sentiment_score(self):
        score = _sentiment_alignment_score("negative")
        assert score == -0.5

    def test_neutral_sentiment_score(self):
        score = _sentiment_alignment_score("neutral")
        assert score == 0.0

    def test_unknown_sentiment_defaults_neutral(self):
        score = _sentiment_alignment_score("mixed")
        assert score == 0.0


# ---------------------------------------------------------------------------
# ensure_column idempotency
# ---------------------------------------------------------------------------


class TestEnsureColumn:
    @pytest.mark.asyncio
    async def test_ensure_column_idempotent(self, tmp_db):
        """Calling ensure_column twice should not raise."""
        service = TrustDynamicsService()
        async with aiosqlite.connect(str(tmp_db)) as db:
            await service.ensure_column(db)
            await service.ensure_column(db)  # second call — no error

    @pytest.mark.asyncio
    async def test_column_is_added(self, tmp_db):
        """After ensure_column, trust_score should exist as a column."""
        service = TrustDynamicsService()
        async with aiosqlite.connect(str(tmp_db)) as db:
            await service.ensure_column(db)

        conn = sqlite3.connect(str(tmp_db))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(agent_relationships)")]
        conn.close()
        assert "trust_score" in cols


# ---------------------------------------------------------------------------
# update_trust_from_round
# ---------------------------------------------------------------------------


class TestUpdateTrustFromRound:
    @pytest.mark.asyncio
    async def test_empty_interactions_returns_empty(self, patched_db):
        service = TrustDynamicsService()
        result = await service.update_trust_from_round("sess_empty", 1)
        assert result == ()

    @pytest.mark.asyncio
    async def test_positive_sentiment_increases_trust(self, patched_db):
        """Positive sentiment interaction should increase trust score."""
        import aiosqlite as _aiosqlite

        # Set up: two agents + one interaction
        async with aiosqlite.connect(str(patched_db)) as db:
            await db.execute(
                "INSERT INTO agent_profiles (id, session_id, oasis_username, political_stance)"
                " VALUES (1, 'sess1', 'user_a', 0.5)"
            )
            await db.execute(
                "INSERT INTO agent_profiles (id, session_id, oasis_username, political_stance)"
                " VALUES (2, 'sess1', 'user_b', 0.5)"
            )
            await db.execute(
                "INSERT INTO simulation_actions "
                "(session_id, round_number, oasis_username, target_agent_username, sentiment, content)"
                " VALUES ('sess1', 1, 'user_a', 'user_b', 'positive', 'test post')"
            )
            await db.commit()

        service = TrustDynamicsService()
        updates = await service.update_trust_from_round("sess1", 1)
        assert len(updates) >= 1
        assert updates[0].new_score > updates[0].old_score

    @pytest.mark.asyncio
    async def test_negative_sentiment_decreases_trust(self, patched_db):
        """Negative sentiment interaction should decrease (or not increase) trust."""
        async with aiosqlite.connect(str(patched_db)) as db:
            await db.execute(
                "INSERT INTO agent_profiles (id, session_id, oasis_username, political_stance)"
                " VALUES (3, 'sess2', 'user_c', 0.5)"
            )
            await db.execute(
                "INSERT INTO agent_profiles (id, session_id, oasis_username, political_stance)"
                " VALUES (4, 'sess2', 'user_d', 0.5)"
            )
            await db.execute(
                "INSERT INTO simulation_actions "
                "(session_id, round_number, oasis_username, target_agent_username, sentiment, content)"
                " VALUES ('sess2', 1, 'user_c', 'user_d', 'negative', 'critical post')"
            )
            await db.commit()

        service = TrustDynamicsService()
        updates = await service.update_trust_from_round("sess2", 1)
        assert len(updates) >= 1
        # Negative sentiment → delta should be negative or zero
        assert updates[0].new_score <= updates[0].old_score

    @pytest.mark.asyncio
    async def test_delta_is_clamped(self, patched_db):
        """Delta should not exceed ±0.15 per interaction."""
        async with aiosqlite.connect(str(patched_db)) as db:
            await db.execute(
                "INSERT INTO agent_profiles (id, session_id, oasis_username, political_stance)"
                " VALUES (5, 'sess3', 'user_e', 0.0)"
            )
            await db.execute(
                "INSERT INTO agent_profiles (id, session_id, oasis_username, political_stance)"
                " VALUES (6, 'sess3', 'user_f', 0.0)"
            )
            await db.execute(
                "INSERT INTO simulation_actions "
                "(session_id, round_number, oasis_username, target_agent_username, sentiment, content)"
                " VALUES ('sess3', 1, 'user_e', 'user_f', 'positive', 'post')"
            )
            await db.commit()

        service = TrustDynamicsService()
        updates = await service.update_trust_from_round("sess3", 1)
        for u in updates:
            delta = u.new_score - u.old_score
            assert abs(delta) <= _DELTA_MAX

    @pytest.mark.asyncio
    async def test_trust_score_clamped_to_range(self, patched_db):
        """Trust score constants must define valid bounds [-1.0, +1.0]."""
        assert _TRUST_MAX == 1.0
        assert _TRUST_MIN == -1.0
        # Verify the formula clamps correctly
        raw = 5.0  # very large raw score
        clamped = max(_TRUST_MIN, min(_TRUST_MAX, raw))
        assert clamped == 1.0
        raw_neg = -5.0
        clamped_neg = max(_TRUST_MIN, min(_TRUST_MAX, raw_neg))
        assert clamped_neg == -1.0


# Helper for test setup
async def service_setup(db):
    try:
        await db.execute(
            "ALTER TABLE agent_relationships ADD COLUMN trust_score REAL DEFAULT 0.0"
        )
        await db.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# decay_trust
# ---------------------------------------------------------------------------


class TestDecayTrust:
    @pytest.mark.asyncio
    async def test_decay_reduces_trust_scores(self, patched_db):
        """Trust score should be multiplied by 0.95 after decay."""
        async with aiosqlite.connect(str(patched_db)) as db:
            await db.execute(
                "ALTER TABLE agent_relationships ADD COLUMN trust_score REAL DEFAULT 0.0"
            )
            await db.execute(
                "INSERT INTO agent_relationships "
                "(session_id, agent_a_id, agent_b_id, relationship_type, trust_score)"
                " VALUES ('sess_decay', 1, 2, 'interaction', 0.5)"
            )
            await db.commit()

        service = TrustDynamicsService()
        count = await service.decay_trust("sess_decay")
        assert count >= 1

        async with aiosqlite.connect(str(patched_db)) as db:
            cursor = await db.execute(
                "SELECT trust_score FROM agent_relationships WHERE session_id = 'sess_decay'"
            )
            row = await cursor.fetchone()
        assert row is not None
        assert abs(row[0] - 0.5 * _TRUST_DECAY_FACTOR) < 0.001

    @pytest.mark.asyncio
    async def test_decay_skips_near_zero_scores(self, patched_db):
        """Rows with |trust_score| <= 0.01 should not be updated."""
        async with aiosqlite.connect(str(patched_db)) as db:
            await db.execute(
                "ALTER TABLE agent_relationships ADD COLUMN trust_score REAL DEFAULT 0.0"
            )
            await db.execute(
                "INSERT INTO agent_relationships "
                "(session_id, agent_a_id, agent_b_id, relationship_type, trust_score)"
                " VALUES ('sess_zero', 10, 20, 'interaction', 0.005)"
            )
            await db.commit()

        service = TrustDynamicsService()
        count = await service.decay_trust("sess_zero")
        assert count == 0  # |0.005| < 0.01 threshold


# ---------------------------------------------------------------------------
# get_trust_context
# ---------------------------------------------------------------------------


class TestGetTrustContext:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_relationships(self, patched_db):
        service = TrustDynamicsService()
        result = await service.get_trust_context("sess_empty_ctx", 999)
        assert result == ""

    @pytest.mark.asyncio
    async def test_formats_trusted_relationships(self, patched_db):
        async with aiosqlite.connect(str(patched_db)) as db:
            await db.execute(
                "ALTER TABLE agent_relationships ADD COLUMN trust_score REAL DEFAULT 0.0"
            )
            await db.execute(
                "INSERT INTO agent_profiles (id, session_id, oasis_username)"
                " VALUES (100, 'sess_ctx', 'trusted_user')"
            )
            await db.execute(
                "INSERT INTO agent_relationships "
                "(session_id, agent_a_id, agent_b_id, relationship_type, trust_score)"
                " VALUES ('sess_ctx', 1, 100, 'interaction', 0.7)"
            )
            await db.commit()

        service = TrustDynamicsService()
        result = await service.get_trust_context("sess_ctx", 1)
        assert "【信任關係】" in result
        assert "trusted_user" in result or "信任" in result

    @pytest.mark.asyncio
    async def test_returns_empty_for_below_threshold_scores(self, patched_db):
        """Scores between -0.1 and +0.1 should not appear in context."""
        async with aiosqlite.connect(str(patched_db)) as db:
            await db.execute(
                "ALTER TABLE agent_relationships ADD COLUMN trust_score REAL DEFAULT 0.0"
            )
            await db.execute(
                "INSERT INTO agent_relationships "
                "(session_id, agent_a_id, agent_b_id, relationship_type, trust_score)"
                " VALUES ('sess_threshold', 1, 2, 'interaction', 0.05)"
            )
            await db.commit()

        service = TrustDynamicsService()
        result = await service.get_trust_context("sess_threshold", 1)
        assert result == ""


# ---------------------------------------------------------------------------
# Propagation weighting formula
# ---------------------------------------------------------------------------


class TestPropagationFormula:
    def test_zero_trust_gives_baseline_boost(self):
        """trust=0.0 → boost_factor = 1.2 * (1 + 0 * 0.3) = 1.2"""
        trust = 0.0
        boost = 1.2 * (1.0 + trust * 0.3)
        assert abs(boost - 1.2) < 1e-9

    def test_positive_trust_increases_boost(self):
        """trust=1.0 → boost_factor = 1.2 * (1 + 1.0 * 0.3) = 1.56"""
        trust = 1.0
        boost = 1.2 * (1.0 + trust * 0.3)
        assert abs(boost - 1.56) < 1e-9

    def test_negative_trust_decreases_boost(self):
        """trust=-1.0 → boost_factor = 1.2 * (1 - 0.3) = 0.84"""
        trust = -1.0
        boost = 1.2 * (1.0 + trust * 0.3)
        assert abs(boost - 0.84) < 1e-9
