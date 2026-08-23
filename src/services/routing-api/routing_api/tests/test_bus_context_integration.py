from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from bus_intelligence_core import (
    EtaFeatureContext,
    SeatRiskFeatureContext,
    TrafficFeatureContext,
    WeatherFeatureContext,
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_SCHEMA_VERSION,
)
from provider_core.canonical import Coordinate
from provider_core.context import TrafficLinkContext, WeatherContext
from provider_core.envelope import ProviderStatus
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from routing_api.application import OptimizeCommand, RequestContext, RoutingUnavailableError
from routing_api.fanin_integration import (
    BusObservationQuery,
    CanonicalFanInOptimizeRouteUseCase,
    FanInDependencies,
    InMemoryOptimizationPersistence,
    SevenPatternFixtureOptimizeRouteUseCase,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import FixtureFault, fixture_scenario
from routing_api.tests.test_api import FakeClock, _request_payload
from transport_mapping import GitsRoadLinkIdentity, ValidityWindow


_ORIGIN = (127.187456, 37.222345)
_DESTINATION = (127.111159, 37.394761)
_DEPARTURE = datetime.fromisoformat("2026-08-24T07:40:00+09:00")


def _gits_identity(*link_ids: str) -> GitsRoadLinkIdentity:
    return GitsRoadLinkIdentity(
        tuple(sorted(link_ids)),
        "gits-map-test-v1",
        ValidityWindow(_DEPARTURE - timedelta(days=1), _DEPARTURE + timedelta(days=1)),
    )


def _request_context(clock: FakeClock) -> RequestContext:
    return RequestContext(
        "context-correlation",
        "context-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )


def _payload() -> dict:
    value = _request_payload()
    value["origin"]["coordinate"] = {"lon": _ORIGIN[0], "lat": _ORIGIN[1]}
    value["destination"]["coordinate"] = {
        "lon": _DESTINATION[0],
        "lat": _DESTINATION[1],
    }
    value["departureTime"] = _DEPARTURE.isoformat()
    return value


class _RecordingContextPort:
    def __init__(self, base_envelope, *, operations=frozenset({"weather_context", "traffic_context"})):
        self.enabled_operations = operations
        self.base_envelope = base_envelope
        self.weather_queries = []
        self.traffic_queries = []

    def weather(self, query, *, deadline):
        del deadline
        self.weather_queries.append(query)
        payload = (
            WeatherContext(query.coordinate, query.observed_at, 0.0, 0.0),
        )
        return replace(
            self.base_envelope,
            provider="KMA",
            operation="weather_context",
            fingerprint=query.fingerprint(),
            observed_at=query.observed_at,
            status=ProviderStatus.OK,
            schema_version="kma.test.v1",
            normalized_count=1,
            payload=payload,
        )

    def traffic(self, query, *, deadline):
        del deadline
        self.traffic_queries.append(query)
        payload = tuple(
            TrafficLinkContext(link_id, 0, 0.0, query.observed_at)
            for link_id in query.relevant_link_external_ids
        )
        return replace(
            self.base_envelope,
            provider="GITS",
            operation="traffic_context",
            fingerprint=query.fingerprint(),
            observed_at=query.observed_at,
            status=ProviderStatus.OK,
            schema_version="gits.test.v1",
            normalized_count=len(payload),
            payload=payload,
        )


def _fixture_leg_and_envelope(dependencies):
    request = TransitSearchRequest(
        Coordinate(*_ORIGIN), Coordinate(*_DESTINATION), _DEPARTURE
    )
    envelope = dependencies.providers.transit(
        request, deadline=Deadline.after_ms(1_000)
    )
    return envelope.payload[0].legs[0], envelope


def test_context_port_is_default_none_and_rejects_unbounded_operations() -> None:
    base = fixture_fan_in_dependencies(fixture_scenario("R1"))
    assert base.context is None
    fake = SimpleNamespace(enabled_operations=frozenset({"weather_context", "unknown"}))
    with pytest.raises(ValueError, match="bounded subset"):
        replace(base, context=fake)


def test_high_mapped_bus_optional_group_preserves_zero_and_family_isolation() -> None:
    clock = FakeClock(wall=_DEPARTURE)
    dependencies = fixture_fan_in_dependencies(fixture_scenario("R1"))
    leg, envelope = _fixture_leg_and_envelope(dependencies)
    context_port = _RecordingContextPort(envelope)
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "context-group", clock, dependencies=replace(dependencies, context=context_port)
    )
    coordinate_a = SimpleNamespace(lon=_ORIGIN[0], lat=_ORIGIN[1])
    coordinate_b = SimpleNamespace(lon=_DESTINATION[0], lat=_DESTINATION[1])
    target = SimpleNamespace(
        route_id="mapped-route",
        boarding=SimpleNamespace(external_id="mapped-a", coordinate=coordinate_a),
        alighting=SimpleNamespace(external_id="mapped-b", coordinate=coordinate_b),
        geometry=(coordinate_a, coordinate_b),
        gits_road_link_identity=_gits_identity("link-a", "link-b"),
    )
    group = use_case._fetch_bus_optional_group(
        _request_context(clock),
        dependencies.providers,
        context_port,
        BusObservationQuery("mapped-route", "mapped-a", _DEPARTURE),
        target,
        leg,
        "SEATED",
    )
    assert group.started_units == 4
    assert len(context_port.weather_queries) == len(context_port.traffic_queries) == 1
    assert group.eta_feature_context is not group.seat_risk_feature_context
    assert group.eta_feature_context.weather.temperature_c == 0.0
    assert group.eta_feature_context.weather.precipitation_mm == 0.0
    assert group.eta_feature_context.traffic.speed_kph == 0.0
    assert group.eta_feature_context.traffic.travel_time_seconds == 0.0
    assert group.eta_feature_context.weather.schema_version == WEATHER_CONTEXT_SCHEMA_VERSION
    assert group.eta_feature_context.traffic.schema_version == TRAFFIC_CONTEXT_SCHEMA_VERSION

    general = use_case._fetch_bus_optional_group(
        _request_context(clock),
        dependencies.providers,
        context_port,
        BusObservationQuery("mapped-route", "mapped-a", _DEPARTURE),
        target,
        leg,
        "GENERAL",
    )
    assert general.eta_feature_context is not None
    assert general.seat_risk_feature_context is None


def test_traffic_aggregate_excludes_future_rows_and_uses_oldest_as_of() -> None:
    now = _DEPARTURE
    envelope = SimpleNamespace(
        status=ProviderStatus.OK,
        payload=(
            TrafficLinkContext("a", 0, 0.0, now - timedelta(seconds=20)),
            TrafficLinkContext("b", 20, 40.0, now - timedelta(seconds=10)),
            TrafficLinkContext("future", 100, 1.0, now + timedelta(seconds=1)),
        ),
    )
    value = CanonicalFanInOptimizeRouteUseCase._traffic_feature(envelope, now)
    assert value.observed_at == now - timedelta(seconds=20)
    assert value.speed_kph == 10.0
    assert value.travel_time_seconds == 40.0

    all_future = SimpleNamespace(
        status=ProviderStatus.OK,
        payload=(TrafficLinkContext("future", 0, 0.0, now + timedelta(seconds=1)),),
    )
    future_value = CanonicalFanInOptimizeRouteUseCase._traffic_feature(
        all_future, now
    )
    assert future_value is not None
    resolved = EtaFeatureContext(traffic=future_value).as_of(now)
    assert resolved.traffic is None
    assert "TRAFFIC_CONTEXT_FUTURE_EXCLUDED" in resolved.missing_flags


def test_context_operations_do_not_start_for_low_mapping_or_exhausted_cap() -> None:
    clock = FakeClock(wall=_DEPARTURE)
    low = fixture_fan_in_dependencies(
        replace(fixture_scenario("R1"), fault=FixtureFault.MAPPING_LOW)
    )
    _, envelope = _fixture_leg_and_envelope(low)
    port = _RecordingContextPort(envelope, operations=frozenset({"weather_context"}))
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        replace(fixture_scenario("R1"), fault=FixtureFault.MAPPING_LOW),
        clock,
        dependencies=replace(low, context=port),
    )
    result = use_case.execute(OptimizeCommand(_payload()), _request_context(clock))
    assert result.response["routes"]
    assert port.weather_queries == []

    high = fixture_fan_in_dependencies(fixture_scenario("R1"))
    _, high_envelope = _fixture_leg_and_envelope(high)
    blocked_port = _RecordingContextPort(
        high_envelope, operations=frozenset({"weather_context"})
    )
    blocked = SevenPatternFixtureOptimizeRouteUseCase(
        fixture_scenario("R1"),
        clock,
        dependencies=replace(high, context=blocked_port),
        provider_operation_cap=2,
    )
    with pytest.raises(RoutingUnavailableError):
        blocked.execute(OptimizeCommand(_payload()), _request_context(clock))
    assert blocked_port.weather_queries == []


def test_context_query_construction_failure_is_typed_missing_not_500() -> None:
    clock = FakeClock(wall=_DEPARTURE)
    dependencies = fixture_fan_in_dependencies(fixture_scenario("R1"))
    leg, envelope = _fixture_leg_and_envelope(dependencies)
    port = _RecordingContextPort(envelope)
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "context-missing", clock, dependencies=replace(dependencies, context=port)
    )
    target = SimpleNamespace(
        route_id="mapped-route",
        boarding=SimpleNamespace(external_id="mapped-a", coordinate=None),
        alighting=SimpleNamespace(external_id="mapped-b", coordinate=None),
        geometry=(),
        gits_road_link_identity=_gits_identity("link-a"),
    )
    group = use_case._fetch_bus_optional_group(
        _request_context(clock),
        dependencies.providers,
        port,
        BusObservationQuery("mapped-route", "mapped-a", _DEPARTURE),
        target,
        replace(leg, geometry=()),
        "SEATED",
    )
    assert group.started_units == 2
    assert group.weather is None and group.traffic is None
    assert group.eta_feature_context is None
    assert group.required_operations == frozenset(
        {"weather_context", "traffic_context"}
    )
    assert group.context_complete is False


def test_context_group_deadline_gate_is_zero_start_and_fault_is_fail_soft() -> None:
    clock = FakeClock(wall=_DEPARTURE)
    dependencies = fixture_fan_in_dependencies(fixture_scenario("R1"))
    leg, envelope = _fixture_leg_and_envelope(dependencies)
    coordinate_a = SimpleNamespace(lon=_ORIGIN[0], lat=_ORIGIN[1])
    coordinate_b = SimpleNamespace(lon=_DESTINATION[0], lat=_DESTINATION[1])
    target = SimpleNamespace(
        route_id="mapped-route",
        boarding=SimpleNamespace(external_id="mapped-a", coordinate=coordinate_a),
        alighting=SimpleNamespace(external_id="mapped-b", coordinate=coordinate_b),
        geometry=(coordinate_a, coordinate_b),
        gits_road_link_identity=None,
    )
    port = _RecordingContextPort(
        envelope, operations=frozenset({"weather_context"})
    )
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "context-gate", clock, dependencies=replace(dependencies, context=port)
    )
    short = RequestContext(
        "short-correlation",
        "short-idempotency",
        clock.now() + timedelta(seconds=1),
        clock.now() + timedelta(seconds=1),
        True,
        threading.Event(),
    )
    gated = use_case._fetch_bus_optional_group(
        short,
        dependencies.providers,
        port,
        BusObservationQuery("mapped-route", "mapped-a", _DEPARTURE),
        target,
        leg,
        "SEATED",
    )
    assert gated.started_units == 0
    assert port.weather_queries == []
    assert gated.context_complete is False

    class FaultingPort(_RecordingContextPort):
        def weather(self, query, *, deadline):
            self.weather_queries.append(query)
            raise TimeoutError("optional KMA timeout")

    faulting = FaultingPort(
        envelope, operations=frozenset({"weather_context"})
    )
    failed = use_case._fetch_bus_optional_group(
        _request_context(clock),
        dependencies.providers,
        faulting,
        BusObservationQuery("mapped-route", "mapped-a", _DEPARTURE),
        target,
        leg,
        "SEATED",
    )
    assert failed.started_units == 3
    assert failed.arrivals is not None and failed.locations is not None
    assert failed.weather is None and failed.context_complete is False


def test_high_mapping_context_evidence_is_leg_local_and_persisted() -> None:
    clock = FakeClock(wall=_DEPARTURE)
    dependencies = fixture_fan_in_dependencies(fixture_scenario("R1"))
    _, envelope = _fixture_leg_and_envelope(dependencies)
    port = _RecordingContextPort(
        envelope, operations=frozenset({"weather_context"})
    )
    persistence = InMemoryOptimizationPersistence()
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        fixture_scenario("R1"),
        clock,
        dependencies=replace(
            dependencies, context=port, persistence=persistence
        ),
        persistence=persistence,
    )
    response = use_case.execute(
        OptimizeCommand(_payload()), _request_context(clock)
    ).response
    assert port.weather_queries
    assert any(
        item["provider"] == "KMA" and item["operation"] == "weather_context"
        for item in response["providerStatus"]
    )
    bus_legs = [
        leg
        for route in response["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    ]
    assert bus_legs
    assert all(
        any(
            item["provider"] == "FIXTURE::KMA/weather_context"
            for item in leg["provenance"]
        )
        for leg in bus_legs
    )
    assert persistence.values
    persisted = persistence.values[-1]
    assert any(
        item["provider"] == "KMA" and item["operation"] == "weather_context"
        for item in persisted.run.provider_summary["envelopes"]
    )


def test_unknown_service_type_starts_zero_bus_optional_or_model_operations() -> None:
    clock = FakeClock(wall=_DEPARTURE)
    base = fixture_fan_in_dependencies(fixture_scenario("R1"))
    _, envelope = _fixture_leg_and_envelope(base)
    port = _RecordingContextPort(
        envelope,
        operations=frozenset({"weather_context", "traffic_context"}),
    )

    class CountingProviders:
        def __init__(self, delegate):
            self.delegate = delegate
            self.arrival_calls = 0
            self.location_calls = 0

        def __getattr__(self, name):
            return getattr(self.delegate, name)

        def arrivals(self, query, *, deadline):
            self.arrival_calls += 1
            return self.delegate.arrivals(query, deadline=deadline)

        def locations(self, query, *, deadline):
            self.location_calls += 1
            return self.delegate.locations(query, deadline=deadline)

    class UnknownServiceMapping:
        def __init__(self, delegate):
            self.delegate = delegate
            self.high_results = 0

        def __call__(self, evidence, evaluated_at):
            mapping, target = self.delegate(evidence, evaluated_at)
            assert mapping.allows_bus_intelligence is True
            self.high_results += 1
            return mapping, replace(target, route_type="UNKNOWN")

    class CountingPredictor:
        def __init__(self):
            self.calls = 0

        def predict(self, value):
            del value
            self.calls += 1
            return None

    providers = CountingProviders(base.providers)
    mapping = UnknownServiceMapping(base.mapping)
    eta = CountingPredictor()
    seat = CountingPredictor()
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        fixture_scenario("R1"),
        clock,
        dependencies=replace(
            base,
            providers=providers,
            mapping=mapping,
            eta_predictor=eta,
            seat_predictor=seat,
            context=port,
        ),
    )
    response = use_case.execute(
        OptimizeCommand(_payload()), _request_context(clock)
    ).response

    assert mapping.high_results > 0
    assert providers.arrival_calls == providers.location_calls == 0
    assert port.weather_queries == port.traffic_queries == []
    assert eta.calls == seat.calls == 0
    assert response["status"] == "PARTIAL"
    assert all(
        leg["busIntelligence"] is None
        for route in response["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    )
    assert all(
        item["status"] == "DISABLED"
        for item in response["providerStatus"]
        if item["provider"] in {"GBIS_V2", "KMA", "GITS"}
    )
