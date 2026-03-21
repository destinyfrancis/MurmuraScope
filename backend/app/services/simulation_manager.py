"""Session lifecycle state machine for MurmuraScope simulations.

Manages simulation sessions through their lifecycle:
  created → running → completed | failed

Uses aiosqlite via get_db() for persistence and immutable SessionState
dataclasses for all state transitions.

DB schema reference (backend/database/schema.sql):
  simulation_sessions columns:
    id, name, sim_mode, seed_text, scenario_type, graph_id,
    agent_count, round_count, llm_provider, llm_model,
    macro_scenario_id, oasis_db_path, status, total_tokens,
    estimated_cost_usd, started_at, completed_at, created_at
  agent_profiles columns:
    id, session_id, agent_type, age, sex, district, occupation,
    income_bracket, education_level, marital_status, housing_type,
    openness, conscientiousness, extraversion, agreeableness, neuroticism,
    monthly_income, savings, oasis_persona, oasis_username, created_at
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.models.project import (
    CostEstimate,
    SessionState,
    SessionStatus,
    SimMode,
)
from backend.app.services.simulation_runner import SimulationRunner
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("simulation_manager")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Module-level singleton — prevents duplicate SimulationRunner instances across
# concurrent API requests.  Access via get_simulation_manager().
_MANAGER_SINGLETON: "SimulationManager | None" = None

# Module-level per-session start locks — shared across ALL SimulationManager
# instances so concurrent POST /simulation/start requests for the same session
# are serialised even when each handler creates a fresh SimulationManager().
_SESSION_START_LOCKS: dict[str, asyncio.Lock] = {}

_VALID_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CREATED: {SessionStatus.RUNNING, SessionStatus.FAILED},
    SessionStatus.RUNNING: {SessionStatus.COMPLETED, SessionStatus.FAILED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.FAILED: set(),
}


class SimulationManager:
    """Session lifecycle: created → running → completed | failed."""

    def __init__(self, runner: SimulationRunner | None = None) -> None:
        self._runner = runner or SimulationRunner()
        self._session_tasks: dict[str, asyncio.Task] = {}

    async def create_session(
        self,
        request: dict[str, Any],
        csv_path: str | None = None,
    ) -> dict[str, Any]:
        """Create a new simulation session.

        1. Build SessionState from request parameters.
        2. Calculate cost estimate.
        3. Persist session record to simulation_sessions table.
        4. Persist agent profiles to agent_profiles table (if csv_path given).
        5. Return session info with cost estimate.

        Args:
            request: Dict with keys matching SimulationCreateRequest fields.
            csv_path: Absolute path to the generated agents CSV file.

        Returns:
            Dict with session_id, agent_count, round_count, status,
            estimated_cost_usd, csv_path.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        graph_id = request.get("graph_id")
        if not graph_id:
            raise ValueError("graph_id is required")

        scenario_type = request.get("scenario_type", "property")
        agent_count = request.get("agent_count", 300)
        round_count = request.get("round_count", 40)

        if agent_count < 1:
            raise ValueError("agent_count must be at least 1")
        if round_count < 1:
            raise ValueError("round_count must be at least 1")

        sim_mode = _infer_sim_mode(scenario_type)

        session = SessionState.create(
            name=f"{scenario_type}_{agent_count}agents",
            sim_mode=sim_mode,
            agent_count=agent_count,
            round_count=round_count,
            graph_id=graph_id,
            scenario_type=scenario_type,
            platforms=request.get("platforms", {"twitter": True, "reddit": True}),
            llm_provider=request.get("llm_provider") or os.environ.get("AGENT_LLM_PROVIDER") or os.environ.get("LLM_PROVIDER", "openrouter"),
        )

        # Derive stable paths for this session.
        session_dir = _PROJECT_ROOT / "data" / "sessions" / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        oasis_db_path = str(session_dir / "oasis.db")
        effective_csv_path = csv_path or str(session_dir / "agents.csv")

        await _persist_session(session, request, oasis_db_path, effective_csv_path)

        # BYOK: store user-provided API key if present
        user_api_key = request.get("api_key")
        if user_api_key:
            try:
                from backend.app.services.session_key_store import SessionKeyStore  # noqa: PLC0415
                key_store = SessionKeyStore()
                await key_store.store_key(
                    session_id=session.id,
                    api_key=user_api_key,
                    provider=request.get("llm_provider") or os.environ.get("AGENT_LLM_PROVIDER", "google"),
                    model=request.get("llm_model", ""),
                    base_url=request.get("llm_base_url", ""),
                )
            except Exception:
                logger.warning(
                    "Failed to store BYOK key for session %s", session.id,
                    exc_info=True,
                )

        logger.info(
            "Created session %s: %d agents, %d rounds, est $%.4f",
            session.id,
            session.agent_count,
            session.round_count,
            session.cost_estimate.total_estimated_usd if session.cost_estimate else 0,
        )

        return {
            "session_id": session.id,
            "agent_count": session.agent_count,
            "round_count": session.round_count,
            "status": session.status.value,
            "estimated_cost_usd": (
                session.cost_estimate.total_estimated_usd
                if session.cost_estimate
                else 0.0
            ),
            "csv_path": effective_csv_path,
        }

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Get session status and metadata.

        Args:
            session_id: UUID of the session.

        Returns:
            Dict with session details.

        Raises:
            ValueError: If session not found.
        """
        session = await _load_session(session_id)
        return _session_to_dict(session)

    async def start_session(self, session_id: str) -> None:
        """Start simulation via SimulationRunner in a background task.

        Validates state transition (created → running), updates DB status
        to running, then launches the runner asynchronously so the HTTP
        response returns immediately.

        A per-session asyncio.Lock serialises concurrent calls so two
        simultaneous POST /simulation/start requests for the same session
        cannot both pass the idempotency check and spawn duplicate runners.

        Args:
            session_id: UUID of the session to start.

        Raises:
            ValueError: If session not found or invalid state transition.
        """
        if session_id not in _SESSION_START_LOCKS:
            _SESSION_START_LOCKS[session_id] = asyncio.Lock()

        async with _SESSION_START_LOCKS[session_id]:
            session = await _load_session(session_id)

            # Idempotent: if already running, just let the client reconnect via WS
            if session.status == SessionStatus.RUNNING:
                logger.info("Session %s already running — skipping restart", session_id)
                return

            _validate_transition(session.status, SessionStatus.RUNNING)

            updated = session.with_status(SessionStatus.RUNNING)
            await _update_session_status(updated, started_at=datetime.utcnow().isoformat())

            config = await _build_runner_config(session)

            logger.info("Starting session %s in background", session_id)

            async def _run_and_finalize() -> None:
                async def on_progress(update: dict[str, Any]) -> None:
                    data = update.get("data", update)
                    current_round = data.get("round", 0)
                    if current_round:
                        await _update_session_round(session_id, current_round)

                try:
                    await self._runner.run(
                        session_id=session_id,
                        config=config,
                        progress_callback=on_progress,
                    )
                    completed = updated.with_status(SessionStatus.COMPLETED)
                    await _update_session_status(
                        completed,
                        completed_at=datetime.utcnow().isoformat(),
                    )
                    logger.info("Session %s completed", session_id)
                except Exception as exc:
                    failed = updated.with_status(
                        SessionStatus.FAILED, error_message=str(exc)
                    )
                    await _update_session_status(failed)
                    logger.error("Session %s failed: %s", session_id, exc)

                    # Push an error event so WebSocket clients know it failed.
                    try:
                        from backend.app.api.ws import push_progress  # noqa: PLC0415
                        await push_progress(
                            session_id,
                            {"type": "error", "data": {"message": str(exc)}},
                        )
                    except Exception:
                        logger.warning(
                            "Failed to push error event for session %s",
                            session_id,
                            exc_info=True,
                        )
                finally:
                    # Release buffered progress memory to prevent unbounded growth.
                    try:
                        from backend.app.api.ws import clear_progress  # noqa: PLC0415
                        clear_progress(session_id)
                    except Exception:
                        logger.warning(
                            "Failed to clear progress for session %s",
                            session_id,
                            exc_info=True,
                        )

            def _on_task_done(task: asyncio.Task) -> None:
                self._session_tasks.pop(session_id, None)
                if task.cancelled():
                    logger.info("Session %s task was cancelled", session_id)
                elif task.exception():
                    logger.error(
                        "Session %s task raised unhandled exception: %s",
                        session_id,
                        task.exception(),
                        exc_info=task.exception(),
                    )

            task = asyncio.create_task(_run_and_finalize(), name=f"sim-{session_id}")
            self._session_tasks[session_id] = task
            task.add_done_callback(_on_task_done)

    async def stop_session(self, session_id: str) -> None:
        """Stop a running simulation.

        Args:
            session_id: UUID of the session to stop.

        Raises:
            ValueError: If session not found or not running.
        """
        session = await _load_session(session_id)
        if session.status != SessionStatus.RUNNING:
            raise ValueError(
                f"Cannot stop session in '{session.status.value}' state"
            )

        await self._runner.stop(session_id)

        stopped = session.with_status(
            SessionStatus.FAILED, error_message="Stopped by user"
        )
        await _update_session_status(stopped)
        logger.info("Session %s stopped by user", session_id)

    async def get_agents(self, session_id: str) -> list[dict[str, Any]]:
        """Get agent profiles for a session from the agent_profiles table.

        Args:
            session_id: UUID of the session.

        Returns:
            List of agent profile dicts.

        Raises:
            ValueError: If session not found.
        """
        await _load_session(session_id)  # validate session exists

        async with get_db() as db:
            cursor = await db.execute(
                """SELECT id, session_id, agent_type, age, sex, district,
                          occupation, income_bracket, education_level,
                          marital_status, housing_type,
                          openness, conscientiousness, extraversion,
                          agreeableness, neuroticism,
                          monthly_income, savings,
                          oasis_username, oasis_persona,
                          COALESCE(political_stance, 0.5) AS political_stance,
                          COALESCE(tier, 2) AS tier
                   FROM agent_profiles
                   WHERE session_id = ?
                   ORDER BY id""",
                (session_id,),
            )
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]


def get_simulation_manager() -> "SimulationManager":
    """Return the process-wide SimulationManager singleton.

    Using a singleton ensures all API handlers share the same SimulationRunner,
    preventing duplicate simulation spawns from concurrent requests.
    """
    global _MANAGER_SINGLETON
    if _MANAGER_SINGLETON is None:
        _MANAGER_SINGLETON = SimulationManager()
    return _MANAGER_SINGLETON


async def generate_agents(
    session_id: str,
    request: dict[str, Any],
    mode: str = "hk_demographic",
    llm_client: Any | None = None,
) -> tuple[list[Any], str]:
    """Generate agent profiles and write the OASIS CSV file.

    Dispatches to the appropriate factory based on *mode*:

    - ``"hk_demographic"`` → :class:`AgentFactory` (default, backward compatible).
    - ``"kg_driven"`` → :class:`KGAgentFactory` which derives agents from the
      knowledge graph nodes and seed text.

    Args:
        session_id: UUID of the owning session (used to resolve the session dir).
        request: The original create-session request dict.  Must contain at
            minimum ``agent_count`` and, for kg_driven mode, ``graph_id`` and
            ``seed_text``.
        mode: Simulation mode string.  Defaults to ``"hk_demographic"``.
        llm_client: Optional LLMClient override (injected for testing).

    Returns:
        A ``(profiles, csv_path)`` tuple where *profiles* is the list of
        generated agent profile objects and *csv_path* is the absolute path
        to the written CSV file.

    Raises:
        ValueError: If required request fields are missing for the chosen mode.
        RuntimeError: If agent generation or CSV writing fails.
    """
    session_dir = _PROJECT_ROOT / "data" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    csv_path = str(session_dir / "agents.csv")

    if mode == "kg_driven":
        graph_id = request.get("graph_id", "")
        seed_text = request.get("seed_text", "")
        if not graph_id:
            raise ValueError("graph_id is required for kg_driven mode")
        if not seed_text:
            raise ValueError("seed_text is required for kg_driven mode")

        try:
            from backend.app.services.kg_agent_factory import KGAgentFactory  # noqa: PLC0415
            from backend.app.utils.llm_client import LLMClient  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "KGAgentFactory not available — ensure kg_agent_factory module exists"
            ) from exc

        llm = llm_client or LLMClient()

        # Load KG nodes/edges from the database.
        # kg_nodes.session_id stores the session_id passed to build_graph(),
        # which may differ from graph_id (format: graph_{session_id}_{hex}).
        # Extract the original session_id to query correctly.
        from backend.app.services.graph_builder import _session_id_from_graph_id  # noqa: PLC0415
        kg_session_id = _session_id_from_graph_id(graph_id)

        kg_nodes: list[dict[str, Any]] = []
        kg_edges: list[dict[str, Any]] = []
        try:
            from backend.app.utils.db import get_db  # noqa: PLC0415
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT id, entity_type, title, description, properties "
                    "FROM kg_nodes WHERE session_id = ?",
                    (kg_session_id,),
                )
                kg_nodes = [dict(row) for row in await cursor.fetchall()]
                cursor = await db.execute(
                    "SELECT source_id, target_id, relation_type, description, weight "
                    "FROM kg_edges WHERE session_id = ?",
                    (kg_session_id,),
                )
                kg_edges = [dict(row) for row in await cursor.fetchall()]
        except Exception:
            logger.warning(
                "Could not load KG data for graph %s — proceeding with empty graph",
                graph_id,
                exc_info=True,
            )

        factory = await KGAgentFactory.create(graph_id=graph_id, llm_client=llm)
        profiles = await factory.generate_from_kg(kg_nodes, kg_edges, seed_text)
        written_path = factory.generate_agents_csv(profiles, csv_path)
        logger.info(
            "KGAgentFactory: generated %d profiles for session %s at %s",
            len(profiles),
            session_id,
            written_path,
        )

        # Hydrate seed memories (best-effort, never blocks simulation start)
        try:
            from backend.app.services.memory_initialization import MemoryInitializationService  # noqa: PLC0415
            mem_svc = MemoryInitializationService()
            agents = [(p.id, p.entity_type) for p in profiles]
            hydration = await mem_svc.hydrate_session_bulk(
                session_id=session_id,
                graph_id=graph_id,
                agents=agents,
            )
            logger.info(
                "Seed memory hydration for session %s: %d injected, %d skipped, %d templates",
                session_id,
                hydration.total_injected,
                hydration.agents_skipped,
                hydration.templates_found,
            )
        except Exception:
            logger.exception(
                "Seed memory hydration failed for session %s — continuing without initial memories",
                session_id,
            )

        return profiles, written_path

    # Default path: hk_demographic via AgentFactory.
    from backend.app.services.agent_factory import AgentFactory  # noqa: PLC0415

    agent_count = request.get("agent_count", 300)
    distribution = request.get("agent_distribution") or {}

    demographics = None
    domain_pack_id = request.get("domain_pack_id", "hk_city")
    try:
        from backend.app.domain.base import DomainPackRegistry  # noqa: PLC0415
        pack = DomainPackRegistry.get(domain_pack_id)
        demographics = pack.demographics
    except Exception:
        logger.debug(
            "Domain pack '%s' unavailable — using AgentFactory defaults",
            domain_pack_id,
        )

    factory = AgentFactory(demographics=demographics)
    profiles = factory.generate_population(agent_count, distribution or None)

    from backend.app.services.profile_generator import ProfileGenerator  # noqa: PLC0415
    from backend.app.services.macro_controller import MacroController  # noqa: PLC0415
    import asyncio as _asyncio  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415

    profile_gen = ProfileGenerator(agent_factory=factory)
    macro = MacroController()
    macro_state = await macro.get_baseline_for_scenario(
        request.get("scenario_type", "property")
    )
    csv_content = profile_gen.to_oasis_csv(profiles, macro_state)
    await _asyncio.to_thread(_Path(csv_path).write_text, csv_content, encoding="utf-8")
    logger.info(
        "AgentFactory: wrote %d agents to %s for session %s",
        len(profiles),
        csv_path,
        session_id,
    )
    return profiles, csv_path


async def store_agent_profiles(
    session_id: str,
    profiles: list[Any],
    profile_generator: Any,
    macro_state: Any | None = None,
) -> None:
    """Persist AgentProfile objects to the agent_profiles table.

    Args:
        session_id: UUID of the owning session.
        profiles: List of AgentProfile (from agent_factory) instances.
        profile_generator: ProfileGenerator instance for persona/username.
        macro_state: Optional MacroState for persona enrichment.
    """
    now = datetime.utcnow().isoformat()
    rows = []
    for profile in profiles:
        username = profile_generator._factory.generate_username(profile)
        persona = profile_generator.to_persona_string(profile, macro_state)
        # Note: id is excluded — let SQLite AUTOINCREMENT assign a globally
        # unique id so that multiple sessions (each starting agent IDs at 1)
        # do not conflict on the PRIMARY KEY.
        rows.append((
            session_id,
            profile.agent_type,
            profile.age,
            profile.sex,
            profile.district,
            profile.occupation,
            profile.income_bracket,
            profile.education_level,
            profile.marital_status,
            profile.housing_type,
            profile.openness,
            profile.conscientiousness,
            profile.extraversion,
            profile.agreeableness,
            profile.neuroticism,
            profile.monthly_income,
            profile.savings,
            persona,
            username,
            now,
        ))

    async with get_db() as db:
        await db.executemany(
            """INSERT INTO agent_profiles
               (session_id, agent_type, age, sex, district,
                occupation, income_bracket, education_level,
                marital_status, housing_type,
                openness, conscientiousness, extraversion,
                agreeableness, neuroticism,
                monthly_income, savings,
                oasis_persona, oasis_username, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await db.commit()

    logger.info(
        "Stored %d agent profiles for session %s", len(rows), session_id
    )


async def store_universal_agent_profiles(
    session_id: str,
    profiles: list[Any],
) -> None:
    """Persist UniversalAgentProfile objects to agent_profiles table.

    Adapts universal fields to the HK-schema columns:
    - age=0, sex="N/A", district=entity_type, occupation=role
    - income_bracket/education_level/marital_status/housing_type = "N/A"
    - monthly_income=0, savings=0
    - oasis_persona = persona, oasis_username = to_oasis_row()["username"]
    """
    import hashlib  # noqa: F811, PLC0415

    now = datetime.utcnow().isoformat()
    rows = []
    for p in profiles:
        oasis_row = p.to_oasis_row()
        rows.append((
            session_id,
            p.entity_type,          # agent_type
            0,                      # age (N/A for universal)
            "N/A",                  # sex
            p.entity_type,          # district → entity_type
            p.role,                 # occupation → role
            "N/A",                  # income_bracket
            "N/A",                  # education_level
            "N/A",                  # marital_status
            "N/A",                  # housing_type
            p.openness,
            p.conscientiousness,
            p.extraversion,
            p.agreeableness,
            p.neuroticism,
            0,                      # monthly_income
            0,                      # savings
            p.persona,              # oasis_persona
            oasis_row["username"],  # oasis_username
            now,
        ))

    async with get_db() as db:
        await db.executemany(
            """INSERT INTO agent_profiles
               (session_id, agent_type, age, sex, district,
                occupation, income_bracket, education_level,
                marital_status, housing_type,
                openness, conscientiousness, extraversion,
                agreeableness, neuroticism,
                monthly_income, savings,
                oasis_persona, oasis_username, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await db.commit()

    logger.info(
        "Stored %d universal agent profiles for session %s", len(rows), session_id
    )


async def store_activity_profiles(
    session_id: str,
    profiles: list[Any],
    session_dir: "Path",
    factory: Any,
) -> None:
    """Generate and persist 24-dim temporal activity profiles.

    Writes a JSON file at ``{session_dir}/activity_profiles.json``
    mapping ``oasis_username → {chronotype, activity_vector, base_activity_rate}``.
    Also stores ``chronotype`` and ``activity_vector`` (JSON array) in
    ``agent_profiles`` via a runtime ALTER TABLE (idempotent).

    Args:
        session_id: Owning session UUID.
        profiles:   List of AgentProfile (from AgentFactory).
        session_dir: Path object pointing to ``data/sessions/{session_id}/``.
        factory:    AgentFactory instance (for ``generate_username``).
    """
    from pathlib import Path  # noqa: PLC0415
    import random as _random  # noqa: PLC0415

    from backend.app.services.temporal_activation import TemporalActivationService  # noqa: PLC0415

    activation = TemporalActivationService()
    rng = _random.Random(session_id)  # deterministic, reproducible

    profile_map: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        username = factory.generate_username(profile)
        act_profile = activation.generate_profile(
            agent_id=profile.id,
            age=profile.age,
            occupation=profile.occupation,
            rng=rng,
        )
        profile_map[username] = {
            "agent_id": profile.id,
            "chronotype": act_profile.chronotype,
            "activity_vector": list(act_profile.activity_vector),
            "base_activity_rate": act_profile.base_activity_rate,
        }

    # Write JSON file (primary storage for subprocess / runner use).
    Path(session_dir).mkdir(parents=True, exist_ok=True)
    json_path = Path(session_dir) / "activity_profiles.json"
    json_path.write_text(
        json.dumps(profile_map, ensure_ascii=False, indent=None),
        encoding="utf-8",
    )
    logger.info(
        "Wrote activity profiles for %d agents to %s", len(profile_map), json_path
    )

    # Persist chronotype + activity_vector columns into agent_profiles (runtime migration).
    try:
        async with get_db() as db:
            # Idempotent ALTER TABLE — fail silently if columns already exist.
            for col_def in (
                "ALTER TABLE agent_profiles ADD COLUMN chronotype TEXT",
                "ALTER TABLE agent_profiles ADD COLUMN activity_vector TEXT",
            ):
                try:
                    await db.execute(col_def)
                except Exception:
                    pass  # Column already exists

            # Update rows for this session using the username lookup.
            rows = []
            for username, ap in profile_map.items():
                rows.append((
                    ap["chronotype"],
                    json.dumps(ap["activity_vector"]),
                    session_id,
                    username,
                ))
            await db.executemany(
                "UPDATE agent_profiles "
                "SET chronotype = ?, activity_vector = ? "
                "WHERE session_id = ? AND oasis_username = ?",
                rows,
            )
            await db.commit()
    except Exception:
        logger.warning(
            "Could not persist activity profiles to DB for session %s",
            session_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _infer_sim_mode(scenario_type: str) -> SimMode:
    """Map scenario_type string to SimMode enum."""
    mapping: dict[str, SimMode] = {
        "property": SimMode.LIFE_DECISION,
        "emigration": SimMode.LIFE_DECISION,
        "fertility": SimMode.LIFE_DECISION,
        "career": SimMode.LIFE_DECISION,
        "education": SimMode.LIFE_DECISION,
        "b2b": SimMode.B2B_CAMPAIGN,
        "macro": SimMode.MACRO_OPINION,
        "kg_driven": SimMode.KG_DRIVEN,
    }
    return mapping.get(scenario_type, SimMode.LIFE_DECISION)


def _validate_transition(current: SessionStatus, target: SessionStatus) -> None:
    """Validate that a state transition is allowed.

    Raises:
        ValueError: If transition is not valid.
    """
    allowed = _VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"Invalid transition: {current.value} → {target.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )


async def _persist_session(
    session: SessionState,
    request: dict[str, Any],
    oasis_db_path: str,
    csv_path: str,
) -> None:
    """Insert a new session record into simulation_sessions table.

    Stores:
    - All required NOT NULL columns (seed_text, llm_model, oasis_db_path).
    - The full request JSON in a dedicated column so start_session can
      recover shocks, family_members, crm_data, and the CSV path.
    - estimated_cost_usd from the SessionState cost estimate.
    """
    llm_model = request.get(
        "llm_model", "deepseek/deepseek-v3.2"
    )
    seed_text = request.get("seed_text", session.scenario_type)

    # Embed csv_path in the request blob so _build_runner_config can read it.
    enriched_request = {**request, "agent_csv_path": csv_path}

    domain_pack_id = request.get("domain_pack_id", "hk_city")

    async with get_db() as db:
        await db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, seed_text, scenario_type, graph_id,
                agent_count, round_count, llm_provider, llm_model,
                macro_scenario_id, oasis_db_path, status,
                estimated_cost_usd, config_json, created_at, domain_pack_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.id,
                session.name,
                session.sim_mode.value,
                seed_text,
                session.scenario_type,
                session.graph_id,
                session.agent_count,
                session.round_count,
                session.llm_provider,
                llm_model,
                request.get("macro_scenario_id"),
                oasis_db_path,
                session.status.value,
                (
                    session.cost_estimate.total_estimated_usd
                    if session.cost_estimate
                    else 0.0
                ),
                json.dumps(enriched_request, ensure_ascii=False),
                session.created_at,
                domain_pack_id,
            ),
        )
        await db.commit()


async def _load_session(session_id: str) -> SessionState:
    """Load a session from DB and return as immutable SessionState.

    Raises:
        ValueError: If session not found.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM simulation_sessions WHERE id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise ValueError(f"Session not found: {session_id}")

    row_keys = row.keys()

    # Reconstruct cost estimate from estimated_cost_usd if present.
    estimated_cost = row["estimated_cost_usd"] if "estimated_cost_usd" in row_keys else 0.0
    cost: CostEstimate | None = None
    if estimated_cost:
        cost = CostEstimate.calculate(
            agent_count=row["agent_count"],
            round_count=row["round_count"],
        )

    platforms_raw = row["platforms"] if "platforms" in row_keys else None
    platforms: dict[str, bool] = (
        json.loads(platforms_raw)
        if platforms_raw
        else {"twitter": True, "reddit": False}
    )

    created_at = row["created_at"] if "created_at" in row_keys else datetime.utcnow().isoformat()

    return SessionState(
        id=row["id"],
        name=row["name"],
        sim_mode=SimMode(row["sim_mode"]),
        status=SessionStatus(row["status"]),
        agent_count=row["agent_count"],
        round_count=row["round_count"],
        current_round=row["current_round"] if "current_round" in row_keys else 0,
        graph_id=row["graph_id"] or "",
        scenario_type=row["scenario_type"] or "",
        platforms=platforms,
        llm_provider=row["llm_provider"],
        cost_estimate=cost,
        created_at=created_at,
        updated_at=row["started_at"] or created_at if "started_at" in row_keys else created_at,
        error_message=row["error_message"] if "error_message" in row_keys else None,
    )


async def _update_session_status(
    session: SessionState,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> None:
    """Update session status (and optional timestamps) in DB."""
    now = datetime.utcnow().isoformat()

    if session.status == SessionStatus.RUNNING:
        async with get_db() as db:
            await db.execute(
                """UPDATE simulation_sessions
                   SET status = ?, started_at = COALESCE(started_at, ?)
                   WHERE id = ?""",
                (session.status.value, started_at or now, session.id),
            )
            await db.commit()
    elif session.status == SessionStatus.COMPLETED:
        async with get_db() as db:
            await db.execute(
                """UPDATE simulation_sessions
                   SET status = ?, completed_at = ?
                   WHERE id = ?""",
                (session.status.value, completed_at or now, session.id),
            )
            await db.commit()
    elif session.status == SessionStatus.FAILED:
        try:
            async with get_db() as db:
                await db.execute(
                    """UPDATE simulation_sessions
                       SET status = ?, error_message = ?
                       WHERE id = ?""",
                    (session.status.value, session.error_message or "", session.id),
                )
                await db.commit()
        except Exception:
            logger.exception("Failed to update session status for %s", session.id)
    else:
        async with get_db() as db:
            await db.execute(
                "UPDATE simulation_sessions SET status = ? WHERE id = ?",
                (session.status.value, session.id),
            )
            await db.commit()


async def _update_session_round(session_id: str, current_round: int) -> None:
    """Update current_round for a running session.

    Note: The schema does not have a current_round column, so this is a
    no-op unless the column is added.  It is safe to call; it will silently
    pass if the column doesn't exist.
    """
    try:
        async with get_db() as db:
            await db.execute(
                "UPDATE simulation_sessions SET current_round = ? WHERE id = ?",
                (current_round, session_id),
            )
            await db.commit()
    except Exception as e:
        logger.debug("_update_session_round failed (column may not exist): %s", e)


async def _build_runner_config(session: SessionState) -> dict[str, Any]:
    """Build the configuration dict for SimulationRunner.

    Reads the original request JSON from DB (stored during create_session)
    to recover the agent_csv_path, shocks, and other per-session parameters.
    Injects LLM credentials from the environment.
    """
    config_json: str | None = None
    oasis_db_path: str = ""
    llm_model: str = "deepseek/deepseek-v3.2"

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT config_json, oasis_db_path, llm_model FROM simulation_sessions WHERE id = ?",
            (session.id,),
        )
        row = await cursor.fetchone()
        if row:
            config_json = row["config_json"]
            oasis_db_path = row["oasis_db_path"] or ""
            llm_model = row["llm_model"] or llm_model

    original_request = json.loads(config_json) if config_json else {}

    # Check BYOK key store first, then fall back to env vars
    provider = session.llm_provider or "openrouter"
    api_key = ""
    base_url = ""

    try:
        from backend.app.services.session_key_store import SessionKeyStore  # noqa: PLC0415
        key_store = SessionKeyStore()
        key_info = await key_store.retrieve_key(session.id)
        if key_info is not None:
            api_key = key_info.api_key
            if key_info.provider:
                provider = key_info.provider
            if key_info.model:
                llm_model = key_info.model
            if key_info.base_url:
                base_url = key_info.base_url
            logger.info("Using BYOK key for session %s", session.id)
    except Exception:
        logger.debug("BYOK key lookup skipped for session %s", session.id)

    # Fall back to env vars if no BYOK key
    if not api_key:
        if provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
        elif provider == "fireworks":
            api_key = os.environ.get("FIREWORKS_API_KEY", "")
        else:
            from backend.app.utils.llm_client import _PROVIDERS  # noqa: PLC0415
            env_key = _PROVIDERS.get(provider, {}).get("env_key", "")
            api_key = os.environ.get(env_key, "") if env_key else ""

    if not base_url:
        if provider == "openrouter":
            base_url = "https://openrouter.ai/api/v1"
        elif provider == "fireworks":
            base_url = "https://api.fireworks.ai/inference/v1"
        else:
            from backend.app.utils.llm_client import _PROVIDERS  # noqa: PLC0415
            base_url = _PROVIDERS.get(provider, {}).get("base_url", "")

    if not llm_model or llm_model in ("accounts/fireworks/models/deepseek/deepseek-v3.2", "deepseek/deepseek-v3.2"):
        # Use AGENT_LLM_MODEL env var if set, else default for the provider
        agent_model_env = os.environ.get("AGENT_LLM_MODEL", "")
        llm_model = agent_model_env or "deepseek/deepseek-v3.2"

    return {
        "session_id": session.id,
        "graph_id": session.graph_id,
        "scenario_type": session.scenario_type,
        "sim_mode": session.sim_mode.value,
        "agent_count": session.agent_count,
        "round_count": session.round_count,
        "platforms": session.platforms,
        "llm_provider": provider,
        "llm_model": llm_model,
        "llm_api_key": api_key,
        "llm_base_url": base_url,
        "oasis_db_path": oasis_db_path,
        "agent_csv_path": original_request.get("agent_csv_path", ""),
        "shocks": original_request.get("shocks", []),
        "family_members": original_request.get("family_members"),
        "crm_data": original_request.get("crm_data"),
        "macro_scenario_id": original_request.get("macro_scenario_id"),
        "agent_distribution": original_request.get("agent_distribution"),
    }


def _session_to_dict(session: SessionState) -> dict[str, Any]:
    """Convert SessionState to a serialisable dict."""
    return {
        "id": session.id,
        "name": session.name,
        "sim_mode": session.sim_mode.value,
        "status": session.status.value,
        "agent_count": session.agent_count,
        "round_count": session.round_count,
        "current_round": session.current_round,
        "graph_id": session.graph_id,
        "scenario_type": session.scenario_type,
        "platforms": session.platforms,
        "llm_provider": session.llm_provider,
        "estimated_cost_usd": (
            session.cost_estimate.total_estimated_usd
            if session.cost_estimate
            else 0.0
        ),
        "error_message": session.error_message,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }
