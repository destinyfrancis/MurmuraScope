"""KG-driven simulation hooks.

Mixin class extracted from SimulationRunner to keep file sizes manageable.
All methods access SimulationRunner state via ``self`` (cooperative MRO).

Covers: kg_driven mode init, world events, cognitive deliberation,
strategic planning, consensus debate, belief propagation, relationship
states/lifecycle, faction mapping, tipping points, and TDMI.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("simulation_runner")


class KGDrivenHooksMixin:
    """KG-driven mode hooks: init, deliberation, beliefs, factions, TDMI."""

    async def _init_kg_driven_mode(self, session_id: str, config: dict[str, Any]) -> None:
        """Detect kg_driven mode from config and initialise services.

        Only activates when ``sim_mode`` in the config is ``"kg_driven"``
        (or falls back to DB lookup). For hk_demographic this is a no-op.
        """
        sim_mode = config.get("sim_mode", "")
        if not sim_mode:
            # Fallback: check DB for the session's sim_mode
            try:
                from backend.app.utils.db import get_db  # noqa: PLC0415

                async with get_db() as db:
                    cursor = await db.execute(
                        "SELECT sim_mode FROM simulation_sessions WHERE id = ?",
                        (session_id,),
                    )
                    row = await cursor.fetchone()
                    sim_mode = row["sim_mode"] if row else ""
            except Exception:
                logger.debug("Could not load sim_mode from DB for %s", session_id)

        if sim_mode != "kg_driven":
            return

        self._kg_mode[session_id] = True
        logger.info("kg_driven mode activated for session %s", session_id)

        # Lazily create shared service instances (singleton across sessions)
        if self._world_event_gen is None:
            from backend.app.services.world_event_generator import WorldEventGenerator  # noqa: PLC0415

            self._world_event_gen = WorldEventGenerator()
        if self._cognitive_engine is None:
            from backend.app.services.cognitive_agent_engine import CognitiveAgentEngine  # noqa: PLC0415

            self._cognitive_engine = CognitiveAgentEngine()
        if self._belief_propagation is None:
            from backend.app.services.belief_propagation import BeliefPropagationEngine  # noqa: PLC0415

            self._belief_propagation = BeliefPropagationEngine()
        if self._consensus_debate is None:
            from backend.app.services.consensus_debate_engine import ConsensusDebateEngine  # noqa: PLC0415

            self._consensus_debate = ConsensusDebateEngine()
        if self._faction_mapper is None:
            from backend.app.services.emergence_tracker import FactionMapper  # noqa: PLC0415

            self._faction_mapper = FactionMapper()
        if self._tipping_detector is None:
            from backend.app.services.emergence_tracker import TippingPointDetector  # noqa: PLC0415

            self._tipping_detector = TippingPointDetector()
        if self._relationship_lifecycle is None:
            from backend.app.services.relationship_lifecycle import RelationshipLifecycleService  # noqa: PLC0415

            self._relationship_lifecycle = RelationshipLifecycleService()
        if self._relationship_memory is None:
            from backend.app.services.relationship_memory import RelationshipMemoryService  # noqa: PLC0415

            self._relationship_memory = RelationshipMemoryService()
        if self._strategic_planner is None:
            from backend.app.services.strategic_planner import StrategicPlanner  # noqa: PLC0415

            self._strategic_planner = StrategicPlanner()
        if self._reflection_service is None:
            from backend.app.services.reflection_service import ReflectionService  # noqa: PLC0415

            self._reflection_service = ReflectionService()

        # Initialise per-session state via KGSessionState
        from backend.app.models.kg_session_state import KGSessionState  # noqa: PLC0415

        lite = config.get("lite_ensemble", False)
        self._kg_sessions[session_id] = KGSessionState(lite_ensemble=lite)
        if lite:
            logger.info("lite_ensemble mode: rule-based hooks for session %s", session_id)

        # Load scenario description + active metrics from DB (if available)
        await self._load_kg_session_context(session_id, config)

        # Initialise relationship states and attachment styles from KG edges
        await self._init_relationship_and_attachment(session_id, config)

    async def _load_kg_session_context(self, session_id: str, config: dict[str, Any]) -> None:
        """Load seed text, scenario config, and stakeholder agents for kg_driven."""
        try:
            from backend.app.utils.db import get_db  # noqa: PLC0415

            async with get_db() as db:
                # Seed text as scenario description
                cursor = await db.execute(
                    "SELECT seed_text FROM simulation_sessions WHERE id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row and row["seed_text"]:
                    self._kg_sessions[session_id].scenario_description = row["seed_text"][:500]

                # Load ALL agent profiles with stakeholder/activity metadata
                cursor = await db.execute(
                    """SELECT id, oasis_username AS name,
                              json_extract(properties, '$.role') AS role,
                              json_extract(properties, '$.faction') AS faction,
                              is_stakeholder,
                              activity_level
                       FROM agent_profiles
                       WHERE session_id = ?
                       ORDER BY CAST(json_extract(properties, '$.importance') AS REAL) DESC""",
                    (session_id,),
                )
                rows = await cursor.fetchall()
                all_agents: list[dict[str, Any]] = []
                stakeholders: list[dict[str, Any]] = []
                for r in rows:
                    agent_dict: dict[str, Any] = {
                        "id": r["id"],
                        "name": r["name"] or "",
                        "role": r["role"] or "",
                        "faction": r["faction"] or "none",
                        "is_stakeholder": bool(r["is_stakeholder"]) if r["is_stakeholder"] else False,
                        "activity_level": float(r["activity_level"]) if r["activity_level"] else 0.5,
                    }
                    all_agents.append(agent_dict)
                    if agent_dict["is_stakeholder"]:
                        stakeholders.append(agent_dict)
                self._kg_sessions[session_id].stakeholder_agents = stakeholders
                self._kg_sessions[session_id].all_agent_dicts = all_agents

                # Store activation seed from config or hook_config
                hook_cfg = getattr(getattr(self, "_preset", None), "hook_config", None)
                self._kg_sessions[session_id].activation_seed = config.get("activation_seed") or getattr(
                    hook_cfg, "activation_seed", None
                )

                # Generate scenario config (decision types, metrics, shocks) via LLM
                # Only if active_metrics not already populated
                if not self._kg_sessions[session_id].active_metrics:
                    seed_desc = self._kg_sessions[session_id].scenario_description
                    if seed_desc:
                        try:
                            from backend.app.models.universal_agent_profile import (
                                UniversalAgentProfile,  # noqa: PLC0415
                            )
                            from backend.app.services.scenario_generator import ScenarioGenerator  # noqa: PLC0415

                            # Resolve graph_id for this session
                            gcursor = await db.execute(
                                "SELECT graph_id FROM simulation_sessions WHERE id = ?",
                                (session_id,),
                            )
                            grow = await gcursor.fetchone()
                            graph_id = grow["graph_id"] if grow else None

                            kg_nodes: list[dict] = []
                            kg_edges: list[dict] = []
                            if graph_id:
                                ncursor = await db.execute(
                                    "SELECT id, entity_type, title, description FROM kg_nodes WHERE session_id = ?",
                                    (graph_id,),
                                )
                                kg_nodes = [
                                    {"id": r["id"], "label": r["title"], "type": r["entity_type"]}
                                    for r in await ncursor.fetchall()
                                ]
                                ecursor = await db.execute(
                                    "SELECT source_id, target_id, relation_type FROM kg_edges WHERE session_id = ?",
                                    (graph_id,),
                                )
                                kg_edges = [
                                    {"source": r["source_id"], "target": r["target_id"], "relation": r["relation_type"]}
                                    for r in await ecursor.fetchall()
                                ]

                            # Build minimal UniversalAgentProfile stubs from stakeholder agents
                            agent_profiles: list[UniversalAgentProfile] = [
                                UniversalAgentProfile(
                                    id=a["id"],
                                    name=a["name"],
                                    role=a["role"],
                                    entity_type="Person",
                                    persona="",
                                    goals=(),
                                    capabilities=(),
                                    stance_axes=(),
                                    relationships=(),
                                    kg_node_id=a["id"],
                                )
                                for a in all_agents
                            ]

                            gen = ScenarioGenerator()
                            scenario_cfg = await gen.generate(seed_desc, kg_nodes, kg_edges, agent_profiles)
                            if scenario_cfg and scenario_cfg.metrics:
                                self._kg_sessions[session_id].active_metrics = {m.id: 0.5 for m in scenario_cfg.metrics}
                                metric_keys = list(self._kg_sessions[session_id].active_metrics.keys())
                                logger.info(
                                    "ScenarioGenerator: %d metrics for session %s: %s",
                                    len(metric_keys),
                                    session_id,
                                    metric_keys[:5],
                                )

                            # Mark stakeholders based on ScenarioGenerator output
                            if scenario_cfg and scenario_cfg.stakeholder_entity_types:
                                sht = scenario_cfg.stakeholder_entity_types
                                sht_set = frozenset(sht)
                                placeholders = ",".join("?" for _ in sht)
                                await db.execute(
                                    "UPDATE agent_profiles SET is_stakeholder = 1, "
                                    "activity_level = MAX(COALESCE(activity_level, 0.5), 0.8) "
                                    f"WHERE session_id = ? AND agent_type IN ({placeholders})",
                                    (session_id, *sht),
                                )
                                await db.commit()
                                # Refresh in-memory agent lists
                                for a in all_agents:
                                    entity_type = a.get("entity_type", "")
                                    if entity_type in sht_set:
                                        a["is_stakeholder"] = True
                                        a["activity_level"] = max(a.get("activity_level", 0.5), 0.8)
                                updated_stakeholders = [a for a in all_agents if a.get("is_stakeholder")]
                                self._kg_sessions[session_id].stakeholder_agents = updated_stakeholders
                                logger.info(
                                    "mark_stakeholders via ScenarioGenerator: %d/%d agents for session %s (types=%s)",
                                    len(updated_stakeholders),
                                    len(all_agents),
                                    session_id,
                                    list(sht),
                                )
                        except Exception:
                            logger.warning(
                                "ScenarioGenerator failed for session %s — using empty metrics",
                                session_id,
                                exc_info=True,
                            )

        except Exception:
            logger.warning(
                "Could not load kg_driven context for session %s",
                session_id,
                exc_info=True,
            )

    async def _init_relationship_and_attachment(self, session_id: str, config: dict[str, Any]) -> None:
        """Initialise relationship states and attachment styles for kg_driven.

        Loads KG edges for the session's graph and creates a RelationshipState
        for each directed edge pair via RelationshipEngine.initialize_relationship().
        Derives AttachmentStyle for every agent from their Big Five traits stored
        in agent_profiles.

        Errors are caught and logged — missing data leaves the dicts empty, which
        is safe (hooks guard on empty dicts).
        """
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return
        try:
            from backend.app.services.relationship_engine import (
                RelationshipEngine,  # noqa: PLC0415
                infer_attachment_style,  # noqa: PLC0415
            )
            from backend.app.utils.db import get_db  # noqa: PLC0415

            engine = RelationshipEngine()

            async with get_db() as db:
                # Resolve graph_id from the session
                cursor = await db.execute(
                    "SELECT graph_id FROM simulation_sessions WHERE id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                graph_id = row["graph_id"] if row and row["graph_id"] else None

                # Load KG edges and seed relationship states
                if graph_id:
                    cursor = await db.execute(
                        """SELECT source_id, target_id, relation_type
                           FROM kg_edges
                           WHERE session_id = ?""",
                        (session_id,),
                    )
                    edges = await cursor.fetchall()
                    rel_states: dict[tuple[str, str], Any] = {}
                    for edge in edges:
                        src = str(edge["source_id"])
                        tgt = str(edge["target_id"])
                        desc = str(edge["relation_type"] or "")
                        state = engine.initialize_relationship(
                            agent_a_id=src,
                            agent_b_id=tgt,
                            edge_description=desc,
                        )
                        rel_states[(src, tgt)] = state
                    kg_state.relationship_states = rel_states
                    logger.debug(
                        "_init_relationship_and_attachment: %d edges → %d relationship states session=%s",
                        len(edges),
                        len(rel_states),
                        session_id,
                    )

                # Load agent Big Five traits and derive attachment styles
                cursor = await db.execute(
                    """SELECT id,
                              CAST(json_extract(properties, '$.neuroticism') AS REAL) AS neuroticism,
                              CAST(json_extract(properties, '$.agreeableness') AS REAL) AS agreeableness,
                              CAST(json_extract(properties, '$.openness') AS REAL) AS openness
                       FROM agent_profiles
                       WHERE session_id = ?""",
                    (session_id,),
                )
                agent_rows = await cursor.fetchall()
                attachment_styles: dict[str, Any] = {}
                for ar in agent_rows:
                    agent_id = str(ar["id"])
                    neuroticism = float(ar["neuroticism"] or 0.5)
                    agreeableness = float(ar["agreeableness"] or 0.5)
                    openness = float(ar["openness"] or 0.5)
                    attachment_styles[agent_id] = infer_attachment_style(
                        agent_id=agent_id,
                        neuroticism=neuroticism,
                        agreeableness=agreeableness,
                        openness=openness,
                    )
                kg_state.attachment_styles = attachment_styles
                logger.debug(
                    "_init_relationship_and_attachment: %d attachment styles session=%s",
                    len(attachment_styles),
                    session_id,
                )

        except Exception:
            logger.warning(
                "_init_relationship_and_attachment failed session=%s — proceeding with empty states",
                session_id,
                exc_info=True,
            )

    async def _kg_generate_world_events(self, session_id: str, round_num: int) -> None:
        """Pre-round: generate world events for kg_driven mode."""
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return

        # Lite ensemble: rule-based event generation (no LLM)
        if kg_state.lite_ensemble:
            from backend.app.services.lite_hooks import generate_lite_events  # noqa: PLC0415

            events = generate_lite_events(
                round_number=round_num,
                active_metrics=tuple(kg_state.active_metrics.keys()),
                prev_dominant_stance=kg_state.prev_dominant_stance,
                event_history=kg_state.event_content_history,
            )
            kg_state.current_round_events = events
            kg_state.event_content_history = kg_state.event_content_history + [e.content for e in events]
            return

        if self._world_event_gen is None:
            return
        try:
            events = await self._world_event_gen.generate(
                scenario_description=kg_state.scenario_description,
                round_number=round_num,
                active_metrics=tuple(kg_state.active_metrics.keys()),
                prev_dominant_stance=kg_state.prev_dominant_stance,
                event_history=kg_state.event_content_history,
            )
            kg_state.current_round_events = events
            kg_state.event_content_history = kg_state.event_content_history + [e.content for e in events]
        except Exception:
            logger.exception(
                "kg_driven world event generation failed session=%s round=%d",
                session_id,
                round_num,
            )
            kg_state.current_round_events = []

    async def _kg_deliberation(self, session_id: str, round_num: int) -> None:
        """Group 2: stochastic cognitive deliberation for kg_driven mode.

        Replaces the former Tier-1-only gate: every round a stochastic subset
        of ALL agents is activated (probability = activity_level, stakeholder
        floor = 0.8).  All activated agents receive full LLM deliberation.
        """
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return

        # Determine active agents for this round via stochastic activation
        all_agents = kg_state.all_agent_dicts
        if not all_agents:
            # Fallback: use stakeholder list if all_agent_dicts not populated
            all_agents = kg_state.stakeholder_agents
        if not all_agents:
            return

        active = self.get_active_agents_for_round(
            session_id,
            round_num,
            all_agents,
            seed=kg_state.activation_seed,
        )
        if not active:
            return

        # Lite ensemble: rule-based deliberation (no LLM)
        if kg_state.lite_ensemble:
            from backend.app.services.lite_hooks import deliberate_lite  # noqa: PLC0415

            events = kg_state.current_round_events
            round_decisions: dict[str, str] = {}
            for agent in active:
                agent_id = agent.get("id", "")
                beliefs = kg_state.agent_beliefs.get(agent_id, {})
                emotional = kg_state.emotional_states.get(agent_id)
                result = deliberate_lite(
                    agent=agent,
                    beliefs=beliefs,
                    events=events,
                    emotional_state=emotional,
                    prev_decision=kg_state.agent_prev_decisions.get(agent_id),
                )
                round_decisions[agent_id] = result.decision
                # Apply belief updates
                if agent_id in kg_state.agent_beliefs:
                    updated = dict(kg_state.agent_beliefs[agent_id])
                    for metric, delta in result.belief_updates.items():
                        if metric in updated:
                            updated[metric] = max(0.0, min(1.0, updated[metric] + delta))
                    kg_state.agent_beliefs[agent_id] = updated
            kg_state.agent_prev_decisions = round_decisions
            return

        if self._cognitive_engine is None:
            return
        current_events = kg_state.current_round_events
        metrics = dict(kg_state.active_metrics)
        scenario = kg_state.scenario_description

        # Build id->profile lookup for relationship-depth disclosure
        active_agents_by_id: dict[str, dict] = {a.get("id", ""): a for a in active if a.get("id")}

        # Snapshot metrics once -- all agents deliberate against the same baseline.
        # Belief updates are accumulated after all coroutines complete so that
        # parallel execution is equivalent to sequential reads of round-start state.
        baseline_metrics = dict(metrics)
        active_metric_keys = tuple(baseline_metrics.keys())
        recent_event_contents = [e.content for e in current_events]

        concurrency = getattr(getattr(self, "_preset", None), "hook_config", None)
        concurrency = getattr(concurrency, "llm_concurrency", 50) if concurrency else 50
        semaphore = asyncio.Semaphore(concurrency)

        async def _deliberate_one(agent: dict) -> Any:
            """Run deliberation for one activated agent under semaphore guard."""
            async with semaphore:
                import hashlib as _hashlib  # noqa: PLC0415

                from backend.app.utils.db import get_db  # noqa: PLC0415

                agent_id = agent.get("id", "")
                emotional_state = kg_state.emotional_states.get(agent_id)
                attachment = kg_state.attachment_styles.get(agent_id)
                rel_states = kg_state.relationship_states
                from backend.app.services.simulation_helpers import _build_key_relationships  # noqa: PLC0415

                key_relationships = _build_key_relationships(
                    agent_id=agent_id,
                    rel_states=rel_states,
                    stakeholder_agents_by_id=active_agents_by_id,
                )

                # Task 2.6: retrieve salient memories to ground deliberation.
                recent_memories = ""
                if self._memory_service is not None:
                    try:
                        numeric_id = int(_hashlib.md5(agent_id.encode()).hexdigest(), 16) % (2**31)
                        recent_memories = await self._memory_service.get_agent_context(
                            session_id=session_id,
                            agent_id=numeric_id,
                            current_round=round_num,
                            context_query=scenario,
                        )
                    except Exception:
                        pass  # memory unavailable -- degrade gracefully

                # Task 2.3: use dynamically detected faction (set every 3 rounds);
                # fall back to static value from agent profile.
                dynamic_faction = kg_state.agent_factions.get(agent_id)
                faction_str = dynamic_faction if dynamic_faction else agent.get("faction", "none")

                # Phase 4: inject strategic plan context if available
                strategy_context = ""
                if self._strategic_planner is not None:
                    strategy_context = self._strategic_planner.get_strategy_context(
                        kg_state=kg_state,
                        agent_id=agent_id,
                        current_round=round_num,
                    )

                # Task 7: retrieve feed items for decision context
                feed_context = ""
                try:
                    from backend.app.services.feed_ranker import FeedRankingEngine  # noqa: PLC0415

                    feed_engine = FeedRankingEngine()
                    prev_round = max(0, round_num - 1)
                    async with get_db() as _feed_db:
                        feed_items = await feed_engine.get_agent_feed(
                            session_id,
                            numeric_id,
                            prev_round,
                            limit=5,
                            db=_feed_db,
                        )
                    if feed_items:
                        feed_lines = [
                            f"- {item.get('oasis_username', '?')}: {(item.get('content', '') or '')[:100]}"
                            for item in feed_items
                        ]
                        feed_context = "\n".join(feed_lines)
                except Exception:
                    pass  # feed unavailable — degrade gracefully

                # Task 10: retrieve trust context for decision context
                trust_context = ""
                try:
                    async with get_db() as _trust_db:
                        cursor = await _trust_db.execute(
                            """SELECT agent_b_id, trust_score
                               FROM agent_relationships
                               WHERE session_id = ? AND agent_a_id = ?
                               ORDER BY trust_score DESC LIMIT 3""",
                            (session_id, numeric_id),
                        )
                        trusted = await cursor.fetchall()
                        cursor = await _trust_db.execute(
                            """SELECT agent_b_id, trust_score
                               FROM agent_relationships
                               WHERE session_id = ? AND agent_a_id = ?
                               ORDER BY trust_score ASC LIMIT 3""",
                            (session_id, numeric_id),
                        )
                        distrusted = await cursor.fetchall()
                        trust_lines: list[str] = []
                        for r in trusted:
                            trust_lines.append(f"Trusted: Agent {r[0]} (trust={float(r[1]):.2f})")
                        for r in distrusted:
                            if float(r[1]) < 0:
                                trust_lines.append(f"Distrusted: Agent {r[0]} (trust={float(r[1]):.2f})")
                        if trust_lines:
                            trust_context = "\n".join(trust_lines)
                except Exception:
                    pass  # trust unavailable — degrade gracefully

                agent_context = {
                    "agent_id": agent_id,
                    "name": agent.get("name", ""),
                    "role": agent.get("role", ""),
                    "persona": agent.get("persona", ""),
                    "goals": list(agent.get("goals", [])),
                    "current_beliefs": baseline_metrics,
                    "recent_events": recent_event_contents,
                    "faction": faction_str,
                    "recent_memories": recent_memories,
                    "feed_context": feed_context,
                    "trust_context": trust_context,
                    "strategic_context": strategy_context,
                    "emotional_state": (
                        {
                            "valence": getattr(emotional_state, "valence", 0.0),
                            "arousal": getattr(emotional_state, "arousal", 0.3),
                        }
                        if emotional_state is not None
                        else {}
                    ),
                    "attachment_style": (
                        {
                            "style": attachment.style,
                            "anxiety": attachment.anxiety,
                            "avoidance": attachment.avoidance,
                        }
                        if attachment is not None
                        else {}
                    ),
                    "key_relationships": key_relationships,
                }
                # Route LLM model based on stakeholder status
                from backend.app.utils.llm_client import get_agent_model  # noqa: PLC0415

                agent_provider, agent_model = get_agent_model(agent.get("is_stakeholder", False))
                return await self._cognitive_engine.deliberate(
                    agent_context=agent_context,
                    scenario_description=scenario,
                    active_metrics=active_metric_keys,
                    provider=agent_provider,
                    model=agent_model,
                )

        # Fan out: deliberate all activated agents in parallel (bounded by semaphore)
        results = await asyncio.gather(
            *[_deliberate_one(agent) for agent in active],
            return_exceptions=True,
        )

        # Accumulate belief updates from all agents sequentially after gathering
        for agent, result in zip(active, results):
            if isinstance(result, Exception):
                logger.warning(
                    "Deliberation failed for agent %s session=%s: %s",
                    agent.get("id", "?"),
                    session_id,
                    result,
                )
                continue
            for metric_id, delta in result.belief_updates.items():
                if metric_id in metrics:
                    metrics[metric_id] = max(0.0, min(1.0, metrics[metric_id] + delta))

        kg_state.active_metrics = metrics

        # Reflection loop: synthesise 'thought' memories for activated agents
        # every reflection_interval rounds (Generative Agents-inspired).
        hook_cfg = self._preset.hook_config
        if self._reflection_service is not None and round_num > 0 and round_num % hook_cfg.reflection_interval == 0:
            try:
                n = await self._reflection_service.reflect_for_agents(
                    session_id=session_id,
                    round_number=round_num,
                    stakeholder_agents=active,
                    scenario_description=scenario,
                )
                logger.debug(
                    "Reflection loop: %d thoughts generated session=%s round=%d",
                    n,
                    session_id,
                    round_num,
                )
            except Exception:
                logger.debug("Reflection loop failed session=%s round=%d", session_id, round_num)

    async def _kg_strategic_planning(self, session_id: str, round_num: int) -> None:
        """Group 2: refresh strategic plans every _PLAN_HORIZON rounds.

        Phase 4 -- multi-round planning.  On plan rounds, each activated agent
        produces a 3-round intent plan via LLM.  The plan is stored in
        kg_state.agent_strategies and injected into the deliberation prompt
        for subsequent rounds so agents act with strategic consistency.

        Uses stochastic activation instead of a fixed Tier-1 gate.
        """
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return
        # Lite ensemble: skip LLM strategic planning (deliberate_lite handles it)
        if kg_state.lite_ensemble:
            return
        if self._strategic_planner is None:
            return

        all_agents = kg_state.all_agent_dicts or kg_state.stakeholder_agents
        if not all_agents:
            return

        active = self.get_active_agents_for_round(
            session_id,
            round_num,
            all_agents,
            seed=kg_state.activation_seed,
        )
        if not active:
            return

        try:
            await self._strategic_planner.update_plans(
                kg_state=kg_state,
                stakeholder_agents=active,
                round_num=round_num,
                scenario_description=kg_state.scenario_description,
            )
        except Exception:
            logger.debug("_kg_strategic_planning: planner failed session=%s round=%d", session_id, round_num)

    async def _kg_consensus_debate(self, session_id: str, round_num: int) -> None:
        """Group 2: structured multi-agent debate on divergent topics.

        Runs every N rounds (default 3). Pairs stochastically activated agents
        with opposing stances on high-divergence topics for pairwise LLM debate.
        Debate deltas feed into agent_beliefs before belief_propagation.
        """
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None or not kg_state.agent_beliefs:
            return

        all_agents = kg_state.all_agent_dicts or kg_state.stakeholder_agents
        if not all_agents:
            return

        active = self.get_active_agents_for_round(
            session_id,
            round_num,
            all_agents,
            seed=kg_state.activation_seed,
        )
        if not active:
            return

        # Lite ensemble: rule-based debate (no LLM)
        if kg_state.lite_ensemble:
            from backend.app.services.lite_hooks import run_debate_round_lite  # noqa: PLC0415

            kg_state.agent_beliefs = run_debate_round_lite(
                stakeholder_agents=active,
                agent_beliefs=kg_state.agent_beliefs,
                round_num=round_num,
            )
            return

        if self._consensus_debate is None:
            return
        if not self._consensus_debate.should_trigger(round_num):
            return

        try:
            # Build agent_profiles lookup for enrichment
            agent_profiles: dict[str, dict] = {}
            for agent in active:
                aid = agent["id"]
                profile: dict = {"persona": "", "recent_memories": ""}
                # Enrich with strategy context if available
                strategy = kg_state.agent_strategies.get(aid)
                if strategy:
                    profile["persona"] = strategy.get("plan", "")
                agent_profiles[aid] = profile

            result = await self._consensus_debate.run_debate(
                session_id=session_id,
                round_num=round_num,
                stakeholder_agents=active,
                agent_beliefs=kg_state.agent_beliefs,
                scenario_description=kg_state.scenario_description,
                agent_profiles=agent_profiles,
            )

            # Apply debate belief deltas to agent_beliefs
            if result.exchanges:
                deltas = self._consensus_debate.get_belief_deltas(result)
                updated = {aid: dict(b) for aid, b in kg_state.agent_beliefs.items()}
                for agent_id, topic_deltas in deltas.items():
                    if agent_id not in updated:
                        continue
                    for topic, delta in topic_deltas.items():
                        if topic in updated[agent_id]:
                            updated[agent_id][topic] = max(0.0, min(1.0, updated[agent_id][topic] + delta))
                kg_state.agent_beliefs = updated

                # Persist debate-updated beliefs to DB
                try:
                    import hashlib  # noqa: PLC0415

                    from backend.app.utils.db import get_db  # noqa: PLC0415

                    debate_belief_rows = []
                    for agent_id, topic_deltas in deltas.items():
                        agent_int = int(hashlib.md5(agent_id.encode()).hexdigest()[:12], 16)
                        for topic in topic_deltas:
                            new_val = kg_state.agent_beliefs.get(agent_id, {}).get(topic)
                            if new_val is not None:
                                debate_belief_rows.append(
                                    (
                                        session_id,
                                        agent_int,
                                        topic,
                                        new_val,
                                        0.5,
                                        0,
                                        round_num,
                                    )
                                )
                    if debate_belief_rows:
                        if self._batch_writer is not None:
                            for row in debate_belief_rows:
                                self._batch_writer.queue("belief_states", row)
                            async with get_db() as db:
                                await self._batch_writer.flush("belief_states", db)
                        else:
                            async with get_db() as db:
                                await db.executemany(
                                    """INSERT OR REPLACE INTO belief_states
                                       (session_id, agent_id, topic, stance,
                                        confidence, evidence_count, round_number)
                                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                    debate_belief_rows,
                                )
                                await db.commit()
                except Exception:
                    logger.debug(
                        "_kg_consensus_debate: persist to belief_states failed session=%s",
                        session_id,
                        exc_info=True,
                    )

                logger.info(
                    "consensus_debate session=%s round=%d pairs=%d topics=%d avg_consensus=%.2f",
                    session_id[:8],
                    round_num,
                    result.pairs_debated,
                    result.topics_debated,
                    (
                        sum(result.consensus_scores.values()) / len(result.consensus_scores)
                        if result.consensus_scores
                        else 0.0
                    ),
                )
        except Exception:
            logger.exception(
                "_kg_consensus_debate failed session=%s round=%d",
                session_id[:8],
                round_num,
            )

    async def _kg_belief_propagation(self, session_id: str, round_num: int) -> None:
        """Group 2: propagate world events into agent beliefs, then 1-hop cascade.

        Tasks 2.1 + 2.2: wires BeliefPropagationEngine (previously never called)
        and adds neighbour cascade so one agent's significant belief shift
        pulls its interaction partners in the same direction.
        """
        if self._belief_propagation is None:
            return
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None or not kg_state.agent_beliefs:
            return

        events = kg_state.current_round_events
        active_metrics = tuple(kg_state.active_metrics.keys())
        if not active_metrics:
            return

        from backend.app.models.cognitive_fingerprint import CognitiveFingerprint  # noqa: PLC0415
        from backend.app.services.simulation_helpers import _compute_faction_peer_stance  # noqa: PLC0415

        # --- Propagation: world events → per-agent belief deltas ---
        all_deltas: dict[str, dict[str, float]] = {}
        for agent_id, beliefs in kg_state.agent_beliefs.items():
            # Build a default fingerprint from session state.
            # CognitiveFingerprints are not yet persisted in SimulationRunner;
            # defaults give reasonable confirmation_bias / conformity values.
            fingerprint = CognitiveFingerprint(
                agent_id=agent_id,
                values={"authority": 0.5, "openness": 0.5, "loyalty": 0.5},
                info_diet=("news", "social_media", "state_media"),
                group_memberships=(),
                susceptibility={m: 0.5 for m in active_metrics},
                confirmation_bias=0.4,
                conformity=0.3,
            )
            faction_id = kg_state.agent_factions.get(agent_id, "")
            faction_peer_stance = _compute_faction_peer_stance(
                faction_id=faction_id,
                agent_id=agent_id,
                agent_beliefs=kg_state.agent_beliefs,
                agent_factions=kg_state.agent_factions,
            )
            delta = await self._belief_propagation.propagate(
                fingerprint=fingerprint,
                events=list(events),
                faction_peer_stance=faction_peer_stance,
                active_metrics=active_metrics,
                current_beliefs=beliefs,
            )
            if delta:
                all_deltas[agent_id] = delta

        # Apply propagation deltas via Bayesian core (immutable update)
        from backend.app.services.belief_system import BeliefSystem  # noqa: PLC0415

        _bs = BeliefSystem()

        updated: dict[str, dict[str, float]] = {aid: dict(b) for aid, b in kg_state.agent_beliefs.items()}
        for agent_id, deltas in all_deltas.items():
            for m, d in deltas.items():
                if m in updated.get(agent_id, {}):
                    current = updated[agent_id][m]
                    # Convert delta to likelihood ratio for Bayesian update
                    lr = _bs.compute_likelihood_ratio(
                        evidence_stance=d,
                        evidence_weight=abs(d),
                        belief_stance=current * 2.0 - 1.0,
                        confirmation_bias=0.4,
                    )
                    updated[agent_id][m] = _bs._bayesian_core(current, lr)

        # --- Cascade: 1-hop neighbour pull for large shifts (Task 2.2) ---
        cascade_deltas = self._belief_propagation.cascade(
            all_deltas=all_deltas,
            interaction_graph=kg_state.interaction_graph,
        )
        for agent_id, c_deltas in cascade_deltas.items():
            if agent_id in updated:
                for m, d in c_deltas.items():
                    if m in updated[agent_id]:
                        current = updated[agent_id][m]
                        lr = _bs.compute_likelihood_ratio(
                            evidence_stance=d,
                            evidence_weight=abs(d),
                            belief_stance=current * 2.0 - 1.0,
                            confirmation_bias=0.4,
                        )
                        updated[agent_id][m] = _bs._bayesian_core(current, lr)

        kg_state.agent_beliefs = updated

        # --- Persist beliefs to belief_states table for multi-run ensemble ---
        try:
            import hashlib  # noqa: PLC0415

            from backend.app.utils.db import get_db  # noqa: PLC0415

            belief_rows = []
            for aid, metric_dict in updated.items():
                # Convert string agent_id (slug) to deterministic int for DB
                agent_int = int(hashlib.md5(aid.encode()).hexdigest()[:12], 16)
                for metric_name, stance_val in metric_dict.items():
                    belief_rows.append(
                        (
                            session_id,
                            agent_int,
                            metric_name,
                            stance_val,
                            0.5,
                            0,
                            round_num,
                        )
                    )
            if belief_rows:
                # Route through BatchWriter if available for reduced DB round-trips
                if self._batch_writer is not None:
                    for row in belief_rows:
                        self._batch_writer.queue("belief_states", row)
                    async with get_db() as db:
                        await self._batch_writer.flush("belief_states", db)
                else:
                    async with get_db() as db:
                        await db.executemany(
                            """INSERT OR REPLACE INTO belief_states
                               (session_id, agent_id, topic, stance,
                                confidence, evidence_count, round_number)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            belief_rows,
                        )
                        await db.commit()
        except Exception:
            logger.debug(
                "_kg_belief_propagation: persist to belief_states failed session=%s",
                session_id,
                exc_info=True,
            )

        logger.debug(
            "_kg_belief_propagation session=%s round=%d agents=%d cascades=%d",
            session_id,
            round_num,
            len(all_deltas),
            len(cascade_deltas),
        )

    async def _process_relationship_states(self, session_id: str, round_num: int) -> None:
        """Group 1 parallel: update multi-dimensional relationship states.

        Reads interaction valences from simulation_actions for this round,
        runs RelationshipEngine.batch_update(), and stores updated states
        both in the in-memory cache and in the relationship_states table.

        Active only in kg_driven mode + emergence_enabled.
        """
        from backend.app.services.relationship_engine import RelationshipEngine  # noqa: PLC0415

        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None or not kg_state.relationship_states:
            return

        try:
            engine = RelationshipEngine()
            rel_states = kg_state.relationship_states

            # Gather interaction valences from simulation_actions this round
            valences: dict[tuple[str, str], float] = {}
            try:
                from backend.app.utils.db import get_db  # noqa: PLC0415

                async with get_db() as db:
                    cursor = await db.execute(
                        """
                        SELECT oasis_username, target_agent_username, sentiment
                        FROM simulation_actions
                        WHERE session_id = ? AND round_number = ?
                          AND target_agent_username IS NOT NULL
                          AND target_agent_username != ''
                        """,
                        (session_id, round_num),
                    )
                    rows = await cursor.fetchall()
                    for row in rows:
                        aid, bid, sentiment = row[0], row[1], (row[2] or "neutral")
                        v = 0.5 if sentiment == "positive" else (-0.5 if sentiment == "negative" else 0.0)
                        valences[(str(aid), str(bid))] = v
            except Exception:
                logger.debug(
                    "_process_relationship_states: could not load valences session=%s",
                    session_id,
                )

            _raw_profiles = [dict(r) for r in self._round_profiles.get(session_id, [])]
            profiles = {
                rd["oasis_username"]: {
                    "agreeableness": float(rd.get("agreeableness", 0.5) or 0.5),
                    "neuroticism": float(rd.get("neuroticism", 0.5) or 0.5),
                }
                for rd in _raw_profiles
                if rd.get("oasis_username")
            }
            attachment_styles = kg_state.attachment_styles

            updated = engine.batch_update(
                states=rel_states,
                interactions=valences,
                profiles=profiles,
                attachment_styles=attachment_styles,
            )

            # Update in-memory cache (immutable replace)
            new_states = dict(rel_states)
            for state in updated:
                new_states[(state.agent_a_id, state.agent_b_id)] = state
            kg_state.relationship_states = new_states

            # Validate relationship coherence (best-effort, never blocks simulation)
            try:
                from backend.app.services.relationship_validator import RelationshipValidator  # noqa: PLC0415

                validator = RelationshipValidator()
                validation = await validator.validate(session_id)
                if validation.dunbar_violation:
                    logger.warning(
                        "Dunbar violation session=%s round=%d avg_degree=%.2f",
                        session_id,
                        round_num,
                        validation.avg_meaningful_degree,
                    )
            except Exception:
                logger.debug(
                    "Relationship validation skipped session=%s round=%d",
                    session_id,
                    round_num,
                )

            # Persist updated states to DB via BatchWriter or direct executemany
            if updated:
                from datetime import datetime as _rel_dt  # noqa: PLC0415
                from datetime import timezone as _rel_tz  # noqa: PLC0415

                _now_str = _rel_dt.now(_rel_tz.utc).strftime("%Y-%m-%d %H:%M:%S")
                rel_rows = [
                    (
                        session_id,
                        s.agent_a_id,
                        s.agent_b_id,
                        round_num,
                        s.intimacy,
                        s.passion,
                        s.commitment,
                        s.satisfaction,
                        s.alternatives,
                        s.investment,
                        s.trust,
                        s.interaction_count,
                        s.rounds_since_change,
                        _now_str,
                    )
                    for s in updated
                ]
                if self._batch_writer is not None:
                    for row in rel_rows:
                        self._batch_writer.queue("relationship_states", row)
                    from backend.app.utils.db import get_db  # noqa: PLC0415

                    async with get_db() as db:
                        await self._batch_writer.flush("relationship_states", db)
                else:
                    from backend.app.utils.db import get_db  # noqa: PLC0415

                    async with get_db() as db:
                        await db.executemany(
                            """
                            INSERT OR REPLACE INTO relationship_states
                                (session_id, agent_a_id, agent_b_id, round_number,
                                 intimacy, passion, commitment, satisfaction,
                                 alternatives, investment, trust,
                                 interaction_count, rounds_since_change,
                                 updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            rel_rows,
                        )
                        await db.commit()

        except Exception:
            logger.exception(
                "_process_relationship_states failed session=%s round=%d",
                session_id,
                round_num,
            )

    async def _process_relationship_lifecycle(self, session_id: str, round_num: int) -> None:
        """Group 3 periodic: detect and persist relationship lifecycle events.

        Active only in kg_driven mode + emergence_enabled.
        Reads current relationship states from KGSessionState.relationship_states, detects
        lifecycle transitions, and persists events to network_events table.
        """
        if self._relationship_lifecycle is None:
            return
        kg_state = self._kg_sessions.get(session_id)
        rel_states = kg_state.relationship_states if kg_state is not None else {}
        if not rel_states:
            return
        try:
            events = self._relationship_lifecycle.detect_events(
                session_id=session_id,
                round_number=round_num,
                rel_states=rel_states,
            )
            if events:
                from backend.app.utils.db import get_db  # noqa: PLC0415

                async with get_db() as db:
                    await self._relationship_lifecycle.persist_events(events, db)
                # Store lifecycle events as dyadic relationship memories
                if self._relationship_memory is not None:
                    for evt in events:
                        agent_a = getattr(evt, "agent_id", None) or getattr(evt, "source_id", "")
                        agent_b = getattr(evt, "related_agent_id", None) or getattr(evt, "target_id", "")
                        evt_type = getattr(evt, "event_type", "interaction")
                        if agent_a and agent_b:
                            content = (
                                f"{evt_type}: relationship event between {agent_a} and {agent_b} at round {round_num}"
                            )
                            salience = 0.7 if evt_type in ("CRISIS", "DISSOLVED") else 0.5
                            await self._relationship_memory.store_interaction_memory(
                                session_id=session_id,
                                agent_id=str(agent_a),
                                related_agent_id=str(agent_b),
                                content=content,
                                round_number=round_num,
                                salience=salience,
                            )
                # Feed CRISIS events back to the emotional engine
                for evt in events:
                    evt_type = getattr(evt, "event_type", "")
                    if evt_type == "CRISIS":
                        for aid_attr in ("agent_id", "source_id"):
                            raw_aid = getattr(evt, aid_attr, None)
                            if raw_aid is not None:
                                try:
                                    self._crisis_agents[session_id].add(int(raw_aid))
                                except (ValueError, TypeError):
                                    pass
                        for aid_attr in ("related_agent_id", "target_id"):
                            raw_aid = getattr(evt, aid_attr, None)
                            if raw_aid is not None:
                                try:
                                    self._crisis_agents[session_id].add(int(raw_aid))
                                except (ValueError, TypeError):
                                    pass

                logger.debug(
                    "_process_relationship_lifecycle: %d events session=%s round=%d",
                    len(events),
                    session_id,
                    round_num,
                )
        except Exception:
            logger.exception(
                "_process_relationship_lifecycle failed session=%s round=%d",
                session_id,
                round_num,
            )

    async def _kg_faction_and_tipping(self, session_id: str, round_num: int) -> None:
        """Group 3 periodic: faction mapping + tipping point detection."""
        kg_state = self._kg_sessions.get(session_id)
        if kg_state is None:
            return
        agent_beliefs = kg_state.agent_beliefs
        if not agent_beliefs:
            return

        # Faction mapping
        if self._faction_mapper is not None:
            try:
                snapshot = self._faction_mapper.compute(
                    simulation_id=session_id,
                    round_number=round_num,
                    agent_beliefs=agent_beliefs,
                    interaction_graph=kg_state.interaction_graph,
                )
                await self._persist_faction_snapshot(snapshot)
                # Task 2.3: feed detected factions back into KGSessionState so
                # _kg_deliberation and _kg_belief_propagation can use them
                # in subsequent rounds (data is 3 rounds old — intentional lag).
                new_factions: dict[str, str] = {}
                for record in snapshot.factions:
                    for member_id in record.member_agent_ids:
                        new_factions[member_id] = record.faction_id
                kg_state.agent_factions = new_factions
            except Exception:
                logger.exception(
                    "Faction mapping failed session=%s round=%d",
                    session_id,
                    round_num,
                )

        # Tipping point detection
        if self._tipping_detector is not None:
            try:
                current_events = kg_state.current_round_events
                tipping = self._tipping_detector.detect(
                    simulation_id=session_id,
                    round_number=round_num,
                    current_beliefs=agent_beliefs,
                    belief_history=kg_state.belief_history[-3:],
                    last_event_id=(current_events[-1].event_id if current_events else None),
                )
                if tipping is not None:
                    await self._persist_tipping_point(tipping)
                    # Auto-fork: create divergent branches at tipping point
                    if kg_state.auto_fork_count < 3 and round_num not in kg_state.auto_fork_rounds:
                        self._create_tracked_task(
                            session_id,
                            self._auto_fork_at_tipping(
                                session_id,
                                round_num,
                                tipping,
                                kg_state,
                            ),
                            timeout_s=30.0,
                        )
            except Exception:
                logger.exception(
                    "Tipping point detection failed session=%s round=%d",
                    session_id,
                    round_num,
                )

        # Snapshot beliefs for history
        belief_copy = {k: dict(v) for k, v in agent_beliefs.items()}
        kg_state.belief_history = kg_state.belief_history + [belief_copy]

    async def _auto_fork_at_tipping(
        self,
        session_id: str,
        round_num: int,
        tipping: Any,
        kg_state: Any,
    ) -> None:
        """Fire-and-forget: create divergent branches at a detected tipping point."""
        from backend.app.services.auto_fork_service import fork_at_tipping_point  # noqa: PLC0415

        result = await fork_at_tipping_point(
            session_id=session_id,
            tipping=tipping,
            current_beliefs=kg_state.agent_beliefs,
            auto_fork_count=kg_state.auto_fork_count,
            round_count=self._preset.rounds,
        )
        if result is not None:
            kg_state.auto_fork_count += 1
            kg_state.auto_fork_rounds = kg_state.auto_fork_rounds + [round_num]
            logger.info(
                "Auto-fork #%d created session=%s round=%d: natural=%s nudged=%s",
                kg_state.auto_fork_count,
                session_id,
                round_num,
                result.natural_branch_id[:8],
                result.nudged_branch_id[:8],
            )
            # Notify frontend via WebSocket
            try:
                from backend.app.api.ws import push_progress  # noqa: PLC0415

                await push_progress(
                    session_id,
                    {
                        "type": "auto_fork",
                        "round": round_num,
                        "direction": result.tipping_direction,
                        "natural_branch_id": result.natural_branch_id,
                        "nudged_branch_id": result.nudged_branch_id,
                        "description": result.nudge_description,
                    },
                )
            except Exception:
                pass  # WS notification is best-effort

    async def _persist_faction_snapshot(self, snapshot: Any) -> None:
        """Persist FactionSnapshot to faction_snapshots_v2 table."""
        import uuid as _uuid  # noqa: PLC0415

        from backend.app.utils.db import get_db  # noqa: PLC0415

        try:
            async with get_db() as db:
                await db.execute(
                    """INSERT OR REPLACE INTO faction_snapshots_v2
                       (id, simulation_id, round_number, factions_json,
                        bridge_agents_json, modularity_score, inter_faction_hostility)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid.uuid4()),
                        snapshot.simulation_id,
                        snapshot.round_number,
                        json.dumps(
                            [
                                {
                                    "faction_id": f.faction_id,
                                    "member_agent_ids": list(f.member_agent_ids),
                                    "belief_center": f.belief_center,
                                }
                                for f in snapshot.factions
                            ]
                        ),
                        json.dumps(list(snapshot.bridge_agents)),
                        snapshot.modularity_score,
                        snapshot.inter_faction_hostility,
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to persist faction snapshot sim=%s round=%d",
                snapshot.simulation_id,
                snapshot.round_number,
            )

    async def _persist_tipping_point(self, tipping: Any) -> None:
        """Persist TippingPoint to tipping_points table."""
        import uuid as _uuid  # noqa: PLC0415

        from backend.app.utils.db import get_db  # noqa: PLC0415

        try:
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO tipping_points
                       (id, simulation_id, round_number, trigger_event_id,
                        kl_divergence, change_direction, affected_factions_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(_uuid.uuid4()),
                        tipping.simulation_id,
                        tipping.round_number,
                        tipping.trigger_event_id,
                        tipping.kl_divergence,
                        tipping.change_direction,
                        json.dumps(list(tipping.affected_faction_ids)),
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to persist tipping point sim=%s round=%d",
                tipping.simulation_id,
                tipping.round_number,
            )

    async def _compute_tdmi(self, session_id: str, round_num: int) -> None:
        """Group 3 periodic: TDMI emergence measurement (every 5 rounds, both modes).

        Reads belief_states table, computes Time-Delayed Mutual Information for
        each topic × lag, and persists results to emergence_metrics table.
        Logged at INFO level; failures are non-fatal.
        """
        try:
            from backend.app.services.emergence_metrics import EmergenceMetricsCalculator  # noqa: PLC0415

            calculator = EmergenceMetricsCalculator()
            await calculator.compute_and_persist(session_id, round_num)
        except Exception:
            logger.exception(
                "_compute_tdmi failed session=%s round=%d",
                session_id,
                round_num,
            )
