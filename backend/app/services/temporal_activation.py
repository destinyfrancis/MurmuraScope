"""Temporal activation service for MurmuraScope agents.

Maps simulation round numbers to clock hours and performs Bernoulli
activation sampling based on each agent's 24-dim activity vector.

Design:
  - Simulation clock starts at _START_HOUR (08:00 HKT, morning commute).
  - Each round advances the clock by one simulated hour.
  - Activation: p = activity_vector[hour] × base_rate, floored at 0.05.
  - Agents without a profile default to always active (backward compatible).
"""

from __future__ import annotations

import random

from backend.app.models.activity_profile import ActivityProfile, Chronotype

# ---------------------------------------------------------------------------
# Hourly activity templates (relative probabilities in [0.0, 1.0])
# ---------------------------------------------------------------------------
# Each entry is a 24-float tuple: index 0 = midnight, index 8 = 8 AM.
_CHRONOTYPE_TEMPLATES: dict[str, tuple[float, ...]] = {
    # Peaks 06–10 AM (elderly, retirees, early risers)
    "morning_lark": (
        0.08,
        0.05,
        0.03,
        0.03,
        0.06,
        0.22,  # 00–05
        0.65,
        0.92,
        1.00,
        0.82,
        0.70,
        0.58,  # 06–11
        0.48,
        0.40,
        0.32,
        0.30,
        0.38,
        0.28,  # 12–17
        0.20,
        0.18,
        0.14,
        0.12,
        0.10,
        0.09,  # 18–23
    ),
    # Peaks 08–11 AM and 19–22 PM (nine-to-five workers)
    "standard": (
        0.05,
        0.03,
        0.02,
        0.02,
        0.03,
        0.10,  # 00–05
        0.30,
        0.62,
        0.72,
        0.72,
        0.62,
        0.50,  # 06–11
        0.42,
        0.50,
        0.50,
        0.52,
        0.60,
        0.70,  # 12–17
        0.80,
        0.90,
        1.00,
        0.82,
        0.52,
        0.20,  # 18–23
    ),
    # Peaks 19 PM–midnight (students, young adults, night owls)
    "evening_owl": (
        0.32,
        0.22,
        0.12,
        0.06,
        0.03,
        0.03,  # 00–05
        0.05,
        0.12,
        0.22,
        0.32,
        0.42,
        0.42,  # 06–11
        0.32,
        0.32,
        0.32,
        0.42,
        0.52,
        0.62,  # 12–17
        0.80,
        0.92,
        1.00,
        0.90,
        0.72,
        0.52,  # 18–23
    ),
    # Peaks 00–04 AM and 20–23 PM (security, transport, manual workers)
    "night_shift": (
        0.92,
        1.00,
        0.90,
        0.72,
        0.42,
        0.20,  # 00–05
        0.10,
        0.06,
        0.05,
        0.10,
        0.20,
        0.30,  # 06–11
        0.30,
        0.22,
        0.12,
        0.12,
        0.20,
        0.32,  # 12–17
        0.52,
        0.62,
        0.72,
        0.82,
        0.90,
        0.92,  # 18–23
    ),
}

# Simulation clock starts at 08:00 HKT (morning commute peak).
_START_HOUR: int = 8

# Minimum per-round activation probability (guarantees some activity even at off-peak hours).
_MIN_ACTIVATION_P: float = 0.05

# Occupations with elevated night-shift probability.
_NIGHT_SHIFT_OCCUPATIONS: frozenset[str] = frozenset({"非技術工人", "機台及機器操作員", "服務及銷售人員"})


class TemporalActivationService:
    """Generate and evaluate 24-dim temporal activity profiles."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def round_to_hour(self, round_number: int) -> int:
        """Map a simulation round number to a 24-hour clock hour.

        Round 0 begins at 08:00 HKT.  Each round advances by one
        simulated hour; the clock wraps every 24 rounds.
        """
        return (_START_HOUR + round_number) % 24

    def should_activate(
        self,
        profile: ActivityProfile,
        round_number: int,
        rng: random.Random,
    ) -> bool:
        """Return True if the agent should act in this round.

        Performs a Bernoulli draw with
        p = max(_MIN_ACTIVATION_P, profile.probability_at_hour(hour)).
        The floor prevents agents from being completely silent.
        """
        hour = self.round_to_hour(round_number)
        p = max(_MIN_ACTIVATION_P, profile.probability_at_hour(hour))
        return rng.random() < p

    def generate_profile(
        self,
        agent_id: int,
        age: int,
        occupation: str,
        rng: random.Random,
    ) -> ActivityProfile:
        """Generate an ActivityProfile based on demographic characteristics.

        Chronotype assignment rules:
          - age >= 65 or occupation == '退休'  →  morning_lark (60 %)
          - age < 25  or occupation == '學生'  →  evening_owl  (60 %)
          - night-shift occupations            →  night_shift  (30 %)
          - all others                         →  standard     (60 %)

        The activity vector is built from the chronotype template with
        per-slot Gaussian noise (σ = 0.08), clamped to [0.0, 1.0].
        The base_activity_rate is drawn from N(0.65, 0.15), clamped to
        (0.10, 1.0].
        """
        chronotype = self._assign_chronotype(age, occupation, rng)
        template = _CHRONOTYPE_TEMPLATES[chronotype]

        # Add per-slot noise to personalise the activity curve.
        vector: tuple[float, ...] = tuple(max(0.0, min(1.0, round(v + rng.gauss(0.0, 0.08), 4))) for v in template)

        base_rate = max(0.10, min(1.0, round(rng.gauss(0.65, 0.15), 3)))

        return ActivityProfile(
            agent_id=agent_id,
            chronotype=chronotype,
            activity_vector=vector,
            base_activity_rate=base_rate,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assign_chronotype(
        self,
        age: int,
        occupation: str,
        rng: random.Random,
    ) -> Chronotype:
        """Assign a chronotype based on age and occupation."""
        if age >= 65 or occupation == "退休":
            return rng.choices(
                ["morning_lark", "standard"],
                weights=[0.60, 0.40],
            )[0]  # type: ignore[return-value]

        if age < 25 or occupation == "學生":
            return rng.choices(
                ["evening_owl", "standard"],
                weights=[0.60, 0.40],
            )[0]  # type: ignore[return-value]

        if occupation in _NIGHT_SHIFT_OCCUPATIONS:
            return rng.choices(
                ["night_shift", "standard", "morning_lark"],
                weights=[0.30, 0.50, 0.20],
            )[0]  # type: ignore[return-value]

        return rng.choices(
            ["standard", "morning_lark", "evening_owl"],
            weights=[0.60, 0.25, 0.15],
        )[0]  # type: ignore[return-value]
