from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from bus_intelligence_core import (
    ETA_CONTEXT_FEATURE_NAMES,
    ETA_CONTEXT_SERVING_SCHEMA_VERSION,
    SEAT_RISK_CONTEXT_FEATURE_NAMES,
    SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
    TRAFFIC_CONTEXT_FUTURE_EXCLUDED,
    TRAFFIC_CONTEXT_SCHEMA_MISMATCH,
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_FUTURE_EXCLUDED,
    WEATHER_CONTEXT_MISSING,
    WEATHER_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_STALE,
    BusIntelligenceEngine,
    BusIntelligenceRequest,
    EtaFeatureContext,
    EtaPrediction,
    FeatureContextPolicy,
    SeatRiskFeatureContext,
    SeatRiskPrediction,
    TrafficFeatureContext,
    VehicleObservation,
    WeatherFeatureContext,
    build_eta_context_features,
    build_seat_risk_context_features,
)
from feature_builder import (
    NormalizedFeatureObservation,
    build_eta_features,
    build_seat_features,
)
from provider_core import Coordinate, ProviderStatus, TransitSearchRequest
from provider_core.context import TrafficLinkContext, WeatherContext
from provider_core.context_queries import GitsTrafficCorridorQuery, KmaWeatherQuery
from provider_core.named import (
    GitsTrafficAdapter,
    KmaContextAdapter,
    ProviderFixtureScenario,
)
from provider_core.resilience import Deadline
from routing_api.application import OptimizeCommand, RequestContext
from routing_api.contract import CanonicalContractValidator
from routing_api.fanin_integration import (
    CanonicalFanInOptimizeRouteUseCase,
    InMemoryOptimizationPersistence,
    SevenPatternFixtureOptimizeRouteUseCase,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.tests.test_bus_context_integration import _RecordingContextPort
from routing_api.tests.test_fixture_integration import _CausalProviderPorts
from routing_domain import (
    BusWaitContribution,
    CandidateSeed,
    LegCost,
    LegSpec,
    MoneyRange,
    RouteConstraints,
    RouteOptimizer,
    StaticLegEvaluator,
    TimeEstimate,
)
from routing_domain.replay_fixtures import build_r1_r4_scenarios
from routing_worker.feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)

from replay_support import FakeClock, map_canonical_bus_leg, request_payload, run_provider


KST = timezone(timedelta(hours=9))
AS_OF = datetime(2026, 8, 24, 8, 49, tzinfo=KST)
COORDINATE = Coordinate(127.10, 37.39)
SCENARIO = build_r1_r4_scenarios()[0]
HIGH_MAPPING = map_canonical_bus_leg(run_provider(SCENARIO))


class _NoCallTransport:
    def send(self, request):
        raise AssertionError(f"fixture adapter attempted network I/O: {request}")


def _worker_observation(
    eta_context: EtaFeatureContext | None,
    seat_context: SeatRiskFeatureContext | None,
) -> NormalizedFeatureObservation:
    observed = AS_OF - timedelta(seconds=10)
    return NormalizedFeatureObservation(
        trip_id="ri-362-trip",
        route_id=HIGH_MAPPING.route_id,
        direction="OUTBOUND",
        observed_at=observed,
        ingested_at=observed + timedelta(seconds=2),
        valid_at=AS_OF,
        query_at=AS_OF,
        current_station_sequence=2,
        target_station_sequence=5,
        current_remaining_seats=0,
        capacity_confidence=0.8,
        eta_feature_context=eta_context,
        seat_risk_feature_context=seat_context,
    )


def test_provider_context_normalization_matches_bus_and_worker_v2_schemas() -> None:
    transport = _NoCallTransport()
    weather_query = KmaWeatherQuery.from_coordinate(COORDINATE, AS_OF)
    weather_fixture = KmaContextAdapter(transport).fixture_context(
        weather_query, ProviderFixtureScenario.SUCCESS
    )
    assert weather_fixture.status is ProviderStatus.OK
    assert isinstance(weather_fixture.payload[0], WeatherContext)
    assert weather_fixture.payload[0].precipitation_mm == 0.0

    weather_drift = KmaContextAdapter(transport).fixture_context(
        weather_query, ProviderFixtureScenario.SCHEMA_DRIFT
    )
    assert weather_drift.status is ProviderStatus.BAD_RESPONSE
    assert CanonicalFanInOptimizeRouteUseCase._weather_feature(
        weather_drift, AS_OF
    ) is None

    traffic_query = GitsTrafficCorridorQuery.from_bounds(
        COORDINATE,
        Coordinate(127.11, 37.40),
        AS_OF,
        maximum_links=1,
    )
    traffic_fixture = GitsTrafficAdapter(transport).fixture_context(
        traffic_query, ProviderFixtureScenario.SUCCESS
    )
    assert traffic_fixture.status is ProviderStatus.OK
    assert isinstance(traffic_fixture.payload[0], TrafficLinkContext)
    rejected_traffic = GitsTrafficAdapter(transport).fixture_context(
        GitsTrafficCorridorQuery.from_corridor(
            (COORDINATE, Coordinate(127.11, 37.40)),
            AS_OF,
            relevant_link_external_ids=("not-the-fixture-link",),
        ),
        ProviderFixtureScenario.SUCCESS,
    )
    assert rejected_traffic.status is ProviderStatus.BAD_RESPONSE
    assert CanonicalFanInOptimizeRouteUseCase._traffic_feature(
        rejected_traffic, AS_OF
    ) is None

    weather = CanonicalFanInOptimizeRouteUseCase._weather_feature(
        SimpleNamespace(
            status=ProviderStatus.OK,
            payload=(WeatherContext(COORDINATE, AS_OF, 0.0, 0.0),),
        ),
        AS_OF,
    )
    traffic = CanonicalFanInOptimizeRouteUseCase._traffic_feature(
        SimpleNamespace(
            status=ProviderStatus.OK,
            payload=(TrafficLinkContext("relevant-zero", 0, 0.0, AS_OF),),
        ),
        AS_OF,
    )
    assert weather is not None and traffic is not None
    traffic = replace(traffic, incident_present=False)
    eta_context = EtaFeatureContext(weather=weather, traffic=traffic)
    seat_context = SeatRiskFeatureContext(weather=weather, traffic=traffic)

    eta_serving = build_eta_context_features(eta_context, AS_OF)
    seat_serving = build_seat_risk_context_features(seat_context, AS_OF)
    assert eta_serving.schema_version == ETA_CONTEXT_SERVING_SCHEMA_VERSION
    assert seat_serving.schema_version == SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION
    assert eta_serving.feature_names == ETA_CONTEXT_FEATURE_NAMES
    assert seat_serving.feature_names == SEAT_RISK_CONTEXT_FEATURE_NAMES
    assert eta_serving.as_mapping["weather_temperature_c"] == 0.0
    assert eta_serving.as_mapping["traffic_speed_kph"] == 0.0
    assert eta_serving.as_mapping["traffic_incident_present"] is False

    observation = _worker_observation(eta_context, seat_context)
    eta_train = build_eta_features(observation)
    seat_train = build_seat_features(observation)
    assert eta_train.schema_version == ETA_SCHEMA_VERSION
    assert seat_train.schema_version == SEAT_SCHEMA_VERSION
    assert eta_train.feature_names == ETA_FEATURE_NAMES
    assert seat_train.feature_names == SEAT_FEATURE_NAMES
    assert ETA_CONTEXT_SERVING_SCHEMA_VERSION in ETA_SCHEMA_VERSION
    assert SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION in SEAT_SCHEMA_VERSION
    assert eta_train.as_mapping["traffic_incident_present"] is False
    assert seat_train.as_mapping["current_remaining_seats"] == 0


def test_context_as_of_matrix_never_converts_missing_future_or_stale_to_zero() -> None:
    mixed = CanonicalFanInOptimizeRouteUseCase._traffic_feature(
        SimpleNamespace(
            status=ProviderStatus.OK,
            payload=(
                TrafficLinkContext("past-zero", 0, 0.0, AS_OF),
                TrafficLinkContext("future", 100, 1.0, AS_OF + timedelta(seconds=1)),
            ),
        ),
        AS_OF,
    )
    assert mixed is not None
    assert mixed.speed_kph == 0.0
    assert mixed.travel_time_seconds == 0.0

    all_future = CanonicalFanInOptimizeRouteUseCase._traffic_feature(
        SimpleNamespace(
            status=ProviderStatus.OK,
            payload=(
                TrafficLinkContext("future", 0, 0.0, AS_OF + timedelta(seconds=1)),
            ),
        ),
        AS_OF,
    )
    all_future_vector = build_eta_context_features(
        EtaFeatureContext(traffic=all_future), AS_OF
    )
    assert all_future_vector.as_mapping["traffic_speed_kph"] is None
    assert TRAFFIC_CONTEXT_FUTURE_EXCLUDED in all_future_vector.missing_flags

    future_weather = WeatherFeatureContext(
        AS_OF + timedelta(seconds=1),
        WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=0.0,
    )
    future_vector = build_eta_context_features(
        EtaFeatureContext(weather=future_weather), AS_OF
    )
    assert future_vector.as_mapping["weather_temperature_c"] is None
    assert WEATHER_CONTEXT_FUTURE_EXCLUDED in future_vector.missing_flags

    stale_weather = WeatherFeatureContext(
        AS_OF - timedelta(seconds=11),
        WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=0.0,
    )
    schema_drift = TrafficFeatureContext(
        AS_OF,
        "traffic-schema-drift",
        speed_kph=0.0,
        incident_present=False,
    )
    rejected = build_eta_context_features(
        EtaFeatureContext(weather=stale_weather, traffic=schema_drift),
        AS_OF,
        policy=FeatureContextPolicy(
            weather_max_age_seconds=10,
            traffic_max_age_seconds=300,
        ),
    )
    assert rejected.as_mapping["weather_temperature_c"] is None
    assert rejected.as_mapping["traffic_speed_kph"] is None
    assert WEATHER_CONTEXT_STALE in rejected.missing_flags
    assert TRAFFIC_CONTEXT_SCHEMA_MISMATCH in rejected.missing_flags

    missing = build_eta_context_features(None, AS_OF)
    assert missing.as_mapping["weather_temperature_c"] is None
    assert WEATHER_CONTEXT_MISSING in missing.missing_flags


class _ContextEtaPredictor:
    def __init__(self) -> None:
        self.inputs = []

    def predict(self, value):
        self.inputs.append(value)
        weather = value.feature_context.weather
        offset = 120 if weather is not None and weather.temperature_c == 0.0 else 600
        return EtaPrediction(
            value.prediction_at + timedelta(seconds=offset),
            value.prediction_at + timedelta(seconds=offset + 60),
            "POSITION_MODEL",
            model_version="eta-context-replay-v2",
            confidence=0.9,
            model_readiness="FIXTURE_ONLY",
        )


class _ContextSeatPredictor:
    def __init__(self) -> None:
        self.inputs = []

    def predict(self, value):
        self.inputs.append(value)
        weather = value.feature_context.weather
        no_seat = (
            0.8
            if weather is not None and weather.precipitation_mm == 10.0
            else 0.0
        )
        return SeatRiskPrediction(
            no_seat,
            min(1.0, no_seat + 0.1),
            min(1.0, no_seat + 0.2),
            "seat-context-replay-v2",
            0.9,
            model_readiness="FIXTURE_ONLY",
        )


def _contextual_bus(
    temperature_c: float,
    precipitation_mm: float,
    *,
    service_type: str = "SEATED",
):
    weather = WeatherFeatureContext(
        AS_OF,
        WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=temperature_c,
        precipitation_mm=precipitation_mm,
    )
    eta = _ContextEtaPredictor()
    seat = _ContextSeatPredictor()
    result = BusIntelligenceEngine(eta, seat).enrich(
        BusIntelligenceRequest(
            HIGH_MAPPING.grade.value,
            HIGH_MAPPING.allows_bus_intelligence,
            HIGH_MAPPING.score,
            HIGH_MAPPING.mapping_version,
            AS_OF,
            AS_OF,
            "canonical-target",
            service_type,
            (
                VehicleObservation(
                    "veh-context",
                    HIGH_MAPPING.route_id,
                    "OUTBOUND",
                    "canonical-board",
                    AS_OF,
                    None,
                    0,
                    None,
                ),
            ),
            eta_feature_context=EtaFeatureContext(weather=weather),
            seat_risk_feature_context=SeatRiskFeatureContext(weather=weather),
        )
    )
    return result, eta, seat


def _optimize_with_bus_wait(wait) -> object:
    bus = CandidateSeed(
        "context-bus",
        "TRANSIT_ONLY",
        (
            LegSpec(
                "context-bus-leg",
                "BUS",
                "origin",
                "destination",
                "bus-cost",
                bus_wait=BusWaitContribution(
                    wait.expected_wait_seconds,
                    wait.p90_wait_seconds,
                ),
                topology_ref=HIGH_MAPPING.route_id,
            ),
        ),
        0,
        600,
        0,
    )
    taxi = CandidateSeed(
        "context-taxi",
        "TAXI_ONLY",
        (LegSpec("context-taxi-leg", "TAXI", "origin", "destination", "taxi-cost"),),
        0,
        1_000,
        5_000,
    )
    evaluator = StaticLegEvaluator(
        {
            "bus-cost": LegCost(
                TimeEstimate(0, 0),
                TimeEstimate(600, 660),
                MoneyRange(0, 0, 0),
                0.9,
            ),
            "taxi-cost": LegCost(
                TimeEstimate(0, 0),
                TimeEstimate(1_000, 1_100),
                MoneyRange(5_000, 5_000, 5_000),
                0.9,
            ),
        }
    )
    return RouteOptimizer(evaluator).optimize(
        (bus, taxi),
        AS_OF,
        RouteConstraints(
            10_000,
            True,
            0,
            0,
            1,
            frozenset({"BUS", "TAXI"}),
        ),
    )


def test_eta_and_seat_contexts_are_family_isolated_and_change_route_only_via_models() -> None:
    early, early_eta, early_seat = _contextual_bus(0.0, 0.0)
    late, late_eta, late_seat = _contextual_bus(30.0, 0.0)
    wet, wet_eta, wet_seat = _contextual_bus(0.0, 10.0)

    assert early.enrichment_applied and late.enrichment_applied and wet.enrichment_applied
    assert late.expected_wait_seconds > early.expected_wait_seconds
    assert late.candidate_vehicles[0].seat_risk_at_boarding == (
        early.candidate_vehicles[0].seat_risk_at_boarding
    )
    assert wet.candidate_vehicles[0].eta == early.candidate_vehicles[0].eta
    assert wet.candidate_vehicles[0].seat_risk_at_boarding != (
        early.candidate_vehicles[0].seat_risk_at_boarding
    )
    assert all(
        isinstance(value.feature_context, EtaFeatureContext)
        for value in (*early_eta.inputs, *late_eta.inputs, *wet_eta.inputs)
    )
    assert all(
        isinstance(value.feature_context, SeatRiskFeatureContext)
        for value in (*early_seat.inputs, *late_seat.inputs, *wet_seat.inputs)
    )

    general, _, general_seat = _contextual_bus(0.0, 10.0, service_type="GENERAL")
    assert general.enrichment_applied
    assert general_seat.inputs == []
    assert general.candidate_vehicles[0].seat_risk_at_boarding is None

    early_routes = _optimize_with_bus_wait(early)
    late_routes = _optimize_with_bus_wait(late)
    assert early_routes.recommendations.fastest != late_routes.recommendations.fastest
    for result in (early_routes, late_routes):
        returned = {route.route_id for route in result.routes}
        assert set(result.pareto_route_ids) <= returned
        assert all(
            value is None or value in returned
            for value in (
                result.recommendations.fastest,
                result.recommendations.stable,
                result.recommendations.efficient,
                result.recommendations.public_transit_only,
            )
        )
        assert all(
            route.total_duration.p90_seconds >= route.total_duration.p50_seconds
            and route.taxi_cost.upper_krw <= 10_000
            for route in result.routes
        )


class _ContextModePort(_RecordingContextPort):
    def __init__(self, base_envelope, mode: str):
        super().__init__(
            base_envelope,
            operations=frozenset({"weather_context"}),
        )
        self.mode = mode

    def weather(self, query, *, deadline):
        del deadline
        self.weather_queries.append(query)
        if self.mode == "timeout":
            raise TimeoutError("optional KMA timeout")
        status = (
            ProviderStatus.BAD_RESPONSE
            if self.mode == "schema_drift"
            else ProviderStatus.OK
        )
        payload = None
        if self.mode == "fresh":
            payload = (WeatherContext(query.coordinate, query.observed_at, 0.0, 0.0),)
        elif self.mode == "future":
            payload = (
                WeatherContext(
                    query.coordinate,
                    query.observed_at + timedelta(seconds=1),
                    0.0,
                    0.0,
                ),
            )
        elif self.mode == "empty":
            payload = ()
        return replace(
            self.base_envelope,
            provider="KMA",
            operation="weather_context",
            fingerprint=query.fingerprint(),
            observed_at=query.observed_at,
            status=status,
            schema_version="kma.replay.v1",
            normalized_count=0 if payload is None else len(payload),
            payload=payload,
        )


class _OptionalFaultProviders(_CausalProviderPorts):
    def __init__(self, base, fault: str | None = None):
        super().__init__(base, taxi_upper_krw=2_500)
        self.fault = fault
        self.arrival_calls = 0
        self.location_calls = 0

    def arrivals(self, query, *, deadline):
        self.arrival_calls += 1
        envelope = super().arrivals(query, deadline=deadline)
        if self.fault == "arrivals_empty":
            return replace(envelope, status=ProviderStatus.OK, payload=(), normalized_count=0)
        if self.fault == "arrivals_timeout":
            return replace(
                envelope,
                status=ProviderStatus.TIMEOUT,
                payload=None,
                normalized_count=0,
            )
        return envelope

    def locations(self, query, *, deadline):
        self.location_calls += 1
        envelope = super().locations(query, deadline=deadline)
        if self.fault == "locations_empty":
            return replace(envelope, status=ProviderStatus.OK, payload=(), normalized_count=0)
        if self.fault == "locations_timeout":
            return replace(
                envelope,
                status=ProviderStatus.TIMEOUT,
                payload=None,
                normalized_count=0,
            )
        return envelope


class _RecordingPredictor:
    def __init__(self, delegate):
        self.delegate = delegate
        self.inputs = []

    def predict(self, value):
        self.inputs.append(value)
        return self.delegate.predict(value)


def _execute_context_api(
    *,
    context_mode: str | None,
    provider_fault: str | None = None,
    unknown_service: bool = False,
    low_mapping: bool = False,
):
    clock = FakeClock()
    scenario = fixture_scenario("MAPPING_LOW" if low_mapping else "R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = _OptionalFaultProviders(base.providers, provider_fault)
    envelope = base.providers.transit(
        TransitSearchRequest(
            Coordinate(127.187456, 37.222345),
            Coordinate(127.111159, 37.394761),
            SCENARIO.departure_at,
        ),
        deadline=Deadline.after_ms(1_000),
    )
    context_port = (
        None if context_mode is None else _ContextModePort(envelope, context_mode)
    )
    mapping = base.mapping
    if unknown_service:
        class _UnknownServiceMapping:
            def __call__(self, evidence, evaluated_at):
                resolved, target = mapping(evidence, evaluated_at)
                return resolved, replace(target, route_type="UNKNOWN")

        mapping = _UnknownServiceMapping()
    eta = _RecordingPredictor(base.eta_predictor)
    seat = _RecordingPredictor(base.seat_predictor)
    persistence = InMemoryOptimizationPersistence()
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario,
        clock,
        dependencies=replace(
            base,
            providers=providers,
            mapping=mapping,
            context=context_port,
            eta_predictor=eta,
            seat_predictor=seat,
            persistence=persistence,
        ),
        persistence=persistence,
    )
    payload = request_payload(SCENARIO)
    payload["constraints"]["allowTaxiBridge"] = True  # type: ignore[index]
    request_context = RequestContext(
        "ri-362-context-correlation",
        "ri-362-context-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), request_context).response
    return response, use_case.trace, providers, context_port, eta, seat, persistence.values[0]


@pytest.mark.parametrize(
    ("context_mode", "provider_fault"),
    (
        ("empty", None),
        ("future", None),
        ("schema_drift", None),
        ("timeout", None),
        ("fresh", "arrivals_empty"),
        ("fresh", "arrivals_timeout"),
        ("fresh", "locations_empty"),
        ("fresh", "locations_timeout"),
    ),
)
def test_optional_context_and_gbis_failures_are_partial_not_500(
    context_mode: str,
    provider_fault: str | None,
) -> None:
    response, trace, _, _, _, _, _ = _execute_context_api(
        context_mode=context_mode,
        provider_fault=provider_fault,
    )
    assert response["routes"]
    assert response["status"] == "PARTIAL"
    assert trace.provider_call_count <= 64
    assert CanonicalContractValidator().validate_optimize_response(response) == ()
    if provider_fault is not None:
        assert all(
            leg["busIntelligence"] is None
            for route in response["routes"]
            for leg in route["legs"]
            if leg["mode"] == "BUS"
        )


def test_high_mapping_context_is_deterministic_leg_local_and_persisted() -> None:
    first = _execute_context_api(context_mode="fresh")
    second = _execute_context_api(context_mode="fresh")
    first_response, first_trace, _, first_port, _, _, first_record = first
    second_response, second_trace, _, _, _, _, second_record = second
    assert first_response == second_response
    assert replace(
        first_trace,
        model_inference=replace(first_trace.model_inference, elapsed_ms=0),
    ) == replace(
        second_trace,
        model_inference=replace(second_trace.model_inference, elapsed_ms=0),
    )
    for trace in (first_trace, second_trace):
        assert 0 <= trace.model_inference.elapsed_ms <= trace.model_inference.hard_cap_ms
    assert first_record == second_record
    assert first_port is not None and first_port.weather_queries
    assert any(
        value["provider"] == "KMA" and value["operation"] == "weather_context"
        for value in first_response["providerStatus"]
    )
    for route in first_response["routes"]:
        for leg in route["legs"]:
            has_kma = any(
                value["provider"] == "FIXTURE::KMA/weather_context"
                for value in leg["provenance"]
            )
            assert has_kma is (leg["mode"] == "BUS")
    assert any(
        value["provider"] == "KMA" and value["operation"] == "weather_context"
        for value in first_record.run.provider_summary["envelopes"]
    )


def test_unknown_service_starts_no_gbis_context_or_model_and_releases_reservation() -> None:
    enabled = _execute_context_api(context_mode="fresh", unknown_service=True)
    disabled = _execute_context_api(context_mode=None, unknown_service=True)
    response, trace, providers, port, eta, seat, _ = enabled
    assert response["routes"]
    assert providers.arrival_calls == providers.location_calls == 0
    assert port is not None and port.weather_queries == []
    assert eta.inputs == seat.inputs == []
    assert trace.provider_call_count == disabled[1].provider_call_count


def test_low_mapping_starts_no_gbis_context_or_model_and_releases_reservation() -> None:
    enabled = _execute_context_api(context_mode="fresh", low_mapping=True)
    disabled = _execute_context_api(context_mode=None, low_mapping=True)
    response, trace, providers, port, eta, seat, _ = enabled
    assert response["routes"]
    assert providers.arrival_calls == providers.location_calls == 0
    assert port is not None and port.weather_queries == []
    assert eta.inputs == seat.inputs == []
    assert trace.provider_call_count == disabled[1].provider_call_count
