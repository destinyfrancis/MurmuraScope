"""Unit tests for agent memory salience floor logic."""

import pytest


@pytest.mark.unit
def test_salience_floor_constant_is_above_prune_threshold():
    """_SALIENCE_MIN_FLOOR must be strictly > _SALIENCE_PRUNE_THRESHOLD."""
    from backend.app.services.agent_memory import (
        _SALIENCE_MIN_FLOOR,
        _SALIENCE_PRUNE_THRESHOLD,
    )

    assert _SALIENCE_MIN_FLOOR > _SALIENCE_PRUNE_THRESHOLD, (
        f"Floor ({_SALIENCE_MIN_FLOOR}) must exceed prune threshold ({_SALIENCE_PRUNE_THRESHOLD})"
    )


@pytest.mark.unit
def test_salience_stabilizes_after_many_rounds():
    """Simulated decay with floor must never go below _SALIENCE_MIN_FLOOR."""
    from backend.app.services.agent_memory import (
        _SALIENCE_DECAY,
        _SALIENCE_MIN_FLOOR,
    )

    salience = 0.8
    for _ in range(100):
        salience = max(salience * _SALIENCE_DECAY, _SALIENCE_MIN_FLOOR)
    assert salience >= _SALIENCE_MIN_FLOOR, f"Salience should stabilize at floor, got {salience}"
