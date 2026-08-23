from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta

from provider_core import Coordinate, TransitSearchRequest
from routing_api.application import OptimizeCommand, RequestContext
from routing_api.fanin_integration import (
    InMemoryOptimizationPersistence,
    SevenPatternFixtureOptimizeRouteUseCase,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.tests.test_fixture_integration import (
    _CausalProviderPorts,
    _causal_response,
)
from routing_domain.replay_fixtures import build_r1_r4_scenarios

from replay_support import FakeClock, invoke_integrated_private_api, request_payload


def _execute_candidate_entry_replay():
    clock = FakeClock()
    scenario = fixture_scenario("R1")
    dependencies = fixture_fan_in_dependencies(scenario)
    providers = _CausalProviderPorts(
        dependencies.providers,
        taxi_upper_krw=2_500,
    )
    persistence = InMemoryOptimizationPersistence()
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario,
        clock,
        dependencies=replace(
            dependencies,
            providers=providers,
            persistence=persistence,
        ),
    )
    payload = request_payload(build_r1_r4_scenarios()[0])
    payload["constraints"]["allowTaxiBridge"] = True  # type: ignore[index]
    context = RequestContext(
        "ri-351-replay-correlation",
        "ri-351-replay-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), context).response
    return response, providers, persistence.values[0], use_case.trace


def _request_fingerprint(
    movement: tuple[str, tuple[float, float], tuple[float, float]],
    departure_at: datetime,
) -> str:
    _, origin, destination = movement
    return TransitSearchRequest(
        Coordinate(*origin),
        Coordinate(*destination),
        departure_at,
        max_itineraries=1,
    ).fingerprint()


def test_candidate_entry_quote_replay_is_deterministic_and_time_scoped() -> None:
    first_response, first_providers, first_record, first_trace = (
        _execute_candidate_entry_replay()
    )
    second_response, second_providers, second_record, second_trace = (
        _execute_candidate_entry_replay()
    )

    assert first_response == second_response
    assert first_record == second_record
    assert replace(
        first_trace,
        model_inference=replace(first_trace.model_inference, elapsed_ms=0),
    ) == replace(
        second_trace,
        model_inference=replace(second_trace.model_inference, elapsed_ms=0),
    )
    for trace in (first_trace, second_trace):
        assert 0 <= trace.model_inference.elapsed_ms <= trace.model_inference.hard_cap_ms
    assert first_trace.provider_call_count <= 64
    assert first_response["computation"]["cache"]["providerCallCount"] == (
        first_trace.provider_call_count
    )

    first_requests = sorted(first_providers.request_departures)
    second_requests = sorted(second_providers.request_departures)
    assert first_requests == second_requests

    by_movement: dict[
        tuple[str, tuple[float, float], tuple[float, float]], set[datetime]
    ] = defaultdict(set)
    for kind, origin, destination, departure_at in first_requests:
        assert departure_at.tzinfo is not None
        by_movement[(kind, origin, destination)].add(departure_at)

    repeated_at_distinct_entries = {
        movement: entries
        for movement, entries in by_movement.items()
        if len(entries) > 1
    }
    assert repeated_at_distinct_entries
    assert {movement[0] for movement in repeated_at_distinct_entries} >= {
        "TRANSIT",
        "WALK",
        "TAXI",
    }
    for movement, entries in repeated_at_distinct_entries.items():
        fingerprints = {
            _request_fingerprint(movement, departure_at)
            for departure_at in entries
        }
        assert len(fingerprints) == len(entries)


def test_candidate_entry_replay_keeps_per_leg_evidence_and_eta_seat_semantics() -> None:
    response, _, record, _ = _execute_candidate_entry_replay()

    assert response["status"] == "PARTIAL"
    assert response["modelVersions"] == [
        {"purpose": "SEAT_RISK", "version": "seat-fixture-0.1.0"}
    ]
    bus_leg = next(
        leg
        for route in response["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS" and leg["busIntelligence"] is not None
    )
    intelligence = bus_leg["busIntelligence"]
    assert intelligence["mapping"]["grade"] == "HIGH"
    assert intelligence["p90WaitSeconds"] >= intelligence["expectedWaitSeconds"]
    assert intelligence["candidateVehicles"]
    for vehicle in intelligence["candidateVehicles"]:
        assert vehicle["eta"]["origin"] == "PROVIDER_ESTIMATE"
        assert vehicle["seatRiskAtBoarding"] is not None
        assert vehicle["seatRiskAtBoarding"]["modelVersion"] == (
            "seat-fixture-0.1.0"
        )

    movement_fingerprints: list[set[str]] = []
    for leg in record.legs:
        values = {
            item["fingerprint"]
            for item in leg.provenance
            if isinstance(item, dict)
            and item.get("fingerprint")
            and item.get("operation") not in {"arrivals", "locations"}
        }
        assert len(values) == 1
        movement_fingerprints.append(values)
    assert len(set().union(*movement_fingerprints)) == len(movement_fingerprints)

    bus_record = next(leg for leg in record.legs if leg.mode == "BUS")
    model_evidence = [
        item
        for item in bus_record.provenance
        if isinstance(item, dict) and item.get("kind") == "MODEL"
    ]
    assert model_evidence == [
        {
            "kind": "MODEL",
            "purpose": "SEAT_RISK",
            "version": "seat-fixture-0.1.0",
            "readiness": "FIXTURE_ONLY",
        }
    ]


def test_bus_wait_changes_final_route_chronology_and_missing_stays_null() -> None:
    early = _causal_response(
        taxi_upper_krw=2_500,
        eta_seconds=120,
        remaining_seats=3,
    )
    late = _causal_response(
        taxi_upper_krw=2_500,
        eta_seconds=600,
        remaining_seats=3,
    )

    def transit_route(response):
        return next(
            route
            for route in response["routes"]
            if route["pattern"] == "TRANSIT_ONLY"
        )

    early_route = transit_route(early)
    late_route = transit_route(late)
    early_bus = next(leg for leg in early_route["legs"] if leg["mode"] == "BUS")
    late_bus = next(leg for leg in late_route["legs"] if leg["mode"] == "BUS")
    early_intelligence = early_bus["busIntelligence"]
    late_intelligence = late_bus["busIntelligence"]

    expected_wait_delta = (
        late_intelligence["expectedWaitSeconds"]
        - early_intelligence["expectedWaitSeconds"]
    )
    p90_wait_delta = (
        late_intelligence["p90WaitSeconds"]
        - early_intelligence["p90WaitSeconds"]
    )
    assert expected_wait_delta > 0
    assert p90_wait_delta > 0
    assert (
        late_route["totalDuration"]["p50Seconds"]
        - early_route["totalDuration"]["p50Seconds"]
    ) == expected_wait_delta
    assert (
        late_route["totalDuration"]["p90Seconds"]
        - early_route["totalDuration"]["p90Seconds"]
    ) == p90_wait_delta
    assert (
        datetime.fromisoformat(late_bus["expectedEndAt"])
        - datetime.fromisoformat(early_bus["expectedEndAt"])
    ).total_seconds() == expected_wait_delta

    scenario = build_r1_r4_scenarios()[0]
    missing = invoke_integrated_private_api(scenario, "R1")
    assert missing.status_code == 200
    assert missing.body["status"] == "PARTIAL"
    assert "BUS_DATA_UNAVAILABLE" in missing.body["warningCodes"]
    assert missing.body["modelVersions"] == []
    assert all(
        leg["busIntelligence"] is None
        for route in missing.body["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    )
