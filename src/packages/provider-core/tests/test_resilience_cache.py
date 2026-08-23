from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from time import sleep
import unittest

from provider_core.cache import BoundedTTLCache, CacheState
from provider_core.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    Deadline,
    DeadlineExceeded,
    ProviderConcurrencyLimiter,
    RetryPolicy,
    SingleFlight,
    call_with_retry,
)


class ResilienceTests(unittest.TestCase):
    def test_retry_is_bounded_and_passes_effective_timeout(self) -> None:
        now = [10.0]
        attempts: list[int] = []

        def operation(timeout_ms: int) -> str:
            attempts.append(timeout_ms)
            if len(attempts) == 1:
                raise TimeoutError("transient")
            return "ok"

        result = call_with_retry(
            operation,
            deadline=Deadline.after_ms(500, clock=lambda: now[0]),
            timeout_cap_ms=200,
            policy=RetryPolicy(max_attempts=2, backoff_ms=(10,)),
            retryable=lambda error: isinstance(error, TimeoutError),
            sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds),
        )
        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 2)
        self.assertTrue(all(0 < timeout <= 200 for timeout in attempts))

    def test_retry_does_not_start_outside_deadline(self) -> None:
        now = [10.0]

        def fail(_: int) -> str:
            raise TimeoutError("transient")

        with self.assertRaises(DeadlineExceeded):
            call_with_retry(
                fail,
                deadline=Deadline.after_ms(20, clock=lambda: now[0]),
                timeout_cap_ms=20,
                policy=RetryPolicy(max_attempts=2, backoff_ms=(20,)),
                retryable=lambda _: True,
                sleeper=lambda _: None,
            )

    def test_circuit_opens_and_allows_single_half_open_probe(self) -> None:
        now = [1.0]
        circuit = CircuitBreaker(failure_threshold=2, recovery_seconds=5, clock=lambda: now[0])
        circuit.record_failure()
        circuit.record_failure()
        self.assertEqual(circuit.state, CircuitState.OPEN)
        with self.assertRaises(CircuitOpenError):
            circuit.before_call()
        now[0] = 7.0
        self.assertEqual(circuit.state, CircuitState.HALF_OPEN)
        circuit.before_call()
        with self.assertRaises(CircuitOpenError):
            circuit.before_call()
        circuit.record_success()
        self.assertEqual(circuit.state, CircuitState.CLOSED)

    def test_concurrency_limiter_rejects_overload(self) -> None:
        limiter = ProviderConcurrencyLimiter(1)
        entered = Event()
        release = Event()
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(limiter.run, lambda: (entered.set(), release.wait(), "one")[-1], timeout_seconds=0)
            self.assertTrue(entered.wait(timeout=1))
            with self.assertRaises(DeadlineExceeded):
                limiter.run(lambda: "two", timeout_seconds=0)
            release.set()
            self.assertEqual(first.result(timeout=1), "one")

    def test_single_flight_coalesces_identical_burst(self) -> None:
        flight: SingleFlight[str] = SingleFlight()
        barrier = Barrier(5)
        started = Event()
        release = Event()
        call_count = 0
        count_lock = Lock()

        def operation() -> str:
            nonlocal call_count
            with count_lock:
                call_count += 1
            started.set()
            release.wait(timeout=1)
            return "shared"

        def caller() -> str:
            barrier.wait(timeout=1)
            return flight.do("same", operation)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(caller) for _ in range(5)]
            self.assertTrue(started.wait(timeout=1))
            sleep(0.05)
            release.set()
            self.assertEqual([future.result(timeout=1) for future in futures], ["shared"] * 5)
        self.assertEqual(call_count, 1)


class CacheTests(unittest.TestCase):
    def test_fresh_stale_and_expired_are_distinct(self) -> None:
        now = [0.0]
        cache = BoundedTTLCache[str](maximum_entries=2, clock=lambda: now[0])
        cache.put("key", "value", ttl_seconds=5, stale_seconds=5)
        self.assertEqual(cache.get("key").state, CacheState.FRESH)
        now[0] = 6
        self.assertEqual(cache.get("key").state, CacheState.MISS)
        cache.put("key", "value", ttl_seconds=5, stale_seconds=5)
        now[0] = 12
        lookup = cache.get("key", allow_stale=True)
        self.assertEqual(lookup.state, CacheState.STALE)
        self.assertEqual(lookup.value, "value")
        now[0] = 17
        self.assertEqual(cache.get("key", allow_stale=True).state, CacheState.MISS)

    def test_cache_is_bounded(self) -> None:
        cache = BoundedTTLCache[int](maximum_entries=1, clock=lambda: 0)
        cache.put("first", 1, ttl_seconds=1)
        cache.put("second", 2, ttl_seconds=1)
        self.assertEqual(cache.get("first").state, CacheState.MISS)
        self.assertEqual(cache.get("second").value, 2)


if __name__ == "__main__":
    unittest.main()
