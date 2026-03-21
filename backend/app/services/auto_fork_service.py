"""Auto-fork service — branch simulation at detected tipping points.

When TippingPointDetector fires (JSD > threshold), this service creates
two divergent branch sessions:

- **Path A (natural):** Snapshot of the simulation at fork round,
  continues the natural trajectory.
- **Path B (nudged):** Same snapshot, but with a counterfactual belief
  nudge applied — reversing or dampening the dominant shift.

Branches are created with ``status='created'`` and registered in
``scenario_branches`` with ``scenario_variant='auto_fork'``.  They are
NOT auto-started — the user (or a downstream orchestrator) decides when
to run them.

Guard: maximum 3 auto-forks per session to prevent runaway branching.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.services.emergence_tracker import TippingPoint
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("auto_fork_service")

# Adaptive fork budget: scale with simulation round count.
# Rationale: tipping points are rare in short simulations (15 rounds)
# and more frequent in long ones (30+ rounds).  A flat cap penalises
# long runs.  Formula: min(5, max(2, round_count // 10)).
# 15 rounds → 2 forks, 20 → 2, 30 → 3, 50 → 5.
# Additional guard: only fork when JSD ≥ 1.5× threshold (strong signal).
_MIN_AUTO_FORKS: int = 2
_MAX_AUTO_FORKS: int = 5
_JSD_STRONG_SIGNAL_MULTIPLIER: float = 1.5
_JSD_BASE_THRESHOLD: float = 0.15


@dataclass(frozen=True)
class AutoForkResult:
    """Immutable record of an auto-fork event."""
    parent_session_id: str
    fork_round: int
    natural_branch_id: str
    nudged_branch_id: str
    tipping_direction: str
    nudge_description: str


def compute_fork_budget(round_count: int) -> int:
    """Adaptive fork budget based on simulation length.

    Short simulations (15 rounds) get 2 forks; long ones (50+) get up to 5.
    Grounded in the observation that tipping point frequency scales roughly
    linearly with round count in agent-based models.

    Args:
        round_count: Total rounds in the simulation.

    Returns:
        Maximum number of auto-forks allowed.
    """
    return min(_MAX_AUTO_FORKS, max(_MIN_AUTO_FORKS, round_count // 10))


async def fork_at_tipping_point(
    session_id: str,
    tipping: TippingPoint,
    current_beliefs: dict[str, dict[str, float]],
    auto_fork_count: int,
    round_count: int = 20,
) -> AutoForkResult | None:
    """Create two divergent branches at a tipping point.

    Guards:
    - Adaptive fork budget: ``min(5, max(2, round_count // 10))``.
    - JSD signal strength: only forks when JSD ≥ 1.5× base threshold
      (i.e. ≥ 0.225), filtering out marginal tipping points.

    Args:
        session_id: Parent simulation session ID.
        tipping: Detected TippingPoint event.
        current_beliefs: agent_id → {metric_id → belief float}.
        auto_fork_count: Current number of auto-forks for this session.
        round_count: Total rounds in the simulation (for budget calc).

    Returns:
        AutoForkResult with both branch IDs, or None if guard triggered
        or an error occurred.
    """
    budget = compute_fork_budget(round_count)
    if auto_fork_count >= budget:
        logger.info(
            "Auto-fork guard: budget exhausted (%d/%d) session=%s",
            auto_fork_count, budget, session_id,
        )
        return None

    # Only fork on strong tipping signals (JSD ≥ 1.5× threshold)
    jsd_min = _JSD_BASE_THRESHOLD * _JSD_STRONG_SIGNAL_MULTIPLIER
    if tipping.kl_divergence < jsd_min:
        logger.debug(
            "Auto-fork skip: JSD %.3f < strong threshold %.3f session=%s round=%d",
            tipping.kl_divergence, jsd_min, session_id, tipping.round_number,
        )
        return None

    round_num = tipping.round_number
    direction = tipping.change_direction
    natural_id = str(uuid.uuid4())
    nudged_id = str(uuid.uuid4())

    # Compute counterfactual nudge
    nudged_beliefs = _apply_counterfactual_nudge(current_beliefs, direction)
    nudge_desc = _nudge_description(direction, round_num)

    try:
        async with get_db() as db:
            # Fetch parent session metadata
            row = await (
                await db.execute(
                    "SELECT config_json, scenario_type, agent_count, round_count, "
                    "llm_provider, llm_model FROM simulation_sessions WHERE id = ?",
                    (session_id,),
                )
            ).fetchone()
            if row is None:
                logger.warning("Auto-fork: parent session %s not found", session_id)
                return None

            config = json.loads(row["config_json"]) if row["config_json"] else {}
            scenario_type = row["scenario_type"] or "kg_driven"

            # Create both branch sessions
            for branch_id, label, variant_tag in [
                (natural_id, f"Auto-fork R{round_num}: natural path", "natural"),
                (nudged_id, f"Auto-fork R{round_num}: nudged ({direction})", "nudged"),
            ]:
                branch_config = {
                    **config,
                    "parent_session_id": session_id,
                    "fork_round": round_num,
                    "auto_fork_variant": variant_tag,
                }
                if variant_tag == "nudged":
                    branch_config["belief_nudge_direction"] = direction

                await db.execute(
                    """INSERT INTO simulation_sessions
                       (id, name, sim_mode, scenario_type, status, config_json,
                        agent_count, round_count, llm_provider, llm_model,
                        oasis_db_path, created_at)
                       VALUES (?, ?, 'parallel', ?, 'created', ?,
                               ?, ?, ?, ?, '', datetime('now'))""",
                    (
                        branch_id, label, scenario_type,
                        json.dumps(branch_config, ensure_ascii=False),
                        row["agent_count"], row["round_count"],
                        row["llm_provider"] or "openrouter",
                        row["llm_model"] or "deepseek/deepseek-v3.2",
                    ),
                )

            # Copy agent profiles to both branches
            for branch_id in (natural_id, nudged_id):
                await db.execute(
                    """INSERT INTO agent_profiles
                       (id, session_id, agent_type, age, sex, district, occupation,
                        income_bracket, education_level, marital_status, housing_type,
                        openness, conscientiousness, extraversion, agreeableness,
                        neuroticism, monthly_income, savings, oasis_persona,
                        oasis_username, created_at)
                       SELECT
                        NULL, ?, agent_type, age, sex, district, occupation,
                        income_bracket, education_level, marital_status, housing_type,
                        openness, conscientiousness, extraversion, agreeableness,
                        neuroticism, monthly_income, savings, oasis_persona,
                        oasis_username, datetime('now')
                       FROM agent_profiles WHERE session_id = ?""",
                    (branch_id, session_id),
                )

            # Copy memories up to fork round for both branches
            for branch_id in (natural_id, nudged_id):
                await db.execute(
                    """INSERT INTO agent_memories
                       (session_id, agent_id, round_number, memory_text,
                        salience_score, memory_type, created_at)
                       SELECT ?, agent_id, round_number, memory_text,
                              salience_score, memory_type, datetime('now')
                       FROM agent_memories
                       WHERE session_id = ? AND round_number <= ?""",
                    (branch_id, session_id, round_num),
                )

            # Copy simulation_actions up to fork round
            for branch_id in (natural_id, nudged_id):
                await db.execute(
                    """INSERT INTO simulation_actions
                       (session_id, agent_id, round_number, action_type,
                        content, platform, created_at)
                       SELECT ?, agent_id, round_number, action_type,
                              content, platform, datetime('now')
                       FROM simulation_actions
                       WHERE session_id = ? AND round_number <= ?""",
                    (branch_id, session_id, round_num),
                )

            # --- Deep copy: additional dynamic state tables ---
            # Copy belief_states up to fork round
            for branch_id in (natural_id, nudged_id):
                try:
                    await db.execute(
                        """INSERT OR IGNORE INTO belief_states
                           (session_id, agent_id, topic, stance,
                            confidence, evidence_count, round_number,
                            created_at)
                           SELECT ?, agent_id, topic, stance,
                                  confidence, evidence_count, round_number,
                                  datetime('now')
                           FROM belief_states
                           WHERE session_id = ? AND round_number <= ?""",
                        (branch_id, session_id, round_num),
                    )
                except Exception:
                    logger.debug("belief_states copy skipped (table may not exist)")

            # Copy emotional_states up to fork round
            for branch_id in (natural_id, nudged_id):
                try:
                    await db.execute(
                        """INSERT OR IGNORE INTO emotional_states
                           (session_id, agent_id, round_number,
                            valence, arousal, dominance, created_at)
                           SELECT ?, agent_id, round_number,
                                  valence, arousal, dominance, datetime('now')
                           FROM emotional_states
                           WHERE session_id = ? AND round_number <= ?""",
                        (branch_id, session_id, round_num),
                    )
                except Exception:
                    logger.debug("emotional_states copy skipped (table may not exist)")

            # Copy agent_relationships (no round_number — copy all)
            for branch_id in (natural_id, nudged_id):
                try:
                    await db.execute(
                        """INSERT OR IGNORE INTO agent_relationships
                           (session_id, agent_a_id, agent_b_id,
                            relationship_type, influence_weight,
                            trust_score, created_at)
                           SELECT ?, agent_a_id, agent_b_id,
                                  relationship_type, influence_weight,
                                  trust_score, datetime('now')
                           FROM agent_relationships WHERE session_id = ?""",
                        (branch_id, session_id),
                    )
                except Exception:
                    logger.debug("agent_relationships copy skipped (table may not exist)")

            # Copy kg_edges (has round_number — filter by fork round)
            for branch_id in (natural_id, nudged_id):
                try:
                    await db.execute(
                        """INSERT OR IGNORE INTO kg_edges
                           (session_id, source_id, target_id, relation_type,
                            description, weight, round_number, created_at)
                           SELECT ?, source_id, target_id, relation_type,
                                  description, weight, round_number,
                                  datetime('now')
                           FROM kg_edges
                           WHERE session_id = ? AND round_number <= ?""",
                        (branch_id, session_id, round_num),
                    )
                except Exception:
                    logger.debug("kg_edges copy skipped (table may not exist)")

            # Copy cognitive_dissonance (has round_number — filter by fork round)
            for branch_id in (natural_id, nudged_id):
                try:
                    await db.execute(
                        """INSERT OR IGNORE INTO cognitive_dissonance
                           (session_id, agent_id, round_number,
                            dissonance_score, conflicting_pairs_json,
                            action_belief_gap, resolution_strategy,
                            created_at)
                           SELECT ?, agent_id, round_number,
                                  dissonance_score, conflicting_pairs_json,
                                  action_belief_gap, resolution_strategy,
                                  datetime('now')
                           FROM cognitive_dissonance
                           WHERE session_id = ? AND round_number <= ?""",
                        (branch_id, session_id, round_num),
                    )
                except Exception:
                    logger.debug("cognitive_dissonance copy skipped (table may not exist)")

            # Persist nudged beliefs as round fork_round+1 belief_snapshot
            # so the nudged branch starts with altered beliefs
            for agent_id, beliefs in nudged_beliefs.items():
                await db.execute(
                    """INSERT INTO agent_memories
                       (session_id, agent_id, round_number, memory_text,
                        salience_score, memory_type, created_at)
                       VALUES (?, ?, ?, ?, 1.0, 'belief_snapshot', datetime('now'))""",
                    (
                        nudged_id, agent_id, round_num,
                        json.dumps(beliefs, ensure_ascii=False),
                    ),
                )

            # Register in scenario_branches
            for branch_id, label in [
                (natural_id, f"Auto-fork R{round_num}: natural path"),
                (nudged_id, f"Auto-fork R{round_num}: nudged ({direction})"),
            ]:
                await db.execute(
                    """INSERT OR IGNORE INTO scenario_branches
                       (id, parent_session_id, branch_session_id, scenario_variant,
                        label, fork_round, created_at)
                       VALUES (?, ?, ?, 'auto_fork', ?, ?, datetime('now'))""",
                    (str(uuid.uuid4()), session_id, branch_id, label, round_num),
                )

            await db.commit()

        logger.info(
            "Auto-fork created session=%s round=%d direction=%s natural=%s nudged=%s",
            session_id, round_num, direction, natural_id[:8], nudged_id[:8],
        )
        return AutoForkResult(
            parent_session_id=session_id,
            fork_round=round_num,
            natural_branch_id=natural_id,
            nudged_branch_id=nudged_id,
            tipping_direction=direction,
            nudge_description=nudge_desc,
        )

    except Exception:
        logger.exception(
            "Auto-fork failed session=%s round=%d", session_id, round_num
        )
        return None


def _apply_counterfactual_nudge(
    beliefs: dict[str, dict[str, float]],
    direction: str,
) -> dict[str, dict[str, float]]:
    """Compute nudged belief state — reverse the tipping point shift.

    Args:
        beliefs: agent_id → {metric_id → belief float [0,1]}.
        direction: TippingPoint.change_direction.

    Returns:
        New beliefs dict with nudge applied (never mutates input).
    """
    result: dict[str, dict[str, float]] = {}
    for agent_id, agent_beliefs in beliefs.items():
        nudged: dict[str, float] = {}
        for metric, val in agent_beliefs.items():
            deviation = val - 0.5
            if direction == "polarize":
                # Counter polarization: compress beliefs toward center
                nudged[metric] = max(0.0, min(1.0, 0.5 + deviation * 0.5))
            elif direction == "converge":
                # Counter convergence: amplify diversity
                nudged[metric] = max(0.0, min(1.0, 0.5 + deviation * 1.5))
            elif direction == "split":
                # Counter split: reverse the shift
                nudged[metric] = max(0.0, min(1.0, 0.5 - deviation))
            else:
                # Unknown direction: mild compression
                nudged[metric] = max(0.0, min(1.0, 0.5 + deviation * 0.7))
        result[agent_id] = nudged
    return result


def _nudge_description(direction: str, round_num: int) -> str:
    """Human-readable description of the counterfactual nudge."""
    descriptions = {
        "polarize": f"R{round_num}: 壓縮極化信念向中心 (counter-polarization)",
        "converge": f"R{round_num}: 放大信念多樣性 (counter-convergence)",
        "split": f"R{round_num}: 翻轉信念偏移方向 (counter-split)",
    }
    return descriptions.get(
        direction,
        f"R{round_num}: 溫和壓縮信念 (mild compression)",
    )
