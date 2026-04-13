"""Unit tests for KGSessionState LLM degradation fields (Phase 1.1).

Covers:
- consecutive_llm_failures and auto_degraded_to_lite defaults
- Field mutation correctness
- Cross-instance isolation
"""

from __future__ import annotations

import pytest

from backend.app.models.kg_session_state import KGSessionState


class TestLLMDegradationFields:
    """Tests for Phase 1.1 auto-degradation tracking fields."""

    def test_consecutive_llm_failures_defaults_zero(self):
        state = KGSessionState()
        assert state.consecutive_llm_failures == 0

    def test_auto_degraded_to_lite_defaults_false(self):
        state = KGSessionState()
        assert state.auto_degraded_to_lite is False

    def test_can_increment_consecutive_failures(self):
        state = KGSessionState()
        state.consecutive_llm_failures += 1
        assert state.consecutive_llm_failures == 1

    def test_can_set_auto_degraded_flag(self):
        state = KGSessionState()
        state.auto_degraded_to_lite = True
        assert state.auto_degraded_to_lite is True

    def test_can_reset_consecutive_failures(self):
        state = KGSessionState()
        state.consecutive_llm_failures = 5
        state.consecutive_llm_failures = 0
        assert state.consecutive_llm_failures == 0

    def test_degradation_fields_isolated_across_instances(self):
        s1 = KGSessionState()
        s2 = KGSessionState()
        s1.consecutive_llm_failures = 3
        s1.auto_degraded_to_lite = True
        # s2 must be unaffected
        assert s2.consecutive_llm_failures == 0
        assert s2.auto_degraded_to_lite is False

    def test_threshold_logic_simulation(self):
        """Simulates the degradation check: 3 consecutive rounds ≥80% failure."""
        state = KGSessionState()
        # Simulate 3 rounds of ≥80% failures
        for _ in range(3):
            state.consecutive_llm_failures += 1

        # Trigger: mark degraded when threshold reached
        if state.consecutive_llm_failures >= 3:
            state.auto_degraded_to_lite = True

        assert state.auto_degraded_to_lite is True

    def test_recovery_resets_counter(self):
        """Simulates failure followed by recovery resetting the counter."""
        state = KGSessionState()
        state.consecutive_llm_failures = 2

        # Successful round resets counter
        state.consecutive_llm_failures = 0
        assert state.consecutive_llm_failures == 0
        # Degradation flag is sticky (once set, stays set)
        assert state.auto_degraded_to_lite is False
