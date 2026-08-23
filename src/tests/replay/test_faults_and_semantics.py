from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from provider_core import ProviderStatus
from provider_core.adapters import FixtureScenario
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
    TransferRequirement,
)
from routing_domain.replay_fixtures import build_r1_r4_scenarios
from routing_domain.pareto import exactly_dominates

from replay_support import (
    bus_intelligence,
    invoke_integrated_private_api,
    map_canonical_bus_leg,
    run_provider,
)


SCENARIO = build_r1_r4_scenarios()[0]
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("fixture", "status", "message_code", "scenario_id", "empty_result"),
    (
        (FixtureScenario.EMPTY, ProviderStatus.OK, None, "PROVIDER_EMPTY", True),
        (FixtureScenario.TIMEOUT, ProviderStatus.TIMEOUT, None, "PROVIDER_TIMEOUT", False),
        (
            FixtureScenario.RATE_LIMITED,
            ProviderStatus.RATE_LIMITED,
            "RATE_LIMITED",
            "PROVIDER_RATE_LIMITED",
            False,
        ),
        (
            FixtureScenario.SCHEMA_DRIFT,
            ProviderStatus.BAD_RESPONSE,
            "PROVIDER_BAD_RESPONSE",
            "PROVIDER_SCHEMA_DRIFT",
            False,
        ),
    ),
)
def test_required_provider_faults_remain_distinct_then_fail_closed_at_private_api(
    fixture: FixtureScenario,
    status: ProviderStatus,
    message_code: str | None,
    scenario_id: str,
    empty_result: bool,
) -> None:
    envelope = run_provider(SCENARIO, fixture)
    assert envelope.status is status
    assert (envelope.payload == ()) if empty_result else (envelope.payload is None)
    assert envelope.message_code == message_code

    api = invoke_integrated_private_api(SCENARIO, scenario_id)
    assert api.status_code == 503
    assert api.body["code"] == "TRANSIT_PROVIDER_UNAVAILABLE"
    assert api.body["retryable"] is True


def test_low_mapping_blocks_bus_intelligence_without_predictor_calls() -> None:
    envelope = run_provider(SCENARIO)
    mapping = map_canonical_bus_leg(envelope, target_direction="OPPOSITE TERMINAL")
    assert mapping.grade.value == "LOW"
    assert mapping.allows_bus_intelligence is False

    intelligence, predictor = bus_intelligence(
        mapping,
        user_arrival_at=SCENARIO.departure_at,
    )
    assert intelligence.enrichment_applied is False
    assert intelligence.expected_wait_seconds is None
    assert intelligence.p90_wait_seconds is None
    assert intelligence.warnings == ("BUS_MAPPING_LOW_CONFIDENCE",)
    assert predictor.inputs == []

    api = invoke_integrated_private_api(SCENARIO, "MAPPING_LOW")
    assert api.status_code == 200
    assert api.body["status"] == "PARTIAL"
    assert api.body["computation"]["mappingVersion"] is None
    assert "BUS_MAPPING_LOW_CONFIDENCE" in api.body["warningCodes"]
    assert all(
        leg["busIntelligence"] is None
        for route in api.body["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    )


def test_model_unavailable_stays_null_and_future_target_remains_unobserved() -> None:
    envelope = run_provider(SCENARIO)
    mapping = map_canonical_bus_leg(envelope)
    intelligence, predictor = bus_intelligence(
        mapping,
        user_arrival_at=SCENARIO.departure_at,
        seat_values={"fixture-vehicle-1": None, "fixture-vehicle-2": None},
    )
    assert intelligence.enrichment_applied is False
    assert intelligence.expected_wait_seconds is None
    assert intelligence.p90_wait_seconds is None
    assert intelligence.coverage == "PARTIAL"
    assert "BUS_DATA_UNAVAILABLE" in intelligence.warnings
    assert predictor.inputs
    assert all(not hasattr(value, "future_target_remaining_seats") for value in predictor.inputs)
    assert all(vehicle.future_target_observed is False for vehicle in intelligence.candidate_vehicles)
    assert all(vehicle.future_target_remaining_seats is None for vehicle in intelligence.candidate_vehicles)

@pytest.mark.parametrize("scenario_id", ("ETA_UNAVAILABLE", "SEAT_UNAVAILABLE"))
def test_separate_eta_or_seat_unavailable_projects_null_bus_and_partial(
    scenario_id: str,
) -> None:
    api = invoke_integrated_private_api(SCENARIO, scenario_id)
    assert api.status_code == 200
    assert api.body["status"] == "PARTIAL"
    assert api.body["modelVersions"] == []
    assert "BUS_DATA_UNAVAILABLE" in api.body["warningCodes"]
    assert all(
        leg["busIntelligence"] is None
        for route in api.body["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    )


def _cost(p50: int, p90: int, fare_upper: int = 0) -> LegCost:
    return LegCost(
        wait=TimeEstimate(0, 0),
        travel=TimeEstimate(p50, p90),
        fare=MoneyRange(fare_upper, fare_upper, fare_upper),
        reliability_score=0.95,
    )


def test_bus_wait_causes_a_real_optimizer_ranking_reversal() -> None:
    envelope = run_provider(SCENARIO)
    mapping = map_canonical_bus_leg(envelope)
    intelligence, _ = bus_intelligence(mapping, user_arrival_at=SCENARIO.departure_at)
    assert intelligence.expected_wait_seconds == 909
    assert intelligence.p90_wait_seconds == 960

    bus = CandidateSeed(
        "bus",
        "TRANSIT_ONLY",
        (LegSpec("bus-leg", "BUS", "origin", "destination", "bus-cost", topology_ref=mapping.route_id),),
        0,
        600,
        0,
    )
    alternative = CandidateSeed(
        "alternative",
        "TAXI_ONLY",
        (LegSpec("taxi-leg", "TAXI", "origin", "destination", "taxi-cost"),),
        0,
        1_000,
        5_000,
    )
    evaluator = StaticLegEvaluator({"bus-cost": _cost(600, 700), "taxi-cost": _cost(1_000, 1_100, 5_000)})
    constraints = RouteConstraints(10_000, True, 1_000, 2, 2, frozenset({"BUS", "TAXI"}))

    raw = RouteOptimizer(evaluator).optimize((bus, alternative), SCENARIO.departure_at, constraints)
    enriched_bus = replace(
        bus,
        legs=(
            replace(
                bus.legs[0],
                bus_wait=BusWaitContribution(
                    intelligence.expected_wait_seconds,
                    intelligence.p90_wait_seconds,
                ),
            ),
        ),
    )
    enriched = RouteOptimizer(evaluator).optimize(
        (enriched_bus, alternative), SCENARIO.departure_at, constraints
    )

    assert raw.recommendations.fastest == bus.route_id
    assert enriched.recommendations.fastest == alternative.route_id
    enriched_bus_route = next(route for route in enriched.routes if route.route_id == bus.route_id)
    assert enriched_bus_route.total_duration.p50_seconds == 1_509


def test_transfer_p90_infeasibility_blocks_and_low_margin_warns() -> None:
    departure = SCENARIO.departure_at
    evaluator = StaticLegEvaluator({"walk": _cost(50, 60), "bus": _cost(300, 400)})
    constraints = RouteConstraints(0, True, 900, 2, 0, frozenset({"WALK", "BUS"}))

    def seed(scheduled_offset: int) -> CandidateSeed:
        return CandidateSeed(
            f"transfer-{scheduled_offset}",
            "TRANSIT_ONLY",
            (
                LegSpec("walk", "WALK", "origin", "platform", "walk"),
                LegSpec(
                    "bus",
                    "BUS",
                    "platform",
                    "destination",
                    "bus",
                    scheduled_departure_at=departure + timedelta(seconds=scheduled_offset),
                    transfer_requirement=TransferRequirement(70, 80),
                    topology_ref="canonical-transfer-route",
                ),
            ),
            1,
            500,
            0,
        )

    infeasible = RouteOptimizer(evaluator).optimize((seed(100),), departure, constraints)
    assert not infeasible.routes
    assert any(item.reason == "TRANSFER_INFEASIBLE" for item in infeasible.rejected)

    low_margin = RouteOptimizer(evaluator).optimize((seed(200),), departure, constraints)
    assert low_margin.routes
    assert "TRANSFER_MARGIN_LOW" in low_margin.routes[0].warning_codes
    assert low_margin.routes[0].total_duration.p90_seconds >= low_margin.routes[0].total_duration.p50_seconds


def test_strict_budget_uses_sum_of_all_taxi_leg_upper_ranges_even_when_flag_is_false() -> None:
    seed = CandidateSeed(
        "two-taxi",
        "TAXI_TRANSIT_TAXI",
        (
            LegSpec("taxi-1", "TAXI", "origin", "stop", "taxi-1"),
            LegSpec("bus", "BUS", "stop", "station", "bus", topology_ref="canonical-bus"),
            LegSpec("taxi-2", "TAXI", "station", "destination", "taxi-2"),
        ),
        1,
        1_500,
        9_000,
    )
    evaluator = StaticLegEvaluator(
        {
            "taxi-1": _cost(300, 400, 6_000),
            "bus": _cost(600, 800),
            "taxi-2": _cost(300, 400, 6_000),
        }
    )
    constraints = RouteConstraints(
        10_000,
        False,
        900,
        3,
        2,
        frozenset({"TAXI", "BUS"}),
    )
    result = RouteOptimizer(evaluator).optimize((seed,), SCENARIO.departure_at, constraints)
    assert not result.routes
    assert any(item.reason == "STRICT_TAXI_BUDGET" for item in result.rejected)


def test_time_dependent_travel_and_fare_are_recomputed_at_actual_post_wait_start() -> None:
    departure = SCENARIO.departure_at

    class RecordingTimeDependentEvaluator:
        def __init__(self) -> None:
            self.calls = []

        def evaluate(self, leg: LegSpec, entry_at: object) -> LegCost:
            self.calls.append(entry_at)
            if entry_at < departure + timedelta(seconds=600):
                return LegCost(
                    TimeEstimate(600, 600),
                    TimeEstimate(100, 100),
                    MoneyRange(1_000, 1_000, 1_000),
                    0.99,
                )
            return LegCost(
                TimeEstimate(0, 0),
                TimeEstimate(2_000, 2_200),
                MoneyRange(7_000, 6_000, 8_000),
                0.70,
                ("TAXI_FARE_MAY_VARY",),
            )

    seed = CandidateSeed(
        "time-dependent-taxi",
        "TAXI_ONLY",
        (LegSpec("taxi", "TAXI", "origin", "destination", "taxi"),),
        0,
        1_000,
        8_000,
    )
    evaluator = RecordingTimeDependentEvaluator()
    result = RouteOptimizer(evaluator).optimize(
        (seed,),
        departure,
        RouteConstraints(10_000, True, 0, 0, 1, frozenset({"TAXI"})),
    )

    assert result.routes
    route = result.routes[0]
    assert departure in evaluator.calls
    assert departure + timedelta(seconds=600) in evaluator.calls
    assert route.total_duration.p50_seconds == 2_600
    assert route.total_duration.p90_seconds == 2_800
    assert route.taxi_cost.upper_krw == 8_000
    assert route.reliability_score == pytest.approx(0.70)
    assert "TAXI_FARE_MAY_VARY" in route.warning_codes


def test_same_endpoints_on_distinct_canonical_lines_are_not_deduplicated() -> None:
    left = CandidateSeed(
        "line-a",
        "TRANSIT_ONLY",
        (LegSpec("bus-a", "BUS", "origin", "destination", "same", topology_ref="line-a"),),
        0,
        600,
        0,
    )
    right = CandidateSeed(
        "line-b",
        "TRANSIT_ONLY",
        (LegSpec("bus-b", "BUS", "origin", "destination", "same", topology_ref="line-b"),),
        0,
        600,
        0,
    )
    result = RouteOptimizer(StaticLegEvaluator({"same": _cost(600, 700)})).optimize(
        (left, right),
        SCENARIO.departure_at,
        RouteConstraints(0, True, 0, 0, 0, frozenset({"BUS"})),
    )
    assert left.route_id != right.route_id
    assert result.counts.feasible == 2
    assert result.counts.pareto == 2


def test_epsilon_dominance_cycle_cannot_erase_a_nonempty_feasible_set() -> None:
    # Valid P90>=P50 cycle under the default epsilon (30s, 60s, 100 KRW):
    # A epsilon-dominates B, B dominates C, and C dominates A.
    seeds = (
        CandidateSeed(
            "cycle-a",
            "TAXI_ONLY",
            (LegSpec("a", "TAXI", "a-origin", "a-destination", "a"),),
            0,
            0,
            200,
        ),
        CandidateSeed(
            "cycle-b",
            "TAXI_ONLY",
            (LegSpec("b", "TAXI", "b-origin", "b-destination", "b"),),
            0,
            60,
            100,
        ),
        CandidateSeed(
            "cycle-c",
            "TRANSIT_ONLY",
            (LegSpec("c", "BUS", "c-origin", "c-destination", "c", topology_ref="cycle-c"),),
            0,
            30,
            0,
        ),
    )
    evaluator = StaticLegEvaluator(
        {
            "a": _cost(0, 90, 200),
            "b": _cost(60, 60, 100),
            "c": _cost(30, 150, 0),
        }
    )
    constraints = RouteConstraints(1_000, True, 0, 0, 1, frozenset({"TAXI", "BUS"}))
    optimizer = RouteOptimizer(evaluator)
    forward = optimizer.optimize(seeds, SCENARIO.departure_at, constraints)
    reverse = optimizer.optimize(tuple(reversed(seeds)), SCENARIO.departure_at, constraints)

    assert forward == reverse
    assert forward.counts.feasible == 3
    assert forward.counts.pareto >= 1
    assert forward.routes
    returned = {route.route_id for route in forward.routes}
    assert forward.recommendations.fastest in returned
    assert not any(
        exactly_dominates(left, right)
        for left in forward.routes
        for right in forward.routes
        if left is not right
    )


def test_canonical_example_has_no_dangling_ids_or_unregistered_codes() -> None:
    example = json.loads(
        (ROOT / "src/contracts/openapi/examples/routing-optimize-response.json").read_text(encoding="utf-8")
    )
    registry = yaml.safe_load(
        (ROOT / "src/contracts/codes/reason-warning-error-codes.yaml").read_text(encoding="utf-8")
    )
    route_ids = {route["routeId"] for route in example["routes"]}
    dangling_recommendations = {
        value for value in example["recommendations"].values() if value is not None and value not in route_ids
    }
    dangling_pareto = set(example["paretoRouteIds"]) - route_ids
    registered_codes = set(registry["reasonCodes"]) | set(registry["warningCodes"]) | set(registry["errorCodes"])
    unregistered_messages = {
        item["messageCode"]
        for item in example["providerStatus"]
        if item["messageCode"] is not None and item["messageCode"] not in registered_codes
    }

    assert example["routes"]
    assert dangling_recommendations == set()
    assert dangling_pareto == set()
    assert unregistered_messages == set()
    assert "NO_SEAT_DATA_FOR_ROUTE" not in json.dumps(example)
