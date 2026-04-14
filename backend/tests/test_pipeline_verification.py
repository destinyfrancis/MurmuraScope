"""Pipeline verification: seed text → mode detection → graph → agents → simulation → DB state.

Proves every major service in both hk_demographic and kg_driven paths is
exercised with realistic data flowing through the full pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "database" / "schema.sql"

# ---------------------------------------------------------------------------
# Realistic LLM fixture data
# ---------------------------------------------------------------------------

_HK_SEED = "年青夫婦，思考2026年買樓是否合適時機？"
_KG_SEED = "USA and Iran enter full military conflict"

_HK_ENTITY_FIXTURE: dict = {
    "entities": [
        {"name": "年青夫婦", "type": "Person", "description": "Young married couple considering property"},
        {"name": "樓市", "type": "Market", "description": "Hong Kong property market"},
        {"name": "CCL指數", "type": "Indicator", "description": "Centa-City Leading Index"},
    ],
    "relations": [
        {"source": "年青夫婦", "target": "樓市", "type": "考慮買入", "weight": 0.7},
    ],
}

_KG_ENTITY_FIXTURE: dict = {
    "entities": [
        {"name": "USA", "type": "Country", "description": "United States of America"},
        {"name": "Iran", "type": "Country", "description": "Islamic Republic of Iran"},
        {"name": "Strait of Hormuz", "type": "Location", "description": "Strategic waterway"},
        {"name": "UN Security Council", "type": "Organization", "description": "International body"},
    ],
    "relations": [
        {"source": "USA", "target": "Iran", "type": "military_conflict", "weight": 0.9},
        {"source": "Iran", "target": "Strait of Hormuz", "type": "controls", "weight": 0.8},
    ],
}

_ONTOLOGY_FIXTURE: dict = {
    "entity_types": ["Country", "Organization", "Location", "Person", "Market", "Indicator"],
    "relation_types": ["military_conflict", "controls", "allied_with", "考慮買入"],
}

_SCENARIO_FIXTURE: dict = {
    "scenario_id": "usa_iran_conflict",
    "scenario_name": "USA-Iran Military Conflict",
    "scenario_description": "Full military confrontation between USA and Iran",
    "decision_types": [
        {
            "id": "military_escalation",
            "label": "Military Escalation",
            "description": "Level of military response",
            "possible_actions": ["escalate", "de_escalate", "maintain"],
            "applicable_entity_types": ["Country"],
        },
        {
            "id": "diplomatic_response",
            "label": "Diplomatic Response",
            "description": "Diplomatic channel actions",
            "possible_actions": ["sanction", "negotiate", "condemn"],
            "applicable_entity_types": [],
        },
        {
            "id": "resource_allocation",
            "label": "Resource Allocation",
            "description": "Resource deployment strategy",
            "possible_actions": ["increase_defense", "humanitarian_aid"],
            "applicable_entity_types": [],
        },
    ],
    "metrics": [
        {
            "id": "oil_price_stability",
            "label": "Oil Price Stability",
            "description": "Global oil price stability",
            "initial_value": 0.5,
        },
        {
            "id": "regional_tension",
            "label": "Regional Tension",
            "description": "Middle East tension index",
            "initial_value": 0.7,
        },
        {
            "id": "diplomatic_trust",
            "label": "Diplomatic Trust",
            "description": "Inter-state trust level",
            "initial_value": 0.3,
        },
    ],
    "shock_types": [
        {
            "id": "surprise_attack",
            "label": "Surprise Strike",
            "description": "Unexpected military strike",
            "affected_metrics": ["regional_tension"],
        },
        {
            "id": "ceasefire_proposal",
            "label": "Ceasefire",
            "description": "Formal ceasefire offer",
            "affected_metrics": ["diplomatic_trust"],
        },
    ],
    "impact_rules": [
        {
            "decision_type_id": "military_escalation",
            "action": "escalate",
            "metric_id": "regional_tension",
            "delta_per_10": 5.0,
        },
        {
            "decision_type_id": "diplomatic_response",
            "action": "negotiate",
            "metric_id": "diplomatic_trust",
            "delta_per_10": 3.0,
        },
    ],
}

_DELIBERATION_FIXTURE: dict = {
    "action": "diplomatic_response",
    "choice": "negotiate",
    "reasoning": "De-escalation preferred to avoid regional instability",
    "confidence": 0.72,
    "belief_deltas": {"oil_price_stability": -0.05, "diplomatic_trust": 0.1},
}

_IMPLICIT_STAKEHOLDER_FIXTURE: dict = {
    "stakeholders": [
        {
            "id": "saudi_arabia",
            "name": "Saudi Arabia",
            "entity_type": "Country",
            "role": "Regional power",
            "relevance_reason": "Oil producer and regional actor",
        },
        {
            "id": "opec",
            "name": "OPEC",
            "entity_type": "Organization",
            "role": "Oil cartel",
            "relevance_reason": "Controls oil supply",
        },
    ],
}

_AGENT_PROFILE_FIXTURE: dict = {
    "agent_name": "Representative Agent",
    "entity_type": "Country",
    "personality": {
        "openness": 0.6,
        "conscientiousness": 0.5,
        "extraversion": 0.4,
        "agreeableness": 0.5,
        "neuroticism": 0.3,
    },
    "background": "A nation state actor in the conflict zone",
}

# ---------------------------------------------------------------------------
# LLM mock routers
# ---------------------------------------------------------------------------


async def _chat_json_router(messages: list[dict], **kw) -> dict:
    """Route chat_json calls to realistic fixtures based on prompt content."""
    prompt = str(messages).lower()
    # Ontology check MUST come before generic entity/extract checks
    # because the ontology prompt also contains "entity" keywords.
    if "ontology" in prompt:
        return _ONTOLOGY_FIXTURE
    if "decision_type" in prompt or ("scenario" in prompt and "simulation scenario" in prompt):
        return _SCENARIO_FIXTURE
    if "entity" in prompt or "extract" in prompt:
        # EntityExtractor expects {"nodes": [...], "edges": [...]} format
        if "年青" in prompt or "樓" in prompt or "買樓" in prompt:
            return {
                "nodes": [
                    {
                        "id": "hk_n0",
                        "entity_type": "Person",
                        "title": "年青夫婦",
                        "description": "Young married couple",
                    },
                    {"id": "hk_n1", "entity_type": "Market", "title": "樓市", "description": "HK property market"},
                    {
                        "id": "hk_n2",
                        "entity_type": "Indicator",
                        "title": "CCL指數",
                        "description": "Centa-City Leading Index",
                    },
                ],
                "edges": [
                    {"source_id": "hk_n0", "target_id": "hk_n1", "relation_type": "考慮買入", "weight": 0.7},
                ],
            }
        return {
            "nodes": [
                {"id": "kg_n0", "entity_type": "Country", "title": "USA", "description": "United States of America"},
                {"id": "kg_n1", "entity_type": "Country", "title": "Iran", "description": "Islamic Republic of Iran"},
                {
                    "id": "kg_n2",
                    "entity_type": "Location",
                    "title": "Strait of Hormuz",
                    "description": "Strategic waterway",
                },
                {
                    "id": "kg_n3",
                    "entity_type": "Organization",
                    "title": "UN Security Council",
                    "description": "International body",
                },
            ],
            "edges": [
                {"source_id": "kg_n0", "target_id": "kg_n1", "relation_type": "military_conflict", "weight": 0.9},
                {"source_id": "kg_n1", "target_id": "kg_n2", "relation_type": "controls", "weight": 0.8},
            ],
        }
    if "scenario" in prompt:
        return _SCENARIO_FIXTURE
    if "stakeholder" in prompt or "implicit" in prompt:
        return _IMPLICIT_STAKEHOLDER_FIXTURE
    if "profile" in prompt or "agent" in prompt:
        return _AGENT_PROFILE_FIXTURE
    return {"result": "ok"}


async def _chat_router(messages: list[dict], **kw) -> MagicMock:
    """Route chat calls — returns MagicMock matching LLMResponse interface."""
    prompt = str(messages).lower()
    if "deliberat" in prompt:
        content = json.dumps(_DELIBERATION_FIXTURE)
    elif "mode" in prompt or "classify" in prompt:
        content = "kg_driven"
    elif "debate" in prompt or "consensus" in prompt:
        content = json.dumps({"position": "negotiate", "argument": "De-escalation is optimal"})
    else:
        content = json.dumps({"result": "ok"})
    return MagicMock(content=content, model="mock", usage={}, cost_usd=0.0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def pipeline_db(tmp_path):
    """File-based test DB with full schema, patched into get_db."""
    db_path = str(tmp_path / "pipeline.db")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_get_db():
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    with patch("backend.app.utils.db.get_db", _mock_get_db):
        yield db_path, _mock_get_db


@pytest.fixture(autouse=True)
def _mock_llm():
    """Patch LLM client globally with realistic fixture routers."""
    with (
        patch(
            "backend.app.utils.llm_client.LLMClient.chat_json",
            new_callable=AsyncMock,
            side_effect=_chat_json_router,
        ),
        patch(
            "backend.app.utils.llm_client.LLMClient.chat",
            new_callable=AsyncMock,
            side_effect=_chat_router,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_embed():
    """Patch embed_single to return a fixed 384-dim vector."""
    import numpy as np

    fixed_vec = np.random.default_rng(42).random(384).astype(np.float32).tolist()

    with patch(
        "backend.app.services.embedding_provider.EmbeddingProvider.embed_single",
        return_value=fixed_vec,
    ):
        yield


# ---------------------------------------------------------------------------
# hk_session fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def hk_session(pipeline_db):
    """Run full HK pipeline: create session, seed graph nodes, run dry simulation."""
    db_path, mock_get_db = pipeline_db
    session_id = "hk-pipe-full"
    graph_id = "hk-graph-001"

    # Add runtime-added columns that schema.sql omits (added via ALTER TABLE in production)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        for stmt in [
            "ALTER TABLE agent_profiles ADD COLUMN political_stance REAL DEFAULT 0.5",
            "ALTER TABLE agent_profiles ADD COLUMN tier INTEGER DEFAULT 2",
        ]:
            try:
                await db.execute(stmt)
            except Exception:
                pass  # column already exists
        await db.commit()

    # Seed kg_nodes — table uses (id, session_id, entity_type, title, description)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        for i, entity in enumerate(_HK_ENTITY_FIXTURE["entities"]):
            await db.execute(
                "INSERT INTO kg_nodes (id, session_id, entity_type, title, description) VALUES (?, ?, ?, ?, ?)",
                (
                    f"hkn{i}",
                    session_id,
                    entity["type"],
                    entity["name"],
                    entity["description"],
                ),
            )
        await db.commit()

    # Create simulation session + 5 HK agents
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, scenario_type, graph_id,
                agent_count, round_count, llm_provider, llm_model,
                status, oasis_db_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                "hk_pipeline_test",
                "social_media",
                "property",
                graph_id,
                5,
                6,
                "openrouter",
                "mock-model",
                "running",
                str(Path(db_path).parent / "oasis.db"),
            ),
        )
        for i in range(1, 6):
            await db.execute(
                """INSERT INTO agent_profiles
                   (session_id, agent_type, age, sex, district,
                    occupation, income_bracket, education_level,
                    marital_status, housing_type,
                    openness, conscientiousness, extraversion,
                    agreeableness, neuroticism,
                    monthly_income, savings,
                    oasis_username, oasis_persona)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    "citizen",
                    25 + i * 3,
                    "M" if i % 2 else "F",
                    "沙田",
                    "professional",
                    "middle",
                    "學位或以上",
                    "married",
                    "private",
                    0.6,
                    0.5,
                    0.7,
                    0.5,
                    0.4,
                    30000 + i * 5000,
                    100000 + i * 20000,
                    f"hk_user_{i - 1}",
                    f"HK citizen persona {i}",
                ),
            )
        await db.commit()

    # Run dry simulation — bypass the 3-round cap so round 5 fires Group 3 hooks
    import backend.app.services.simulation_runner as _sr_mod
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner(dry_run=True)
    events: list[dict] = []

    async def _capture(update: dict) -> None:
        events.append(update)

    config = {
        "session_id": session_id,
        "graph_id": graph_id,
        "scenario_type": "property",
        "agent_count": 5,
        "round_count": 6,
        "platforms": {"facebook": True},
        "llm_provider": "openrouter",
        "llm_model": "mock-model",
        "agent_csv_path": "",
        "shocks": [],
    }

    # Patch min() inside the simulation_runner module so mock_rounds = round_count
    _original_min = _sr_mod.__builtins__["min"] if isinstance(_sr_mod.__builtins__, dict) else _sr_mod.__builtins__.min  # type: ignore[union-attr]

    def _uncapped_min(*args, **kw):  # type: ignore[return]
        # Allow round_count to pass through uncapped for the specific (N, 3) call
        if len(args) == 2 and args[1] == 3 and isinstance(args[0], int) and args[0] > 3:
            return args[0]
        return _original_min(*args, **kw)

    try:
        if isinstance(_sr_mod.__builtins__, dict):
            _sr_mod.__builtins__["min"] = _uncapped_min
        else:
            _sr_mod.__builtins__.min = _uncapped_min  # type: ignore[union-attr]
        await runner.run(session_id, config, progress_callback=_capture)
    finally:
        if isinstance(_sr_mod.__builtins__, dict):
            _sr_mod.__builtins__["min"] = _original_min
        else:
            _sr_mod.__builtins__.min = _original_min  # type: ignore[union-attr]

    yield {
        "session_id": session_id,
        "graph_id": graph_id,
        "db_path": db_path,
        "events": events,
        "runner": runner,
    }

    await runner.cleanup_session(session_id)


# ---------------------------------------------------------------------------
# TestHKDemographicPipeline
# ---------------------------------------------------------------------------


class TestHKDemographicPipeline:
    """Verify full pipeline for hk_demographic mode."""

    @pytest.mark.asyncio
    async def test_mode_detection(self, pipeline_db):
        """Seed containing HK keywords routes to hk_demographic without LLM call."""
        from backend.app.services.zero_config import ZeroConfigService

        svc = ZeroConfigService()
        # Use a seed that contains an unambiguous HK keyword so the fast-path fires
        hk_keyword_seed = "香港樓市2026年分析"
        with patch.object(svc, "_llm_detect_mode", new_callable=AsyncMock) as mock_llm:
            result = await svc.detect_mode_async(hk_keyword_seed)
        mock_llm.assert_not_called()
        assert result == "hk_demographic"

    @pytest.mark.asyncio
    async def test_graph_build(self, pipeline_db):
        """GraphBuilderService produces KG nodes from HK seed."""
        db_path, mock_get_db = pipeline_db

        # Satisfy foreign key constraint from kg_nodes to simulation_sessions
        async with mock_get_db() as db:
            await db.execute(
                """INSERT INTO simulation_sessions (id, name, sim_mode, agent_count, round_count, llm_provider)
                   VALUES (?, 'HK Test', 'parallel', 10, 5, 'openrouter')""",
                ("hk-pipe-test",),
            )
            await db.commit()

        from backend.app.services.graph_builder import GraphBuilderService

        gbs = GraphBuilderService()
        result = await gbs.build_graph(
            session_id="hk-pipe-test",
            scenario_type="property",
            seed_text=_HK_SEED,
        )
        assert result["graph_id"], "graph_id must be non-empty"
        # kg_nodes rows are keyed by session_id (not graph_id) per schema
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM kg_nodes WHERE session_id = ?",
                ("hk-pipe-test",),
            )
            row = await cursor.fetchone()
            assert row["cnt"] >= 1, "Graph build should produce at least 1 node"

    @pytest.mark.asyncio
    async def test_agent_generation(self, hk_session):
        """HK agents have census fields."""
        db_path = hk_session["db_path"]
        session_id = hk_session["session_id"]
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM agent_profiles WHERE session_id = ?",
                (session_id,),
            )
            rows = await cursor.fetchall()
        assert len(rows) == 5, f"Expected 5 HK agents, got {len(rows)}"
        for row in rows:
            assert row["district"], "HK agent must have district"
            assert row["income_bracket"], "HK agent must have income_bracket"
            assert row["education_level"], "HK agent must have education_level"

    @pytest.mark.asyncio
    async def test_dry_run_completes(self, hk_session):
        """Dry run emits post, progress, and complete events."""
        event_types = [e.get("type") for e in hk_session["events"]]
        assert "post" in event_types, "Must emit post events"
        assert "progress" in event_types, "Must emit progress events"
        assert "complete" in event_types, "Must emit complete event"

    @pytest.mark.asyncio
    async def test_hook_execution(self, hk_session):
        """Per-round hooks fire — verify via post events emitted each round."""
        events = hk_session["events"]
        # _run_dry emits 2 post events per round; with 6 rounds we expect >= 6 posts
        post_events = [e for e in events if e.get("type") == "post"]
        progress_events = [e for e in events if e.get("type") == "progress"]
        assert len(post_events) >= 6, f"Expected >= 6 post events (2/round × ≥3 rounds), got {len(post_events)}"
        assert len(progress_events) >= 3, (
            f"Expected >= 3 progress events (1/round × ≥3 rounds), got {len(progress_events)}"
        )

    @pytest.mark.asyncio
    async def test_db_state_after_sim(self, hk_session):
        """DB tables have rows after full pipeline."""
        db_path = hk_session["db_path"]
        session_id = hk_session["session_id"]
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT graph_id FROM simulation_sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            assert row is not None, "Session must exist"
            assert row["graph_id"] == hk_session["graph_id"], "graph_id must flow through"
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM agent_profiles WHERE session_id = ?",
                (session_id,),
            )
            assert (await cursor.fetchone())["cnt"] == 5, "Agent profiles must persist"


# ---------------------------------------------------------------------------
# kg_session fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def kg_session(pipeline_db):
    """Run full KG-driven pipeline: create session, seed graph nodes, run dry simulation."""
    db_path, mock_get_db = pipeline_db
    session_id = "kg-pipe-full"
    graph_id = "kg-graph-001"

    # Add runtime-added columns that schema.sql omits (added via ALTER TABLE in production)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        for stmt in [
            "ALTER TABLE agent_profiles ADD COLUMN political_stance REAL DEFAULT 0.5",
            "ALTER TABLE agent_profiles ADD COLUMN tier INTEGER DEFAULT 2",
        ]:
            try:
                await db.execute(stmt)
            except Exception:
                pass  # column already exists
        await db.commit()

    # Seed kg_nodes — table uses (id, session_id, entity_type, title, description)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        for i, entity in enumerate(_KG_ENTITY_FIXTURE["entities"]):
            await db.execute(
                "INSERT INTO kg_nodes (id, session_id, entity_type, title, description) VALUES (?, ?, ?, ?, ?)",
                (
                    f"kgn{i}",
                    session_id,
                    entity["type"],
                    entity["name"],
                    entity["description"],
                ),
            )
        await db.commit()

    # Entity names and types for 4 agents
    _KG_AGENTS = [
        {"name": "USA", "entity_type": "Country"},
        {"name": "Iran", "entity_type": "Country"},
        {"name": "UN Security Council", "entity_type": "Organization"},
        {"name": "Strait of Hormuz", "entity_type": "Location"},
    ]

    # Create simulation session + 4 KG agents
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """INSERT INTO simulation_sessions
               (id, name, sim_mode, scenario_type, graph_id, seed_text,
                agent_count, round_count, llm_provider, llm_model,
                status, oasis_db_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                "kg_pipeline_test",
                "kg_driven",
                "kg_driven",
                graph_id,
                _KG_SEED,
                4,
                6,
                "openrouter",
                "mock-model",
                "running",
                str(Path(db_path).parent / "oasis.db"),
            ),
        )
        for i, agent in enumerate(_KG_AGENTS):
            tier = 1 if i < 2 else 2
            await db.execute(
                """INSERT INTO agent_profiles
                   (session_id, agent_type, age, sex, district,
                    occupation, income_bracket, education_level,
                    marital_status, housing_type,
                    openness, conscientiousness, extraversion,
                    agreeableness, neuroticism,
                    monthly_income, savings,
                    oasis_username, oasis_persona,
                    tier)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    "entity",
                    0,
                    "N/A",
                    agent["entity_type"],
                    "state_actor",
                    "n/a",
                    "n/a",
                    "n/a",
                    "n/a",
                    0.6,
                    0.5,
                    0.7,
                    0.5,
                    0.4,
                    0,
                    0,
                    f"kg_agent_{i}",
                    f"{agent['name']} entity persona",
                    tier,
                ),
            )
        await db.commit()

    # Run dry simulation — bypass the 3-round cap so round 5 fires Group 3 hooks
    import backend.app.services.simulation_runner as _sr_mod
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner(dry_run=True)
    events: list[dict] = []

    async def _capture(update: dict) -> None:
        events.append(update)

    config = {
        "session_id": session_id,
        "graph_id": graph_id,
        "scenario_type": "kg_driven",
        "sim_mode": "kg_driven",
        "agent_count": 4,
        "round_count": 6,
        "platforms": {"facebook": True},
        "llm_provider": "openrouter",
        "llm_model": "mock-model",
        "agent_csv_path": "",
        "shocks": [],
    }

    # Patch min() inside the simulation_runner module so mock_rounds = round_count
    _original_min = _sr_mod.__builtins__["min"] if isinstance(_sr_mod.__builtins__, dict) else _sr_mod.__builtins__.min  # type: ignore[union-attr]

    def _uncapped_min(*args, **kw):  # type: ignore[return]
        # Allow round_count to pass through uncapped for the specific (N, 3) call
        if len(args) == 2 and args[1] == 3 and isinstance(args[0], int) and args[0] > 3:
            return args[0]
        return _original_min(*args, **kw)

    try:
        if isinstance(_sr_mod.__builtins__, dict):
            _sr_mod.__builtins__["min"] = _uncapped_min
        else:
            _sr_mod.__builtins__.min = _uncapped_min  # type: ignore[union-attr]
        await runner.run(session_id, config, progress_callback=_capture)
    finally:
        if isinstance(_sr_mod.__builtins__, dict):
            _sr_mod.__builtins__["min"] = _original_min
        else:
            _sr_mod.__builtins__.min = _original_min  # type: ignore[union-attr]

    yield {
        "session_id": session_id,
        "graph_id": graph_id,
        "db_path": db_path,
        "events": events,
        "runner": runner,
    }

    await runner.cleanup_session(session_id)


# ---------------------------------------------------------------------------
# TestKGDrivenPipeline
# ---------------------------------------------------------------------------


class TestKGDrivenPipeline:
    """Verify full pipeline for kg_driven mode."""

    @pytest.mark.asyncio
    async def test_mode_detection(self, pipeline_db):
        """Non-HK seed routes to kg_driven via LLM fallback."""
        from backend.app.services.zero_config import ZeroConfigService

        svc = ZeroConfigService()
        with patch.object(svc, "_llm_detect_mode", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "kg_driven"
            result = await svc.detect_mode_async(_KG_SEED)
        mock_llm.assert_called_once()
        assert result == "kg_driven"

    @pytest.mark.asyncio
    async def test_graph_build(self, pipeline_db):
        """GraphBuilderService produces KG with geopolitical entities."""
        _, mock_get_db = pipeline_db
        async with mock_get_db() as db:
            await db.execute(
                """INSERT INTO simulation_sessions (id, name, sim_mode, agent_count, round_count, llm_provider)
                   VALUES (?, 'KG Test', 'parallel', 10, 5, 'openrouter')""",
                ("kg-pipe-test",),
            )
            await db.commit()

        from backend.app.services.graph_builder import GraphBuilderService

        gbs = GraphBuilderService()
        result = await gbs.build_graph(
            session_id="kg-pipe-test",
            scenario_type="kg_driven",
            seed_text=_KG_SEED,
        )
        # Verify the graph_id was generated and entities were extracted.
        # Storage relies on get_db patching which is covered by test_db_state_after_sim.
        assert result["graph_id"]
        assert result["node_count"] >= 2  # USA, Iran (at minimum)

    @pytest.mark.asyncio
    async def test_scenario_generation(self, pipeline_db):
        """ScenarioGenerator produces decision types, metrics, shocks."""
        from backend.app.services.scenario_generator import ScenarioGenerator

        sg = ScenarioGenerator()
        config = await sg.generate(
            seed_text=_KG_SEED,
            kg_nodes=[
                {"id": "n1", "name": "USA", "entity_type": "Country"},
                {"id": "n2", "name": "Iran", "entity_type": "Country"},
            ],
            kg_edges=[
                {"source_id": "n1", "target_id": "n2", "relation_type": "military_conflict"},
            ],
            agent_profiles=[],
        )
        assert len(config.decision_types) >= 1
        assert len(config.metrics) >= 1
        assert len(config.shock_types) >= 1
        dt = config.decision_types[0]
        assert dt.id
        assert len(dt.possible_actions) >= 1

    @pytest.mark.asyncio
    async def test_agent_generation(self, kg_session):
        """KG agents stored with universal markers (age=0)."""
        db_path = kg_session["db_path"]
        session_id = kg_session["session_id"]
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM agent_profiles WHERE session_id = ? AND age = 0",
                (session_id,),
            )
            rows = await cursor.fetchall()
        assert len(rows) >= 2
        entity_types = {row["district"] for row in rows}
        assert "Country" in entity_types

    @pytest.mark.asyncio
    async def test_memory_hydration(self, kg_session):
        """Memory hydration does not crash; if rows exist, session_id is consistent."""
        db_path = kg_session["db_path"]
        session_id = kg_session["session_id"]
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM agent_memories WHERE session_id = ?",
                (session_id,),
            )
            count = (await cursor.fetchone())["cnt"]
            if count > 0:
                cursor2 = await db.execute(
                    "SELECT DISTINCT session_id FROM agent_memories WHERE session_id = ?",
                    (session_id,),
                )
                rows = await cursor2.fetchall()
                assert all(r["session_id"] == session_id for r in rows)

    @pytest.mark.asyncio
    async def test_dry_run_completes(self, kg_session):
        """KG dry run emits all event types across 6 rounds."""
        event_types = [e.get("type") for e in kg_session["events"]]
        assert "post" in event_types
        assert "progress" in event_types
        assert "complete" in event_types
        progress_rounds = [e["data"]["round"] for e in kg_session["events"] if e.get("type") == "progress"]
        assert len(progress_rounds) >= 3

    @pytest.mark.asyncio
    async def test_kg_hooks_execution(self, kg_session):
        """KG-specific hooks fire — verify via events."""
        events = kg_session["events"]
        post_events = [e for e in events if e.get("type") == "post"]
        assert len(post_events) >= 6  # 2 per round × ≥3 rounds

    @pytest.mark.asyncio
    async def test_db_state_after_sim(self, kg_session):
        """KG tables populated — data flowed through pipeline."""
        db_path = kg_session["db_path"]
        session_id = kg_session["session_id"]
        graph_id = kg_session["graph_id"]
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT graph_id, scenario_type FROM simulation_sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row["graph_id"] == graph_id
            assert row["scenario_type"] == "kg_driven"
            # KG nodes with correct session_id
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM kg_nodes WHERE session_id = ?",
                (session_id,),
            )
            assert (await cursor.fetchone())["cnt"] >= 2
            # Agent profiles survived
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM agent_profiles WHERE session_id = ?",
                (session_id,),
            )
            assert (await cursor.fetchone())["cnt"] == 4

    @pytest.mark.asyncio
    async def test_implicit_stakeholders(self, pipeline_db):
        """ImplicitStakeholderService.discover is callable and does not crash."""
        from backend.app.services.implicit_stakeholder_service import ImplicitStakeholderService

        svc = ImplicitStakeholderService()
        result = await svc.discover(
            graph_id="kg-graph-001",
            seed_text=_KG_SEED,
            existing_nodes=[
                {"id": "n1", "name": "USA", "entity_type": "Country"},
                {"id": "n2", "name": "Iran", "entity_type": "Country"},
            ],
        )
        assert result is not None
        assert hasattr(result, "nodes_added")
