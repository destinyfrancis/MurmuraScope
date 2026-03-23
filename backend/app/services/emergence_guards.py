"""Emergence validity guards: diversity, bias, convergence, phase transitions.

Provides tools to validate that a simulated agent population is
sufficiently diverse, that the LLM driving agents is not systematically
biased toward particular outcomes, and that observed emergent phenomena
are genuine rather than artifacts.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
from collections import Counter
from dataclasses import dataclass

from backend.app.models.emergence import (
    BiasProbeResult,
    EmergenceAttribution,
    MetricSnapshot,
    PhaseTransitionAlert,
)
from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("emergence_guards")

_emergence_llm: LLMClient | None = None


def _get_emergence_llm() -> LLMClient:
    global _emergence_llm
    if _emergence_llm is None:
        from backend.app.utils.llm_client import LLMClient  # noqa: PLC0415

        _emergence_llm = LLMClient()
    return _emergence_llm


# ---------------------------------------------------------------------------
# DiversityResult + DiversityChecker (unchanged)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiversityResult:
    """Result of a Shannon-entropy diversity check on an agent population."""

    shannon_entropy: float
    entropy_ratio: float
    passed: bool


class DiversityChecker:
    """Check that a population of agent profiles is sufficiently diverse.

    Uses Shannon entropy over discretised trait bins. An ``entropy_ratio``
    at or above *threshold* (default 0.8) means the population is diverse
    enough to be considered valid.
    """

    def check(self, profiles: list[dict], threshold: float = 0.8) -> DiversityResult:
        """Run diversity check on *profiles*.

        Args:
            profiles: List of agent profile dicts, each expected to contain
                      numeric keys ``big5_openness``, ``big5_extraversion``,
                      ``political_stance``, ``occupation`` (str), and ``age``.
            threshold: Minimum ``entropy_ratio`` to pass (default 0.8).

        Returns:
            Frozen :class:`DiversityResult`.
        """
        if len(profiles) < 2:
            return DiversityResult(shannon_entropy=0, entropy_ratio=0, passed=False)

        all_bins = [self._discretize(p) for p in profiles]

        counts = Counter(all_bins)
        n = len(all_bins)
        entropy = -sum((c / n) * math.log2(c / n) for c in counts.values() if c > 0)

        # Max entropy: log2 of the number of distinct bins observed
        # (plus a small buffer so a near-full partition can still pass)
        max_entropy = math.log2(min(n, len(counts) + 5))
        if max_entropy == 0:
            max_entropy = 1.0
        ratio = entropy / max_entropy

        return DiversityResult(
            shannon_entropy=round(entropy, 4),
            entropy_ratio=round(min(ratio, 1.0), 4),
            passed=ratio >= threshold,
        )

    @staticmethod
    def _discretize(profile: dict) -> str:
        """Convert a profile dict to a discrete trait-bin string.

        Each of three continuous traits is bucketed into Low/Medium/High.
        Occupation is truncated to its first 3 characters.
        Age is bucketed into Young (<35), Middle (35-54), Old (55+).
        """
        parts = []
        for key in ["big5_openness", "big5_extraversion", "political_stance"]:
            val = profile.get(key, 0.5)
            if val < 0.33:
                parts.append("L")
            elif val < 0.66:
                parts.append("M")
            else:
                parts.append("H")
        parts.append(profile.get("occupation", "unknown")[:3])
        age = profile.get("age", 30)
        parts.append("Y" if age < 35 else ("M" if age < 55 else "O"))
        return "-".join(parts)


# ---------------------------------------------------------------------------
# Scenario classification for persona compliance
# ---------------------------------------------------------------------------

# Indices into PROBE_SCENARIOS that are "liberal" policies.
# A pro-democracy agent (political_stance > 0.6) is expected to 'support' these.
_LIBERAL_SCENARIO_INDICES = frozenset({0, 1})


def _is_liberal_scenario(scenario: str, all_scenarios: list[str]) -> bool:
    """Return True if the scenario is classified as liberal-leaning."""
    try:
        idx = all_scenarios.index(scenario)
    except ValueError:
        return False
    return idx in _LIBERAL_SCENARIO_INDICES


def _expected_stance(
    political_stance: float,
    scenario: str,
    all_scenarios: list[str],
) -> str | None:
    """Return expected stance given agent politics and scenario, or None if centrist."""
    if 0.4 <= political_stance <= 0.6:
        return None  # centrist -- any stance is compliant
    liberal = _is_liberal_scenario(scenario, all_scenarios)
    if political_stance > 0.6:
        return "support" if liberal else "oppose"
    # political_stance < 0.4 (pro-establishment)
    return "oppose" if liberal else "support"


# ---------------------------------------------------------------------------
# Shannon entropy helper
# ---------------------------------------------------------------------------


def _shannon_entropy(counts: dict[str, int]) -> float:
    """Compute Shannon entropy (base-2) from a frequency dict."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)


def _kurtosis_from_counts(counts: dict[str, int]) -> float:
    """Compute excess kurtosis from a frequency dict (Fisher definition).

    Uses a simple categorical-to-numeric mapping:
    support=1, neutral=0, oppose=-1.
    Falls back to 0.0 on insufficient data.
    """
    mapping = {"support": 1.0, "neutral": 0.0, "oppose": -1.0}
    values: list[float] = []
    for stance, count in counts.items():
        val = mapping.get(stance, 0.0)
        values.extend([val] * count)
    n = len(values)
    if n < 4:
        return 0.0
    mean = sum(values) / n
    m2 = sum((v - mean) ** 2 for v in values) / n
    m4 = sum((v - mean) ** 4 for v in values) / n
    if m2 < 1e-12:
        return 0.0
    return (m4 / (m2**2)) - 3.0


# ---------------------------------------------------------------------------
# BiasProbe
# ---------------------------------------------------------------------------


class BiasProbe:
    """Detect systematic LLM bias by testing agents with identical neutral prompts."""

    PROBE_SCENARIOS: list[str] = [
        "政府應否增加公屋供應？",
        "香港應否放寬移民政策？",
        "樓價未來一年會升定跌？",
        "AI 會唔會取代大部分工作？",
        "聯儲局應否繼續加息？",
    ]

    _SEMAPHORE_LIMIT: int = 10

    async def probe(self, session_id: str, sample_size: int = 30) -> BiasProbeResult:
        """Run bias probe against sampled agent profiles.

        1. Load agent profiles from DB (sample ``sample_size`` with diversity).
        2. Pick a random scenario from PROBE_SCENARIOS.
        3. For each sampled agent, build a persona-specific prompt with the
           scenario but NO social context, NO memory -- just persona + question.
        4. Call LLM for each agent (asyncio.gather with semaphore of 10).
        5. Parse each response to extract stance: support / oppose / neutral.
        6. Compute metrics and persist to bias_probe_results table.
        """
        try:
            profiles = await self._load_profiles(session_id, sample_size)
        except Exception:
            logger.exception(
                "Failed to load profiles for bias probe session=%s",
                session_id,
            )
            return self._empty_result(session_id)

        if not profiles:
            logger.warning("No agent profiles found for session=%s", session_id)
            return self._empty_result(session_id)

        scenario = random.choice(self.PROBE_SCENARIOS)
        stances = await self._collect_stances(profiles, scenario)

        stance_counts: dict[str, int] = Counter(stances)
        total = len(stances) if stances else 1

        agreement_rate = max(stance_counts.values(), default=0) / total
        stance_kurtosis = _kurtosis_from_counts(stance_counts)
        persona_compliance = self._compute_persona_compliance(
            profiles,
            stances,
            scenario,
        )
        diversity_index = _shannon_entropy(stance_counts)
        bias_detected = agreement_rate > 0.7 and persona_compliance < 0.5

        details = {
            "stance_counts": dict(stance_counts),
            "profiles_sampled": len(profiles),
            "responses_received": len(stances),
        }

        result = BiasProbeResult(
            session_id=session_id,
            scenario=scenario,
            sample_size=len(profiles),
            agreement_rate=round(agreement_rate, 4),
            stance_kurtosis=round(stance_kurtosis, 4),
            persona_compliance=round(persona_compliance, 4),
            diversity_index=round(diversity_index, 4),
            bias_detected=bias_detected,
            details=details,
        )

        await self._persist(session_id, scenario, result)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_profiles(
        self,
        session_id: str,
        sample_size: int,
    ) -> list[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, district, occupation, age, political_stance, "
                "big5_openness, big5_extraversion, big5_neuroticism "
                "FROM agent_profiles WHERE session_id = ? "
                "ORDER BY RANDOM() LIMIT ?",
                (session_id, sample_size),
            )
            rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "district": r["district"],
                "occupation": r["occupation"],
                "age": r["age"],
                "political_stance": r["political_stance"] or 0.5,
                "big5_openness": r["big5_openness"] or 0.5,
                "big5_extraversion": r["big5_extraversion"] or 0.5,
                "big5_neuroticism": r["big5_neuroticism"] or 0.5,
            }
            for r in rows
        ]

    async def _collect_stances(
        self,
        profiles: list[dict],
        scenario: str,
    ) -> list[str]:
        """Call the LLM for each profile and return list of stances."""
        from backend.app.utils.llm_client import get_agent_provider_model  # noqa: PLC0415

        llm = _get_emergence_llm()
        sem = asyncio.Semaphore(self._SEMAPHORE_LIMIT)

        async def _query_one(profile: dict) -> str:
            persona = f"一位{profile['age']}歲嘅{profile['occupation']}，住在{profile['district']}區"
            async with sem:
                try:
                    resp = await llm.chat_json(
                        messages=[
                            {
                                "role": "system",
                                "content": (f"你是{persona}。只用JSON回答。"),
                            },
                            {
                                "role": "user",
                                "content": (
                                    "以下問題請給出"
                                    "你的立場和理由"
                                    f"：{scenario}\n"
                                    "回答格式："
                                    '{"stance": "support/oppose/neutral", '
                                    '"reason": "..."}'
                                ),
                            },
                        ],
                        provider=get_agent_provider_model()[0],
                        temperature=0.7,
                        max_tokens=256,
                    )
                    stance = resp.get("stance", "neutral").lower().strip()
                    if stance not in {"support", "oppose", "neutral"}:
                        stance = "neutral"
                    return stance
                except Exception:
                    logger.debug(
                        "LLM call failed for agent %s in bias probe",
                        profile["id"],
                    )
                    return "neutral"

        tasks = [_query_one(p) for p in profiles]
        return list(await asyncio.gather(*tasks))

    def _compute_persona_compliance(
        self,
        profiles: list[dict],
        stances: list[str],
        scenario: str,
    ) -> float:
        """Fraction of responses that match persona-expected stance."""
        if not stances:
            return 0.0
        compliant = 0
        for profile, stance in zip(profiles, stances):
            expected = _expected_stance(
                profile.get("political_stance", 0.5),
                scenario,
                self.PROBE_SCENARIOS,
            )
            if expected is None:
                compliant += 1
            elif stance == expected:
                compliant += 1
        return compliant / len(stances)

    async def _persist(
        self,
        session_id: str,
        scenario: str,
        result: BiasProbeResult,
    ) -> None:
        try:
            async with get_db() as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS bias_probe_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        scenario TEXT NOT NULL,
                        sample_size INTEGER NOT NULL,
                        agreement_rate REAL NOT NULL,
                        stance_kurtosis REAL NOT NULL DEFAULT 0.0,
                        persona_compliance REAL NOT NULL DEFAULT 0.0,
                        diversity_index REAL NOT NULL DEFAULT 0.0,
                        bias_detected INTEGER NOT NULL DEFAULT 0,
                        details_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                await db.execute(
                    "INSERT INTO bias_probe_results "
                    "(session_id, scenario, sample_size, agreement_rate, "
                    "stance_kurtosis, persona_compliance, diversity_index, "
                    "bias_detected, details_json) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        session_id,
                        scenario,
                        result.sample_size,
                        result.agreement_rate,
                        result.stance_kurtosis,
                        result.persona_compliance,
                        result.diversity_index,
                        int(result.bias_detected),
                        json.dumps(result.details, ensure_ascii=False),
                    ),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to persist bias probe result session=%s",
                session_id,
            )

    @staticmethod
    def _empty_result(session_id: str) -> BiasProbeResult:
        return BiasProbeResult(
            session_id=session_id,
            scenario="",
            sample_size=0,
            agreement_rate=0.0,
            stance_kurtosis=0.0,
            persona_compliance=0.0,
            diversity_index=0.0,
            bias_detected=False,
        )


# ---------------------------------------------------------------------------
# PhaseTransitionDetector
# ---------------------------------------------------------------------------

_METRIC_FIELDS = ("modularity", "opinion_variance", "sentiment_mean", "trust_density")
_WINDOW_SIZE = 10
_Z_CRITICAL = 3.0
_Z_WARNING = 2.0
_STD_FLOOR = 0.01


class PhaseTransitionDetector:
    """Monitor metrics per round for sudden jumps indicating phase transitions."""

    def __init__(self) -> None:
        self._history: dict[str, list[MetricSnapshot]] = {}

    def record(
        self,
        session_id: str,
        snapshot: MetricSnapshot,
    ) -> list[PhaseTransitionAlert]:
        """Record a metric snapshot and check for phase transitions.

        Uses rolling z-score (window=10) on each of the 4 metrics.
        Returns list of alerts (may be empty).
        """
        history = self._history.setdefault(session_id, [])
        history.append(snapshot)

        if len(history) < 3:
            return []

        alerts: list[PhaseTransitionAlert] = []
        for field in _METRIC_FIELDS:
            alert = self._check_field(session_id, history, snapshot, field)
            if alert is not None:
                alerts.append(alert)

        # Bound history to window size
        if len(history) > _WINDOW_SIZE:
            self._history[session_id] = history[-_WINDOW_SIZE:]

        return alerts

    @staticmethod
    def _check_field(
        session_id: str,
        history: list[MetricSnapshot],
        current: MetricSnapshot,
        field: str,
    ) -> PhaseTransitionAlert | None:
        """Check a single metric field for phase transition."""
        current_val = getattr(current, field)
        previous_val = getattr(history[-2], field)

        # Window excludes the current value
        window_start = max(0, len(history) - 1 - _WINDOW_SIZE)
        window_vals = [getattr(s, field) for s in history[window_start:-1]]

        if len(window_vals) < 2:
            return None

        mean = sum(window_vals) / len(window_vals)
        variance = sum((v - mean) ** 2 for v in window_vals) / len(window_vals)
        std = math.sqrt(variance)

        if std < _STD_FLOOR:
            # All past values nearly identical; any non-trivial delta is a phase transition
            if abs(current_val - mean) < _STD_FLOOR:
                return None
            z = 100.0 * (1.0 if current_val > mean else -1.0)
        else:
            z = (current_val - mean) / std

        abs_z = abs(z)
        if abs_z < _Z_WARNING:
            return None

        delta = current_val - previous_val
        direction = "diverging" if delta > 0 else "converging"
        severity = "critical" if abs_z >= _Z_CRITICAL else "warning"

        return PhaseTransitionAlert(
            session_id=session_id,
            round_number=current.round_number,
            metric_name=field,
            z_score=round(z, 4),
            delta=round(delta, 6),
            direction=direction,
            severity=severity,
        )

    async def persist_alerts(
        self,
        session_id: str,
        alerts: list[PhaseTransitionAlert],
    ) -> None:
        """Store alerts in emergence_alerts table."""
        if not alerts:
            return
        try:
            async with get_db() as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS emergence_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        round_number INTEGER NOT NULL,
                        metric_name TEXT NOT NULL,
                        z_score REAL NOT NULL,
                        delta REAL NOT NULL,
                        direction TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                await db.executemany(
                    "INSERT INTO emergence_alerts "
                    "(session_id, round_number, metric_name, z_score, delta, "
                    "direction, severity) VALUES (?,?,?,?,?,?,?)",
                    [
                        (
                            a.session_id,
                            a.round_number,
                            a.metric_name,
                            a.z_score,
                            a.delta,
                            a.direction,
                            a.severity,
                        )
                        for a in alerts
                    ],
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to persist emergence alerts session=%s",
                session_id,
            )


# ---------------------------------------------------------------------------
# EmergenceAttributor
# ---------------------------------------------------------------------------


class EmergenceAttributor:
    """Attribute observed metric changes to exogenous, endogenous, or artifact sources."""

    _METRIC_TO_COLUMN: dict[str, str] = {
        "modularity": "modularity",
        "opinion_variance": "opinion_variance",
        "sentiment_mean": "sentiment_mean",
        "polarization_index": "polarization_index",
    }

    async def compute_attribution(
        self,
        session_id: str,
        metric_name: str,
        start_round: int,
        end_round: int,
        bias_probe_result: BiasProbeResult | None = None,
    ) -> EmergenceAttribution:
        """Compute attribution for a single metric over a round range.

        Steps:
        1. Load metric values at start_round and end_round.
        2. Compute total_change = end_value - start_value.
        3. Exogenous: identify rounds with shocks, sum metric deltas.
        4. Artifact: bias_probe.agreement_rate * total_change (if available).
        5. Endogenous = total_change - exogenous - artifact (clamped >= 0).
        6. emergence_ratio = endogenous / |total_change| if total_change != 0.
        """
        try:
            start_val, end_val = await self._load_metric_values(
                session_id,
                metric_name,
                start_round,
                end_round,
            )
        except Exception:
            logger.exception(
                "Failed to load metric values: session=%s metric=%s",
                session_id,
                metric_name,
            )
            return self._zero_attribution(
                session_id,
                metric_name,
                start_round,
                end_round,
            )

        total_change = end_val - start_val

        try:
            shock_delta = await self._compute_shock_delta(
                session_id,
                metric_name,
                start_round,
                end_round,
            )
        except Exception:
            logger.debug("Could not compute shock delta, defaulting to 0")
            shock_delta = 0.0

        exogenous = shock_delta

        artifact = 0.0
        if bias_probe_result is not None and abs(total_change) > 1e-9:
            artifact = bias_probe_result.agreement_rate * abs(total_change)

        endogenous = max(0.0, abs(total_change) - abs(exogenous) - artifact)

        if abs(total_change) > 1e-9:
            emergence_ratio = min(1.0, max(0.0, endogenous / abs(total_change)))
        else:
            emergence_ratio = 0.0

        return EmergenceAttribution(
            session_id=session_id,
            metric_name=metric_name,
            total_change=round(total_change, 6),
            exogenous_component=round(exogenous, 6),
            endogenous_component=round(endogenous, 6),
            artifact_component=round(artifact, 6),
            emergence_ratio=round(emergence_ratio, 4),
            round_range=(start_round, end_round),
        )

    async def _load_metric_values(
        self,
        session_id: str,
        metric_name: str,
        start_round: int,
        end_round: int,
    ) -> tuple[float, float]:
        """Load metric values at start and end rounds."""
        col = self._METRIC_TO_COLUMN.get(metric_name)
        if col is None:
            return 0.0, 0.0

        async with get_db() as db:
            cursor = await db.execute(
                f"SELECT round_number, {col} FROM polarization_snapshots "
                "WHERE session_id = ? AND round_number IN (?, ?) "
                "ORDER BY round_number",
                (session_id, start_round, end_round),
            )
            rows = await cursor.fetchall()

        vals: dict[int, float] = {r["round_number"]: r[col] for r in rows}
        return vals.get(start_round, 0.0), vals.get(end_round, 0.0)

    async def _compute_shock_delta(
        self,
        session_id: str,
        metric_name: str,
        start_round: int,
        end_round: int,
    ) -> float:
        """Estimate metric change attributable to exogenous shocks.

        Detects shock rounds by looking for posts from system-injected
        agents (oasis_username starting with 'system' or 'shock', or
        action_type = 'shock').  For each shock round, we attribute the
        metric delta at that round as exogenous.
        """
        col = self._METRIC_TO_COLUMN.get(metric_name)
        if col is None:
            return 0.0

        async with get_db() as db:
            cursor = await db.execute(
                "SELECT DISTINCT round_number FROM simulation_actions "
                "WHERE session_id = ? AND round_number BETWEEN ? AND ? "
                "AND (oasis_username LIKE 'system%' "
                "OR oasis_username LIKE 'shock%' "
                "OR action_type = 'shock')",
                (session_id, start_round, end_round),
            )
            shock_rounds = {r["round_number"] for r in await cursor.fetchall()}

            if not shock_rounds:
                return 0.0

            cursor = await db.execute(
                f"SELECT round_number, {col} FROM polarization_snapshots "
                "WHERE session_id = ? AND round_number BETWEEN ? AND ? "
                "ORDER BY round_number",
                (session_id, start_round, end_round),
            )
            snapshots = await cursor.fetchall()

        if len(snapshots) < 2:
            return 0.0

        vals = {s["round_number"]: s[col] for s in snapshots}
        sorted_rounds = sorted(vals.keys())
        total_shock_delta = 0.0
        for i in range(1, len(sorted_rounds)):
            rnd = sorted_rounds[i]
            prev_rnd = sorted_rounds[i - 1]
            if rnd in shock_rounds:
                total_shock_delta += vals[rnd] - vals[prev_rnd]

        return total_shock_delta

    @staticmethod
    def _zero_attribution(
        session_id: str,
        metric_name: str,
        start_round: int,
        end_round: int,
    ) -> EmergenceAttribution:
        return EmergenceAttribution(
            session_id=session_id,
            metric_name=metric_name,
            total_change=0.0,
            exogenous_component=0.0,
            endogenous_component=0.0,
            artifact_component=0.0,
            emergence_ratio=0.0,
            round_range=(start_round, end_round),
        )
