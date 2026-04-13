"""Belief topic generator for KG-driven simulation.

Dynamically generates agent-specific belief topics from the Knowledge Graph
and scenario context, replacing hard-coded metric keys with scenario-aware
dimensions (e.g., "trust_in_government", "supply_chain_resilience").

The generator is called once during session initialisation (in
_load_kg_session_context) and topically refreshed every N rounds to reflect
emerging narrative focal points.

Algorithm:
  1. Extract entity types and relation clusters from KG nodes/edges.
  2. Map entity clusters to belief domain templates (economic, social, political...).
  3. Optionally query LLM for scenario-specific topic names (lite fallback available).
  4. Return a de-duplicated, prioritised list of topic strings.

LLM cost: Optional — the lite path is fully rule-based; LLM enrichment is
guarded by ``use_llm=True`` and uses the AGENT_LLM_PROVIDER cheapest model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("belief_topic_generator")

# ---------------------------------------------------------------------------
# Domain templates
# ---------------------------------------------------------------------------

_ECONOMIC_KEYWORDS = frozenset(
    {"company", "market", "bank", "finance", "trade", "supply", "demand", "gdp", "stock"}
)
_POLITICAL_KEYWORDS = frozenset(
    {"government", "policy", "election", "party", "law", "regulation", "minister", "parliament"}
)
_SOCIAL_KEYWORDS = frozenset(
    {"community", "culture", "identity", "media", "family", "religion", "education"}
)
_CONFLICT_KEYWORDS = frozenset(
    {"war", "conflict", "protest", "strike", "violence", "tension", "dispute"}
)
_TECH_KEYWORDS = frozenset(
    {"technology", "ai", "software", "platform", "data", "cyber", "infrastructure"}
)

_DOMAIN_TOPICS: dict[str, list[str]] = {
    "economic": [
        "economic_stability",
        "market_confidence",
        "supply_chain_resilience",
        "employment_outlook",
        "inflation_concern",
    ],
    "political": [
        "government_trust",
        "policy_effectiveness",
        "institutional_legitimacy",
        "political_polarisation",
        "civic_engagement",
    ],
    "social": [
        "community_cohesion",
        "cultural_identity",
        "media_credibility",
        "social_trust",
        "collective_wellbeing",
    ],
    "conflict": [
        "security_concern",
        "conflict_escalation_risk",
        "humanitarian_outcome",
        "peace_prospect",
    ],
    "technology": [
        "tech_adoption_rate",
        "digital_trust",
        "information_integrity",
        "platform_influence",
    ],
}

_DEFAULT_TOPICS = [
    "general_sentiment",
    "agent_influence",
    "collective_action_potential",
]


# ---------------------------------------------------------------------------
# BeliefTopicGenerator
# ---------------------------------------------------------------------------


@dataclass
class BeliefTopicGenerator:
    """Generate and refresh scenario-specific belief dimensions.

    Designed to be instantiated once per SimulationRunner.
    """

    max_topics: int = 12
    # Cache: session_id → list of topic strings
    _topic_cache: dict[str, list[str]] = field(default_factory=dict, init=False, repr=False)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def generate_topics(
        self,
        session_id: str,
        scenario_description: str,
        kg_nodes: list[dict[str, Any]],
        kg_edges: list[dict[str, Any]],
        *,
        use_llm: bool = False,
        provider: str = "openrouter",
        model: str | None = None,
    ) -> list[str]:
        """Generate belief topics for a session.

        Args:
            session_id: The current simulation session.
            scenario_description: Free-text scenario seed.
            kg_nodes: KG node dicts with ``type`` or ``label`` fields.
            kg_edges: KG edge dicts with ``relation`` fields.
            use_llm: If True, attempt LLM enrichment on top of rule-based topics.
            provider: LLM provider for enrichment (ignored when use_llm=False).
            model: LLM model override.

        Returns:
            Ordered list of topic strings (most relevant first).
        """
        # Rule-based foundation
        topics = self._extract_rule_based_topics(scenario_description, kg_nodes, kg_edges)

        # Optional LLM enrichment
        if use_llm and scenario_description:
            try:
                llm_topics = await self._enrich_with_llm(
                    scenario_description, topics, provider, model
                )
                # Merge: LLM topics first, then rule-based (LLM gets priority)
                merged: list[str] = []
                seen: set[str] = set()
                for t in llm_topics + topics:
                    key = self._normalise(t)
                    if key not in seen:
                        seen.add(key)
                        merged.append(t)
                topics = merged
            except Exception:
                logger.warning(
                    "BeliefTopicGenerator LLM enrichment failed session=%s — using rule-based only",
                    session_id,
                )

        topics = topics[: self.max_topics]
        self._topic_cache[session_id] = topics
        logger.info(
            "BeliefTopicGenerator: %d topics for session=%s: %s",
            len(topics),
            session_id,
            topics[:5],
        )
        return topics

    def get_cached_topics(self, session_id: str) -> list[str] | None:
        """Return cached topics, or None if not yet generated."""
        return self._topic_cache.get(session_id)

    def clear_session(self, session_id: str) -> None:
        """Remove cache entry for a completed session."""
        self._topic_cache.pop(session_id, None)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _extract_rule_based_topics(
        self,
        scenario_description: str,
        kg_nodes: list[dict[str, Any]],
        kg_edges: list[dict[str, Any]],
    ) -> list[str]:
        """Identify domains from node types and return matching topic lists."""
        text = (scenario_description + " ".join(
            str(n.get("type", "")) + " " + str(n.get("label", ""))
            for n in kg_nodes
        ) + " ".join(
            str(e.get("relation", "")) for e in kg_edges
        )).lower()

        domain_scores: dict[str, int] = {}
        for domain, keywords in [
            ("economic", _ECONOMIC_KEYWORDS),
            ("political", _POLITICAL_KEYWORDS),
            ("social", _SOCIAL_KEYWORDS),
            ("conflict", _CONFLICT_KEYWORDS),
            ("technology", _TECH_KEYWORDS),
        ]:
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                domain_scores[domain] = score

        # Sort domains by relevance (highest score first)
        sorted_domains = sorted(domain_scores, key=lambda d: domain_scores[d], reverse=True)

        topics: list[str] = []
        seen: set[str] = set()
        for domain in sorted_domains:
            for t in _DOMAIN_TOPICS.get(domain, []):
                if t not in seen:
                    seen.add(t)
                    topics.append(t)

        # Always include defaults
        for t in _DEFAULT_TOPICS:
            if t not in seen:
                seen.add(t)
                topics.append(t)

        return topics

    async def _enrich_with_llm(
        self,
        scenario_description: str,
        existing_topics: list[str],
        provider: str,
        model: str | None,
    ) -> list[str]:
        """Ask LLM to suggest scenario-specific belief axis names."""
        from backend.app.utils.llm_client import get_default_client  # noqa: PLC0415

        client = get_default_client()
        existing_str = ", ".join(existing_topics[:6])
        messages = [
            {
                "role": "system",
                "content": (
                    "You generate belief dimension names for agent-based simulations. "
                    "Names must be snake_case, 2-5 words, specific to the scenario. "
                    "Return ONLY a JSON list of strings, max 8 items."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Scenario: {scenario_description[:400]}\n"
                    f"Existing dimensions: {existing_str}\n"
                    "Suggest 5 additional specific belief dimensions relevant to this scenario."
                ),
            },
        ]
        resp = await client.chat(messages, provider=provider, model=model, max_tokens=256)
        # Parse JSON list from response
        raw = resp.content.strip()
        # Extract JSON array if wrapped in markdown
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            import json  # noqa: PLC0415
            items = json.loads(match.group())
            return [str(t).strip() for t in items if isinstance(t, str) and t.strip()]
        return []

    @staticmethod
    def _normalise(topic: str) -> str:
        """Normalise topic for deduplication (lowercase snake_case)."""
        return re.sub(r"[^a-z0-9_]", "_", topic.lower()).strip("_")
