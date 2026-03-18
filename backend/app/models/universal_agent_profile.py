"""Universal agent profile for domain-agnostic simulation.

Unlike AgentProfile (HK census-calibrated), UniversalAgentProfile is
generated dynamically from knowledge graph entities via LLM.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class UniversalAgentProfile:
    """Immutable agent profile derived from a KG entity.

    Used when the simulation scenario is NOT Hong Kong demographics
    (e.g., geopolitical conflicts, corporate competition, historical events).

    All collection fields use tuples to preserve immutability.
    The ``stance_axes`` field stores named stance dimensions as a tuple of
    ``(axis_name, value)`` pairs where value is in [0.0, 1.0].
    The ``relationships`` field stores ``(other_agent_id, relationship_desc)``
    pairs describing inter-agent relationships derived from KG edges.
    """

    id: str
    """Unique agent identifier (slug form, e.g. 'iran_supreme_leader')."""

    name: str
    """Display name, may be in any language (e.g. '伊朗最高領袖哈梅內伊')."""

    role: str
    """One-line role description for this agent."""

    entity_type: str
    """KG ontology type (e.g. 'PoliticalFigure', 'Country', 'Military',
    'Organization', 'MediaOutlet', 'Person')."""

    persona: str
    """LLM-generated detailed persona used as the OASIS user_char.
    Should capture worldview, communication style, and decision patterns
    (2–4 sentences)."""

    goals: tuple[str, ...]
    """Core objectives that drive this agent's behaviour."""

    capabilities: tuple[str, ...]
    """Actions or resources available to this agent."""

    stance_axes: tuple[tuple[str, float], ...]
    """Named stance dimensions relevant to the scenario.
    Each element is ``(axis_name, value)`` where value is in [0.0, 1.0].
    Axes are inferred by the LLM from the scenario context."""

    relationships: tuple[tuple[str, str], ...]
    """Inter-agent relationships as ``(other_agent_id, description)`` pairs.
    Derived from KG edges during generation."""

    kg_node_id: str
    """Back-reference to the originating KG node ID."""

    # ------------------------------------------------------------------
    # Voice / communication style fields (Task 2 — report quality upgrade)
    # All have defaults for backward compatibility with existing callers.
    # ------------------------------------------------------------------

    communication_style: str = ""
    """Voice/style descriptor — e.g. 'casual_gen_z', 'formal_academic', 'strategic_institutional'.
    Used in OASIS persona and report interview prompts."""

    vocabulary_hints: tuple[str, ...] = ()
    """Domain-specific vocabulary this agent uses naturally.
    e.g. ('程序正義', '申訴機制') for legal expert, ('遊戲比喻', 'Z世代語言') for student."""

    platform_persona: str = ""
    """How this agent behaves differently across platforms.
    e.g. 'Facebook: 長文理性分析; Instagram: 短句情緒化+標籤'"""

    # ------------------------------------------------------------------
    # Big Five personality traits (OASIS emotional engine compatibility)
    # Default 0.5 = neutral / average population baseline
    # ------------------------------------------------------------------

    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    def to_oasis_row(self) -> dict[str, str]:
        """Convert to OASIS agents.csv row format.

        OASIS expects three columns: ``userid``, ``user_char``, ``username``.

        ``userid``    — the agent's unique ID (string)
        ``user_char`` — full persona text used by OASIS as the agent's
                        personality/character description
        ``username``  — deterministic URL-safe slug derived from name + id
                        to prevent collisions across simulations

        Returns:
            A dict with keys ``userid``, ``user_char``, ``username``.
        """
        return {
            "userid": self.id,
            "user_char": self.persona,
            "username": _make_username(self.name, self.id),
        }

    def get_stance(self, axis: str, default: float = 0.5) -> float:
        """Retrieve the value for a named stance axis.

        Args:
            axis: The axis name to look up.
            default: Value to return if the axis is not present.

        Returns:
            The stance value in [0.0, 1.0], or ``default``.
        """
        for name, value in self.stance_axes:
            if name == axis:
                return value
        return default


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _make_username(name: str, agent_id: str) -> str:
    """Return a deterministic, URL-safe username derived from name + id.

    The slug is formed by lower-casing and stripping non-ASCII characters
    from ``name``, then appending the first 6 hex characters of the MD5
    of ``name + agent_id`` to guarantee uniqueness.

    Args:
        name: Display name (may contain CJK or other Unicode).
        agent_id: Unique agent identifier string.

    Returns:
        A slug such as ``"iran_supreme_leader_a3f9b2"``.
    """
    # Keep only ASCII word characters, collapse spaces/hyphens to underscores
    ascii_part = re.sub(r"[^\w]", "_", name.encode("ascii", errors="ignore").decode())
    ascii_part = re.sub(r"_+", "_", ascii_part).strip("_").lower()

    # Fallback if name was entirely non-ASCII
    if not ascii_part:
        ascii_part = agent_id

    suffix = hashlib.md5(f"{name}{agent_id}".encode()).hexdigest()[:6]
    return f"{ascii_part}_{suffix}"
