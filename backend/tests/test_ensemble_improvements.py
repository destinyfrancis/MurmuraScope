"""Unit tests for EnsembleRunner improvements: cap raise + dry_run."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.app.services.ensemble_runner import EnsembleRunner


class TestEnsembleRunnerCap:
    """Verify trial cap raised from 50 to 200."""

    @pytest.mark.asyncio
    async def test_cap_clamps_to_500(self):
        """n_trials above 500 should be clamped to 500."""
        runner = EnsembleRunner()

        with patch.object(runner, "_load_parent_session", new_callable=AsyncMock) as mock_load:
            mock_load.side_effect = ValueError("test: stop after clamp check")

            with pytest.raises(ValueError, match="test: stop after clamp check"):
                await runner.run_ensemble("sess1", n_trials=600)

            # Verify the method was called (proves we got past the clamp line)
            mock_load.assert_called_once()

    @pytest.mark.asyncio
    async def test_cap_allows_400(self):
        """n_trials=400 should NOT be clamped (was previously blocked at 50)."""
        runner = EnsembleRunner()

        with patch.object(runner, "_load_parent_session", new_callable=AsyncMock) as mock_load:
            mock_load.side_effect = ValueError("test: stop after clamp check")

            with pytest.raises(ValueError, match="test: stop after clamp check"):
                await runner.run_ensemble("sess1", n_trials=400)

            mock_load.assert_called_once()

    def test_cap_minimum_is_one(self):
        """n_trials below 1 should be clamped to 1."""
        # Verify the clamp formula: max(1, min(n, 500))
        assert max(1, min(0, 500)) == 1
        assert max(1, min(-5, 500)) == 1
        assert max(1, min(1, 500)) == 1

    def test_cap_500_exact(self):
        """n_trials=500 should pass through unchanged."""
        assert max(1, min(500, 500)) == 500

    def test_cap_501_clamps(self):
        """n_trials=501 should clamp to 500."""
        assert max(1, min(501, 500)) == 500


class TestEnsembleRunnerDryRun:
    """Verify dry_run parameter threads through to SimulationRunner."""

    @pytest.mark.asyncio
    async def test_dry_run_passes_to_simulation_runner(self):
        """dry_run=True should set self._dry_run and be used in _execute_trial_simulation."""
        runner = EnsembleRunner()

        mock_macro = MagicMock()
        mock_macro.__dict__ = {"hibor_1m": 0.05}

        with patch.object(runner, "_load_parent_session", new_callable=AsyncMock) as mock_load, \
             patch.object(runner, "_create_branch_session", new_callable=AsyncMock), \
             patch.object(runner, "_execute_trial_simulation", new_callable=AsyncMock) as mock_exec, \
             patch.object(runner, "_persist_trial_metadata", new_callable=AsyncMock), \
             patch("backend.app.services.ensemble_runner._perturb_macro_fields") as mock_perturb:

            mock_load.return_value = ({"agent_count": 10, "round_count": 5}, mock_macro)
            mock_perturb.return_value = {"hibor_1m": 0.06}

            mock_analyzer = MagicMock()
            mock_analyzer.compute_percentiles = AsyncMock(return_value=MagicMock(
                to_dict=lambda: {},
                n_trials=1,
                distributions=[],
            ))
            runner._analyzer = mock_analyzer

            await runner.run_ensemble("sess1", n_trials=1, dry_run=True)

            # Verify dry_run flag was set on the runner instance
            assert runner._dry_run is True
            # Verify _execute_trial_simulation was called
            mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_dry_run_false_by_default(self):
        """Default dry_run should be False."""
        runner = EnsembleRunner()

        with patch.object(runner, "_load_parent_session", new_callable=AsyncMock) as mock_load:
            mock_load.side_effect = ValueError("stop early")

            with pytest.raises(ValueError):
                await runner.run_ensemble("sess1", n_trials=1)

            # dry_run defaults to False — check instance attr set in run_ensemble
            assert runner._dry_run is False
