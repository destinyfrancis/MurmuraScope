"""KG-driven universal agent factory.

Converts knowledge graph nodes and edges into UniversalAgentProfile instances
via a two-stage LLM pipeline:

  Stage 1 — Eligibility filter: determine which KG nodes are concrete actors
  Stage 2 — Profile generation: generate full agent profiles from eligible nodes

This service makes the simulation engine domain-agnostic: any scenario that can
be described as a knowledge graph (geopolitical, corporate, historical, etc.)
can be converted into OASIS-compatible simulation agents.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any

from backend.app.models.universal_agent_profile import UniversalAgentProfile
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.prompts.agent_generation_prompts import (
    AGENT_ELIGIBLE_FILTER_SYSTEM,
    AGENT_ELIGIBLE_FILTER_USER,
    AGENT_GENERATION_SYSTEM,
    AGENT_GENERATION_USER,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Entity types that qualify a KG node as a simulation agent
# ---------------------------------------------------------------------------

_AGENT_ELIGIBLE_TYPES: frozenset[str] = frozenset(
    {
        "Person",
        "Country",
        "Military",
        "Organization",
        "MediaOutlet",
        "PoliticalFigure",
        "Company",
        "NGO",
        "Institution",
        "Inferred",
    }
)

# Fallback minimum agents when all LLM calls fail
_MIN_FALLBACK_AGENTS = 1


# ---------------------------------------------------------------------------
# KGAgentFactory
# ---------------------------------------------------------------------------


class KGAgentFactory:
    """Generate UniversalAgentProfile instances from KG nodes and edges.

    Usage::

        factory = KGAgentFactory()
        profiles = await factory.generate_from_kg(
            nodes=kg_nodes,
            edges=kg_edges,
            seed_text="Iran nuclear negotiations 2024...",
            target_count=20,
        )
        csv_path = await factory.generate_agents_csv(profiles, "/tmp/agents.csv")
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_from_kg(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        seed_text: str,
        target_count: int | None = None,
    ) -> list[UniversalAgentProfile]:
        """Generate agent profiles from KG nodes and edges.

        Two-stage pipeline:
        1. Filter nodes down to agent-eligible actors via LLM.
        2. Generate full UniversalAgentProfile for each eligible node.

        If ``target_count`` exceeds the number of eligible nodes the LLM is
        instructed to invent additional plausible agents implied by the
        scenario.

        Args:
            nodes: KG node dicts (must contain at minimum ``id`` and ``label``
                   keys; additional properties such as ``entity_type`` and
                   ``description`` improve output quality).
            edges: KG edge dicts (``source``, ``target``, ``relation`` keys).
            seed_text: Original scenario description used as context.
            target_count: Desired total number of agents.  ``None`` means
                          generate one agent per eligible node.

        Returns:
            A list of frozen ``UniversalAgentProfile`` instances.

        Raises:
            ValueError: If ``nodes`` is empty.
            RuntimeError: If both LLM stages fail and no fallback is possible.
        """
        if not nodes:
            raise ValueError("nodes must not be empty")

        logger.info(
            "generate_from_kg: %d nodes, %d edges, target_count=%s",
            len(nodes),
            len(edges),
            target_count,
        )

        # Stage 1 — eligibility filter
        eligible_nodes = await self._filter_agent_eligible_nodes(nodes)

        if not eligible_nodes:
            logger.warning(
                "No agent-eligible nodes found among %d KG nodes; "
                "falling back to all nodes",
                len(nodes),
            )
            # Last-resort: treat all nodes as eligible so we always produce
            # at least some agents rather than returning an empty list.
            eligible_nodes = nodes

        resolved_target = target_count if target_count is not None else len(eligible_nodes)
        logger.info(
            "Stage 1 complete: %d eligible nodes, resolved target=%d",
            len(eligible_nodes),
            resolved_target,
        )

        # Stage 2 — profile generation
        profiles = await self._generate_profiles(
            eligible_nodes=eligible_nodes,
            edges=edges,
            seed_text=seed_text,
            target_count=resolved_target,
        )

        logger.info("generate_from_kg complete: produced %d profiles", len(profiles))
        return profiles

    def generate_agents_csv(
        self,
        profiles: list[UniversalAgentProfile],
        output_path: str,
    ) -> str:
        """Write OASIS-compatible agents.csv to ``output_path``.

        The CSV has three columns: ``userid``, ``user_char``, ``username``.
        The file is created (or overwritten) at the given path.

        Args:
            profiles: Agent profiles to serialise.
            output_path: Absolute or relative path for the output CSV.

        Returns:
            The resolved absolute path of the written file.

        Raises:
            ValueError: If ``profiles`` is empty.
            OSError: If the file cannot be written.
        """
        if not profiles:
            raise ValueError("profiles must not be empty to write agents.csv")

        abs_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        rows = [p.to_oasis_row() for p in profiles]
        fieldnames = ["userid", "user_char", "username"]

        with open(abs_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        logger.info("agents.csv written: %d rows → %s", len(rows), abs_path)
        return abs_path

    # ------------------------------------------------------------------
    # Stage 1: eligibility filter
    # ------------------------------------------------------------------

    async def _filter_agent_eligible_nodes(
        self,
        nodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Use LLM to identify which KG nodes should become simulation agents.

        Falls back to a fast heuristic filter if the LLM call fails.

        Args:
            nodes: All KG nodes from GraphBuilder.

        Returns:
            Filtered list of node dicts (eligible agents only).
        """
        nodes_json = json.dumps(nodes, ensure_ascii=False, indent=2)

        try:
            result = await self._llm.chat_json(
                messages=[
                    {"role": "system", "content": AGENT_ELIGIBLE_FILTER_SYSTEM},
                    {
                        "role": "user",
                        "content": AGENT_ELIGIBLE_FILTER_USER.format(
                            nodes_json=nodes_json
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=4096,
            )
            eligible_ids: set[str] = {
                entry["node_id"] for entry in result.get("eligible", [])
            }
            eligible = [n for n in nodes if str(n.get("id", "")) in eligible_ids]

            if not eligible:
                logger.warning(
                    "LLM filter returned 0 eligible nodes; using heuristic fallback"
                )
                return self._heuristic_filter(nodes)

            return eligible

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM eligibility filter failed (%s); using heuristic fallback",
                exc,
            )
            return self._heuristic_filter(nodes)

    @staticmethod
    def _heuristic_filter(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fast heuristic fallback when the LLM filter is unavailable.

        Keeps nodes whose ``entity_type`` is in the eligible set, or whose
        ``label`` / ``type`` field contains actor-like keywords.

        Args:
            nodes: All KG nodes.

        Returns:
            Subset likely to be concrete actors.
        """
        _ACTOR_KEYWORDS = frozenset(
            {
                "person", "people", "country", "nation", "government",
                "military", "army", "organization", "organisation", "company",
                "corporation", "media", "outlet", "party", "movement",
                "institution", "leader", "minister", "president", "figure",
            }
        )

        def _is_actor(node: dict[str, Any]) -> bool:
            entity_type = str(node.get("entity_type", "")).lower()
            label = str(node.get("label", "")).lower()
            node_type = str(node.get("type", "")).lower()
            combined = f"{entity_type} {label} {node_type}"
            return any(kw in combined for kw in _ACTOR_KEYWORDS)

        filtered = [n for n in nodes if _is_actor(n)]
        # If heuristic also returns nothing, accept all nodes as a last resort
        return filtered if filtered else nodes

    # ------------------------------------------------------------------
    # Stage 2: profile generation
    # ------------------------------------------------------------------

    async def _generate_profiles(
        self,
        eligible_nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        seed_text: str,
        target_count: int,
    ) -> list[UniversalAgentProfile]:
        """Call LLM to generate full agent profiles for eligible nodes.

        Args:
            eligible_nodes: Agent-eligible KG nodes (from Stage 1).
            edges: All KG edges (used for relationship inference).
            seed_text: Original scenario description.
            target_count: Desired number of agents (LLM may add inferred ones).

        Returns:
            List of ``UniversalAgentProfile`` instances.

        Raises:
            RuntimeError: If LLM call fails and no profiles can be produced.
        """
        eligible_json = json.dumps(eligible_nodes, ensure_ascii=False, indent=2)
        edges_json = json.dumps(edges, ensure_ascii=False, indent=2)

        try:
            result = await self._llm.chat_json(
                messages=[
                    {"role": "system", "content": AGENT_GENERATION_SYSTEM},
                    {
                        "role": "user",
                        "content": AGENT_GENERATION_USER.format(
                            seed_text=seed_text,
                            eligible_nodes_json=eligible_json,
                            edges_json=edges_json,
                            target_count=target_count,
                        ),
                    },
                ],
                temperature=0.7,
                max_tokens=8192,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"LLM profile generation failed: {exc}"
            ) from exc

        raw_agents: list[dict[str, Any]] = result.get("agents", [])
        if not raw_agents:
            raise RuntimeError(
                "LLM returned no agents in profile generation response"
            )

        profiles: list[UniversalAgentProfile] = []
        for raw in raw_agents:
            profile = self._parse_agent_dict(raw)
            if profile is not None:
                profiles.append(profile)

        if not profiles:
            raise RuntimeError(
                "No valid agent profiles could be parsed from LLM response"
            )

        return profiles

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_agent_dict(raw: dict[str, Any]) -> UniversalAgentProfile | None:
        """Parse a single raw agent dict into an UniversalAgentProfile.

        Returns ``None`` and logs a warning if the dict is missing required
        fields or contains invalid values.

        Args:
            raw: Dict from LLM response ``agents`` list.

        Returns:
            A frozen ``UniversalAgentProfile``, or ``None`` on parse error.
        """
        required = {"id", "name", "role", "entity_type", "persona"}
        missing = required - raw.keys()
        if missing:
            logger.warning("Skipping agent with missing fields %s: %r", missing, raw)
            return None

        try:
            # Convert stance_axes from dict to tuple-of-tuples
            raw_stance = raw.get("stance_axes", {})
            if isinstance(raw_stance, dict):
                stance_axes: tuple[tuple[str, float], ...] = tuple(
                    (str(k), float(v)) for k, v in raw_stance.items()
                )
            else:
                stance_axes = tuple()

            # Convert relationships from dict or list to tuple-of-tuples
            raw_rels = raw.get("relationships", {})
            if isinstance(raw_rels, dict):
                relationships: tuple[tuple[str, str], ...] = tuple(
                    (str(k), str(v)) for k, v in raw_rels.items()
                )
            elif isinstance(raw_rels, list):
                relationships = tuple(
                    (str(item[0]), str(item[1]))
                    for item in raw_rels
                    if len(item) >= 2
                )
            else:
                relationships = tuple()

            goals = tuple(str(g) for g in raw.get("goals", []))
            capabilities = tuple(str(c) for c in raw.get("capabilities", []))

            return UniversalAgentProfile(
                id=str(raw["id"]),
                name=str(raw["name"]),
                role=str(raw["role"]),
                entity_type=str(raw["entity_type"]),
                persona=str(raw["persona"]),
                goals=goals,
                capabilities=capabilities,
                stance_axes=stance_axes,
                relationships=relationships,
                kg_node_id=str(raw.get("kg_node_id", raw["id"])),
                openness=_clamp(float(raw.get("openness", 0.5))),
                conscientiousness=_clamp(float(raw.get("conscientiousness", 0.5))),
                extraversion=_clamp(float(raw.get("extraversion", 0.5))),
                agreeableness=_clamp(float(raw.get("agreeableness", 0.5))),
                neuroticism=_clamp(float(raw.get("neuroticism", 0.5))),
            )

        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Failed to parse agent dict: %s — %r", exc, raw)
            return None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp ``value`` to the range [lo, hi]."""
    return max(lo, min(hi, value))
