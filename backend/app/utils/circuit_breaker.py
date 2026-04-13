"""Generic async circuit breaker for LLM API calls.

Provides a ``CircuitBreaker`` that tracks failures per service endpoint and
transitions through three states:

  CLOSED  — Normal operation; calls pass through.
  OPEN    — Failure threshold exceeded; calls raise ``CircuitBreakerOpenError``
             immediately without touching the downstream service.
  HALF_OPEN — After ``recovery_timeout_s`` the breaker allows one probe call.
              Success → CLOSED; failure → OPEN (reset timer).

Usage::

    breaker = CircuitBreaker(name="openai", failure_threshold=5,
                             recovery_timeout_s=60.0)

    async def call_llm():
        if breaker.is_open():
            raise CircuitBreakerOpenError("openai")
        try:
            result = await openai_client.chat(...)
            breaker.record_success()
            return result
        except Exception as exc:
            breaker.record_failure()
            raise

Intended to be used alongside the ``llm_client`` module so that sustained LLM
API outages short-circuit quickly instead of every agent waiting for a timeout.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto

from backend.app.utils.logger import get_logger

logger = get_logger("circuit_breaker")


class CircuitState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the circuit breaker is OPEN."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Circuit breaker '{name}' is OPEN — call rejected")
        self.breaker_name = name


@dataclass
class CircuitBreaker:
    """Async-safe circuit breaker.

    Args:
        name: Human-readable label for logging.
        failure_threshold: Consecutive failures before tripping OPEN.
        recovery_timeout_s: Seconds to wait in OPEN before probing (HALF_OPEN).
        success_threshold: Consecutive successes in HALF_OPEN before closing.
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout_s: float = 60.0
    success_threshold: int = 2

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False, repr=False)
    _failure_count: int = field(default=0, init=False, repr=False)
    _success_count: int = field(default=0, init=False, repr=False)
    _opened_at: float = field(default=0.0, init=False, repr=False)

    # -----------------------------------------------------------------------
    # State inspection
    # -----------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Return current state, auto-transitioning OPEN → HALF_OPEN on timeout."""
        if self._state is CircuitState.OPEN:
            if time.monotonic() - self._opened_at >= self.recovery_timeout_s:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info(
                    "CircuitBreaker '%s': OPEN → HALF_OPEN after %.0fs",
                    self.name,
                    self.recovery_timeout_s,
                )
        return self._state

    def is_open(self) -> bool:
        """Return True if calls should be rejected (OPEN state)."""
        return self.state is CircuitState.OPEN

    def is_half_open(self) -> bool:
        return self.state is CircuitState.HALF_OPEN

    def is_closed(self) -> bool:
        return self.state is CircuitState.CLOSED

    # -----------------------------------------------------------------------
    # Call outcome recording
    # -----------------------------------------------------------------------

    def record_success(self) -> None:
        """Record a successful call."""
        current = self.state  # trigger OPEN→HALF_OPEN transition if needed
        if current is CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                logger.info("CircuitBreaker '%s': HALF_OPEN → CLOSED (recovered)", self.name)
        elif current is CircuitState.CLOSED:
            self._failure_count = 0  # Reset on any success

    def record_failure(self) -> None:
        """Record a failed call; trip to OPEN if threshold exceeded."""
        current = self.state
        if current is CircuitState.HALF_OPEN:
            # Probe failed — reopen
            self._trip_open()
        elif current is CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._trip_open()

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _trip_open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._success_count = 0
        logger.warning(
            "CircuitBreaker '%s': tripped OPEN after %d failure(s)",
            self.name,
            self._failure_count,
        )

    def reset(self) -> None:
        """Manually close the breaker (e.g., after operator intervention)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info("CircuitBreaker '%s': manually reset to CLOSED", self.name)

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(name={self.name!r}, state={self._state.name}, "
            f"failures={self._failure_count}/{self.failure_threshold})"
        )


# ---------------------------------------------------------------------------
# Module-level registry: one breaker per provider
# ---------------------------------------------------------------------------

_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(provider: str) -> CircuitBreaker:
    """Return (and create if necessary) the circuit breaker for *provider*.

    Example::

        breaker = get_breaker("openai")
        if breaker.is_open():
            raise CircuitBreakerOpenError("openai")
    """
    if provider not in _breakers:
        _breakers[provider] = CircuitBreaker(name=provider)
    return _breakers[provider]
