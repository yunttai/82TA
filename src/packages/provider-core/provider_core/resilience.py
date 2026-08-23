"""Deterministic deadline, retry, circuit, concurrency and single-flight tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import BoundedSemaphore, Condition, Lock
from time import monotonic, sleep
from typing import Callable, Generic, Hashable, TypeVar

T = TypeVar("T")


class DeadlineExceeded(TimeoutError):
    pass


@dataclass(frozen=True, slots=True)
class Deadline:
    expires_at: float
    clock: Callable[[], float] = monotonic

    @classmethod
    def after_ms(cls, duration_ms: int, *, clock: Callable[[], float] = monotonic) -> "Deadline":
        if duration_ms <= 0:
            raise ValueError("deadline duration must be positive")
        return cls(expires_at=clock() + duration_ms / 1000.0, clock=clock)

    @property
    def remaining_ms(self) -> int:
        return max(0, int((self.expires_at - self.clock()) * 1000))

    def require(self, required_ms: int = 1) -> None:
        if self.remaining_ms < required_ms:
            raise DeadlineExceeded("provider deadline exhausted")

    def bounded_timeout_ms(self, configured_cap_ms: int) -> int:
        if configured_cap_ms <= 0:
            raise ValueError("configured timeout must be positive")
        self.require()
        return min(configured_cap_ms, self.remaining_ms)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 2
    backoff_ms: tuple[int, ...] = (25,)

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("provider attempts must be bounded between one and three")
        if any(value < 0 for value in self.backoff_ms):
            raise ValueError("retry backoff cannot be negative")


def call_with_retry(
    operation: Callable[[int], T],
    *,
    deadline: Deadline,
    timeout_cap_ms: int,
    policy: RetryPolicy,
    retryable: Callable[[Exception], bool],
    sleeper: Callable[[float], None] = sleep,
) -> T:
    last_error: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            return operation(deadline.bounded_timeout_ms(timeout_cap_ms))
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= policy.max_attempts or not retryable(exc):
                raise
            backoff_ms = policy.backoff_ms[min(attempt, len(policy.backoff_ms) - 1)] if policy.backoff_ms else 0
            deadline.require(backoff_ms + 1)
            if backoff_ms:
                sleeper(backoff_ms / 1000.0)
    assert last_error is not None
    raise last_error


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 3, recovery_seconds: float = 30.0, clock: Callable[[], float] = monotonic) -> None:
        if failure_threshold <= 0 or recovery_seconds <= 0:
            raise ValueError("circuit bounds must be positive")
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False
        self._lock = Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._opened_at is None:
                return CircuitState.CLOSED
            if self._clock() - self._opened_at >= self._recovery_seconds:
                return CircuitState.HALF_OPEN
            return CircuitState.OPEN

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if self._clock() - self._opened_at < self._recovery_seconds:
                raise CircuitOpenError("provider circuit is open")
            if self._half_open_in_flight:
                raise CircuitOpenError("provider circuit probe is already in flight")
            self._half_open_in_flight = True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            self._half_open_in_flight = False
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = self._clock()


class ProviderConcurrencyLimiter:
    def __init__(self, maximum: int) -> None:
        if maximum <= 0:
            raise ValueError("provider concurrency maximum must be positive")
        self._semaphore = BoundedSemaphore(maximum)

    def run(self, operation: Callable[[], T], *, timeout_seconds: float = 0.0) -> T:
        if timeout_seconds < 0:
            raise ValueError("concurrency wait timeout cannot be negative")
        if not self._semaphore.acquire(timeout=timeout_seconds):
            raise DeadlineExceeded("provider concurrency limit reached")
        try:
            return operation()
        finally:
            self._semaphore.release()


@dataclass(slots=True)
class _Flight(Generic[T]):
    condition: Condition
    done: bool = False
    value: T | None = None
    error: BaseException | None = None


class SingleFlight(Generic[T]):
    """Coalesces identical in-process calls without caching their result."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._flights: dict[Hashable, _Flight[T]] = {}

    def do(self, key: Hashable, operation: Callable[[], T]) -> T:
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = _Flight(condition=Condition(self._lock))
                self._flights[key] = flight
            else:
                while not flight.done:
                    flight.condition.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.value  # type: ignore[return-value]
        try:
            value = operation()
        except BaseException as exc:
            with self._lock:
                flight.error = exc
                flight.done = True
                flight.condition.notify_all()
                self._flights.pop(key, None)
            raise
        with self._lock:
            flight.value = value
            flight.done = True
            flight.condition.notify_all()
            self._flights.pop(key, None)
        return value
