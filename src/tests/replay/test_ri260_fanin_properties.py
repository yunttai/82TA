from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Mapping

import pytest

from bus_intelligence_core import (
    BusIntelligenceEngine,
    BusIntelligenceRequest,
    EtaPrediction,
    VehicleObservation,
)
from provider_core import (
    ProviderAdapterSuite,
    ProviderFixtureScenario,
    ProviderStatus,
    QualityFlag,
)
from routing_api.contract import CanonicalContractValidator
from routing_domain import (
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
from transport_mapping import MappingGrade
from transport_mapping.models import ReviewDecision, ReviewDisposition

from replay_support import (
    FixtureSeatRiskPredictor,
    NoEtaFallback,
    build_integrated_application,
    bus_intelligence,
    invoke_application,
    map_canonical_bus_leg,
    request_payload,
    run_provider,
)


SCENARIOS = build_r1_r4_scenarios()
PATTERNS = {
    "TRANSIT_ONLY",
    "TAXI_TRANSIT",
    "TRANSIT_TAXI",
    "TAXI_TRANSIT_TAXI",
    "TAXI_ONLY",
    "UPSTREAM_STOP_TAXI_TRANSIT",
    "TRANSIT_TAXI_BRIDGE_TRANSIT",
}
EXACT_BUNDLES = {
    "R1": ((127.187456, 37.222345), (127.111159, 37.394761), "2026-08-24T07:40:00+09:00"),
    "R2": ((127.111159, 37.394761), (127.187456, 37.222345), "2026-08-24T18:10:00+09:00"),
    "R3": ((127.051, 37.289), (127.111159, 37.394761), "2026-08-24T08:05:00+09:00"),
    "R4": ((127.111159, 37.394761), (127.051, 37.289), "2026-08-24T19:20:00+09:00"),
}


def _coordinate(value: Mapping[str, object]) -> tuple[float, float]:
    return float(value["lon"]), float(value["lat"])


def _forbidden_boundary_keys(value: object) -> set[str]:
    forbidden = {
        "raw",
        "body",
        "apikey",
        "servicekey",
        "authorization",
        "userid",
        "email",
        "phone",
        "platenumber",
        "socialid",
        "savedplacelabel",
    }
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).replace("_", "").lower()
            if normalized in forbidden:
                found.add(str(key))
            found.update(_forbidden_boundary_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_forbidden_boundary_keys(item))
    return found


@pytest.mark.parametrize("scenario", SCENARIOS, ids=("R1", "R2", "R3", "R4"))
def test_exact_r1_r4_request_keeps_only_causally_resolved_api_patterns(
    scenario: object,
) -> None:
    application, clock = build_integrated_application(scenario.replay_id)
    payload = request_payload(scenario)
    expected_origin, expected_destination, expected_departure = EXACT_BUNDLES[scenario.replay_id]
    assert _coordinate(payload["origin"]["coordinate"]) == expected_origin
    assert _coordinate(payload["destination"]["coordinate"]) == expected_destination
    assert payload["departureTime"] == expected_departure

    result = invoke_application(application, clock, scenario, scenario.replay_id, payload=payload)
    assert result.status_code == 200
    body = result.body
    assert CanonicalContractValidator().validate_optimize_response(body) == ()
    assert body["status"] == "PARTIAL"

    trace = application._use_case.trace  # type: ignore[attr-defined]
    assert trace is not None
    assert set(trace.coarse_patterns) == PATTERNS
    # The named fixtures only resolve the corridor transit segment. Coarse
    # generation may consider every policy pattern, but the API must not
    # fabricate unresolved walk/taxi/bridge/upstream provider quotes.
    assert set(trace.exact_patterns) == {"TRANSIT_ONLY"}
    assert trace.exact_plan
    assert len(trace.exact_plan) == len({request_key for request_key, _ in trace.exact_plan})
    exact_kinds = {kind for _, kind in trace.exact_plan}
    assert exact_kinds >= {"WALK", "TAXI", "TRANSIT", "BUS_INTELLIGENCE"}
    # Official Kakao route/stop labels and geometry are useful graph evidence,
    # but the documented shape has no external route ID or direction. Replay
    # must prove that an opaque graph identity never starts canonical mapping.
    assert "MAPPING" not in exact_kinds
    assert trace.provider_call_count == body["computation"]["cache"]["providerCallCount"]
    assert trace.provider_call_count <= 64
    assert body["computation"]["cache"]["exactEnrichmentResolved"] is True
    assert body["computation"]["cache"]["strategyPolicyVersion"] == "strategy-2.0.0"
    assert "COARSE_TAXI_BUDGET" not in trace.rejected_reasons
    assert {
        "TAXI_BRIDGE_CONNECTION_INFEASIBLE",
        "UPSTREAM_ROUTE_DIRECTION_MISMATCH",
    } <= set(trace.rejected_reasons)
    budget = payload["constraints"]["taxiBudget"]["maxAmount"]
    assert all(
        sum(
            leg["fare"]["upper"]
            for leg in route["legs"]
            if leg["mode"] == "TAXI"
        )
        <= budget
        for route in body["routes"]
    )

    returned = {route["routeId"] for route in body["routes"]}
    assert all(
        value is None or value in returned
        for value in body["recommendations"].values()
    )
    assert set(body["paretoRouteIds"]) <= returned
    for route in body["routes"]:
        taxi_upper = sum(
            leg["fare"]["upper"] for leg in route["legs"] if leg["mode"] == "TAXI"
        )
        assert route["taxiCost"]["upper"] == taxi_upper
        assert taxi_upper <= scenario.constraints.taxi_budget_krw
        assert route["totalDuration"]["p90Seconds"] >= route["totalDuration"]["p50Seconds"]
        for previous, current in zip(route["legs"], route["legs"][1:]):
            assert datetime.fromisoformat(current["expectedStartAt"]) >= datetime.fromisoformat(
                previous["expectedEndAt"]
            )

    bus_legs = [
        leg
        for route in body["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    ]
    assert bus_legs
    assert all(leg["busIntelligence"] is None for leg in bus_legs)
    assert body["modelVersions"] == []
    assert "BUS_DATA_UNAVAILABLE" in body["warningCodes"]
    assert _forbidden_boundary_keys(body) == set()


def test_strict_budget_admits_exact_sum_and_rejects_sum_one_won_over_even_when_flag_false() -> None:
    def seed(name: str, middle: str, second_key: str, coarse_upper: int) -> CandidateSeed:
        return CandidateSeed(
            candidate_key=name,
            pattern="TAXI_TRANSIT_TAXI",
            legs=(
                LegSpec(f"{name}-first", "TAXI", "origin", middle, "first"),
                LegSpec(f"{name}-bus", "BUS", middle, f"{middle}-after-bus", "bus", topology_ref="line"),
                LegSpec(f"{name}-second", "TAXI", f"{middle}-after-bus", "destination", second_key),
            ),
            transfer_count=0,
            coarse_p50_seconds=300,
            coarse_taxi_upper_krw=coarse_upper,
        )

    evaluator = StaticLegEvaluator(
        {
            "first": LegCost(TimeEstimate(0, 0), TimeEstimate(60, 90), MoneyRange(4_000, 4_000, 4_000)),
            "bus": LegCost(TimeEstimate(0, 0), TimeEstimate(60, 90), MoneyRange(0, 0, 0)),
            "exact-second": LegCost(TimeEstimate(0, 0), TimeEstimate(60, 90), MoneyRange(6_000, 6_000, 6_000)),
            "over-second": LegCost(TimeEstimate(0, 0), TimeEstimate(60, 90), MoneyRange(6_001, 6_001, 6_001)),
        }
    )
    constraints = RouteConstraints(
        10_000,
        False,
        0,
        0,
        2,
        frozenset({"TAXI", "BUS"}),
    )
    exact = seed("exact", "exact-middle", "exact-second", 10_000)
    over = seed("over", "over-middle", "over-second", 10_001)
    result = RouteOptimizer(evaluator).optimize(
        (exact, over),
        SCENARIOS[0].departure_at,
        constraints,
    )
    assert [route.candidate_key for route in result.routes] == ["exact"]
    assert result.routes[0].taxi_cost.upper_krw == 10_000


@pytest.mark.parametrize("variant", ("MEDIUM", "LOW", "AMBIGUOUS"))
def test_medium_low_and_ambiguous_mapping_cannot_enable_bus_enrichment(variant: str) -> None:
    envelope = run_provider(SCENARIOS[0])
    high = map_canonical_bus_leg(envelope)
    if variant == "LOW":
        mapping = map_canonical_bus_leg(envelope, target_direction="OPPOSITE TERMINAL")
    elif variant == "AMBIGUOUS":
        mapping = replace(
            high,
            grade=MappingGrade.MEDIUM,
            review=ReviewDecision(
                ReviewDisposition.QUEUE,
                ("AMBIGUOUS_TOP_CANDIDATES",),
            ),
        )
    else:
        mapping = replace(high, grade=MappingGrade.MEDIUM)
    assert mapping.allows_bus_intelligence is False
    result, seat = bus_intelligence(mapping, user_arrival_at=SCENARIOS[0].departure_at)
    assert result.enrichment_applied is False
    assert result.expected_wait_seconds is None
    assert result.p90_wait_seconds is None
    assert seat.inputs == []


def test_eta_p50_before_or_equal_to_user_arrival_is_excluded_and_missing_future_stays_null() -> None:
    mapping = map_canonical_bus_leg(run_provider(SCENARIOS[0]))
    arrival = SCENARIOS[0].departure_at
    observations = tuple(
        VehicleObservation(
            vehicle_ref=name,
            route_id=mapping.route_id,
            direction="OUTBOUND",
            boarding_stop_id="canonical-board",
            observed_at=arrival - timedelta(seconds=30),
            official_eta=EtaPrediction(p50, p90, "OFFICIAL"),
            remain_seat_observed=None,
            future_target_remaining_seats=None,
        )
        for name, p50, p90 in (
            ("before", arrival - timedelta(seconds=1), arrival + timedelta(seconds=10)),
            ("equal", arrival, arrival + timedelta(seconds=10)),
            ("after", arrival + timedelta(seconds=1), arrival + timedelta(seconds=20)),
        )
    )
    seat = FixtureSeatRiskPredictor({"before": 0.1, "equal": 0.1, "after": 0.1})
    result = BusIntelligenceEngine(NoEtaFallback(), seat).enrich(
        BusIntelligenceRequest(
            mapping.grade.value,
            mapping.allows_bus_intelligence,
            mapping.score,
            mapping.mapping_version,
            arrival,
            arrival,
            "canonical-target",
            "SEATED",
            observations,
        )
    )
    assert [vehicle.vehicle_ref for vehicle in result.candidate_vehicles] == ["after"]
    assert [getattr(value, "vehicle_ref") for value in seat.inputs] == ["after"]
    assert result.candidate_vehicles[0].future_target_observed is False
    assert result.candidate_vehicles[0].future_target_remaining_seats is None


def test_named_provider_fixture_matrix_is_deterministic_canonical_and_sanitized() -> None:
    suite = ProviderAdapterSuite(object())  # fixture() never touches the injected transport
    adapters = (
        (suite.kakao_transit, ("search_current",)),
        (suite.kakao_walk, ("route",)),
        (suite.kakao_mobility, ("route_current", "many_destinations", "many_origins", "route_future")),
        (suite.gbis, ("arrivals", "locations", "routes", "stations")),
        (suite.kma, ("weather_context",)),
        (suite.gits, ("traffic_context",)),
        (suite.tmap, ("search",)),
        (suite.odsay, ("search",)),
    )
    expected = {
        ProviderFixtureScenario.SUCCESS: ProviderStatus.OK,
        ProviderFixtureScenario.EMPTY: ProviderStatus.OK,
        ProviderFixtureScenario.ERROR: ProviderStatus.UNAVAILABLE,
        ProviderFixtureScenario.RATE_LIMITED: ProviderStatus.RATE_LIMITED,
        ProviderFixtureScenario.SCHEMA_DRIFT: ProviderStatus.BAD_RESPONSE,
    }
    for adapter, operations in adapters:
        for operation in operations:
            for scenario, status in expected.items():
                first = adapter.fixture(operation, scenario)
                second = adapter.fixture(operation, scenario)
                assert first == second
                assert first.status is status
                assert QualityFlag.SANITIZED_FIXTURE in first.quality_flags
                if scenario is ProviderFixtureScenario.SUCCESS:
                    assert first.payload
                    assert all(not isinstance(item, Mapping) for item in first.payload)
                elif scenario is ProviderFixtureScenario.EMPTY:
                    assert first.payload == ()
                    assert QualityFlag.EMPTY_RESULT in first.quality_flags
                else:
                    assert first.payload is None


def test_private_api_idempotency_identity_rejection_and_boundary_shape() -> None:
    scenario = SCENARIOS[0]
    application, clock = build_integrated_application("R1")
    payload = request_payload(scenario)
    first = invoke_application(
        application,
        clock,
        scenario,
        "R1",
        payload=payload,
        idempotency_key="ri280-idempotency-r1",
    )
    first_trace = application._use_case.trace  # type: ignore[attr-defined]
    replay = invoke_application(
        application,
        clock,
        scenario,
        "R1",
        payload=payload,
        idempotency_key="ri280-idempotency-r1",
    )
    assert first.status_code == replay.status_code == 200
    assert first.body == replay.body
    assert application._use_case.trace is first_trace  # type: ignore[attr-defined]

    changed = request_payload(scenario)
    changed["constraints"]["taxiBudget"]["maxAmount"] = 9_999
    conflict = invoke_application(
        application,
        clock,
        scenario,
        "R1",
        payload=changed,
        idempotency_key="ri280-idempotency-r1",
    )
    assert conflict.status_code == 409
    assert conflict.body["code"] == "IDEMPOTENCY_CONFLICT"

    rejected_application, rejected_clock = build_integrated_application("R1")
    identity_payload = request_payload(scenario)
    identity_payload["userId"] = "forbidden-user-identity"
    rejected = invoke_application(
        rejected_application,
        rejected_clock,
        scenario,
        "R1",
        payload=identity_payload,
        idempotency_key="ri280-identity-reject",
    )
    assert rejected.status_code == 400
    assert rejected.body["code"] == "CONSTRAINT_OUT_OF_RANGE"
    assert rejected_application._use_case.trace is None  # type: ignore[attr-defined]
    assert "forbidden-user-identity" not in str(rejected.body)
    assert _forbidden_boundary_keys(first.body) == set()
