"""Universal scenario configuration — LLM-generated decision space, metrics, and shocks.

Replaces hardcoded DecisionType enum, MetricSpec, and ShockTypeSpec for
non-demographic simulation modes (kg_driven).

All dataclasses are frozen to enforce immutability per project code style.
Use dataclasses.replace() for any state transitions.
"""
from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Decision space
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversalDecisionType:
    """A single decision type available to agents in this scenario.

    Attributes:
        id: URL-safe slug, e.g. ``"form_alliance"``.
        label: Human-readable display name, e.g. ``"結盟"``.
        description: One-sentence explanation of what this decision represents.
        possible_actions: Tuple of valid action strings agents may take.
        applicable_entity_types: Which KG entity types may make this decision.
            Empty tuple means all agent types are eligible.
    """

    id: str
    label: str
    description: str
    possible_actions: tuple[str, ...]
    applicable_entity_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("UniversalDecisionType.id must not be empty")
        if not self.possible_actions:
            raise ValueError(
                f"UniversalDecisionType '{self.id}' must have at least one possible_action"
            )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversalMetric:
    """A scenario-specific metric to track during simulation.

    Attributes:
        id: URL-safe slug, e.g. ``"oil_price"``.
        label: Human-readable display name.
        description: What this metric captures.
        initial_value: Starting value (recommended 0–100 normalised scale).
        unit: Optional label for the unit, e.g. ``"USD/barrel"``.
    """

    id: str
    label: str
    description: str
    initial_value: float
    unit: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("UniversalMetric.id must not be empty")


# ---------------------------------------------------------------------------
# Shocks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversalShockType:
    """A type of external shock that can be injected into a running simulation.

    Attributes:
        id: URL-safe slug, e.g. ``"imperial_decree"``.
        label: Human-readable display name.
        description: What happens when this shock is triggered.
        affected_metrics: IDs of metrics this shock influences.
        severity_range: ``(min, max)`` severity multiplier for the shock.
    """

    id: str
    label: str
    description: str
    affected_metrics: tuple[str, ...]
    severity_range: tuple[float, float] = (0.1, 1.0)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("UniversalShockType.id must not be empty")
        lo, hi = self.severity_range
        if lo < 0 or hi > 10 or lo > hi:
            raise ValueError(
                f"UniversalShockType '{self.id}' severity_range must satisfy "
                f"0 <= lo <= hi <= 10, got ({lo}, {hi})"
            )


# ---------------------------------------------------------------------------
# Impact rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversalImpactRule:
    """How aggregate decisions of a given type shift a metric.

    Attributes:
        decision_type_id: Which ``UniversalDecisionType`` triggers this rule.
        action: Which specific action string within that decision type.
        metric_id: ID of the ``UniversalMetric`` that is affected.
        delta_per_10: Change applied to the metric per 10 net occurrences of
            this action in a single simulation round.
        description: Optional human-readable explanation.
    """

    decision_type_id: str
    action: str
    metric_id: str
    delta_per_10: float
    description: str = ""

    def __post_init__(self) -> None:
        if not self.decision_type_id:
            raise ValueError("UniversalImpactRule.decision_type_id must not be empty")
        if not self.action:
            raise ValueError("UniversalImpactRule.action must not be empty")
        if not self.metric_id:
            raise ValueError("UniversalImpactRule.metric_id must not be empty")


# ---------------------------------------------------------------------------
# Implied actors (Option B — ScenarioGenerator discovery)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImpliedActor:
    """An actor identified by ScenarioGenerator as relevant but not in the KG.

    Attributes:
        id: URL-safe slug.
        name: Human-readable name in seed text's language.
        entity_type: Actor category (Country, Organization, etc.)
        role: One sentence describing their role in the scenario.
        relevance_reason: Why they are critically relevant.
    """

    id: str
    name: str
    entity_type: str
    role: str
    relevance_reason: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ImpliedActor.id must not be empty")


# ---------------------------------------------------------------------------
# Top-level scenario config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversalScenarioConfig:
    """Complete scenario configuration generated by the LLM from seed text.

    This replaces ``DomainPack`` for ``kg_driven`` simulation mode.  It is
    entirely domain-agnostic and carries no HK-specific assumptions.

    Cross-validation is performed in ``__post_init__``:
    - Every ``impact_rule.decision_type_id`` must exist in ``decision_types``.
    - Every ``impact_rule.metric_id`` must exist in ``metrics``.
    - Every ``impact_rule.action`` must exist in the referenced decision type.

    Attributes:
        scenario_id: Unique identifier for this scenario config (UUID or slug).
        scenario_name: Short human-readable name.
        scenario_description: 1–2 sentence summary of the scenario.
        decision_types: All decision types agents may face.
        metrics: All metrics tracked during simulation.
        shock_types: External events that can be injected.
        impact_rules: How decisions map to metric changes.
        time_scale: Semantic label for simulation rounds, e.g. ``"days"``.
        language_hint: Preferred output language code, e.g. ``"zh-HK"``.
        implied_actors: Actors identified by ScenarioGenerator as critically
            relevant but absent from the KG. Informational audit trail.
    """

    scenario_id: str
    scenario_name: str
    scenario_description: str

    decision_types: tuple[UniversalDecisionType, ...]
    metrics: tuple[UniversalMetric, ...]
    shock_types: tuple[UniversalShockType, ...]
    impact_rules: tuple[UniversalImpactRule, ...]

    time_scale: str = "rounds"
    language_hint: str = "auto"
    implied_actors: tuple[ImpliedActor, ...] = ()
    stakeholder_entity_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.decision_types:
            raise ValueError("UniversalScenarioConfig must have at least one decision_type")
        if not self.metrics:
            raise ValueError("UniversalScenarioConfig must have at least one metric")

        decision_map: dict[str, frozenset[str]] = {
            dt.id: frozenset(dt.possible_actions) for dt in self.decision_types
        }
        metric_ids: frozenset[str] = frozenset(m.id for m in self.metrics)

        for rule in self.impact_rules:
            if rule.decision_type_id not in decision_map:
                raise ValueError(
                    f"ImpactRule references unknown decision_type_id "
                    f"'{rule.decision_type_id}'"
                )
            if rule.metric_id not in metric_ids:
                raise ValueError(
                    f"ImpactRule references unknown metric_id '{rule.metric_id}'"
                )
            if rule.action not in decision_map[rule.decision_type_id]:
                raise ValueError(
                    f"ImpactRule action '{rule.action}' not found in "
                    f"decision_type '{rule.decision_type_id}'"
                )

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_decision_type(self, decision_id: str) -> UniversalDecisionType | None:
        """Return the decision type for ``decision_id``, or None if absent."""
        for dt in self.decision_types:
            if dt.id == decision_id:
                return dt
        return None

    def get_metric(self, metric_id: str) -> UniversalMetric | None:
        """Return the metric for ``metric_id``, or None if absent."""
        for m in self.metrics:
            if m.id == metric_id:
                return m
        return None

    def rules_for_action(
        self, decision_type_id: str, action: str
    ) -> tuple[UniversalImpactRule, ...]:
        """Return all impact rules matching a specific decision type + action."""
        return tuple(
            r
            for r in self.impact_rules
            if r.decision_type_id == decision_type_id and r.action == action
        )
