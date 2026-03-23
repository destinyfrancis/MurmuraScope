"""Triple extractor for Temporal Knowledge Graph Memory (TKG).

Extracts (subject, predicate, object) triples from agent memory text
using rule-based pattern matching on Cantonese expressions.
Zero LLM cost — pure regex / keyword rules.

Supported Cantonese patterns:
  「我擔心X」/ 「我驚X」    → (agent, worries_about, X)
  「X升」 / 「X加」          → (X, increases, value)
  「X跌」 / 「X減」          → (X, decreases, value)
  「我見到X」               → (agent, observes, X)
  「X影響Y」 / 「X導致Y」   → (X, causes, Y)
  「我支持X」 / 「我贊成X」 → (agent, supports, X)
  「我反對X」               → (agent, opposes, X)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.utils.logger import get_logger

logger = get_logger("triple_extractor")

# Maximum length for extracted subject/object strings
_MAX_ENTITY_LEN = 30

# Confidence for rule-based triples (high confidence — explicit pattern match)
_RULE_CONFIDENCE = 0.85

# ---------------------------------------------------------------------------
# Frozen dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryTriple:
    """Immutable (subject, predicate, object) triple extracted from memory text."""

    subject: str
    predicate: str
    object: str
    confidence: float = _RULE_CONFIDENCE


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Each pattern is a tuple of (compiled_regex, handler_function).
# Handler receives the match object and the agent_username, returns MemoryTriple or None.

_WORRY_PATTERN = re.compile(r"我(?:擔心|驚)(.{1,%d}?)(?:[，。！？\n]|$)" % _MAX_ENTITY_LEN)

_INCREASE_PATTERN = re.compile(r"(.{1,%d}?)(?:升|加|上升|上漲|增加)(?:.{0,10}?)(?:[，。！？]|$)" % _MAX_ENTITY_LEN)

_DECREASE_PATTERN = re.compile(r"(.{1,%d}?)(?:跌|減|下跌|下降|減少|縮水)(?:.{0,10}?)(?:[，。！？]|$)" % _MAX_ENTITY_LEN)

_OBSERVE_PATTERN = re.compile(r"我見到(.{1,%d}?)(?:[，。！？\n]|$)" % _MAX_ENTITY_LEN)

_CAUSE_PATTERN = re.compile(
    r"(.{1,%d}?)(?:影響|導致|令到|使到|造成)(.{1,%d}?)(?:[，。！？\n]|$)" % (_MAX_ENTITY_LEN, _MAX_ENTITY_LEN)
)

_SUPPORT_PATTERN = re.compile(r"我(?:支持|贊成|同意)(.{1,%d}?)(?:[，。！？\n]|$)" % _MAX_ENTITY_LEN)

_OPPOSE_PATTERN = re.compile(r"我反對(.{1,%d}?)(?:[，。！？\n]|$)" % _MAX_ENTITY_LEN)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TripleExtractor:
    """Rule-based triple extraction from Cantonese memory text.

    Completely LLM-free — uses compiled regex patterns to identify
    common Cantonese linguistic structures.
    """

    def extract_triples(
        self,
        memory_text: str,
        memory_type: str = "observation",
        agent_username: str = "",
    ) -> tuple[MemoryTriple, ...]:
        """Extract (subject, predicate, object) triples from memory_text.

        Args:
            memory_text: The memory text string (in Cantonese/Chinese).
            memory_type: Type of memory (influences which patterns apply).
            agent_username: Used as 'agent' placeholder in subject position.

        Returns:
            Tuple of MemoryTriple instances (immutable, zero cost).
        """
        if not memory_text or not memory_text.strip():
            return ()

        agent_label = agent_username or "我"
        triples: list[MemoryTriple] = []

        # 1. 「我擔心X」/ 「我驚X」 → (agent, worries_about, X)
        for m in _WORRY_PATTERN.finditer(memory_text):
            obj = _clean(m.group(1))
            if obj:
                triples.append(
                    MemoryTriple(
                        subject=agent_label,
                        predicate="worries_about",
                        object=obj,
                    )
                )

        # 2. 「X升/加」 → (X, increases, value)
        for m in _INCREASE_PATTERN.finditer(memory_text):
            subj = _clean(m.group(1))
            if subj and _is_plausible_entity(subj):
                triples.append(
                    MemoryTriple(
                        subject=subj,
                        predicate="increases",
                        object="value",
                    )
                )

        # 3. 「X跌/減」 → (X, decreases, value)
        for m in _DECREASE_PATTERN.finditer(memory_text):
            subj = _clean(m.group(1))
            if subj and _is_plausible_entity(subj):
                triples.append(
                    MemoryTriple(
                        subject=subj,
                        predicate="decreases",
                        object="value",
                    )
                )

        # 4. 「我見到X」 → (agent, observes, X)
        for m in _OBSERVE_PATTERN.finditer(memory_text):
            obj = _clean(m.group(1))
            if obj:
                triples.append(
                    MemoryTriple(
                        subject=agent_label,
                        predicate="observes",
                        object=obj,
                    )
                )

        # 5. 「X影響/導致Y」 → (X, causes, Y)
        for m in _CAUSE_PATTERN.finditer(memory_text):
            subj = _clean(m.group(1))
            obj = _clean(m.group(2))
            if subj and obj:
                triples.append(
                    MemoryTriple(
                        subject=subj,
                        predicate="causes",
                        object=obj,
                    )
                )

        # 6. 「我支持/贊成X」 → (agent, supports, X)
        for m in _SUPPORT_PATTERN.finditer(memory_text):
            obj = _clean(m.group(1))
            if obj:
                triples.append(
                    MemoryTriple(
                        subject=agent_label,
                        predicate="supports",
                        object=obj,
                    )
                )

        # 7. 「我反對X」 → (agent, opposes, X)
        for m in _OPPOSE_PATTERN.finditer(memory_text):
            obj = _clean(m.group(1))
            if obj:
                triples.append(
                    MemoryTriple(
                        subject=agent_label,
                        predicate="opposes",
                        object=obj,
                    )
                )

        # Deduplicate while preserving order
        seen: set[tuple[str, str, str]] = set()
        unique: list[MemoryTriple] = []
        for t in triples:
            key = (t.subject, t.predicate, t.object)
            if key not in seen:
                seen.add(key)
                unique.append(t)

        return tuple(unique)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    """Strip whitespace and punctuation from extracted entity text."""
    if not text:
        return ""
    cleaned = text.strip("，。！？、 \t\n\r「」『』【】（）()[]")
    return cleaned[:_MAX_ENTITY_LEN]


def _is_plausible_entity(text: str) -> bool:
    """Reject obviously bad extractions (too short, pure punctuation, etc.)."""
    if len(text) < 1:
        return False
    # Must contain at least one Chinese character or ASCII letter/digit
    has_content = any(("\u4e00" <= c <= "\u9fff") or c.isalnum() for c in text)
    return has_content
