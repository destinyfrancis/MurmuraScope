# backend/app/services/world_event_generator.py
"""Per-round world event generator for kg_driven simulation mode."""
from __future__ import annotations

import uuid
from typing import Any

from backend.app.models.world_event import WorldEvent
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.prompts.world_event_prompts import WORLD_EVENT_SYSTEM, WORLD_EVENT_USER

logger = get_logger(__name__)

_MAX_EVENTS_PER_ROUND = 5


class WorldEventGenerator:
    """Generate 3-5 contextually coherent WorldEvents per simulation round.

    Active in kg_driven mode only.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def generate(
        self,
        scenario_description: str,
        round_number: int,
        active_metrics: tuple[str, ...],
        prev_dominant_stance: dict[str, float],
        event_history: list[str],  # list of previous event content strings
    ) -> list[WorldEvent]:
        """Generate world events for the current round.

        Args:
            scenario_description: Short scenario summary from seed text.
            round_number: Current simulation round (1-based).
            active_metrics: Metric IDs from UniversalScenarioConfig.
            prev_dominant_stance: Average belief values from previous round.
            event_history: Content of previously generated events (deduplication).

        Returns:
            List of WorldEvent instances. Empty list on LLM failure (never raises).
        """
        history_summary = event_history[-10:] if event_history else []
        user_content = WORLD_EVENT_USER.format(
            scenario_description=scenario_description[:400],
            round_number=round_number,
            active_metrics=list(active_metrics),
            prev_dominant_stance=prev_dominant_stance,
            event_history_summary=history_summary,
        )
        messages = [
            {"role": "system", "content": WORLD_EVENT_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        try:
            raw = await self._llm.chat_json(messages, max_tokens=2048, temperature=0.7)
        except Exception as exc:
            logger.warning("WorldEventGenerator: LLM call failed: %s", exc)
            return []

        return _parse_events(raw, round_number, active_metrics)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_events(
    raw: dict[str, Any],
    round_number: int,
    active_metrics: tuple[str, ...],
) -> list[WorldEvent]:
    events_raw = raw.get("events", [])
    if not isinstance(events_raw, list):
        return []

    result: list[WorldEvent] = []
    active_set = set(active_metrics)

    for item in events_raw[:_MAX_EVENTS_PER_ROUND]:
        if not isinstance(item, dict):
            continue
        try:
            # Filter impact_vector to only known metrics
            raw_impact = item.get("impact_vector", {})
            impact = {k: float(v) for k, v in raw_impact.items() if k in active_set}

            reach_raw = item.get("reach", ["ALL"])
            reach = tuple(str(r) for r in reach_raw) if reach_raw else ("ALL",)

            result.append(WorldEvent(
                event_id=str(item.get("event_id", uuid.uuid4().hex[:8])),
                round_number=round_number,
                content=str(item.get("content", "")),
                event_type=str(item.get("event_type", "shock")),
                reach=reach,
                impact_vector=impact,
                credibility=float(item.get("credibility", 0.8)),
            ))
        except (ValueError, TypeError) as exc:
            logger.warning("WorldEventGenerator: skipping malformed event: %s", exc)

    logger.info(
        "WorldEventGenerator: round=%d generated %d events", round_number, len(result)
    )
    return result
