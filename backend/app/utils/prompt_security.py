"""Prompt injection prevention utilities.

Sanitizes user-controlled text before insertion into LLM prompts.
Strategy: Unicode normalization + length truncation + brace escaping +
XML tag stripping + system-instruction prefix detection.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Length limits
# ---------------------------------------------------------------------------

MAX_SEED_TEXT = 800
MAX_SCENARIO_DESC = 400
MAX_AGENT_FIELD = 200

# ---------------------------------------------------------------------------
# Injection pattern detection
# ---------------------------------------------------------------------------

_INJECTION_PATTERN = re.compile(
    r"(?i)("
    r"ignore\s+(previous|above|all\s+previous)"
    r"|disregard\s+(previous|above|all)"
    r"|system\s*:"
    r"|<\s*system\s*>"
    r"|assistant\s*:"
    r"|human\s*:"
    r"|<\s*/?instructions?\s*>"
    r"|<\s*/?prompt\s*>"
    r")",
    re.MULTILINE | re.DOTALL,
)

# XML/HTML tag pattern — only matches actual tags (start with letter or slash/!)
# Uses a possessive-style approach: tag name starts with [a-zA-Z/!], then optional attrs.
# Conservative length cap (100 chars between <>) avoids catastrophic backtracking.
_XML_TAG_PATTERN = re.compile(r"<[a-zA-Z/!][^>]{0,100}>")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_seed_text(text: str, max_len: int = MAX_SEED_TEXT) -> str:
    """Sanitize user-provided seed text for LLM prompt inclusion.

    Applies the following transforms in order:
    1. Coerce to str and truncate to ``max_len`` characters.
    2. Escape curly braces to prevent Python format-string injection.
    3. Strip XML/HTML tags that could confuse prompt structure.
    4. Replace common prompt-injection instruction patterns with ``[FILTERED]``.

    Args:
        text: Raw user-supplied string.
        max_len: Maximum character length (default ``MAX_SEED_TEXT``).

    Returns:
        Sanitized string, safe for interpolation into an LLM prompt template.
    """
    text = str(text)[:max_len]
    # Normalize Unicode to catch homoglyph attacks (e.g., fullwidth 'ｓｙｓｔｅｍ' → 'system')
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("{", "{{").replace("}", "}}")
    # Detect injection patterns BEFORE stripping XML tags so that patterns like
    # "<system>..." are matched in full before their tag wrapper is removed.
    text = _INJECTION_PATTERN.sub("[FILTERED]", text)
    text = _XML_TAG_PATTERN.sub("", text)
    return text.strip()


def sanitize_scenario_description(text: str) -> str:
    """Sanitize a scenario description (shorter limit than full seed text).

    Args:
        text: Raw scenario description string.

    Returns:
        Sanitized string capped at ``MAX_SCENARIO_DESC`` characters.
    """
    return sanitize_seed_text(text, max_len=MAX_SCENARIO_DESC)


def sanitize_agent_field(text: str) -> str:
    """Sanitize an agent name, role, or persona field.

    Args:
        text: Raw agent field string.

    Returns:
        Sanitized string capped at ``MAX_AGENT_FIELD`` characters.
    """
    return sanitize_seed_text(text, max_len=MAX_AGENT_FIELD)
