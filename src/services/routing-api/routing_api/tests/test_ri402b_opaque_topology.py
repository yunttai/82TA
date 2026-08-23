"""RI-402B graph-only topology for truthful incomplete Provider descriptors."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import threading

from provider_core.canonical import CanonicalItinerary
from provider_core.named import ProviderAdapterSuite, ProviderFixtureScenario
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from routing_api.application import OptimizeCommand, RequestContext
from routing_api.fanin_integration import (
    CanonicalFanInOptimizeRouteUseCase,
    InMemoryOptimizationPersistence,
    _canonical_itinerary_baseline,
    _canonical_itinerary_identity,
    _canonicalize_returned_itineraries,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.tests.test_api import FakeClock, _request_payload
from routing_domain import TransitLegInput


class _NoNetwork:
    def send(self, request):
        del request
        raise AssertionError("RI-402B uses only the sanitized official-shape fixture")


def _official_kakao_bus_only_envelope():
    suite = ProviderAdapterSuite(_NoNetwork())
    envelope = suite.kakao_transit.fixture(
        "search_current", ProviderFixtureScenario.SUCCESS
    )
    itinerary = envelope.payload[0]
    bus = next(leg for leg in itinerary.legs if leg.mode.value == "BUS")
    bus_only = CanonicalItinerary(
        f"{itinerary.itinerary_id}-bus-only",
        (replace(bus, sequence=0),),
    )
    return replace(envelope, payload=(bus_only,), normalized_count=1)


def test_incomplete_official_topology_is_deterministic_and_deduplicates() -> None:
    envelope = _official_kakao_bus_only_envelope()
    itinerary = envelope.payload[0]
    leg = itinerary.legs[0]
    assert leg.transit.external_route_id is None
    assert leg.transit.direction is None
    assert leg.from_stop.external_id is None
    assert leg.to_stop.external_id is None

    duplicate = replace(itinerary, itinerary_id="opaque-provider-duplicate")
    origin = {"lon": leg.from_stop.coordinate.lon, "lat": leg.from_stop.coordinate.lat}
    destination = {"lon": leg.to_stop.coordinate.lon, "lat": leg.to_stop.coordinate.lat}
    canonical = _canonicalize_returned_itineraries(
        (itinerary, duplicate), origin, destination, max_itineraries=5
    )
    assert len(canonical) == 1

    identity = _canonical_itinerary_identity(itinerary)
    baseline, _, sources, bus_evidence = _canonical_itinerary_baseline(
        itinerary, envelope, reference_namespace=identity
    )
    movement = baseline.legs[0]
    assert isinstance(movement, TransitLegInput)
    assert movement.topology.route_ref.startswith("opaque-itinerary-local:")
    assert movement.topology.direction == "OPAQUE_FORWARD"
    assert movement.mapping_ready is False
    assert movement.bus_intelligence_requested is True
    assert len(sources) == 1
    assert next(iter(sources.values())).routing_topology_ref == movement.topology.fingerprint
    assert bus_evidence[0][0] == movement.topology.fingerprint

    duplicate_baseline, *_ = _canonical_itinerary_baseline(
        duplicate, envelope, reference_namespace=identity
    )
    assert duplicate_baseline.legs[0].topology == movement.topology


def test_complete_provider_topology_is_preserved_exactly() -> None:
    envelope = _official_kakao_bus_only_envelope()
    itinerary = envelope.payload[0]
    bus = itinerary.legs[0]
    complete_bus = replace(
        bus,
        transit=replace(
            bus.transit,
            external_route_id="provider-route-701",
            direction="OUTBOUND",
        ),
    )
    complete = replace(itinerary, legs=(complete_bus,))

    baseline, *_ = _canonical_itinerary_baseline(complete, envelope)
    movement = baseline.legs[0]
    assert isinstance(movement, TransitLegInput)
    assert movement.topology.route_ref == "provider-route-701"
    assert movement.topology.direction == "OUTBOUND"
    assert movement.topology.board_sequence == complete_bus.transit.boarding_sequence
    assert movement.topology.alight_sequence == complete_bus.transit.alighting_sequence


def test_opaque_bus_reuses_baseline_once_and_never_projects_identity_or_mapping() -> None:
    envelope = _official_kakao_bus_only_envelope()
    bus = envelope.payload[0].legs[0]
    base = fixture_fan_in_dependencies(fixture_scenario("R1"))

    class OfficialKakaoPorts:
        def __init__(self):
            self.transit_calls = 0
            self._attempts = ()

        @property
        def transit_call_cap(self):
            return 1

        @property
        def last_transit_attempt_count(self):
            return len(self._attempts)

        @property
        def last_transit_envelopes(self):
            return self._attempts

        def transit(self, request: TransitSearchRequest, *, deadline: Deadline):
            del request, deadline
            self.transit_calls += 1
            self._attempts = (envelope,)
            return envelope

        def walk(self, request, *, deadline):
            return base.providers.walk(request, deadline=deadline)

        def taxi(self, request, *, deadline):
            return base.providers.taxi(request, deadline=deadline)

        def arrivals(self, query, *, deadline):
            raise AssertionError("opaque topology must not start GBIS arrivals")

        def locations(self, query, *, deadline):
            raise AssertionError("opaque topology must not start GBIS locations")

    class MappingMustNotStart:
        calls = 0

        def __call__(self, evidence, evaluated_at):
            del evidence, evaluated_at
            self.calls += 1
            raise AssertionError("opaque topology must not enter canonical mapping")

    ports = OfficialKakaoPorts()
    mapping = MappingMustNotStart()
    dependencies = replace(
        base,
        providers=ports,
        mapping=mapping,
        persistence=InMemoryOptimizationPersistence(),
        fixture_only=True,
    )
    departure = datetime(2026, 8, 23, 22, 40, tzinfo=timezone.utc)
    clock = FakeClock(wall=departure)
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "ri402b", clock, dependencies=dependencies
    )
    payload = _request_payload()
    payload["origin"]["coordinate"] = {
        "lon": bus.from_stop.coordinate.lon,
        "lat": bus.from_stop.coordinate.lat,
    }
    payload["destination"]["coordinate"] = {
        "lon": bus.to_stop.coordinate.lon,
        "lat": bus.to_stop.coordinate.lat,
    }
    payload["departureTime"] = "2026-08-24T07:40:00+09:00"
    payload["constraints"]["taxiBudget"]["maxAmount"] = 0
    payload["constraints"]["maxWalkSeconds"] = 0
    payload["constraints"]["maxTaxiLegs"] = 0
    payload["constraints"]["allowedModes"] = ["BUS"]
    context = RequestContext(
        "ri402b-correlation",
        "ri402b-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )

    response = use_case.execute(OptimizeCommand(payload), context).response

    assert ports.transit_calls == 1
    assert mapping.calls == 0
    assert response["status"] == "PARTIAL"
    assert response["routes"]
    assert response["computation"]["candidateCounts"]["fullyEvaluated"] > 0
    assert response["computation"]["cache"]["providerCallCount"] == 1
    assert response["modelVersions"] == []
    assert response["computation"]["mappingVersion"] is None
    assert "BUS_MAPPING_LOW_CONFIDENCE" in response["warningCodes"]
    assert "opaque-itinerary-local" not in json.dumps(response)

    bus_legs = [
        leg
        for route in response["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    ]
    assert bus_legs
    assert all(leg["transit"]["externalRouteId"] is None for leg in bus_legs)
    assert all(leg["transit"]["direction"] is None for leg in bus_legs)
    assert all(leg["from"]["providerStopId"] is None for leg in bus_legs)
    assert all(leg["to"]["providerStopId"] is None for leg in bus_legs)
    assert all(leg["from"]["canonicalStopId"] is None for leg in bus_legs)
    assert all(leg["to"]["canonicalStopId"] is None for leg in bus_legs)
    assert all(leg["busIntelligence"] is None for leg in bus_legs)
    assert all(
        not any(item["provider"].startswith("TRANSPORT_MAPPING/") for item in leg["provenance"])
        for leg in bus_legs
    )
