"""Token budget manager for multi-tier context assembly."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.utils.token_counter import TokenCounter


@dataclass(frozen=True)
class TokenBudget:
    """Manages token allocation across context tiers.

    Each block is a (text, token_count, priority) tuple.
    Higher priority blocks are kept first; overflow is trimmed
    from lowest priority.
    """

    total: int = 4096

    def tier_limit(self, ratio: float) -> int:
        """Compute token limit for a tier given its budget ratio."""
        return int(self.total * ratio)

    def assemble(self, blocks: list[tuple[str, int, float]]) -> str:
        """Assemble blocks respecting total budget.

        Args:
            blocks: List of (text, token_count, priority) tuples.
                Higher priority kept first. Overflow trimmed from lowest priority.

        Returns:
            Assembled context string within budget.
        """
        sorted_blocks = sorted(blocks, key=lambda b: b[2], reverse=True)
        result_parts: list[str] = []
        remaining = self.total

        for text, tokens, _priority in sorted_blocks:
            if not text or remaining <= 0:
                continue
            if tokens <= remaining:
                result_parts.append(text)
                remaining -= tokens
            else:
                truncated = TokenCounter.truncate(text, remaining)
                if truncated:
                    result_parts.append(truncated)
                remaining = 0

        return "\n\n".join(result_parts)
