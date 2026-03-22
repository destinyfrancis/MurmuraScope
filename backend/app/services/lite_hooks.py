"""Lite (rule-based) fallbacks for kg_driven LLM hooks.

Used in ``lite_ensemble`` mode to drive meaningful agent behaviour changes
without any LLM calls.  Each fallback uses the same data structures as the
real hook (WorldEvent, DeliberationResult) so the rest of the pipeline
(belief propagation, faction mapping, tipping detection) works identically.

Design principle: **stochastic but grounded**.  Randomness comes from
personality traits, cognitive fingerprints, and current belief state — not
from uniform random.  This means different agents react differently to the
same event, and different random seeds produce meaningfully different
collective trajectories.
"""
from __future__ import annotations

import math
import random
import uuid
from typing import Any

from backend.app.models.world_event import WorldEvent
from backend.app.services.cognitive_agent_engine import DeliberationResult
from backend.app.services.constants import HC_EPSILON
from backend.app.utils.logger import get_logger

logger = get_logger("lite_hooks")

# ---------------------------------------------------------------------------
# 1. Rule-based world event generation
# ---------------------------------------------------------------------------

# Event templates parameterised by metric direction.  In lite mode we
# recycle Phase A's event_content_history and generate metric perturbations
# from the *current belief distribution* rather than from LLM.

_EVENT_TYPES = ("shock", "rumor", "official", "grassroots")
_EVENT_TYPE_WEIGHTS = (0.15, 0.30, 0.35, 0.20)


def generate_lite_events(
    round_number: int,
    active_metrics: tuple[str, ...],
    prev_dominant_stance: dict[str, float],
    event_history: list[str],
    rng: random.Random | None = None,
) -> list[WorldEvent]:
    """Generate 1-3 synthetic world events using metric trends + noise.

    Each event perturbs 1-2 metrics with a small delta drawn from a
    distribution shaped by the current dominant stance (mean-reverting bias
    + random shock).  This creates enough variation to drive belief updates
    and faction shifts without LLM.

    Args:
        round_number: Current simulation round.
        active_metrics: Tuple of active scenario metric IDs.
        prev_dominant_stance: metric_id → dominant belief from previous round.
        event_history: Prior event content strings (for dedup context).
        rng: Optional seeded Random for reproducibility.

    Returns:
        List of 1-3 WorldEvent instances.
    """
    _rng = rng or random.Random()
    if not active_metrics:
        return []

    n_events = _rng.choices([1, 2, 3], weights=[0.3, 0.5, 0.2], k=1)[0]
    events: list[WorldEvent] = []

    for i in range(n_events):
        # Pick event type by weighted distribution
        etype = _rng.choices(_EVENT_TYPES, weights=_EVENT_TYPE_WEIGHTS, k=1)[0]

        # Pick 1-2 metrics to impact
        n_metrics = min(len(active_metrics), _rng.choice([1, 1, 2]))
        affected = _rng.sample(list(active_metrics), n_metrics)

        # Compute impact: mean-reverting bias + noise
        # If dominant stance is > 0.5, events tend to push back (stabilising)
        # Shocks override this with larger random magnitude
        impact: dict[str, float] = {}
        for metric in affected:
            stance = prev_dominant_stance.get(metric, 0.5)
            deviation = abs(stance - 0.5)
            # Probabilistic counter-trend: extreme stances more likely to revert,
            # but reinforcement still possible — avoids deterministic mean-revert
            revert_prob = 0.5 + deviation * 0.75  # [0.5, 0.875]
            if _rng.random() < revert_prob:
                direction = -1.0 if stance > 0.5 else 1.0
            else:
                direction = 1.0 if stance > 0.5 else -1.0  # reinforcing
            base_delta = direction * (0.03 + deviation * 0.06)
            noise = _rng.gauss(0, 0.08)
            if etype == "shock":
                noise *= 2.5  # Shocks have bigger impact
            delta = max(-0.25, min(0.25, base_delta + noise))
            impact[metric] = round(delta, 4)

        # Credibility varies by type
        cred_map = {"official": 0.85, "shock": 0.7, "rumor": 0.4, "grassroots": 0.6}
        credibility = cred_map.get(etype, 0.6) + _rng.gauss(0, 0.05)
        credibility = max(0.1, min(1.0, credibility))

        # Content: generic template (sufficient for belief propagation)
        metric_labels = ", ".join(affected)
        content = (
            f"[R{round_number}] {etype.upper()} event affecting {metric_labels} "
            f"(impact: {', '.join(f'{k}:{v:+.2f}' for k, v in impact.items())})"
        )

        events.append(WorldEvent(
            event_id=f"lite_{round_number}_{i}_{uuid.uuid4().hex[:6]}",
            round_number=round_number,
            content=content,
            event_type=etype,
            reach=("ALL",),
            impact_vector=impact,
            credibility=round(credibility, 3),
        ))

    return events


# ---------------------------------------------------------------------------
# 2. Rule-based stakeholder deliberation
# ---------------------------------------------------------------------------

# Emotional reactions indexed by VAD quadrant
_EMOTIONAL_REACTIONS = {
    "high_arousal_neg": ("憤怒", "焦慮", "恐懼", "不安"),
    "high_arousal_pos": ("興奮", "決心", "激昂", "希望"),
    "low_arousal_neg": ("無奈", "疲憊", "灰心", "冷漠"),
    "low_arousal_pos": ("平靜", "滿意", "穩定", "自信"),
}


def deliberate_lite(
    agent: dict[str, Any],
    beliefs: dict[str, float],
    events: list[WorldEvent],
    emotional_state: Any | None = None,
    cognitive_fingerprint: dict[str, float] | None = None,
    rng: random.Random | None = None,
    prev_decision: str | None = None,
) -> DeliberationResult:
    """Rule-based deliberation for one stakeholder agent.

    Uses cognitive fingerprint values + current beliefs + event impacts
    to compute belief updates and stance, without LLM.  Personality
    modulates reaction magnitude (high openness = larger updates,
    high neuroticism = stronger emotional reactions).

    Args:
        agent: Agent dict with at least 'id', 'name', 'role'.
        beliefs: Current {metric_id → belief float}.
        events: Current round's WorldEvent list.
        emotional_state: Optional EmotionalState (VAD).
        cognitive_fingerprint: Optional {value_name → float 0-1}.
        rng: Optional seeded Random.

    Returns:
        DeliberationResult with belief_updates, decision, reasoning.
    """
    _rng = rng or random.Random()
    agent_id = agent.get("id", "unknown")
    cf = cognitive_fingerprint or {}

    # Personality-modulated reactivity
    openness = agent.get("openness", 0.5)
    neuroticism = agent.get("neuroticism", 0.5)
    reactivity = 0.5 + (openness - 0.5) * 0.6 + _rng.gauss(0, 0.1)
    reactivity = max(0.1, min(1.0, reactivity))

    # Compute belief updates from events
    belief_updates: dict[str, float] = {}
    for event in events:
        for metric, delta in event.impact_vector.items():
            if metric not in beliefs:
                continue
            # Personality-graded confirmation bias: closed-minded agents
            # amplify confirming evidence and dismiss disconfirming evidence
            # more strongly than open-minded agents.
            current = beliefs.get(metric, 0.5)
            event_direction = 1.0 if delta > 0 else -1.0
            belief_direction = 1.0 if current > 0.5 else -1.0
            dogmatism = 1.0 - agent.get("openness", 0.5)
            if event_direction == belief_direction:
                confirmation = 1.0 + 0.4 * dogmatism      # [1.0, 1.4]
            else:
                confirmation = 1.0 - 0.5 * dogmatism       # [0.5, 1.0]

            # Cognitive fingerprint modulation
            susceptibility = cf.get("susceptibility", 0.5)
            adjusted_delta = delta * reactivity * confirmation * (0.5 + susceptibility)
            adjusted_delta = max(-0.25, min(0.25, adjusted_delta))

            belief_updates[metric] = belief_updates.get(metric, 0.0) + adjusted_delta

    # Round and cap updates
    belief_updates = {
        k: round(max(-0.25, min(0.25, v)), 4)
        for k, v in belief_updates.items()
    }

    # Strategic momentum: bias toward consistency with previous decision.
    # Conscientiousness modulates persistence (high = more sticky).
    if prev_decision in ("escalate", "de-escalate") and belief_updates:
        momentum_metric = max(belief_updates, key=lambda k: abs(belief_updates[k]))
        sign = 1.0 if prev_decision == "escalate" else -1.0
        nudge = sign * 0.03 * (0.5 + agent.get("conscientiousness", 0.5))
        belief_updates[momentum_metric] = round(
            max(-0.25, min(0.25, belief_updates[momentum_metric] + nudge)), 4,
        )

    # Decision: pick action based on strongest belief shift
    if belief_updates:
        strongest_metric = max(belief_updates, key=lambda k: abs(belief_updates[k]))
        strongest_delta = belief_updates[strongest_metric]
        if abs(strongest_delta) > 0.08:
            decision = "escalate" if strongest_delta > 0 else "de-escalate"
        else:
            decision = "maintain"
    else:
        decision = "observe"

    # Emotional reaction from VAD
    if emotional_state is not None:
        valence = getattr(emotional_state, "valence", 0.0)
        arousal = getattr(emotional_state, "arousal", 0.3)
        if arousal > 0.5 and valence < 0:
            quad = "high_arousal_neg"
        elif arousal > 0.5:
            quad = "high_arousal_pos"
        elif valence < 0:
            quad = "low_arousal_neg"
        else:
            quad = "low_arousal_pos"
        emotional_reaction = _rng.choice(_EMOTIONAL_REACTIONS[quad])
    else:
        emotional_reaction = "觀望"

    # Topic tags from affected metrics
    topic_tags = tuple(belief_updates.keys())[:4] if belief_updates else ("general",)

    # Reasoning: template based on decision
    reasoning = (
        f"基於 {len(events)} 個事件分析，{strongest_metric if belief_updates else '局勢'}"
        f"趨勢{'上升' if belief_updates.get(strongest_metric if belief_updates else '', 0) > 0 else '下降'}，"
        f"選擇 {decision}。"
    ) if belief_updates else "當前局勢穩定，繼續觀察。"

    return DeliberationResult(
        agent_id=agent_id,
        decision=decision,
        reasoning=reasoning,
        belief_updates=belief_updates,
        stance_statement=f"[{agent.get('name', agent_id)}] {decision}: {reasoning[:60]}",
        topic_tags=topic_tags,
        emotional_reaction=emotional_reaction,
    )


# ---------------------------------------------------------------------------
# 3. Rule-based consensus debate
# ---------------------------------------------------------------------------

def debate_lite(
    agent_a: dict[str, Any],
    agent_b: dict[str, Any],
    beliefs_a: dict[str, float],
    beliefs_b: dict[str, float],
    topic: str,
    rng: random.Random | None = None,
    confidence_radius: float = 0.55,
) -> tuple[float, float]:
    """Rule-based pairwise debate on a single topic.

    Uses Hegselmann-Krause bounded confidence: agents only influence each
    other if their stance gap is < *confidence_radius* (default 0.55,
    wider than the global HC_EPSILON to reduce premature convergence in
    lite mode).  Personality modulates the magnitude of shift.

    Args:
        agent_a, agent_b: Agent dicts with personality traits.
        beliefs_a, beliefs_b: Current beliefs.
        topic: Metric ID to debate.
        rng: Optional seeded Random.
        confidence_radius: Maximum stance gap for mutual influence.

    Returns:
        (delta_a, delta_b): Belief deltas for each agent, capped at ±0.20.
    """
    _rng = rng or random.Random()

    stance_a = beliefs_a.get(topic, 0.5)
    stance_b = beliefs_b.get(topic, 0.5)
    gap = abs(stance_a - stance_b)

    # Bounded confidence: no influence if too far apart
    if gap > confidence_radius:
        return (0.0, 0.0)

    # Pull toward each other, modulated by agreeableness
    agree_a = agent_a.get("agreeableness", 0.5)
    agree_b = agent_b.get("agreeableness", 0.5)

    pull_a = (stance_b - stance_a) * agree_a * 0.3 + _rng.gauss(0, 0.02)
    pull_b = (stance_a - stance_b) * agree_b * 0.3 + _rng.gauss(0, 0.02)

    delta_a = max(-0.20, min(0.20, pull_a))
    delta_b = max(-0.20, min(0.20, pull_b))

    return (round(delta_a, 4), round(delta_b, 4))


def run_debate_round_lite(
    stakeholder_agents: list[dict[str, Any]],
    agent_beliefs: dict[str, dict[str, float]],
    round_num: int,
    trigger_every: int = 3,
    rng: random.Random | None = None,
) -> dict[str, dict[str, float]]:
    """Run a lite debate round: pair maximally-divergent agents, apply deltas.

    Args:
        stakeholder_agents: List of stakeholder agent dicts.
        agent_beliefs: agent_id → {metric → belief}.
        round_num: Current round number.
        trigger_every: Debate frequency (default every 3 rounds).
        rng: Optional seeded Random.

    Returns:
        Updated agent_beliefs (new dict, never mutates input).
    """
    if round_num % trigger_every != 0 or len(stakeholder_agents) < 2:
        return agent_beliefs

    _rng = rng or random.Random()

    # Find high-divergence topics
    all_metrics: set[str] = set()
    for beliefs in agent_beliefs.values():
        all_metrics.update(beliefs.keys())

    divergent_topics: list[tuple[str, float]] = []
    for metric in all_metrics:
        vals = [
            agent_beliefs.get(a.get("id", ""), {}).get(metric, 0.5)
            for a in stakeholder_agents
        ]
        if len(vals) < 2:
            continue
        mean = sum(vals) / len(vals)
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
        divergent_topics.append((metric, std))

    divergent_topics.sort(key=lambda x: -x[1])
    top_topics = [t for t, _ in divergent_topics[:3]]

    if not top_topics:
        return agent_beliefs

    # Pair agents with max divergence
    updated = {aid: dict(b) for aid, b in agent_beliefs.items()}
    n_pairs = min(5, len(stakeholder_agents) // 2)
    paired: set[str] = set()

    for topic in top_topics:
        agents_sorted = sorted(
            stakeholder_agents,
            key=lambda a: agent_beliefs.get(a.get("id", ""), {}).get(topic, 0.5),
        )
        pair_count = 0
        lo_idx, hi_idx = 0, len(agents_sorted) - 1
        while lo_idx < hi_idx and pair_count < n_pairs:
            a = agents_sorted[lo_idx]
            b = agents_sorted[hi_idx]
            aid = a.get("id", "")
            bid = b.get("id", "")
            pair_key = f"{aid}_{bid}_{topic}"
            if pair_key not in paired:
                paired.add(pair_key)
                da, db = debate_lite(a, b, updated.get(aid, {}), updated.get(bid, {}), topic, _rng)
                if aid in updated and topic in updated[aid]:
                    updated[aid][topic] = max(0.0, min(1.0, updated[aid][topic] + da))
                if bid in updated and topic in updated[bid]:
                    updated[bid][topic] = max(0.0, min(1.0, updated[bid][topic] + db))
                pair_count += 1
            lo_idx += 1
            hi_idx -= 1

    return updated
