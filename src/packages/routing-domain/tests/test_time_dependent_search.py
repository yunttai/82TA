from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from routing_domain.evaluation import CandidateEvaluator
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
from routing_domain.policy import EpsilonPolicy
from routing_domain.search import (
    SearchNotCertifiedError,
    TimeDependentCandidateSearch,
)


KST = timezone(timedelta(hours=9))
DEPARTURE = datetime(2026, 8, 24, 7, 0, tzinfo=KST)
ZERO_EPSILON = EpsilonPolicy(0, 0, 0, 0, 0.0)


def cost(
    travel_p50: int,
    travel_p90: int | None = None,
    *,
    wait_p50: int = 0,
    wait_p90: int | None = None,
    taxi_upper: int = 0,
    reliability: float = 1.0,
    next_service: TimeEstimate | None = None,
) -> LegCost:
    travel_p90 = travel_p50 if travel_p90 is None else travel_p90
    wait_p90 = wait_p50 if wait_p90 is None else wait_p90
    return LegCost(
        wait=TimeEstimate(wait_p50, wait_p90),
        travel=TimeEstimate(travel_p50, travel_p90),
        fare=MoneyRange(taxi_upper, taxi_upper, taxi_upper),
        reliability_score=reliability,
        next_service_wait=next_service,
    )


def seed(
    key: str,
    pattern: str,
    modes: tuple[str, ...],
    *,
    lower_bound: int,
    taxi_upper: int = 0,
    bus_waits: tuple[BusWaitContribution | None, ...] | None = None,
    transfers: tuple[TransferRequirement, ...] | None = None,
    scheduled: tuple[datetime | None, ...] | None = None,
) -> CandidateSeed:
    bus_waits = bus_waits or (None,) * len(modes)
    transfers = transfers or (TransferRequirement(),) * len(modes)
    scheduled = scheduled or (None,) * len(modes)
    legs = tuple(
        LegSpec(
            leg_id=f"{key}-{index}",
            mode=mode,
            from_ref=f"{key}-node-{index}",
            to_ref=f"{key}-node-{index + 1}",
            evaluator_key=f"{key}-{index}",
            scheduled_departure_at=scheduled[index],
            transfer_requirement=transfers[index],
            bus_wait=bus_waits[index],
            topology_ref=f"{key}-topology-{index}",
        )
        for index, mode in enumerate(modes)
    )
    return CandidateSeed(
        candidate_key=key,
        pattern=pattern,
        legs=legs,
        transfer_count=max(
            0,
            sum(mode in {"BUS", "SUBWAY", "GTX", "TRAIN"} for mode in modes) - 1,
        ),
        coarse_p50_seconds=lower_bound,
        coarse_taxi_upper_krw=taxi_upper,
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


def run_to_exhaustion(search: TimeDependentCandidateSearch) -> None:
    while search.has_pending_candidates:
        before = search.active_candidate
        evaluated = search.evaluate_next()
        if evaluated is None and before is None and search.active_candidate is None:
            # A hard cap leaves a non-empty frontier intentionally unconsumed.
            if search.certificate().hard_cap_reached:
                break


def build_search(
    seeds: tuple[CandidateSeed, ...],
    costs: dict[str, LegCost],
    *,
    hard_cap: int | None = None,
    epsilon: EpsilonPolicy = ZERO_EPSILON,
    route_constraints: RouteConstraints | None = None,
) -> TimeDependentCandidateSearch:
    evaluator = CandidateEvaluator(StaticLegEvaluator(costs))
    return TimeDependentCandidateSearch(
        seeds,
        DEPARTURE,
        route_constraints or constraints(),
        evaluator,
        epsilon=epsilon,
        hard_candidate_cap=hard_cap,
    )


def test_k_plus_one_winner_is_not_hidden_by_hard_cap() -> None:
    seeds = tuple(
        seed(f"cap-{index}", "TAXI_ONLY", ("TAXI",), lower_bound=index + 1)
        for index in range(3)
    )
    search = build_search(
        seeds,
        {
            "cap-0-0": cost(500),
            "cap-1-0": cost(400),
            "cap-2-0": cost(100),
        },
        hard_cap=2,
    )

    run_to_exhaustion(search)

    certificate = search.certificate()
    assert certificate.hard_cap_reached
    assert not certificate.fastest_certified
    assert certificate.fastest_reason == "HARD_CANDIDATE_CAP_UNCERTIFIED"
    with pytest.raises(SearchNotCertifiedError, match="SEARCH_NOT_CERTIFIED"):
        search.finalize(("FASTEST",))


def test_equal_unseen_lower_bound_requires_exact_tie_evaluation() -> None:
    first = seed("tie-a", "TRANSIT_ONLY", ("BUS",), lower_bound=1)
    second = seed("tie-b", "TRANSIT_ONLY", ("BUS",), lower_bound=100)
    search = build_search(
        (second, first),
        {
            "tie-a-0": cost(100, reliability=0.8),
            "tie-b-0": cost(100, reliability=0.99),
        },
    )

    assert search.evaluate_next() is not None
    certificate = search.certificate()
    assert not certificate.fastest_certified
    assert certificate.fastest_reason == "EQUAL_LOWER_BOUND_REQUIRES_TIE_EVALUATION"

    run_to_exhaustion(search)
    outcome = search.finalize()
    by_key = {candidate.candidate_key: candidate for candidate in outcome.ranked_routes}
    assert outcome.recommendations.fastest == by_key["tie-b"].route_id


def test_strict_summed_taxi_upper_accepts_budget_and_rejects_budget_plus_one() -> None:
    at_budget = seed(
        "budget",
        "TAXI_TRANSIT_TAXI",
        ("TAXI", "BUS", "TAXI"),
        lower_bound=1,
        taxi_upper=10_000,
    )
    base_costs = {
        "budget-0": cost(100, taxi_upper=5_000),
        "budget-1": cost(200),
        "budget-2": cost(100, taxi_upper=5_000),
    }
    accepted = build_search((at_budget,), base_costs)
    run_to_exhaustion(accepted)
    assert accepted.finalize().exact_feasible[0].taxi_cost.upper_krw == 10_000

    rejected = build_search(
        (at_budget,),
        {**base_costs, "budget-2": cost(100, taxi_upper=5_001)},
    )
    run_to_exhaustion(rejected)
    outcome = rejected.finalize()
    assert not outcome.exact_feasible
    assert {item.reason for item in outcome.rejected} == {"STRICT_TAXI_BUDGET"}


def test_missed_transfer_without_next_service_is_rejected() -> None:
    connection = seed(
        "transfer",
        "TRANSIT_ONLY",
        ("BUS", "SUBWAY"),
        lower_bound=1,
        transfers=(TransferRequirement(), TransferRequirement(200, 200)),
        scheduled=(None, DEPARTURE + timedelta(seconds=250)),
    )
    search = build_search(
        (connection,),
        {
            "transfer-0": cost(100),
            "transfer-1": cost(100),
        },
    )

    run_to_exhaustion(search)

    outcome = search.finalize()
    assert not outcome.exact_feasible
    assert {item.reason for item in outcome.rejected} == {"TRANSFER_INFEASIBLE"}


class EntryTimeEvaluator:
    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        if leg.mode == "WALK":
            return cost(50 if leg.evaluator_key.startswith("early") else 200)
        elapsed = int((entry_at - DEPARTURE).total_seconds())
        return cost(1_000 if elapsed < 100 else 100)


def test_sequential_leg_entry_time_reverses_coarse_frontier_order() -> None:
    early = seed("early", "TRANSIT_ONLY", ("WALK", "BUS"), lower_bound=1)
    later = seed("later", "TRANSIT_ONLY", ("WALK", "BUS"), lower_bound=2)
    search = TimeDependentCandidateSearch(
        (later, early),
        DEPARTURE,
        constraints(),
        CandidateEvaluator(EntryTimeEvaluator()),
        epsilon=ZERO_EPSILON,
    )

    run_to_exhaustion(search)

    outcome = search.finalize()
    by_key = {candidate.candidate_key: candidate for candidate in outcome.ranked_routes}
    assert by_key["early"].total_duration.p50_seconds == 1_050
    assert by_key["later"].total_duration.p50_seconds == 300
    assert outcome.recommendations.fastest == by_key["later"].route_id


def test_taxi_dispatch_and_bus_boarding_wait_change_the_fastest_route() -> None:
    taxi = seed("wait-taxi", "TAXI_ONLY", ("TAXI",), lower_bound=1, taxi_upper=1_000)
    bus = seed(
        "wait-bus",
        "TRANSIT_ONLY",
        ("BUS",),
        lower_bound=2,
        bus_waits=(BusWaitContribution(500, 700),),
    )
    subway = seed("wait-subway", "TRANSIT_ONLY", ("SUBWAY",), lower_bound=3)
    search = build_search(
        (taxi, bus, subway),
        {
            "wait-taxi-0": cost(100, wait_p50=600, taxi_upper=1_000),
            "wait-bus-0": cost(100),
            "wait-subway-0": cost(550),
        },
    )

    run_to_exhaustion(search)

    outcome = search.finalize()
    exact = {candidate.candidate_key: candidate for candidate in outcome.exact_feasible}
    ranked = {candidate.candidate_key: candidate for candidate in outcome.ranked_routes}
    assert exact["wait-taxi"].total_duration.p50_seconds == 700
    assert exact["wait-bus"].total_duration.p50_seconds == 600
    assert outcome.recommendations.fastest == ranked["wait-subway"].route_id


def test_exact_anchors_survive_epsilon_display_pruning() -> None:
    public = seed("epsilon-public", "TRANSIT_ONLY", ("BUS",), lower_bound=1)
    taxi = seed("epsilon-taxi", "TAXI_ONLY", ("TAXI",), lower_bound=2, taxi_upper=100)
    search = build_search(
        (taxi, public),
        {
            "epsilon-public-0": cost(100, 200),
            "epsilon-taxi-0": cost(110, 110, taxi_upper=100),
        },
        epsilon=EpsilonPolicy(),
    )

    run_to_exhaustion(search)

    outcome = search.finalize()
    exact = {candidate.candidate_key for candidate in outcome.exact_feasible}
    display = {candidate.candidate_key for candidate in outcome.epsilon_frontier}
    ranked = {candidate.candidate_key: candidate for candidate in outcome.ranked_routes}
    assert exact == {"epsilon-public", "epsilon-taxi"}
    assert display == {"epsilon-taxi"}
    assert outcome.recommendations.fastest == ranked["epsilon-public"].route_id
    assert outcome.recommendations.public_transit_only == ranked["epsilon-public"].route_id


def test_permutation_determinism_includes_exact_dedupe_and_rankings() -> None:
    a = seed("perm-a", "TRANSIT_ONLY", ("BUS",), lower_bound=10)
    duplicate = replace(
        a,
        candidate_key="perm-a-faster",
        legs=(replace(a.legs[0], leg_id="perm-a-faster-0", evaluator_key="perm-a-faster-0"),),
        coarse_p50_seconds=11,
    )
    taxi = seed("perm-taxi", "TAXI_ONLY", ("TAXI",), lower_bound=12, taxi_upper=100)
    costs = {
        "perm-a-0": cost(500),
        "perm-a-faster-0": cost(300),
        "perm-taxi-0": cost(200, taxi_upper=100),
    }

    outcomes = []
    for ordering in ((a, duplicate, taxi), (taxi, duplicate, a)):
        search = build_search(ordering, costs)
        run_to_exhaustion(search)
        outcomes.append(search.finalize())

    assert outcomes[0] == outcomes[1]
    assert {item.candidate_key for item in outcomes[0].exact_feasible} == {
        "perm-a-faster",
        "perm-taxi",
    }


def test_certificate_transitions_and_early_fastest_finalization() -> None:
    first = seed("cert-fast", "TRANSIT_ONLY", ("BUS",), lower_bound=1)
    unseen = seed("cert-unseen", "TRANSIT_ONLY", ("BUS",), lower_bound=101)
    search = build_search(
        (unseen, first),
        {"cert-fast-0": cost(100), "cert-unseen-0": cost(200)},
    )

    assert not search.certificate().fastest_certified
    assert search.evaluate_next() is not None
    certificate = search.certificate()
    assert certificate.fastest_certified
    assert certificate.min_unseen_p50_lower_bound == 101
    assert certificate.fastest_reason == "MIN_UNSEEN_LOWER_BOUND_EXCEEDS_INCUMBENT"
    early = search.finalize(("FASTEST",))
    assert early.recommendations.fastest is not None
    assert early.recommendations.stable is None
    assert not early.certificate.supplied_scope_exhausted

    run_to_exhaustion(search)
    assert search.certificate().supplied_scope_exhausted
    assert search.finalize().recommendations.fastest == early.recommendations.fastest
