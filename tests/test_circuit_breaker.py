import time

import pytest

from calyb.runtime.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=10)
    for _ in range(2):
        cb.on_failure()
        cb.before_call()  # still closed
    cb.on_failure()
    assert cb.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        cb.before_call()


def test_half_open_after_reset_timeout_then_closes_on_success():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.01)
    cb.on_failure()
    assert cb.state == CircuitState.OPEN
    time.sleep(0.02)
    assert cb.state == CircuitState.HALF_OPEN
    cb.before_call()  # half-open allows the probe through
    cb.on_success()
    assert cb.state == CircuitState.CLOSED


def test_half_open_failure_reopens_immediately():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.01)
    cb.on_failure()
    time.sleep(0.02)
    assert cb.state == CircuitState.HALF_OPEN
    cb.on_failure()
    assert cb.state == CircuitState.OPEN
