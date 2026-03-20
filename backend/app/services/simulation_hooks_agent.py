"""Agent-level simulation hooks: memories, trust, decisions, consumption.

Mixin class extracted from SimulationRunner to keep file sizes manageable.
All methods access SimulationRunner state via ``self`` (cooperative MRO).
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.app.services.emotional_engine import EmotionalEngine
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("simulation_hooks.agent")


def _clamp_float(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


class AgentHooksMixin:
    """Per-round hooks for individual agent processing."""

    async def _process_attention_allocation(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Allocate attention budgets for all agents based on posts this round."""
        try:
            from backend.app.services.attention_economy import batch_allocate_attention  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415

            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT id FROM agent_profiles WHERE session_id = ?",
                    (session_id,),
                )
                rows = await cursor.fetchall()

                cursor2 = await db.execute(
                    "SELECT content FROM simulation_actions WHERE session_id = ? AND round_number = ?",
                    (session_id, round_num),
                )
                post_rows = await cursor2.fetchall()

            agent_ids = [r[0] for r in rows]
            posts = [{"content": r[0] or ""} for r in post_rows]

            budgets = await batch_allocate_attention(session_id, round_num, agent_ids, posts)
            logger.debug(
                "_process_attention_allocation session=%s round=%d agents=%d",
                session_id, round_num, len(budgets),
            )
        except Exception:
            logger.exception(
                "_process_attention_allocation failed session=%s round=%d",
                session_id, round_num,
            )

    async def _apply_decision_side_effects(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Apply employment and relocation side effects from decisions this round."""
        try:
            if self._kg_mode.get(session_id):
                return  # kg_driven: HK district/employment side effects not applicable
            from backend.app.utils.db import get_db  # noqa: PLC0415

            async with get_db() as db:
                cursor = await db.execute(
                    """
                    SELECT agent_id, action FROM agent_decisions
                    WHERE session_id = ? AND round_number = ?
                      AND decision_type = 'employment_change'
                      AND action IN ('quit', 'lie_flat')
                    """,
                    (session_id, round_num),
                )
                quit_rows = await cursor.fetchall()

                cursor = await db.execute(
                    """
                    SELECT agent_id, action FROM agent_decisions
                    WHERE session_id = ? AND round_number = ?
                      AND decision_type = 'relocate'
                      AND action != 'stay'
                    """,
                    (session_id, round_num),
                )
                relocate_rows = await cursor.fetchall()

            _ACTION_TO_DISTRICT: dict[str, str] = {
                "relocate_nt": "沙田",
                "relocate_kln": "深水埗",
                "relocate_hk_island": "東區",
                "relocate_gba": "北區",
            }

            quit_updates: list[tuple[int, str]] = []
            for row in quit_rows:
                agent_id = row[0]
                quit_updates.append((agent_id, session_id))

            relocate_updates: list[tuple[str, int, str]] = []
            for row in relocate_rows:
                agent_id, action = row[0], row[1]
                new_district = _ACTION_TO_DISTRICT.get(action)
                if new_district:
                    relocate_updates.append((new_district, agent_id, session_id))

            if not quit_updates and not relocate_updates:
                return

            async with get_db() as db:
                if quit_updates:
                    await db.executemany(
                        "UPDATE agent_profiles SET monthly_income = 0 WHERE id = ? AND session_id = ?",
                        quit_updates,
                    )
                if relocate_updates:
                    await db.executemany(
                        "UPDATE agent_profiles SET district = ? WHERE id = ? AND session_id = ?",
                        relocate_updates,
                    )
                await db.commit()

            logger.debug(
                "_apply_decision_side_effects session=%s round=%d quits=%d relocates=%d",
                session_id, round_num, len(quit_updates), len(relocate_updates),
            )

        except Exception:
            logger.exception(
                "_apply_decision_side_effects failed session=%s round=%d",
                session_id, round_num,
            )

    async def _process_round_memories(
        self,
        session_id: str,
        round_number: int,
        username_to_agent_id: dict[str, int] | None = None,
    ) -> None:
        """Summarise buffered posts into agent memories for a completed round."""
        posts_by_agent = dict(self._posts_buffer.get(session_id, {}).get(round_number, {}))
        if not posts_by_agent:
            return

        if username_to_agent_id is None:
            try:
                import aiosqlite as _aiosqlite  # noqa: PLC0415
                from backend.app.utils.db import get_db  # noqa: PLC0415
                async with get_db() as db:
                    db.row_factory = _aiosqlite.Row
                    cursor = await db.execute(
                        "SELECT id, oasis_username FROM agent_profiles WHERE session_id = ?",
                        (session_id,),
                    )
                    rows = await cursor.fetchall()
                    username_to_agent_id = {
                        r["oasis_username"]: r["id"] for r in rows if r["oasis_username"]
                    }
            except Exception:
                logger.warning("Failed to build username mapping for session=%s", session_id)
                username_to_agent_id = {}

        try:
            from backend.app.services.agent_memory import AgentMemoryService  # noqa: PLC0415
            if self._memory_service is None:
                if self._vector_store is None:
                    try:
                        from backend.app.services.vector_store import VectorStore  # noqa: PLC0415
                        self._vector_store = VectorStore()
                    except Exception:
                        logger.warning("VectorStore init failed, using SQL-only memory")
                self._memory_service = AgentMemoryService(
                    vector_store=self._vector_store,
                )
            stored = await self._memory_service.store_round_memories(
                session_id=session_id,
                round_number=round_number,
                posts_by_agent=posts_by_agent,
                username_to_agent_id=username_to_agent_id,
            )
            await self._memory_service.decay_memories(session_id, round_number)
            logger.debug(
                "round %d memories stored=%d session=%s", round_number, stored, session_id
            )

            # Memory summarization: every summarize_interval rounds (config-driven)
            if round_number > 0 and round_number % self._preset.hook_config.summarize_interval == 0:
                try:
                    from backend.app.utils.db import get_db as _get_db  # noqa: PLC0415
                    async with _get_db() as _db:
                        cursor = await _db.execute(
                            "SELECT DISTINCT agent_id FROM agent_memories WHERE session_id = ?",
                            (session_id,),
                        )
                        agent_rows = await cursor.fetchall()
                    agent_ids = [r[0] for r in agent_rows if r[0] is not None]

                    if agent_ids:
                        semaphore = asyncio.Semaphore(self._preset.hook_config.llm_concurrency)
                        async def _limited_summarize(aid: int) -> bool:
                            async with semaphore:
                                return await self._memory_service.summarize_old_memories(
                                    session_id, aid, round_number
                                )
                        summarize_results = await asyncio.gather(
                            *[_limited_summarize(aid) for aid in agent_ids],
                            return_exceptions=True,
                        )
                        summarized_count = sum(
                            1 for r in summarize_results if r is True
                        )
                        logger.info(
                            "Memory summarization round=%d: %d/%d agents compressed session=%s",
                            round_number, summarized_count, len(agent_ids), session_id,
                        )
                except Exception:
                    logger.exception(
                        "Memory summarization failed session=%s round=%d",
                        session_id, round_number,
                    )
        except Exception:
            logger.exception(
                "_process_round_memories failed session=%s round=%d", session_id, round_number
            )

    async def _process_round_trust(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Update dynamic trust scores using sparse active-agent filtering.

        Phase 4A optimisation: only process interaction pairs where at least
        one agent was active (posted) this round.  This reduces O(N²) trust
        pairs to O(N_active × avg_followers), which is typically 10-50x fewer
        pairs for large simulations.
        """
        try:
            from backend.app.services.trust_dynamics import TrustDynamicsService  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415

            if self._trust_service is None:
                self._trust_service = TrustDynamicsService()

            # Collect active agent usernames from simulation_actions this round
            active_usernames: set[str] = set()
            try:
                async with get_db() as db:
                    cursor = await db.execute(
                        """
                        SELECT DISTINCT oasis_username
                        FROM simulation_actions
                        WHERE session_id = ? AND round_number = ?
                          AND oasis_username IS NOT NULL AND oasis_username != ''
                        """,
                        (session_id, round_number),
                    )
                    rows = await cursor.fetchall()
                    active_usernames = {r[0] for r in rows}
            except Exception:
                logger.warning(
                    "_process_round_trust: could not load active agents "
                    "session=%s round=%d — falling back to full update",
                    session_id, round_number,
                )

            # Pass active_usernames hint to trust service (sparse update)
            updates = await self._trust_service.update_trust_from_round(
                session_id,
                round_number,
                active_usernames=active_usernames if active_usernames else None,
            )
            await self._trust_service.decay_trust(session_id)

            logger.debug(
                "_process_round_trust round=%d updates=%d active_agents=%d session=%s",
                round_number, len(updates), len(active_usernames), session_id,
            )
        except Exception:
            logger.exception(
                "_process_round_trust failed session=%s round=%d", session_id, round_number
            )

    async def _process_round_decisions(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Run the Agent Decision Engine for a completed simulation round."""
        try:
            if self._kg_mode.get(session_id):
                return  # kg_driven: uses UniversalDecisionEngine via Tier 1 deliberation
            from backend.app.services.decision_engine import DecisionEngine  # noqa: PLC0415
            if self._decision_engine is None:
                self._decision_engine = DecisionEngine()

            rows = list(self._round_profiles.get(session_id, []))

            if not rows:
                return

            from backend.app.services.agent_factory import AgentProfile  # noqa: PLC0415
            profiles_by_id: dict[int, AgentProfile] = {}
            for r in rows:
                profiles_by_id[r["id"]] = AgentProfile(
                    id=r["id"],
                    agent_type=r["agent_type"],
                    age=r["age"],
                    sex=r["sex"],
                    district=r["district"],
                    occupation=r["occupation"],
                    income_bracket=r["income_bracket"],
                    education_level=r["education_level"],
                    marital_status=r["marital_status"],
                    housing_type=r["housing_type"],
                    openness=r["openness"],
                    conscientiousness=r["conscientiousness"],
                    extraversion=r["extraversion"],
                    agreeableness=r["agreeableness"],
                    neuroticism=r["neuroticism"],
                    monthly_income=r["monthly_income"] or 0,
                    savings=r["savings"] or 0,
                )

            macro_state = self._macro_state.get(session_id)
            if macro_state is None:
                from backend.app.services.macro_controller import MacroController  # noqa: PLC0415
                mc = MacroController()
                macro_state = await mc.get_baseline()

            summary = await self._decision_engine.process_round_decisions(
                session_id=session_id,
                round_number=round_number,
                profiles_by_id=profiles_by_id,
                macro_state=macro_state,
            )

            # Apply macro adjustments derived from agent decisions
            macro_adjustments = summary.get("macro_adjustments", {})
            if macro_adjustments and session_id in self._macro_state:
                import dataclasses  # noqa: PLC0415
                async with self._macro_locks[session_id]:
                    current = self._macro_state[session_id]
                    updates: dict[str, Any] = {}
                    for field, delta in macro_adjustments.items():
                        current_val = getattr(current, field, None)
                        if current_val is not None and isinstance(current_val, (int, float)):
                            updates[field] = type(current_val)(current_val + delta)
                    if updates:
                        new_state = self._clamp_macro_state(dataclasses.replace(current, **updates))
                        self._macro_state[session_id] = new_state
                        await self._persist_macro_state(session_id, round_number, new_state)
                        logger.info(
                            "Applied macro adjustments session=%s round=%d fields=%s",
                            session_id,
                            round_number,
                            list(updates.keys()),
                        )
        except Exception:
            logger.exception(
                "_process_round_decisions failed session=%s round=%d",
                session_id,
                round_number,
            )

    # ------------------------------------------------------------------
    # Phase 3: Emotional state + Belief updates
    # ------------------------------------------------------------------

    async def _process_emotional_state(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Update VAD emotional states for all agents this round."""
        try:
            import aiosqlite as _aiosqlite  # noqa: PLC0415

            engine = EmotionalEngine()

            async with get_db() as db:
                db.row_factory = _aiosqlite.Row

                # Load previous emotional states (round_num - 1) or empty
                prev_round = max(0, round_num - 1)
                prev_states = await engine.load_states(session_id, prev_round, db)

            profile_rows = list(self._round_profiles.get(session_id, []))

            if not profile_rows:
                return

            from backend.app.services.agent_factory import AgentProfile  # noqa: PLC0415
            profiles: dict[int, AgentProfile] = {}
            for r in profile_rows:
                try:
                    profiles[r["id"]] = AgentProfile(
                        id=r["id"],
                        agent_type=r["agent_type"],
                        age=r["age"],
                        sex=r["sex"],
                        district=r["district"],
                        occupation=r["occupation"],
                        income_bracket=r["income_bracket"],
                        education_level=r["education_level"],
                        marital_status=r["marital_status"],
                        housing_type=r["housing_type"],
                        openness=r["openness"],
                        conscientiousness=r["conscientiousness"],
                        extraversion=r["extraversion"],
                        agreeableness=r["agreeableness"],
                        neuroticism=r["neuroticism"],
                        monthly_income=r["monthly_income"] or 0,
                        savings=r["savings"] or 0,
                    )
                except Exception:
                    pass

            # Initialize missing states (round 0 or new agents)
            for agent_id, profile in profiles.items():
                if agent_id not in prev_states:
                    prev_states[agent_id] = engine.initialize_state(agent_id, session_id, profile)

            # Compute feed sentiment per agent from this round's actions
            feed_data: dict[int, dict[str, float]] = {}
            from backend.app.utils.db import get_db as _get_db  # noqa: PLC0415
            async with _get_db() as db2:
                cursor2 = await db2.execute(
                    """SELECT agent_id,
                        AVG(CASE sentiment WHEN 'positive' THEN 1.0 WHEN 'negative' THEN -1.0 ELSE 0.0 END) AS sent_avg,
                        COUNT(*) AS post_count
                    FROM simulation_actions
                    WHERE session_id = ? AND round_number = ?
                    GROUP BY agent_id""",
                    (session_id, round_num),
                )
                sentiment_rows = await cursor2.fetchall()
                for row in sentiment_rows:
                    aid = int(row[0])
                    feed_data[aid] = {
                        "sentiment_avg": float(row[1] or 0.0),
                        "controversy": 0.2,  # default controversy exposure
                        "personal_valence": 0.0,
                    }

            # Macro shock valence from current macro state
            macro_state = self._macro_state.get(session_id)
            macro_valence = 0.0
            if macro_state is not None:
                # Derive valence signal from macro indicators
                unemployment = float(getattr(macro_state, "unemployment_rate", 4.0))
                gdp = float(getattr(macro_state, "gdp_growth", 2.0))
                macro_valence = _clamp_float((gdp - 2.0) * 0.1 - (unemployment - 4.0) * 0.08)

            # Load pending arousal deltas from previous dissonance resolution
            pending_deltas: dict[int, float] = getattr(self, "_pending_arousal_deltas", {}).get(
                session_id, {}
            )

            async with _get_db() as db3:
                await engine.batch_update(
                    session_id=session_id,
                    round_number=round_num,
                    agent_states=prev_states,
                    profiles=profiles,
                    feed_data=feed_data,
                    macro_valence=macro_valence,
                    pending_deltas=pending_deltas,
                    db=db3,
                )

            # Clear consumed pending deltas
            if hasattr(self, "_pending_arousal_deltas") and session_id in self._pending_arousal_deltas:
                self._pending_arousal_deltas[session_id] = {}

            logger.debug(
                "_process_emotional_state session=%s round=%d agents=%d",
                session_id, round_num, len(prev_states),
            )
        except Exception:
            logger.exception(
                "_process_emotional_state failed session=%s round=%d",
                session_id, round_num,
            )

    async def _process_belief_update(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Update agent beliefs from feed and detect cognitive dissonance."""
        try:
            from backend.app.services.belief_system import BeliefSystem  # noqa: PLC0415
            from backend.app.services.cognitive_dissonance import DissonanceDetector  # noqa: PLC0415
            import aiosqlite as _aiosqlite  # noqa: PLC0415

            belief_sys = BeliefSystem()
            dissonance_det = DissonanceDetector()

            profile_rows = list(self._round_profiles.get(session_id, []))

            if not profile_rows:
                return

            from backend.app.services.agent_factory import AgentProfile  # noqa: PLC0415
            profiles: dict[int, AgentProfile] = {}
            for r in profile_rows:
                try:
                    profiles[r["id"]] = AgentProfile(
                        id=r["id"],
                        agent_type=r["agent_type"],
                        age=r["age"],
                        sex=r["sex"],
                        district=r["district"],
                        occupation=r["occupation"],
                        income_bracket=r["income_bracket"],
                        education_level=r["education_level"],
                        marital_status=r["marital_status"],
                        housing_type=r["housing_type"],
                        openness=r["openness"],
                        conscientiousness=r["conscientiousness"],
                        extraversion=r["extraversion"],
                        agreeableness=r["agreeableness"],
                        neuroticism=r["neuroticism"],
                        monthly_income=r["monthly_income"] or 0,
                        savings=r["savings"] or 0,
                    )
                except Exception:
                    pass

            # Load current beliefs (initialize if missing)
            prev_round = max(0, round_num - 1)
            agent_beliefs: dict[int, list] = {}

            from backend.app.utils.db import get_db as _get_db  # noqa: PLC0415
            async with _get_db() as db4:
                for agent_id, profile in profiles.items():
                    beliefs = await belief_sys.load_beliefs(session_id, agent_id, prev_round, db4)
                    if not beliefs:
                        beliefs = belief_sys.initialize_beliefs(agent_id, session_id, profile)
                    agent_beliefs[agent_id] = beliefs

                # Load feed posts for belief update
                cursor = await db4.execute(
                    """SELECT agent_id, content FROM simulation_actions
                    WHERE session_id = ? AND round_number = ?""",
                    (session_id, round_num),
                )
                action_rows = await cursor.fetchall()

            feed_data: dict[int, list[str]] = {}
            for row in action_rows:
                aid = int(row[0])
                content = str(row[1] or "")
                feed_data.setdefault(aid, []).append(content)

            # Load agent decisions for dissonance detection
            agent_actions: dict[int, list[str]] = {}
            from backend.app.utils.db import get_db as _get_db2  # noqa: PLC0415
            async with _get_db2() as db5:
                cursor = await db5.execute(
                    """SELECT agent_id, action FROM agent_decisions
                    WHERE session_id = ? AND round_number = ?""",
                    (session_id, round_num),
                )
                decision_rows = await cursor.fetchall()
                for row in decision_rows:
                    aid = int(row[0])
                    agent_actions.setdefault(aid, []).append(str(row[1] or ""))

                # Update beliefs from feed
                updated_beliefs = await belief_sys.batch_update_from_feed(
                    session_id=session_id,
                    round_number=round_num,
                    agent_beliefs=agent_beliefs,
                    feed_data=feed_data,
                    trust_scores={},
                    profiles=profiles,
                    db=db5,
                )

                # Detect and resolve dissonance
                _dissonance_results, pending_deltas = await dissonance_det.batch_detect_and_resolve(
                    session_id=session_id,
                    round_number=round_num,
                    agent_beliefs=updated_beliefs,
                    agent_actions=agent_actions,
                    profiles=profiles,
                    db=db5,
                )

            # Store pending arousal deltas for next round's emotional state update
            if not hasattr(self, "_pending_arousal_deltas"):
                from collections import defaultdict  # noqa: PLC0415
                self._pending_arousal_deltas: dict[str, dict[int, float]] = defaultdict(dict)
            self._pending_arousal_deltas[session_id] = pending_deltas

            logger.debug(
                "_process_belief_update session=%s round=%d agents=%d dissonances=%d",
                session_id, round_num, len(updated_beliefs), len(_dissonance_results),
            )
        except Exception:
            logger.exception(
                "_process_belief_update failed session=%s round=%d",
                session_id, round_num,
            )

    async def _process_round_consumption(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Track household consumption for a completed simulation round."""
        try:
            if self._kg_mode.get(session_id):
                return  # kg_driven: HK consumption model not applicable
            from backend.app.services.consumption_model import ConsumptionTracker  # noqa: PLC0415
            if self._consumption_tracker is None:
                self._consumption_tracker = ConsumptionTracker()

            rows = list(self._round_profiles.get(session_id, []))

            if not rows:
                return

            from backend.app.services.agent_factory import AgentProfile  # noqa: PLC0415
            profiles = [
                AgentProfile(
                    id=r["id"],
                    agent_type=r["agent_type"],
                    age=r["age"],
                    sex=r["sex"],
                    district=r["district"],
                    occupation=r["occupation"],
                    income_bracket=r["income_bracket"],
                    education_level=r["education_level"],
                    marital_status=r["marital_status"],
                    housing_type=r["housing_type"],
                    openness=r["openness"],
                    conscientiousness=r["conscientiousness"],
                    extraversion=r["extraversion"],
                    agreeableness=r["agreeableness"],
                    neuroticism=r["neuroticism"],
                    monthly_income=r["monthly_income"] or 0,
                    savings=r["savings"] or 0,
                )
                for r in rows
            ]

            macro_state = self._macro_state.get(session_id)
            if macro_state is None:
                from backend.app.services.macro_controller import MacroController  # noqa: PLC0415
                mc = MacroController()
                macro_state = await mc.get_baseline()

            inserted = await self._consumption_tracker.track_round(
                session_id=session_id,
                round_number=round_number,
                profiles=profiles,
                macro_state=macro_state,
            )
            logger.debug(
                "_process_round_consumption: %d rows session=%s round=%d",
                inserted, session_id, round_number,
            )
        except Exception:
            logger.exception(
                "_process_round_consumption failed session=%s round=%d",
                session_id, round_number,
            )
