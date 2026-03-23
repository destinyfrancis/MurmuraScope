"""Unit tests for MultiRunOrchestrator and helpers."""

import math


class TestWilsonCI:
    """_compute_confidence_intervals must implement true Wilson score, not Wald."""

    def test_wilson_upper_nonzero_at_p_zero(self):
        """At p=0, Wald gives [0,0] but Wilson must give [0, >0]."""
        from backend.app.services.multi_run_orchestrator import _compute_confidence_intervals

        ci = _compute_confidence_intervals({"zero": 0}, 30)
        lo, hi = ci["zero"]
        assert lo == 0.0
        assert hi > 0.10, f"Wilson upper at p=0, n=30 should be ~0.113, got {hi:.4f}"
        assert hi < 0.20, f"Wilson upper at p=0, n=30 should be ~0.113, got {hi:.4f}"

    def test_wilson_ci_asymmetric_at_low_p(self):
        """Wilson CI center > p̂ when p is small (due to z²/2n numerator shift)."""
        from backend.app.services.multi_run_orchestrator import _compute_confidence_intervals

        counts = {"rare": 2, "common": 48}
        ci = _compute_confidence_intervals(counts, 50)
        lo, hi = ci["rare"]
        p = 2 / 50  # 0.04
        ci_center = (lo + hi) / 2
        # Wilson center is shifted right of p̂ for low p
        assert ci_center > p, f"Wilson CI center {ci_center:.4f} should exceed p={p:.4f} for low-p Wilson"

    def test_wilson_differs_from_wald_at_small_n(self):
        """At n=20, p=0.1, Wilson and Wald must produce different intervals."""
        from backend.app.services.multi_run_orchestrator import _compute_confidence_intervals

        ci = _compute_confidence_intervals({"event": 2, "other": 18}, 20)
        lo_wilson, hi_wilson = ci["event"]
        # Wald manual computation
        p, n, z = 2 / 20, 20, 1.96
        margin_wald = z * math.sqrt(p * (1 - p) / n)
        lo_wald = max(0.0, p - margin_wald)
        hi_wald = min(1.0, p + margin_wald)
        # Must differ by more than numerical noise
        assert abs(lo_wilson - lo_wald) > 1e-4 or abs(hi_wilson - hi_wald) > 1e-4, (
            "Wilson and Wald CIs are identical — fix not applied"
        )

    def test_total_zero_returns_full_range(self):
        """When total=0, CI should be [0.0, 1.0] (maximal uncertainty)."""
        from backend.app.services.multi_run_orchestrator import _compute_confidence_intervals

        ci = _compute_confidence_intervals({"a": 0}, 0)
        lo, hi = ci["a"]
        assert lo == 0.0
        assert hi == 1.0

    def test_wilson_all_outcomes_in_one(self):
        """At p=1.0, Wilson gives asymmetric interval [~0.88, 1.0], not degenerate [1,1]."""
        from backend.app.services.multi_run_orchestrator import _compute_confidence_intervals

        ci = _compute_confidence_intervals({"all": 30}, 30)
        lo, hi = ci["all"]
        assert 0.88 < lo < 1.0, f"Wilson lower at p=1, n=30 should be ~0.884, got {lo:.4f}"
        assert hi == 1.0
