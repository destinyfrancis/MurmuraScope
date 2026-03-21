"""EnsembleRunner for MurmuraScope Phase A.

Runs N real simulation trials by:
1. Reading the parent session's MacroState baseline.
2. Perturbing 10 numeric MacroState fields with Gaussian noise.
3. Creating a branch session for each trial via the branch creation logic.
4. Running each branch through SimulationRunner (non-blocking, sequential
   to avoid GPU/API contention).
5. Delegating final analysis to EnsembleAnalyzer.

This is distinct from MonteCarloEngine (statistical MC): EnsembleRunner
spawns real OASIS subprocesses for each trial.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.app.models.ensemble import DistributionBand, EnsembleResult
from backend.app.services.ensemble_analyzer import EnsembleAnalyzer, PERTURBABLE_FIELDS
from backend.app.services.macro_state import MacroState, apply_overrides
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("ensemble_runner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default Gaussian σ for perturbation (as fraction of the field's baseline value)
DEFAULT_PERTURBATION_STD: float = 0.05

# Clamp bounds for each perturbable field to keep values physically sane
_FIELD_CLAMPS: dict[str, tuple[float, float]] = {
    "hibor_1m":           (0.001,  0.20),
    "unemployment_rate":  (0.005,  0.25),
    "ccl_index":          (40.0,   350.0),
    "hsi_level":          (5_000,  80_000),
    "consumer_confidence":(15.0,   130.0),
    "gdp_growth":         (-0.15,  0.20),
    "net_migration":      (-250_000, 100_000),
    "fed_rate":           (0.0,    0.15),
    "china_gdp_growth":   (-0.10,  0.15),
    "taiwan_strait_risk": (0.0,    1.0),
}

# Maximum parallel trials to avoid spawning too many subprocesses simultaneously
_MAX_CONCURRENT_TRIALS: int = 3


# ---------------------------------------------------------------------------
# Frozen result for a single trial
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrialRecord:
    """Record of a single ensemble trial.

    Attributes:
        trial_index: Zero-based trial number.
        branch_session_id: UUID of the branch session created for this trial.
        perturbation: Dict of field → perturbed value applied.
        status: 'completed', 'failed', or 'skipped'.
        error_message: Non-empty if status is 'failed'.
    """

    trial_index: int
    branch_session_id: str
    perturbation: dict[str, float]
    status: str
    error_message: str = ""


# ---------------------------------------------------------------------------
# EnsembleRunner
# ---------------------------------------------------------------------------


class EnsembleRunner:
    """Orchestrates a real Monte Carlo ensemble by spawning trial simulations."""

    def __init__(self) -> None:
        self._analyzer = EnsembleAnalyzer()

    async def run_ensemble(
        self,
        session_id: str,
        n_trials: int = 20,
        perturbation_std: float = DEFAULT_PERTURBATION_STD,
        dry_run: bool = False,
    ) -> EnsembleResult:
        """Run N real simulation trials with perturbed MacroState.

        Algorithm:
        1. Load parent session config + MacroState baseline.
        2. For each trial: perturb numeric MacroState fields → create branch
           session with overrides in config_json → run simulation.
        3. Collect trial session IDs.
        4. Delegate to EnsembleAnalyzer.compute_percentiles().

        Args:
            session_id: Parent simulation session UUID.
            n_trials: Number of trials to run (clamped to [1, 200]).
            perturbation_std: Gaussian σ as fraction of each field's value.
            dry_run: If True, use rule-based decisions (skip LLM) for
                cheaper multi-trajectory exploration.

        Returns:
            EnsembleResult with DistributionBands for each perturbable field.

        Raises:
            ValueError: If the parent session is not found.
        """
        # Cap at 500.  For ±5% precision on binary outcomes at 95% CI,
        # theory requires ~384 trials (σ/√n formula: (1.96×0.5/0.05)²).
        # 500 provides ±4.4% — adequate for exploratory ensemble analysis.
        # In dry_run mode this is cheap (no LLM); in full mode the batched
        # _MAX_CONCURRENT_TRIALS=3 keeps resource usage bounded.
        n_trials = max(1, min(n_trials, 500))
        perturbation_std = max(0.001, min(perturbation_std, 0.5))

        logger.info(
            "EnsembleRunner.run_ensemble session=%s n_trials=%d std=%.3f dry_run=%s",
            session_id, n_trials, perturbation_std, dry_run,
        )
        self._dry_run = dry_run

        # Load parent session data
        parent_config, parent_macro = await self._load_parent_session(session_id)

        # Generate perturbed MacroStates
        rng = np.random.default_rng(seed=None)
        perturbations: list[dict[str, float]] = [
            _perturb_macro_fields(parent_macro, rng, perturbation_std)
            for _ in range(n_trials)
        ]

        # Create branch sessions and run trials
        trial_records: list[TrialRecord] = []
        trial_batch: list[tuple[int, dict[str, float]]] = list(enumerate(perturbations))

        # Run in batches of _MAX_CONCURRENT_TRIALS
        import asyncio
        for batch_start in range(0, len(trial_batch), _MAX_CONCURRENT_TRIALS):
            batch = trial_batch[batch_start: batch_start + _MAX_CONCURRENT_TRIALS]
            tasks = [
                self._run_single_trial(
                    parent_session_id=session_id,
                    parent_config=parent_config,
                    trial_index=idx,
                    perturbation=pert,
                )
                for idx, pert in batch
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in batch_results:
                if isinstance(result, TrialRecord):
                    trial_records.append(result)
                else:
                    # Exception from gather — log and continue
                    logger.exception("Trial gather returned exception: %s", result)

        # Persist trial metadata
        await self._persist_trial_metadata(session_id, trial_records)

        completed_ids = [
            r.branch_session_id
            for r in trial_records
            if r.status == "completed"
        ]
        logger.info(
            "Ensemble run completed: %d/%d trials succeeded session=%s",
            len(completed_ids), n_trials, session_id,
        )

        # Compute percentiles across completed trials
        return await self._analyzer.compute_percentiles(
            session_id=session_id,
            trial_session_ids=completed_ids,
        )

    async def get_trial_metadata(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """Return metadata for all trials of a given parent session.

        Args:
            session_id: Parent session UUID.

        Returns:
            List of dicts with trial_index, branch_session_id, status,
            perturbation (dict), error_message, created_at.
        """
        try:
            async with get_db() as db:
                await _ensure_trial_table(db)
                cursor = await db.execute(
                    """
                    SELECT trial_index, branch_session_id, perturbation_json,
                           status, error_message, created_at
                    FROM ensemble_trials
                    WHERE parent_session_id = ?
                    ORDER BY trial_index
                    """,
                    (session_id,),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.exception("get_trial_metadata failed session=%s", session_id)
            return []

        results: list[dict[str, Any]] = []
        for row in rows:
            try:
                pert = json.loads(row[2] if isinstance(row, (list, tuple)) else row["perturbation_json"])
            except (json.JSONDecodeError, TypeError):
                pert = {}
            results.append({
                "trial_index": row[0] if isinstance(row, (list, tuple)) else row["trial_index"],
                "branch_session_id": row[1] if isinstance(row, (list, tuple)) else row["branch_session_id"],
                "perturbation": pert,
                "status": row[3] if isinstance(row, (list, tuple)) else row["status"],
                "error_message": row[4] if isinstance(row, (list, tuple)) else row["error_message"],
                "created_at": row[5] if isinstance(row, (list, tuple)) else row["created_at"],
            })
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_parent_session(
        self, session_id: str
    ) -> tuple[dict[str, Any], MacroState]:
        """Load parent session config and construct its MacroState.

        Args:
            session_id: Parent session UUID.

        Returns:
            (config dict, MacroState baseline)

        Raises:
            ValueError: If session not found.
        """
        from backend.app.services.macro_controller import MacroController  # noqa: PLC0415

        try:
            async with get_db() as db:
                row = await (
                    await db.execute(
                        "SELECT config_json, scenario_type FROM simulation_sessions WHERE id = ?",
                        (session_id,),
                    )
                ).fetchone()
        except Exception as exc:
            raise ValueError(f"Session {session_id} not found (DB error: {exc})") from exc

        if row is None:
            raise ValueError(f"Session {session_id} not found")

        raw_cfg = row[0] if isinstance(row, (list, tuple)) else row["config_json"]
        scenario_type = row[1] if isinstance(row, (list, tuple)) else row["scenario_type"]
        config: dict[str, Any] = json.loads(raw_cfg) if raw_cfg else {}

        mc = MacroController()
        if scenario_type:
            macro_state = await mc.get_baseline_for_scenario(scenario_type)
        else:
            macro_state = await mc.get_baseline()

        return config, macro_state

    async def _run_single_trial(
        self,
        parent_session_id: str,
        parent_config: dict[str, Any],
        trial_index: int,
        perturbation: dict[str, float],
    ) -> TrialRecord:
        """Create a branch session and run it with perturbed macro values.

        The perturbation is stored in config_json under 'macro_overrides'
        so EnsembleAnalyzer can read it as a fallback when macro_snapshots
        are unavailable.

        Args:
            parent_session_id: Parent session UUID.
            parent_config: Parent session config dict.
            trial_index: Zero-based trial number.
            perturbation: Dict mapping field name → perturbed numeric value.

        Returns:
            TrialRecord with status 'completed' or 'failed'.
        """
        branch_id = str(uuid.uuid4())
        label = f"Ensemble Trial {trial_index + 1} (session {parent_session_id[:8]})"

        # Build branch config with macro overrides embedded
        branch_config: dict[str, Any] = {
            **parent_config,
            "parent_session_id": parent_session_id,
            "ensemble_trial_index": trial_index,
            "macro_overrides": perturbation,
        }

        try:
            await self._create_branch_session(
                branch_id=branch_id,
                parent_session_id=parent_session_id,
                label=label,
                config=branch_config,
                original_config=parent_config,
            )

            # Run the simulation for this branch
            await self._execute_trial_simulation(branch_id, branch_config)

            logger.info(
                "Trial %d completed branch=%s", trial_index, branch_id
            )
            return TrialRecord(
                trial_index=trial_index,
                branch_session_id=branch_id,
                perturbation=perturbation,
                status="completed",
            )

        except Exception as exc:
            error_msg = str(exc)
            logger.warning(
                "Trial %d failed branch=%s: %s",
                trial_index, branch_id, error_msg,
            )
            # Mark branch as failed in DB
            try:
                async with get_db() as db:
                    await db.execute(
                        "UPDATE simulation_sessions SET status='failed', error_message=? WHERE id=?",
                        (error_msg[:500], branch_id),
                    )
                    await db.commit()
            except Exception:
                pass

            return TrialRecord(
                trial_index=trial_index,
                branch_session_id=branch_id,
                perturbation=perturbation,
                status="failed",
                error_message=error_msg[:500],
            )

    async def _create_branch_session(
        self,
        branch_id: str,
        parent_session_id: str,
        label: str,
        config: dict[str, Any],
        original_config: dict[str, Any],
    ) -> None:
        """Insert a branch simulation_session and copy agent profiles.

        Args:
            branch_id: New branch session UUID.
            parent_session_id: Parent session UUID.
            label: Human-readable label.
            config: Branch config dict (includes macro_overrides).
            original_config: Original parent config (for metadata).
        """
        async with get_db() as db:
            # Fetch parent scenario_type
            row = await (
                await db.execute(
                    "SELECT scenario_type FROM simulation_sessions WHERE id = ?",
                    (parent_session_id,),
                )
            ).fetchone()
            scenario_type = (
                (row[0] if isinstance(row, (list, tuple)) else row["scenario_type"])
                if row else "property"
            )

            await db.execute(
                """
                INSERT INTO simulation_sessions
                   (id, name, sim_mode, scenario_type, status, config_json,
                    agent_count, round_count, llm_provider, llm_model,
                    oasis_db_path, created_at)
                VALUES (?, ?, 'parallel', ?, 'created', ?,
                        ?, ?, ?, ?,
                        '', datetime('now'))
                """,
                (
                    branch_id,
                    label,
                    scenario_type,
                    json.dumps(config, ensure_ascii=False),
                    original_config.get("agent_count", 0),
                    original_config.get("round_count", 0),
                    original_config.get("llm_provider", "openrouter"),
                    original_config.get("llm_model", "deepseek/deepseek-v3.2"),
                ),
            )

            # Copy agent profiles from parent (includes stakeholder/activity columns)
            await db.execute(
                """
                INSERT INTO agent_profiles
                   (id, session_id, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness,
                    neuroticism, monthly_income, savings, oasis_persona,
                    oasis_username, created_at,
                    activity_level, influence_weight, is_stakeholder)
                SELECT
                    NULL, ?, agent_type, age, sex, district, occupation,
                    income_bracket, education_level, marital_status, housing_type,
                    openness, conscientiousness, extraversion, agreeableness,
                    neuroticism, monthly_income, savings, oasis_persona,
                    oasis_username, datetime('now'),
                    activity_level, influence_weight, is_stakeholder
                FROM agent_profiles WHERE session_id = ?
                """,
                (branch_id, parent_session_id),
            )

            # Copy belief states
            try:
                await db.execute(
                    """INSERT INTO belief_states
                       (session_id, agent_id, topic, stance,
                        confidence, evidence_count, round_number)
                       SELECT ?, agent_id, topic, stance,
                              confidence, evidence_count, round_number
                       FROM belief_states WHERE session_id = ?""",
                    (branch_id, parent_session_id),
                )
            except Exception:
                logger.debug("belief_states copy skipped (table may not exist)")

            # Copy emotional states (latest snapshot only)
            try:
                await db.execute(
                    """INSERT INTO emotional_states
                       (session_id, agent_id, round_number,
                        valence, arousal, dominance)
                       SELECT ?, agent_id, round_number,
                              valence, arousal, dominance
                       FROM emotional_states
                       WHERE session_id = ? AND round_number = (
                           SELECT MAX(round_number) FROM emotional_states
                           WHERE session_id = ?
                       )""",
                    (branch_id, parent_session_id, parent_session_id),
                )
            except Exception:
                logger.debug("emotional_states copy skipped (table may not exist)")

            # Copy agent relationships
            try:
                await db.execute(
                    """INSERT OR IGNORE INTO agent_relationships
                       (session_id, agent_a_id, agent_b_id, relationship_type,
                        influence_weight, trust_score, created_at)
                       SELECT ?, agent_a_id, agent_b_id, relationship_type,
                              influence_weight, trust_score, datetime('now')
                       FROM agent_relationships WHERE session_id = ?""",
                    (branch_id, parent_session_id),
                )
            except Exception:
                logger.debug("agent_relationships copy skipped (table may not exist)")

            # Copy KG edges
            try:
                await db.execute(
                    """INSERT OR IGNORE INTO kg_edges
                       (session_id, source_id, target_id, relation_type,
                        description, weight, round_number, created_at)
                       SELECT ?, source_id, target_id, relation_type,
                              description, weight, round_number, datetime('now')
                       FROM kg_edges WHERE session_id = ?""",
                    (branch_id, parent_session_id),
                )
            except Exception:
                logger.debug("kg_edges copy skipped (table may not exist)")

            # Copy cognitive dissonance
            try:
                await db.execute(
                    """INSERT OR IGNORE INTO cognitive_dissonance
                       (session_id, agent_id, round_number, dissonance_score,
                        conflicting_pairs_json, action_belief_gap,
                        resolution_strategy, created_at)
                       SELECT ?, agent_id, round_number, dissonance_score,
                              conflicting_pairs_json, action_belief_gap,
                              resolution_strategy, datetime('now')
                       FROM cognitive_dissonance WHERE session_id = ?""",
                    (branch_id, parent_session_id),
                )
            except Exception:
                logger.debug("cognitive_dissonance copy skipped (table may not exist)")

            # Copy agent memories
            try:
                await db.execute(
                    """INSERT INTO agent_memories
                       (session_id, agent_id, round_number, memory_text,
                        salience_score, memory_type, created_at)
                       SELECT ?, agent_id, round_number, memory_text,
                              salience_score, memory_type, datetime('now')
                       FROM agent_memories WHERE session_id = ?""",
                    (branch_id, parent_session_id),
                )
            except Exception:
                logger.debug("agent_memories copy skipped (table may not exist)")

            # Copy simulation actions
            try:
                await db.execute(
                    """INSERT INTO simulation_actions
                       (session_id, agent_id, round_number, action_type,
                        content, platform, created_at)
                       SELECT ?, agent_id, round_number, action_type,
                              content, platform, datetime('now')
                       FROM simulation_actions WHERE session_id = ?""",
                    (branch_id, parent_session_id),
                )
            except Exception:
                logger.debug("simulation_actions copy skipped (table may not exist)")

            # Register in scenario_branches
            branch_record_id = str(uuid.uuid4())
            try:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO scenario_branches
                       (id, parent_session_id, branch_session_id, scenario_variant,
                        label, fork_round, created_at)
                    VALUES (?, ?, ?, 'ensemble', ?, NULL, datetime('now'))
                    """,
                    (branch_record_id, parent_session_id, branch_id, label),
                )
            except Exception:
                # Older schema without fork_round column
                await db.execute(
                    """
                    INSERT OR IGNORE INTO scenario_branches
                       (id, parent_session_id, branch_session_id, scenario_variant,
                        label, created_at)
                    VALUES (?, ?, ?, 'ensemble', ?, datetime('now'))
                    """,
                    (branch_record_id, parent_session_id, branch_id, label),
                )

            await db.commit()

    async def _execute_trial_simulation(
        self,
        branch_id: str,
        config: dict[str, Any],
    ) -> None:
        """Run the simulation subprocess for a branch session.

        Applies macro_overrides from config to prime the MacroController
        before handing off to SimulationRunner.

        Args:
            branch_id: Branch session UUID.
            config: Branch config dict (includes 'macro_overrides').
        """
        from backend.app.services.simulation_runner import SimulationRunner  # noqa: PLC0415
        from backend.app.services.macro_controller import MacroController  # noqa: PLC0415
        from backend.app.services.macro_history import MacroHistoryService  # noqa: PLC0415

        macro_overrides = config.get("macro_overrides", {})

        # Materialise the perturbed MacroState and persist as round-0 snapshot
        if macro_overrides:
            mc = MacroController()
            scenario_type = config.get("scenario_type", "property")
            base_state = await mc.get_baseline_for_scenario(scenario_type)

            # Only override fields that exist in MacroState
            valid_overrides = {
                k: v for k, v in macro_overrides.items()
                if hasattr(base_state, k)
            }
            perturbed_state = apply_overrides(base_state, valid_overrides)

            history_svc = MacroHistoryService()
            await history_svc.save_snapshot(branch_id, 0, perturbed_state)

        # Update session status to running
        async with get_db() as db:
            await db.execute(
                "UPDATE simulation_sessions SET status='running', started_at=datetime('now') WHERE id=?",
                (branch_id,),
            )
            await db.commit()

        try:
            runner = SimulationRunner(dry_run=self._dry_run)
            await runner.run(session_id=branch_id, config=config)

            async with get_db() as db:
                await db.execute(
                    "UPDATE simulation_sessions SET status='completed', completed_at=datetime('now') WHERE id=?",
                    (branch_id,),
                )
                await db.commit()
        except Exception:
            async with get_db() as db:
                await db.execute(
                    "UPDATE simulation_sessions SET status='failed', completed_at=datetime('now') WHERE id=?",
                    (branch_id,),
                )
                await db.commit()
            raise

    async def _persist_trial_metadata(
        self,
        parent_session_id: str,
        records: list[TrialRecord],
    ) -> None:
        """Save trial metadata to ensemble_trials table for introspection.

        Args:
            parent_session_id: Parent session UUID.
            records: TrialRecord list from the run.
        """
        if not records:
            return
        try:
            async with get_db() as db:
                await _ensure_trial_table(db)
                rows = [
                    (
                        parent_session_id,
                        r.trial_index,
                        r.branch_session_id,
                        json.dumps(r.perturbation, ensure_ascii=False),
                        r.status,
                        r.error_message,
                    )
                    for r in records
                ]
                await db.executemany(
                    """
                    INSERT OR REPLACE INTO ensemble_trials
                        (parent_session_id, trial_index, branch_session_id,
                         perturbation_json, status, error_message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    rows,
                )
                await db.commit()
        except Exception:
            logger.exception(
                "_persist_trial_metadata failed session=%s", parent_session_id
            )


# ---------------------------------------------------------------------------
# Private pure functions
# ---------------------------------------------------------------------------


def _perturb_macro_fields(
    state: MacroState,
    rng: np.random.Generator,
    sigma_fraction: float,
) -> dict[str, float]:
    """Apply Gaussian noise to each perturbable MacroState field.

    Noise is proportional to the field's absolute value: σ = sigma_fraction * |value|.
    Each perturbed value is clamped to its allowed range.

    Args:
        state: Base MacroState (frozen dataclass).
        rng: NumPy random Generator (for reproducibility if seeded).
        sigma_fraction: Standard deviation as fraction of field value.

    Returns:
        Dict mapping field name → perturbed float value.
    """
    state_dict = dataclasses.asdict(state)
    result: dict[str, float] = {}

    for field in PERTURBABLE_FIELDS:
        base_val = state_dict.get(field)
        if base_val is None:
            continue
        base_float = float(base_val)

        # σ proportional to |value|, minimum 1e-6 to handle zero-valued fields
        sigma = sigma_fraction * abs(base_float) if abs(base_float) > 1e-9 else sigma_fraction * 1e-4
        noisy = base_float + rng.normal(0.0, sigma)

        lo, hi = _FIELD_CLAMPS.get(field, (-1e12, 1e12))
        result[field] = float(np.clip(noisy, lo, hi))

    return result


async def _ensure_trial_table(db: Any) -> None:
    """Create ensemble_trials table if not present.

    Args:
        db: aiosqlite connection.
    """
    await db.execute("""
        CREATE TABLE IF NOT EXISTS ensemble_trials (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_session_id  TEXT NOT NULL,
            trial_index        INTEGER NOT NULL,
            branch_session_id  TEXT NOT NULL,
            perturbation_json  TEXT NOT NULL DEFAULT '{}',
            status             TEXT NOT NULL DEFAULT 'created',
            error_message      TEXT DEFAULT '',
            created_at         TEXT DEFAULT (datetime('now')),
            UNIQUE(parent_session_id, trial_index)
        )
    """)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ensemble_trials_parent ON ensemble_trials(parent_session_id)"
    )
