"""Swarm Ensemble — probability cloud from genuine agent interactions.

Runs the same scenario N times with different random seeds in lite mode
(rule-based decisions, no LLM, no OASIS subprocess).  Each run executes
the full round loop with all emergence hooks — trust, emotions, belief
propagation, faction formation, tipping points.  Because the engine has
6+ stochastic sources (agent sampling, emotional filtering, cognitive
dissonance resolution, triadic closure, feed ranking), each run produces
a genuinely different trajectory.

The aggregate across all runs forms a *probability cloud*: a distribution
of possible futures grounded in realistic agent behaviour, not statistical
perturbation.

Architecture::

    Phase A:  1 × full LLM simulation (baseline trajectory)
    Phase B:  N × lite_ensemble dry_run (same conditions, different seeds)
    Phase C:  Aggregate outcomes → probability cloud + confidence intervals

Usage::

    cloud = await SwarmEnsemble().run(session_id, n_replicas=50)
    # cloud.outcome_distribution = {"escalation": 0.42, "stalemate": 0.31, ...}
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("swarm_ensemble")

# Default replicas: 50 provides ±7% CI on binary outcomes (95% conf).
# For ±5% precision, use 100+.  Each replica is zero-LLM so cost ≈ $0.
_DEFAULT_REPLICAS: int = 50
_MAX_REPLICAS: int = 500
_MAX_CONCURRENT: int = 3


@dataclass(frozen=True)
class TrajectoryOutcome:
    """Immutable summary of one simulation trajectory."""
    replica_index: int
    branch_session_id: str
    faction_count: int
    tipping_point_rounds: tuple[int, ...]
    dominant_faction_size_ratio: float  # largest faction / total agents
    final_belief_centroid: dict[str, float]  # metric → avg belief
    polarization_score: float  # std of beliefs across agents


@dataclass(frozen=True)
class ProbabilityCloud:
    """Aggregate result from N genuine simulation trajectories."""
    parent_session_id: str
    n_replicas: int
    n_completed: int
    trajectories: tuple[TrajectoryOutcome, ...]
    # Derived statistics
    avg_faction_count: float
    tipping_probability: float  # fraction of runs with ≥1 tipping point
    avg_polarization: float
    belief_cloud: dict[str, tuple[float, float, float]]  # metric → (p25, median, p75)
    # Named outcome distribution (from surrogate or faction-based clustering)
    outcome_distribution: dict[str, float]
    confidence_intervals: dict[str, tuple[float, float]]


class SwarmEnsemble:
    """Run N genuine agent-interaction replicas to build a probability cloud."""

    async def run(
        self,
        session_id: str,
        n_replicas: int = _DEFAULT_REPLICAS,
        fork_round: int | None = None,
    ) -> ProbabilityCloud:
        """Execute the swarm ensemble pipeline.

        1. Load parent session config + agent profiles.
        2. Determine fork_round (default: 50% of total rounds).
        3. Create N branch sessions copying ALL state up to fork_round
           (memories, beliefs, actions, emotional states, relationships).
        4. Run each branch from fork_round in lite_ensemble mode
           (rule-based hooks, full remaining rounds, no LLM).
        5. Extract outcome from each completed branch.
        6. Aggregate into ProbabilityCloud.

        Args:
            session_id: Completed Phase A simulation session ID.
            n_replicas: Number of replicas (capped at 500).
            fork_round: Round to fork from.  If None, defaults to 50%
                of total rounds (so replicas have deep Phase A initialization
                but enough remaining rounds for divergence).

        Returns:
            ProbabilityCloud with outcome distribution and statistics.
        """
        n_replicas = max(1, min(n_replicas, _MAX_REPLICAS))
        logger.info(
            "SwarmEnsemble: starting %d replicas for session=%s",
            n_replicas, session_id,
        )

        # Load parent session
        parent_config = await self._load_parent_config(session_id)
        if parent_config is None:
            raise ValueError(f"Session {session_id} not found")

        # Default fork_round: 50% of total rounds
        total_rounds = int(parent_config.get("round_count", 20))
        if fork_round is None:
            fork_round = max(1, total_rounds // 2)
        fork_round = max(1, min(fork_round, total_rounds - 1))

        logger.info(
            "SwarmEnsemble: fork_round=%d (of %d total) session=%s",
            fork_round, total_rounds, session_id,
        )

        # Create and run replicas in batches
        outcomes: list[TrajectoryOutcome] = []
        for batch_start in range(0, n_replicas, _MAX_CONCURRENT):
            batch_size = min(_MAX_CONCURRENT, n_replicas - batch_start)
            tasks = [
                self._run_replica(
                    parent_session_id=session_id,
                    parent_config=parent_config,
                    replica_index=batch_start + i,
                    fork_round=fork_round,
                )
                for i in range(batch_size)
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in batch_results:
                if isinstance(result, TrajectoryOutcome):
                    outcomes.append(result)
                else:
                    logger.warning("Replica failed: %s", result)

        logger.info(
            "SwarmEnsemble: %d/%d replicas completed session=%s",
            len(outcomes), n_replicas, session_id,
        )

        return self._aggregate(session_id, n_replicas, outcomes)

    async def _load_parent_config(self, session_id: str) -> dict[str, Any] | None:
        """Load parent session configuration."""
        async with get_db() as db:
            row = await (
                await db.execute(
                    "SELECT config_json, scenario_type, agent_count, round_count, "
                    "llm_provider, llm_model FROM simulation_sessions WHERE id = ?",
                    (session_id,),
                )
            ).fetchone()
        if row is None:
            return None
        config = json.loads(row["config_json"]) if row["config_json"] else {}
        config["scenario_type"] = row["scenario_type"]
        config["agent_count"] = row["agent_count"]
        config["round_count"] = row["round_count"]
        config["llm_provider"] = row["llm_provider"]
        config["llm_model"] = row["llm_model"]
        return config

    async def _run_replica(
        self,
        parent_session_id: str,
        parent_config: dict[str, Any],
        replica_index: int,
        fork_round: int = 10,
    ) -> TrajectoryOutcome:
        """Create a branch session and run it in lite_ensemble mode."""
        from backend.app.services.simulation_runner import SimulationRunner  # noqa: PLC0415

        branch_id = str(uuid.uuid4())
        label = f"Swarm replica #{replica_index + 1} ({parent_session_id[:8]})"

        # Branch config: same conditions, lite_ensemble mode, start from fork_round
        total_rounds = int(parent_config.get("round_count", 20))
        remaining_rounds = total_rounds - fork_round
        branch_config = {
            **parent_config,
            "parent_session_id": parent_session_id,
            "lite_ensemble": True,
            "swarm_replica_index": replica_index,
            "round_count": remaining_rounds,
            "sim_mode": parent_config.get("sim_mode", "kg_driven"),
        }

        try:
            # Create branch session + copy full state up to fork_round
            await self._create_branch(
                branch_id, parent_session_id, label, branch_config,
                fork_round=fork_round,
            )

            # Run in dry_run + lite_ensemble mode (full rounds, no LLM)
            runner = SimulationRunner(dry_run=True)
            await runner.run(session_id=branch_id, config=branch_config)

            # Extract outcome
            outcome = await self._extract_outcome(branch_id, replica_index)

            # Mark completed
            async with get_db() as db:
                await db.execute(
                    "UPDATE simulation_sessions SET status='completed' WHERE id=?",
                    (branch_id,),
                )
                await db.commit()

            return outcome

        except Exception as exc:
            logger.warning(
                "Replica %d failed branch=%s: %s", replica_index, branch_id, exc,
            )
            # Mark failed
            try:
                async with get_db() as db:
                    await db.execute(
                        "UPDATE simulation_sessions SET status='failed' WHERE id=?",
                        (branch_id,),
                    )
                    await db.commit()
            except Exception:
                pass
            raise

    async def _create_branch(
        self,
        branch_id: str,
        parent_session_id: str,
        label: str,
        config: dict[str, Any],
        fork_round: int = 0,
    ) -> None:
        """Insert branch session + copy full Phase A state up to fork_round.

        Copies agent profiles, ALL memories up to fork_round, belief states,
        simulation actions, and emotional states — giving the replica a deep
        initialization grounded in Phase A's LLM-driven interactions.
        """
        async with get_db() as db:
            await db.execute(
                """INSERT INTO simulation_sessions
                   (id, name, sim_mode, scenario_type, status, config_json,
                    agent_count, round_count, llm_provider, llm_model,
                    oasis_db_path, created_at)
                   VALUES (?, ?, ?, ?, 'running', ?,
                           ?, ?, ?, ?, '', datetime('now'))""",
                (
                    branch_id, label,
                    config.get("sim_mode", "kg_driven"),
                    config.get("scenario_type", "kg_driven"),
                    json.dumps(config, ensure_ascii=False),
                    config.get("agent_count", 0),
                    config.get("round_count", 0),
                    config.get("llm_provider", "openrouter"),
                    config.get("llm_model", "deepseek/deepseek-v3.2"),
                ),
            )

            # Copy agent profiles (identical starting conditions)
            await db.execute(
                """INSERT INTO agent_profiles
                   (id, session_id, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness,
                    neuroticism, monthly_income, savings, oasis_persona,
                    oasis_username, created_at)
                   SELECT NULL, ?, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness,
                    neuroticism, monthly_income, savings, oasis_persona,
                    oasis_username, datetime('now')
                   FROM agent_profiles WHERE session_id = ?""",
                (branch_id, parent_session_id),
            )

            # Copy ALL memories up to fork_round (deep Phase A initialization)
            await db.execute(
                """INSERT INTO agent_memories
                   (session_id, agent_id, round_number, memory_text,
                    salience_score, memory_type, created_at)
                   SELECT ?, agent_id, round_number, memory_text,
                          salience_score, memory_type, datetime('now')
                   FROM agent_memories
                   WHERE session_id = ? AND round_number <= ?""",
                (branch_id, parent_session_id, fork_round),
            )

            # Copy belief states up to fork_round
            await db.execute(
                """INSERT INTO belief_states
                   (session_id, agent_id, topic, stance,
                    confidence, evidence_count, round_number)
                   SELECT ?, agent_id, topic, stance,
                          confidence, evidence_count, round_number
                   FROM belief_states
                   WHERE session_id = ? AND round_number <= ?""",
                (branch_id, parent_session_id, fork_round),
            )

            # Copy simulation actions up to fork_round
            await db.execute(
                """INSERT INTO simulation_actions
                   (session_id, agent_id, round_number, action_type,
                    content, platform, created_at)
                   SELECT ?, agent_id, round_number, action_type,
                          content, platform, datetime('now')
                   FROM simulation_actions
                   WHERE session_id = ? AND round_number <= ?""",
                (branch_id, parent_session_id, fork_round),
            )

            # Copy emotional states at fork_round (latest snapshot)
            await db.execute(
                """INSERT INTO emotional_states
                   (session_id, agent_id, round_number,
                    valence, arousal, dominance)
                   SELECT ?, agent_id, round_number,
                          valence, arousal, dominance
                   FROM emotional_states
                   WHERE session_id = ? AND round_number = ?""",
                (branch_id, parent_session_id, fork_round),
            )

            # Copy KG nodes and edges (static structure)
            await db.execute(
                """INSERT OR IGNORE INTO kg_nodes
                   (session_id, title, node_type, description, source, created_at)
                   SELECT ?, title, node_type, description, source, datetime('now')
                   FROM kg_nodes WHERE session_id = ?""",
                (branch_id, parent_session_id),
            )

            # Register as swarm replica
            await db.execute(
                """INSERT OR IGNORE INTO scenario_branches
                   (id, parent_session_id, branch_session_id, scenario_variant,
                    label, fork_round, created_at)
                   VALUES (?, ?, ?, 'swarm_replica', ?, ?, datetime('now'))""",
                (str(uuid.uuid4()), parent_session_id, branch_id, label, fork_round),
            )

            await db.commit()

    async def _extract_outcome(
        self, branch_id: str, replica_index: int,
    ) -> TrajectoryOutcome:
        """Extract outcome summary from a completed replica."""
        async with get_db() as db:
            # Faction count from latest faction snapshot
            faction_row = await (
                await db.execute(
                    """SELECT factions_json FROM faction_snapshots_v2
                       WHERE simulation_id = ?
                       ORDER BY round_number DESC LIMIT 1""",
                    (branch_id,),
                )
            ).fetchone()
            faction_count = 0
            dominant_ratio = 0.0
            if faction_row and faction_row["factions_json"]:
                factions = json.loads(faction_row["factions_json"])
                faction_count = len(factions)
                total_members = sum(
                    len(f.get("member_agent_ids", []))
                    for f in factions
                )
                if total_members > 0 and factions:
                    largest = max(
                        len(f.get("member_agent_ids", []))
                        for f in factions
                    )
                    dominant_ratio = largest / total_members

            # Tipping points
            tp_rows = await (
                await db.execute(
                    "SELECT round_number FROM tipping_points WHERE simulation_id = ?",
                    (branch_id,),
                )
            ).fetchall()
            tp_rounds = tuple(r["round_number"] for r in tp_rows)

            # Final belief states → centroid + polarization
            belief_rows = await (
                await db.execute(
                    """SELECT topic, stance FROM belief_states
                       WHERE session_id = ?
                       AND round_number = (
                           SELECT MAX(round_number) FROM belief_states
                           WHERE session_id = ?
                       )""",
                    (branch_id, branch_id),
                )
            ).fetchall()

            centroid: dict[str, float] = {}
            polarization = 0.0
            if belief_rows:
                by_topic: dict[str, list[float]] = {}
                for row in belief_rows:
                    topic = row["topic"]
                    stance = float(row["stance"])
                    by_topic.setdefault(topic, []).append(stance)
                for topic, stances in by_topic.items():
                    n = len(stances)
                    mean = sum(stances) / n
                    centroid[topic] = round(mean, 4)
                if by_topic:
                    # Polarization = average std deviation across topics
                    import math
                    stds = []
                    for stances in by_topic.values():
                        n = len(stances)
                        mean = sum(stances) / n
                        var = sum((s - mean) ** 2 for s in stances) / max(n - 1, 1)
                        stds.append(math.sqrt(var))
                    polarization = round(sum(stds) / len(stds), 4)

        return TrajectoryOutcome(
            replica_index=replica_index,
            branch_session_id=branch_id,
            faction_count=faction_count,
            tipping_point_rounds=tp_rounds,
            dominant_faction_size_ratio=round(dominant_ratio, 4),
            final_belief_centroid=centroid,
            polarization_score=polarization,
        )

    def _aggregate(
        self,
        session_id: str,
        n_replicas: int,
        outcomes: list[TrajectoryOutcome],
    ) -> ProbabilityCloud:
        """Aggregate trajectory outcomes into a probability cloud."""
        if not outcomes:
            return ProbabilityCloud(
                parent_session_id=session_id,
                n_replicas=n_replicas, n_completed=0,
                trajectories=(), avg_faction_count=0,
                tipping_probability=0, avg_polarization=0,
                belief_cloud={}, outcome_distribution={},
                confidence_intervals={},
            )

        n = len(outcomes)

        # Basic statistics
        avg_factions = sum(o.faction_count for o in outcomes) / n
        tipping_runs = sum(1 for o in outcomes if o.tipping_point_rounds)
        tipping_prob = tipping_runs / n
        avg_polar = sum(o.polarization_score for o in outcomes) / n

        # Belief cloud: per-topic percentiles across all runs
        all_topics: set[str] = set()
        for o in outcomes:
            all_topics.update(o.final_belief_centroid.keys())

        belief_cloud: dict[str, tuple[float, float, float]] = {}
        for topic in sorted(all_topics):
            vals = sorted(
                o.final_belief_centroid.get(topic, 0.5)
                for o in outcomes
            )
            p25 = vals[max(0, len(vals) // 4)]
            median = vals[len(vals) // 2]
            p75 = vals[max(0, 3 * len(vals) // 4)]
            belief_cloud[topic] = (
                round(p25, 4), round(median, 4), round(p75, 4),
            )

        # Outcome clustering: classify each run by dominant pattern
        # High polarization + many factions → "fragmentation"
        # Low polarization + dominant faction → "consensus"
        # Tipping points → "disruption"
        # No tipping + moderate → "stalemate"
        outcome_counts: dict[str, int] = {}
        for o in outcomes:
            label = self._classify_trajectory(o)
            outcome_counts[label] = outcome_counts.get(label, 0) + 1

        outcome_dist = {k: round(v / n, 4) for k, v in outcome_counts.items()}

        # Wilson score confidence intervals
        ci = {}
        for label, count in outcome_counts.items():
            ci[label] = _wilson_ci(count, n)

        return ProbabilityCloud(
            parent_session_id=session_id,
            n_replicas=n_replicas,
            n_completed=n,
            trajectories=tuple(outcomes),
            avg_faction_count=round(avg_factions, 2),
            tipping_probability=round(tipping_prob, 4),
            avg_polarization=round(avg_polar, 4),
            belief_cloud=belief_cloud,
            outcome_distribution=outcome_dist,
            confidence_intervals=ci,
        )

    def _classify_trajectory(self, outcome: TrajectoryOutcome) -> str:
        """Classify a trajectory into a named outcome category.

        Categories are derived from emergence patterns, not hardcoded:
        - **fragmentation**: high polarization + multiple factions
        - **consensus**: low polarization + one dominant faction
        - **disruption**: ≥1 tipping points triggered
        - **stalemate**: no tipping, moderate polarization
        """
        has_tipping = len(outcome.tipping_point_rounds) > 0
        high_polar = outcome.polarization_score > 0.25
        dominant = outcome.dominant_faction_size_ratio > 0.6

        if has_tipping and high_polar:
            return "disruption_polarized"
        if has_tipping and not high_polar:
            return "disruption_converged"
        if not has_tipping and high_polar and not dominant:
            return "fragmentation"
        if not has_tipping and dominant:
            return "consensus"
        return "stalemate"


def _wilson_ci(
    count: int, total: int, z: float = 1.96,
) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a proportion."""
    if total == 0:
        return (0.0, 0.0)
    p = count / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    import math
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    lo = max(0.0, round((centre - spread) / denom, 4))
    hi = min(1.0, round((centre + spread) / denom, 4))
    return (lo, hi)
