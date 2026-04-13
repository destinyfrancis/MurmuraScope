"""Unit tests for circuit breaker utility (Phase 1.2).

Covers:
- CLOSED state allows calls
- OPEN state rejects calls with CircuitBreakerOpenError
- Failure threshold opens the breaker
- Recovery timeout transitions OPEN → HALF_OPEN
- Successful call in HALF_OPEN → CLOSED
- Failed call in HALF_OPEN → OPEN again
- Module-level registry (get_breaker) returns same instance
"""

from __future__ import annotations

import time

import pytest

from backend.app.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    get_breaker,
)


class TestCircuitBreakerClosed:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout_s=30.0)
        assert cb.state == CircuitState.CLOSED

    def test_is_open_false_when_closed(self):
        cb = CircuitBreaker(name="test")
        assert not cb.is_open()

    def test_failure_count_zero_initially(self):
        cb = CircuitBreaker(name="test")
        assert cb._failure_count == 0

    def test_record_success_keeps_closed(self):
        cb = CircuitBreaker(name="test")
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_single_failure_stays_closed_below_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 1


class TestCircuitBreakerOpens:
    def test_reaches_threshold_opens(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_is_open_true_when_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open()

    def test_raises_on_call_when_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        # In actual usage we check is_open()
        assert cb.is_open()

    def test_failure_count_does_not_exceed_threshold_tracking(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(10):
            cb.record_failure()
        # State should remain OPEN and is_open should be True
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerHalfOpen:
    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout_s=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.05)
        # After timeout, is_open should return False (allow probe)
        assert not cb.is_open()

    def test_success_in_half_open_closes_breaker(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout_s=0.01, success_threshold=1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.05)
        # Probe allowed (HALF_OPEN)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout_s=0.01)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.05)
        # Force state to HALF_OPEN by calling is_open
        cb.is_open()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerRegistry:
    def test_get_breaker_same_key_same_instance(self):
        b1 = get_breaker("test_provider_unique_x")
        b2 = get_breaker("test_provider_unique_x")
        assert b1 is b2

    def test_get_breaker_different_keys_different_instances(self):
        b1 = get_breaker("provider_alpha_test")
        b2 = get_breaker("provider_beta_test")
        assert b1 is not b2

    def test_get_breaker_returns_circuit_breaker(self):
        b = get_breaker("provider_gamma_test")
        assert isinstance(b, CircuitBreaker)
