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
from threading import Barrier, Event, Lock

import pytest
from django.test import override_settings

from provider_core.adapters import FixtureScenario, FixtureTransitAdapter
from provider_core.cache import BoundedTTLCache, CacheState
from provider_core.canonical import Coordinate
from provider_core.capabilities import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
)
from provider_core.http import HttpResponse, SensitiveValue
from provider_core.named import KakaoWalkAdapter
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import (
    CircuitBreaker,
    Deadline,
    DeadlineExceeded,
    ProviderConcurrencyLimiter,
    RetryPolicy,
    SingleFlight,
)
from provider_core.runtime import (
    ProviderRuntimeEvidenceConfig,
    RuntimeEvidence,
    RuntimeEvidenceKind,
)
from provider_core.telemetry import MemoryTelemetrySink
from routing_api.application import (
    BoundedUseCaseRunner,
    FixtureOptimizeRouteUseCase,
    InMemoryIdempotencyStore,
    OptimizeCommand,
    RequestContext,
    RoutingApiApplication,
    RoutingUnavailableError,
    UseCaseResult,
)
from routing_api.auth import Hs256ServiceBearerVerifier
from routing_api.contract import CanonicalContractValidator
from routing_api.container import get_application
from routing_api.fanin_integration import (
    SevenPatternFixtureOptimizeRouteUseCase,
    _ProviderOperationBudget,
    _expanded_provider_operation_units,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_integration import IntegratedFixtureOptimizeRouteUseCase
from routing_api.fixture_scenarios import fixture_scenario
from routing_domain.models import CandidateSeed, LegSpec, RouteConstraints
from routing_domain.optimizer import RouteOptimizer
from routing_domain.replay_fixtures import build_r1_r4_scenarios
from routing_domain.strategy_generation import (
    CandidateExactificationPlan,
    EnrichmentKind,
    EntryTimeBasis,
    ExactEnrichmentRequest,
    ExactificationPlan,
    ExactificationStep,
)


NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
KST = timezone(timedelta(hours=9))
SECRET = b"routing-api-local-performance-test-secret-long-enough"
REQUEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "openapi"
    / "examples"
    / "routing-optimize-request.json"
)


@dataclass
class RealMonotonicClock:
    wall: datetime = NOW

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass
class AdvancingClock:
    """Wall clock that advances with monotonic time for deadline-reserve evidence."""

    wall: datetime
    started: float = field(default_factory=time.monotonic)

    def now(self) -> datetime:
        return self.wall + timedelta(seconds=time.monotonic() - self.started)

    def monotonic(self) -> float:
        return time.monotonic()


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _metric(**values: object) -> None:
    print("RI330_METRIC " + json.dumps(values, sort_keys=True))


def _r1_success_request_payload() -> dict[str, object]:
    """Load the canonical request shape and bind it to RI-070's allowlisted R1 bundle."""

    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    payload["origin"]["coordinate"] = {"lon": 127.187456, "lat": 37.222345}  # type: ignore[index]
    payload["destination"]["coordinate"] = {"lon": 127.111159, "lat": 37.394761}  # type: ignore[index]
    payload["departureTime"] = "2026-08-24T07:40:00+09:00"
    return payload


def _segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(clock: RealMonotonicClock) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload = _segment(
        {
            "iss": "service-api",
            "aud": "routing-api",
            "sub": "service-api-performance-test",
            "jti": "fixture-load",
            "exp": int((clock.now() + timedelta(minutes=5)).timestamp()),
        }
    )
    signature = hmac.new(SECRET, f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _application_with_use_case(
    clock: RealMonotonicClock,
    use_case: object,
    *,
    runner: object | None = None,
) -> RoutingApiApplication:
    return RoutingApiApplication(
        verifier=Hs256ServiceBearerVerifier(SECRET, "service-api", "routing-api", clock.now),
        contract=CanonicalContractValidator(),
        use_case=use_case,  # type: ignore[arg-type]
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version="performance-fixture",
        runner=runner,  # type: ignore[arg-type]
    )


def _api_call(
    app: RoutingApiApplication,
    clock: RealMonotonicClock,
    token: str,
    payload: dict[str, object],
    index: int,
    deadline_seconds: float,
) -> tuple[int, str, float, dict[str, object]]:
    started = time.perf_counter()
    result = app.optimize(
        authorization=f"Bearer {token}",
        correlation_id=f"perf-{index}",
        deadline_header=(clock.now() + timedelta(seconds=deadline_seconds)).isoformat(),
        idempotency_key=f"perf-idem-{index:06d}",
        content_type="application/json",
        raw_body=json.dumps(payload).encode(),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    return result.status_code, str(result.body.get("status")), elapsed_ms, dict(result.body)


def test_fixture_cold_then_warm_cache_has_one_adapter_call() -> None:
    cache = BoundedTTLCache(maximum_entries=4)
    adapter = FixtureTransitAdapter(FixtureScenario.SUCCESS)
    request = TransitSearchRequest(
        Coordinate(127.1, 37.4),
        Coordinate(127.2, 37.5),
        datetime(2026, 8, 23, 9, 0, tzinfo=KST),
    )
    key = request.fingerprint()
    provider_calls = 0

    cold_started = time.perf_counter()
    lookup = cache.get(key)
    assert lookup.state is CacheState.MISS
    provider_calls += 1
    value = adapter.search(request, deadline=Deadline.after_ms(1000))
    cache.put(key, value, ttl_seconds=60)
    cold_ms = (time.perf_counter() - cold_started) * 1000

    warm_started = time.perf_counter()
    warm = cache.get(key)
    warm_ms = (time.perf_counter() - warm_started) * 1000
    assert warm.state is CacheState.FRESH
    assert warm.value == value
    assert provider_calls == 1
    _metric(
        scenario="fixture_cache",
        cold_ms=round(cold_ms, 4),
        warm_ms=round(warm_ms, 4),
        cold_provider_calls=1,
        warm_additional_provider_calls=0,
        network_calls=0,
    )


def test_named_provider_retry_quota_cost_cache_and_circuit_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from provider_core import named

    fixture = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "packages/provider-core/provider_core/fixtures/named_kakao_walk.json"
        ).read_text(encoding="utf-8")
    )
    success_body = fixture["operations"]["route"]["success"]["body"]
    original_spec = named._SPECS[("KAKAO_WALK", "route")]
    schema_version = "ri330-kakao-walk-test-v1"
    monkeypatch.setitem(
        named._SPECS,
        ("KAKAO_WALK", "route"),
        replace(
            original_spec,
            response_schema_verified=True,
            response_schema_version=schema_version,
            estimated_cost_microunits=7,
        ),
    )
    registry = CapabilityRegistry(
        (
            Capability(
                "KAKAO_WALK",
                "route",
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )
    runtime_evidence = ProviderRuntimeEvidenceConfig(
        RuntimeEvidence(
            provider="KAKAO_WALK",
            operation="route",
            kind=kind,
            evidence_id=f"ri330-{kind.value.lower().replace('_', '-')}",
            artifact_sha256="a" * 64,
            version=schema_version,
            issued_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=1),
        )
        for kind in RuntimeEvidenceKind
    )

    class SequenceTransport:
        def __init__(self, responses):
            self.responses = list(responses)
            self.calls = 0

        def send(self, request):
            self.calls += 1
            return self.responses.pop(0)

    transport = SequenceTransport(
        (
            HttpResponse(429, "application/json", b"{}"),
            HttpResponse(
                200,
                "application/json",
                json.dumps(success_body, separators=(",", ":")).encode(),
            ),
        )
    )
    telemetry = MemoryTelemetrySink()
    adapter = KakaoWalkAdapter(
        transport,
        capabilities=registry,
        runtime_evidence=runtime_evidence,
        credential=SensitiveValue("fixture-secret"),
        telemetry=telemetry,
        clock=lambda: NOW,
        retry_policy=RetryPolicy(max_attempts=2, backoff_ms=(0,)),
    )
    request = TransitSearchRequest(
        Coordinate(127.1, 37.4),
        Coordinate(127.2, 37.5),
        datetime(2026, 8, 23, 9, 0, tzinfo=KST),
    )
    first = adapter.route(request, deadline=Deadline.after_ms(1_000))
    warm = adapter.route(request, deadline=Deadline.after_ms(1_000))
    assert first.status.value == "OK"
    assert warm.cache_hit is True
    assert transport.calls == 2
    event = telemetry.events[-1]
    assert event.provider_call_count == 2
    assert event.retry_count == 1
    assert event.quota_units == 2
    assert event.estimated_cost_microunits == 14

    failing_transport = SequenceTransport(
        (
            HttpResponse(500, "application/json", b"{}"),
            HttpResponse(500, "application/json", b"{}"),
        )
    )
    failing = KakaoWalkAdapter(
        failing_transport,
        capabilities=registry,
        runtime_evidence=runtime_evidence,
        credential=SensitiveValue("fixture-secret"),
        clock=lambda: NOW,
        retry_policy=RetryPolicy(max_attempts=2, backoff_ms=(0,)),
        breaker=CircuitBreaker(failure_threshold=1, recovery_seconds=60),
    )
    exhausted = failing.route(request, deadline=Deadline.after_ms(1_000))
    open_circuit = failing.route(request, deadline=Deadline.after_ms(1_000))
    assert exhausted.status.value == "UNAVAILABLE"
    assert open_circuit.status.value == "UNAVAILABLE"
    assert failing_transport.calls == 2
    _metric(
        scenario="named_provider_resilience_cost",
        bounded_attempts=2,
        retry_count=1,
        quota_units=2,
        estimated_cost_microunits=14,
        warm_additional_provider_calls=0,
        circuit_open_additional_provider_calls=0,
        network_provider_calls=0,
    )


@pytest.mark.parametrize("concurrency", (10, 50, 100))
def test_identical_burst_singleflight_coalesces_to_one_fixture_operation(concurrency: int) -> None:
    flight: SingleFlight[str] = SingleFlight()
    leader_entered = Event()
    release = Event()
    calls = 0
    lock = Lock()

    def operation() -> str:
        nonlocal calls
        with lock:
            calls += 1
        leader_entered.set()
        assert release.wait(timeout=5)
        return "fixture-result"

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(flight.do, "identical", operation) for _ in range(concurrency)]
        assert leader_entered.wait(timeout=2)
        time.sleep(0.02)
        release.set()
        assert [future.result(timeout=5) for future in futures] == ["fixture-result"] * concurrency
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert calls == 1
    _metric(
        scenario="singleflight_identical_burst",
        concurrency=concurrency,
        provider_operations=calls,
        coalesced=concurrency - calls,
        elapsed_ms=round(elapsed_ms, 4),
    )


@pytest.mark.parametrize("concurrency", (10, 50, 100))
def test_provider_limiter_rejects_work_above_four_in_flight(concurrency: int) -> None:
    maximum = 4
    limiter = ProviderConcurrencyLimiter(maximum)
    entered = 0
    entered_lock = Lock()
    saturated = Event()
    release = Event()

    def blocking() -> str:
        nonlocal entered
        with entered_lock:
            entered += 1
            if entered == maximum:
                saturated.set()
        assert release.wait(timeout=5)
        return "ok"

    with ThreadPoolExecutor(max_workers=maximum) as executor:
        holders = [executor.submit(limiter.run, blocking, timeout_seconds=0) for _ in range(maximum)]
        assert saturated.wait(timeout=2)
        rejected = 0
        for _ in range(concurrency - maximum):
            with pytest.raises(DeadlineExceeded):
                limiter.run(lambda: "oversubscribed", timeout_seconds=0)
            rejected += 1
        release.set()
        assert [future.result(timeout=5) for future in holders] == ["ok"] * maximum
    assert rejected == concurrency - maximum
    _metric(
        scenario="provider_concurrency_limiter",
        concurrency=concurrency,
        admitted=maximum,
        rejected=rejected,
    )


def test_candidate_and_provider_call_counts_are_hard_bounded() -> None:
    constraints = RouteConstraints(
        taxi_budget_krw=0,
        strict_taxi_budget=True,
        max_walk_seconds=10_000,
        max_transfers=3,
        max_taxi_legs=0,
        allowed_modes=frozenset({"BUS"}),
    )
    seeds = tuple(
        CandidateSeed(
            candidate_key=f"candidate-{index:03d}",
            pattern="TRANSIT_ONLY",
            legs=(
                LegSpec(
                    f"bus-{index:03d}",
                    "BUS",
                    "origin",
                    f"destination-{index:03d}",
                    f"eval-{index:03d}",
                    topology_ref=f"route-{index:03d}",
                ),
            ),
            transfer_count=0,
            coarse_p50_seconds=1000 + index,
            coarse_taxi_upper_krw=0,
        )
        for index in range(200)
    )
    optimizer = RouteOptimizer(build_r1_r4_scenarios()[0].evaluator)
    batch = optimizer.generator.generate(seeds, constraints, provider_call_count=64)
    assert batch.supplied_count == 200
    assert len(batch.candidates) <= optimizer.caps.pre_pareto
    assert len(batch.candidates) <= optimizer.caps.transit_baselines
    assert len(batch.rejected) == 195
    with pytest.raises(ValueError, match="provider call cap"):
        optimizer.generator.generate(seeds, constraints, provider_call_count=65)
    _metric(
        scenario="routing_bounds",
        supplied=batch.supplied_count,
        admitted=len(batch.candidates),
        rejected=len(batch.rejected),
        provider_call_cap=optimizer.caps.provider_calls,
        pre_pareto_cap=optimizer.caps.pre_pareto,
        user_result_cap=optimizer.caps.user_results,
    )


def test_bus_exact_request_expands_to_two_operations_atomically_before_cap() -> None:
    request = ExactEnrichmentRequest(
        "bus:cap-boundary",
        EnrichmentKind.BUS_INTELLIGENCE,
        "boarding-stop",
        "target-stop",
    )
    budget = _ProviderOperationBudget(64)
    budget.reserve(63)
    assert _expanded_provider_operation_units(request) == 2
    with pytest.raises(RoutingUnavailableError, match="provider operation cap exceeded"):
        budget.reserve(_expanded_provider_operation_units(request))
    assert budget.consumed == 63


def test_concurrent_exact_stage_over_cap_starts_zero_operations() -> None:
    budget = _ProviderOperationBudget(4)
    budget.reserve(3)
    contenders = 16
    gate = Barrier(contenders)
    starts = 0
    starts_lock = Lock()

    def attempt(_: int) -> bool:
        nonlocal starts
        gate.wait(timeout=2)
        admitted = budget.try_reserve(2)
        if admitted:
            with starts_lock:
                starts += 1
        return admitted

    with ThreadPoolExecutor(max_workers=contenders) as executor:
        admitted = tuple(executor.map(attempt, range(contenders)))

    assert admitted == (False,) * contenders
    assert starts == 0
    assert budget.consumed == 3


def test_production_fallback_attempt_settlement_is_request_context_local() -> None:
    from provider_core.named import ProviderAdapterSuite, ProviderFixtureScenario
    from routing_api.production_composition import FallbackTransitSearch

    class NoNetwork:
        def send(self, request):
            raise AssertionError("fallback regression attempted network I/O")

    suite = ProviderAdapterSuite(NoNetwork())
    success = suite.tmap.fixture("search", ProviderFixtureScenario.SUCCESS)
    empty = suite.kakao_transit.fixture(
        "search_current", ProviderFixtureScenario.EMPTY
    )

    class Adapter:
        def __init__(self, name: str) -> None:
            self.name = name

        def search(self, request, *, deadline):
            deadline.require()
            fingerprint = request.fingerprint()
            if self.name == "KAKAO" and request.origin.lon == 126.8:
                raise RuntimeError("sanitized adapter failure")
            if self.name == "KAKAO" and request.origin.lon < 127.0:
                return replace(
                    success,
                    provider="KAKAO_PUBLIC_TRANSIT",
                    operation="search_current",
                    fingerprint=fingerprint,
                )
            if self.name == "KAKAO":
                return replace(empty, fingerprint=fingerprint)
            return replace(success, fingerprint=fingerprint)

    fallback = FallbackTransitSearch(
        (Adapter("KAKAO"), Adapter("TMAP"), Adapter("ODSAY"))
    )
    requests = (
        TransitSearchRequest(Coordinate(126.9, 37.2), Coordinate(127.1, 37.4), NOW),
        TransitSearchRequest(Coordinate(127.2, 37.2), Coordinate(127.1, 37.4), NOW),
    )
    interleave = Barrier(2)

    def invoke(request):
        selected = fallback.search(request, deadline=Deadline.after_ms(1_000))
        interleave.wait(timeout=2)
        attempts = fallback.attempts
        budget = _ProviderOperationBudget(3)
        budget.reserve(3)
        budget.release(3 - len(attempts))
        return selected, attempts, budget.consumed

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(invoke, requests))

    assert [len(attempts) for _, attempts, _ in results] == [1, 2]
    assert [consumed for _, _, consumed in results] == [1, 2]
    assert [
        [attempt.provider for attempt in attempts]
        for _, attempts, _ in results
    ] == [["KAKAO_PUBLIC_TRANSIT"], ["KAKAO_PUBLIC_TRANSIT", "TMAP_TRANSIT"]]
    assert all(
        {attempt.fingerprint for attempt in attempts} == {request.fingerprint()}
        for request, (_, attempts, _) in zip(requests, results)
    )
    assert fallback.attempts == ()

    fallback.search(requests[0], deadline=Deadline.after_ms(1_000))
    assert len(fallback.attempts) == 1
    failing_request = TransitSearchRequest(
        Coordinate(126.8, 37.2), Coordinate(127.1, 37.4), NOW
    )
    with pytest.raises(RuntimeError, match="sanitized adapter failure"):
        fallback.search(failing_request, deadline=Deadline.after_ms(1_000))
    assert fallback.attempts == ()
    _metric(
        scenario="production_fallback_context_isolation",
        concurrent_requests=2,
        attempt_depths=[1, 2],
        settled_operations=[1, 2],
        stale_attempts_after_failure=0,
        network_provider_calls=0,
    )


def test_integrated_r1_reports_actual_expanded_fixture_operation_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from provider_core.named import (
        GbisAdapter,
        KakaoMobilityDirectionsAdapter,
        KakaoWalkAdapter,
    )
    from routing_api import fanin_integration

    operations: list[str] = []
    original_search = fanin_integration.FixtureTransitAdapter.search
    original_gbis = GbisAdapter.fixture
    original_taxi = KakaoMobilityDirectionsAdapter.fixture
    original_walk = KakaoWalkAdapter.fixture

    def baseline(self, *args, **kwargs):
        operations.append("TRANSIT:search")
        return original_search(self, *args, **kwargs)

    def fixture_wrapper(original, prefix):
        def wrapped(self, operation, scenario):
            operations.append(f"{prefix}:{operation}")
            return original(self, operation, scenario)

        return wrapped

    monkeypatch.setattr(fanin_integration.FixtureTransitAdapter, "search", baseline)
    monkeypatch.setattr(GbisAdapter, "fixture", fixture_wrapper(original_gbis, "GBIS"))
    monkeypatch.setattr(
        KakaoMobilityDirectionsAdapter,
        "fixture",
        fixture_wrapper(original_taxi, "TAXI"),
    )
    monkeypatch.setattr(
        KakaoWalkAdapter,
        "fixture",
        fixture_wrapper(original_walk, "WALK"),
    )

    clock = RealMonotonicClock(datetime.now(timezone.utc))
    payload = _r1_success_request_payload()
    payload["constraints"]["allowTaxiBridge"] = True  # type: ignore[index]
    app = _application_with_use_case(
        clock,
        IntegratedFixtureOptimizeRouteUseCase(fixture_scenario("R1"), clock),
    )
    result = _api_call(app, clock, _token(clock), payload, 1_500, 10)
    assert result[0] == 200
    reported = result[3]["computation"]["cache"]["providerCallCount"]  # type: ignore[index]
    assert reported == len(operations) == 10
    assert operations.count("TRANSIT:search") == 4
    assert operations.count("GBIS:arrivals") == 1
    assert operations.count("GBIS:locations") == 1
    assert operations.count("TAXI:route_current") == 4
    assert operations.count("WALK:route") == 0
    assert not any("MAPPING" in operation for operation in operations)
    _metric(
        scenario="expanded_provider_operation_accounting",
        reported_operations=reported,
        observed_fixture_operations=len(operations),
        gbis_operations=2,
        network_provider_calls=0,
    )


@pytest.mark.parametrize("concurrency", (10, 50, 100))
def test_integrated_r1_container_concurrency_measurement(
    concurrency: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from routing_api import fixture_integration

    calls = 0
    call_lock = Lock()
    original_search = fixture_integration.FixtureTransitAdapter.search

    def counting_search(self, *args, **kwargs):
        nonlocal calls
        with call_lock:
            calls += 1
        return original_search(self, *args, **kwargs)

    monkeypatch.setattr(fixture_integration.FixtureTransitAdapter, "search", counting_search)
    clock = RealMonotonicClock(datetime.now(timezone.utc))
    payload = _r1_success_request_payload()
    with override_settings(
        ROUTING_FIXTURE_SCENARIO="R1",
        ROUTING_ALLOW_FIXTURE_BACKEND=True,
        ROUTING_RUNTIME_ENVIRONMENT="TEST",
        ROUTING_SERVICE_JWT_SECRET=SECRET.decode(),
        ROUTING_SERVICE_JWT_ISSUER="service-api",
        ROUTING_SERVICE_JWT_AUDIENCE="routing-api",
    ):
        get_application.cache_clear()
        app = get_application()
        clock.wall = datetime.now(timezone.utc)
        token = _token(clock)
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                results = list(
                    executor.map(
                        lambda index: _api_call(app, clock, token, payload, index + 2_000, 10),
                        range(concurrency),
                    )
                )
        finally:
            get_application.cache_clear()

    successful = [item for item in results if item[0] == 200]
    rejected = [item for item in results if item[0] == 429]
    assert successful
    assert len(successful) + len(rejected) == concurrency
    assert all(item[3]["code"] == "RATE_LIMITED" for item in rejected)
    assert calls == 4 * len(successful)
    assert all(item[1] == "PARTIAL" for item in successful)
    assert all(
        item[3]["computation"]["cache"]["providerCallCount"] == 10
        for item in successful
    )
    assert all(item[3]["computation"]["candidateCounts"]["generated"] <= 20 for item in successful)
    assert all(len(item[3]["routes"]) <= 4 for item in successful)
    for item in successful:
        bus_legs = [
            leg
            for route in item[3]["routes"]
            for leg in route["legs"]
            if leg["mode"] == "BUS"
        ]
        assert bus_legs
        assert all(leg["busIntelligence"] is None for leg in bus_legs)
        assert "BUS_DATA_UNAVAILABLE" in item[3]["warningCodes"]
    latencies = [item[2] for item in results]
    successful_latencies = [item[2] for item in successful]
    success_p95_ms = _percentile(successful_latencies, 0.95)
    assert success_p95_ms < 6_500
    _metric(
        scenario="integrated_r1_provider_mapping_bus_optimizer",
        concurrency=concurrency,
        p50_ms=round(_percentile(latencies, 0.50), 4),
        p95_ms=round(_percentile(latencies, 0.95), 4),
        max_ms=round(max(latencies), 4),
        success_p50_ms=round(_percentile(successful_latencies, 0.50), 4),
        success_p95_ms=round(success_p95_ms, 4),
        success_count=len(successful),
        admission_rejected=len(rejected),
        partial_response_rate=round(len(successful) / concurrency, 4),
        fixture_provider_calls=calls,
        candidates_max=max(
            int(item[3]["computation"]["candidateCounts"]["generated"])
            for item in successful
        ),
        routes_max=max(len(item[3]["routes"]) for item in successful),
        network_provider_calls=0,
        evidence_scope="local_fixture_no_network_not_production_slo",
    )


def test_integrated_deadline_inside_optional_reserve_starts_no_exact_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from routing_api import fixture_integration

    calls = 0
    original_search = fixture_integration.FixtureTransitAdapter.search

    def counting_search(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original_search(self, *args, **kwargs)

    monkeypatch.setattr(fixture_integration.FixtureTransitAdapter, "search", counting_search)
    clock = RealMonotonicClock(datetime.now(timezone.utc))
    payload = _r1_success_request_payload()
    with override_settings(
        ROUTING_FIXTURE_SCENARIO="R1",
        ROUTING_ALLOW_FIXTURE_BACKEND=True,
        ROUTING_RUNTIME_ENVIRONMENT="TEST",
        ROUTING_SERVICE_JWT_SECRET=SECRET.decode(),
    ):
        get_application.cache_clear()
        app = get_application()
        clock.wall = datetime.now(timezone.utc)
        token = _token(clock)
        try:
            result = _api_call(app, clock, token, payload, 3_000, 0.24)
        finally:
            get_application.cache_clear()

    assert result[0] == 200
    assert result[1] == "NO_FEASIBLE_ROUTE"
    assert result[3]["routes"] == []
    assert result[3]["computation"]["candidateCounts"]["generated"] == 0
    assert result[3]["computation"]["cache"]["providerCallCount"] == 1
    assert calls == 1
    _metric(
        scenario="integrated_optional_exact_start_gate",
        requests=1,
        no_feasible_route_rate=1.0,
        fixture_provider_calls=calls,
        network_provider_calls=0,
        candidates_max=0,
        client_deadline_seconds=0.24,
        optional_start_reserve_seconds=1.75,
    )


def test_exact_dependency_levels_parallelize_same_depth_and_preserve_order() -> None:
    r1_endpoints = (
        (127.187456, 37.222345),
        (127.111159, 37.394761),
    )

    class DelayedProviderPorts:
        def __init__(self, delegate: object) -> None:
            self._delegate = delegate
            self._guard = Lock()
            self._active = 0
            self.maximum_active = 0
            self.intervals: list[tuple[str, datetime, float, float]] = []
            self.bus_observation_starts: list[float] = []

        def __getattr__(self, name: str):
            return getattr(self._delegate, name)

        def _delayed(self, kind: str, request, invoke):
            started = time.perf_counter()
            with self._guard:
                self._active += 1
                self.maximum_active = max(self.maximum_active, self._active)
            try:
                time.sleep(0.06)
                return invoke()
            finally:
                finished = time.perf_counter()
                with self._guard:
                    self._active -= 1
                    self.intervals.append(
                        (kind, request.departure_time, started, finished)
                    )

        def transit(self, request, *, deadline):
            endpoints = (
                (request.origin.lon, request.origin.lat),
                (request.destination.lon, request.destination.lat),
            )
            if endpoints == r1_endpoints:
                return self._delegate.transit(request, deadline=deadline)
            return self._delayed(
                "TRANSIT",
                request,
                lambda: self._delegate.transit(request, deadline=deadline),
            )

        def walk(self, request, *, deadline):
            return self._delayed(
                "WALK",
                request,
                lambda: self._delegate.walk(request, deadline=deadline),
            )

        def taxi(self, request, *, deadline):
            return self._delayed(
                "TAXI",
                request,
                lambda: self._delegate.taxi(request, deadline=deadline),
            )

        def arrivals(self, query, *, deadline):
            with self._guard:
                self.bus_observation_starts.append(time.perf_counter())
            return self._delegate.arrivals(query, deadline=deadline)

        def locations(self, query, *, deadline):
            with self._guard:
                self.bus_observation_starts.append(time.perf_counter())
            return self._delegate.locations(query, deadline=deadline)

    clock = AdvancingClock(datetime.now(timezone.utc))
    scenario = fixture_scenario("R1")
    dependencies = fixture_fan_in_dependencies(scenario)
    providers = DelayedProviderPorts(dependencies.providers)
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario,
        clock,
        dependencies=replace(dependencies, providers=providers),
    )
    payload = _r1_success_request_payload()
    payload["constraints"]["allowTaxiBridge"] = True  # type: ignore[index]
    context = RequestContext(
        "perf-exact-levels",
        "perf-exact-levels-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        Event(),
    )

    outcome = use_case.execute(OptimizeCommand(payload), context)
    assert outcome.response["routes"]
    assert 2 <= providers.maximum_active <= 8
    assert len(providers.intervals) >= 2

    overlapping: tuple[
        tuple[str, datetime, float, float],
        tuple[str, datetime, float, float],
    ] | None = None
    for index, left in enumerate(providers.intervals):
        for right in providers.intervals[index + 1 :]:
            if left[2] < right[3] and right[2] < left[3]:
                overlapping = left, right
                break
        if overlapping is not None:
            break
    assert overlapping is not None
    left, right = overlapping
    parallel_span = max(left[3], right[3]) - min(left[2], right[2])
    serial_sum = (left[3] - left[2]) + (right[3] - right[2])
    assert parallel_span < serial_sum * 0.8

    assert len({item[1] for item in providers.intervals}) > 1
    departure = datetime.fromisoformat("2026-08-24T07:40:00+09:00")
    first_a = ExactificationStep(
        "candidate-a:0", "candidate-a", 0, "a-0", "TAXI",
        "origin", "hub-a", "eval-a-0", None,
        EntryTimeBasis.REQUEST_DEPARTURE, None, 0,
    )
    second_a = ExactificationStep(
        "candidate-a:1", "candidate-a", 1, "a-1", "BUS",
        "hub-a", "destination", "eval-a-1", "route-a",
        EntryTimeBasis.PREDECESSOR_P50_END, first_a.step_key, 30,
    )
    first_b = ExactificationStep(
        "candidate-b:0", "candidate-b", 0, "b-0", "BUS",
        "origin", "destination", "eval-b-0", "route-b",
        EntryTimeBasis.REQUEST_DEPARTURE, None, 0,
    )
    dependency_plan = ExactificationPlan(
        (
            CandidateExactificationPlan("candidate-a", departure, (first_a, second_a)),
            CandidateExactificationPlan("candidate-b", departure, (first_b,)),
        ),
        candidate_cap=2,
        logical_provider_call_cap=4,
    )
    assert {step.step_key for step in dependency_plan.ready_steps(())} == {
        first_a.step_key,
        first_b.step_key,
    }
    assert second_a.step_key not in {
        step.step_key for step in dependency_plan.ready_steps(())
    }
    assert {step.step_key for step in dependency_plan.ready_steps(
        (first_a.step_key, first_b.step_key)
    )} == {second_a.step_key}
    predecessor_end = departure + timedelta(seconds=300)
    assert second_a.ready_at(
        departure, predecessor_p50_end_at=predecessor_end
    ) == predecessor_end + timedelta(seconds=30)
    _metric(
        scenario="candidate_entry_exact_depth_parallelism",
        delayed_exact_calls=len(providers.intervals),
        maximum_active=providers.maximum_active,
        overlapping_pair_span_ms=round(parallel_span * 1000, 4),
        overlapping_pair_serial_ms=round(serial_sum * 1000, 4),
        distinct_provider_departure_times=len(
            {item[1] for item in providers.intervals}
        ),
        topological_dependency_asserted=True,
        network_provider_calls=0,
    )


def test_exact_hard_stop_keeps_reserve_and_charges_running_noncooperative_work() -> None:
    r1_endpoints = (
        (127.187456, 37.222345),
        (127.111159, 37.394761),
    )
    release = Event()
    entered = Event()
    guard = Lock()
    started_calls = 0
    finished_calls = 0

    class BlockingProviderPorts:
        def __init__(self, delegate: object) -> None:
            self._delegate = delegate

        def __getattr__(self, name: str):
            return getattr(self._delegate, name)

        def _blocking(self, invoke):
            nonlocal started_calls, finished_calls
            with guard:
                started_calls += 1
                entered.set()
            assert release.wait(timeout=5)
            try:
                return invoke()
            finally:
                with guard:
                    finished_calls += 1

        def transit(self, request, *, deadline):
            endpoints = (
                (request.origin.lon, request.origin.lat),
                (request.destination.lon, request.destination.lat),
            )
            if endpoints == r1_endpoints:
                return self._delegate.transit(request, deadline=deadline)
            return self._blocking(
                lambda: self._delegate.transit(request, deadline=deadline)
            )

        def walk(self, request, *, deadline):
            return self._blocking(
                lambda: self._delegate.walk(request, deadline=deadline)
            )

        def taxi(self, request, *, deadline):
            return self._blocking(
                lambda: self._delegate.taxi(request, deadline=deadline)
            )

    clock = AdvancingClock(datetime.now(timezone.utc))
    scenario = fixture_scenario("R1")
    dependencies = fixture_fan_in_dependencies(scenario)
    providers = BlockingProviderPorts(dependencies.providers)
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario,
        clock,
        dependencies=replace(dependencies, providers=providers),
    )
    payload = _r1_success_request_payload()
    payload["constraints"]["allowTaxiBridge"] = True  # type: ignore[index]
    effective_deadline = clock.now() + timedelta(seconds=2.05)
    context = RequestContext(
        "perf-hard-stop",
        "perf-hard-stop-idempotency",
        effective_deadline,
        effective_deadline,
        True,
        Event(),
    )

    started = time.perf_counter()
    try:
        outcome = use_case.execute(OptimizeCommand(payload), context)
        elapsed = time.perf_counter() - started
        assert entered.is_set()
        with guard:
            started_at_return = started_calls
            finished_at_return = finished_calls
        time.sleep(0.05)
        with guard:
            starts_after_return = started_calls
        remaining = (effective_deadline - clock.now()).total_seconds()
        charged = use_case.trace.provider_call_count
    finally:
        release.set()

    completion_deadline = time.monotonic() + 2
    while time.monotonic() < completion_deadline:
        with guard:
            if finished_calls >= started_at_return:
                break
        time.sleep(0.01)

    assert outcome.response["status"] == "PARTIAL"
    assert outcome.response["routes"]
    assert 0.6 < elapsed < 1.3
    assert 0.95 <= remaining <= 1.25
    assert started_at_return > 0
    assert finished_at_return == 0
    assert starts_after_return == started_at_return
    assert charged >= 1 + started_at_return
    with guard:
        assert finished_calls >= started_at_return
    _metric(
        scenario="exact_hard_stop_noncooperative_charge",
        elapsed_ms=round(elapsed * 1000, 4),
        reserve_remaining_ms=round(remaining * 1000, 4),
        running_calls_at_return=started_at_return,
        new_calls_after_return=starts_after_return - started_at_return,
        charged_provider_operations=charged,
        network_provider_calls=0,
    )


@pytest.mark.parametrize("concurrency", (10, 50, 100))
def test_optimizer_r1_fixture_cpu_concurrency_measurement(concurrency: int) -> None:
    scenario = build_r1_r4_scenarios()[0]
    optimizer = RouteOptimizer(scenario.evaluator)

    def run(_: int) -> tuple[float, int, int]:
        started = time.perf_counter()
        result = optimizer.optimize(scenario.seeds, scenario.departure_at, scenario.constraints)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, result.counts.generated, len(result.routes)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = list(executor.map(run, range(concurrency)))
    latencies = [item[0] for item in results]
    assert all(item[1] <= optimizer.caps.pre_pareto for item in results)
    assert all(item[2] <= optimizer.caps.user_results for item in results)
    _metric(
        scenario="optimizer_r1_cpu_only",
        concurrency=concurrency,
        p50_ms=round(_percentile(latencies, 0.50), 4),
        p95_ms=round(_percentile(latencies, 0.95), 4),
        max_ms=round(max(latencies), 4),
        generated_max=max(item[1] for item in results),
        returned_max=max(item[2] for item in results),
    )


@pytest.mark.parametrize("concurrency", (10, 50, 100))
def test_non_cooperative_work_is_deadlined_and_excess_is_fail_fast_429(concurrency: int) -> None:
    clock = RealMonotonicClock()
    delegate = FixtureOptimizeRouteUseCase(clock, optional_complete=True)
    maximum_inflight = 8
    entered = 0
    entered_lock = Lock()
    saturated = Event()
    release = Event()

    class NonCooperativeUseCase:
        def execute(self, command, context) -> UseCaseResult:
            nonlocal entered
            with entered_lock:
                entered += 1
                if entered == maximum_inflight:
                    saturated.set()
            assert release.wait(timeout=5)
            return delegate.execute(command, context)

    runner = BoundedUseCaseRunner(maximum_inflight=maximum_inflight)
    app = _application_with_use_case(clock, NonCooperativeUseCase(), runner=runner)
    token = _token(clock)
    payload = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=maximum_inflight) as executor:
            holder_futures = [
                executor.submit(
                    _api_call, app, clock, token, payload, index + 10_000, 0.02
                )
                for index in range(maximum_inflight)
            ]
            assert saturated.wait(timeout=2)
            time.sleep(0.03)
            holders = [future.result(timeout=2) for future in holder_futures]

        with ThreadPoolExecutor(max_workers=max(1, concurrency - maximum_inflight)) as executor:
            overload = list(
                executor.map(
                    lambda index: _api_call(app, clock, token, payload, index + 20_000, 10),
                    range(concurrency - maximum_inflight),
                )
            )
        wall_ms = (time.perf_counter() - started) * 1000
    finally:
        release.set()
        runner.shutdown()

    assert all(item[0] == 504 for item in holders)
    assert all(item[3]["code"] == "ROUTING_DEADLINE_EXCEEDED" for item in holders)
    assert all(item[0] == 429 for item in overload)
    assert all(item[3]["code"] == "RATE_LIMITED" for item in overload)
    latencies = [item[2] for item in holders + overload]
    _metric(
        scenario="bounded_admission_deadline_and_fail_fast",
        concurrency=concurrency,
        deadline_504=len(holders),
        admission_429=len(overload),
        timeout_rate=round(len(holders) / concurrency, 4),
        admission_reject_rate=round(len(overload) / concurrency, 4),
        p50_ms=round(_percentile(latencies, 0.50), 4),
        p95_ms=round(_percentile(latencies, 0.95), 4),
        wall_ms=round(wall_ms, 4),
        executor_workers=maximum_inflight,
    )
