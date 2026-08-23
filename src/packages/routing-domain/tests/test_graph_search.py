from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from routing_domain.evaluators import StaticLegEvaluator
from routing_domain.graph_search import (
    CanonicalRoutingGraph,
    GraphSearchCaps,
    GraphSearchUncertifiedError,
    TimeDependentGraphSearch,
)
from routing_domain.models import (
    CandidateSeed,
    LegCost,
    LegSpec,
    MoneyRange,
    RouteConstraints,
    TimeEstimate,
    TransferRequirement,
)
from routing_domain.optimizer import RouteOptimizer
from routing_domain.policy import CandidateCaps, EpsilonPolicy


KST = timezone(timedelta(hours=9))
DEPARTURE = datetime(2026, 8, 24, 7, 0, tzinfo=KST)
ZERO_EPSILON = EpsilonPolicy(0, 0, 0, 0, 0.0)


def cost(
    p50: int,
    p90: int | None = None,
    *,
    wait: int = 0,
    upper: int = 0,
    reliability: float = 1.0,
    next_service: TimeEstimate | None = None,
) -> LegCost:
    p90 = p50 if p90 is None else p90
    return LegCost(
        wait=TimeEstimate(wait, wait),
        travel=TimeEstimate(p50, p90),
        fare=MoneyRange(upper, upper, upper),
        reliability_score=reliability,
        next_service_wait=next_service,
    )


def edge(
    key: str,
    mode: str,
    start: str,
    end: str,
    *,
    scheduled: datetime | None = None,
    transfer: TransferRequirement | None = None,
) -> LegSpec:
    return LegSpec(
        leg_id=key,
        mode=mode,
        from_ref=start,
        to_ref=end,
        evaluator_key=key,
        scheduled_departure_at=scheduled,
        transfer_requirement=transfer or TransferRequirement(),
        topology_ref=f"topology:{key}",
    )


def constraints(*, budget: int = 10_000) -> RouteConstraints:
    return RouteConstraints(
        taxi_budget_krw=budget,
        strict_taxi_budget=True,
        max_walk_seconds=10_000,
        max_transfers=4,
        max_taxi_legs=3,
        allowed_modes=frozenset({"WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"}),
        allow_taxi_bridge=True,
    )


class TimeReversalEvaluator:
    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        if leg.evaluator_key == "early-access":
            return cost(50)
        if leg.evaluator_key == "late-access":
            return cost(200)
        elapsed = int((entry_at - DEPARTURE).total_seconds())
        return cost(1_000 if elapsed < 100 else 100)


class BusCatchEvaluator:
    """Nine-minute bus: a ten-minute walk misses it, a six-minute Taxi catches it."""

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        if leg.evaluator_key == "catch-walk":
            return cost(600)
        if leg.evaluator_key == "catch-taxi":
            # Dispatch wait and road travel are already included in this P50.
            return cost(360, 480, upper=5_000)

        elapsed = int((entry_at - DEPARTURE).total_seconds())
        first_bus_at = 9 * 60
        next_bus_at = 30 * 60
        board_at = first_bus_at if elapsed < first_bus_at else next_bus_at
        return cost(20 * 60, 22 * 60, wait=board_at - elapsed)


def test_later_discovered_label_wins_after_downstream_time_band_reversal() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("early-access", "WALK", "o", "m"),
            edge("late-access", "WALK", "o", "m"),
            edge("band-bus", "BUS", "m", "d"),
        )
    )

    result = TimeDependentGraphSearch(TimeReversalEvaluator()).search(
        graph, "o", "d", DEPARTURE, constraints()
    )

    by_first_leg = {
        candidate.legs[0].leg_id: candidate for candidate in result.evaluated_candidates
    }
    assert by_first_leg["early-access"].total_duration.p50_seconds == 1_050
    assert by_first_leg["late-access"].total_duration.p50_seconds == 300
    assert result.evaluated_candidates[0] == by_first_leg["late-access"]


def test_taxi_is_selected_when_ten_minute_walk_misses_bus_arriving_in_nine() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("catch-walk", "WALK", "origin", "stop"),
            edge("catch-taxi", "TAXI", "origin", "stop"),
            edge("catch-bus", "BUS", "stop", "destination"),
        )
    )

    outcome = RouteOptimizer(
        BusCatchEvaluator(), epsilon=ZERO_EPSILON
    ).optimize_graph(
        graph,
        "origin",
        "destination",
        DEPARTURE,
        constraints(),
    )
    routes = {
        route.legs[0].leg_id: route for route in outcome.optimization.routes
    }

    # The walk reaches at +10m and must wait for the +30m service. The Taxi
    # reaches at +6m, waits three minutes, and boards the +9m service.
    assert routes["catch-walk"].total_duration.p50_seconds == 50 * 60
    assert routes["catch-taxi"].total_duration.p50_seconds == 29 * 60
    assert outcome.optimization.recommendations.fastest == routes["catch-taxi"].route_id
    assert outcome.optimization.recommendations.efficient == routes["catch-taxi"].route_id
    assert (
        outcome.optimization.recommendations.public_transit_only
        == routes["catch-walk"].route_id
    )


class ScheduledEvaluator:
    def __init__(self, *, next_service: bool) -> None:
        self.next_service = next_service

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        if leg.evaluator_key == "scheduled-first":
            return cost(100, 200)
        return cost(
            100,
            100,
            next_service=(TimeEstimate(400, 500) if self.next_service else None),
        )


def test_scheduled_transfer_uses_next_service_for_p90_and_fails_without_evidence() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("scheduled-first", "BUS", "o", "m"),
            edge(
                "scheduled-second",
                "SUBWAY",
                "m",
                "d",
                scheduled=DEPARTURE + timedelta(seconds=250),
                transfer=TransferRequirement(50, 100),
            ),
        )
    )
    feasible = TimeDependentGraphSearch(
        ScheduledEvaluator(next_service=True)
    ).search(graph, "o", "d", DEPARTURE, constraints())
    route = feasible.evaluated_candidates[0]
    assert route.legs[1].start_at_p50 == DEPARTURE + timedelta(seconds=250)
    assert route.legs[1].start_at_p90 == DEPARTURE + timedelta(seconds=800)
    assert route.total_duration == TimeEstimate(350, 900)

    infeasible = TimeDependentGraphSearch(
        ScheduledEvaluator(next_service=False)
    ).search(graph, "o", "d", DEPARTURE, constraints())
    assert not infeasible.seeds
    assert "TRANSFER_INFEASIBLE" in {item.reason for item in infeasible.rejected}


def test_summed_taxi_upper_budget_boundary_is_pruned_during_expansion() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("taxi-first", "TAXI", "o", "m"),
            edge("taxi-boundary", "TAXI", "m", "d"),
            edge("taxi-over", "TAXI", "m", "d"),
        )
    )
    result = TimeDependentGraphSearch(
        StaticLegEvaluator(
            {
                "taxi-first": cost(100, upper=5_000),
                "taxi-boundary": cost(100, upper=5_000),
                "taxi-over": cost(90, upper=5_001),
            }
        )
    ).search(graph, "o", "d", DEPARTURE, constraints(budget=10_000))

    assert len(result.seeds) == 1
    assert result.evaluated_candidates[0].taxi_cost.upper_krw == 10_000
    assert "STRICT_TAXI_BUDGET" in {item.reason for item in result.rejected}


def test_earlier_expensive_label_does_not_kill_budget_feasible_suffix() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("expensive-early", "TAXI", "o", "m"),
            edge("cheap-late", "WALK", "o", "m"),
            edge("suffix-taxi", "TAXI", "m", "d"),
        )
    )
    result = TimeDependentGraphSearch(
        StaticLegEvaluator(
            {
                "expensive-early": cost(100, upper=9_000),
                "cheap-late": cost(200),
                "suffix-taxi": cost(100, upper=2_000),
            }
        )
    ).search(graph, "o", "d", DEPARTURE, constraints(budget=10_000))

    assert len(result.seeds) == 1
    assert result.seeds[0].legs[0].leg_id == "cheap-late"
    assert result.evaluated_candidates[0].taxi_cost.upper_krw == 2_000
    assert "STRICT_TAXI_BUDGET" in {item.reason for item in result.rejected}


def test_equal_metric_label_with_more_visited_nodes_cannot_hide_feasible_suffix() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("visited-o-x", "WALK", "o", "x"),
            edge("visited-x-m", "WALK", "x", "m"),
            edge("visited-o-y", "WALK", "o", "y"),
            edge("visited-y-m", "WALK", "y", "m"),
            edge("visited-m-x", "WALK", "m", "x"),
            edge("visited-x-d", "BUS", "x", "d"),
        )
    )
    evaluator = StaticLegEvaluator(
        {
            "visited-o-x": cost(50),
            "visited-x-m": cost(50),
            "visited-o-y": cost(50),
            "visited-y-m": cost(50),
            "visited-m-x": cost(50),
            "visited-x-d": cost(50),
        }
    )

    result = TimeDependentGraphSearch(evaluator).search(
        graph, "o", "d", DEPARTURE, constraints()
    )

    paths = {tuple(leg.leg_id for leg in seed.legs) for seed in result.seeds}
    assert (
        "visited-o-y",
        "visited-y-m",
        "visited-m-x",
        "visited-x-d",
    ) in paths


def test_equal_metric_different_pattern_automata_are_not_tie_deduplicated() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("state-a-taxi", "TAXI", "o", "a"),
            edge("state-a-bus", "BUS", "a", "b"),
            edge("state-a-walk", "WALK", "b", "m"),
            edge("state-b-bus-2", "BUS", "o", "b"),
            edge("state-b-taxi-2", "TAXI", "b", "a"),
            edge("state-b-walk-2", "WALK", "a", "m"),
            edge("state-suffix-taxi", "TAXI", "m", "d"),
        )
    )
    evaluator = StaticLegEvaluator({item.evaluator_key: cost(30) for item in graph.edges})

    result = TimeDependentGraphSearch(evaluator).search(
        graph, "o", "d", DEPARTURE, constraints()
    )

    paths = {tuple(leg.leg_id for leg in seed.legs) for seed in result.seeds}
    assert (
        "state-a-taxi",
        "state-a-bus",
        "state-a-walk",
        "state-suffix-taxi",
    ) in paths
    assert "PATTERN_UNSUPPORTED" in {item.reason for item in result.rejected}


def test_taxi_bridge_pattern_obeys_request_constraint_during_search() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("bridge-bus-a", "BUS", "o", "a"),
            edge("bridge-taxi", "TAXI", "a", "b"),
            edge("bridge-bus-b", "BUS", "b", "d"),
        )
    )
    evaluator = StaticLegEvaluator({item.evaluator_key: cost(100) for item in graph.edges})
    disallowed = replace(constraints(), allow_taxi_bridge=False)

    result = TimeDependentGraphSearch(evaluator).search(
        graph, "o", "d", DEPARTURE, disallowed
    )

    assert not result.seeds
    assert "TAXI_BRIDGE_DISABLED" in {item.reason for item in result.rejected}


def test_cycle_is_rejected_without_blocking_simple_path() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("to-a", "WALK", "o", "a"),
            edge("back-to-o", "WALK", "a", "o"),
            edge("a-to-d", "BUS", "a", "d"),
        )
    )
    result = TimeDependentGraphSearch(
        StaticLegEvaluator(
            {"to-a": cost(100), "back-to-o": cost(100), "a-to-d": cost(100)}
        ),
        caps=GraphSearchCaps(max_legs=3),
    ).search(graph, "o", "d", DEPARTURE, constraints())

    assert len(result.seeds) == 1
    assert "GRAPH_CYCLE" in {item.reason for item in result.rejected}
    assert len(result.seeds[0].legs) == 2


def test_graph_edge_permutation_is_deterministic() -> None:
    edges = (
        edge("perm-walk", "WALK", "o", "m"),
        edge("perm-bus", "BUS", "m", "d"),
        edge("perm-taxi", "TAXI", "o", "d"),
    )
    evaluator = StaticLegEvaluator(
        {"perm-walk": cost(100), "perm-bus": cost(200), "perm-taxi": cost(250, upper=1_000)}
    )
    search = TimeDependentGraphSearch(evaluator)

    forward = search.search(CanonicalRoutingGraph(edges), "o", "d", DEPARTURE, constraints())
    reverse = search.search(
        CanonicalRoutingGraph(tuple(reversed(edges))),
        "o",
        "d",
        DEPARTURE,
        constraints(),
    )
    assert forward == reverse


class PhaseAwareEvaluator:
    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        return LegCost(
            wait=TimeEstimate(100, 120),
            travel=TimeEstimate(9_999, 9_999),
            fare=MoneyRange(1_000, 1_000, 1_000),
            reliability_score=0.9,
            warning_codes=("READY_PHASE",),
        )

    def evaluate_travel(
        self,
        leg: LegSpec,
        start_at: datetime,
        ready_cost: LegCost | None,
    ) -> LegCost:
        assert ready_cost is not None
        seconds = 200 if leg.evaluator_key.endswith("a") else 300
        return LegCost(
            wait=TimeEstimate(0, 0),
            travel=TimeEstimate(seconds, seconds + 50),
            fare=ready_cost.fare,
            reliability_score=ready_cost.reliability_score,
            warning_codes=ready_cost.warning_codes,
        )


class CountingPhaseAwareEvaluator(PhaseAwareEvaluator):
    def __init__(self) -> None:
        self.ready_calls = 0
        self.travel_calls = 0

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        self.ready_calls += 1
        return super().evaluate(leg, entry_at)

    def evaluate_travel(
        self,
        leg: LegSpec,
        start_at: datetime,
        ready_cost: LegCost | None,
    ) -> LegCost:
        self.travel_calls += 1
        return super().evaluate_travel(leg, start_at, ready_cost)


def test_optional_travel_phase_hook_is_reentrant_and_legacy_fallback_is_unchanged() -> None:
    edges = (
        edge("phase-a", "TAXI", "o", "d"),
        edge("phase-b", "TAXI", "o", "d"),
    )
    graph = CanonicalRoutingGraph(edges)
    phase_search = TimeDependentGraphSearch(PhaseAwareEvaluator())

    first = phase_search.search(graph, "o", "d", DEPARTURE, constraints())
    second = phase_search.search(
        CanonicalRoutingGraph(tuple(reversed(edges))),
        "o",
        "d",
        DEPARTURE,
        constraints(),
    )
    assert first == second
    assert [item.total_duration.p50_seconds for item in first.evaluated_candidates] == [
        300,
        400,
    ]
    assert all("READY_PHASE" in item.warning_codes for item in first.evaluated_candidates)

    legacy = TimeDependentGraphSearch(
        StaticLegEvaluator(
            {
                "phase-a": cost(200, wait=100, upper=1_000),
                "phase-b": cost(300, wait=100, upper=1_000),
            }
        )
    ).search(graph, "o", "d", DEPARTURE, constraints())
    assert [item.total_duration.p50_seconds for item in legacy.evaluated_candidates] == [
        300,
        400,
    ]


def test_graph_entrypoint_reuses_discovery_costs_without_second_evaluation() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("phase-a", "TAXI", "o", "d"),
            edge("phase-b", "TAXI", "o", "d"),
        )
    )
    baseline_evaluator = CountingPhaseAwareEvaluator()
    TimeDependentGraphSearch(baseline_evaluator).search(
        graph, "o", "d", DEPARTURE, constraints()
    )

    entrypoint_evaluator = CountingPhaseAwareEvaluator()
    outcome = RouteOptimizer(
        entrypoint_evaluator,
        epsilon=ZERO_EPSILON,
    ).optimize_graph(graph, "o", "d", DEPARTURE, constraints())

    assert outcome.optimization.routes
    assert (
        entrypoint_evaluator.ready_calls,
        entrypoint_evaluator.travel_calls,
    ) == (
        baseline_evaluator.ready_calls,
        baseline_evaluator.travel_calls,
    )


def test_nondominated_label_cap_fails_closed() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("cap-fast", "TAXI", "o", "m"),
            edge("cap-cheap", "WALK", "o", "m"),
            edge("cap-end", "BUS", "m", "d"),
        )
    )
    search = TimeDependentGraphSearch(
        StaticLegEvaluator(
            {"cap-fast": cost(100, upper=1_000), "cap-cheap": cost(200), "cap-end": cost(100)}
        ),
        caps=GraphSearchCaps(max_labels_per_node=1),
    )

    with pytest.raises(
        GraphSearchUncertifiedError,
        match="GRAPH_LABEL_CAP_UNCERTIFIED",
    ):
        search.search(graph, "o", "d", DEPARTURE, constraints())


def test_discovered_paths_feed_four_distinct_optimizer_rankings() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("rank-public", "BUS", "o", "d"),
            edge("rank-efficient", "TAXI", "o", "d"),
            edge("rank-stable", "TAXI", "o", "d"),
            edge("rank-fastest", "TAXI", "o", "d"),
        )
    )
    costs = {
        "rank-public": cost(3_600, 5_000, reliability=0.8),
        "rank-efficient": cost(3_000, 4_500, upper=1_000, reliability=0.9),
        "rank-stable": cost(2_900, 3_000, upper=8_000, reliability=0.99),
        "rank-fastest": cost(2_400, 4_200, upper=10_000, reliability=0.7),
    }
    outcome = RouteOptimizer(
        StaticLegEvaluator(costs), epsilon=ZERO_EPSILON
    ).optimize_graph(graph, "o", "d", DEPARTURE, constraints())
    optimized = outcome.optimization
    assert len(outcome.graph_search.seeds) == 4
    by_key = {
        route.legs[0].leg_id: route.route_id for route in optimized.routes
    }

    assert optimized.recommendations.fastest == by_key["rank-fastest"]
    assert optimized.recommendations.stable == by_key["rank-stable"]
    assert optimized.recommendations.efficient == by_key["rank-efficient"]
    assert optimized.recommendations.public_transit_only == by_key["rank-public"]
    assert len(
        {
            optimized.recommendations.fastest,
            optimized.recommendations.stable,
            optimized.recommendations.efficient,
            optimized.recommendations.public_transit_only,
        }
    ) == 4


def test_graph_entrypoint_intersects_graph_and_optimizer_caps_fail_closed() -> None:
    graph = CanonicalRoutingGraph(
        (
            edge("cap-public", "BUS", "o", "d"),
            edge("cap-taxi", "TAXI", "o", "d"),
        )
    )
    optimizer = RouteOptimizer(
        StaticLegEvaluator(
            {
                "cap-public": cost(300),
                "cap-taxi": cost(200, upper=1_000),
            }
        ),
        caps=CandidateCaps(coarse_combinations=1, pre_pareto=1),
    )

    with pytest.raises(
        GraphSearchUncertifiedError,
        match="GRAPH_COMPLETE_PATH_CAP_UNCERTIFIED",
    ):
        optimizer.optimize_graph(
            graph,
            "o",
            "d",
            DEPARTURE,
            constraints(),
            graph_caps=GraphSearchCaps(max_complete_paths=8),
        )


def test_graph_entrypoint_restores_named_pattern_for_an_original_exact_path() -> None:
    legs = (
        edge("hint-taxi", "TAXI", "o", "m"),
        edge("hint-bus", "BUS", "m", "d"),
    )
    hint = CandidateSeed(
        candidate_key="upstream-hint",
        pattern="UPSTREAM_STOP_TAXI_TRANSIT",
        legs=legs,
        transfer_count=0,
        coarse_p50_seconds=0,
        coarse_taxi_upper_krw=1_000,
    )
    outcome = RouteOptimizer(
        StaticLegEvaluator(
            {
                "hint-taxi": cost(100, upper=1_000),
                "hint-bus": cost(200),
            }
        ),
        epsilon=ZERO_EPSILON,
    ).optimize_graph(
        CanonicalRoutingGraph(legs),
        "o",
        "d",
        DEPARTURE,
        constraints(),
        pattern_hints=(hint,),
    )

    assert outcome.graph_search.seeds[0].pattern == "UPSTREAM_STOP_TAXI_TRANSIT"
    assert outcome.graph_search.evaluated_candidates[0].pattern == (
        "UPSTREAM_STOP_TAXI_TRANSIT"
    )
    assert outcome.optimization.routes[0].pattern == "UPSTREAM_STOP_TAXI_TRANSIT"
