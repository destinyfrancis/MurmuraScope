"""Scenario-to-contract matching service.

Maps simulation seed text / scenario keywords to relevant Polymarket contracts
using keyword extraction and relevance scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.app.services.polymarket_client import PolymarketContract
from backend.app.utils.logger import get_logger

logger = get_logger("scenario_matcher")

# Topic → keyword groups for matching
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "geopolitics": [
        "war", "conflict", "military", "sanctions", "taiwan", "china", "russia",
        "ukraine", "nato", "missile", "invasion", "ceasefire", "troops",
        "戰爭", "衝突", "制裁", "台海", "軍事",
    ],
    "us_politics": [
        "trump", "biden", "election", "congress", "senate", "republican",
        "democrat", "impeach", "supreme court", "white house", "executive order",
        "tariff", "關稅",
    ],
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "defi", "nft",
        "stablecoin", "binance", "coinbase", "sec", "加密貨幣",
    ],
    "fed_rates": [
        "fed", "federal reserve", "rate cut", "rate hike", "basis points",
        "bps", "fomc", "powell", "interest rate", "monetary policy",
        "加息", "減息", "聯儲局",
    ],
    "markets": [
        "s&p", "sp500", "nasdaq", "dow jones", "stock market", "bear market",
        "bull market", "recession", "crash", "correction", "rally",
        "恒指", "hsi", "股市",
    ],
    "tech_regulation": [
        "ai regulation", "ai ban", "antitrust", "big tech", "meta", "google",
        "apple", "microsoft", "openai", "regulation", "ban",
    ],
    "hk_specific": [
        "hong kong", "hkd", "property", "ccl", "emigration", "national security",
        "article 23", "linked exchange", "mpf", "樓市", "移民", "香港",
    ],
}


@dataclass(frozen=True)
class ContractMatch:
    """A matched Polymarket contract with relevance metadata."""
    contract: PolymarketContract
    relevance_score: float  # [0.0, 1.0]
    matched_keywords: tuple[str, ...]
    matched_topics: tuple[str, ...]


class ScenarioMatcher:
    """Matches simulation scenarios to Polymarket contracts."""

    def __init__(
        self,
        extra_topic_groups: tuple[tuple[str, ...], ...] | None = None,
    ) -> None:
        """Optionally accept additional topic groups from a domain pack."""
        self._extra_topic_groups = extra_topic_groups or ()

    def match_contracts(
        self,
        seed_text: str,
        contracts: list[PolymarketContract],
        min_relevance: float = 0.1,
        max_results: int = 20,
    ) -> list[ContractMatch]:
        """Match seed text against available Polymarket contracts.

        Scoring is based on:
        1. Keyword overlap between seed text and contract question/description
        2. Topic alignment (seed topics ∩ contract topics)
        """
        seed_lower = seed_text.lower()
        seed_topics = self._extract_topics(seed_lower)
        seed_keywords = set(re.findall(r'\b\w{3,}\b', seed_lower))

        matches: list[ContractMatch] = []

        for contract in contracts:
            contract_text = f"{contract.question} {contract.description}".lower()
            contract_topics = self._extract_topics(contract_text)
            contract_keywords = set(re.findall(r'\b\w{3,}\b', contract_text))

            # Keyword overlap score
            common_keywords = seed_keywords & contract_keywords
            keyword_score = len(common_keywords) / max(len(seed_keywords), 1)

            # Topic overlap score
            common_topics = seed_topics & contract_topics
            topic_score = len(common_topics) / max(len(seed_topics), 1) if seed_topics else 0

            # Combined relevance (topic match weighted higher)
            relevance = 0.4 * keyword_score + 0.6 * topic_score

            if relevance >= min_relevance:
                matches.append(ContractMatch(
                    contract=contract,
                    relevance_score=round(min(1.0, relevance), 4),
                    matched_keywords=tuple(sorted(common_keywords)[:10]),
                    matched_topics=tuple(sorted(common_topics)),
                ))

        # Sort by relevance descending, then by volume descending
        matches.sort(key=lambda m: (-m.relevance_score, -m.contract.volume))
        return matches[:max_results]

    def _extract_topics(self, text: str) -> set[str]:
        """Extract topic labels from text based on keyword groups.

        Includes both built-in topic groups and any extra groups from domain packs.
        """
        found_topics: set[str] = set()
        for topic, keywords in _TOPIC_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text:
                    found_topics.add(topic)
                    break

        # Check extra topic groups from domain pack
        for idx, group in enumerate(self._extra_topic_groups):
            topic_name = f"domain_topic_{idx}"
            for kw in group:
                if kw.lower() in text:
                    found_topics.add(topic_name)
                    break

        return found_topics
