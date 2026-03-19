"""API endpoints for domain pack discovery, generation, and persistence."""

from __future__ import annotations

import json
import uuid
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

# Import triggers pack registration
import backend.app.domain.hk_city  # noqa: F401
import backend.app.domain.us_markets  # noqa: F401
import backend.app.domain.global_macro  # noqa: F401
import backend.app.domain.public_narrative  # noqa: F401
import backend.app.domain.real_estate  # noqa: F401
import backend.app.domain.company_competitor  # noqa: F401
import backend.app.domain.community_movement  # noqa: F401

from backend.app.domain.base import DomainPackRegistry
from backend.app.models.domain import DraftDomainPack
from backend.app.services.domain_generator import DomainGenerator
from backend.app.utils.db import get_db
from backend.app.utils.llm_client import LLMClient

router = APIRouter(prefix="/domain-packs", tags=["domain"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class GeneratePackRequest(BaseModel):
    """Request body for LLM-based domain pack generation."""

    model_config = ConfigDict(frozen=True)

    description: str
    provider: str = "openrouter"


class SavePackRequest(BaseModel):
    """Request body for persisting a custom domain pack to the database."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str = ""
    regions: list[str]
    occupations: list[str]
    income_brackets: list[str]
    shocks: list[str]
    metrics: list[str]
    persona_template: str
    sentiment_keywords: list[str]
    locale: str = "en-US"
    source: str = "user_edited"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _draft_pack_to_dict(pack: DraftDomainPack) -> dict[str, Any]:
    """Serialise a DraftDomainPack to a plain dict for JSON responses."""
    return {
        "id": pack.id,
        "name": pack.name,
        "description": pack.description,
        "regions": list(pack.regions),
        "occupations": list(pack.occupations),
        "income_brackets": list(pack.income_brackets),
        "shocks": list(pack.shocks),
        "metrics": list(pack.metrics),
        "persona_template": pack.persona_template,
        "sentiment_keywords": list(pack.sentiment_keywords),
        "locale": pack.locale,
        "source": pack.source,
    }


# ---------------------------------------------------------------------------
# Builtin pack endpoints (existing)
# ---------------------------------------------------------------------------

@router.get("")
async def list_domain_packs() -> dict:
    """Return all registered domain packs (id + name).

    Includes both builtin packs from the DomainPackRegistry and custom
    packs saved to the database.
    """
    packs = []
    for pack_id in DomainPackRegistry.list_packs():
        pack = DomainPackRegistry.get(pack_id)
        packs.append({
            "id": pack.id,
            "name_zh": pack.name_zh,
            "name_en": pack.name_en,
            "locale": pack.locale,
            "shock_count": len(pack.valid_shock_types),
            "metric_count": len(pack.metrics),
            "source": "builtin",
        })

    # Include custom packs from DB
    try:
        async with get_db() as db:
            rows = await db.execute_fetchall(
                "SELECT id, name, locale, shocks, metrics FROM custom_domain_packs ORDER BY created_at DESC"
            )
        for row in rows:
            shocks = json.loads(row[3]) if row[3] else []
            metrics = json.loads(row[4]) if row[4] else []
            packs.append({
                "id": row[0],
                "name_zh": row[1],
                "name_en": row[1],
                "locale": row[2],
                "shock_count": len(shocks),
                "metric_count": len(metrics),
                "source": "custom",
            })
    except Exception:
        # DB table may not exist yet on first boot; silently skip
        pass

    return {"packs": packs}


@router.get("/{pack_id}")
async def get_domain_pack(pack_id: str) -> dict:
    """Return full details for a specific domain pack.

    Checks the builtin registry first, then the custom_domain_packs DB table.
    """
    # Try builtin registry first
    try:
        pack = DomainPackRegistry.get(pack_id)
    except KeyError:
        pack = None

    if pack is not None:
        demographics_summary: dict | None = None
        if pack.demographics is not None:
            d = pack.demographics
            demographics_summary = {
                "currency_code": d.currency_code,
                "currency_symbol": d.currency_symbol,
                "region_count": len(d.regions),
                "occupation_count": len(d.occupations),
                "regions": list(d.regions.keys()),
                "occupations": list(d.occupations.keys()),
            }

        return {
            "id": pack.id,
            "name_zh": pack.name_zh,
            "name_en": pack.name_en,
            "locale": pack.locale,
            "shock_types": [
                {"id": s.id, "label_zh": s.label_zh, "label_en": s.label_en}
                for s in pack.shock_specs
            ],
            "metrics": [
                {"name": m.name, "db_category": m.db_category, "seasonal_period": m.seasonal_period}
                for m in pack.metrics
            ],
            "mc_default_metrics": list(pack.mc_default_metrics),
            "correlated_vars": list(pack.correlated_vars),
            "scenarios": list(pack.scenarios),
            "demographics": demographics_summary,
            "macro_fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "default_value": f.default_value,
                    "unit": f.unit,
                }
                for f in pack.macro_fields
            ],
        }

    # Fall back to custom DB packs
    try:
        async with get_db() as db:
            row = await db.execute_fetchall(
                "SELECT id, name, description, regions, occupations, income_brackets, "
                "shocks, metrics, persona_template, sentiment_keywords, locale, source "
                "FROM custom_domain_packs WHERE id = ?",
                (pack_id,),
            )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Domain pack '{pack_id}' not found") from exc

    if not row:
        raise HTTPException(status_code=404, detail=f"Domain pack '{pack_id}' not found")

    r = row[0]
    return {
        "id": r[0],
        "name": r[1],
        "description": r[2],
        "regions": json.loads(r[3] or "[]"),
        "occupations": json.loads(r[4] or "[]"),
        "income_brackets": json.loads(r[5] or "[]"),
        "shocks": json.loads(r[6] or "[]"),
        "metrics": json.loads(r[7] or "[]"),
        "persona_template": r[8] or "",
        "sentiment_keywords": json.loads(r[9] or "[]"),
        "locale": r[10] or "en-US",
        "source": r[11] or "user_edited",
    }


# ---------------------------------------------------------------------------
# Generation endpoint (Task 10)
# ---------------------------------------------------------------------------

@router.post("/generate")
async def generate_domain_pack(req: GeneratePackRequest) -> dict:
    """Generate a domain pack from a natural language description via LLM.

    Uses DomainGenerator which makes up to 2 LLM calls with automatic retry.
    The generated pack is NOT automatically saved — call POST /save to persist.

    Returns the generated DraftDomainPack as JSON.
    """
    if not req.description.strip():
        raise HTTPException(status_code=422, detail="description must not be empty")

    try:
        llm = LLMClient()
        # Wrap to honour the provider preference from the request
        class _ProviderLLM:
            def __init__(self, client: LLMClient, provider: str) -> None:
                self._c = client
                self._p = provider

            async def chat_json(self, messages: list[dict]) -> dict:
                return await self._c.chat_json(messages, provider=self._p)

        gen = DomainGenerator(llm_client=_ProviderLLM(llm, req.provider))
        pack = await gen.generate(req.description)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Validation error") from exc
    except Exception as exc:
        logger.error("Domain generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Domain generation failed. Please try again.") from exc

    return {"pack": _draft_pack_to_dict(pack)}


# ---------------------------------------------------------------------------
# Save endpoint (Task 10)
# ---------------------------------------------------------------------------

@router.post("/save")
async def save_custom_domain_pack(req: SavePackRequest) -> dict:
    """Persist a custom domain pack to the database.

    Validates the pack fields via DraftDomainPack before saving.
    If a pack with the same id already exists, it is replaced (UPSERT).

    Returns the saved pack id and a confirmation flag.
    """
    # Validate via model — raises 422 on constraint violations
    try:
        validated = DraftDomainPack(
            id=req.id,
            name=req.name,
            description=req.description,
            regions=req.regions,
            occupations=req.occupations,
            income_brackets=req.income_brackets,
            shocks=req.shocks,
            metrics=req.metrics,
            persona_template=req.persona_template,
            sentiment_keywords=req.sentiment_keywords,
            locale=req.locale,
            source=req.source,  # type: ignore[arg-type]
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Validation error") from exc

    try:
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO custom_domain_packs
                  (id, name, description, regions, occupations, income_brackets,
                   shocks, metrics, persona_template, sentiment_keywords, locale, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  description=excluded.description,
                  regions=excluded.regions,
                  occupations=excluded.occupations,
                  income_brackets=excluded.income_brackets,
                  shocks=excluded.shocks,
                  metrics=excluded.metrics,
                  persona_template=excluded.persona_template,
                  sentiment_keywords=excluded.sentiment_keywords,
                  locale=excluded.locale,
                  source=excluded.source,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (
                    validated.id,
                    validated.name,
                    validated.description,
                    json.dumps(list(validated.regions)),
                    json.dumps(list(validated.occupations)),
                    json.dumps(list(validated.income_brackets)),
                    json.dumps(list(validated.shocks)),
                    json.dumps(list(validated.metrics)),
                    validated.persona_template,
                    json.dumps(list(validated.sentiment_keywords)),
                    validated.locale,
                    validated.source,
                ),
            )
            await db.commit()
    except Exception as exc:
        logger.error("Failed to save custom domain pack '%s': %s", req.id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save domain pack to database") from exc

    return {"saved": True, "id": validated.id}
