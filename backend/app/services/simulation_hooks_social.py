"""Social-layer simulation hooks: echo chambers, media, polarization, groups.

Mixin class extracted from SimulationRunner to keep file sizes manageable.
All methods access SimulationRunner state via ``self`` (cooperative MRO).
"""

from __future__ import annotations

from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("simulation_hooks.social")


class SocialHooksMixin:
    """Periodic hooks for social-network phenomena."""

    async def _process_echo_chambers(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Detect echo chambers and apply filter-bubble dampening."""
        try:
            from backend.app.services.social_network import SocialNetworkBuilder  # noqa: PLC0415
            if self._social_network is None:
                self._social_network = SocialNetworkBuilder()

            echo_result = await self._social_network.detect_echo_chambers(session_id)
            self._echo_chamber_result = echo_result

            await self._social_network.persist_echo_chamber_result(
                session_id, round_number, echo_result
            )

            if echo_result.num_clusters > 1:
                dampened = await self._social_network.apply_echo_chamber_dampening(
                    session_id, round_number, echo_result
                )
                logger.info(
                    "Echo chambers: %d clusters, modularity=%.4f, dampened=%d session=%s round=%d",
                    echo_result.num_clusters,
                    echo_result.modularity,
                    dampened,
                    session_id,
                    round_number,
                )
            else:
                logger.debug(
                    "Echo chambers: single cluster (no filter bubble) session=%s",
                    session_id,
                )
        except Exception:
            logger.exception(
                "_process_echo_chambers failed session=%s round=%d",
                session_id, round_number,
            )

    async def _process_community_summaries(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Generate GraphRAG community summaries for current echo chamber clusters."""
        try:
            from backend.app.services.social_network import SocialNetworkBuilder  # noqa: PLC0415
            from backend.app.services.graph_rag import GraphRAGService  # noqa: PLC0415

            if self._social_network is None:
                self._social_network = SocialNetworkBuilder()

            echo_result = await self._social_network.detect_echo_chambers(session_id)

            if echo_result.num_clusters <= 1:
                logger.debug(
                    "Skipping community summaries: only %d cluster(s) session=%s",
                    echo_result.num_clusters, session_id,
                )
                return

            from backend.app.utils.llm_client import get_default_client  # noqa: PLC0415
            graph_rag = GraphRAGService(
                vector_store=self._vector_store,
                llm_client=get_default_client(),
            )
            summaries = await graph_rag.generate_community_summaries(
                session_id, round_number, echo_result
            )
            logger.info(
                "_process_community_summaries: %d summaries session=%s round=%d",
                len(summaries), session_id, round_number,
            )
        except Exception:
            logger.exception(
                "_process_community_summaries failed session=%s round=%d",
                session_id, round_number,
            )

    async def _process_group_formation(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Detect and form new agent groups from trust network clusters."""
        try:
            from backend.app.services.collective_actions import process_group_formation  # noqa: PLC0415
            groups = await process_group_formation(session_id, round_num)
            if groups:
                logger.info(
                    "_process_group_formation session=%s round=%d new_groups=%d",
                    session_id, round_num, len(groups),
                )
        except Exception:
            logger.exception(
                "_process_group_formation failed session=%s round=%d",
                session_id, round_num,
            )

    async def _process_collective_action_momentum(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Update collective action momentum for all active actions this round."""
        try:
            from backend.app.services.collective_actions import process_collective_action_momentum  # noqa: PLC0415
            await process_collective_action_momentum(session_id, round_num)
            logger.debug(
                "_process_collective_action_momentum done session=%s round=%d",
                session_id, round_num,
            )
        except Exception:
            logger.exception(
                "_process_collective_action_momentum failed session=%s round=%d",
                session_id, round_num,
            )

    async def _process_wealth_transfers(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Process peer wealth transfers from eligible donors to KOLs."""
        try:
            from backend.app.services.wealth_transfer import process_wealth_transfers  # noqa: PLC0415

            rows = list(self._round_profiles.get(session_id, []))

            if not rows:
                return

            from backend.app.services.agent_factory import AgentProfile  # noqa: PLC0415
            profiles_by_id: dict[int, AgentProfile] = {}
            for r in rows:
                try:
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
                except Exception:
                    pass

            macro_state = self._macro_state.get(session_id)
            if macro_state is None:
                from backend.app.services.macro_controller import MacroController  # noqa: PLC0415
                macro_state = await MacroController().get_baseline()

            transfers = await process_wealth_transfers(
                session_id=session_id,
                round_num=round_num,
                profiles_by_id=profiles_by_id,
                macro_state=macro_state,
            )
            logger.debug(
                "_process_wealth_transfers session=%s round=%d transfers=%d",
                session_id, round_num, len(transfers),
            )
        except Exception:
            logger.exception(
                "_process_wealth_transfers failed session=%s round=%d",
                session_id, round_num,
            )

    async def _process_media_influence(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Propagate media influence on agent political stances."""
        try:
            from backend.app.services.media_influence import MediaInfluenceModel  # noqa: PLC0415
            if self._media_model is None:
                self._media_model = MediaInfluenceModel()

            result = await self._media_model.propagate_media_influence(
                session_id, round_number
            )
            logger.info(
                "Media influence applied session=%s round=%d influenced=%d",
                session_id,
                round_number,
                result.get("influenced_count", 0),
            )
        except Exception:
            logger.exception(
                "_process_media_influence failed session=%s round=%d",
                session_id,
                round_number,
            )

    async def _process_info_warfare(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Run fact-checking and fabricated content generation this round."""
        try:
            from backend.app.services.info_warfare import process_fact_checks, process_fabrication  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415

            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT * FROM agent_profiles WHERE session_id = ?",
                    (session_id,),
                )
                rows = await cursor.fetchall()

            if not rows:
                return

            from backend.app.services.agent_factory import AgentProfile  # noqa: PLC0415
            profiles_by_id: dict[int, AgentProfile] = {}
            for r in rows:
                try:
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
                except Exception:
                    pass

            checks = await process_fact_checks(session_id, round_num, profiles_by_id)
            fabrications = await process_fabrication(session_id, round_num, profiles_by_id)

            logger.debug(
                "_process_info_warfare session=%s round=%d checks=%d fabrications=%d",
                session_id, round_num, len(checks), len(fabrications),
            )
        except Exception:
            logger.exception(
                "_process_info_warfare failed session=%s round=%d",
                session_id, round_num,
            )

    async def _process_polarization(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Compute and persist polarization index for the current round."""
        try:
            from backend.app.services.social_network import SocialNetworkBuilder  # noqa: PLC0415
            if self._social_network is None:
                self._social_network = SocialNetworkBuilder()

            result = await self._social_network.compute_polarization_index(
                session_id, round_number
            )
            await self._social_network.persist_polarization_result(session_id, result)

            logger.info(
                "Polarization index=%.4f session=%s round=%d (mod=%.4f, var=%.4f, host=%.4f)",
                result.polarization_index, session_id, round_number,
                result.modularity, result.opinion_variance, result.cross_cluster_hostility,
            )
        except Exception:
            logger.exception(
                "_process_polarization failed session=%s round=%d",
                session_id, round_number,
            )

    # ------------------------------------------------------------------
    # Phase 3: Emotional contagion
    # ------------------------------------------------------------------

    async def _process_emotional_contagion(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Propagate emotional states through the trust network.

        High-arousal agents spread their valence/arousal to trusted neighbors.
        Contagion strength is modulated by trust score and target dominance.
        """
        try:
            from backend.app.services.emotional_engine import EmotionalEngine  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415
            from dataclasses import replace as dc_replace  # noqa: PLC0415
            from typing import Any as _Any  # noqa: PLC0415

            engine = EmotionalEngine()

            async with get_db() as db:
                states = await engine.load_states(session_id, round_num, db)

                if not states:
                    return

                # Load trust network edges
                cursor = await db.execute(
                    """SELECT agent_a_id, agent_b_id, trust_score
                    FROM agent_relationships
                    WHERE session_id = ? AND trust_score > 0""",
                    (session_id,),
                )
                trust_rows = await cursor.fetchall()

            if not trust_rows:
                return

            # Build trust map: {(source, target): score}
            trust_map: dict[tuple[int, int], float] = {}
            for row in trust_rows:
                trust_map[(int(row[0]), int(row[1]))] = float(row[2])

            # Build neighbour index once: O(E) — then each source looks up only its own edges
            trust_neighbors: dict[int, list[tuple[int, float]]] = {}
            for (a_id, b_id), score in trust_map.items():
                trust_neighbors.setdefault(a_id, []).append((b_id, score))

            # Find high-arousal agents (arousal > 0.6)
            high_arousal = {
                aid: state for aid, state in states.items()
                if state.arousal > 0.6
            }

            if not high_arousal:
                return

            modified_states: dict[int, _Any] = {}

            # O(H × avg_degree) — each source only iterates its own neighbours
            for source_id, source_state in high_arousal.items():
                for target_id, trust_score in trust_neighbors.get(source_id, []):
                    target_state = states.get(target_id)
                    if target_state is None:
                        continue

                    # Contagion strength modulated by trust and target dominance
                    contagion_strength = (
                        trust_score * source_state.arousal * (1.0 - target_state.dominance)
                    )
                    contagion_strength = max(0.0, min(1.0, contagion_strength))

                    if contagion_strength < 0.05:
                        continue

                    # Propagate valence and arousal
                    valence_delta = contagion_strength * (source_state.valence - target_state.valence) * 0.3
                    arousal_delta = contagion_strength * 0.2

                    base_state = modified_states.get(target_id, target_state)
                    new_valence = max(-1.0, min(1.0, base_state.valence + valence_delta))
                    new_arousal = max(0.0, min(1.0, base_state.arousal + arousal_delta))

                    modified_states[target_id] = dc_replace(
                        base_state,
                        valence=round(new_valence, 4),
                        arousal=round(new_arousal, 4),
                    )

            if modified_states:
                async with get_db() as db2:
                    await engine.persist_states(list(modified_states.values()), db2)

                logger.debug(
                    "_process_emotional_contagion session=%s round=%d modified=%d high_arousal=%d",
                    session_id, round_num, len(modified_states), len(high_arousal),
                )
        except Exception:
            logger.exception(
                "_process_emotional_contagion failed session=%s round=%d",
                session_id, round_num,
            )

    # ------------------------------------------------------------------
    # Emergence validation hooks (Phase 0)
    # ------------------------------------------------------------------

    async def _process_emergence_monitoring(
        self,
        session_id: str,
        round_number: int,
    ) -> None:
        """Record metric snapshot and check for phase transitions each round."""
        try:
            from backend.app.services.emergence_guards import PhaseTransitionDetector  # noqa: PLC0415
            from backend.app.models.emergence import MetricSnapshot  # noqa: PLC0415

            if not hasattr(self, "_phase_transition_detector"):
                self._phase_transition_detector = PhaseTransitionDetector()

            # Gather current metrics from available sources
            modularity = 0.0
            opinion_variance = 0.0
            sentiment_mean = 0.0
            trust_density = 0.0

            # Modularity from latest echo chamber result
            if hasattr(self, "_echo_chamber_result") and self._echo_chamber_result is not None:
                modularity = self._echo_chamber_result.modularity

            # Sentiment mean from this round's actions
            from backend.app.utils.db import get_db  # noqa: PLC0415
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT AVG(CASE sentiment
                        WHEN 'positive' THEN 1.0
                        WHEN 'negative' THEN -1.0
                        ELSE 0.0 END) AS mean_sent
                    FROM simulation_actions
                    WHERE session_id = ? AND round_number = ?""",
                    (session_id, round_number),
                )
                row = await cursor.fetchone()
                if row and row[0] is not None:
                    sentiment_mean = float(row[0])

                # Trust density: fraction of positive trust edges
                cursor = await db.execute(
                    """SELECT
                        COUNT(CASE WHEN COALESCE(trust_score, 0) > 0 THEN 1 END) AS pos,
                        COUNT(*) AS total
                    FROM agent_relationships WHERE session_id = ?""",
                    (session_id,),
                )
                trust_row = await cursor.fetchone()
                if trust_row and trust_row[1] > 0:
                    trust_density = float(trust_row[0]) / float(trust_row[1])

                # Opinion variance from latest polarization snapshot
                cursor = await db.execute(
                    """SELECT opinion_variance FROM polarization_snapshots
                    WHERE session_id = ? ORDER BY round_number DESC LIMIT 1""",
                    (session_id,),
                )
                pol_row = await cursor.fetchone()
                if pol_row and pol_row[0] is not None:
                    opinion_variance = float(pol_row[0])

            snapshot = MetricSnapshot(
                round_number=round_number,
                modularity=modularity,
                opinion_variance=opinion_variance,
                sentiment_mean=sentiment_mean,
                trust_density=trust_density,
            )

            alerts = self._phase_transition_detector.record(session_id, snapshot)

            if alerts:
                await self._phase_transition_detector.persist_alerts(session_id, alerts)
                for alert in alerts:
                    logger.warning(
                        "PHASE TRANSITION %s: %s z=%.2f delta=%.4f session=%s round=%d",
                        alert.severity.upper(),
                        alert.metric_name,
                        alert.z_score,
                        alert.delta,
                        session_id,
                        round_number,
                    )
                # Push alerts via WebSocket
                try:
                    from backend.app.api.ws import push_progress  # noqa: PLC0415
                    for alert in alerts:
                        await push_progress(session_id, {
                            "type": "emergence_alert",
                            "data": {
                                "metric": alert.metric_name,
                                "severity": alert.severity,
                                "z_score": alert.z_score,
                                "delta": alert.delta,
                                "round": round_number,
                                "direction": alert.direction,
                            },
                        })
                except Exception:
                    pass  # WebSocket push is best-effort

        except Exception:
            logger.exception(
                "_process_emergence_monitoring failed session=%s round=%d",
                session_id, round_number,
            )

    async def _run_bias_probe(self, session_id: str) -> None:
        """Run BiasProbe at simulation start to detect LLM directional bias."""
        try:
            from backend.app.services.emergence_guards import BiasProbe  # noqa: PLC0415
            probe = BiasProbe()
            result = await probe.probe(session_id, sample_size=30)
            if result.bias_detected:
                logger.warning(
                    "BIAS DETECTED session=%s: agreement=%.2f, persona_compliance=%.2f",
                    session_id, result.agreement_rate, result.persona_compliance,
                )
            else:
                logger.info(
                    "BiasProbe OK session=%s: agreement=%.2f, compliance=%.2f",
                    session_id, result.agreement_rate, result.persona_compliance,
                )
        except Exception:
            logger.exception("_run_bias_probe failed session=%s", session_id)

    # ------------------------------------------------------------------
    # Phase 1C: Dynamic Network Evolution hooks
    # ------------------------------------------------------------------

    async def _process_network_evolution(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Detect structural network changes (tie formation/dissolution, bridges, triadic closures)."""
        try:
            from backend.app.services.network_evolution import NetworkEvolutionEngine  # noqa: PLC0415

            if not hasattr(self, "_network_evolution_engine") or self._network_evolution_engine is None:
                self._network_evolution_engine = NetworkEvolutionEngine()

            engine: NetworkEvolutionEngine = self._network_evolution_engine

            # Load current trust scores from DB
            current_trusts = await engine.load_current_trusts(session_id)
            # Retrieve previous trusts from engine cache (set at end of last call)
            previous_trusts = engine._prev_trusts.get(session_id, {})
            # Load cluster assignments from latest echo chamber snapshot
            cluster_assignments = await engine.load_cluster_assignments(session_id)

            events, stats = await engine.detect_events(
                session_id=session_id,
                round_number=round_num,
                previous_trusts=previous_trusts,
                current_trusts=current_trusts,
                cluster_assignments=cluster_assignments,
            )

            # Persist events to DB
            await engine.persist_events(session_id, events)

            # Write network patch for triadic closures
            triadic = [e for e in events if e.event_type == "TRIADIC_CLOSURE"]
            if triadic:
                await engine.write_network_patch(session_id, triadic)

            # Update previous trusts cache for next round
            engine._prev_trusts[session_id] = current_trusts

            logger.info(
                "_process_network_evolution session=%s round=%d "
                "events=%d formed=%d dissolved=%d bridges=%d triadic=%d shifts=%d",
                session_id, round_num, len(events),
                stats.ties_formed, stats.ties_dissolved,
                stats.bridges_detected, stats.triadic_closures, stats.cluster_shifts,
            )
        except Exception:
            logger.exception(
                "_process_network_evolution failed session=%s round=%d",
                session_id, round_num,
            )

    # ------------------------------------------------------------------
    # Phase 2: Recommendation Engine hooks
    # ------------------------------------------------------------------

    async def _process_feed_ranking(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Rank posts for all agents and compute filter bubble metrics."""
        try:
            from backend.app.services.feed_ranker import FeedRankingEngine  # noqa: PLC0415
            from backend.app.models.recommendation import FeedAlgorithm  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415

            engine = FeedRankingEngine()

            # Get feed algorithm from preset config
            feed_algo_str = getattr(
                self._preset.hook_config, "feed_algorithm", "engagement_first"
            )
            try:
                algorithm = FeedAlgorithm(feed_algo_str)
            except ValueError:
                algorithm = FeedAlgorithm.ENGAGEMENT_FIRST

            async with get_db() as db:
                # Load agent profiles for stance
                cursor = await db.execute(
                    "SELECT id, COALESCE(political_stance, 0.5) "
                    "FROM agent_profiles WHERE session_id = ?",
                    (session_id,),
                )
                agent_rows = await cursor.fetchall()

                if not agent_rows:
                    return

                feeds: dict[int, list] = {}
                bubble_indices = []

                for agent_row in agent_rows:
                    agent_id = int(agent_row[0])
                    agent_stance = float(agent_row[1])
                    feed = await engine.rank_feed(
                        session_id=session_id,
                        agent_id=agent_id,
                        agent_stance=agent_stance,
                        round_number=round_num,
                        algorithm=algorithm,
                        db=db,
                    )
                    feeds[agent_id] = feed
                    bubble_idx = await engine.compute_bubble_index(
                        agent_id=agent_id,
                        agent_stance=agent_stance,
                        feed_posts=feed,
                        round_number=round_num,
                    )
                    bubble_indices.append(bubble_idx)

                # Persist feeds and bubble report
                await engine.persist_feeds(session_id, feeds, db)
                report = await engine.compute_bubble_report(
                    session_id, round_num, algorithm, bubble_indices
                )
                await engine.persist_bubble_report(report, db)

            logger.info(
                "_process_feed_ranking session=%s round=%d agents=%d "
                "algorithm=%s avg_bubble=%.3f",
                session_id, round_num, len(feeds),
                algorithm.value, report.avg_bubble_score,
            )
        except Exception:
            logger.exception(
                "_process_feed_ranking failed session=%s round=%d",
                session_id, round_num,
            )

    async def _process_virality_scoring(
        self,
        session_id: str,
        round_num: int,
    ) -> None:
        """Compute and persist virality scores for all root posts."""
        try:
            from backend.app.services.virality_scorer import ViralityScorer  # noqa: PLC0415
            from backend.app.utils.db import get_db  # noqa: PLC0415

            scorer = ViralityScorer()
            async with get_db() as db:
                scores = await scorer.score_posts(session_id, round_num, db)
                await scorer.persist_scores(session_id, scores, db)

            logger.info(
                "_process_virality_scoring session=%s round=%d posts_scored=%d",
                session_id, round_num, len(scores),
            )
        except Exception:
            logger.exception(
                "_process_virality_scoring failed session=%s round=%d",
                session_id, round_num,
            )

    async def _generate_emergence_scorecard(self, session_id: str) -> None:
        """Generate emergence scorecard at simulation completion."""
        try:
            from backend.app.services.emergence_scorecard import EmergenceScorecardGenerator  # noqa: PLC0415
            generator = EmergenceScorecardGenerator()
            scorecard = await generator.generate(session_id)
            logger.info(
                "Emergence scorecard session=%s: grade=%s, emergence_ratio=%.2f, bias=%.2f",
                session_id, scorecard.grade, scorecard.emergence_ratio,
                scorecard.bias_contamination,
            )
        except Exception:
            logger.exception(
                "_generate_emergence_scorecard failed session=%s", session_id,
            )
