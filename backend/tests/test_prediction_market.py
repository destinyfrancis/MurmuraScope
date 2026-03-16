"""Tests for the Prediction Market Connector services."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, patch, MagicMock
from contextlib import asynccontextmanager

import aiosqlite
import pytest

from backend.app.services.polymarket_client import (
    PolymarketClient,
    PolymarketContract,
    _parse_contract,
)
from backend.app.services.scenario_matcher import (
    ContractMatch,
    ScenarioMatcher,
)
from backend.app.services.consensus_estimator import (
    ConsensusEstimate,
    ConsensusEstimator,
)
from backend.app.services.signal_generator import (
    SignalGenerator,
    TradingSignal,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_contract(**overrides) -> PolymarketContract:
    """Helper to create a PolymarketContract with defaults."""
    defaults = {
        "id": "test-1",
        "question": "Will the Fed cut rates in 2026?",
        "description": "Federal Reserve interest rate decision",
        "outcomes": ("Yes", "No"),
        "outcome_prices": (0.65, 0.35),
        "volume": 100000.0,
        "liquidity": 50000.0,
        "slug": "fed-rate-cut-2026",
        "category": "economics",
        "end_date": "2026-12-31",
        "closed": False,
    }
    defaults.update(overrides)
    return PolymarketContract(**defaults)


@pytest.fixture
async def db_setup():
    """Create in-memory DB with required tables for consensus estimator."""
    db = await aiosqlite.connect(":memory:")
    await db.execute("""
        CREATE TABLE simulation_sessions (
            id TEXT PRIMARY KEY, seed_text TEXT, status TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE belief_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, agent_id INTEGER, topic TEXT,
            stance REAL, confidence REAL
        )
    """)
    await db.execute("""
        CREATE TABLE agent_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, round_number INTEGER, agent_id INTEGER,
            decision_type TEXT, action TEXT, reasoning TEXT, oasis_username TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE simulation_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, round_number INTEGER, agent_id INTEGER,
            oasis_username TEXT, action_type TEXT, platform TEXT,
            content TEXT, target_agent_username TEXT,
            sentiment TEXT, topics TEXT, post_id TEXT,
            parent_action_id INTEGER, spread_depth INTEGER
        )
    """)
    await db.execute("""
        CREATE TABLE prediction_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, contract_id TEXT, contract_question TEXT,
            market_price REAL, engine_probability REAL, alpha REAL,
            direction TEXT, strength TEXT, strength_score REAL,
            confidence REAL, supporting_agents INTEGER,
            opposing_agents INTEGER, reasoning TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    await db.commit()

    @asynccontextmanager
    async def mock_get_db():
        yield db

    with patch("backend.app.services.consensus_estimator.get_db", mock_get_db), \
         patch("backend.app.services.signal_generator.get_db", mock_get_db):
        yield db

    await db.close()


# ---------------------------------------------------------------------------
# PolymarketContract tests
# ---------------------------------------------------------------------------


class TestPolymarketContract:
    def test_contract_is_frozen(self):
        c = _make_contract()
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.id = "changed"  # type: ignore[misc]

    def test_parse_contract_basic(self):
        raw = {
            "id": "42",
            "question": "Will BTC hit 100k?",
            "description": "Bitcoin price prediction",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '[0.72,0.28]',
            "volume": "500000",
            "liquidity": "200000",
            "slug": "btc-100k",
            "category": "crypto",
            "endDate": "2026-12-31",
            "closed": False,
        }
        c = _parse_contract(raw)
        assert c is not None
        assert c.id == "42"
        assert c.question == "Will BTC hit 100k?"
        assert c.outcomes == ("Yes", "No")
        assert c.outcome_prices == (0.72, 0.28)
        assert c.volume == 500000.0

    def test_parse_contract_missing_fields(self):
        # When "outcomes" key is absent entirely, the default else-branch fires → ("Yes", "No").
        # When it is present but None/0/other non-str non-list, same else-branch fires.
        raw = {"id": "1"}
        c = _parse_contract(raw)
        assert c is not None
        assert c.question == ""
        # outcomes_raw is "" (empty string) → split gives [] → empty tuple
        assert c.outcomes == ()

    def test_parse_contract_list_outcomes(self):
        raw = {
            "id": "2",
            "outcomes": ["Option A", "Option B", "Option C"],
            "outcomePrices": [0.3, 0.5, 0.2],
        }
        c = _parse_contract(raw)
        assert c is not None
        assert c.outcomes == ("Option A", "Option B", "Option C")
        assert len(c.outcome_prices) == 3


# ---------------------------------------------------------------------------
# ScenarioMatcher tests
# ---------------------------------------------------------------------------


class TestScenarioMatcher:
    def test_match_by_topic(self):
        contracts = [
            _make_contract(id="1", question="Will the Fed cut rates?", description="Federal Reserve monetary policy"),
            _make_contract(id="2", question="Will Bitcoin hit 200k?", description="Crypto prediction"),
        ]
        matcher = ScenarioMatcher()
        matches = matcher.match_contracts("Fed announces rate cut of 50bps", contracts)
        assert len(matches) >= 1
        assert matches[0].contract.id == "1"

    def test_match_returns_empty_for_unrelated(self):
        contracts = [
            _make_contract(id="1", question="Will team X win the championship?", description="Sports prediction"),
        ]
        matcher = ScenarioMatcher()
        matches = matcher.match_contracts("台海軍事衝突", contracts, min_relevance=0.3)
        assert len(matches) == 0

    def test_match_contract_frozen(self):
        c = _make_contract()
        match = ContractMatch(
            contract=c, relevance_score=0.8,
            matched_keywords=("fed",), matched_topics=("fed_rates",),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            match.relevance_score = 0.5  # type: ignore[misc]

    def test_extract_topics_geopolitics(self):
        matcher = ScenarioMatcher()
        topics = matcher._extract_topics("us china military conflict in taiwan strait")
        assert "geopolitics" in topics

    def test_extract_topics_hk(self):
        matcher = ScenarioMatcher()
        topics = matcher._extract_topics("香港樓市移民潮")
        assert "hk_specific" in topics


# ---------------------------------------------------------------------------
# ConsensusEstimator tests
# ---------------------------------------------------------------------------


class TestConsensusEstimator:
    @pytest.mark.asyncio
    async def test_estimate_with_beliefs(self, db_setup):
        db = db_setup
        session_id = "test-session"
        # Insert positive economy beliefs
        for i in range(10):
            await db.execute(
                "INSERT INTO belief_states (session_id, agent_id, topic, stance, confidence) VALUES (?, ?, ?, ?, ?)",
                (session_id, i, "economy_outlook", 0.6, 0.8),
            )
        await db.commit()

        estimator = ConsensusEstimator()
        result = await estimator.estimate_probability(
            session_id, "Will the economy enter recession?"
        )
        assert isinstance(result, ConsensusEstimate)
        assert result.probability > 0.5  # positive beliefs = higher prob
        assert result.belief_signal > 0

    @pytest.mark.asyncio
    async def test_estimate_with_decisions(self, db_setup):
        db = db_setup
        session_id = "test-session"
        # Insert mostly bearish decisions
        for i in range(8):
            await db.execute(
                "INSERT INTO agent_decisions (session_id, round_number, agent_id, decision_type, action, reasoning, oasis_username) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, 1, i, "emigrate", "emigrate", "economy bad", f"agent_{i}"),
            )
        for i in range(2):
            await db.execute(
                "INSERT INTO agent_decisions (session_id, round_number, agent_id, decision_type, action, reasoning, oasis_username) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, 1, 10+i, "invest", "invest_stocks", "bullish", f"agent_{10+i}"),
            )
        await db.commit()

        estimator = ConsensusEstimator()
        result = await estimator.estimate_probability(session_id, "Some question")
        assert result.decision_signal < 0  # more bearish decisions

    @pytest.mark.asyncio
    async def test_estimate_with_sentiment(self, db_setup):
        db = db_setup
        session_id = "test-session"
        for i in range(20):
            sentiment = "positive" if i < 15 else "negative"
            await db.execute(
                "INSERT INTO simulation_actions (session_id, round_number, oasis_username, action_type, sentiment, topics) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, 1, f"user_{i}", "post", sentiment, "[]"),
            )
        await db.commit()

        estimator = ConsensusEstimator()
        result = await estimator.estimate_probability(session_id, "Any question")
        assert result.sentiment_signal > 0  # 75% positive

    @pytest.mark.asyncio
    async def test_estimate_neutral_returns_half(self, db_setup):
        estimator = ConsensusEstimator()
        result = await estimator.estimate_probability("empty-session", "Unknown topic")
        assert 0.45 <= result.probability <= 0.55

    def test_consensus_estimate_frozen(self):
        est = ConsensusEstimate(
            probability=0.6, confidence=0.5, supporting_agents=10,
            opposing_agents=5, neutral_agents=3, belief_signal=0.3,
            decision_signal=0.1, sentiment_signal=0.2,
            evidence_summary="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            est.probability = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SignalGenerator tests
# ---------------------------------------------------------------------------


class TestSignalGenerator:
    @pytest.mark.asyncio
    async def test_generate_buy_yes_signal(self, db_setup):
        db = db_setup
        session_id = "test-session"
        # Strong positive beliefs about economy
        for i in range(20):
            await db.execute(
                "INSERT INTO belief_states (session_id, agent_id, topic, stance, confidence) VALUES (?, ?, ?, ?, ?)",
                (session_id, i, "economy_outlook", 0.8, 0.9),
            )
        await db.commit()

        contract = _make_contract(
            question="Will the economy grow in 2026?",
            outcome_prices=(0.30, 0.70),  # market says 30% YES
        )
        match = ContractMatch(
            contract=contract, relevance_score=0.8,
            matched_keywords=("economy",), matched_topics=("markets",),
        )

        generator = SignalGenerator()
        signals = await generator.generate_signals(session_id, [match])
        assert len(signals) == 1
        assert signals[0].direction == "BUY_YES"
        assert signals[0].alpha > 0

    @pytest.mark.asyncio
    async def test_generate_hold_signal(self, db_setup):
        contract = _make_contract(
            question="Will something random happen?",
            outcome_prices=(0.50, 0.50),
        )
        match = ContractMatch(
            contract=contract, relevance_score=0.5,
            matched_keywords=(), matched_topics=(),
        )

        generator = SignalGenerator()
        signals = await generator.generate_signals("empty-session", [match])
        assert len(signals) == 1
        assert signals[0].direction == "HOLD"
        assert abs(signals[0].alpha) < 0.1

    def test_trading_signal_frozen(self):
        sig = TradingSignal(
            contract_id="1", contract_question="Test?",
            market_price=0.5, engine_probability=0.7,
            alpha=0.2, direction="BUY_YES", strength="strong",
            strength_score=0.8, confidence=0.9,
            supporting_agents=10, opposing_agents=3,
            reasoning="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            sig.alpha = 0.1  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_alpha_calculation(self, db_setup):
        contract = _make_contract(
            question="Will the economy recover?",
            outcome_prices=(0.40, 0.60),
        )
        match = ContractMatch(
            contract=contract, relevance_score=0.8,
            matched_keywords=("economy",), matched_topics=("markets",),
        )

        generator = SignalGenerator()
        signals = await generator.generate_signals("empty-session", [match])
        # With no data, engine should estimate ~0.5
        # Alpha should be approximately 0.5 - 0.4 = 0.1
        assert len(signals) == 1
        assert -0.2 <= signals[0].alpha <= 0.2

    @pytest.mark.asyncio
    async def test_signals_sorted_by_alpha(self, db_setup):
        contracts = [
            _make_contract(id="1", question="Economy question?", outcome_prices=(0.20, 0.80)),
            _make_contract(id="2", question="Another economy question?", outcome_prices=(0.45, 0.55)),
        ]
        matches = [
            ContractMatch(contract=c, relevance_score=0.5, matched_keywords=(), matched_topics=())
            for c in contracts
        ]

        generator = SignalGenerator()
        signals = await generator.generate_signals("empty-session", matches)
        # Should be sorted by absolute alpha descending
        if len(signals) >= 2:
            assert abs(signals[0].alpha) >= abs(signals[1].alpha)
