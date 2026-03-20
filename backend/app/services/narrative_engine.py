"""Convert simulation results into natural language trend reports.

The NarrativeEngine takes structured analysis artifacts (macro forecasts,
agent decision summaries, Monte Carlo bands, confidence scores) and produces
a human-readable :class:`TrendNarrative` via an LLM call.

Design:
  - Stateless: each ``generate()`` call is independent.
  - LLM client is injected at construction time (testable via mocks).
  - All models are frozen Pydantic (immutable).
  - Gracefully handles missing/partial LLM responses.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from backend.app.models.narrative import TrendBlock, TrendNarrative
from backend.prompts.narrative_prompts import NARRATIVE_SYSTEM, NARRATIVE_USER

logger = logging.getLogger(__name__)


class NarrativeEngine:
    """Generate natural language trend narratives from simulation artifacts.

    Args:
        llm_client: An LLM client instance with an async ``chat_json`` method.
    """

    def __init__(self, llm_client: object = None) -> None:
        self._llm = llm_client

    async def generate(
        self,
        report_artifacts: dict,
        confidence_score: float = 0.5,
        confidence_level: str = "medium",
    ) -> TrendNarrative:
        """Generate a :class:`TrendNarrative` from *report_artifacts*.

        Args:
            report_artifacts: Dict of analysis results (forecasts, agent summaries,
                              MC bands, polarization metrics, etc.).
            confidence_score: Numeric confidence score (0-1).
            confidence_level: Human-readable confidence label ("high"/"medium"/"low").

        Returns:
            Frozen :class:`TrendNarrative` instance.

        Raises:
            RuntimeError: If no LLM client is configured.
        """
        if self._llm is None:
            raise RuntimeError("NarrativeEngine requires an LLM client")

        prompt = NARRATIVE_USER.format(
            artifacts=json.dumps(report_artifacts, ensure_ascii=False, default=str)[:8000],
            confidence_level=confidence_level,
            confidence_score=confidence_score,
        )

        try:
            messages = [
                {"role": "system", "content": NARRATIVE_SYSTEM},
                {"role": "user", "content": prompt},
            ]
            raw = await self._llm.chat_json(messages)
        except Exception as exc:
            logger.error("NarrativeEngine LLM call failed: %s", exc)
            return _empty_narrative()

        trends = []
        for t in raw.get("trends", []):
            try:
                trends.append(TrendBlock(**t))
            except Exception as exc:
                logger.warning("Skipping malformed TrendBlock: %s — %s", t, exc)

        return TrendNarrative(
            executive_summary=raw.get("executive_summary", ""),
            trends=trends,
            deep_dive_summary=raw.get("deep_dive_summary", ""),
            methodology_note=raw.get("methodology_note"),
            generated_at=datetime.now(timezone.utc),
        )


def _empty_narrative() -> TrendNarrative:
    """Return an empty TrendNarrative used as a fallback on LLM failure."""
    return TrendNarrative(
        executive_summary="",
        trends=[],
        deep_dive_summary="",
        methodology_note=None,
        generated_at=datetime.now(timezone.utc),
    )
