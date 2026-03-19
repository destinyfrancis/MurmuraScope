"""Seed text intelligent preprocessing service.

Performs a single DeepSeek chat_json call to extract entities, timeline,
stakeholders, sentiment, and scenario suggestions from user-provided seed text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.utils.llm_client import LLMClient, get_agent_provider_model
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_seed_text
from backend.prompts.text_processor_prompts import (
    ANALYZE_SEED_SYSTEM,
    ANALYZE_SEED_USER,
    SUGGEST_AGENTS_SYSTEM,
    SUGGEST_AGENTS_USER,
)

logger = get_logger("text_processor")

_VALID_SCENARIOS = frozenset([
    "property", "emigration", "fertility", "career",
    "education", "b2b", "macro",
])

_VALID_ENTITY_TYPES = frozenset([
    "person", "org", "location", "policy", "economic", "event",
])

_VALID_SENTIMENTS = frozenset(["positive", "negative", "neutral", "mixed"])

_HK_DISTRICTS = frozenset([
    "中西區", "灣仔", "東區", "南區", "油尖旺", "深水埗",
    "九龍城", "黃大仙", "觀塘", "葵青", "荃灣", "屯門",
    "元朗", "北區", "大埔", "沙田", "西貢", "離島",
])


@dataclass(frozen=True)
class SeedEntity:
    """Immutable entity extracted from seed text."""

    name: str
    type: str
    relevance: float = 1.0


@dataclass(frozen=True)
class TimelineEvent:
    """Immutable timeline event extracted from seed text."""

    date_hint: str
    event: str


@dataclass(frozen=True)
class Stakeholder:
    """Immutable stakeholder group affected by the seed event."""

    group: str
    impact: str
    description: str


@dataclass(frozen=True)
class ProcessedSeed:
    """Immutable result of seed text analysis."""

    language: str
    entities: tuple[SeedEntity, ...]
    timeline: tuple[TimelineEvent, ...]
    stakeholders: tuple[Stakeholder, ...]
    sentiment: str
    key_claims: tuple[str, ...]
    suggested_scenario: str
    suggested_districts: tuple[str, ...]
    confidence: float

    def to_summary(self) -> str:
        """Return a short text summary of the analysis."""
        entity_names = ", ".join(e.name for e in self.entities[:5])
        claims = "; ".join(self.key_claims[:3])
        return (
            f"情景：{self.suggested_scenario} | "
            f"情感：{self.sentiment} | "
            f"關鍵實體：{entity_names} | "
            f"核心論點：{claims}"
        )


def _validate_scenario(raw: str) -> str:
    if raw in _VALID_SCENARIOS:
        return raw
    return "property"


def _validate_sentiment(raw: str) -> str:
    if raw in _VALID_SENTIMENTS:
        return raw
    return "neutral"


def _validate_districts(raw: list) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(d for d in raw if d in _HK_DISTRICTS)[:6]


def _parse_processed_seed(data: dict) -> ProcessedSeed:
    """Parse raw LLM JSON into a ProcessedSeed dataclass."""
    entities = tuple(
        SeedEntity(
            name=str(e.get("name", "")),
            type=e.get("type", "event") if e.get("type") in _VALID_ENTITY_TYPES else "event",
            relevance=float(e.get("relevance", 1.0)),
        )
        for e in (data.get("entities") or [])[:10]
        if e.get("name")
    )
    timeline = tuple(
        TimelineEvent(
            date_hint=str(t.get("date_hint", "")),
            event=str(t.get("event", "")),
        )
        for t in (data.get("timeline") or [])[:5]
        if t.get("event")
    )
    stakeholders = tuple(
        Stakeholder(
            group=str(s.get("group", "")),
            impact=str(s.get("impact", "中性")),
            description=str(s.get("description", "")),
        )
        for s in (data.get("stakeholders") or [])[:6]
        if s.get("group")
    )
    key_claims = tuple(
        str(c) for c in (data.get("key_claims") or [])[:5] if c
    )

    return ProcessedSeed(
        language=str(data.get("language", "zh-HK")),
        entities=entities,
        timeline=timeline,
        stakeholders=stakeholders,
        sentiment=_validate_sentiment(data.get("sentiment", "neutral")),
        key_claims=key_claims,
        suggested_scenario=_validate_scenario(data.get("suggested_scenario", "property")),
        suggested_districts=_validate_districts(data.get("suggested_districts", [])),
        confidence=float(min(1.0, max(0.0, data.get("confidence", 0.7)))),
    )


class TextProcessor:
    """Analyzes seed text and extracts structured scenario information."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def process(self, seed_text: str) -> ProcessedSeed:
        """Analyze seed text with a single DeepSeek chat_json call.

        Args:
            seed_text: Raw user-provided seed text (news article, policy doc, etc.).

        Returns:
            Immutable ProcessedSeed with extracted entities, timeline, etc.

        Raises:
            ValueError: If seed_text is empty.
        """
        if not seed_text or not seed_text.strip():
            raise ValueError("seed_text cannot be empty")

        truncated = sanitize_seed_text(seed_text[:3000])

        messages = [
            {"role": "system", "content": ANALYZE_SEED_SYSTEM},
            {"role": "user", "content": ANALYZE_SEED_USER.format(seed_text=truncated)},
        ]

        try:
            data = await self._llm.chat_json(
                messages,
                provider=get_agent_provider_model()[0],
                temperature=0.3,
                max_tokens=4096,
            )
            return _parse_processed_seed(data)
        except Exception:
            logger.exception("TextProcessor.process failed, returning fallback")
            # Return a minimal fallback rather than crashing
            return ProcessedSeed(
                language="zh-HK",
                entities=(),
                timeline=(),
                stakeholders=(),
                sentiment="neutral",
                key_claims=(seed_text[:100],),
                suggested_scenario="property",
                suggested_districts=(),
                confidence=0.1,
            )

    async def suggest_agents(self, seed: ProcessedSeed) -> list[dict]:
        """Suggest agent role distribution based on processed seed analysis.

        Args:
            seed: ProcessedSeed from process().

        Returns:
            List of agent suggestion dicts with agent_type, proportion, etc.
        """
        stakeholders_text = "; ".join(
            f"{s.group}（{s.impact}）" for s in seed.stakeholders
        )
        districts_text = ", ".join(seed.suggested_districts) or "全港"

        messages = [
            {"role": "system", "content": SUGGEST_AGENTS_SYSTEM},
            {
                "role": "user",
                "content": SUGGEST_AGENTS_USER.format(
                    summary=seed.to_summary(),
                    scenario=seed.suggested_scenario,
                    stakeholders=stakeholders_text,
                    districts=districts_text,
                ),
            },
        ]

        try:
            data = await self._llm.chat_json(
                messages,
                provider=get_agent_provider_model()[0],
                temperature=0.5,
                max_tokens=1024,
            )
            return data.get("agent_suggestions", [])
        except Exception:
            logger.exception("suggest_agents failed")
            return []
