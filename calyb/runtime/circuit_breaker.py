from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    pass


@dataclass
class CircuitBreaker:
    """Standard closed/open/half-open circuit breaker. After
    `failure_threshold` consecutive failures it stops letting calls through
    at all for `reset_timeout` seconds, then allows one probe call
    (half-open) before deciding whether to close again."""

    failure_threshold: int = 3
    reset_timeout: float = 5.0
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.reset_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def before_call(self) -> None:
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError("circuit is open; call rejected without invoking the tool")

    def on_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None

    def on_failure(self) -> None:
        self._failure_count += 1
        if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()


class CircuitBreakerRegistry:
    """One breaker per tool name, created lazily."""

    def __init__(self, **breaker_kwargs) -> None:
        self._kwargs = breaker_kwargs
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(**self._kwargs)
        return self._breakers[name]
