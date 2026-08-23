from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from provider_core.canonical import Coordinate
from provider_core.context import TrafficLinkContext, WeatherContext
from provider_core.envelope import ProviderStatus
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from routing_api.application import (
    InMemoryIdempotencyStore,
    RequestContext,
    RoutingApiApplication,
)
from routing_api.auth import Hs256ServiceBearerVerifier
from routing_api.contract import CanonicalContractValidator
from routing_api.fanin_integration import (
    BusObservationQuery,
    CanonicalFanInOptimizeRouteUseCase,
    SevenPatternFixtureOptimizeRouteUseCase,
    _ProviderOperationBudget,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_domain.strategy_generation import EntryTimeBasis, ExactificationStep
from transport_mapping import GitsRoadLinkIdentity, ValidityWindow


KST = timezone(timedelta(hours=9))
DEPARTURE = datetime.fromisoformat("2026-08-24T07:40:00+09:00")
ORIGIN = Coordinate(127.187456, 37.222345)
DESTINATION = Coordinate(127.111159, 37.394761)
SECRET = b"routing-api-ri362-performance-secret-long-enough"
REQUEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts/openapi/examples/routing-optimize-request.json"
)


@dataclass
class _AdvancingClock:
    wall: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started: float = field(default_factory=time.monotonic)

    def now(self) -> datetime:
        return self.wall + timedelta(seconds=time.monotonic() - self.started)

    def monotonic(self) -> float:
        return time.monotonic()


class _OperationTracker:
    def __init__(self) -> None:
        self.guard = Lock()
        self.active = 0
        self.maximum_active = 0
        self.starts: list[tuple[str, float]] = []
        self.finishes: list[tuple[str, float]] = []

    def run(
        self,
        name: str,
        invoke,
        *,
        delay_seconds: float = 0.0,
        fail: bool = False,
        release: Event | None = None,
    ):
        started = time.monotonic()
        with self.guard:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.starts.append((name, started))
        try:
            if release is not None:
                assert release.wait(timeout=5)
            elif delay_seconds:
                time.sleep(delay_seconds)
            if fail:
                raise TimeoutError(f"sanitized optional {name} timeout")
            return invoke()
        finally:
            finished = time.monotonic()
            with self.guard:
                self.active -= 1
                self.finishes.append((name, finished))


class _DelayedProviderPorts:
    def __init__(
        self,
        delegate,
        tracker: _OperationTracker,
        *,
        delay_seconds: float = 0.0,
        release: Event | None = None,
    ) -> None:
        self._delegate = delegate
        self._tracker = tracker
        self._delay_seconds = delay_seconds
        self._release = release

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def arrivals(self, query, *, deadline):
        return self._tracker.run(
            "arrivals",
            lambda: self._delegate.arrivals(query, deadline=deadline),
            delay_seconds=self._delay_seconds,
            release=self._release,
        )

    def locations(self, query, *, deadline):
        return self._tracker.run(
            "locations",
            lambda: self._delegate.locations(query, deadline=deadline),
            delay_seconds=self._delay_seconds,
            release=self._release,
        )


class _ContextPort:
    enabled_operations = frozenset({"weather_context", "traffic_context"})

    def __init__(
        self,
        base_envelope,
        tracker: _OperationTracker,
        *,
        delay_seconds: float = 0.0,
        fail: bool = False,
        release: Event | None = None,
    ) -> None:
        self._base = base_envelope
        self._tracker = tracker
        self._delay_seconds = delay_seconds
        self._fail = fail
        self._release = release

    def weather(self, query, *, deadline):
        del deadline
        return self._tracker.run(
            "weather_context",
            lambda: replace(
                self._base,
                provider="KMA",
                operation="weather_context",
                fingerprint=query.fingerprint(),
                observed_at=query.observed_at,
                status=ProviderStatus.OK,
                schema_version="kma.ri362.fixture.v1",
                normalized_count=1,
                payload=(WeatherContext(query.coordinate, query.observed_at, 20.0, 0.0),),
            ),
            delay_seconds=self._delay_seconds,
            fail=self._fail,
            release=self._release,
        )

    def traffic(self, query, *, deadline):
        del deadline
        return self._tracker.run(
            "traffic_context",
            lambda: replace(
                self._base,
                provider="GITS",
                operation="traffic_context",
                fingerprint=query.fingerprint(),
                observed_at=query.observed_at,
                status=ProviderStatus.OK,
                schema_version="gits.ri362.fixture.v1",
                normalized_count=len(query.relevant_link_external_ids),
                payload=tuple(
                    TrafficLinkContext(link, 30, 60.0, query.observed_at)
                    for link in query.relevant_link_external_ids
                ),
            ),
            delay_seconds=self._delay_seconds,
            fail=self._fail,
            release=self._release,
        )


class _CountingGateUseCase(CanonicalFanInOptimizeRouteUseCase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.gate_decisions = 0
        self._gate_guard = Lock()

    def _optional_provider_start_allowed(self, context: RequestContext) -> bool:
        with self._gate_guard:
            self.gate_decisions += 1
        return super()._optional_provider_start_allowed(context)


def _fixture_parts():
    dependencies = fixture_fan_in_dependencies(fixture_scenario("R1"))
    request = TransitSearchRequest(ORIGIN, DESTINATION, DEPARTURE)
    envelope = dependencies.providers.transit(
        request, deadline=Deadline.after_ms(1_000)
    )
    leg = envelope.payload[0].legs[0]
    boarding = SimpleNamespace(lon=ORIGIN.lon, lat=ORIGIN.lat)
    alighting = SimpleNamespace(lon=DESTINATION.lon, lat=DESTINATION.lat)
    target = SimpleNamespace(
        route_id="mapped-route",
        boarding=SimpleNamespace(external_id="mapped-origin", coordinate=boarding),
        alighting=SimpleNamespace(
            external_id="mapped-destination", coordinate=alighting
        ),
        geometry=(boarding, alighting),
        gits_road_link_identity=GitsRoadLinkIdentity(
            link_external_ids=("link-a", "link-b"),
            mapping_version="ri373-performance-fixture-v1",
            validity=ValidityWindow(
                DEPARTURE - timedelta(days=1), DEPARTURE + timedelta(days=1)
            ),
        ),
    )
    query = BusObservationQuery("mapped-route", "mapped-origin", DEPARTURE)
    return dependencies, envelope, leg, target, query


def _request_context(clock: _AdvancingClock, seconds: float, suffix: str) -> RequestContext:
    deadline = clock.now() + timedelta(seconds=seconds)
    return RequestContext(
        f"ri362-{suffix}",
        f"ri362-idempotency-{suffix}",
        deadline,
        deadline,
        True,
        Event(),
    )


def _metric(**values: object) -> None:
    print("RI362_METRIC " + json.dumps(values, sort_keys=True))


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def test_optional_group_makes_one_gate_decision_and_four_siblings_overlap_under_700ms() -> None:
    dependencies, envelope, leg, target, query = _fixture_parts()
    tracker = _OperationTracker()
    providers = _DelayedProviderPorts(
        dependencies.providers, tracker, delay_seconds=0.08
    )
    context_port = _ContextPort(envelope, tracker, delay_seconds=0.08)
    clock = _AdvancingClock()
    use_case = _CountingGateUseCase(
        "ri362-four-siblings",
        clock,
        dependencies=replace(
            dependencies, providers=providers, context=context_port
        ),
    )
    context = _request_context(clock, 2.05, "four-siblings")
    cutoff = clock.monotonic() + (
        context.effective_deadline - clock.now()
    ).total_seconds() - 1.75

    started = time.perf_counter()
    group = use_case._fetch_bus_optional_group(
        context, providers, context_port, query, target, leg, "SEATED"
    )
    elapsed = time.perf_counter() - started

    assert use_case.gate_decisions == 1
    assert group.started_units == 4
    assert group.context_complete is True
    assert len(tracker.starts) == len(tracker.finishes) == 4
    assert tracker.maximum_active == 4
    assert max(item[1] for item in tracker.starts) < cutoff
    assert elapsed < 0.7
    _metric(
        scenario="optional_context_four_sibling_fanout",
        gate_decisions=use_case.gate_decisions,
        started_operations=group.started_units,
        maximum_active=tracker.maximum_active,
        wall_ms=round(elapsed * 1000, 4),
        optional_gate_reserve_ms=1750,
        group_deadline_ms=700,
        network_provider_calls=0,
        evidence_scope="local_fixture_no_network_not_production_slo",
    )


def test_noncooperative_optional_calls_return_at_700ms_and_all_started_work_is_charged() -> None:
    dependencies, envelope, leg, target, query = _fixture_parts()
    tracker = _OperationTracker()
    release = Event()
    providers = _DelayedProviderPorts(
        dependencies.providers, tracker, release=release
    )
    context_port = _ContextPort(envelope, tracker, release=release)
    clock = _AdvancingClock()
    use_case = _CountingGateUseCase(
        "ri362-noncooperative",
        clock,
        dependencies=replace(
            dependencies, providers=providers, context=context_port
        ),
    )

    started = time.perf_counter()
    try:
        group = use_case._fetch_bus_optional_group(
            _request_context(clock, 6.5, "noncooperative"),
            providers,
            context_port,
            query,
            target,
            leg,
            "SEATED",
        )
        elapsed = time.perf_counter() - started
        with tracker.guard:
            started_at_return = len(tracker.starts)
            finished_at_return = len(tracker.finishes)
        time.sleep(0.03)
        with tracker.guard:
            starts_after_return = len(tracker.starts)
    finally:
        release.set()

    assert use_case.gate_decisions == 1
    assert group.started_units == 4
    assert started_at_return == 4
    assert finished_at_return == 0
    assert starts_after_return == started_at_return
    assert 0.55 < elapsed < 1.2
    assert group.arrivals is group.locations is None
    assert group.context_complete is False
    _metric(
        scenario="optional_context_noncooperative_deadline",
        wall_ms=round(elapsed * 1000, 4),
        started_operations=started_at_return,
        charged_operations=group.started_units,
        finished_at_return=finished_at_return,
        new_starts_after_return=starts_after_return - started_at_return,
        network_provider_calls=0,
        evidence_scope="local_fixture_no_network_not_production_slo",
    )


def test_gbis_and_two_context_operations_reserve_atomically_under_global_cap() -> None:
    dependencies, envelope, _, _, _ = _fixture_parts()
    context_port = _ContextPort(envelope, _OperationTracker())
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "ri362-atomic-cap",
        _AdvancingClock(),
        dependencies=replace(dependencies, context=context_port),
    )
    step = ExactificationStep(
        "candidate:0",
        "candidate",
        0,
        "bus-leg",
        "BUS",
        "origin",
        "destination",
        "bus-evaluator",
        "bus-topology",
        EntryTimeBasis.REQUEST_DEPARTURE,
        None,
        0,
    )
    required = use_case._exact_step_reservation_units(step, movement_reused=False)
    assert required == 4

    blocked = _ProviderOperationBudget(64)
    blocked.reserve(61)
    operation_starts = 0
    if blocked.try_reserve(required):
        operation_starts += required
    assert operation_starts == 0
    assert blocked.consumed == 61

    admitted = _ProviderOperationBudget(64)
    admitted.reserve(60)
    assert admitted.try_reserve(required) is True
    assert admitted.consumed == 64


@pytest.mark.parametrize("request_count", (10, 50, 100))
@pytest.mark.parametrize("context_fails", (False, True), ids=("delayed", "failing"))
def test_optional_context_local_fixture_load_is_bounded_and_fail_soft(
    request_count: int, context_fails: bool
) -> None:
    dependencies, envelope, leg, target, query = _fixture_parts()
    tracker = _OperationTracker()
    providers = _DelayedProviderPorts(
        dependencies.providers, tracker, delay_seconds=0.01
    )
    context_port = _ContextPort(
        envelope,
        tracker,
        delay_seconds=0.01,
        fail=context_fails,
    )
    latencies: list[float] = []
    results = []
    guard = Lock()

    def invoke(index: int):
        clock = _AdvancingClock()
        use_case = _CountingGateUseCase(
            f"ri362-load-{index}",
            clock,
            dependencies=replace(
                dependencies, providers=providers, context=context_port
            ),
        )
        started = time.perf_counter()
        group = use_case._fetch_bus_optional_group(
            _request_context(clock, 3.0, f"load-{index}"),
            providers,
            context_port,
            query,
            target,
            leg,
            "SEATED",
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        with guard:
            latencies.append(elapsed_ms)
        return group, use_case.gate_decisions

    batch_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(10, request_count)) as executor:
        results = list(executor.map(invoke, range(request_count)))
    batch_ms = (time.perf_counter() - batch_started) * 1000

    assert len(results) == request_count
    assert all(group.started_units == 4 for group, _ in results)
    assert all(gates == 1 for _, gates in results)
    assert all(group.arrivals is not None for group, _ in results)
    assert all(group.locations is not None for group, _ in results)
    assert all(
        group.context_complete is (not context_fails) for group, _ in results
    )
    assert max(latencies) < 700
    assert len(tracker.starts) == 4 * request_count
    _metric(
        scenario="optional_context_local_fixture_load",
        context_outcome="failure" if context_fails else "delayed_success",
        requests=request_count,
        operation_starts=len(tracker.starts),
        p50_ms=round(_percentile(latencies, 0.50), 4),
        p95_ms=round(_percentile(latencies, 0.95), 4),
        max_ms=round(max(latencies), 4),
        batch_ms=round(batch_ms, 4),
        network_provider_calls=0,
        evidence_scope="local_fixture_no_network_not_production_slo",
    )


def _segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(clock: _AdvancingClock) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    claims = _segment(
        {
            "iss": "service-api",
            "aud": "routing-api",
            "sub": "ri362-performance",
            "jti": "ri362-failing-context",
            "exp": int((clock.now() + timedelta(minutes=5)).timestamp()),
        }
    )
    signature = hmac.new(
        SECRET, f"{header}.{claims}".encode("ascii"), hashlib.sha256
    ).digest()
    return f"{header}.{claims}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def test_failing_optional_context_is_partial_not_500_and_does_not_extend_6_5_seconds() -> None:
    dependencies, envelope, _, _, _ = _fixture_parts()
    tracker = _OperationTracker()
    context_port = _ContextPort(envelope, tracker, delay_seconds=0.01, fail=True)
    clock = _AdvancingClock()
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        fixture_scenario("R1"),
        clock,
        dependencies=replace(dependencies, context=context_port),
    )
    app = RoutingApiApplication(
        verifier=Hs256ServiceBearerVerifier(
            SECRET, "service-api", "routing-api", clock.now
        ),
        contract=CanonicalContractValidator(),
        use_case=use_case,
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version="ri362-fixture",
    )
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    payload["origin"]["coordinate"] = {"lon": ORIGIN.lon, "lat": ORIGIN.lat}
    payload["destination"]["coordinate"] = {
        "lon": DESTINATION.lon,
        "lat": DESTINATION.lat,
    }
    payload["departureTime"] = DEPARTURE.isoformat()

    started = time.perf_counter()
    response = app.optimize(
        authorization=f"Bearer {_token(clock)}",
        correlation_id="ri362-failing-context",
        deadline_header=(clock.now() + timedelta(seconds=6.5)).isoformat(),
        idempotency_key="ri362-failing-context-idempotency",
        content_type="application/json",
        raw_body=json.dumps(payload).encode(),
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert response.body["status"] == "PARTIAL"
    assert response.body["routes"]
    assert elapsed < 6.5
    assert tracker.starts
    _metric(
        scenario="failing_context_private_api_fail_soft",
        http_status=response.status_code,
        response_status=response.body["status"],
        wall_ms=round(elapsed * 1000, 4),
        context_operation_starts=len(tracker.starts),
        network_provider_calls=0,
        evidence_scope="local_fixture_no_network_not_production_slo",
    )
