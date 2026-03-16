"""Nonlinear shock modifiers: regime switching, threshold effects, and interaction terms.

Provides regime detection (crisis/normal/boom) and amplification/dampening of
macro shocks based on the current economic regime.  Interaction terms model
compounding effects when multiple shocks occur simultaneously.

All functions are pure — they return new dicts of adjustments without mutating
any input state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regime detection
# ---------------------------------------------------------------------------

# Long-run HSI statistics (2000-2024 approximate)
_HSI_MEAN: float = 22_000.0
_HSI_STD: float = 5_000.0

# Threshold constants for regime boundaries
_UNEMPLOYMENT_CRISIS: float = 0.06
_UNEMPLOYMENT_BOOM: float = 0.03
_CONFIDENCE_CRISIS: float = 30.0
_CONFIDENCE_BOOM: float = 80.0


@dataclass(frozen=True)
class RegimeState:
    """Immutable snapshot of the detected economic regime.

    Attributes:
        regime: One of "crisis", "normal", or "boom".
        hsi_zscore: Standardised deviation of HSI from historical mean.
        unemployment_deviation: Current unemployment minus long-run average (~3.5%).
        confidence_level: Consumer confidence index value.
    """

    regime: str
    hsi_zscore: float
    unemployment_deviation: float
    confidence_level: float


def detect_regime(macro_state: Any) -> RegimeState:
    """Detect the current economic regime from macro indicators.

    Rules:
        crisis:  HSI z-score < -2  OR  unemployment > 6%  OR  confidence < 30
        boom:    HSI z-score > +2  OR  unemployment < 3%  OR  confidence > 80
        normal:  everything else

    Args:
        macro_state: MacroState frozen dataclass instance.

    Returns:
        Frozen ``RegimeState`` describing the detected regime.
    """
    hsi = getattr(macro_state, "hsi_level", _HSI_MEAN)
    unemployment = getattr(macro_state, "unemployment_rate", 0.035)
    confidence = getattr(macro_state, "consumer_confidence", 55.0)

    hsi_zscore = (hsi - _HSI_MEAN) / _HSI_STD if _HSI_STD > 0 else 0.0
    unemployment_deviation = unemployment - 0.035  # long-run HK average

    # Crisis takes priority over boom when both conditions are met
    if hsi_zscore < -2.0 or unemployment > _UNEMPLOYMENT_CRISIS or confidence < _CONFIDENCE_CRISIS:
        regime = "crisis"
    elif hsi_zscore > 2.0 or unemployment < _UNEMPLOYMENT_BOOM or confidence > _CONFIDENCE_BOOM:
        regime = "boom"
    else:
        regime = "normal"

    return RegimeState(
        regime=regime,
        hsi_zscore=round(hsi_zscore, 3),
        unemployment_deviation=round(unemployment_deviation, 4),
        confidence_level=confidence,
    )


# ---------------------------------------------------------------------------
# Regime multipliers
# ---------------------------------------------------------------------------

_REGIME_MULTIPLIERS: dict[str, dict[str, float]] = {
    "crisis": {"negative": 1.5, "positive": 0.7},
    "normal": {"negative": 1.0, "positive": 1.0},
    "boom":   {"negative": 0.8, "positive": 1.3},
}


def _classify_shock_direction(shock_type: str) -> str:
    """Classify whether a shock type is generally negative or positive.

    Returns "negative" or "positive".
    """
    _POSITIVE_SHOCKS = frozenset({
        "market_rally", "fed_rate_cut", "china_stimulus",
        "taiwan_strait_ease", "greater_bay_boost", "rcep_benefit",
    })
    if shock_type in _POSITIVE_SHOCKS:
        return "positive"
    return "negative"


# ---------------------------------------------------------------------------
# Threshold effects
# ---------------------------------------------------------------------------

_THRESHOLD_EFFECTS: dict[str, dict[str, Any]] = {
    "ccl_panic": {
        "trigger_field": "ccl_index",
        "trigger_op": "lt",
        "trigger_value": 100.0,
        "multiplier": 2.0,
        "fields": ("consumer_confidence", "net_migration"),
    },
    "unemployment_crisis": {
        "trigger_field": "unemployment_rate",
        "trigger_op": "gt",
        "trigger_value": 0.08,
        "multiplier": 1.8,
        "fields": ("gdp_growth", "consumer_confidence"),
    },
}


def _check_thresholds(
    macro_state: Any, base_adjustments: dict[str, float]
) -> dict[str, float]:
    """Amplify adjustments when macro indicators cross critical thresholds.

    Args:
        macro_state: Current MacroState.
        base_adjustments: Dict of field -> delta from the primary shock.

    Returns:
        New dict with amplified values where thresholds are triggered.
    """
    result = dict(base_adjustments)

    for _name, effect in _THRESHOLD_EFFECTS.items():
        field_val = getattr(macro_state, effect["trigger_field"], None)
        if field_val is None:
            continue

        triggered = False
        if effect["trigger_op"] == "lt" and field_val < effect["trigger_value"]:
            triggered = True
        elif effect["trigger_op"] == "gt" and field_val > effect["trigger_value"]:
            triggered = True

        if triggered:
            for field in effect["fields"]:
                if field in result:
                    result[field] = result[field] * effect["multiplier"]
                    logger.debug(
                        "Threshold %s triggered: %s *= %.1f",
                        _name, field, effect["multiplier"],
                    )

    return result


# ---------------------------------------------------------------------------
# Interaction terms (compounding shocks)
# ---------------------------------------------------------------------------

_INTERACTION_TERMS: dict[
    tuple[str, str], dict[str, float]
] = {
    ("interest_rate_hike", "china_slowdown"): {
        "hsi_level": -0.05,
        "consumer_confidence": -3.0,
    },
    ("property_crash", "unemployment_spike"): {
        "gdp_growth": -0.01,
        "net_migration": -10000,
    },
    ("fed_rate_hike", "taiwan_strait_tension"): {
        "hsi_level": -0.08,
        "consumer_confidence": -5.0,
    },
}


def _compute_interaction_effects(
    shock_type: str, active_shocks: tuple[str, ...]
) -> dict[str, float]:
    """Compute additional adjustments from shock interactions.

    Checks both orderings of (shock_type, active_shock) to find matches.

    Args:
        shock_type: The shock currently being applied.
        active_shocks: Other shocks already active in this simulation step.

    Returns:
        Dict of additional field adjustments from interaction terms.
    """
    extras: dict[str, float] = {}

    for other in active_shocks:
        if other == shock_type:
            continue
        # Check both orderings
        pair_key = (shock_type, other)
        reverse_key = (other, shock_type)

        effects = _INTERACTION_TERMS.get(pair_key) or _INTERACTION_TERMS.get(reverse_key)
        if effects:
            for field, delta in effects.items():
                extras[field] = extras.get(field, 0.0) + delta
                logger.debug(
                    "Interaction (%s, %s): %s += %.4f",
                    shock_type, other, field, delta,
                )

    return extras


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_nonlinear_shock(
    state: Any,
    shock_type: str,
    base_adjustments: dict[str, float],
    active_shocks: tuple[str, ...] = (),
) -> dict[str, float]:
    """Apply regime-switching multiplier, threshold effects, and interaction terms.

    This function takes the *base_adjustments* already computed by the primary
    shock handler and returns an enhanced set of adjustments that account for:

    1. **Regime multiplier** -- amplifies negative shocks in crisis, dampens in boom.
    2. **Threshold effects** -- when indicators cross critical levels (e.g. CCL < 100).
    3. **Interaction terms** -- compounding effects from simultaneous shocks.

    Args:
        state: Current MacroState (frozen dataclass).
        shock_type: Name of the shock being applied.
        base_adjustments: Dict of field-name -> delta from the primary handler.
        active_shocks: Other shocks active in the current step.

    Returns:
        New dict of field adjustments (may include additional fields from interactions).
    """
    if not base_adjustments:
        return {}

    # Step 1: Detect regime and apply multiplier
    regime = detect_regime(state)
    direction = _classify_shock_direction(shock_type)
    multiplier = _REGIME_MULTIPLIERS.get(regime.regime, {}).get(direction, 1.0)

    scaled: dict[str, float] = {
        field: delta * multiplier for field, delta in base_adjustments.items()
    }

    # Step 2: Threshold amplification
    scaled = _check_thresholds(state, scaled)

    # Step 3: Interaction terms (additive on top of scaled adjustments)
    interactions = _compute_interaction_effects(shock_type, active_shocks)
    for field, extra in interactions.items():
        scaled[field] = scaled.get(field, 0.0) + extra

    return scaled


# ---------------------------------------------------------------------------
# Simplified regime API (task spec — multi-signal crisis scoring)
# ---------------------------------------------------------------------------

_SIMPLE_REGIME_MULTIPLIERS: dict[str, float] = {
    "normal": 1.0,
    "stress": 1.4,   # shocks hit 40% harder in stress
    "crisis": 2.1,   # shocks hit 2.1x in crisis (asymmetry: crises amplify shocks)
}


def _detect_regime(state: Any) -> str:
    """Classify macro state into crisis/stress/normal regime.

    Uses a signal-counting approach: each deteriorated indicator contributes
    one crisis signal.  Threshold effects observed in real financial crises
    motivate the three-tier classification.

    Args:
        state: MacroState or any object with the relevant attributes.

    Returns:
        One of "crisis", "stress", or "normal".
    """
    crisis_signals = 0
    if getattr(state, "unemployment_rate", 4.0) > 6.0:
        crisis_signals += 1
    if getattr(state, "hsi_level", 20_000) < 15_000:
        crisis_signals += 1
    if getattr(state, "ccl_index", 150) < 120:
        crisis_signals += 1
    if getattr(state, "consumer_confidence", 50) < 35:
        crisis_signals += 1
    if getattr(state, "gdp_growth", 2.0) < -2.0:
        crisis_signals += 1

    if crisis_signals >= 3:
        return "crisis"
    if crisis_signals >= 1:
        return "stress"
    return "normal"


def _regime_multiplier(regime: str) -> float:
    """Return the shock amplitude multiplier for the given regime.

    Args:
        regime: One of "crisis", "stress", or "normal".

    Returns:
        Float multiplier (crisis > stress > normal).
    """
    return _SIMPLE_REGIME_MULTIPLIERS.get(regime, 1.0)


def compute_shock_interaction(
    shock_a_delta: float,
    shock_b_delta: float,
    sensitivity: float = 0.5,
) -> float:
    """Nonlinear interaction term for simultaneous shocks.

    When two shocks act in the same direction, their combined effect exceeds
    simple additivity (vulnerability stacking effect observed in compounding
    crises such as the 1997-98 AFC and 2020 COVID shock).

    Args:
        shock_a_delta: Effect of shock A (negative = bad).
        shock_b_delta: Effect of shock B (negative = bad).
        sensitivity: Interaction strength (0 = additive, 1 = fully multiplicative).
            Defaults to 0.5.

    Returns:
        Additional impact beyond simple addition.  Always <= 0 when both
        inputs are negative, always >= 0 when both are positive, and 0.0
        when shocks are in opposite directions.
    """
    # Interaction only amplifies when both shocks are in the same direction
    if shock_a_delta * shock_b_delta > 0:
        return sensitivity * shock_a_delta * shock_b_delta
    return 0.0


# ---------------------------------------------------------------------------
# NonlinearShockEngine — object-oriented façade
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShockApplicationResult:
    """Immutable result of a nonlinear shock application.

    Attributes:
        base_effect: The raw (pre-amplification) shock delta.
        regime: Detected regime string ("crisis" / "stress" / "normal").
        regime_multiplier: Float multiplier applied to the base effect.
        interaction_bonus: Additional delta from shock interaction term.
        total_effect: Sum of all components (amplified base + concurrent + interaction).
    """

    base_effect: float
    regime: str
    regime_multiplier: float
    interaction_bonus: float
    total_effect: float


class NonlinearShockEngine:
    """Applies macro shocks with regime-dependent amplification and interaction effects.

    Combines the simplified three-regime classifier (``_detect_regime``) with
    the nonlinear interaction term (``compute_shock_interaction``) to produce a
    single consolidated ``ShockApplicationResult``.

    This class is stateless; all methods are pure functions over the inputs.
    """

    def apply_shock(
        self,
        state: Any,
        shock_delta: float,
        concurrent_shock_delta: float = 0.0,
    ) -> ShockApplicationResult:
        """Apply a shock with regime amplification and optional concurrent-shock interaction.

        Args:
            state: Current MacroState (or compatible object with macro attributes).
            shock_delta: Primary shock delta (negative = adverse).
            concurrent_shock_delta: Delta of a second simultaneous shock.
                Defaults to 0.0 (no concurrent shock).

        Returns:
            Frozen ``ShockApplicationResult`` with all components.
        """
        regime = _detect_regime(state)
        mult = _regime_multiplier(regime)

        amplified_primary = shock_delta * mult
        amplified_concurrent = concurrent_shock_delta * mult

        interaction = compute_shock_interaction(amplified_primary, amplified_concurrent)
        total = amplified_primary + amplified_concurrent + interaction

        return ShockApplicationResult(
            base_effect=shock_delta,
            regime=regime,
            regime_multiplier=mult,
            interaction_bonus=interaction,
            total_effect=total,
        )
