"""Universal scenario configuration generator.

Generates a domain-agnostic ``UniversalScenarioConfig`` from seed text and
knowledge-graph data using a single LLM call.

Three conceptual stages (executed in one prompt for efficiency):
  1. Analyse seed text → infer decision space (what can agents DO?)
  2. Analyse seed text → infer metrics (what should we TRACK?)
  3. Analyse seed text → infer shocks + impact rules (what EXTERNAL events can happen?)

The LLM is expected to return a single JSON object matching the schema
defined in ``backend/prompts/scenario_generation_prompts.py``.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from backend.app.models.universal_agent_profile import UniversalAgentProfile
from backend.app.models.universal_scenario import (
    ImpliedActor,
    UniversalDecisionType,
    UniversalImpactRule,
    UniversalMetric,
    UniversalScenarioConfig,
    UniversalShockType,
)
from backend.app.utils.llm_client import LLMClient
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_seed_text
from backend.prompts.scenario_generation_prompts import (
    SCENARIO_GENERATION_SYSTEM,
    SCENARIO_GENERATION_USER,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")
_MAX_DECISION_TYPES = 20
_MIN_DECISION_TYPES = 1
_MAX_METRICS = 15
_MIN_METRICS = 1
_MAX_SHOCK_TYPES = 15


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


class ScenarioGenerator:
    """Generate domain-agnostic scenario configuration from seed text and KG.

    Three-stage LLM pipeline (single call):
      1. Analyse seed text → infer decision space (what can agents DO?)
      2. Analyse seed text → infer metrics (what should we TRACK?)
      3. Analyse seed text → infer shocks + impact rules (what EXTERNAL events?)

    Args:
        llm_client: Optional pre-configured ``LLMClient``.  A default client
            is created if not provided.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def generate(
        self,
        seed_text: str,
        kg_nodes: list[dict[str, Any]],
        kg_edges: list[dict[str, Any]],
        agent_profiles: list[UniversalAgentProfile],
    ) -> UniversalScenarioConfig:
        """Generate complete scenario config from seed text, KG, and agents.

        Args:
            seed_text: Original free-text seed that was used to build the KG.
            kg_nodes: List of KG node dicts (must include ``id`` and ``label``).
            kg_edges: List of KG edge dicts (must include ``source``, ``target``,
                ``relation``).
            agent_profiles: Generated ``UniversalAgentProfile`` list for this KG.

        Returns:
            A frozen ``UniversalScenarioConfig`` ready for use in simulation.

        Raises:
            RuntimeError: If the LLM call fails, returns unparseable JSON, or
                the response fails validation.
        """
        raw = await self._call_llm(seed_text, kg_nodes, kg_edges, agent_profiles)
        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Private: LLM call
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        seed_text: str,
        kg_nodes: list[dict[str, Any]],
        kg_edges: list[dict[str, Any]],
        agent_profiles: list[UniversalAgentProfile],
    ) -> dict[str, Any]:
        """Build prompts, call the LLM, and return the parsed JSON dict."""
        agent_summaries = _build_agent_summaries(agent_profiles)
        safe_seed = sanitize_seed_text(seed_text)

        user_content = SCENARIO_GENERATION_USER.format(
            seed_text=safe_seed,
            node_count=len(kg_nodes),
            kg_nodes_json=json.dumps(kg_nodes, ensure_ascii=False, indent=2),
            edge_count=len(kg_edges),
            kg_edges_json=json.dumps(kg_edges, ensure_ascii=False, indent=2),
            agent_count=len(agent_summaries),
            agent_summaries_json=json.dumps(agent_summaries, ensure_ascii=False, indent=2),
        )

        messages = [
            {"role": "system", "content": SCENARIO_GENERATION_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        logger.info(
            "ScenarioGenerator: calling LLM (nodes=%d, edges=%d, agents=%d)",
            len(kg_nodes),
            len(kg_edges),
            len(agent_profiles),
        )

        try:
            raw = await self._llm.chat_json(
                messages,
                max_tokens=4096,
                temperature=0.3,
            )
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"ScenarioGenerator: LLM returned non-JSON response: {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"ScenarioGenerator: LLM call failed: {exc}"
            ) from exc

        logger.info("ScenarioGenerator: LLM response received, parsing...")
        return raw

    # ------------------------------------------------------------------
    # Private: parse + validate
    # ------------------------------------------------------------------

    def _parse_response(self, raw: dict[str, Any]) -> UniversalScenarioConfig:
        """Parse and validate the raw LLM response dict.

        Args:
            raw: Parsed JSON dict from the LLM.

        Returns:
            A fully validated ``UniversalScenarioConfig``.

        Raises:
            RuntimeError: On any validation failure.
        """
        try:
            decision_types = _parse_decision_types(raw.get("decision_types", []))
            metrics = _parse_metrics(raw.get("metrics", []))
            shock_types = _parse_shock_types(raw.get("shock_types", []))
            impact_rules = _parse_impact_rules(raw.get("impact_rules", []))
            implied_actors = _parse_implied_actors(raw.get("implied_actors", []))
            stakeholder_types = _parse_stakeholder_entity_types(
                raw.get("stakeholder_entity_types", [])
            )

            config = UniversalScenarioConfig(
                scenario_id=str(uuid.uuid4()),
                scenario_name=_require_str(raw, "scenario_name"),
                scenario_description=_require_str(raw, "scenario_description"),
                decision_types=tuple(decision_types),
                metrics=tuple(metrics),
                shock_types=tuple(shock_types),
                impact_rules=tuple(impact_rules),
                time_scale=raw.get("time_scale", "rounds"),
                language_hint=raw.get("language_hint", "auto"),
                implied_actors=tuple(implied_actors),
                stakeholder_entity_types=tuple(stakeholder_types),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"ScenarioGenerator: response validation failed: {exc}"
            ) from exc

        logger.info(
            "ScenarioGenerator: config created (decisions=%d, metrics=%d, "
            "shocks=%d, rules=%d, implied_actors=%d, stakeholder_types=%d)",
            len(config.decision_types),
            len(config.metrics),
            len(config.shock_types),
            len(config.impact_rules),
            len(config.implied_actors),
            len(config.stakeholder_entity_types),
        )
        return config


# ---------------------------------------------------------------------------
# Private parsers
# ---------------------------------------------------------------------------


def _require_str(data: dict[str, Any], key: str) -> str:
    """Return a non-empty string value from ``data[key]`` or raise ValueError."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or empty required field: '{key}'")
    return value.strip()


def _validate_slug(slug: str, context: str) -> str:
    """Assert that ``slug`` is a valid URL-safe identifier, return it."""
    if not _SLUG_RE.match(slug):
        logger.warning(
            "ScenarioGenerator: slug '%s' in %s contains invalid characters — sanitising",
            slug,
            context,
        )
        slug = _sanitise_slug(slug)
    return slug


def _sanitise_slug(raw: str) -> str:
    """Convert an arbitrary string to a URL-safe slug."""
    slug = raw.lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "unknown"


def _parse_decision_types(items: list[Any]) -> list[UniversalDecisionType]:
    """Parse and validate decision type entries from the LLM response."""
    if not items:
        raise ValueError("decision_types must not be empty")

    result: list[UniversalDecisionType] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"decision_types[{i}] must be a dict, got {type(item)}")

        raw_id = _sanitise_slug(str(item.get("id", f"decision_{i}")))
        slug = _validate_slug(raw_id, f"decision_types[{i}].id")

        raw_actions = item.get("possible_actions", [])
        if not isinstance(raw_actions, list) or not raw_actions:
            raise ValueError(
                f"decision_types[{i}] '{slug}' must have non-empty possible_actions"
            )
        actions = tuple(_sanitise_slug(str(a)) for a in raw_actions)

        raw_entity_types = item.get("applicable_entity_types", [])
        entity_types: tuple[str, ...] = (
            tuple(str(e) for e in raw_entity_types)
            if isinstance(raw_entity_types, list)
            else ()
        )

        result.append(
            UniversalDecisionType(
                id=slug,
                label=str(item.get("label", slug)),
                description=str(item.get("description", "")),
                possible_actions=actions,
                applicable_entity_types=entity_types,
            )
        )

    if len(result) > _MAX_DECISION_TYPES:
        logger.warning(
            "ScenarioGenerator: %d decision_types exceeds max %d — truncating",
            len(result),
            _MAX_DECISION_TYPES,
        )
        result = result[:_MAX_DECISION_TYPES]

    return result


def _parse_metrics(items: list[Any]) -> list[UniversalMetric]:
    """Parse and validate metric entries from the LLM response."""
    if not items:
        raise ValueError("metrics must not be empty")

    result: list[UniversalMetric] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"metrics[{i}] must be a dict, got {type(item)}")

        raw_id = _sanitise_slug(str(item.get("id", f"metric_{i}")))
        slug = _validate_slug(raw_id, f"metrics[{i}].id")

        try:
            initial_value = float(item.get("initial_value", 50.0))
        except (TypeError, ValueError):
            initial_value = 50.0
            logger.warning(
                "ScenarioGenerator: metrics[%d] '%s' has invalid initial_value — defaulting to 50.0",
                i,
                slug,
            )

        result.append(
            UniversalMetric(
                id=slug,
                label=str(item.get("label", slug)),
                description=str(item.get("description", "")),
                initial_value=initial_value,
                unit=str(item.get("unit", "")),
            )
        )

    if len(result) > _MAX_METRICS:
        logger.warning(
            "ScenarioGenerator: %d metrics exceeds max %d — truncating",
            len(result),
            _MAX_METRICS,
        )
        result = result[:_MAX_METRICS]

    return result


def _parse_shock_types(items: list[Any]) -> list[UniversalShockType]:
    """Parse and validate shock type entries from the LLM response."""
    result: list[UniversalShockType] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            logger.warning("ScenarioGenerator: shock_types[%d] is not a dict — skipping", i)
            continue

        raw_id = _sanitise_slug(str(item.get("id", f"shock_{i}")))
        slug = _validate_slug(raw_id, f"shock_types[{i}].id")

        raw_affected = item.get("affected_metrics", [])
        affected: tuple[str, ...] = (
            tuple(_sanitise_slug(str(m)) for m in raw_affected)
            if isinstance(raw_affected, list)
            else ()
        )

        raw_range = item.get("severity_range", [0.1, 1.0])
        severity_range = _parse_severity_range(raw_range, slug)

        result.append(
            UniversalShockType(
                id=slug,
                label=str(item.get("label", slug)),
                description=str(item.get("description", "")),
                affected_metrics=affected,
                severity_range=severity_range,
            )
        )

    if len(result) > _MAX_SHOCK_TYPES:
        logger.warning(
            "ScenarioGenerator: %d shock_types exceeds max %d — truncating",
            len(result),
            _MAX_SHOCK_TYPES,
        )
        result = result[:_MAX_SHOCK_TYPES]

    return result


def _parse_severity_range(
    raw: Any, context: str
) -> tuple[float, float]:
    """Parse and clamp a severity_range value."""
    try:
        lo, hi = float(raw[0]), float(raw[1])
        lo = max(0.0, min(lo, 10.0))
        hi = max(0.0, min(hi, 10.0))
        if lo > hi:
            lo, hi = hi, lo
        return (lo, hi)
    except (TypeError, IndexError, ValueError):
        logger.warning(
            "ScenarioGenerator: invalid severity_range for '%s' — using default (0.1, 1.0)",
            context,
        )
        return (0.1, 1.0)


def _parse_impact_rules(items: list[Any]) -> list[UniversalImpactRule]:
    """Parse impact rule entries.  Silently skips malformed entries."""
    result: list[UniversalImpactRule] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            logger.warning("ScenarioGenerator: impact_rules[%d] is not a dict — skipping", i)
            continue

        decision_type_id = _sanitise_slug(str(item.get("decision_type_id", "")))
        action = _sanitise_slug(str(item.get("action", "")))
        metric_id = _sanitise_slug(str(item.get("metric_id", "")))

        if not decision_type_id or not action or not metric_id:
            logger.warning(
                "ScenarioGenerator: impact_rules[%d] missing required fields — skipping",
                i,
            )
            continue

        try:
            delta_per_10 = float(item.get("delta_per_10", 0.0))
        except (TypeError, ValueError):
            delta_per_10 = 0.0

        result.append(
            UniversalImpactRule(
                decision_type_id=decision_type_id,
                action=action,
                metric_id=metric_id,
                delta_per_10=delta_per_10,
                description=str(item.get("description", "")),
            )
        )

    return result


def _parse_stakeholder_entity_types(raw: list[Any]) -> list[str]:
    """Parse stakeholder_entity_types list from LLM response.

    Returns a deduplicated list of non-empty strings.  Silently discards
    non-string entries.  Returns [] if input is not a list.
    """
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in raw:
        val = str(item).strip() if item else ""
        if val and val not in seen:
            seen.add(val)
            result.append(val)
    return result


def _parse_implied_actors(raw_list: list[Any]) -> list[ImpliedActor]:
    """Parse implied_actors list from LLM response. Returns [] on any error."""
    result: list[ImpliedActor] = []
    for item in raw_list[:30]:  # cap at 30
        try:
            actor_id = _validate_slug(
                item.get("id", ""), f"implied_actor[{item.get('name', '?')}]"
            )
            result.append(ImpliedActor(
                id=actor_id,
                name=str(item.get("name", "")).strip(),
                entity_type=str(item.get("entity_type", "Organization")).strip(),
                role=str(item.get("role", "")).strip(),
                relevance_reason=str(item.get("relevance_reason", "")).strip(),
            ))
        except Exception as exc:
            logger.warning("ScenarioGenerator: skipping malformed implied_actor: %s", exc)
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_agent_summaries(
    agent_profiles: list[UniversalAgentProfile],
) -> list[dict[str, str]]:
    """Convert agent profiles to compact summary dicts for the prompt."""
    return [
        {
            "id": p.id,
            "name": p.name,
            "entity_type": p.entity_type,
            "role": p.role,
        }
        for p in agent_profiles
    ]
