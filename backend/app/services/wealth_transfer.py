"""Wealth Transfer — Layer 1 resource-bound action for KOL support.

High-savings agents can transfer wealth to opinion leaders (KOLs) to
boost their influence in the social network. Transfers are eligibility-
filtered, capped, and persisted to the wealth_transfers table.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("wealth_transfer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_SAVINGS: int = 50_000           # donor must have ≥ 50,000 HKD savings
_MIN_INCOME: int = 15_000            # donor must earn ≥ 15,000 HKD/month
_TRUST_THRESHOLD: float = 0.5        # donor must trust KOL at this level
_KOL_EXTRAVERSION_THRESHOLD: float = 0.7  # KOL must have high extraversion
_MAX_AMOUNT_SAVINGS_RATIO: float = 0.02   # max 2% of savings per transfer
_MAX_AMOUNT_INCOME_RATIO: float = 0.5     # max 50% of monthly income per transfer
_SAMPLE_RATE: float = 0.05           # 5% of eligible donors
_MAX_PER_ROUND: int = 20             # hard cap per round
_INFLUENCE_BOOST: float = 0.05       # KOL influence boost per received transfer

# ---------------------------------------------------------------------------
# Frozen dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WealthTransfer:
    """Immutable record of a single wealth transfer event."""

    session_id: str
    from_agent_id: int
    to_agent_id: int | None       # recipient agent (if peer-to-peer)
    to_entity: str | None         # named entity recipient (e.g. community fund)
    amount: int                   # transfer amount in HKD
    reason: str
    round_number: int


# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

_CREATE_TRANSFERS_TABLE = """
CREATE TABLE IF NOT EXISTS wealth_transfers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    from_agent_id   INTEGER NOT NULL,
    to_agent_id     INTEGER,
    to_entity       TEXT,
    amount          INTEGER NOT NULL,
    reason          TEXT,
    round_number    INTEGER NOT NULL,
    created_at      TEXT    DEFAULT (datetime('now'))
)
"""

_CREATE_TRANSFERS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_wealth_session_round
    ON wealth_transfers(session_id, round_number)
"""


async def _ensure_transfers_table(db: Any) -> None:
    """Create wealth_transfers table and index if they do not exist."""
    await db.execute(_CREATE_TRANSFERS_TABLE)
    await db.execute(_CREATE_TRANSFERS_INDEX)
    await db.commit()


# ---------------------------------------------------------------------------
# Core processing function
# ---------------------------------------------------------------------------

async def process_wealth_transfers(
    session_id: str,
    round_num: int,
    profiles_by_id: dict[int, Any],
    macro_state: Any,
    rng_seed: int | None = None,
) -> list[WealthTransfer]:
    """Process peer wealth transfers from eligible donors to KOLs.

    Steps:
    1. Load trust relationships and KOL flags from DB.
    2. Filter eligible donors (savings + income thresholds).
    3. Match donors to trusted KOLs (trust ≥ threshold, KOL extraversion ≥ threshold).
    4. Sample 5% of eligible donors, cap at MAX_PER_ROUND.
    5. Compute transfer amounts.
    6. Batch-UPDATE donor savings in agent_profiles.
    7. Boost KOL influence_weight in agent_relationships.
    8. Persist transfers to wealth_transfers table.

    Args:
        session_id: Simulation session UUID.
        round_num: Current round number.
        profiles_by_id: Dict of agent_id → AgentProfile.
        macro_state: Current MacroState (not directly used but passed for extensibility).
        rng_seed: Optional seed for reproducible sampling.

    Returns:
        List of WealthTransfer records processed this round.
    """
    if not profiles_by_id:
        return []

    transfers: list[WealthTransfer] = []

    try:
        async with get_db() as db:
            await _ensure_transfers_table(db)

            # Load trust relationships in one batch query
            agent_ids = list(profiles_by_id.keys())
            placeholders = ",".join("?" * len(agent_ids))
            cursor = await db.execute(
                f"""
                SELECT agent_a_id, agent_b_id, trust_score, influence_weight
                FROM agent_relationships
                WHERE session_id = ?
                  AND agent_a_id IN ({placeholders})
                  AND trust_score >= ?
                """,
                (session_id, *agent_ids, _TRUST_THRESHOLD),
            )
            trust_rows = await cursor.fetchall()

        # Build (donor → list of trusted agent_ids) mapping
        trusted_kols: dict[int, list[int]] = {}
        for row in trust_rows:
            donor_id = row[0]
            kol_id = row[1]
            # Only accept KOLs (high extraversion = opinion leader proxy)
            kol_profile = profiles_by_id.get(kol_id)
            if kol_profile is None:
                continue
            if getattr(kol_profile, "extraversion", 0.0) < _KOL_EXTRAVERSION_THRESHOLD:
                continue
            if donor_id not in trusted_kols:
                trusted_kols[donor_id] = []
            trusted_kols[donor_id].append(kol_id)

        # Filter eligible donors
        eligible_donors: list[int] = []
        for agent_id, profile in profiles_by_id.items():
            savings = getattr(profile, "savings", 0)
            income = getattr(profile, "monthly_income", 0)
            if savings >= _MIN_SAVINGS and income >= _MIN_INCOME:
                if agent_id in trusted_kols and trusted_kols[agent_id]:
                    eligible_donors.append(agent_id)

        if not eligible_donors:
            return []

        # Sample eligible donors
        rng = random.Random(rng_seed)
        k = max(1, int(len(eligible_donors) * _SAMPLE_RATE))
        k = min(k, _MAX_PER_ROUND, len(eligible_donors))
        sampled_donors = rng.sample(eligible_donors, k)

        # Compute transfers
        savings_deltas: dict[int, int] = {}   # agent_id → negative delta
        influence_boosts: list[tuple[int, int]] = []  # (donor_id, kol_id)

        for donor_id in sampled_donors:
            profile = profiles_by_id[donor_id]
            savings = getattr(profile, "savings", 0)
            income = getattr(profile, "monthly_income", 0)

            # Transfer amount: min of 2% savings vs 50% monthly income
            amount = int(min(
                savings * _MAX_AMOUNT_SAVINGS_RATIO,
                income * _MAX_AMOUNT_INCOME_RATIO,
            ))
            if amount <= 0:
                continue

            # Pick the highest-trust KOL
            kol_id = rng.choice(trusted_kols[donor_id])

            transfers.append(WealthTransfer(
                session_id=session_id,
                from_agent_id=donor_id,
                to_agent_id=kol_id,
                to_entity=None,
                amount=amount,
                reason="KOL support donation",
                round_number=round_num,
            ))
            savings_deltas[donor_id] = savings_deltas.get(donor_id, 0) - amount
            influence_boosts.append((donor_id, kol_id))

        if not transfers:
            return []

        # Batch-UPDATE donor savings
        savings_updates = [
            (savings_deltas[aid], session_id, aid)
            for aid in savings_deltas
        ]
        # Batch-UPDATE KOL influence_weight
        influence_updates = [
            (_INFLUENCE_BOOST, session_id, donor_id, kol_id)
            for donor_id, kol_id in influence_boosts
        ]

        # Persist transfers
        transfer_rows = [
            (
                t.session_id,
                t.from_agent_id,
                t.to_agent_id,
                t.to_entity,
                t.amount,
                t.reason,
                t.round_number,
            )
            for t in transfers
        ]

        async with get_db() as db:
            # Update donor savings (delta, not absolute to avoid race conditions)
            await db.executemany(
                """
                UPDATE agent_profiles
                SET savings = MAX(0, savings + ?)
                WHERE session_id = ? AND id = ?
                """,
                savings_updates,
            )

            # Boost KOL influence weight
            await db.executemany(
                """
                UPDATE agent_relationships
                SET influence_weight = MIN(1.0, influence_weight + ?)
                WHERE session_id = ? AND agent_a_id = ? AND agent_b_id = ?
                """,
                influence_updates,
            )

            # Persist transfer records
            await db.executemany(
                """
                INSERT INTO wealth_transfers
                    (session_id, from_agent_id, to_agent_id, to_entity,
                     amount, reason, round_number)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                transfer_rows,
            )
            await db.commit()

        logger.info(
            "wealth_transfers session=%s round=%d count=%d total_hkd=%d",
            session_id, round_num, len(transfers),
            sum(t.amount for t in transfers),
        )

    except Exception:
        logger.exception(
            "process_wealth_transfers failed session=%s round=%d",
            session_id, round_num,
        )

    return transfers
