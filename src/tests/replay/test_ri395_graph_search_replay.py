from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from itertools import permutations
from typing import Callable, Iterable

import pytest

from routing_domain import (
    CanonicalRoutingGraph,
    EpsilonPolicy,
    GraphSearchCaps,
    GraphSearchUncertifiedError,
    LegCost,
    LegSpec,
    MoneyRange,
    RouteConstraints,
    RouteOptimizer,
    TimeDependentGraphSearch,
    TimeEstimate,
    TransferRequirement,
)


DEPARTURE = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
ZERO_FARE = MoneyRange.zero()


@dataclass(frozen=True)
class _Rule:
    cost_at: Callable[[datetime], LegCost]


class _RuleEvaluator:
    """Deterministic test port whose rules are also consumable by the oracle."""

    def __init__(self, rules: dict[str, _Rule]) -> None:
        self.rules = rules
        self.calls: list[tuple[str, datetime]] = []

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        self.calls.append((leg.evaluator_key, entry_at))
        return self.cost_for(leg, entry_at)

    def cost_for(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        return self.rules[leg.evaluator_key].cost_at(entry_at)


@dataclass(frozen=True)
class _OraclePath:
    leg_ids: tuple[str, ...]
    p50_seconds: int
    p90_seconds: int
    taxi_upper_krw: int


def _constant_rule(
    p50: int,
    p90: int | None = None,
    *,
    wait_p50: int = 0,
    wait_p90: int | None = None,
    fare_upper: int = 0,
    reliability: float = 1.0,
    next_service: TimeEstimate | None = None,
) -> _Rule:
    p90 = p50 if p90 is None else p90
    wait_p90 = wait_p50 if wait_p90 is None else wait_p90
    fare = MoneyRange(fare_upper, fare_upper, fare_upper)
    return _Rule(
        lambda _entry: LegCost(
            wait=TimeEstimate(wait_p50, wait_p90),
            travel=TimeEstimate(p50, p90),
            fare=fare,
            reliability_score=reliability,
            next_service_wait=next_service,
        )
    )


def _leg(
    leg_id: str,
    mode: str,
    from_ref: str,
    to_ref: str,
    *,
    key: str | None = None,
    scheduled_at: datetime | None = None,
    transfer: TransferRequirement | None = None,
    topology_ref: str | None = None,
) -> LegSpec:
    return LegSpec(
        leg_id=leg_id,
        mode=mode,
        from_ref=from_ref,
        to_ref=to_ref,
        evaluator_key=key or leg_id,
        scheduled_departure_at=scheduled_at,
        transfer_requirement=transfer or TransferRequirement(),
        topology_ref=topology_ref or leg_id,
    )


def _constraints(
    *,
    budget: int = 20_000,
    max_legs: int = 4,
    allow_taxi_bridge: bool = True,
) -> RouteConstraints:
    return RouteConstraints(
        taxi_budget_krw=budget,
        strict_taxi_budget=True,
        max_walk_seconds=20_000,
        max_transfers=max_legs,
        max_taxi_legs=max_legs,
        allowed_modes=frozenset({"WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"}),
        allow_taxi_bridge=allow_taxi_bridge,
    )


def _path_key(leg_ids: Iterable[str]) -> str:
    material = "|".join(leg_ids)
    return f"graph_{sha256(material.encode('utf-8')).hexdigest()[:20]}"


def _supported_pattern(legs: tuple[LegSpec, ...]) -> bool:
    transit = {"BUS", "SUBWAY", "GTX", "TRAIN"}
    core = tuple(leg.mode for leg in legs if leg.mode not in {"WALK", "WAIT", "TRANSFER"})
    if not core or any(mode != "TAXI" and mode not in transit for mode in core):
        return False
    kinds = tuple("TAXI" if mode == "TAXI" else "TRANSIT" for mode in core)
    compressed = tuple(
        kind for index, kind in enumerate(kinds) if index == 0 or kind != kinds[index - 1]
    )
    return compressed in {
        ("TRANSIT",),
        ("TAXI",),
        ("TAXI", "TRANSIT"),
        ("TRANSIT", "TAXI"),
        ("TAXI", "TRANSIT", "TAXI"),
        ("TRANSIT", "TAXI", "TRANSIT"),
    }


def _enumerate_simple_paths(
    edges: tuple[LegSpec, ...],
    origin: str,
    destination: str,
    max_legs: int,
) -> tuple[tuple[LegSpec, ...], ...]:
    adjacency: dict[str, list[LegSpec]] = {}
    for edge in edges:
        adjacency.setdefault(edge.from_ref, []).append(edge)
    found: list[tuple[LegSpec, ...]] = []

    def visit(node: str, visited: frozenset[str], path: tuple[LegSpec, ...]) -> None:
        if node == destination:
            if path and _supported_pattern(path):
                found.append(path)
            return
        if len(path) >= max_legs:
            return
        for edge in adjacency.get(node, ()):
            if edge.to_ref in visited:
                continue
            visit(edge.to_ref, visited | {edge.to_ref}, (*path, edge))

    visit(origin, frozenset({origin}), ())
    return tuple(found)


def _oracle_unscheduled(
    path: tuple[LegSpec, ...],
    evaluator: _RuleEvaluator,
    departure_at: datetime,
) -> _OraclePath:
    """Independent sequential clock propagation for unscheduled oracle graphs."""

    current_p50 = departure_at
    current_p90 = departure_at
    taxi_upper = 0
    walk_seconds = 0
    for leg in path:
        requirement = leg.transfer_requirement
        ready_p50 = current_p50 + timedelta(seconds=requirement.p50_seconds)
        ready_p90 = current_p90 + timedelta(seconds=requirement.p90_seconds)
        ready_cost_p50 = evaluator.cost_for(leg, ready_p50)
        ready_cost_p90 = evaluator.cost_for(leg, ready_p90)
        start_p50 = ready_p50 + timedelta(seconds=ready_cost_p50.wait.p50_seconds)
        start_p90 = ready_p90 + timedelta(seconds=ready_cost_p90.wait.p90_seconds)
        travel_p50 = evaluator.cost_for(leg, start_p50)
        travel_p90 = evaluator.cost_for(leg, start_p90)
        assert travel_p50.fare is not None and travel_p90.fare is not None
        current_p50 = start_p50 + timedelta(seconds=travel_p50.travel.p50_seconds)
        current_p90 = max(
            start_p90 + timedelta(seconds=travel_p90.travel.p90_seconds),
            current_p50,
        )
        if leg.mode == "TAXI":
            taxi_upper += max(travel_p50.fare.upper_krw, travel_p90.fare.upper_krw)
        if leg.mode == "WALK":
            walk_seconds += travel_p50.travel.p50_seconds
        walk_seconds += requirement.connector_walk_seconds
    assert walk_seconds >= 0
    return _OraclePath(
        leg_ids=tuple(leg.leg_id for leg in path),
        p50_seconds=int((current_p50 - departure_at).total_seconds()),
        p90_seconds=int((current_p90 - departure_at).total_seconds()),
        taxi_upper_krw=taxi_upper,
    )


def _actual_paths(result: object) -> dict[tuple[str, ...], tuple[int, int, int, str]]:
    evaluated = result.evaluated_candidates  # type: ignore[attr-defined]
    seeds = result.seeds  # type: ignore[attr-defined]
    return {
        tuple(leg.leg_id for leg in seed.legs): (
            candidate.total_duration.p50_seconds,
            candidate.total_duration.p90_seconds,
            candidate.taxi_cost.upper_krw,
            seed.candidate_key,
        )
        for seed, candidate in zip(seeds, evaluated)
    }


def test_graph_search_matches_independent_exhaustive_oracle_for_all_edge_permutations() -> None:
    edges = (
        _leg("oa", "BUS", "O", "A"),
        _leg("ad", "BUS", "A", "D"),
        _leg("ob", "TAXI", "O", "B"),
        _leg("bd", "BUS", "B", "D"),
        _leg("ab", "WALK", "A", "B"),
    )

    def bd_rule(entry: datetime) -> LegCost:
        # The same edge changes after propagated entry time; the oracle does not
        # assume a static edge weight.
        seconds = 180 if entry < DEPARTURE + timedelta(minutes=5) else 45
        return LegCost(TimeEstimate(0, 0), TimeEstimate(seconds, seconds), ZERO_FARE)

    evaluator = _RuleEvaluator(
        {
            "oa": _constant_rule(120),
            "ad": _constant_rule(300),
            "ob": _constant_rule(60, fare_upper=4_000),
            "bd": _Rule(bd_rule),
            "ab": _constant_rule(90),
        }
    )
    constraints = _constraints(max_legs=3)
    oracle = {
        item.leg_ids: item
        for item in (
            _oracle_unscheduled(path, evaluator, DEPARTURE)
            for path in _enumerate_simple_paths(edges, "O", "D", 3)
        )
        if item.taxi_upper_krw <= constraints.taxi_budget_krw
    }
    assert set(oracle) == {("oa", "ad"), ("ob", "bd"), ("oa", "ab", "bd")}

    expected: dict[tuple[str, ...], tuple[int, int, int, str]] | None = None
    for ordering in permutations(edges):
        result = TimeDependentGraphSearch(evaluator).search(
            CanonicalRoutingGraph(tuple(ordering)), "O", "D", DEPARTURE, constraints
        )
        actual = _actual_paths(result)
        assert set(actual) == set(oracle)
        for leg_ids, metrics in actual.items():
            oracle_path = oracle[leg_ids]
            assert metrics == (
                oracle_path.p50_seconds,
                oracle_path.p90_seconds,
                oracle_path.taxi_upper_krw,
                _path_key(leg_ids),
            )
        expected = actual if expected is None else expected
        assert actual == expected


def test_time_band_reversal_retains_later_label_that_becomes_globally_fastest() -> None:
    edges = (
        _leg("oa", "BUS", "O", "A"),
        _leg("ob", "BUS", "O", "B"),
        _leg("ba", "BUS", "B", "A"),
        _leg("ad", "BUS", "A", "D"),
    )

    def final_band(entry: datetime) -> LegCost:
        travel = 1_200 if entry < DEPARTURE + timedelta(minutes=5) else 60
        return LegCost(TimeEstimate(0, 0), TimeEstimate(travel, travel), ZERO_FARE)

    evaluator = _RuleEvaluator(
        {
            "oa": _constant_rule(60),
            "ob": _constant_rule(180),
            "ba": _constant_rule(180),
            "ad": _Rule(final_band),
        }
    )
    result = TimeDependentGraphSearch(evaluator).search(
        CanonicalRoutingGraph(edges), "O", "D", DEPARTURE, _constraints(max_legs=3)
    )
    actual = _actual_paths(result)
    assert actual[("oa", "ad")][0] == 1_260
    assert actual[("ob", "ba", "ad")][0] == 420
    assert min(actual, key=lambda path: actual[path]) == ("ob", "ba", "ad")


def test_scheduled_transfer_catch_and_p90_miss_use_explicit_next_service() -> None:
    scheduled = DEPARTURE + timedelta(minutes=5)
    transfer = TransferRequirement(p50_seconds=60, p90_seconds=120, connector_walk_seconds=45)
    edges = (
        _leg("access", "WALK", "O", "S"),
        _leg("scheduled", "BUS", "S", "D", scheduled_at=scheduled, transfer=transfer),
    )
    evaluator = _RuleEvaluator(
        {
            "access": _constant_rule(180, 240),
            "scheduled": _constant_rule(
                300,
                360,
                next_service=TimeEstimate(600, 720),
            ),
        }
    )
    result = TimeDependentGraphSearch(evaluator).search(
        CanonicalRoutingGraph(edges), "O", "D", DEPARTURE, _constraints(max_legs=2)
    )
    candidate = result.evaluated_candidates[0]
    transfer_leg = candidate.legs[1]
    assert transfer_leg.transfer_margin is not None
    assert transfer_leg.transfer_margin.p50_seconds == 60
    assert transfer_leg.transfer_margin.p90_seconds == -60
    assert transfer_leg.start_at_p50 == scheduled
    assert transfer_leg.start_at_p90 == DEPARTURE + timedelta(minutes=18)
    assert candidate.walk_seconds == 225

    no_evidence = _RuleEvaluator(
        {"access": _constant_rule(180, 240), "scheduled": _constant_rule(300, 360)}
    )
    failed = TimeDependentGraphSearch(no_evidence).search(
        CanonicalRoutingGraph(edges), "O", "D", DEPARTURE, _constraints(max_legs=2)
    )
    assert failed.seeds == ()
    assert any(item.reason == "TRANSFER_INFEASIBLE" for item in failed.rejected)


def test_strict_sum_taxi_upper_budget_accepts_b_and_prunes_b_plus_one_before_tail() -> None:
    edges = (
        _leg("ok-1", "TAXI", "O", "A"),
        _leg("ok-middle", "BUS", "A", "Y"),
        _leg("ok-2", "TAXI", "Y", "Z"),
        _leg("ok-tail", "WALK", "Z", "D"),
        _leg("over-1", "TAXI", "O", "B"),
        _leg("over-middle", "BUS", "B", "C"),
        _leg("over-2", "TAXI", "C", "W"),
        _leg("over-tail", "WALK", "W", "D"),
    )
    evaluator = _RuleEvaluator(
        {
            "ok-1": _constant_rule(60, fare_upper=4_000),
            "ok-middle": _constant_rule(60),
            "ok-2": _constant_rule(60, fare_upper=6_000),
            "ok-tail": _constant_rule(60),
            "over-1": _constant_rule(60, fare_upper=4_001),
            "over-middle": _constant_rule(60),
            "over-2": _constant_rule(60, fare_upper=6_000),
            "over-tail": _constant_rule(60),
        }
    )
    result = TimeDependentGraphSearch(evaluator).search(
        CanonicalRoutingGraph(edges), "O", "D", DEPARTURE, _constraints(budget=10_000, max_legs=4)
    )
    assert set(_actual_paths(result)) == {("ok-1", "ok-middle", "ok-2", "ok-tail")}
    assert result.evaluated_candidates[0].taxi_cost.upper_krw == 10_000
    assert any(item.reason == "STRICT_TAXI_BUDGET" for item in result.rejected)
    assert all(key != "over-tail" for key, _entry in evaluator.calls)


def test_resource_label_keeps_later_cheap_prefix_needed_for_budget_feasible_suffix() -> None:
    edges = (
        _leg("fast-expensive", "TAXI", "O", "A"),
        _leg("slow-public-1", "BUS", "O", "B"),
        _leg("slow-public-2", "BUS", "B", "A"),
        _leg("suffix-taxi", "TAXI", "A", "D"),
    )
    evaluator = _RuleEvaluator(
        {
            "fast-expensive": _constant_rule(60, fare_upper=8_000),
            "slow-public-1": _constant_rule(180),
            "slow-public-2": _constant_rule(180),
            "suffix-taxi": _constant_rule(60, fare_upper=5_000),
        }
    )
    result = TimeDependentGraphSearch(evaluator).search(
        CanonicalRoutingGraph(edges), "O", "D", DEPARTURE, _constraints(budget=10_000, max_legs=3)
    )
    assert set(_actual_paths(result)) == {("slow-public-1", "slow-public-2", "suffix-taxi")}
    assert result.evaluated_candidates[0].taxi_cost.upper_krw == 5_000
    assert any(item.reason == "STRICT_TAXI_BUDGET" for item in result.rejected)


def test_equal_metric_labels_do_not_discard_smaller_visited_set_needed_by_suffix() -> None:
    edges = (
        _leg("oa", "BUS", "O", "A"),
        _leg("ax", "BUS", "A", "X"),
        _leg("ob", "BUS", "O", "B"),
        _leg("bx", "BUS", "B", "X"),
        _leg("xa", "BUS", "X", "A"),
        _leg("ad", "BUS", "A", "D"),
    )
    evaluator = _RuleEvaluator({edge.evaluator_key: _constant_rule(60) for edge in edges})
    assert _path_key(("oa", "ax")) < _path_key(("ob", "bx"))
    result = TimeDependentGraphSearch(evaluator).search(
        CanonicalRoutingGraph(edges), "O", "D", DEPARTURE, _constraints(max_legs=4)
    )
    assert ("ob", "bx", "xa", "ad") in _actual_paths(result)
    assert any(item.reason == "GRAPH_CYCLE" for item in result.rejected)


def test_equal_metric_labels_keep_distinct_pattern_state_for_future_extension() -> None:
    edges = (
        _leg("tax-start", "TAXI", "O", "T"),
        _leg("bus-mid", "BUS", "T", "X"),
        _leg("bus-start", "BUS", "O", "B"),
        _leg("tax-mid", "TAXI", "B", "X"),
        _leg("tax-final", "TAXI", "X", "D"),
    )
    evaluator = _RuleEvaluator(
        {
            "tax-start": _constant_rule(60, fare_upper=1_000),
            "bus-mid": _constant_rule(60),
            "bus-start": _constant_rule(60),
            "tax-mid": _constant_rule(60, fare_upper=1_000),
            "tax-final": _constant_rule(60, fare_upper=1_000),
        }
    )
    assert _path_key(("bus-start", "tax-mid")) < _path_key(("tax-start", "bus-mid"))
    result = TimeDependentGraphSearch(evaluator).search(
        CanonicalRoutingGraph(edges), "O", "D", DEPARTURE, _constraints(max_legs=3)
    )
    assert ("tax-start", "bus-mid", "tax-final") in _actual_paths(result)
    assert any(item.reason == "PATTERN_UNSUPPORTED" for item in result.rejected)


def test_taxi_bridge_is_rejected_when_constraint_disables_it() -> None:
    edges = (
        _leg("bus-in", "BUS", "O", "A"),
        _leg("taxi-bridge", "TAXI", "A", "B"),
        _leg("bus-out", "BUS", "B", "D"),
    )
    evaluator = _RuleEvaluator(
        {
            "bus-in": _constant_rule(60),
            "taxi-bridge": _constant_rule(60, fare_upper=1_000),
            "bus-out": _constant_rule(60),
        }
    )
    result = TimeDependentGraphSearch(evaluator).search(
        CanonicalRoutingGraph(edges),
        "O",
        "D",
        DEPARTURE,
        _constraints(max_legs=3, allow_taxi_bridge=False),
    )
    assert result.seeds == ()
    assert any(item.reason == "TAXI_BRIDGE_DISABLED" for item in result.rejected)


def test_cycles_are_rejected_and_all_search_caps_fail_closed() -> None:
    cycle_edges = (
        _leg("oa", "BUS", "O", "A"),
        _leg("ao", "BUS", "A", "O"),
        _leg("ad", "BUS", "A", "D"),
    )
    cycle_eval = _RuleEvaluator({edge.evaluator_key: _constant_rule(60) for edge in cycle_edges})
    cycle_result = TimeDependentGraphSearch(cycle_eval).search(
        CanonicalRoutingGraph(cycle_edges), "O", "D", DEPARTURE, _constraints(max_legs=3)
    )
    assert set(_actual_paths(cycle_result)) == {("oa", "ad")}
    assert any(item.reason == "GRAPH_CYCLE" for item in cycle_result.rejected)

    chain = (_leg("oa", "BUS", "O", "A"), _leg("ad", "BUS", "A", "D"))
    chain_eval = _RuleEvaluator({edge.evaluator_key: _constant_rule(60) for edge in chain})
    with pytest.raises(GraphSearchUncertifiedError, match="GRAPH_EXPANSION_CAP_UNCERTIFIED"):
        TimeDependentGraphSearch(
            chain_eval,
            caps=GraphSearchCaps(max_expansions=1, max_labels_per_node=8, max_complete_paths=8, max_legs=3),
        ).search(CanonicalRoutingGraph(chain), "O", "D", DEPARTURE, _constraints(max_legs=3))

    with pytest.raises(GraphSearchUncertifiedError, match="GRAPH_LEG_CAP_UNCERTIFIED"):
        TimeDependentGraphSearch(
            chain_eval,
            caps=GraphSearchCaps(max_expansions=8, max_labels_per_node=8, max_complete_paths=8, max_legs=1),
        ).search(CanonicalRoutingGraph(chain), "O", "D", DEPARTURE, _constraints(max_legs=3))

    label_edges = (
        _leg("oa", "BUS", "O", "A"),
        _leg("ob", "BUS", "O", "B"),
        _leg("ba", "BUS", "B", "A"),
        _leg("ad", "BUS", "A", "D"),
    )
    label_eval = _RuleEvaluator(
        {"oa": _constant_rule(60), "ob": _constant_rule(60), "ba": _constant_rule(60), "ad": _constant_rule(60)}
    )
    with pytest.raises(GraphSearchUncertifiedError, match="GRAPH_LABEL_CAP_UNCERTIFIED"):
        TimeDependentGraphSearch(
            label_eval,
            caps=GraphSearchCaps(max_expansions=20, max_labels_per_node=1, max_complete_paths=8, max_legs=3),
        ).search(CanonicalRoutingGraph(label_edges), "O", "D", DEPARTURE, _constraints(max_legs=3))

    complete_edges = (
        _leg("bus", "BUS", "O", "D"),
        _leg("taxi", "TAXI", "O", "D"),
    )
    complete_eval = _RuleEvaluator(
        {"bus": _constant_rule(60), "taxi": _constant_rule(60, fare_upper=1_000)}
    )
    with pytest.raises(GraphSearchUncertifiedError, match="GRAPH_COMPLETE_PATH_CAP_UNCERTIFIED"):
        TimeDependentGraphSearch(
            complete_eval,
            caps=GraphSearchCaps(max_expansions=8, max_labels_per_node=8, max_complete_paths=1, max_legs=3),
        ).search(CanonicalRoutingGraph(complete_edges), "O", "D", DEPARTURE, _constraints(max_legs=3))


def test_graph_seeds_drive_four_distinct_optimizer_policies_deterministically() -> None:
    edges = (
        _leg("fastest", "TAXI", "O", "D", topology_ref="fastest"),
        _leg("efficient", "TAXI", "O", "D", topology_ref="efficient"),
        _leg("public-fast", "BUS", "O", "D", topology_ref="public-fast"),
        _leg("stable", "SUBWAY", "O", "D", topology_ref="stable"),
    )
    evaluator = _RuleEvaluator(
        {
            "fastest": _constant_rule(600, 1_800, fare_upper=9_000, reliability=0.70),
            "efficient": _constant_rule(720, 1_500, fare_upper=5_000, reliability=0.95),
            "public-fast": _constant_rule(900, 2_400, reliability=0.80),
            "stable": _constant_rule(1_080, 1_200, reliability=0.99),
        }
    )
    constraints = _constraints(max_legs=1)
    outcome = RouteOptimizer(
        evaluator,
        epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0),
    ).optimize_graph(
        CanonicalRoutingGraph(edges),
        "O",
        "D",
        DEPARTURE,
        constraints,
    )
    optimized = outcome.optimization
    routes_by_leg = {candidate.legs[0].leg_id: candidate.route_id for candidate in optimized.routes}
    recommendations = optimized.recommendations
    assert len(set(routes_by_leg.values())) == 4
    assert recommendations.fastest == routes_by_leg["fastest"]
    assert recommendations.stable == routes_by_leg["stable"]
    assert recommendations.efficient == routes_by_leg["efficient"]
    assert recommendations.public_transit_only == routes_by_leg["public-fast"]

    reversed_outcome = RouteOptimizer(
        evaluator,
        epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0),
    ).optimize_graph(
        CanonicalRoutingGraph(tuple(reversed(edges))),
        "O",
        "D",
        DEPARTURE,
        constraints,
    )
    reversed_optimized = reversed_outcome.optimization
    assert reversed_optimized.recommendations == recommendations
    assert tuple(route.route_id for route in reversed_optimized.routes) == tuple(
        route.route_id for route in optimized.routes
    )


def test_exact_fastest_anchor_survives_epsilon_display_pruning() -> None:
    edges = (
        _leg("exact-fast", "TAXI", "O", "D", topology_ref="exact-fast"),
        _leg("epsilon-representative", "BUS", "O", "D", topology_ref="epsilon-representative"),
    )
    evaluator = _RuleEvaluator(
        {
            "exact-fast": _constant_rule(100, 300, fare_upper=1_000),
            "epsilon-representative": _constant_rule(110, 200, fare_upper=900),
        }
    )
    constraints = _constraints(budget=1_000, max_legs=1)
    graph_result = TimeDependentGraphSearch(evaluator).search(
        CanonicalRoutingGraph(edges), "O", "D", DEPARTURE, constraints
    )
    optimized = RouteOptimizer(evaluator).optimize(graph_result.seeds, DEPARTURE, constraints)
    by_leg = {candidate.legs[0].leg_id: candidate for candidate in optimized.routes}
    assert optimized.recommendations.fastest == by_leg["exact-fast"].route_id
    assert by_leg["exact-fast"].route_id not in optimized.pareto_route_ids
    assert by_leg["epsilon-representative"].route_id in optimized.pareto_route_ids
