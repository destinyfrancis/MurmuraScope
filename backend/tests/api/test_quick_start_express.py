"""Tests for extended quick-start endpoint (file upload, preset, scenario_question)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_zc_result() -> MagicMock:
    return MagicMock(
        domain_pack_id="hk_city",
        agent_count=100,
        round_count=15,
        preset_name="fast",
        seed_text="HSI drops 10%",
        detected_entities=["HSI"],
        estimated_duration_seconds=120,
    )


def _common_patches():
    """Return a context manager stacking all heavy-service patches."""
    mock_zc = MagicMock()
    mock_zc.prepare = AsyncMock(return_value=_mock_zc_result())

    mock_gb = MagicMock()
    mock_gb.build_graph = AsyncMock(return_value={"graph_id": "graph-abc-123"})

    mock_mgr = MagicMock()
    mock_mgr.create_session = AsyncMock(return_value={"session_id": "sess-xyz-456"})
    mock_mgr.start_session = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.generate_population = MagicMock(return_value=[])

    mock_macro = MagicMock()
    mock_macro.get_baseline_for_scenario = AsyncMock(return_value=MagicMock())

    mock_prof = MagicMock()
    mock_prof.to_oasis_csv = MagicMock(return_value="header\n")

    from contextlib import ExitStack
    from unittest.mock import patch as _patch

    stack = ExitStack()
    stack.enter_context(_patch("backend.app.api.simulation.ZeroConfigService", return_value=mock_zc, create=True))
    stack.enter_context(_patch("backend.app.services.zero_config.ZeroConfigService", return_value=mock_zc))
    stack.enter_context(_patch("backend.app.api.simulation.GraphBuilderService", return_value=mock_gb, create=True))
    stack.enter_context(_patch("backend.app.services.graph_builder.GraphBuilderService", return_value=mock_gb))
    stack.enter_context(_patch("backend.app.api.simulation.SimulationManager", return_value=mock_mgr))
    stack.enter_context(_patch("backend.app.api.simulation.AgentFactory", return_value=mock_factory))
    stack.enter_context(_patch("backend.app.api.simulation.MacroController", return_value=mock_macro))
    stack.enter_context(_patch("backend.app.api.simulation.ProfileGenerator", return_value=mock_prof))
    stack.enter_context(_patch("backend.app.api.simulation.store_agent_profiles", new_callable=AsyncMock))
    stack.enter_context(_patch("backend.app.api.simulation.store_activity_profiles", new_callable=AsyncMock))
    stack.enter_context(_patch("asyncio.to_thread", new_callable=AsyncMock))
    stack.enter_context(_patch("asyncio.create_task"))
    return stack


class TestQuickStartExpress:
    """Extended quick-start endpoint tests — mirrors TestQuickStartEndpoint pattern."""

    @pytest.mark.asyncio
    async def test_quick_start_returns_graph_id(self) -> None:
        """Response must include graph_id."""
        from backend.app.api.simulation import quick_start

        with _common_patches():
            resp = await quick_start({"seed_text": "HSI drops 10%"})

        assert resp.success is True
        assert resp.data["graph_id"] == "graph-abc-123"
        assert resp.data["session_id"] == "sess-xyz-456"

    @pytest.mark.asyncio
    async def test_quick_start_accepts_preset(self) -> None:
        """quick-start should accept preset param without error."""
        from backend.app.api.simulation import quick_start

        with _common_patches():
            resp = await quick_start({"seed_text": "HSI drops 10%", "preset": "fast"})

        assert resp.success is True

    @pytest.mark.asyncio
    async def test_quick_start_echoes_scenario_question(self) -> None:
        """quick-start must echo scenario_question back in response data."""
        from backend.app.api.simulation import quick_start

        with _common_patches():
            resp = await quick_start({
                "seed_text": "HSI drops 10%",
                "scenario_question": "Will unemployment rise above 4%?",
            })

        assert resp.data["scenario_question"] == "Will unemployment rise above 4%?"

    @pytest.mark.asyncio
    async def test_quick_start_upload_txt(self) -> None:
        """quick_start_upload should accept a text file and return session_id + graph_id."""
        from backend.app.api.simulation import quick_start_upload

        fake_file = MagicMock()
        fake_file.filename = "report.txt"
        fake_file.read = AsyncMock(return_value=b"HSI drops 10 percent. Unemployment rising.")

        with _common_patches():
            resp = await quick_start_upload(
                file=fake_file,
                scenario_question="Will GDP contract?",
                preset="fast",
            )

        assert resp.success is True
        assert "session_id" in resp.data
        assert "graph_id" in resp.data

    @pytest.mark.asyncio
    async def test_quick_start_upload_rejects_oversized(self) -> None:
        """quick_start_upload must reject files over 10 MB."""
        from fastapi import HTTPException
        from backend.app.api.simulation import quick_start_upload

        big_file = MagicMock()
        big_file.filename = "big.txt"
        big_file.read = AsyncMock(return_value=b"x" * (11 * 1024 * 1024))

        with pytest.raises(HTTPException) as exc_info:
            await quick_start_upload(file=big_file)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_quick_start_upload_rejects_bad_ext(self) -> None:
        """quick_start_upload must reject unsupported file extensions."""
        from fastapi import HTTPException
        from backend.app.api.simulation import quick_start_upload

        bad_file = MagicMock()
        bad_file.filename = "data.xlsx"
        bad_file.read = AsyncMock(return_value=b"some data")

        with pytest.raises(HTTPException) as exc_info:
            await quick_start_upload(file=bad_file)
        assert exc_info.value.status_code == 400
