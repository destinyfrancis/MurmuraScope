"""Shared simulation constants used across multiple engines."""

# Hegselmann-Krause bounded confidence radius.
# Agents ignore peers whose belief differs by more than this amount.
# Value: 0.4 matches Hegselmann-Krause (1997) upper range for moderate
# bounded-confidence dynamics.
HC_EPSILON: float = 0.4
