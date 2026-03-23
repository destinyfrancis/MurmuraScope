"""Unit tests for _compute_risk_appetite smooth sigmoid function."""

from __future__ import annotations

from backend.app.services.cognitive_agent_engine import _compute_risk_appetite


class TestRiskAppetiteSigmoid:
    """Verify continuous sigmoid replaces the old step function."""

    def test_default_values_returns_neutral(self):
        """Empty emotional state → 0.5 (neutral)."""
        result = _compute_risk_appetite({})
        assert 0.48 <= result <= 0.52

    def test_low_arousal_returns_near_neutral(self):
        """Low arousal should produce near-neutral regardless of valence."""
        for valence in [-0.8, -0.3, 0.0, 0.3, 0.8]:
            result = _compute_risk_appetite({"valence": valence, "arousal": 0.1})
            assert 0.45 <= result <= 0.55, f"arousal=0.1, valence={valence} → {result}, expected [0.45, 0.55]"

    def test_high_arousal_neg_valence_cautious(self):
        """High arousal + strong negative valence → cautious (< 0.35)."""
        result = _compute_risk_appetite({"valence": -0.6, "arousal": 0.8})
        assert result < 0.35, f"Expected < 0.35, got {result}"

    def test_high_arousal_pos_valence_bold(self):
        """High arousal + strong positive valence → bold (> 0.65)."""
        result = _compute_risk_appetite({"valence": 0.6, "arousal": 0.8})
        assert result > 0.65, f"Expected > 0.65, got {result}"

    def test_continuity_no_cliff(self):
        """No adjacent arousal step should produce > 0.05 jump."""
        valence = -0.5
        prev = _compute_risk_appetite({"valence": valence, "arousal": 0.4})
        for a_int in range(41, 71):
            arousal = a_int / 100.0
            current = _compute_risk_appetite({"valence": valence, "arousal": arousal})
            diff = abs(current - prev)
            assert diff < 0.05, (
                f"Cliff detected: arousal {arousal - 0.01:.2f}→{arousal:.2f}, "
                f"risk {prev:.4f}→{current:.4f} (diff={diff:.4f})"
            )
            prev = current

    def test_symmetry(self):
        """risk(v) + risk(-v) ≈ 1.0 for fixed arousal."""
        for arousal in [0.3, 0.5, 0.7, 0.9]:
            for valence in [0.1, 0.3, 0.5, 0.8]:
                pos = _compute_risk_appetite({"valence": valence, "arousal": arousal})
                neg = _compute_risk_appetite({"valence": -valence, "arousal": arousal})
                assert abs((pos + neg) - 1.0) < 0.02, f"arousal={arousal}, v={valence}: pos={pos}+neg={neg}={pos + neg}"

    def test_boundary_clamping(self):
        """Extreme inputs never exceed [0.1, 0.9]."""
        extremes = [
            {"valence": -1.0, "arousal": 1.0},
            {"valence": 1.0, "arousal": 1.0},
            {"valence": -1.0, "arousal": 0.0},
            {"valence": 1.0, "arousal": 0.0},
        ]
        for state in extremes:
            result = _compute_risk_appetite(state)
            assert 0.1 <= result <= 0.9, f"state={state} → {result}, out of [0.1, 0.9]"

    def test_monotonicity_with_arousal(self):
        """For positive valence, increasing arousal → increasing appetite."""
        valence = 0.5
        prev = _compute_risk_appetite({"valence": valence, "arousal": 0.0})
        for a_int in range(1, 11):
            arousal = a_int / 10.0
            current = _compute_risk_appetite({"valence": valence, "arousal": arousal})
            assert current >= prev - 0.001, (
                f"Non-monotonic: arousal {(a_int - 1) / 10:.1f}→{arousal:.1f}, risk {prev:.4f}→{current:.4f}"
            )
            prev = current

    def test_monotonicity_neg_valence_decreasing(self):
        """For negative valence, increasing arousal → decreasing appetite."""
        valence = -0.5
        prev = _compute_risk_appetite({"valence": valence, "arousal": 0.0})
        for a_int in range(1, 11):
            arousal = a_int / 10.0
            current = _compute_risk_appetite({"valence": valence, "arousal": arousal})
            assert current <= prev + 0.001, (
                f"Non-monotonic: arousal {(a_int - 1) / 10:.1f}→{arousal:.1f}, risk {prev:.4f}→{current:.4f}"
            )
            prev = current
