"""Trading signal generator.

Compares engine probability estimates against Polymarket prices
to generate alpha signals with strength and direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.services.consensus_estimator import ConsensusEstimate, ConsensusEstimator
from backend.app.services.polymarket_client import PolymarketContract
from backend.app.services.scenario_matcher import ContractMatch
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("signal_generator")

# Minimum alpha threshold to generate a signal (avoid noise)
_MIN_ALPHA_THRESHOLD = 0.05

# Signal strength classifications
_STRENGTH_STRONG = 0.15
_STRENGTH_MODERATE = 0.08


@dataclass(frozen=True)
class TradingSignal:
    """Immutable trading signal for a Polymarket contract."""
    contract_id: str
    contract_question: str
    market_price: float         # current YES price on Polymarket
    engine_probability: float   # our estimated P(YES)
    alpha: float                # engine_prob - market_price
    direction: str              # BUY_YES | BUY_NO | HOLD
    strength: str               # strong | moderate | weak
    strength_score: float       # [0, 1] numeric strength
    confidence: float           # engine confidence [0, 1]
    supporting_agents: int
    opposing_agents: int
    reasoning: str              # human-readable explanation


class SignalGenerator:
    """Generates trading signals from consensus estimates vs market prices."""

    def __init__(self) -> None:
        self._estimator = ConsensusEstimator()

    async def generate_signals(
        self,
        session_id: str,
        matched_contracts: list[ContractMatch],
    ) -> list[TradingSignal]:
        """Generate signals for all matched contracts.

        For each contract:
        1. Get current market price (YES outcome price)
        2. Estimate probability from agent consensus (using domain pack weights)
        3. Compute alpha = engine_prob - market_price
        4. Determine direction and strength
        """
        signals: list[TradingSignal] = []
        domain_pack_id = await self._get_session_domain_pack(session_id)

        for match in matched_contracts:
            contract = match.contract

            try:
                estimate = await self._estimator.estimate_probability(
                    session_id, contract.question, domain_pack_id=domain_pack_id
                )
            except Exception:
                logger.exception(
                    "Consensus estimation failed for contract %s", contract.id
                )
                continue

            # Market price = YES outcome price (first outcome)
            market_price = contract.outcome_prices[0] if contract.outcome_prices else 0.5

            # Alpha = our estimate - market price
            alpha = estimate.probability - market_price

            # Direction
            if alpha > _MIN_ALPHA_THRESHOLD:
                direction = "BUY_YES"
            elif alpha < -_MIN_ALPHA_THRESHOLD:
                direction = "BUY_NO"
            else:
                direction = "HOLD"

            # Strength
            abs_alpha = abs(alpha)
            strength_score = min(1.0, abs_alpha * estimate.confidence * 5)

            if abs_alpha >= _STRENGTH_STRONG:
                strength = "strong"
            elif abs_alpha >= _STRENGTH_MODERATE:
                strength = "moderate"
            else:
                strength = "weak"

            reasoning = self._build_reasoning(
                contract.question, market_price, estimate, alpha, direction
            )

            signal = TradingSignal(
                contract_id=contract.id,
                contract_question=contract.question,
                market_price=round(market_price, 4),
                engine_probability=estimate.probability,
                alpha=round(alpha, 4),
                direction=direction,
                strength=strength,
                strength_score=round(strength_score, 4),
                confidence=estimate.confidence,
                supporting_agents=estimate.supporting_agents,
                opposing_agents=estimate.opposing_agents,
                reasoning=reasoning,
            )
            signals.append(signal)

        # Sort by absolute alpha descending (strongest signals first)
        signals.sort(key=lambda s: -abs(s.alpha))

        # Persist signals
        if signals:
            await self._persist_signals(session_id, signals)

        return signals

    async def _get_session_domain_pack(self, session_id: str) -> str | None:
        """Look up the domain pack ID for a session from the DB."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT domain_pack FROM simulation_sessions WHERE id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                return row[0] if row and row[0] else None
        except Exception:
            logger.debug("Could not fetch domain_pack for session=%s", session_id)
            return None

    async def _persist_signals(
        self, session_id: str, signals: list[TradingSignal]
    ) -> None:
        """Save signals to prediction_signals table."""
        try:
            async with get_db() as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS prediction_signals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        contract_id TEXT NOT NULL,
                        contract_question TEXT,
                        market_price REAL,
                        engine_probability REAL,
                        alpha REAL,
                        direction TEXT,
                        strength TEXT,
                        strength_score REAL,
                        confidence REAL,
                        supporting_agents INTEGER,
                        opposing_agents INTEGER,
                        reasoning TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                await db.executemany(
                    """INSERT INTO prediction_signals
                       (session_id, contract_id, contract_question, market_price,
                        engine_probability, alpha, direction, strength, strength_score,
                        confidence, supporting_agents, opposing_agents, reasoning)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            session_id, s.contract_id, s.contract_question,
                            s.market_price, s.engine_probability, s.alpha,
                            s.direction, s.strength, s.strength_score,
                            s.confidence, s.supporting_agents, s.opposing_agents,
                            s.reasoning,
                        )
                        for s in signals
                    ],
                )
                await db.commit()
            logger.info("Persisted %d signals for session=%s", len(signals), session_id)
        except Exception:
            logger.exception("Failed to persist signals session=%s", session_id)

    @staticmethod
    def _build_reasoning(
        question: str,
        market_price: float,
        estimate: ConsensusEstimate,
        alpha: float,
        direction: str,
    ) -> str:
        """Build human-readable reasoning for the signal."""
        market_pct = f"{market_price:.0%}"
        engine_pct = f"{estimate.probability:.0%}"
        alpha_pct = f"{alpha:+.1%}"

        dir_zh = {"BUY_YES": "買入 YES", "BUY_NO": "買入 NO", "HOLD": "觀望"}.get(
            direction, direction
        )

        return (
            f"市場定價 {market_pct}，引擎估算 {engine_pct}（alpha {alpha_pct}）。"
            f"{estimate.supporting_agents} 個代理人支持、"
            f"{estimate.opposing_agents} 個反對。"
            f"建議：{dir_zh}。{estimate.evidence_summary}"
        )
