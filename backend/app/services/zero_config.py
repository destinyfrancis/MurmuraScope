"""Zero-config quick-start service for HKSimEngine.

Enables paste-text-and-run: accepts seed text, infers domain,
and returns a ready-to-run simulation configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.utils.logger import get_logger

logger = get_logger("zero_config")

# ---------------------------------------------------------------------------
# Domain inference keywords (static fallback)
# ---------------------------------------------------------------------------

_STATIC_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "hk_city": [
        "香港", "樓市", "property", "移民", "emigration", "生育", "fertility",
        "hk", "hong kong",
    ],
    "us_markets": [
        "美股", "wall street", "nasdaq", "s&p", "fed", "inflation",
        "dow jones", "treasury",
    ],
    "global_macro": [
        "global", "recession", "trade war", "油價", "commodity",
        "world economy", "geopolitical",
    ],
    "public_narrative": [
        "輿論", "narrative", "media", "民意", "protest",
        "public opinion", "social media",
    ],
    "real_estate": [
        "地產", "real estate", "mortgage", "樓價", "ccl",
        "rent", "housing",
    ],
    "company_competitor": [
        "公司", "company", "competitor", "market share", "營銷",
        "enterprise", "corporate",
    ],
    "community_movement": [
        "社區", "community", "movement", "組織",
        "grassroots", "activism",
    ],
}


def _build_domain_keywords() -> dict[str, list[str]]:
    """Build domain keywords dynamically from DomainPackRegistry.

    If a pack has a ``keywords`` field, those keywords are used.
    Falls back to ``_STATIC_DOMAIN_KEYWORDS`` for packs without keywords
    or when the registry is unavailable.
    """
    result = dict(_STATIC_DOMAIN_KEYWORDS)
    try:
        from backend.app.domain.base import DomainPackRegistry  # noqa: PLC0415

        for pack_id in DomainPackRegistry.list_packs():
            pack = DomainPackRegistry.get(pack_id)
            if pack.keywords:
                result[pack_id] = list(pack.keywords)
    except Exception:
        logger.debug("DomainPackRegistry unavailable — using static keywords")
    return result


# Module-level cache: populated from DomainPackRegistry on import, with static fallback
_DOMAIN_KEYWORDS = _build_domain_keywords()


# ---------------------------------------------------------------------------
# HK-specific keywords used for mode detection
# ---------------------------------------------------------------------------

_HK_MODE_KEYWORDS: list[str] = [
    "香港", "樓市", "移民", "生育", "hk", "hong kong",
    "hkd", "legco", "mtv", "tuen mun", "yuen long",
    "kowloon", "新界", "九龍", "港島", "ccl", "hsi",
]

# Geopolitical / non-HK scenario keywords that indicate kg_driven mode
_KG_DRIVEN_KEYWORDS: list[str] = [
    "war", "military", "geopolitical", "sanctions", "nuclear",
    "nato", "united nations", "un security council", "alliance",
    "troops", "invasion", "conflict", "treaty", "tariff",
    "trade war", "embargo", "coup",
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZeroConfigResult:
    """Result of zero-config inference."""

    domain_pack_id: str
    agent_count: int
    round_count: int
    preset_name: str
    seed_text: str
    detected_entities: list[str]
    estimated_duration_seconds: int
    mode: str = "hk_demographic"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ZeroConfigService:
    """Infer domain and configuration from seed text alone."""

    def detect_mode(self, seed_text: str) -> str:
        """Detect simulation mode from seed text.

        Returns ``"hk_demographic"`` when the text contains HK-specific
        keywords (place names, financial indicators, demographics).
        Returns ``"kg_driven"`` for geopolitical or other non-HK scenarios
        that are better served by the KG-driven agent generation path.

        The HK check is performed first: if both HK and geopolitical keywords
        are present, ``"hk_demographic"`` wins to maintain backward
        compatibility.

        Args:
            seed_text: Raw scenario text submitted by the user.

        Returns:
            ``"hk_demographic"`` or ``"kg_driven"``.
        """
        text_lower = seed_text.lower()

        hk_hits = sum(1 for kw in _HK_MODE_KEYWORDS if kw.lower() in text_lower)
        if hk_hits > 0:
            return "hk_demographic"

        kg_hits = sum(1 for kw in _KG_DRIVEN_KEYWORDS if kw.lower() in text_lower)
        if kg_hits > 0:
            return "kg_driven"

        return "hk_demographic"

    async def detect_mode_async(self, seed_text: str) -> str:
        """Detect simulation mode using fast-path keyword check, LLM fallback.

        Fast path: if HK keywords are present → immediately return hk_demographic
        (no LLM call). This covers the common case cheaply.

        LLM path: for all other inputs, a single LLM classification call handles
        any language, fiction, geopolitics, or ambiguous scenarios correctly.

        Args:
            seed_text: Raw scenario text submitted by the user.

        Returns:
            ``"hk_demographic"`` or ``"kg_driven"``.
        """
        text_lower = seed_text.lower()
        hk_hits = sum(1 for kw in _HK_MODE_KEYWORDS if kw.lower() in text_lower)
        if hk_hits > 0:
            return "hk_demographic"
        # LLM fallback for everything else
        return await self._llm_detect_mode(seed_text)

    async def _llm_detect_mode(self, seed_text: str) -> str:
        """Single LLM call to classify seed text as hk_demographic or kg_driven."""
        from backend.app.utils.llm_client import get_default_client  # noqa: PLC0415
        llm = get_default_client()
        prompt = (
            "Classify the following scenario text into exactly one category:\n"
            "- hk_demographic: scenario is specifically about Hong Kong society, "
            "Hong Kong real estate, HK politics, or HK demographics.\n"
            "- kg_driven: anything else (geopolitics, fiction, corporations, "
            "elections, crypto, historical events, etc.).\n\n"
            f"Scenario: {seed_text[:500]}\n\n"
            "Reply with ONLY the category name, nothing else."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            raw = await llm.chat(messages, max_tokens=10, temperature=0.0)
            result = raw.content.strip().lower()
            if "hk_demographic" in result:
                return "hk_demographic"
            return "kg_driven"
        except Exception:
            logger.warning("LLM mode detection failed — defaulting to kg_driven")
            return "kg_driven"

    def infer_domain(self, seed_text: str) -> str:
        """Keyword-match seed text to a domain pack ID.

        Dynamically loads keywords from DomainPackRegistry when available,
        falling back to static keyword dict.
        Returns ``"hk_city"`` when nothing matches.
        """
        domain_keywords = _build_domain_keywords()
        text_lower = seed_text.lower()
        scores: dict[str, int] = {}
        for domain, keywords in domain_keywords.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[domain] = score
        if not scores:
            return "hk_city"
        return max(scores, key=scores.get)  # type: ignore[arg-type]

    async def prepare(self, seed_text: str) -> ZeroConfigResult:
        """Analyse seed text and return a zero-config result.

        Uses the existing *TextProcessor* for entity extraction when
        available; falls back gracefully otherwise.

        Raises:
            ValueError: If *seed_text* is empty or whitespace-only.
        """
        if not seed_text or not seed_text.strip():
            raise ValueError("seed_text must not be empty")

        domain = self.infer_domain(seed_text)
        mode = self.detect_mode(seed_text)

        # Try entity extraction via existing TextProcessor -----------------
        entities: list[str] = []
        try:
            from backend.app.services.text_processor import TextProcessor

            tp = TextProcessor()
            analysis = await tp.analyze_seed(seed_text)
            entities = (
                analysis.get("entities", [])
                if isinstance(analysis, dict)
                else []
            )
        except Exception:
            logger.debug("TextProcessor unavailable — skipping entity extraction")

        # PRESET_FAST defaults ---------------------------------------------
        agent_count = 100
        round_count = 10
        estimated_seconds = agent_count * round_count // 50  # rough heuristic

        logger.info(
            "ZeroConfig: domain=%s mode=%s agents=%d rounds=%d entities=%d",
            domain,
            mode,
            agent_count,
            round_count,
            len(entities),
        )

        return ZeroConfigResult(
            domain_pack_id=domain,
            agent_count=agent_count,
            round_count=round_count,
            preset_name="fast",
            seed_text=seed_text,
            detected_entities=entities[:10],
            estimated_duration_seconds=estimated_seconds,
            mode=mode,
        )

    async def infer_time_config(
        self,
        seed_text: str,
        round_count: int,
        llm: Any | None = None,
    ) -> "TimeConfig":
        """LLM-infer scenario-appropriate time granularity.

        Falls back to 1 day per round on any error.
        """
        from backend.app.models.time_config import TimeConfig

        _DEFAULT = TimeConfig(
            total_simulated_hours=round_count * 24,
            minutes_per_round=1440,
            round_label_unit="day",
            rationale="Default: 1 day per round",
        )

        if llm is None:
            try:
                from backend.app.utils.llm_client import get_default_client
                llm = get_default_client()
            except Exception:
                return _DEFAULT

        prompt = (
            "You are a simulation time-scale advisor. Given a scenario description, "
            "determine the appropriate time granularity for an agent-based simulation.\n\n"
            f"Scenario (first 500 chars): {seed_text[:500]}\n"
            f"Number of simulation rounds: {round_count}\n\n"
            "Return ONLY a JSON object with these fields:\n"
            '- "total_simulated_hours": total real-world hours the simulation should cover\n'
            '- "minutes_per_round": how many real-world minutes each round represents\n'
            '- "round_label_unit": one of "hour", "day", "week", "month"\n'
            '- "rationale": one-sentence explanation\n\n'
            "Examples:\n"
            '- Social media controversy (40 rounds): {"total_simulated_hours": 72, "minutes_per_round": 60, "round_label_unit": "hour", "rationale": "Social media storms peak within 72 hours"}\n'
            '- Geopolitical conflict (30 rounds): {"total_simulated_hours": 720, "minutes_per_round": 1440, "round_label_unit": "day", "rationale": "Geopolitical events unfold over weeks"}\n'
            '- Corporate competition (20 rounds): {"total_simulated_hours": 3360, "minutes_per_round": 10080, "round_label_unit": "week", "rationale": "Market dynamics shift weekly"}\n'
        )

        try:
            import json
            from backend.app.utils.llm_client import get_agent_provider_model
            provider, model = get_agent_provider_model()
            resp = await llm.chat(
                [{"role": "user", "content": prompt}],
                provider=provider,
                model=model,
            )
            data = json.loads(resp.content)
            return TimeConfig(
                total_simulated_hours=int(data["total_simulated_hours"]),
                minutes_per_round=int(data["minutes_per_round"]),
                round_label_unit=str(data["round_label_unit"]),
                rationale=str(data.get("rationale", "")),
            )
        except Exception:
            logger.warning("Time config inference failed — using default (1 day/round)")
            return _DEFAULT
