"""Simulation configuration: hook intervals and presets."""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class HookConfig:
    """Config-driven hook intervals. Replaces all hardcoded % N checks."""

    echo_chamber_interval: int = 5
    media_influence_interval: int = 5
    macro_feedback_interval: int = 5
    kg_snapshot_interval: int = 5
    kg_evolution_interval: int = 3  # Zep-style KG evolution from agent activities
    news_shock_interval: int = 5
    polarization_interval: int = 5
    company_decision_interval: int = 2
    summarize_interval: int = 20
    summarize_salience_threshold: float = 0.3
    decision_sample_rate: float = 0.05
    decision_cap: int = 25
    llm_concurrency: int = 50
    mc_trials: int = 100
    # Phase 1C: dynamic network evolution
    network_evolution_interval: int = 3
    # Phase 2: recommendation engine
    feed_algorithm: str = "engagement_first"
    virality_interval: int = 3
    # Phase 3: emotional state
    emotional_contagion_interval: int = 3   # emotional spread every N rounds
    # Phase 1A/1B: OASIS fork integration
    attention_economy_interval: int = 1     # attention allocation every N rounds (1 = every round)
    temporal_activation_enabled: bool = True # enable time-of-day gating
    collective_action_interval: int = 5     # group formation every N rounds
    # Phase C: emergence toggle
    emergence_enabled: bool = True          # enable emergence hooks (emotional, belief, contagion, etc.)

    @classmethod
    def scaled(cls, agent_count: int) -> HookConfig:
        """Create a HookConfig auto-scaled for the given agent count.

        Adjusts decision_cap, llm_concurrency, and emergence_enabled
        based on agent count to maintain reasonable performance.
        """
        return cls(
            decision_cap=max(25, agent_count // 20),
            llm_concurrency=min(100, max(10, agent_count // 5)),
            emergence_enabled=agent_count <= 5000,
            # Widen periodic intervals for large populations
            echo_chamber_interval=5 if agent_count <= 1000 else 10,
            macro_feedback_interval=5 if agent_count <= 1000 else 10,
            polarization_interval=5 if agent_count <= 1000 else 10,
            kg_snapshot_interval=5 if agent_count <= 1000 else 10,
            attention_economy_interval=1 if agent_count <= 500 else 3,
            collective_action_interval=5 if agent_count <= 1000 else 10,
        )


@dataclass(frozen=True)
class SimPreset:
    """User-facing simulation preset."""

    name: str
    agents: int
    rounds: int
    mc_trials: int
    hook_config: HookConfig = field(default_factory=HookConfig)

    @classmethod
    def custom(
        cls,
        agents: int,
        rounds: int,
        mc_trials: int = 100,
    ) -> SimPreset:
        """Create a custom preset with auto-scaled HookConfig."""
        return cls(
            name="custom",
            agents=agents,
            rounds=rounds,
            mc_trials=mc_trials,
            hook_config=HookConfig.scaled(agents),
        )


PRESET_FAST = SimPreset(
    name="fast", agents=100, rounds=15, mc_trials=30,
    hook_config=HookConfig(emergence_enabled=False),
)
PRESET_STANDARD = SimPreset(
    name="standard", agents=300, rounds=20, mc_trials=50,
    hook_config=HookConfig(emergence_enabled=True),
)
PRESET_DEEP = SimPreset(
    name="deep", agents=500, rounds=30, mc_trials=100,
    hook_config=HookConfig(emergence_enabled=True),
)
PRESET_LARGE = SimPreset(
    name="large", agents=1000, rounds=25, mc_trials=200,
    hook_config=HookConfig.scaled(1000),
)
PRESET_MASSIVE = SimPreset(
    name="massive", agents=3000, rounds=20, mc_trials=300,
    hook_config=HookConfig.scaled(3000),
)

# Registry for lookup by name
PRESETS: dict[str, SimPreset] = {
    "fast": PRESET_FAST,
    "standard": PRESET_STANDARD,
    "deep": PRESET_DEEP,
    "large": PRESET_LARGE,
    "massive": PRESET_MASSIVE,
}


def resolve_preset(
    preset_name: str | None,
    agent_count: int | None = None,
    round_count: int | None = None,
    mc_trials: int | None = None,
) -> SimPreset:
    """Resolve a preset by name, or create a custom one.

    Args:
        preset_name: One of fast/standard/deep/large/massive/custom, or None.
        agent_count: Required when preset_name is "custom".
        round_count: Required when preset_name is "custom".
        mc_trials: Optional MC trial count for custom preset.

    Returns:
        Resolved SimPreset.

    Raises:
        ValueError: If preset_name is unknown or custom params are missing.
    """
    if not preset_name:
        return PRESET_STANDARD

    if preset_name == "custom":
        if not agent_count or not round_count:
            raise ValueError("custom preset requires agent_count and round_count")
        if agent_count > 50_000:
            raise ValueError("agent_count must be <= 50,000")
        if round_count > 100:
            raise ValueError("round_count must be <= 100")
        return SimPreset.custom(
            agents=agent_count,
            rounds=round_count,
            mc_trials=mc_trials or 100,
        )

    preset = PRESETS.get(preset_name)
    if preset is None:
        raise ValueError(
            f"Unknown preset '{preset_name}'. "
            f"Available: {sorted(PRESETS)}, 'custom'"
        )
    return preset
