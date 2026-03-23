"""Load persona profiles from CSV/JSON and inject them as KG nodes.

Profiles uploaded by researchers become kg_nodes with source="persona_upload"
stored in the properties JSON column, allowing KGAgentFactory to pick them up
as pre-seeded agents in Step 2.

Note: kg_nodes table uses 'session_id' for the graph identifier and 'title'
for the node label — these column names must match schema.sql exactly.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import TYPE_CHECKING

from backend.app.models.persona_profile import PersonaProfile
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger("persona_loader")

_MAX_PROFILES: int = 500
_NODE_ID_PREFIX: str = "persona"


def _slug(text: str) -> str:
    """Convert text to a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower().strip()).strip("_")[:40]


def _parse_csv(content: bytes) -> list[PersonaProfile]:
    """Parse CSV bytes into PersonaProfile list."""
    # Handle BOM
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    profiles: list[PersonaProfile] = []
    for i, row in enumerate(reader):
        if i >= _MAX_PROFILES:
            logger.warning("CSV has >%d rows; extra rows ignored", _MAX_PROFILES)
            break
        try:
            age_raw = row.get("age", "").strip()
            age = int(age_raw) if age_raw else None
            stance_raw = row.get("political_stance", "").strip()
            stance = float(stance_raw) if stance_raw else None
            profiles.append(
                PersonaProfile(
                    name=row.get("name", "").strip(),
                    role=row.get("role", "").strip(),
                    age=age,
                    occupation=row.get("occupation") or None,
                    beliefs=row.get("beliefs") or None,
                    goals=row.get("goals") or None,
                    political_stance=stance,
                    background=row.get("background") or None,
                )
            )
        except Exception as exc:
            logger.warning("Skipping CSV row %d: %s", i + 1, exc)
    return profiles


def _parse_json(content: bytes) -> list[PersonaProfile]:
    """Parse JSON bytes (array of objects) into PersonaProfile list."""
    data = json.loads(content.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("JSON must be an array of objects")
    profiles: list[PersonaProfile] = []
    for i, item in enumerate(data[:_MAX_PROFILES]):
        try:
            profiles.append(PersonaProfile.model_validate(item))
        except Exception as exc:
            logger.warning("Skipping JSON item %d: %s", i, exc)
    return profiles


def load_profiles(content: bytes, filename: str) -> list[PersonaProfile]:
    """Auto-detect CSV or JSON by filename extension and parse."""
    if filename.lower().endswith(".csv"):
        return _parse_csv(content)
    return _parse_json(content)


async def inject_as_kg_nodes(graph_id: str, profiles: list[PersonaProfile]) -> int:
    """Insert profiles as kg_nodes with source="persona_upload" in properties JSON.

    Uses INSERT OR IGNORE for idempotency. Returns count of rows attempted.

    Note: kg_nodes schema uses 'session_id' for the graph FK and 'title' for
    the display name — both are used correctly here.
    """
    if not profiles:
        return 0

    graph_prefix = graph_id.replace("-", "")[:8]
    inserted = 0

    async with get_db() as db:
        for profile in profiles:
            node_id = f"{graph_prefix}_{_NODE_ID_PREFIX}_{_slug(profile.name)}"
            properties: dict = {
                "source": "persona_upload",
            }
            if profile.age is not None:
                properties["age"] = profile.age
            if profile.occupation is not None:
                properties["occupation"] = profile.occupation
            if profile.beliefs is not None:
                properties["beliefs"] = profile.beliefs
            if profile.goals is not None:
                properties["goals"] = profile.goals
            if profile.political_stance is not None:
                properties["political_stance"] = profile.political_stance
            if profile.personality_traits is not None:
                properties["personality_traits"] = profile.personality_traits
            if profile.background is not None:
                properties["background"] = profile.background

            description_parts = [profile.role]
            if profile.beliefs:
                description_parts.append(profile.beliefs)
            if profile.background:
                description_parts.append(profile.background)
            description = ": ".join(description_parts)

            await db.execute(
                """
                INSERT OR IGNORE INTO kg_nodes
                  (id, session_id, entity_type, title, description, properties)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    graph_id,
                    profile.role,
                    profile.name,
                    description,
                    json.dumps(properties, ensure_ascii=False),
                ),
            )
            inserted += 1
        await db.commit()

    logger.info("Injected %d persona nodes into graph %s", inserted, graph_id)
    return inserted
