"""Tests for HookConfig, SimPreset, and service integration."""
import pytest

from backend.app.models.simulation_config import (
    HookConfig,
    SimPreset,
    PRESET_FAST,
    PRESET_STANDARD,
    PRESET_DEEP,
)


def test_hook_config_defaults():
    cfg = HookConfig()
    assert cfg.echo_chamber_interval == 5
    assert cfg.media_influence_interval == 5
    assert cfg.macro_feedback_interval == 5
    assert cfg.summarize_interval == 20
    assert cfg.summarize_salience_threshold == 0.3
    assert cfg.decision_sample_rate == 0.05
    assert cfg.decision_cap == 25
    assert cfg.llm_concurrency == 50


def test_hook_config_frozen():
    cfg = HookConfig()
    with pytest.raises(AttributeError):
        cfg.echo_chamber_interval = 10  # type: ignore[misc]


def test_preset_fast():
    assert PRESET_FAST.agents == 100
    assert PRESET_FAST.rounds == 15
    assert PRESET_FAST.mc_trials == 30
    assert PRESET_FAST.name == "fast"


def test_preset_standard():
    assert PRESET_STANDARD.agents == 300
    assert PRESET_STANDARD.rounds == 20
    assert PRESET_STANDARD.mc_trials == 50


def test_preset_deep():
    assert PRESET_DEEP.agents == 500
    assert PRESET_DEEP.rounds == 30
    assert PRESET_DEEP.mc_trials == 100


def test_custom_preset():
    custom = SimPreset(name="custom", agents=200, rounds=25, mc_trials=40)
    assert custom.agents == 200
    assert custom.hook_config.echo_chamber_interval == 5  # uses defaults


def test_runner_accepts_preset():
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner(preset=PRESET_FAST)
    assert runner._preset.agents == 100
    assert runner._preset.hook_config.echo_chamber_interval == 5


def test_runner_default_preset_is_standard():
    from backend.app.services.simulation_runner import SimulationRunner

    runner = SimulationRunner()
    assert runner._preset.name == "standard"


@pytest.mark.asyncio
async def test_memory_service_accepts_summarize_interval():
    from backend.app.services.agent_memory import AgentMemoryService

    svc = AgentMemoryService(summarize_interval=20, summarize_salience_threshold=0.3)
    assert svc._summarize_interval == 20
    assert svc._summarize_salience_threshold == 0.3


@pytest.mark.asyncio
async def test_memory_service_default_interval():
    from backend.app.services.agent_memory import AgentMemoryService

    svc = AgentMemoryService()
    assert svc._summarize_interval == 20


def test_decision_engine_uses_config_sampling():
    from backend.app.services.decision_engine import DecisionEngine

    cfg = HookConfig(decision_sample_rate=0.05, decision_cap=25)
    engine = DecisionEngine(hook_config=cfg)
    assert engine._sample_rate == 0.05
    assert engine._sample_cap == 25


def test_scaled_hook_config_emergence_always_enabled():
    """emergence_enabled must be True at any agent count (removal of 5000-agent cap).

    This test validates the config change only. The O(n²) performance fixes
    (profile caching + contagion neighbor indexing) are in Tasks 2-4.
    """
    cfg_small = HookConfig.scaled(1000)
    cfg_large = HookConfig.scaled(5001)
    cfg_xlarge = HookConfig.scaled(10000)
    assert cfg_small.emergence_enabled is True
    assert cfg_large.emergence_enabled is True   # was False before fix
    assert cfg_xlarge.emergence_enabled is True  # was False before fix


def test_scaled_hook_config_intervals_widen_for_large_populations():
    """Interval widening (every 10 rounds instead of 5) should still apply for large n."""
    cfg = HookConfig.scaled(5001)
    assert cfg.echo_chamber_interval == 10
    assert cfg.macro_feedback_interval == 10
