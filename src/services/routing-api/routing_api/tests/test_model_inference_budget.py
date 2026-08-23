from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore, Event, Lock, enumerate as enumerate_threads
from time import monotonic, sleep

from bus_intelligence_core import (
    BusIntelligenceEngine,
    BusIntelligenceRequest,
    EtaPrediction,
    VehicleObservation,
)

from routing_api.fanin_integration import (
    _BudgetedEtaPredictor,
    _BudgetedSeatRiskPredictor,
    _RequestModelInferenceBudget,
)


def _wait_until(predicate, timeout: float = 1.0) -> bool:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return True
        sleep(0.005)
    return predicate()


class _ManualTimer:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _ImmediateExecutor:
    """Deterministic completed-Future seam for boundary scheduling races."""

    def submit(self, work):
        future = Future()
        try:
            future.set_result(work())
        except BaseException as exc:
            future.set_exception(exc)
        return future


def test_noncooperative_inference_returns_at_hard_cap_and_holds_permit() -> None:
    release = Event()
    entered = Event()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="unit-model-hard")
    admission = BoundedSemaphore(1)
    budget = _RequestModelInferenceBudget(
        Event(),
        executor=executor,
        admission=admission,
        target_seconds=0.03,
        hard_seconds=0.05,
    )

    def noncooperative():
        entered.set()
        release.wait(1.0)
        return object()

    started_at = monotonic()
    try:
        assert budget.run(noncooperative) is None
        elapsed = monotonic() - started_at
        assert entered.is_set()
        assert 0.04 <= elapsed < 0.20
        assert admission.acquire(blocking=False) is False
        # Once the request hard window is spent, no later model call starts.
        assert budget.run(lambda: (_ for _ in ()).throw(AssertionError("late start"))) is None
        trace = budget.trace
        assert trace.started == 1
        assert trace.completed == 0
        assert trace.timeouts == 1
        assert trace.target_exceeded is True
        assert trace.hard_exhausted is True
    finally:
        release.set()
        assert _wait_until(lambda: admission.acquire(blocking=False))
        admission.release()
        executor.shutdown(wait=True, cancel_futures=True)


def test_predictor_work_exception_preserves_other_family_budget() -> None:
    for failing_family in ("eta", "seat"):
        executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"unit-model-error-{failing_family}"
        )
        admission = BoundedSemaphore(1)
        budget = _RequestModelInferenceBudget(
            Event(),
            executor=executor,
            admission=admission,
            hard_seconds=0.2,
            target_seconds=0.1,
        )
        calls = {"eta": 0, "seat": 0}
        success = object()

        class Eta:
            def predict(self, value):
                calls["eta"] += 1
                if failing_family == "eta":
                    raise RuntimeError("ETA runtime failed")
                return success

        class Seat:
            def predict(self, value):
                calls["seat"] += 1
                if failing_family == "seat":
                    raise RuntimeError("Seat runtime failed")
                return success

        try:
            if failing_family == "eta":
                assert _BudgetedEtaPredictor(Eta(), budget).predict(object()) is None
                assert (
                    _BudgetedSeatRiskPredictor(Seat(), budget).predict(object())
                    is success
                )
            else:
                assert (
                    _BudgetedSeatRiskPredictor(Seat(), budget).predict(object())
                    is None
                )
                assert _BudgetedEtaPredictor(Eta(), budget).predict(object()) is success
            assert calls == {"eta": 1, "seat": 1}
            assert budget.trace.failures == 1
            assert budget.trace.started == 2
            assert budget.trace.completed == 1
            assert budget.trace.hard_exhausted is False
        finally:
            executor.shutdown(wait=True, cancel_futures=True)


def test_result_completed_at_exact_hard_boundary_is_discarded() -> None:
    timer = _ManualTimer()
    admission = BoundedSemaphore(1)
    budget = _RequestModelInferenceBudget(
        Event(),
        executor=_ImmediateExecutor(),  # type: ignore[arg-type]
        admission=admission,
        timer=timer,
        target_seconds=0.3,
        hard_seconds=0.4,
    )
    sentinel = object()

    def completes_at_boundary():
        timer.value = 0.4
        return sentinel

    assert budget.run(completes_at_boundary) is None
    assert budget.trace.started == 1
    assert budget.trace.completed == 0
    assert budget.trace.timeouts == 1
    assert budget.trace.elapsed_ms == 400
    assert budget.trace.hard_exhausted is True


def test_completed_result_is_discarded_when_cancellation_wins_race() -> None:
    cancellation = Event()
    admission = BoundedSemaphore(1)
    budget = _RequestModelInferenceBudget(
        cancellation,
        executor=_ImmediateExecutor(),  # type: ignore[arg-type]
        admission=admission,
        target_seconds=0.3,
        hard_seconds=0.4,
    )

    def completes_while_cancelled():
        cancellation.set()
        return object()

    assert budget.run(completes_while_cancelled) is None
    assert budget.trace.started == 1
    assert budget.trace.completed == 0
    assert budget.trace.cancellations == 1
    assert budget.trace.hard_exhausted is False


def test_request_cancellation_returns_without_releasing_running_model_permit() -> None:
    cancellation = Event()
    release = Event()
    entered = Event()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="unit-model-cancel")
    admission = BoundedSemaphore(1)
    budget = _RequestModelInferenceBudget(
        cancellation,
        executor=executor,
        admission=admission,
        hard_seconds=0.2,
        target_seconds=0.1,
    )

    def work():
        entered.set()
        release.wait(1.0)
        return object()

    caller = ThreadPoolExecutor(max_workers=1, thread_name_prefix="unit-model-cancel-caller")
    try:
        future = caller.submit(budget.run, work)
        assert entered.wait(0.2)
        cancellation.set()
        assert future.result(timeout=0.1) is None
        assert budget.trace.cancellations == 1
        assert admission.acquire(blocking=False) is False
    finally:
        release.set()
        caller.shutdown(wait=True, cancel_futures=True)
        executor.shutdown(wait=True, cancel_futures=True)


def test_slow_seat_does_not_discard_fresh_official_eta() -> None:
    release = Event()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="unit-model-family")
    admission = BoundedSemaphore(1)
    budget = _RequestModelInferenceBudget(
        Event(),
        executor=executor,
        admission=admission,
        hard_seconds=0.06,
        target_seconds=0.03,
    )
    now = datetime(2026, 8, 23, 3, 0, tzinfo=timezone.utc)
    official = EtaPrediction(
        now + timedelta(seconds=120),
        now + timedelta(seconds=180),
        "OFFICIAL",
    )

    class EtaMustNotRun:
        def predict(self, value):
            raise AssertionError("fresh official ETA called fallback predictor")

    class NoncooperativeSeat:
        def predict(self, value):
            release.wait(1.0)
            return None

    engine = BusIntelligenceEngine(
        _BudgetedEtaPredictor(EtaMustNotRun(), budget),
        _BudgetedSeatRiskPredictor(NoncooperativeSeat(), budget),
    )
    request = BusIntelligenceRequest(
        mapping_grade="HIGH",
        mapping_allows_bus_intelligence=True,
        mapping_score=0.99,
        mapping_version="mapping-v1",
        user_arrival_at=now,
        evaluated_at=now,
        target_stop_id="target-stop",
        service_type="SEATED",
        observations=(
            VehicleObservation(
                vehicle_ref="opaque-vehicle",
                route_id="route-1",
                direction="OUTBOUND",
                boarding_stop_id="boarding-stop",
                observed_at=now,
                official_eta=official,
                remain_seat_observed=3,
            ),
        ),
    )

    started_at = monotonic()
    try:
        result = engine.enrich(request)
        assert monotonic() - started_at < 0.20
        assert result.enrichment_applied is False
        assert result.expected_wait_seconds is None
        assert len(result.candidate_vehicles) == 1
        candidate = result.candidate_vehicles[0]
        assert candidate.eta == official
        assert candidate.seat_risk_at_boarding is None
        assert all(item.purpose != "SEAT_RISK" for item in result.model_provenance)
        assert "BUS_DATA_UNAVAILABLE" in result.warnings
        assert budget.trace.started == 1
        assert budget.trace.timeouts == 1
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_process_admission_bounds_started_work_and_never_builds_a_queue() -> None:
    release = Event()
    entered = 0
    entered_lock = Lock()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="unit-model-bounded")
    admission = BoundedSemaphore(2)
    budgets = tuple(
        _RequestModelInferenceBudget(
            Event(),
            executor=executor,
            admission=admission,
            hard_seconds=0.06,
            target_seconds=0.03,
        )
        for _ in range(4)
    )

    def work():
        nonlocal entered
        with entered_lock:
            entered += 1
        release.wait(1.0)
        return object()

    callers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="unit-model-caller")
    try:
        results = tuple(callers.map(lambda budget: budget.run(work), budgets))
        assert results == (None, None, None, None)
        assert entered == 2
        assert sum(item.trace.started for item in budgets) == 2
        assert sum(item.trace.admission_rejections for item in budgets) == 2
        assert len(
            [
                thread
                for thread in enumerate_threads()
                if thread.name.startswith("unit-model-bounded")
            ]
        ) <= 2
    finally:
        release.set()
        callers.shutdown(wait=True, cancel_futures=True)
        executor.shutdown(wait=True, cancel_futures=True)
