from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock

import pytest

from routing_api.application import OptimizeCommand, RequestContext
from routing_api.fanin_integration import (
    SevenPatternFixtureOptimizeRouteUseCase,
    _BudgetedEtaPredictor,
    _BudgetedSeatRiskPredictor,
    _RequestModelInferenceBudget,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.tests.test_fixture_integration import _CausalProviderPorts


DEPARTURE = datetime.fromisoformat("2026-08-24T07:40:00+09:00")
REQUEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts/openapi/examples/routing-optimize-request.json"
)


@dataclass
class _AdvancingClock:
    wall: datetime = field(default_factory=lambda: DEPARTURE)
    started: float = field(default_factory=time.monotonic)

    def now(self) -> datetime:
        return self.wall + timedelta(seconds=time.monotonic() - self.started)

    def monotonic(self) -> float:
        return time.monotonic()


class _NonCooperativePredictor:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.guard = Lock()
        self.calls = 0
        self.completions = 0
        self.first_entered_at: float | None = None

    def predict(self, value):
        del value
        with self.guard:
            self.calls += 1
            if self.first_entered_at is None:
                self.first_entered_at = time.monotonic()
            self.entered.set()
        assert self.release.wait(timeout=5)
        with self.guard:
            self.completions += 1
        return None


class _StaleOfficialEtaProviders:
    """Force the ETA fallback without changing route/vehicle identity."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def arrivals(self, query, *, deadline):
        envelope = self._delegate.arrivals(query, deadline=deadline)
        stale_at = query.evaluated_at - timedelta(seconds=181)
        return replace(
            envelope,
            observed_at=stale_at,
            payload=tuple(
                replace(item, observed_at=stale_at) for item in envelope.payload
            ),
        )

    def locations(self, query, *, deadline):
        envelope = self._delegate.locations(query, deadline=deadline)
        stale_at = query.evaluated_at - timedelta(seconds=181)
        return replace(
            envelope,
            observed_at=stale_at,
            payload=tuple(
                replace(item, observed_at=stale_at) for item in envelope.payload
            ),
        )


def _payload() -> dict[str, object]:
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    payload["origin"]["coordinate"] = {"lon": 127.187456, "lat": 37.222345}
    payload["destination"]["coordinate"] = {
        "lon": 127.111159,
        "lat": 37.394761,
    }
    payload["departureTime"] = DEPARTURE.isoformat()
    return payload


def _context(clock: _AdvancingClock, family: str) -> RequestContext:
    deadline = clock.now() + timedelta(seconds=6.5)
    return RequestContext(
        f"ri373-{family.lower()}-deadline",
        f"ri373-{family.lower()}-deadline-idempotency",
        deadline,
        deadline,
        True,
        Event(),
    )


def _metric(**values: object) -> None:
    print("RI373_METRIC " + json.dumps(values, sort_keys=True))


def test_result_completed_at_hard_boundary_is_discarded_as_late() -> None:
    observed = [0.0]
    executor = ThreadPoolExecutor(max_workers=1)
    budget = _RequestModelInferenceBudget(
        Event(),
        executor=executor,
        timer=lambda: observed[0],
        target_seconds=0.03,
        hard_seconds=0.05,
    )

    def late_work():
        observed[0] = 0.05
        return "must-not-cross-hard-boundary"

    try:
        assert budget.run(late_work) is None
        trace = budget.trace
        assert trace.completed == 0
        assert trace.hard_exhausted is True
        assert trace.elapsed_ms == 50
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.parametrize("failing_family", ("ETA", "SEAT_RISK"))
def test_one_model_family_exception_does_not_close_remaining_shared_budget(
    failing_family: str,
) -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    budget = _RequestModelInferenceBudget(
        Event(),
        executor=executor,
        target_seconds=0.1,
        hard_seconds=0.2,
    )
    eta_calls = 0
    seat_calls = 0
    survivor = object()

    class Eta:
        def predict(self, value):
            nonlocal eta_calls
            del value
            eta_calls += 1
            if failing_family == "ETA":
                raise RuntimeError("ordinary ETA inference failure")
            return survivor

    class Seat:
        def predict(self, value):
            nonlocal seat_calls
            del value
            seat_calls += 1
            if failing_family == "SEAT_RISK":
                raise RuntimeError("ordinary Seat inference failure")
            return survivor

    eta = _BudgetedEtaPredictor(Eta(), budget)
    seat = _BudgetedSeatRiskPredictor(Seat(), budget)
    try:
        if failing_family == "ETA":
            failed_result = eta.predict(object())
            surviving_result = seat.predict(object())
        else:
            failed_result = seat.predict(object())
            surviving_result = eta.predict(object())
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    assert eta_calls == 1
    assert seat_calls == 1
    assert failed_result is None
    assert surviving_result is survivor
    trace = budget.trace
    assert trace.started == 2
    assert trace.completed == 1
    assert trace.failures == 1
    assert trace.hard_exhausted is False


@pytest.mark.parametrize("request_count", (10, 50, 100))
def test_global_model_admission_is_bounded_and_timed_out_permits_remain_charged(
    request_count: int,
) -> None:
    blocker = _NonCooperativePredictor()
    budgets = [_RequestModelInferenceBudget(Event()) for _ in range(request_count)]

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=request_count) as executor:
        results = list(
            executor.map(
                lambda budget: budget.run(lambda: blocker.predict(None)), budgets
            )
        )
    batch_ms = (time.perf_counter() - started) * 1000
    traces = [budget.trace for budget in budgets]
    with blocker.guard:
        started_at_return = blocker.calls
        completed_at_return = blocker.completions

    # All eight process permits remain owned by the still-running work even after
    # each request-local caller has timed out. A ninth probe therefore rejects
    # immediately instead of queuing behind non-cooperative inference.
    probe_calls = 0

    def probe_work():
        nonlocal probe_calls
        probe_calls += 1
        return "unexpected"

    probe = _RequestModelInferenceBudget(Event())
    assert probe.run(probe_work) is None
    probe_trace = probe.trace
    assert probe_calls == 0
    assert probe_trace.started == 0
    assert probe_trace.admission_rejections == 1

    blocker.release.set()
    completion_deadline = time.monotonic() + 2
    while time.monotonic() < completion_deadline:
        with blocker.guard:
            if blocker.completions == started_at_return:
                break
        time.sleep(0.01)

    assert results == [None] * request_count
    assert started_at_return == 8
    assert completed_at_return == 0
    assert sum(item.started for item in traces) == 8
    assert sum(item.timeouts for item in traces) == 8
    assert sum(item.admission_rejections for item in traces) == request_count - 8
    assert all(item.hard_cap_ms == 400 for item in traces)
    assert all(item.target_ms == 300 for item in traces)
    with blocker.guard:
        assert blocker.completions == 8
    _metric(
        scenario="global_model_admission_noncooperative_load",
        requests=request_count,
        batch_ms=round(batch_ms, 4),
        started=started_at_return,
        completed_at_return=completed_at_return,
        timeouts=sum(item.timeouts for item in traces),
        admission_rejections=sum(item.admission_rejections for item in traces),
        probe_started=probe_trace.started,
        probe_admission_rejections=probe_trace.admission_rejections,
        global_inflight_cap=8,
        target_ms=300,
        hard_cap_ms=400,
        evidence_scope="local_fixture_no_network_not_production_slo",
    )


@pytest.mark.parametrize("family", ("ETA", "SEAT_RISK"))
def test_noncooperative_model_family_obeys_shared_400ms_hard_cap_and_zero_late_starts(
    family: str,
) -> None:
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    blocker = _NonCooperativePredictor()
    causal = _CausalProviderPorts(base.providers)
    providers = (
        _StaleOfficialEtaProviders(causal)
        if family == "ETA"
        else causal
    )
    dependencies = replace(
        base,
        providers=providers,
        eta_predictor=blocker if family == "ETA" else base.eta_predictor,
        seat_predictor=(
            blocker if family == "SEAT_RISK" else base.seat_predictor
        ),
    )
    clock = _AdvancingClock()
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario, clock, dependencies=dependencies
    )
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(
        use_case.execute, OptimizeCommand(_payload()), _context(clock, family)
    )
    assert blocker.entered.wait(timeout=1), f"{family} predictor never started"
    settlement_started = time.monotonic()
    timed_out = False
    outcome = None
    try:
        try:
            outcome = future.result(timeout=0.50)
        except FutureTimeout:
            timed_out = True
    finally:
        with blocker.guard:
            calls_at_return = blocker.calls
            completions_at_return = blocker.completions
        blocker.release.set()
        if outcome is None:
            outcome = future.result(timeout=3)
        executor.shutdown(wait=True, cancel_futures=True)
    settlement_ms = (time.monotonic() - settlement_started) * 1000
    time.sleep(0.03)
    with blocker.guard:
        calls_after_return = blocker.calls

    assert not timed_out, (
        f"{family} inference did not settle within the 400ms hard cap plus "
        "100ms local scheduling tolerance"
    )
    assert calls_at_return == 1
    assert completions_at_return == 0
    assert calls_after_return == calls_at_return
    assert outcome.response["routes"]
    assert outcome.response["status"] == "PARTIAL"

    bus_legs = [
        leg
        for route in outcome.response["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    ]
    assert bus_legs
    provenance = {
        item["provider"]
        for leg in bus_legs
        for item in leg["provenance"]
    }
    expected_token = "BUS_ETA" if family == "ETA" else "SEAT_RISK"
    assert not any(expected_token in item for item in provenance)
    if family == "SEAT_RISK":
        # Fresh official ETA remains a separate observation; timing out Seat Risk
        # cannot manufacture or copy Seat evidence into ETA/model provenance.
        assert all(leg["busIntelligence"] is None for leg in bus_legs)
        assert not any("SEAT_RISK" in item for item in provenance)

    trace = use_case.trace
    assert trace is not None
    model = trace.model_inference
    assert model.target_ms == 300
    assert model.hard_cap_ms == 400
    assert model.started == 1
    assert model.completed == 0
    assert model.timeouts == 1
    assert model.hard_exhausted is True
    assert model.elapsed_ms <= 500
    _metric(
        scenario="noncooperative_model_hard_cap",
        family=family,
        settlement_ms=round(settlement_ms, 4),
        calls_at_return=calls_at_return,
        completions_at_return=completions_at_return,
        late_starts=calls_after_return - calls_at_return,
        trace_elapsed_ms=model.elapsed_ms,
        target_ms=model.target_ms,
        hard_cap_ms=model.hard_cap_ms,
        evidence_scope="local_fixture_no_network_not_production_slo",
    )
