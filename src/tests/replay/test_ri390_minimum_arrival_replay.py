from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import permutations, product

from routing_domain.evaluators import StaticLegEvaluator
from routing_domain.models import (
    BusWaitContribution,
    CandidateSeed,
    LegCost,
    LegSpec,
    MoneyRange,
    RouteConstraints,
    TimeEstimate,
    TransferRequirement,
)
from routing_domain.optimizer import RouteOptimizer
from routing_domain.policy import EpsilonPolicy
from routing_domain.strategy_generation import (
    AccessHub,
    BoundedStrategyGenerator,
    CanonicalTransitTopology,
    StrategyGenerationInput,
    TaxiQuote,
    TransitBaseline,
    TransitLegInput,
    WalkQuote,
)


KST = timezone(timedelta(hours=9))
DEPARTURE = datetime(2026, 8, 24, 7, 0, tzinfo=KST)
BUDGET = 10_000
ZERO = MoneyRange.zero()
ZERO_EPSILON = EpsilonPolicy(0, 0, 0, 0, 0.0)


@dataclass(frozen=True)
class OracleLeg:
    wait: tuple[int, int]
    travel: tuple[int, int]
    taxi_upper: int = 0
    connector: tuple[int, int] = (0, 0)
    connector_walk: int = 0
    bus_wait: tuple[int, int] | None = None
    schedule: int | None = None
    next_service_wait: tuple[int, int] | None = None
    incident_delay: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class OracleCandidate:
    candidate_key: str
    legs: tuple[OracleLeg, ...]


def _oracle_evaluate(candidate: OracleCandidate, budget: int) -> tuple[int, int, int] | None:
    """Independent integer chronology; no production evaluator/ranking reuse."""

    current = [0, 0]
    taxi_upper = 0
    for leg in candidate.legs:
        taxi_upper += leg.taxi_upper
        for quantile in (0, 1):
            ready = current[quantile] + leg.connector[quantile]
            if leg.bus_wait is not None:
                start = ready + leg.bus_wait[quantile]
            elif leg.schedule is not None:
                if ready <= leg.schedule:
                    start = leg.schedule
                elif leg.next_service_wait is not None:
                    start = ready + leg.next_service_wait[quantile]
                else:
                    return None
            else:
                start = ready + leg.wait[quantile]
            current[quantile] = (
                start + leg.travel[quantile] + leg.incident_delay[quantile]
            )
        if current[1] < current[0]:
            return None
    if taxi_upper > budget:
        return None
    return current[0], current[1], taxi_upper


def _money(upper: int) -> MoneyRange:
    return MoneyRange(upper * 9 // 10, upper * 8 // 10, upper)


def _cost(
    wait: tuple[int, int],
    travel: tuple[int, int],
    *,
    taxi_upper: int = 0,
    next_service_wait: tuple[int, int] | None = None,
) -> LegCost:
    return LegCost(
        wait=TimeEstimate(*wait),
        travel=TimeEstimate(*travel),
        fare=_money(taxi_upper) if taxi_upper else ZERO,
        next_service_wait=(
            TimeEstimate(*next_service_wait)
            if next_service_wait is not None
            else None
        ),
    )


def _constraints() -> RouteConstraints:
    return RouteConstraints(
        taxi_budget_krw=BUDGET,
        strict_taxi_budget=True,
        max_walk_seconds=3_600,
        max_transfers=4,
        max_taxi_legs=3,
        allowed_modes=frozenset(
            {"WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"}
        ),
        allow_taxi_bridge=True,
    )


def _seed(
    key: str,
    pattern: str,
    modes: tuple[str, ...],
    *,
    taxi_upper: int = 0,
    bus_waits: tuple[BusWaitContribution | None, ...] | None = None,
    schedules: tuple[datetime | None, ...] | None = None,
    transfers: tuple[TransferRequirement, ...] | None = None,
) -> CandidateSeed:
    waits = bus_waits or tuple(None for _ in modes)
    departures = schedules or tuple(None for _ in modes)
    requirements = transfers or tuple(TransferRequirement() for _ in modes)
    return CandidateSeed(
        candidate_key=key,
        pattern=pattern,
        legs=tuple(
            LegSpec(
                leg_id=f"{key}-{index}",
                mode=mode,
                from_ref=f"{key}-node-{index}",
                to_ref=f"{key}-node-{index + 1}",
                evaluator_key=f"{key}-{index}",
                bus_wait=waits[index],
                scheduled_departure_at=departures[index],
                transfer_requirement=requirements[index],
                topology_ref=f"{key}:{mode}:{index}",
            )
            for index, mode in enumerate(modes)
        ),
        transfer_count=max(
            0,
            sum(mode in {"BUS", "SUBWAY", "GTX", "TRAIN"} for mode in modes)
            - 1,
        ),
        coarse_p50_seconds=0,
        coarse_taxi_upper_krw=taxi_upper,
    )


def test_independent_scenario_oracle_covers_full_arrival_arithmetic() -> None:
    oracle = (
        OracleCandidate(
            "oracle-taxi-bus-walk",
            (
                OracleLeg((120, 180), (200, 260), taxi_upper=BUDGET),
                OracleLeg(
                    (0, 0),
                    (500, 650),
                    bus_wait=(100, 240),
                    schedule=500,
                ),
                OracleLeg((0, 0), (100, 140)),
            ),
        ),
        OracleCandidate(
            "oracle-public",
            (
                OracleLeg((0, 0), (100, 140)),
                OracleLeg((300, 420), (800, 1_000)),
                OracleLeg((0, 0), (200, 240)),
            ),
        ),
        OracleCandidate(
            "oracle-over-budget",
            (OracleLeg((0, 0), (500, 600), taxi_upper=BUDGET + 1),),
        ),
        OracleCandidate(
            "oracle-scheduled",
            (
                OracleLeg((0, 0), (700, 850)),
                OracleLeg(
                    (0, 0),
                    (300, 400),
                    connector=(100, 150),
                    connector_walk=100,
                    schedule=900,
                    next_service_wait=(0, 200),
                ),
            ),
        ),
        OracleCandidate(
            "oracle-incident",
            (
                OracleLeg(
                    (100, 100),
                    (300, 400),
                    taxi_upper=5_000,
                    incident_delay=(900, 900),
                ),
            ),
        ),
    )
    expected = {
        item.candidate_key: _oracle_evaluate(item, BUDGET) for item in oracle
    }
    assert expected == {
        "oracle-taxi-bus-walk": (1_020, 1_470, 10_000),
        "oracle-public": (1_400, 1_800, 0),
        "oracle-over-budget": None,
        "oracle-scheduled": (1_200, 1_600, 0),
        "oracle-incident": (1_300, 1_400, 5_000),
    }

    seeds = (
        _seed(
            "oracle-taxi-bus-walk",
            "TAXI_TRANSIT",
            ("TAXI", "BUS", "WALK"),
            taxi_upper=BUDGET,
            bus_waits=(None, BusWaitContribution(100, 240), None),
            schedules=(None, DEPARTURE + timedelta(seconds=500), None),
        ),
        _seed("oracle-public", "TRANSIT_ONLY", ("WALK", "BUS", "WALK")),
        _seed(
            "oracle-over-budget",
            "TAXI_ONLY",
            ("TAXI",),
            taxi_upper=BUDGET + 1,
        ),
        _seed(
            "oracle-scheduled",
            "TRANSIT_ONLY",
            ("BUS", "SUBWAY"),
            schedules=(None, DEPARTURE + timedelta(seconds=900)),
            transfers=(
                TransferRequirement(),
                TransferRequirement(100, 150, connector_walk_seconds=100),
            ),
        ),
        _seed(
            "oracle-incident",
            "TAXI_ONLY",
            ("TAXI",),
            taxi_upper=5_000,
        ),
    )
    costs = {
        "oracle-taxi-bus-walk-0": _cost((120, 180), (200, 260), taxi_upper=BUDGET),
        "oracle-taxi-bus-walk-1": _cost((0, 0), (500, 650)),
        "oracle-taxi-bus-walk-2": _cost((0, 0), (100, 140)),
        "oracle-public-0": _cost((0, 0), (100, 140)),
        "oracle-public-1": _cost((300, 420), (800, 1_000)),
        "oracle-public-2": _cost((0, 0), (200, 240)),
        "oracle-over-budget-0": _cost(
            (0, 0), (500, 600), taxi_upper=BUDGET + 1
        ),
        "oracle-scheduled-0": _cost((0, 0), (700, 850)),
        "oracle-scheduled-1": _cost(
            (0, 0),
            (300, 400),
            next_service_wait=(0, 200),
        ),
        "oracle-incident-0": _cost(
            (100, 100), (1_200, 1_300), taxi_upper=5_000
        ),
    }
    optimizer = RouteOptimizer(StaticLegEvaluator(costs))
    by_key = {item.candidate_key: item for item in seeds}
    for candidate_key, expected_value in expected.items():
        result = optimizer.optimize(
            (by_key[candidate_key],), DEPARTURE, _constraints()
        )
        if expected_value is None:
            assert result.routes == ()
            continue
        assert result.routes[0].total_duration == TimeEstimate(
            expected_value[0], expected_value[1]
        )
        assert result.routes[0].taxi_cost.upper_krw == expected_value[2]

    combined = optimizer.optimize(seeds, DEPARTURE, _constraints())
    returned = {route.candidate_key: route for route in combined.routes}
    assert combined.recommendations.fastest == returned[
        "oracle-taxi-bus-walk"
    ].route_id


def test_bounded_cartesian_oracle_exhaustively_matches_chronology_and_fastest() -> None:
    """Exhaust a small state space without production expected-value helpers."""

    dimensions = (
        (5, 35),  # Taxi dispatch wait P50.
        (105, 185),  # Taxi drive P50 before incident delay.
        (0, 30),  # P90 delta propagated through wait/travel.
        (BUDGET, BUDGET + 1),  # Strict upper-fare boundary.
        (0, 40),  # Connector duration and walking contribution.
        (False, True),  # Scheduled wait versus authoritative BusWait.
        ("CATCH", "MISS"),  # Both catch versus P50-catch/P90-miss.
        (0, 145),  # Incident delay on the Taxi drive.
    )
    states = tuple(product(*dimensions))
    assert len(states) == 256

    individual_candidate_checks = 0
    permutation_checks = 0
    authoritative_bus_results: dict[tuple[object, ...], tuple[int, int, int]] = {}

    for (
        taxi_wait,
        taxi_drive,
        p90_delta,
        taxi_upper,
        connector,
        has_bus_wait,
        schedule_case,
        incident_delay,
    ) in states:
        ready_bus_p50 = 60 + connector
        ready_bus_p90 = 60 + p90_delta + connector + 20
        schedule_seconds = (
            ready_bus_p90 + 10
            if schedule_case == "CATCH"
            else ready_bus_p50 + 10
        )
        if schedule_case == "CATCH":
            assert ready_bus_p50 <= schedule_seconds
            assert ready_bus_p90 <= schedule_seconds
        else:
            assert ready_bus_p50 <= schedule_seconds < ready_bus_p90

        authoritative_wait = (50, 90) if has_bus_wait else None
        oracle_candidates = (
            OracleCandidate(
                "cartesian-taxi",
                (
                    OracleLeg(
                        (taxi_wait, taxi_wait + p90_delta),
                        (taxi_drive, taxi_drive + p90_delta),
                        taxi_upper=taxi_upper,
                        incident_delay=(incident_delay, incident_delay),
                    ),
                ),
            ),
            OracleCandidate(
                "cartesian-bus",
                (
                    OracleLeg((0, 0), (60, 60 + p90_delta)),
                    OracleLeg(
                        (0, 0),
                        (180, 220 + p90_delta),
                        connector=(connector, connector + 20),
                        connector_walk=connector,
                        bus_wait=authoritative_wait,
                        schedule=schedule_seconds,
                        next_service_wait=(30, 60),
                    ),
                ),
            ),
            OracleCandidate(
                "cartesian-public",
                (OracleLeg((55, 75), (260, 310)),),
            ),
        )
        expected = {
            candidate.candidate_key: _oracle_evaluate(candidate, BUDGET)
            for candidate in oracle_candidates
        }
        feasible = {
            candidate_key: value
            for candidate_key, value in expected.items()
            if value is not None
        }
        # P50s are deliberately unique, so expected FASTEST needs no copy of the
        # production reliability/risk/walk/route-id tie-break implementation.
        assert len({value[0] for value in feasible.values()}) == len(feasible)
        expected_fastest = min(feasible, key=lambda key: feasible[key][0])

        seeds = (
            _seed(
                "cartesian-taxi",
                "TAXI_ONLY",
                ("TAXI",),
                taxi_upper=taxi_upper,
            ),
            _seed(
                "cartesian-bus",
                "TRANSIT_ONLY",
                ("WALK", "BUS"),
                bus_waits=(
                    None,
                    BusWaitContribution(*authoritative_wait)
                    if authoritative_wait is not None
                    else None,
                ),
                schedules=(
                    None,
                    DEPARTURE + timedelta(seconds=schedule_seconds),
                ),
                transfers=(
                    TransferRequirement(),
                    TransferRequirement(
                        connector,
                        connector + 20,
                        connector_walk_seconds=connector,
                    ),
                ),
            ),
            _seed("cartesian-public", "TRANSIT_ONLY", ("BUS",)),
        )
        costs = {
            "cartesian-taxi-0": _cost(
                (taxi_wait, taxi_wait + p90_delta),
                (
                    taxi_drive + incident_delay,
                    taxi_drive + incident_delay + p90_delta,
                ),
                taxi_upper=taxi_upper,
            ),
            "cartesian-bus-0": _cost((0, 0), (60, 60 + p90_delta)),
            "cartesian-bus-1": _cost(
                (0, 0),
                (180, 220 + p90_delta),
                next_service_wait=(30, 60),
            ),
            "cartesian-public-0": _cost((55, 75), (260, 310)),
        }
        optimizer = RouteOptimizer(
            StaticLegEvaluator(costs), epsilon=ZERO_EPSILON
        )
        seeds_by_key = {candidate.candidate_key: candidate for candidate in seeds}

        for candidate_key, expected_value in expected.items():
            result = optimizer.optimize(
                (seeds_by_key[candidate_key],), DEPARTURE, _constraints()
            )
            individual_candidate_checks += 1
            if expected_value is None:
                assert result.routes == ()
                assert {item.reason for item in result.rejected} == {
                    "STRICT_TAXI_BUDGET"
                }
                continue
            assert len(result.routes) == 1
            actual = result.routes[0]
            assert actual.total_duration == TimeEstimate(
                expected_value[0], expected_value[1]
            )
            assert actual.taxi_cost.upper_krw == expected_value[2]

            if candidate_key == "cartesian-bus" and has_bus_wait:
                invariance_key = (
                    taxi_wait,
                    taxi_drive,
                    p90_delta,
                    taxi_upper,
                    connector,
                    incident_delay,
                )
                previous = authoritative_bus_results.setdefault(
                    invariance_key, expected_value
                )
                assert previous == expected_value

        for ordering in permutations(seeds):
            result = optimizer.optimize(ordering, DEPARTURE, _constraints())
            fastest = next(
                route
                for route in result.routes
                if route.route_id == result.recommendations.fastest
            )
            assert fastest.candidate_key == expected_fastest
            permutation_checks += 1

    assert individual_candidate_checks == 768
    assert permutation_checks == 1_536
    # For each of 64 non-schedule dimensions, CATCH and MISS metadata produce
    # the same authoritative-BusWait chronology.
    assert len(authoritative_bus_results) == 64


def _strategy_inputs(*, access_drive: int, egress_walk: int) -> StrategyGenerationInput:
    origin, stop, alight, destination = "origin", "stop", "alight", "destination"
    baseline = TransitBaseline(
        "bus-with-walk",
        (
            WalkQuote(
                "access-walk",
                origin,
                stop,
                "cost:access-walk",
                TimeEstimate(600, 720),
                600,
                lower_bound_seconds=500,
            ),
            TransitLegInput(
                "bus",
                "BUS",
                CanonicalTransitTopology(
                    "route-1", "OUTBOUND", stop, alight, 1, 10
                ),
                "cost:bus",
                TimeEstimate(600, 750),
                lower_bound_seconds=500,
                bus_wait=BusWaitContribution(120, 300),
            ),
            WalkQuote(
                "egress-walk",
                alight,
                destination,
                "cost:egress-walk",
                TimeEstimate(egress_walk, egress_walk + 60),
                egress_walk,
                lower_bound_seconds=egress_walk,
            ),
        ),
    )
    access_taxi = TaxiQuote(
        "access-taxi",
        origin,
        stop,
        "cost:access-taxi",
        TimeEstimate(120, 180),
        TimeEstimate(access_drive, access_drive + 120),
        _money(4_000),
        2_000,
        lower_bound_dispatch_seconds=60,
        lower_bound_drive_seconds=max(0, access_drive - 60),
    )
    taxi_only = TaxiQuote(
        "taxi-only",
        origin,
        destination,
        "cost:taxi-only",
        TimeEstimate(120, 180),
        TimeEstimate(1_000, 1_200),
        _money(8_000),
        8_000,
        lower_bound_dispatch_seconds=60,
        lower_bound_drive_seconds=900,
    )
    return StrategyGenerationInput(
        origin,
        destination,
        DEPARTURE,
        (baseline,),
        access_hubs=(AccessHub("taxi-to-bus", baseline.baseline_id, 1, access_taxi),),
        taxi_only_quotes=(taxi_only,),
    )


def _strategy_optimize(inputs: StrategyGenerationInput):
    batch = BoundedStrategyGenerator().generate(inputs, _constraints())
    result = RouteOptimizer(
        StaticLegEvaluator(batch.costs()), epsilon=ZERO_EPSILON
    ).optimize(
        batch.seeds,
        DEPARTURE,
        _constraints(),
        provider_call_count=batch.unique_provider_calls,
    )
    return batch, result


def test_strategy_to_optimizer_taxi_bus_walk_incident_and_egress_reversals() -> None:
    clear_batch, clear = _strategy_optimize(
        _strategy_inputs(access_drive=120, egress_walk=100)
    )
    clear_routes = {route.route_id: route for route in clear.routes}
    clear_fastest = clear_routes[clear.recommendations.fastest]
    assert clear_fastest.pattern == "TAXI_TRANSIT"
    assert tuple(leg.mode for leg in clear_fastest.legs) == ("TAXI", "BUS", "WALK")
    assert {item.seed.pattern for item in clear_batch.candidates} >= {
        "TRANSIT_ONLY",
        "TAXI_TRANSIT",
        "TAXI_ONLY",
    }

    _, incident = _strategy_optimize(
        _strategy_inputs(access_drive=600, egress_walk=100)
    )
    incident_routes = {route.route_id: route for route in incident.routes}
    assert incident_routes[incident.recommendations.fastest].pattern == "TAXI_ONLY"

    _, long_egress = _strategy_optimize(
        _strategy_inputs(access_drive=120, egress_walk=300)
    )
    egress_routes = {route.route_id: route for route in long_egress.routes}
    assert egress_routes[long_egress.recommendations.fastest].pattern == "TAXI_ONLY"


def test_connector_walk_seconds_propagates_from_strategy_input_to_leg_spec() -> None:
    connector = TransferRequirement(300, 360, connector_walk_seconds=240)
    baseline = TransitBaseline(
        "connector",
        (
            TransitLegInput(
                "bus",
                "BUS",
                CanonicalTransitTopology(
                    "route-bus", "OUTBOUND", "origin", "station", 1, 4
                ),
                "cost:connector-bus",
                TimeEstimate(600, 720),
            ),
            TransitLegInput(
                "subway",
                "SUBWAY",
                CanonicalTransitTopology(
                    "line-1", "OUTBOUND", "station", "destination", 2, 8
                ),
                "cost:connector-subway",
                TimeEstimate(900, 1_020),
                transfer_requirement=connector,
            ),
        ),
    )
    batch = BoundedStrategyGenerator().generate(
        StrategyGenerationInput(
            "origin", "destination", DEPARTURE, (baseline,)
        ),
        _constraints(),
    )

    transit = next(item.seed for item in batch.candidates if item.seed.pattern == "TRANSIT_ONLY")
    assert transit.legs[1].transfer_requirement is connector
    assert transit.legs[1].transfer_requirement.connector_walk_seconds == 240
