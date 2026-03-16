"""Domain-agnostic macro state for non-HK domain packs.

GenericMacroState replaces HK-specific MacroState when a non-HK DomainPack
is used. It stores macro field values as a flat dict keyed by MacroFieldSpec
names, enabling domain-agnostic prompt rendering and feedback loops.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.app.domain.base import MacroFieldSpec


@dataclass(frozen=True)
class GenericMacroState:
    """Flexible macro state using dynamic fields from a DomainPack.

    Attributes:
        fields: Mapping of field name → current float value.
        round_number: Current simulation round (0-indexed).
    """

    fields: dict[str, float] = field(default_factory=dict)
    round_number: int = 0

    def get(self, field_name: str, default: float = 0.0) -> float:
        """Return the value of a named macro field, or ``default`` if absent."""
        return self.fields.get(field_name, default)

    def with_update(self, **kwargs: float) -> GenericMacroState:
        """Return a new state with updated field values (immutable)."""
        new_fields = {**self.fields, **kwargs}
        return GenericMacroState(fields=new_fields, round_number=self.round_number)

    def with_round(self, round_number: int) -> GenericMacroState:
        """Return a new state advanced to ``round_number``."""
        return replace(self, round_number=round_number)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (round_number + all fields)."""
        return {"round_number": self.round_number, **self.fields}

    def to_prompt_context(self, locale: str | None = None) -> str:
        """Render a single-line macro context string for LLM prompts.

        Args:
            locale: Optional locale code — reserved for future i18n use.

        Returns:
            Pipe-delimited string of ``key: value`` pairs.
        """
        parts = [f"Round {self.round_number}"]
        for key, value in sorted(self.fields.items()):
            parts.append(f"{key}: {value:.2f}")
        return " | ".join(parts)

    def to_brief_context(self, locale: str | None = None) -> str:
        """Alias for :meth:`to_prompt_context` (shared interface with MacroState)."""
        return self.to_prompt_context(locale=locale)

    @classmethod
    def from_macro_fields(
        cls,
        macro_fields: tuple[MacroFieldSpec, ...],
        round_number: int = 0,
    ) -> GenericMacroState:
        """Construct a baseline GenericMacroState from a DomainPack's macro_fields.

        Args:
            macro_fields: Tuple of MacroFieldSpec instances from the pack.
            round_number: Initial round number (default 0).

        Returns:
            GenericMacroState initialised with each field's ``default_value``.
        """
        fields = {f.name: f.default_value for f in macro_fields}
        return cls(fields=fields, round_number=round_number)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenericMacroState:
        """Reconstruct from a serialised dict (inverse of :meth:`to_dict`).

        Args:
            data: Dict with optional ``round_number`` key; all other keys
                are treated as macro field names.

        Returns:
            Reconstructed GenericMacroState.
        """
        round_number = int(data.pop("round_number", 0)) if isinstance(data, dict) else 0
        # Avoid mutating the input dict
        fields = {k: float(v) for k, v in data.items() if k != "round_number"}
        return cls(fields=fields, round_number=round_number)
