"""Political spectrum model for HKSimEngine Phase 6.

Models political stance assignment, echo chamber detection, and
spiral of silence theory for Hong Kong society simulation agents.

Political stance scale:
  0.0 = 建制派 (pro-establishment)
  0.5 = 中間派 (centrist)
  1.0 = 民主派 (pro-democracy)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("political_model")

# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PoliticalProfile:
    """Immutable political profile snapshot for a single agent."""

    agent_id: int
    political_stance: float          # 0.0–1.0
    political_label: str             # 建制派 / 中間派 / 民主派
    engagement_willingness: float    # 0.0–1.0, spiral of silence factor


@dataclass(frozen=True)
class StanceReport:
    """Population-level stance distribution snapshot (immutable)."""

    mean: float
    std: float
    skewness: float
    polarization_index: float   # bimodality coefficient, 0–1
    extremism_ratio: float      # fraction with stance < 0.1 or > 0.9
    alert_level: str            # "normal" | "warning" | "critical"


# ---------------------------------------------------------------------------
# District and education lean constants
# ---------------------------------------------------------------------------

# District lean values are informed by 2019 District Council election results
# and HKUPOP/PORI longitudinal surveys (2012-2019) showing geographic variation
# in political attitudes.  Positive = more pro-democracy, negative = more
# pro-establishment.  Post-2020 NSL era data is less available; these values
# represent the structural baseline from the 2012-2019 trend.
# Source: HKUPOP "People's Satisfaction with Hong Kong" half-yearly surveys;
#         PORI "Political Attitudes" tracking polls (2012–2019);
#         2019 District Council election vote share by district.
_DISTRICT_LEAN: dict[str, float] = {
    "中西區": -0.05,
    "灣仔":   -0.03,
    "東區":    0.02,
    "南區":    0.00,
    "油尖旺":  0.03,
    "深水埗":  0.05,
    "九龍城":  0.02,
    "黃大仙": -0.02,
    "觀塘":    0.04,
    "葵青":    0.01,
    "荃灣":   -0.01,
    "屯門":    0.01,
    "元朗":   -0.04,
    "北區":   -0.03,
    "大埔":    0.02,
    "沙田":    0.03,
    "西貢":    0.02,
    "離島":   -0.02,
}

# Education lean values are derived from HKUPOP "Political Attitudes by
# Education Level" tracking data (2012-2019).  University-educated respondents
# consistently showed stronger pro-democracy leaning across all survey waves.
# Source: HKUPOP half-yearly surveys, education cross-tabs (n≈1000 per wave).
_EDUCATION_LEAN: dict[str, float] = {
    "學位或以上":   0.08,
    "專上非學位":   0.04,
    "中學":        -0.02,
    "小學或以下":  -0.06,
}

# Label boundaries — roughly map to HKUPOP self-identification surveys
# where ~30% identified as pro-establishment, ~30% as democrat, ~40% centrist
# (2012-2019 average; post-2020 surveys show different patterns).
_ESTABLISHMENT_MAX = 0.3   # stance < 0.3  → 建制派
_DEMOCRACY_MIN = 0.7       # stance >= 0.7 → 民主派


# ---------------------------------------------------------------------------
# PoliticalModel
# ---------------------------------------------------------------------------

class PoliticalModel:
    """Models political spectrum, echo chambers, and spiral of silence in HK.

    This class is stateless; all DB interactions are explicit async methods.
    Call ``ensure_column()`` once during startup to migrate the DB schema.
    """

    # ------------------------------------------------------------------
    # Schema migration (idempotent)
    # ------------------------------------------------------------------

    async def ensure_column(self) -> None:
        """Add political_stance column to agent_profiles if not yet present.

        Safe to call multiple times — uses a try/except guard because
        SQLite does not support ALTER TABLE … IF NOT EXISTS.
        """
        async with get_db() as db:
            try:
                await db.execute(
                    "ALTER TABLE agent_profiles ADD COLUMN political_stance REAL DEFAULT 0.5"
                )
                await db.commit()
                logger.info("Added political_stance column to agent_profiles")
            except Exception:
                pass  # Column already exists — no-op

    # ------------------------------------------------------------------
    # Stance assignment
    # ------------------------------------------------------------------

    def assign_political_stance(
        self,
        age: int,
        district: str,
        education_level: str,
        occupation: str,
        openness: float,
        neuroticism: float,
    ) -> float:
        """Compute a political stance value (0–1) from agent demographics.

        Uses additive adjustments derived from HK sociological research:

        - Age: younger cohorts lean more pro-democracy.
        - Education: university-educated lean more pro-democracy.
        - District: geographic political culture differences.
        - Personality: high openness → pro-democracy; high neuroticism →
          slightly more establishment (security-seeking).
        - Gaussian noise (σ=0.05) adds individual variation.

        Args:
            age: Agent age in years.
            district: HK district name (18 districts).
            education_level: HK education level category string.
            occupation: Agent occupation string (reserved for future use).
            openness: Big Five openness score 0–1.
            neuroticism: Big Five neuroticism score 0–1.

        Returns:
            Political stance in [0.0, 1.0].
        """
        base = 0.5  # centrist default

        # Age effect: younger → more pro-democracy
        if age < 30:
            base += 0.12
        elif age < 40:
            base += 0.06
        elif age > 60:
            base -= 0.10
        elif age > 50:
            base -= 0.05

        # Education effect
        base += _EDUCATION_LEAN.get(education_level, 0.0)

        # District effect
        base += _DISTRICT_LEAN.get(district, 0.0)

        # Personality effect
        base += (openness - 0.5) * 0.15
        base -= (neuroticism - 0.5) * 0.05

        # Individual variation
        noise = random.gauss(0, 0.05)
        return max(0.0, min(1.0, round(base + noise, 3)))

    def get_political_label(self, stance: float) -> str:
        """Return the Cantonese political label for a given stance value.

        Args:
            stance: Political stance in [0.0, 1.0].

        Returns:
            One of: 建制派, 中間派, 民主派.
        """
        if stance < _ESTABLISHMENT_MAX:
            return "建制派"
        if stance < _DEMOCRACY_MIN:
            return "中間派"
        return "民主派"

    # ------------------------------------------------------------------
    # Echo chamber
    # ------------------------------------------------------------------

    def echo_chamber_score(
        self,
        agent_stance: float,
        neighbor_stances: list[float],
    ) -> float:
        """Compute information homogeneity within an agent's social network.

        Score 0 means maximally diverse neighbourhood; score 1 means pure
        echo chamber (all neighbours share the same stance).

        Formula:
            avg_diff = mean(|agent_stance - ns| for ns in neighbor_stances)
            echo     = 1 - min(avg_diff * 2, 1.0)

        Args:
            agent_stance: The focal agent's political stance.
            neighbor_stances: List of stances of the agent's neighbours.

        Returns:
            Echo chamber score in [0.0, 1.0].
        """
        if not neighbor_stances:
            return 0.0

        avg_diff = (
            sum(abs(agent_stance - ns) for ns in neighbor_stances)
            / len(neighbor_stances)
        )
        return round(1.0 - min(avg_diff * 2, 1.0), 3)

    # ------------------------------------------------------------------
    # Spiral of silence
    # ------------------------------------------------------------------

    def spiral_of_silence(
        self,
        agent_stance: float,
        community_avg_stance: float,
        agent_neuroticism: float,
    ) -> float:
        """Compute engagement willingness via spiral of silence theory.

        Agents whose stance diverges from the community average become less
        willing to post, especially when they have high neuroticism.

        Args:
            agent_stance: This agent's political stance.
            community_avg_stance: Mean stance across all agents in session.
            agent_neuroticism: Big Five neuroticism 0–1; high values amplify
                               the silencing effect.

        Returns:
            Posting willingness in [0.1, 1.0]; lower = more silent.
        """
        stance_diff = abs(agent_stance - community_avg_stance)

        willingness = 1.0

        # Penalty for being in the minority
        if stance_diff > 0.3:
            willingness -= stance_diff * 0.4

        # Neuroticism amplifies the silencing effect
        if agent_neuroticism > 0.6:
            willingness -= (agent_neuroticism - 0.6) * stance_diff * 0.5

        return max(0.1, min(1.0, round(willingness, 3)))

    # ------------------------------------------------------------------
    # Echo chamber network homophily (Phase 5A)
    # ------------------------------------------------------------------

    async def compute_network_homophily(
        self,
        session_id: str,
        agents: list[dict[str, Any]],
    ) -> float:
        """Compute network homophily ratio for echo chamber detection.

        Compares average stance difference between connected agents (neighbours
        in ``agent_relationships``) vs random agent pairs.  A ratio < 1.0
        indicates echo chamber formation (neighbours are more similar than
        random pairs).

        Args:
            session_id: UUID of the simulation session.
            agents: List of agent dicts, each with at least ``id`` and
                ``political_stance`` keys.

        Returns:
            Homophily ratio (neighbour_diff / random_diff).  Returns 1.0
            (neutral) on failure or insufficient data.
        """
        try:
            if len(agents) < 4:
                return 1.0

            # Build stance lookup
            stance_map: dict[int, float] = {}
            for a in agents:
                aid = a.get("id")
                stance = a.get("political_stance")
                if aid is not None and stance is not None:
                    stance_map[int(aid)] = float(stance)

            if len(stance_map) < 4:
                return 1.0

            # Load relationships
            async with get_db() as db:
                rows = await (
                    await db.execute(
                        """SELECT agent_a_id, agent_b_id
                           FROM agent_relationships
                           WHERE session_id = ?""",
                        (session_id,),
                    )
                ).fetchall()

            if not rows:
                return 1.0

            # Average stance difference between connected pairs
            neighbor_diffs: list[float] = []
            for row in rows:
                a_id = int(row["agent_a_id"])
                b_id = int(row["agent_b_id"])
                if a_id in stance_map and b_id in stance_map:
                    neighbor_diffs.append(abs(stance_map[a_id] - stance_map[b_id]))

            if not neighbor_diffs:
                return 1.0

            neighbor_avg = sum(neighbor_diffs) / len(neighbor_diffs)

            # Average stance difference between random pairs (sample up to 500)
            all_stances = list(stance_map.values())
            random_diffs: list[float] = []
            n = len(all_stances)
            sample_count = min(500, n * (n - 1) // 2)
            rng = random.Random(42)
            for _ in range(sample_count):
                i = rng.randint(0, n - 1)
                j = rng.randint(0, n - 1)
                if i != j:
                    random_diffs.append(abs(all_stances[i] - all_stances[j]))

            if not random_diffs:
                return 1.0

            random_avg = sum(random_diffs) / len(random_diffs)

            if random_avg < 1e-9:
                return 1.0

            return round(neighbor_avg / random_avg, 4)

        except Exception:
            logger.exception(
                "compute_network_homophily failed session=%s", session_id
            )
            return 1.0

    # ------------------------------------------------------------------
    # Spiral of silence — district-level engagement suppression (Phase 5A)
    # ------------------------------------------------------------------

    @staticmethod
    def apply_spiral_of_silence(
        agents: list[dict[str, Any]],
        district_stats: dict[str, float],
    ) -> dict[int, float]:
        """Compute engagement multipliers based on spiral of silence theory.

        For each agent, if their political stance deviates more than 0.3 from
        their district's mean stance, their engagement is suppressed by 50%.

        Args:
            agents: List of agent dicts with ``id``, ``political_stance``,
                and ``district`` keys.
            district_stats: Dict mapping district name to mean political
                stance for that district.

        Returns:
            Dict of agent_id -> engagement_multiplier (0.5 or 1.0).
        """
        multipliers: dict[int, float] = {}
        for agent in agents:
            agent_id = agent.get("id")
            stance = agent.get("political_stance")
            district = agent.get("district", "")

            if agent_id is None or stance is None:
                continue

            agent_id = int(agent_id)
            stance = float(stance)
            district_mean = district_stats.get(district, 0.5)

            if abs(stance - district_mean) > 0.3:
                multipliers[agent_id] = 0.5
            else:
                multipliers[agent_id] = 1.0

        return multipliers

    # ------------------------------------------------------------------
    # Population-level monitoring
    # ------------------------------------------------------------------

    @staticmethod
    def monitor_stance_distribution(stances: list[float]) -> StanceReport:
        """Compute population-level stance statistics and alert level.

        Uses the bimodality coefficient (BC) as polarization index:
            BC = (skewness^2 + 1) / (kurtosis + 3 * (n-1)^2 / ((n-2)*(n-3)))
        Simplified: BC > 0.555 suggests bimodal distribution.

        Args:
            stances: List of agent stance values in [0, 1].

        Returns:
            Frozen StanceReport with alert level.
        """
        n = len(stances)
        if n < 3:
            return StanceReport(
                mean=sum(stances) / max(n, 1),
                std=0.0, skewness=0.0,
                polarization_index=0.0, extremism_ratio=0.0,
                alert_level="normal",
            )

        mean = sum(stances) / n
        variance = sum((s - mean) ** 2 for s in stances) / n
        std = math.sqrt(variance)

        # Skewness (Fisher)
        if std > 1e-9:
            m3 = sum((s - mean) ** 3 for s in stances) / n
            skewness = m3 / (std ** 3)
            m4 = sum((s - mean) ** 4 for s in stances) / n
            kurtosis = m4 / (std ** 4)
        else:
            skewness = 0.0
            kurtosis = 3.0  # normal

        # Bimodality coefficient (Sarle's BC) with sample-size correction
        # per Pfister et al. (2013):
        #   excess_kurtosis = kurtosis - 3*(n-1)^2 / ((n-2)*(n-3))
        #   BC = (skewness^2 + 1) / (excess_kurtosis + 3*(n-1)^2 / ((n-2)*(n-3)))
        # Values > 0.555 suggest bimodality
        if n > 3:
            sample_correction = 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3))
            excess_kurtosis = kurtosis - sample_correction
            bc = (skewness ** 2 + 1) / max(excess_kurtosis + sample_correction, 1e-9)
        else:
            bc = (skewness ** 2 + 1) / max(kurtosis, 1e-9)
        polarization_index = min(1.0, max(0.0, bc))

        # Extremism ratio
        extremism_ratio = sum(1 for s in stances if s < 0.1 or s > 0.9) / n

        # Alert level
        if polarization_index > 0.8 or extremism_ratio > 0.4:
            alert_level = "critical"
        elif polarization_index > 0.6 or extremism_ratio > 0.25:
            alert_level = "warning"
        else:
            alert_level = "normal"

        return StanceReport(
            mean=round(mean, 4),
            std=round(std, 4),
            skewness=round(skewness, 4),
            polarization_index=round(polarization_index, 4),
            extremism_ratio=round(extremism_ratio, 4),
            alert_level=alert_level,
        )

    @staticmethod
    def apply_depolarization(
        stances: list[float],
        alert_level: str,
    ) -> list[float]:
        """Apply centripetal force toward 0.5 to reduce polarization.

        Returns a NEW list — no mutation.

        Args:
            stances: Current agent stance values.
            alert_level: "normal", "warning", or "critical".

        Returns:
            New list of adjusted stances (unchanged if alert_level is normal).
        """
        if alert_level == "normal":
            return list(stances)

        strength = 0.05 if alert_level == "critical" else 0.02
        return [
            round(max(0.0, min(1.0, s + (0.5 - s) * strength)), 4)
            for s in stances
        ]

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def compute_community_stance(self, session_id: str) -> float:
        """Compute the mean political stance across all agents in a session.

        Args:
            session_id: UUID of the simulation session.

        Returns:
            Average stance in [0.0, 1.0]; defaults to 0.5 if no data.
        """
        async with get_db() as db:
            row = await (
                await db.execute(
                    """SELECT AVG(political_stance) AS avg_stance
                       FROM agent_profiles
                       WHERE session_id = ?
                         AND political_stance IS NOT NULL""",
                    (session_id,),
                )
            ).fetchone()

        if row and row["avg_stance"] is not None:
            return float(row["avg_stance"])
        return 0.5  # default centrist

    async def get_agent_political_profile(
        self,
        session_id: str,
        agent_id: int,
    ) -> PoliticalProfile | None:
        """Load a political profile for a specific agent.

        Args:
            session_id: UUID of the simulation session.
            agent_id: Integer agent identifier.

        Returns:
            PoliticalProfile if the agent exists and has a stance value;
            None otherwise.
        """
        async with get_db() as db:
            row = await (
                await db.execute(
                    """SELECT political_stance, neuroticism
                       FROM agent_profiles
                       WHERE session_id = ? AND id = ?""",
                    (session_id, agent_id),
                )
            ).fetchone()

        if row is None or row["political_stance"] is None:
            return None

        stance = float(row["political_stance"])
        neuroticism = float(row["neuroticism"]) if row["neuroticism"] is not None else 0.5
        community_avg = await self.compute_community_stance(session_id)

        return PoliticalProfile(
            agent_id=agent_id,
            political_stance=stance,
            political_label=self.get_political_label(stance),
            engagement_willingness=self.spiral_of_silence(
                stance, community_avg, neuroticism
            ),
        )

    async def get_political_distribution(self, session_id: str) -> dict[str, Any]:
        """Compute the distribution of political stances across agents.

        Args:
            session_id: UUID of the simulation session.

        Returns:
            Dict with keys: 建制派, 中間派, 民主派, total, avg_stance.
        """
        async with get_db() as db:
            rows = await (
                await db.execute(
                    """SELECT political_stance
                       FROM agent_profiles
                       WHERE session_id = ? AND political_stance IS NOT NULL""",
                    (session_id,),
                )
            ).fetchall()

        if not rows:
            return {
                "建制派": 0,
                "中間派": 0,
                "民主派": 0,
                "total": 0,
                "avg_stance": 0.5,
            }

        stances = [float(r["political_stance"]) for r in rows]
        establishment = sum(1 for s in stances if s < _ESTABLISHMENT_MAX)
        centrist = sum(
            1 for s in stances if _ESTABLISHMENT_MAX <= s < _DEMOCRACY_MIN
        )
        democracy = sum(1 for s in stances if s >= _DEMOCRACY_MIN)

        return {
            "建制派": establishment,
            "中間派": centrist,
            "民主派": democracy,
            "total": len(stances),
            "avg_stance": round(sum(stances) / len(stances), 3),
        }

    async def assign_stances_for_session(self, session_id: str) -> int:
        """Compute and persist political stances for all agents in a session.

        Reads each agent's demographics and personality from the DB,
        computes a stance using ``assign_political_stance``, and writes
        the result back.  Idempotent — existing stances are overwritten.

        Args:
            session_id: UUID of the simulation session.

        Returns:
            Number of agent stances written.
        """
        await self.ensure_column()

        async with get_db() as db:
            rows = await (
                await db.execute(
                    """SELECT id, age, district, education_level, occupation,
                              openness, neuroticism
                       FROM agent_profiles
                       WHERE session_id = ?""",
                    (session_id,),
                )
            ).fetchall()

            if not rows:
                logger.warning(
                    "assign_stances_for_session: no agents found session=%s",
                    session_id,
                )
                return 0

            updates: list[tuple[float, str, int]] = []
            for row in rows:
                stance = self.assign_political_stance(
                    age=int(row["age"]),
                    district=str(row["district"]),
                    education_level=str(row["education_level"]),
                    occupation=str(row["occupation"]),
                    openness=float(row["openness"]),
                    neuroticism=float(row["neuroticism"]),
                )
                updates.append((stance, session_id, int(row["id"])))

            await db.executemany(
                "UPDATE agent_profiles SET political_stance = ? WHERE session_id = ? AND id = ?",
                updates,
            )
            await db.commit()

        logger.info(
            "Assigned political stances for %d agents session=%s",
            len(updates),
            session_id,
        )
        return len(updates)
