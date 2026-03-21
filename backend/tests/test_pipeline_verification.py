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
        {"id": "oil_price_stability", "label": "Oil Price Stability", "description": "Global oil price stability", "initial_value": 0.5},
        {"id": "regional_tension", "label": "Regional Tension", "description": "Middle East tension index", "initial_value": 0.7},
        {"id": "diplomatic_trust", "label": "Diplomatic Trust", "description": "Inter-state trust level", "initial_value": 0.3},
    ],
    "shock_types": [
        {"id": "surprise_attack", "label": "Surprise Strike", "description": "Unexpected military strike", "affected_metrics": ["regional_tension"]},
        {"id": "ceasefire_proposal", "label": "Ceasefire", "description": "Formal ceasefire offer", "affected_metrics": ["diplomatic_trust"]},
    ],
    "impact_rules": [
        {"decision_type_id": "military_escalation", "action": "escalate", "metric_id": "regional_tension", "delta_per_10": 5.0},
        {"decision_type_id": "diplomatic_response", "action": "negotiate", "metric_id": "diplomatic_trust", "delta_per_10": 3.0},
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
        {"id": "saudi_arabia", "name": "Saudi Arabia", "entity_type": "Country", "role": "Regional power", "relevance_reason": "Oil producer and regional actor"},
        {"id": "opec", "name": "OPEC", "entity_type": "Organization", "role": "Oil cartel", "relevance_reason": "Controls oil supply"},
    ],
}

_AGENT_PROFILE_FIXTURE: dict = {
    "agent_name": "Representative Agent",
    "entity_type": "Country",
    "personality": {"openness": 0.6, "conscientiousness": 0.5, "extraversion": 0.4, "agreeableness": 0.5, "neuroticism": 0.3},
    "background": "A nation state actor in the conflict zone",
}

# ---------------------------------------------------------------------------
# LLM mock routers
# ---------------------------------------------------------------------------


async def _chat_json_router(messages: list[dict], **kw) -> dict:
    """Route chat_json calls to realistic fixtures based on prompt content."""
    prompt = str(messages).lower()
    if "entity" in prompt or "extract" in prompt:
        if "年青" in prompt or "樓" in prompt or "買樓" in prompt:
            return _HK_ENTITY_FIXTURE
        return _KG_ENTITY_FIXTURE
    if "ontology" in prompt:
        return _ONTOLOGY_FIXTURE
    if "scenario" in prompt or "decision_type" in prompt:
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
        "backend.app.utils.llm_client.LLMClient.embed_single",
        return_value=fixed_vec,
    ):
        yield
