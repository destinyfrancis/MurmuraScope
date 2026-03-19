"""Tests for kg_driven quick-start support."""
from backend.app.models.project import SimMode


def test_simmode_has_kg_driven():
    assert hasattr(SimMode, "KG_DRIVEN")
    assert SimMode.KG_DRIVEN.value == "kg_driven"


from backend.app.services.simulation_manager import _infer_sim_mode


def test_infer_sim_mode_kg_driven():
    assert _infer_sim_mode("kg_driven") == SimMode.KG_DRIVEN


def test_infer_sim_mode_property_unchanged():
    assert _infer_sim_mode("property") == SimMode.LIFE_DECISION


import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_run_quick_start_kg_driven_mode():
    """When seed text is geopolitical, quick-start should use kg_driven path."""
    from backend.app.api.simulation import _run_quick_start

    mock_zc = MagicMock()
    mock_zc_result = MagicMock()
    mock_zc_result.mode = "kg_driven"
    mock_zc_result.domain_pack_id = "global_macro"
    mock_zc.prepare = AsyncMock(return_value=mock_zc_result)
    mock_zc.infer_time_config = AsyncMock(
        return_value=MagicMock(to_dict=lambda: {"minutes_per_round": 1440, "round_label_unit": "day"})
    )

    mock_graph = MagicMock()
    mock_graph.build_graph = AsyncMock(return_value={"graph_id": "graph_test_123"})

    mock_manager = MagicMock()
    mock_manager.create_session = AsyncMock(return_value={"session_id": "sess-123"})
    mock_manager.start_session = AsyncMock()

    mock_gen_agents = AsyncMock(return_value=([], "/tmp/agents.csv"))

    with patch("backend.app.services.zero_config.ZeroConfigService", return_value=mock_zc), \
         patch("backend.app.services.graph_builder.GraphBuilderService", return_value=mock_graph), \
         patch("backend.app.api.simulation.get_simulation_manager", return_value=mock_manager), \
         patch("backend.app.api.simulation.generate_agents", mock_gen_agents), \
         patch("backend.app.api.simulation.store_universal_agent_profiles", new_callable=AsyncMock), \
         patch("backend.app.models.simulation_config.resolve_preset", return_value=MagicMock(agents=100, rounds=30)), \
         patch("backend.app.utils.prompt_security.sanitize_seed_text", side_effect=lambda x: x), \
         patch("asyncio.create_task"):

        result = await _run_quick_start("USA and Iran enter full military conflict.", "predict oil prices", "standard")

    # Verify kg_driven path was taken
    create_call = mock_manager.create_session.call_args[0][0]
    assert create_call["scenario_type"] == "kg_driven"
    mock_gen_agents.assert_called_once()
    gen_kwargs = mock_gen_agents.call_args
    assert gen_kwargs.kwargs.get("mode") == "kg_driven" or gen_kwargs[1].get("mode") == "kg_driven"
    assert result.data["mode"] == "kg_driven"


@pytest.mark.asyncio
async def test_run_quick_start_hk_mode_unchanged():
    """When seed text is HK-related, quick-start should use hk_demographic path."""
    from backend.app.api.simulation import _run_quick_start

    mock_zc = MagicMock()
    mock_zc_result = MagicMock()
    mock_zc_result.mode = "hk_demographic"
    mock_zc_result.domain_pack_id = "hk_city"
    mock_zc.prepare = AsyncMock(return_value=mock_zc_result)
    mock_zc.infer_time_config = AsyncMock(
        return_value=MagicMock(to_dict=lambda: {"minutes_per_round": 1440, "round_label_unit": "day"})
    )

    mock_graph = MagicMock()
    mock_graph.build_graph = AsyncMock(return_value={"graph_id": "graph_hk_123"})

    mock_manager = MagicMock()
    mock_manager.create_session = AsyncMock(return_value={"session_id": "sess-hk"})
    mock_manager.start_session = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.generate_population = MagicMock(return_value=[])
    mock_macro = MagicMock()
    mock_macro.get_baseline_for_scenario = AsyncMock(return_value=MagicMock())
    mock_profile_gen = MagicMock()
    mock_profile_gen.to_oasis_csv = MagicMock(return_value="userid,user_char,username\n")

    with patch("backend.app.services.zero_config.ZeroConfigService", return_value=mock_zc), \
         patch("backend.app.services.graph_builder.GraphBuilderService", return_value=mock_graph), \
         patch("backend.app.api.simulation.get_simulation_manager", return_value=mock_manager), \
         patch("backend.app.api.simulation.AgentFactory", return_value=mock_factory), \
         patch("backend.app.api.simulation.MacroController", return_value=mock_macro), \
         patch("backend.app.api.simulation.ProfileGenerator", return_value=mock_profile_gen), \
         patch("backend.app.models.simulation_config.resolve_preset", return_value=MagicMock(agents=100, rounds=15)), \
         patch("backend.app.utils.prompt_security.sanitize_seed_text", side_effect=lambda x: x), \
         patch("backend.app.api.simulation.store_agent_profiles", new_callable=AsyncMock), \
         patch("backend.app.api.simulation.store_activity_profiles", new_callable=AsyncMock), \
         patch("asyncio.to_thread", new_callable=AsyncMock), \
         patch("asyncio.create_task"):

        result = await _run_quick_start("香港樓市最新走勢", "", "fast")

    create_call = mock_manager.create_session.call_args[0][0]
    assert create_call["scenario_type"] == "property"
    assert result.data["mode"] == "hk_demographic"


def test_agent_interview_accepts_string_id():
    """Interview endpoint should accept both int and string agent IDs."""
    from backend.app.models.request import AgentInterviewRequest

    # String ID (kg_driven agent)
    req = AgentInterviewRequest(
        session_id="test-sess",
        agent_id="iran_supreme_leader",
        question="What is your strategy?",
    )
    assert req.agent_id == "iran_supreme_leader"

    # Int ID (HK agent) — should still work
    req2 = AgentInterviewRequest(
        session_id="test-sess",
        agent_id=42,
        question="What do you think?",
    )
    assert req2.agent_id == 42
