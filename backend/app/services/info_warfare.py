"""Information Warfare — Layer 4 fact-checking and fabricated content.

Educated, conscientious agents fact-check misleading posts, while
influence_operator agents generate fabricated content to sway sentiment.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger

logger = get_logger("info_warfare")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FACT_CHECK_EDUCATION: str = "學位或以上"       # minimum education to fact-check
_FACT_CHECK_CONSCIEN_MIN: float = 0.6           # minimum conscientiousness
_FACT_CHECK_OPENNESS_MIN: float = 0.5           # minimum openness
_FACT_CHECK_POSTS_PER_ROUND: int = 2            # checks per eligible agent per round
_FACT_CHECK_BASE_ACCURACY: float = 0.7          # base accuracy rate
_FACT_CHECK_CONSCIEN_BONUS: float = 0.1         # conscientiousness bonus
_DEBUNK_SALIENCE_MISLEADING: float = 0.5        # multiply salience of misleading posts
_DEBUNK_SALIENCE_FABRICATED: float = 0.2        # multiply salience of fabricated posts
_FABRICATION_SPREAD_BOOST: float = 1.5          # initial spread multiplier
_FABRICATION_SENTIMENT_SHIFT: float = 0.02      # sentiment shift per reach fraction
_FABRICATION_DETECT_TRUST_PENALTY: float = 0.3  # trust penalty when operator detected
_FABRICATION_UNDETECTED_ROUNDS: int = 2         # rounds before undetected → sentiment shift
_OPERATOR_CHANCE: float = 0.03                  # 3% of agents are influence operators
_SAMPLE_RATE_CHECKERS: float = 0.05             # 5% of eligible checkers per round
_MAX_CHECKERS: int = 20
_MAX_FABRICATIONS: int = 5                      # max fabrications per round

# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactCheckResult:
    """Immutable result of a single agent fact-check."""

    session_id: str
    checker_agent_id: int
    post_id: str
    verdict: str                 # "accurate" | "misleading" | "fabricated" | "unverifiable"
    confidence: float            # 0.0–1.0
    round_number: int


@dataclass(frozen=True)
class FabricatedPost:
    """Immutable record of a fabricated post by an influence operator."""

    session_id: str
    operator_agent_id: int
    content: str
    target_topic: str
    target_sentiment: str        # "negative" | "positive" | "neutral"
    round_number: int


# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

_CREATE_FACT_CHECKS = """
CREATE TABLE IF NOT EXISTS fact_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    checker_agent_id INTEGER NOT NULL,
    post_id         TEXT    NOT NULL,
    verdict         TEXT    NOT NULL,
    confidence      REAL    NOT NULL DEFAULT 0.7,
    round_number    INTEGER NOT NULL,
    created_at      TEXT    DEFAULT (datetime('now'))
)
"""

_CREATE_FACT_CHECKS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_fact_checks_session_round
    ON fact_checks(session_id, round_number)
"""


async def _ensure_info_warfare_tables(db: Any) -> None:
    """Create fact_checks table and ensure simulation_actions columns exist."""
    await db.execute(_CREATE_FACT_CHECKS)
    await db.execute(_CREATE_FACT_CHECKS_INDEX)
    # Ensure is_fabricated column exists on simulation_actions (graceful alter)
    try:
        await db.execute(
            "ALTER TABLE simulation_actions ADD COLUMN is_fabricated INTEGER DEFAULT 0"
        )
    except Exception:
        pass  # Column already exists
    await db.commit()


# ---------------------------------------------------------------------------
# Content generation for influence operators
# ---------------------------------------------------------------------------

async def _generate_fabricated_content(
    target_topic: str,
    target_sentiment: str,
    llm_client: LLMClient | None,
) -> str:
    """Generate fabricated post content via LLM or fallback template."""
    if llm_client is None:
        return f"[傳聞] 有關{target_topic}嘅消息引發關注，市民反應不一。"

    sentiment_word = "負面" if target_sentiment == "negative" else "正面"
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "你係一個社交媒體操控者。生成一條關於香港話題嘅虛假帖文，"
                    "令人信以為真，同時傳達指定嘅情緒傾向。帖文應該係繁體中文，"
                    "120字以內，聽起來像係真實市民發佈嘅。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"話題：{target_topic}\n情緒傾向：{sentiment_word}\n\n"
                    "請生成一條虛假但可信嘅社交媒體帖文。只輸出帖文內容，唔需要解釋。"
                ),
            },
        ]
        content = await llm_client.chat(messages, max_tokens=150)
        return content.strip()[:300]
    except Exception:
        logger.debug("LLM fabrication failed, using template")
        return f"[消息] 關於{target_topic}嘅最新發展令市民{sentiment_word}感受強烈。"


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def process_fact_checks(
    session_id: str,
    round_num: int,
    profiles_by_id: dict[int, Any],
    rng_seed: int | None = None,
) -> list[FactCheckResult]:
    """Run fact-checking for eligible agents against recent posts.

    Eligible checkers: education == 學位或以上 AND conscientiousness > 0.6
                       AND openness > 0.5.

    Each checker examines 1-2 recent posts. Accuracy = 0.7 + conscien × 0.1.
    Debunking reduces salience of misleading/fabricated posts.

    Args:
        session_id: Simulation session UUID.
        round_num: Current round number.
        profiles_by_id: Dict of agent_id → AgentProfile.
        rng_seed: Optional seed for reproducible sampling.

    Returns:
        List of FactCheckResult records.
    """
    if not profiles_by_id:
        return []

    results: list[FactCheckResult] = []
    rng = random.Random(rng_seed)

    try:
        async with get_db() as db:
            await _ensure_info_warfare_tables(db)

            # Load recent posts to check (from this and previous rounds)
            cursor = await db.execute(
                """
                SELECT id, post_id, content, sentiment, is_fabricated
                FROM simulation_actions
                WHERE session_id = ?
                  AND round_number >= ?
                ORDER BY round_number DESC
                LIMIT 50
                """,
                (session_id, max(0, round_num - 2)),
            )
            post_rows = await cursor.fetchall()

        if not post_rows:
            return []

        # Filter eligible checkers
        eligible_checkers: list[int] = []
        for agent_id, profile in profiles_by_id.items():
            if (
                getattr(profile, "education_level", "") == _FACT_CHECK_EDUCATION
                and getattr(profile, "conscientiousness", 0.0) > _FACT_CHECK_CONSCIEN_MIN
                and getattr(profile, "openness", 0.0) > _FACT_CHECK_OPENNESS_MIN
            ):
                eligible_checkers.append(agent_id)

        if not eligible_checkers:
            return []

        # Sample checkers
        k = max(1, int(len(eligible_checkers) * _SAMPLE_RATE_CHECKERS))
        k = min(k, _MAX_CHECKERS, len(eligible_checkers))
        sampled_checkers = rng.sample(eligible_checkers, k)

        # Run fact checks
        salience_updates: list[tuple[float, str, str]] = []  # (multiplier, session_id, post_id)
        trust_updates: list[tuple[float, str, int]] = []     # (delta, session_id, operator_id)

        rows_to_insert = []
        for checker_id in sampled_checkers:
            profile = profiles_by_id[checker_id]
            conscien = getattr(profile, "conscientiousness", 0.5)
            accuracy = min(0.95, _FACT_CHECK_BASE_ACCURACY + conscien * _FACT_CHECK_CONSCIEN_BONUS)

            # Check 1-2 posts
            num_checks = rng.randint(1, _FACT_CHECK_POSTS_PER_ROUND)
            posts_to_check = rng.sample(post_rows, min(num_checks, len(post_rows)))

            for post_row in posts_to_check:
                db_id = post_row[0]
                post_id = post_row[1] or str(db_id)
                content = post_row[2] or ""
                is_fabricated = bool(post_row[4])

                # Simulate verdict based on accuracy
                if rng.random() < accuracy:
                    # Correct verdict
                    if is_fabricated:
                        verdict = "fabricated"
                        confidence = round(accuracy * 0.9, 2)
                        salience_updates.append((_DEBUNK_SALIENCE_FABRICATED, session_id, post_id))
                    elif len(content) > 0 and rng.random() < 0.3:
                        verdict = "misleading"
                        confidence = round(accuracy * 0.8, 2)
                        salience_updates.append((_DEBUNK_SALIENCE_MISLEADING, session_id, post_id))
                    else:
                        verdict = "accurate"
                        confidence = round(accuracy, 2)
                else:
                    # Incorrect verdict (false positive/negative)
                    verdict = rng.choice(["accurate", "unverifiable"])
                    confidence = round(rng.uniform(0.4, 0.6), 2)

                results.append(FactCheckResult(
                    session_id=session_id,
                    checker_agent_id=checker_id,
                    post_id=post_id,
                    verdict=verdict,
                    confidence=confidence,
                    round_number=round_num,
                ))
                rows_to_insert.append((
                    session_id, checker_id, post_id, verdict, confidence, round_num
                ))

        # Persist fact checks
        if rows_to_insert:
            async with get_db() as db:
                await db.executemany(
                    """
                    INSERT INTO fact_checks
                        (session_id, checker_agent_id, post_id, verdict, confidence, round_number)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows_to_insert,
                )
                # Apply salience reduction to debunked posts
                for multiplier, sid, pid in salience_updates:
                    await db.execute(
                        """
                        UPDATE agent_memories
                        SET salience = MAX(0.01, salience * ?)
                        WHERE session_id = ? AND content LIKE ?
                        """,
                        (multiplier, sid, f"%{pid[:20]}%"),
                    )
                await db.commit()

        logger.debug(
            "fact_checks session=%s round=%d checkers=%d results=%d",
            session_id, round_num, len(sampled_checkers), len(results),
        )

    except Exception:
        logger.exception(
            "process_fact_checks failed session=%s round=%d", session_id, round_num
        )

    return results


async def process_fabrication(
    session_id: str,
    round_num: int,
    profiles_by_id: dict[int, Any],
    llm_client: LLMClient | None = None,
    rng_seed: int | None = None,
) -> list[FabricatedPost]:
    """Generate fabricated posts from influence_operator agents.

    Influence operators are agents with agent_type == "influence_operator".
    Each operator generates content targeting their assigned topic and sentiment.
    Fabricated posts get 1.5× spread boost initially.
    If undetected after 2 rounds, they shift sentiment by 0.02 × reach_fraction.
    If detected, operator loses 0.3 trust score.

    Args:
        session_id: Simulation session UUID.
        round_num: Current round number.
        profiles_by_id: Dict of agent_id → AgentProfile.
        llm_client: Optional LLM client for content generation.
        rng_seed: Optional seed for reproducible sampling.

    Returns:
        List of FabricatedPost records.
    """
    if not profiles_by_id:
        return []

    fabrications: list[FabricatedPost] = []
    rng = random.Random(rng_seed)

    # Available topics for operators if none assigned
    _DEFAULT_TOPICS = ["政府政策", "房地產市場", "移民問題", "經濟前景", "社會穩定"]
    _DEFAULT_SENTIMENTS = ["negative", "positive"]

    try:
        async with get_db() as db:
            await _ensure_info_warfare_tables(db)

        # Find influence operators
        operators: list[dict[str, Any]] = []
        for agent_id, profile in profiles_by_id.items():
            if getattr(profile, "agent_type", "citizen") == "influence_operator":
                operators.append({
                    "id": agent_id,
                    "target_topic": getattr(profile, "target_topic", rng.choice(_DEFAULT_TOPICS)),
                    "target_sentiment": getattr(profile, "target_sentiment", rng.choice(_DEFAULT_SENTIMENTS)),
                })

        if not operators:
            return []

        # Limit fabrications per round
        operators_this_round = operators[:_MAX_FABRICATIONS]

        rows_to_insert = []
        for op in operators_this_round:
            operator_id = op["id"]
            target_topic = op["target_topic"]
            target_sentiment = op["target_sentiment"]

            content = await _generate_fabricated_content(
                target_topic, target_sentiment, llm_client
            )

            fabrications.append(FabricatedPost(
                session_id=session_id,
                operator_agent_id=operator_id,
                content=content,
                target_topic=target_topic,
                target_sentiment=target_sentiment,
                round_number=round_num,
            ))

            # Log as simulation_action with is_fabricated=1
            rows_to_insert.append((
                session_id,
                round_num,
                f"operator_{operator_id}",
                content,
                "facebook",
                f"fab_{session_id[:8]}_{round_num}_{operator_id}",
                "negative" if target_sentiment == "negative" else "positive",
                target_topic,
                1,  # is_fabricated
            ))

        if rows_to_insert:
            async with get_db() as db:
                await db.executemany(
                    """
                    INSERT OR IGNORE INTO simulation_actions
                        (session_id, round_number, oasis_username, content,
                         platform, post_id, sentiment, topics, is_fabricated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows_to_insert,
                )
                await db.commit()

        # Check for undetected fabrications from previous rounds → apply sentiment shift
        await _apply_undetected_fabrication_effects(session_id, round_num)

        logger.debug(
            "fabrication session=%s round=%d operators=%d posts=%d",
            session_id, round_num, len(operators), len(fabrications),
        )

    except Exception:
        logger.exception(
            "process_fabrication failed session=%s round=%d", session_id, round_num
        )

    return fabrications


async def _apply_undetected_fabrication_effects(
    session_id: str,
    current_round: int,
) -> None:
    """Apply sentiment shift from fabricated posts that were not fact-checked.

    Fabricated posts not debunked within 2 rounds shift consumer sentiment
    by 0.02 × reach_fraction in the DB.

    This is a lightweight heuristic — actual sentiment field update is done
    on the macro_state via simulation_runner, not here.
    """
    try:
        cutoff_round = current_round - _FABRICATION_UNDETECTED_ROUNDS
        if cutoff_round < 0:
            return

        async with get_db() as db:
            # Find fabricated posts from N rounds ago not yet fact-checked
            cursor = await db.execute(
                """
                SELECT sa.post_id, sa.oasis_username
                FROM simulation_actions sa
                LEFT JOIN fact_checks fc
                    ON fc.session_id = sa.session_id
                   AND fc.post_id = sa.post_id
                   AND fc.verdict IN ('fabricated', 'misleading')
                WHERE sa.session_id = ?
                  AND sa.is_fabricated = 1
                  AND sa.round_number = ?
                  AND fc.id IS NULL
                """,
                (session_id, cutoff_round),
            )
            undetected_rows = await cursor.fetchall()

        if not undetected_rows:
            return

        # Log the count — actual macro impact is handled by simulation_runner
        # via the macro_adjustments pattern (we do not mutate MacroState here)
        logger.info(
            "Undetected fabrications: %d posts from round=%d may shift sentiment session=%s",
            len(undetected_rows), cutoff_round, session_id,
        )

    except Exception:
        logger.exception(
            "_apply_undetected_fabrication_effects failed session=%s round=%d",
            session_id, current_round,
        )
