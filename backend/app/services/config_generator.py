"""Natural language configuration generator for simulations.

Accepts a free-text user query (and optional ProcessedSeed) and returns a
fully-formed SuggestedConfig using a single DeepSeek call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.utils.llm_client import LLMClient, get_agent_provider_model
from backend.app.utils.logger import get_logger
from backend.app.utils.prompt_security import sanitize_scenario_description
from backend.prompts.config_prompts import (
    CONFIG_SYSTEM,
    CONFIG_USER,
    _VALID_SCENARIOS,
    _VALID_SHOCK_TYPES,
    _VALID_MACRO_SCENARIOS,
)

logger = get_logger("config_generator")

_HK_DISTRICTS = frozenset([
    "中西區", "灣仔", "東區", "南區", "油尖旺", "深水埗",
    "九龍城", "黃大仙", "觀塘", "葵青", "荃灣", "屯門",
    "元朗", "北區", "大埔", "沙田", "西貢", "離島",
])

_AGENT_COUNT_MIN = 50
_AGENT_COUNT_MAX = 1000
_ROUND_COUNT_MIN = 20
_ROUND_COUNT_MAX = 80


@dataclass(frozen=True)
class SuggestedShock:
    """Immutable suggested shock event."""

    round_number: int
    shock_type: str
    description: str
    post_content: str = ""


@dataclass(frozen=True)
class SuggestedConfig:
    """Immutable simulation configuration suggestion."""

    scenario_type: str
    agent_count: int
    round_count: int
    district_focus: tuple[str, ...]
    suggested_shocks: tuple[SuggestedShock, ...]
    macro_scenario: str
    rationale: str
    confidence: float


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _validate_scenario(raw: str) -> str:
    return raw if raw in _VALID_SCENARIOS else "property"


def _validate_macro(raw: str) -> str:
    return raw if raw in _VALID_MACRO_SCENARIOS else "baseline"


def _validate_districts(raw: list) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(d for d in raw if d in _HK_DISTRICTS)[:5]


def _parse_shocks(raw: list) -> tuple[SuggestedShock, ...]:
    shocks = []
    for s in (raw or [])[:4]:
        shock_type = s.get("shock_type", "social_event")
        if shock_type not in _VALID_SHOCK_TYPES:
            shock_type = "social_event"
        round_num = int(s.get("round_number", 5))
        if round_num < 1:
            round_num = 1
        shocks.append(SuggestedShock(
            round_number=round_num,
            shock_type=shock_type,
            description=str(s.get("description", "")),
            post_content=str(s.get("post_content", "")),
        ))
    return tuple(shocks)


def _parse_suggested_config(data: dict) -> SuggestedConfig:
    """Parse raw LLM JSON into SuggestedConfig."""
    agent_count = _clamp(
        int(data.get("agent_count", 300)),
        _AGENT_COUNT_MIN,
        _AGENT_COUNT_MAX,
    )
    round_count = _clamp(
        int(data.get("round_count", 40)),
        _ROUND_COUNT_MIN,
        _ROUND_COUNT_MAX,
    )
    return SuggestedConfig(
        scenario_type=_validate_scenario(data.get("scenario_type", "property")),
        agent_count=agent_count,
        round_count=round_count,
        district_focus=_validate_districts(data.get("district_focus", [])),
        suggested_shocks=_parse_shocks(data.get("suggested_shocks", [])),
        macro_scenario=_validate_macro(data.get("macro_scenario", "baseline")),
        rationale=str(data.get("rationale", ""))[:300],
        confidence=float(min(1.0, max(0.0, data.get("confidence", 0.7)))),
    )


class ConfigGenerator:
    """Generate simulation config from natural language user query."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def generate(
        self,
        user_query: str,
        processed_seed_summary: str | None = None,
    ) -> SuggestedConfig:
        """Generate simulation config from natural language input.

        Args:
            user_query: Free-text description of the scenario to simulate.
            processed_seed_summary: Optional summary from TextProcessor.process().

        Returns:
            Immutable SuggestedConfig.

        Raises:
            ValueError: If user_query is empty.
        """
        if not user_query or not user_query.strip():
            raise ValueError("user_query cannot be empty")

        seed_context = ""
        if processed_seed_summary:
            seed_context = f"\n種子文本分析結果：\n{processed_seed_summary}\n"

        messages = [
            {"role": "system", "content": CONFIG_SYSTEM},
            {
                "role": "user",
                "content": CONFIG_USER.format(
                    user_query=sanitize_scenario_description(user_query)[:500],
                    seed_context=seed_context,
                ),
            },
        ]

        try:
            data = await self._llm.chat_json(
                messages,
                provider=get_agent_provider_model()[0],
                temperature=0.4,
                max_tokens=1500,
            )
            return _parse_suggested_config(data)
        except Exception:
            logger.exception("ConfigGenerator.generate failed, returning defaults")
            return SuggestedConfig(
                scenario_type="property",
                agent_count=300,
                round_count=40,
                district_focus=(),
                suggested_shocks=(),
                macro_scenario="baseline",
                rationale="自動生成失敗，使用預設配置",
                confidence=0.1,
            )
