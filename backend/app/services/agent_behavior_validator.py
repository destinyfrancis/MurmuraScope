# backend/app/services/agent_behavior_validator.py
"""Tier 1 Agent Behavioral Validation.

Two metrics:
  1. action_diversity_entropy — Shannon entropy over Tier 1 decision types.
     Low entropy (<0.5) = mode collapse (LLM always picks same decision).
  2. avg_consistency_score — LLM-as-judge: given persona + context + decision,
     how consistent is the decision? Score 1–5 (1=incoherent, 5=fully consistent).
     Sampled from up to `tier1_sample_size` recent Tier 1 agent decisions.

Usage::

    validator = AgentBehaviorValidator()
    result = await validator.validate("session_abc", tier1_sample_size=10)
    print(result.mode_collapse_warning, result.avg_consistency_score)
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from backend.app.utils.db import get_db
from backend.app.utils.logger import get_logger

logger = get_logger("agent_behavior_validator")

_MODE_COLLAPSE_ENTROPY_THRESHOLD = 0.5
_LLM_JUDGE_PROMPT = """\
You are evaluating an AI agent's decision in a social simulation.

Agent persona: {persona}
Context / recent events: {context}
Decision taken: {decision}
Reasoning given: {reasoning}

On a scale of 1–5, how CONSISTENT is this decision with the persona and context?
1 = completely incoherent
3 = plausible but unclear motivation
5 = highly coherent and well-motivated

Reply with a single integer (1, 2, 3, 4, or 5) and nothing else."""


@dataclass(frozen=True)
class BehaviorValidationResult:
    """Behavioral validation output for one simulation session."""
    session_id: str
    tier1_decisions_sampled: int
    action_diversity_entropy: float   # Shannon entropy; 0 = mode collapse
    mode_collapse_warning: bool       # True if entropy < threshold
    avg_consistency_score: float      # 1–5 LLM-as-judge mean; 0.0 if no LLM sample
    consistency_scores: tuple[float, ...]
    summary: str


class AgentBehaviorValidator:
    """Validate Tier 1 agent behavioral coherence and diversity."""

    def compute_action_diversity(self, decisions: list[str]) -> float:
        """Shannon entropy over decision type distribution.

        Args:
            decisions: List of decision_type strings from Tier 1 agents.

        Returns:
            Entropy in bits (log2).  0 = all same, log2(N) = uniform over N types.
        """
        if not decisions:
            return 0.0
        counts = Counter(decisions)
        total = len(decisions)
        return -sum(
            (c / total) * math.log2(c / total)
            for c in counts.values()
            if c > 0
        )

    def _check_mode_collapse(self, decisions: list[str]) -> bool:
        """Return True if entropy below collapse threshold."""
        return self.compute_action_diversity(decisions) < _MODE_COLLAPSE_ENTROPY_THRESHOLD

    async def _llm_judge_sample(
        self,
        persona: str,
        context: str,
        decision: str,
        reasoning: str,
    ) -> float:
        """Call LLM to rate decision consistency. Returns 1–5 float."""
        from backend.app.utils.llm_client import get_default_client  # noqa: PLC0415
        client = get_default_client()
        prompt = _LLM_JUDGE_PROMPT.format(
            persona=persona[:300],
            context=context[:400],
            decision=decision,
            reasoning=reasoning[:400],
        )
        try:
            response = await client.complete(prompt, max_tokens=5, temperature=0.0)
            score = float(response.strip().split()[0])
            return max(1.0, min(5.0, score))
        except Exception as exc:
            logger.debug("LLM judge failed: %s", exc)
            return 0.0

    async def validate(
        self,
        session_id: str,
        tier1_sample_size: int = 10,
        skip_llm: bool = False,
    ) -> BehaviorValidationResult:
        """Run behavioral validation for a completed session.

        Args:
            session_id: Session to validate.
            tier1_sample_size: Max Tier 1 decisions to send to LLM judge.
            skip_llm: If True, compute diversity only (no LLM calls).

        Returns:
            BehaviorValidationResult with entropy + consistency scores.
        """
        # Note: agent_profiles.tier column is added at startup via idempotent migration
        # (see CLAUDE.md "Tier assignment" — INTEGER DEFAULT 2, added at startup).
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT sa.agent_id, sa.decision_type, sa.reasoning,
                       sa.round_number, ap.persona
                FROM simulation_actions sa
                LEFT JOIN agent_profiles ap
                    ON ap.session_id = sa.session_id AND ap.agent_id = sa.agent_id
                WHERE sa.session_id = ?
                  AND ap.tier = 1
                ORDER BY sa.round_number DESC
                LIMIT 200
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()

        if not rows:
            return BehaviorValidationResult(
                session_id=session_id,
                tier1_decisions_sampled=0,
                action_diversity_entropy=0.0,
                mode_collapse_warning=False,
                avg_consistency_score=0.0,
                consistency_scores=(),
                summary=f"No Tier 1 decisions found for session {session_id}.",
            )

        # Support both dict-style and sqlite Row objects
        def _get(row: Any, key: str) -> Any:
            if isinstance(row, dict):
                return row.get(key)
            try:
                return row[key]
            except (IndexError, KeyError, TypeError):
                return None

        decisions = [_get(r, "decision_type") for r in rows if _get(r, "decision_type")]
        entropy = self.compute_action_diversity(decisions)
        collapse = self._check_mode_collapse(decisions)

        consistency_scores: list[float] = []
        if not skip_llm:
            sample = rows[:tier1_sample_size]
            for row in sample:
                score = await self._llm_judge_sample(
                    persona=_get(row, "persona") or "",
                    context=f"Round {_get(row, 'round_number')}",
                    decision=_get(row, "decision_type") or "",
                    reasoning=_get(row, "reasoning") or "",
                )
                if score > 0.0:
                    consistency_scores.append(score)

        avg_score = (
            sum(consistency_scores) / len(consistency_scores)
            if consistency_scores else 0.0
        )

        summary_parts = [
            f"Session {session_id}: {len(decisions)} Tier 1 decisions.",
            f"Action diversity entropy={entropy:.3f}",
            "(MODE COLLAPSE DETECTED)" if collapse else "(diversity OK)",
        ]
        if consistency_scores:
            summary_parts.append(f"LLM consistency avg={avg_score:.2f}/5")

        return BehaviorValidationResult(
            session_id=session_id,
            tier1_decisions_sampled=len(decisions),
            action_diversity_entropy=round(entropy, 4),
            mode_collapse_warning=collapse,
            avg_consistency_score=round(avg_score, 3),
            consistency_scores=tuple(consistency_scores),
            summary=" ".join(summary_parts),
        )
