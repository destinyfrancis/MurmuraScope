"""OASIS subprocess orchestration for MurmuraScope.

Launches and monitors the OASIS Twitter simulation as an external subprocess,
reading JSONL progress updates from stdout, pushing them to the WebSocket
progress queue, and parking the OASIS output database at a stable path.

Hook methods are organised into mixin classes:
  - AgentHooksMixin       (memories, trust, decisions, consumption)
  - SocialHooksMixin      (echo chambers, media, polarization, groups)
  - MacroHooksMixin       (macro feedback, credit cycle, news, B2B decisions)
  - KGHooksMixin          (KG snapshots, B2B/social init)
  - KGDrivenHooksMixin    (kg_driven: deliberation, beliefs, factions, TDMI)
  - SimulationLifecycleMixin (run, stop, cleanup, dry-run, action logs)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
import json
import os
import random
import random as _random
import time as _time
from pathlib import Path
from typing import Any, Callable, Coroutine

from backend.app.models.kg_session_state import KGSessionState
from backend.app.services.simulation_helpers import _timed_block, _PROJECT_ROOT
from backend.app.services.simulation_hooks_agent import AgentHooksMixin
from backend.app.services.simulation_hooks_kg import KGHooksMixin
from backend.app.services.simulation_hooks_kg_driven import KGDrivenHooksMixin
from backend.app.services.simulation_hooks_macro import MacroHooksMixin
from backend.app.services.simulation_hooks_social import SocialHooksMixin
from backend.app.services.simulation_lifecycle import SimulationLifecycleMixin
from backend.app.services.simulation_subprocess_manager import SimulationSubprocessManager
from backend.app.utils.logger import get_logger

logger = get_logger("simulation_runner")

ProgressCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class SimulationRunner(
    KGDrivenHooksMixin,
    SimulationLifecycleMixin,
    AgentHooksMixin,
    SocialHooksMixin,
    MacroHooksMixin,
    KGHooksMixin,
):
    """Orchestrates the OASIS Twitter simulation subprocess.

    Hook methods are defined in the mixin base classes to keep this file
    focused on subprocess lifecycle and round dispatch.
    """

    def __init__(
        self,
        dry_run: bool = False,
        preset: "SimPreset | None" = None,
    ) -> None:
        from backend.app.models.simulation_config import PRESET_STANDARD, SimPreset  # noqa: PLC0415
        self._preset: SimPreset = preset or PRESET_STANDARD
        self._dry_run = dry_run
        self._subprocess_mgr = SimulationSubprocessManager()
        self._action_logger: Any | None = None
        self._memory_service: Any | None = None
        self._vector_store: Any | None = None
        self._posts_buffer: dict[str, dict[int, dict[str, list[str]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        self._macro_controller: Any | None = None
        self._macro_history: Any | None = None
        # Tracks the latest MacroState per session for feedback accumulation
        self._macro_state: dict[str, Any] = {}
        # Per-session locks protecting _macro_state writes (Plan A — H3 race condition)
        self._macro_locks: dict[str, asyncio.Lock] = {}
        self._decision_engine: Any | None = None
        self._media_model: Any | None = None
        self._consumption_tracker: Any | None = None
        self._bank_agent: Any | None = None
        self._trust_service: Any | None = None
        self._social_network: Any | None = None
        self._echo_chamber_result: Any | None = None
        # Track per-session background tasks to cancel them on cleanup
        self._pending_tasks: dict[str, set[asyncio.Task]] = defaultdict(set)  # type: ignore[type-arg]
        # Round-level profile cache: populated once per round before Group 1, cleared at session end.
        # Keyed by session_id. Stores raw aiosqlite.Row objects (dict-style access supported).
        # MUST NOT be cleared per-round — Group 3 fire-and-forget tasks (_process_wealth_transfers)
        # may read the cache after the round boundary.
        self._round_profiles: dict[str, list] = {}
        # Phase 1B: per-session activity profiles (username → ActivityProfile)
        self._activity_profiles: dict[str, dict[str, Any]] = {}
        # Per-session RNG for activation sampling (seeded per session for reproducibility)
        self._activation_rngs: dict[str, random.Random] = {}
        # Phase 3: pending arousal deltas from cognitive dissonance denial
        self._pending_arousal_deltas: dict[str, dict[int, float]] = defaultdict(dict)
        # Phase 4: agents in relationship crisis (session_id → set of agent_id ints)
        self._crisis_agents: dict[str, set[int]] = defaultdict(set)
        # Phase 4A: optional scale profiler (None = profiling disabled)
        self._profiler: Any | None = None
        # kg_driven mode services (initialised lazily per session in run())
        self._kg_mode: dict[str, bool] = {}  # session_id → True if kg_driven
        self._world_event_gen: Any | None = None
        self._cognitive_engine: Any | None = None
        self._belief_propagation: Any | None = None
        self._faction_mapper: Any | None = None
        self._tipping_detector: Any | None = None
        # kg_driven per-session state — all 12 fields consolidated into KGSessionState
        self._kg_sessions: dict[str, KGSessionState] = {}
        # Phase 4: relationship lifecycle service (kg_driven + emergence)
        self._relationship_lifecycle: Any | None = None
        # Phase 4: relationship memory service (dyadic memory storage)
        self._relationship_memory: Any | None = None
        # Phase 4: strategic planner for stakeholder multi-round planning
        self._strategic_planner: Any | None = None
        # Consensus debate engine for structured multi-agent argumentation
        self._consensus_debate: Any | None = None
        # Reflection loop: periodic insight synthesis for stakeholder agents
        self._reflection_service: Any | None = None
        # Phase 4A: per-session RoundCache for in-memory agent profile lookups
        self._round_caches: dict[str, "RoundCache"] = {}
        # Phase 4A: BatchWriter for high-throughput bulk inserts
        self._batch_writer: Any | None = None
        # Phase 4D: optional shard coordinator for large-scale subprocess sharding
        # Activated only when DB_SHARDING_ENABLED=true env var is set.
        self._shard_coordinators: dict[str, Any] = {}
        self._init_batch_writer()

    def _init_batch_writer(self) -> None:
        """Lazily initialise the BatchWriter and register hot-path tables."""
        try:
            from backend.app.services.batch_writer import BatchWriter  # noqa: PLC0415
            writer = BatchWriter(flush_threshold=500)
            writer.register_table("belief_states", [
                "session_id", "agent_id", "topic", "stance",
                "confidence", "evidence_count", "round_number",
            ])
            writer.register_table("relationship_states", [
                "session_id", "agent_a_id", "agent_b_id", "round_number",
                "intimacy", "passion", "commitment", "satisfaction",
                "alternatives", "investment", "trust",
                "interaction_count", "rounds_since_change", "updated_at",
            ])
            writer.register_table("simulation_actions", [
                "session_id", "oasis_username", "round_number",
                "action_type", "content", "sentiment",
                "target_agent_username",
            ])
            self._batch_writer = writer
            logger.debug("BatchWriter initialised with 3 registered tables")
        except Exception:
            logger.warning("BatchWriter init failed — falling back to direct executemany", exc_info=True)
            self._batch_writer = None

    def _is_sharding_enabled(self) -> bool:
        """Check if subprocess sharding is enabled via env var."""
        return os.environ.get("DB_SHARDING_ENABLED", "").lower() == "true"

    def _get_shard_coordinator(
        self,
        session_id: str,
        python_bin: Path,
        script_path: Path,
    ) -> Any:
        """Create or retrieve a ShardCoordinator for the given session.

        Returns None if sharding is not enabled.
        """
        if not self._is_sharding_enabled():
            return None

        if session_id not in self._shard_coordinators:
            from backend.app.services.shard_coordinator import ShardCoordinator  # noqa: PLC0415
            coord = ShardCoordinator(
                session_id=session_id,
                python_bin=python_bin,
                script_path=script_path,
            )
            self._shard_coordinators[session_id] = coord
            logger.info("Created ShardCoordinator for session %s", session_id)

        return self._shard_coordinators[session_id]

    async def _cleanup_shard_coordinator(self, session_id: str) -> None:
        """Shutdown and remove the shard coordinator for a session."""
        coord = self._shard_coordinators.pop(session_id, None)
        if coord is not None:
            try:
                await coord.shutdown_all()
                logger.info("ShardCoordinator cleaned up for session %s", session_id)
            except Exception:
                logger.exception("ShardCoordinator cleanup failed for session %s", session_id)

    def _create_tracked_task(
        self,
        session_id: str,
        coro: Any,
        timeout_s: float = 60.0,
    ) -> "asyncio.Task[Any]":
        """Create an asyncio task and register it for cleanup on session end.

        All fire-and-forget tasks must go through this method so that the
        finally block in run() can cancel them if the simulation ends before
        the task completes, preventing async task leaks.

        Args:
            timeout_s: Per-task timeout in seconds. Exceeded tasks are cancelled
                and logged as warnings rather than crashing the simulation.
        """
        coro_name = getattr(coro, "__qualname__", type(coro).__name__)

        async def _wrapped() -> None:
            try:
                await asyncio.wait_for(coro, timeout=timeout_s)
            except asyncio.TimeoutError:
                logger.warning(
                    "Task timeout after %.0fs session=%s task=%s",
                    timeout_s,
                    session_id,
                    coro_name,
                )
            except asyncio.CancelledError:
                pass  # Expected on clean shutdown
            except Exception:
                logger.error(
                    "Tracked task crashed session=%s task=%s",
                    session_id,
                    coro_name,
                    exc_info=True,
                )

        task: asyncio.Task[Any] = asyncio.create_task(_wrapped())
        task_set = self._pending_tasks[session_id]
        task_set.add(task)
        task.add_done_callback(lambda t: task_set.discard(t))
        return task

    async def _fetch_and_cache_profiles(self, session_id: str) -> list:
        """Fetch all agent profiles for a session and cache for the current round.

        Called once per round at the start of _execute_round_hooks, before Group 1.
        All hooks that need profiles read from self._round_profiles[session_id] instead
        of issuing their own SELECT queries.

        Cache is cleared at session end (not per-round) because Group 3 fire-and-forget
        tasks may read the cache after the round boundary.

        The cache stores raw aiosqlite.Row objects. Consuming code may:
        - Access columns via r["column_name"] (dict-style, supported by aiosqlite.Row)
        - Reconstruct AgentProfile from the row fields
        NOTE: `oasis_username` is in the cache but is NOT an AgentProfile
        field — access it via r["oasis_username"] directly, never via a reconstructed AgentProfile.
        """
        from backend.app.utils.db import get_db  # noqa: PLC0415
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT id, agent_type, age, sex, district, occupation, income_bracket,
                       education_level, marital_status, housing_type,
                       openness, conscientiousness, extraversion,
                       agreeableness, neuroticism, monthly_income,
                       savings, political_stance, oasis_username
                       FROM agent_profiles WHERE session_id = ?""",
                    (session_id,),
                )
                rows = await cursor.fetchall()
        except Exception:
            logger.error(
                "_fetch_and_cache_profiles failed session=%s — using empty cache",
                session_id, exc_info=True,
            )
            rows = []
        self._round_profiles[session_id] = rows

        # Populate RoundCache with agent data keyed by oasis_username for O(1) lookups
        try:
            from backend.app.services.round_cache import RoundCache  # noqa: PLC0415
            cache = self._round_caches.get(session_id)
            if cache is None:
                cache = RoundCache()
                self._round_caches[session_id] = cache
            agents_dict: dict[str, dict] = {}
            for r in rows:
                uname = r["oasis_username"] if r["oasis_username"] else str(r["id"])
                agents_dict[uname] = {
                    "id": r["id"],
                    "agent_type": r["agent_type"],
                    "oasis_username": r["oasis_username"],
                    "political_stance": r["political_stance"],
                    "openness": r["openness"],
                    "conscientiousness": r["conscientiousness"],
                    "extraversion": r["extraversion"],
                    "agreeableness": r["agreeableness"],
                    "neuroticism": r["neuroticism"],
                }
            cache.bulk_load_agents(agents_dict)
        except Exception:
            logger.debug(
                "_fetch_and_cache_profiles: RoundCache population failed session=%s",
                session_id, exc_info=True,
            )

        return rows

    async def _execute_round_hooks(self, session_id: str, round_num: int) -> None:
        """Execute round hooks with dependency-aware grouping.

        Group 1 (parallel, awaited): memories + trust (+ emotional_state if emergence)
        Group 2 (sequential after G1): decisions → side effects (+ belief if emergence) → consumption
        Group 3 (periodic, fire-and-forget): all interval-driven hooks
        """
        _round_t0 = _time.monotonic()
        # Populate per-round profile cache (shared by all hooks this round via self._round_profiles)
        await self._fetch_and_cache_profiles(session_id)
        agent_count = len(self._round_profiles.get(session_id, []))

        hc = self._preset.hook_config

        # Pre-round: kg_driven world event generation
        if self._kg_mode.get(session_id):
            await self._kg_generate_world_events(session_id, round_num)

        # Phase 2: feed ranking must complete before agent decision hooks read the feed
        if self._profiler:
            _t_feed = self._profiler.start_hook("feed_ranking", round_num)
        await self._process_feed_ranking(session_id, round_num)
        if self._profiler:
            self._profiler.end_hook("feed_ranking", round_num, _t_feed)

        # Emergence monitoring: phase transition detection (every round, lightweight)
        self._create_tracked_task(
            session_id,
            self._process_emergence_monitoring(session_id, round_num),
        )

        # Group 1: Independent critical hooks (run in parallel, AWAIT completion)
        if self._profiler:
            _t_g1 = self._profiler.start_hook("group_1", round_num)
        critical = [
            self._process_round_memories(session_id, round_num),
            self._process_round_trust(session_id, round_num),
        ]
        if hc.emergence_enabled:
            critical.append(self._process_emotional_state(session_id, round_num))
        # kg_driven + emergence: update multi-dimensional relationship states
        if self._kg_mode.get(session_id) and hc.emergence_enabled:
            critical.append(self._process_relationship_states(session_id, round_num))
        with _timed_block("group1_parallel", session_id, round_num=round_num):
            results = await asyncio.gather(*critical, return_exceptions=True)
        if self._profiler:
            self._profiler.end_hook("group_1", round_num, _t_g1)
        for r in results:
            if isinstance(r, Exception):
                logger.error(
                    "Critical hook failed session=%s round=%d: %s",
                    session_id, round_num, r,
                )

        # Group 2: Depends on memories being stored
        if self._profiler:
            _t_g2 = self._profiler.start_hook("group_2", round_num)
        with _timed_block("group2_sequential", session_id, round_num=round_num):
            await self._process_round_decisions(session_id, round_num)
            await self._apply_decision_side_effects(session_id, round_num)
            if hc.emergence_enabled:
                await self._process_belief_update(session_id, round_num)
            await self._process_round_consumption(session_id, round_num)
            # kg_driven: strategic planning + stochastic cognitive deliberation + consensus debate + belief propagation
            if self._kg_mode.get(session_id):
                await self._kg_strategic_planning(session_id, round_num)
                await self._kg_deliberation(session_id, round_num)
                await self._kg_consensus_debate(session_id, round_num)
                await self._kg_belief_propagation(session_id, round_num)
        if self._profiler:
            self._profiler.end_hook("group_2", round_num, _t_g2)

        # Group 3: Periodic hooks (fire-and-forget, tracked for cleanup)
        logger.debug(
            "hook=group3_fired session=%s round=%d",
            session_id[:8],
            round_num,
        )
        if round_num > 0 and round_num % hc.company_decision_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_round_company_decisions(session_id, round_num),
            )
            self._create_tracked_task(
                session_id,
                self._process_credit_cycle(session_id, round_num),
            )
        if round_num > 0 and round_num % hc.media_influence_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_media_influence(session_id, round_num),
                timeout_s=90.0,
            )
            if hc.emergence_enabled:
                self._create_tracked_task(
                    session_id,
                    self._process_info_warfare(session_id, round_num),
                    timeout_s=90.0,
                )
        if round_num > 0 and round_num % hc.echo_chamber_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_echo_chambers(session_id, round_num),
            )
        if round_num > 0 and round_num % hc.macro_feedback_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_macro_feedback(session_id, round_num),
            )
            if hc.emergence_enabled:
                self._create_tracked_task(
                    session_id,
                    self._process_wealth_transfers(session_id, round_num),
                )
            # Supply chain cascade: propagate disruption through KG edges (kg_driven only)
            if self._kg_mode.get(session_id):
                self._create_tracked_task(
                    session_id,
                    self._process_supply_chain_cascade(session_id, round_num),
                )
        if round_num > 0 and round_num % hc.news_shock_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_news_shock(session_id, round_num),
                timeout_s=90.0,
            )
        if round_num > 0 and round_num % hc.kg_evolution_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_kg_evolution(session_id, round_num),
                timeout_s=90.0,
            )
        if round_num > 0 and round_num % hc.kg_snapshot_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_kg_snapshot(session_id, round_num),
            )
        if round_num > 0 and round_num % hc.polarization_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_polarization(session_id, round_num),
            )
            self._create_tracked_task(
                session_id,
                self._process_community_summaries(session_id, round_num),
            )
        # Bug 2 fix: group_formation uses collective_action_interval, not polarization_interval
        if hc.emergence_enabled and round_num > 0 and round_num % hc.collective_action_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_group_formation(session_id, round_num),
            )
        # Collective action momentum (moved from Group 2 to Group 3, periodic)
        if hc.emergence_enabled and round_num > 0 and round_num % hc.collective_action_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_collective_action_momentum(session_id, round_num),
            )
        # Bug 1 fix: attention_allocation moved from Group 1 to Group 3 with interval check
        if hc.emergence_enabled and round_num > 0 and round_num % hc.attention_economy_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_attention_allocation(session_id, round_num),
            )
        # Phase 1C: network evolution (structural tie / bridge / triadic closure detection)
        if hc.emergence_enabled and round_num > 0 and round_num % hc.network_evolution_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_network_evolution(session_id, round_num),
            )
        # Phase 2: virality scoring
        if hc.emergence_enabled and round_num > 0 and round_num % hc.virality_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_virality_scoring(session_id, round_num),
            )
        # Phase 3: emotional contagion (periodic, emergence-gated)
        if hc.emergence_enabled and round_num > 0 and round_num % hc.emotional_contagion_interval == 0:
            self._create_tracked_task(
                session_id,
                self._process_emotional_contagion(session_id, round_num),
            )

        # kg_driven: faction mapping + tipping point detection (every 3 rounds)
        if self._kg_mode.get(session_id) and round_num > 0 and round_num % 3 == 0:
            self._create_tracked_task(
                session_id,
                self._kg_faction_and_tipping(session_id, round_num),
                timeout_s=90.0,
            )

        # kg_driven + emergence: relationship lifecycle detection (every 3 rounds)
        if (
            self._kg_mode.get(session_id)
            and hc.emergence_enabled
            and round_num > 0
            and round_num % 3 == 0
            and self._relationship_lifecycle is not None
        ):
            self._create_tracked_task(
                session_id,
                self._process_relationship_lifecycle(session_id, round_num),
            )

        # TDMI emergence measurement (every 5 rounds, both modes)
        if round_num > 0 and round_num % 5 == 0:
            self._create_tracked_task(
                session_id,
                self._compute_tdmi(session_id, round_num),
                timeout_s=30.0,
            )

        # Round-level wall-clock summary (Groups 1+2 synchronous work only;
        # Group 3 fire-and-forget tasks finish asynchronously after this point).
        _round_total_ms = int((_time.monotonic() - _round_t0) * 1000)
        logger.info(
            "session=%s round=%d agents=%d total_round_ms=%d",
            session_id, round_num, agent_count, _round_total_ms,
        )

        # Clean up posts buffer for completed round to prevent memory growth
        session_buf = self._posts_buffer.get(session_id)
        if session_buf is not None:
            session_buf.pop(round_num, None)

        # Cost pause check: if the session has hit the hard cap, pause up to 30 min.
        # The simulation continues automatically after the timeout even if not resumed.
        try:
            from backend.app.services import cost_tracker as _ct  # noqa: PLC0415
            if _ct.is_paused(session_id):
                total_cost = _ct.get_session_cost(session_id)
                hard_cap = float(
                    os.environ.get("SESSION_COST_HARD_CAP_USD", "10.0")
                )
                logger.warning(
                    "Cost pause: session=%s round=%d total=$%.4f cap=$%.2f — "
                    "waiting up to 30 min for resume",
                    session_id, round_num, total_cost, hard_cap,
                )
                # Push WebSocket notification (best-effort)
                try:
                    from backend.app.api.ws import push_progress as _push  # noqa: PLC0415
                    await _push(session_id, {
                        "type": "cost_pause",
                        "session_id": session_id,
                        "total_cost": total_cost,
                        "cap": hard_cap,
                        "round": round_num,
                    })
                except Exception:
                    logger.debug("cost_pause: WS push failed (best-effort)")

                resumed = await _ct.wait_for_resume(session_id, timeout_s=1800.0)
                if resumed:
                    logger.info(
                        "Cost pause: session=%s resumed after manual resume",
                        session_id,
                    )
                else:
                    logger.warning(
                        "Cost pause: session=%s timed out after 30 min — continuing",
                        session_id,
                    )
        except Exception:
            logger.debug(
                "cost_pause check failed session=%s round=%d — continuing",
                session_id, round_num, exc_info=True,
            )

    # ------------------------------------------------------------------
    # Phase 1B: Temporal activation helpers
    # ------------------------------------------------------------------

    def _load_activity_profiles(self, session_id: str) -> None:
        """Load activity profiles JSON for a session into memory cache.

        Reads ``data/sessions/{session_id}/activity_profiles.json``.
        Silently skips if the file does not exist (backward compatible).
        """
        json_path = _PROJECT_ROOT / "data" / "sessions" / session_id / "activity_profiles.json"
        if not json_path.is_file():
            return
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            self._activity_profiles[session_id] = raw
            self._activation_rngs[session_id] = random.Random(session_id)
            logger.info(
                "Loaded activity profiles for %d agents (session %s)",
                len(raw),
                session_id,
            )
        except Exception:
            logger.warning(
                "Failed to load activity_profiles.json for session %s",
                session_id,
                exc_info=True,
            )

    def _is_agent_active(
        self,
        session_id: str,
        username: str,
        round_number: int,
    ) -> bool:
        """Return True if the agent is temporally active in this round.

        Falls back to True (always active) when no profile is available,
        ensuring backward compatibility with sessions created before Phase 1B.
        """
        profiles = self._activity_profiles.get(session_id)
        if not profiles:
            return True  # No profiles loaded — always active

        agent_data = profiles.get(username)
        if agent_data is None:
            return True  # Unknown agent — always active

        try:
            from backend.app.services.temporal_activation import TemporalActivationService  # noqa: PLC0415
            from backend.app.models.activity_profile import ActivityProfile  # noqa: PLC0415

            profile = ActivityProfile(
                agent_id=agent_data.get("agent_id", 0),
                chronotype=agent_data["chronotype"],
                activity_vector=tuple(agent_data["activity_vector"]),
                base_activity_rate=agent_data["base_activity_rate"],
            )
            rng = self._activation_rngs.get(session_id)
            if rng is None:
                rng = random.Random(session_id)
                self._activation_rngs[session_id] = rng

            svc = TemporalActivationService()
            return svc.should_activate(profile, round_number, rng)
        except Exception:
            logger.debug(
                "Temporal activation check failed for %s round %d",
                username,
                round_number,
            )
            return True  # Fail open

    # ------------------------------------------------------------------

    async def _handle_post_update(
        self,
        session_id: str,
        update: dict[str, Any],
    ) -> None:
        """Handle a 'post' type update: log action + accumulate for memory."""
        data = update.get("data", {})
        username = data.get("username") or data.get("oasis_username", "")
        content = data.get("content", "")
        platform = data.get("platform", "twitter")
        round_number = int(data.get("round", 0))
        post_id = str(data.get("post_id", "")) or None

        if not username or not content:
            return

        # Phase 1B: Skip logging if agent is temporally inactive this round.
        if not self._is_agent_active(session_id, username, round_number):
            logger.debug(
                "Temporal gate: skipping post from %s round %d (inactive)",
                username, round_number,
            )
            return

        # 1. Log structured action
        try:
            from backend.scripts.action_logger import ActionLogger  # noqa: PLC0415
            if self._action_logger is None:
                self._action_logger = ActionLogger()
            logged = await self._action_logger.log_post(
                session_id=session_id,
                round_number=round_number,
                oasis_username=username,
                content=content,
                platform=platform,
                post_id=post_id,
            )
            # Enrich WS broadcast data with sentiment from the logged action
            data["sentiment"] = logged.sentiment
        except Exception:
            logger.exception("action_logger.log_post failed session=%s", session_id)

        if "timestamp" not in data:
            from datetime import datetime as _dt  # noqa: PLC0415
            data["timestamp"] = _dt.now().isoformat()

        # 2. Accumulate for memory service (batch per round)
        self._posts_buffer[session_id][round_number][username].append(content)

    async def _handle_action_update(
        self,
        session_id: str,
        update: dict[str, Any],
    ) -> None:
        """Handle an 'action' type update: log non-content actions.

        Routes follow/unfollow events to social_network for relationship
        tracking, and logs all action types to simulation_actions for
        action diversity analytics.
        """
        data = update.get("data", {})
        username = data.get("username", "")
        action_type = data.get("action_type", "")
        platform = data.get("platform", "twitter")
        round_number = int(data.get("round", 0))
        info = data.get("info", {})

        if not username or not action_type:
            return

        # Phase 1B: passive DO_NOTHING always passes (no cost to log passivity);
        # other non-content actions are gated by temporal activation.
        if action_type != "do_nothing" and not self._is_agent_active(
            session_id, username, round_number
        ):
            logger.debug(
                "Temporal gate: skipping action %s from %s round %d (inactive)",
                action_type, username, round_number,
            )
            return

        # Extract target username from info payload (for follow/unfollow/like)
        target_username = None
        if isinstance(info, dict):
            target_username = info.get("user_name") or info.get("target_user")

        # 1. Log the action to simulation_actions
        try:
            from backend.scripts.action_logger import ActionLogger  # noqa: PLC0415
            if self._action_logger is None:
                self._action_logger = ActionLogger()
            await self._action_logger.log_action(
                session_id=session_id,
                round_number=round_number,
                oasis_username=username,
                action_type=action_type,
                platform=platform,
                target_agent_username=target_username,
                info=info,
            )
        except Exception:
            logger.exception(
                "action_logger.log_action failed session=%s action=%s",
                session_id, action_type,
            )

        # 2. Route graph-affecting actions to social_network service
        _graph_actions = {"follow", "unfollow", "mute", "unmute"}
        if action_type in _graph_actions and target_username:
            try:
                await self._process_graph_action(
                    session_id, username, target_username, action_type, round_number,
                )
            except Exception:
                logger.exception(
                    "graph action routing failed session=%s action=%s",
                    session_id, action_type,
                )

    async def _process_graph_action(
        self,
        session_id: str,
        source_username: str,
        target_username: str,
        action_type: str,
        round_number: int,
    ) -> None:
        """Update agent_relationships based on follow/unfollow/mute actions."""
        from backend.app.utils.db import get_db  # noqa: PLC0415

        async with get_db() as db:
            # Resolve agent IDs from oasis_username
            cursor = await db.execute(
                "SELECT id, oasis_username FROM agent_profiles "
                "WHERE session_id = ? AND oasis_username IN (?, ?)",
                (session_id, source_username, target_username),
            )
            rows = await cursor.fetchall()

        id_map = {r[1]: r[0] for r in rows}
        source_id = id_map.get(source_username)
        target_id = id_map.get(target_username)

        if source_id is None or target_id is None:
            return

        async with get_db() as db:
            if action_type == "follow":
                await db.execute(
                    """INSERT INTO agent_relationships
                       (session_id, agent_a_id, agent_b_id, relationship_type, trust_score)
                       VALUES (?, ?, ?, 'follows', 0.1)
                       ON CONFLICT(session_id, agent_a_id, agent_b_id) DO UPDATE
                       SET trust_score = MIN(1.0, trust_score + 0.05)""",
                    (session_id, source_id, target_id),
                )
            elif action_type == "unfollow":
                await db.execute(
                    """UPDATE agent_relationships
                       SET trust_score = MAX(-1.0, trust_score - 0.15)
                       WHERE session_id = ? AND agent_a_id = ? AND agent_b_id = ?""",
                    (session_id, source_id, target_id),
                )
            elif action_type == "mute":
                await db.execute(
                    """INSERT INTO agent_relationships
                       (session_id, agent_a_id, agent_b_id, relationship_type, trust_score)
                       VALUES (?, ?, ?, 'muted', -0.5)
                       ON CONFLICT(session_id, agent_a_id, agent_b_id) DO UPDATE
                       SET relationship_type = 'muted', trust_score = MAX(-1.0, trust_score - 0.3)""",
                    (session_id, source_id, target_id),
                )
            elif action_type == "unmute":
                await db.execute(
                    """UPDATE agent_relationships
                       SET relationship_type = 'follows',
                           trust_score = MIN(0.0, trust_score + 0.2)
                       WHERE session_id = ? AND agent_a_id = ? AND agent_b_id = ?""",
                    (session_id, source_id, target_id),
                )
            await db.commit()

    # ------------------------------------------------------------------
    # Stochastic activation
    # ------------------------------------------------------------------

    def get_active_agents_for_round(
        self,
        session_id: str,
        round_num: int,
        all_agents: list[dict[str, Any]],
        seed: int | None = None,
    ) -> list[dict[str, Any]]:
        """Stochastic activation: each agent independently activated by activity_level.

        Stakeholders have a floor of 0.8 to ensure they participate most rounds.
        When *seed* is provided, activation is deterministic for the given
        (seed, round_num) pair — enabling reproducible simulation runs.
        """
        rng = _random.Random(f"{seed}_{round_num}" if seed is not None else None)
        active: list[dict[str, Any]] = []
        for agent in all_agents:
            level = agent.get("activity_level", 0.5)
            if agent.get("is_stakeholder"):
                level = max(level, 0.8)  # stakeholder floor
            if rng.random() < level:
                active.append(agent)
        return active
