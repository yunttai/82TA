"""Deterministic representative selection with canonical reason codes."""

from __future__ import annotations

from dataclasses import replace
from math import ceil

from .models import EvaluatedCandidate, RecommendationSet, RouteConstraints
from .policy import RankingPolicy


def _fastest_key(candidate: EvaluatedCandidate) -> tuple[object, ...]:
    return (
        candidate.total_duration.p50_seconds,
        -candidate.reliability_score,
        candidate.transfer_risk,
        candidate.walk_seconds,
        candidate.total_duration.p90_seconds,
        candidate.taxi_cost.upper_krw,
        candidate.route_id,
    )


def _mode_choice_penalty_seconds(
    candidate: EvaluatedCandidate,
    policy: RankingPolicy,
) -> int:
    """Preference cost used outside the literal FASTEST clock.

    Walking time is already part of actual arrival time.  This adds discomfort
    only beyond the comfortable walking band, while each Taxi leg carries a
    small activation burden.  A Taxi that catches an earlier Bus still wins when
    its real end-to-end saving is larger than these preference costs.
    """

    excess_walk = max(0, candidate.walk_seconds - policy.comfortable_walk_seconds)
    walk_penalty = ceil(excess_walk * (policy.walk_time_weight - 1.0))
    taxi_penalty = candidate.taxi_leg_count * policy.taxi_activation_penalty_seconds
    return walk_penalty + taxi_penalty


def _stable_key(
    candidate: EvaluatedCandidate,
    policy: RankingPolicy,
) -> tuple[object, ...]:
    preference_penalty = _mode_choice_penalty_seconds(candidate, policy)
    return (
        candidate.total_duration.p90_seconds + preference_penalty,
        candidate.transfer_risk,
        -candidate.reliability_score,
        candidate.total_duration.p50_seconds + preference_penalty,
        candidate.walk_seconds,
        candidate.route_id,
    )


def _efficient_duration_seconds(
    candidate: EvaluatedCandidate,
    policy: RankingPolicy,
) -> int:
    return (
        candidate.total_duration.p50_seconds
        + _mode_choice_penalty_seconds(candidate, policy)
    )


def _with_reasons(
    candidates: tuple[EvaluatedCandidate, ...],
    reasons: dict[str, set[str]],
) -> tuple[EvaluatedCandidate, ...]:
    return tuple(
        replace(
            candidate,
            reason_codes=tuple(sorted(set(candidate.reason_codes) | reasons.get(candidate.route_id, set()))),
        )
        for candidate in candidates
    )


def select_recommendations(
    frontier: tuple[EvaluatedCandidate, ...],
    constraints: RouteConstraints,
    policy: RankingPolicy,
    *,
    exact_feasible: tuple[EvaluatedCandidate, ...] | None = None,
) -> tuple[tuple[EvaluatedCandidate, ...], RecommendationSet]:
    eligible = exact_feasible if exact_feasible is not None else frontier
    if not eligible:
        return frontier, RecommendationSet(None, None, None, None)
    if not frontier:
        raise ValueError("non-empty exact feasible pool requires a frontier")

    # FASTEST and PUBLIC_TRANSIT_ONLY are canonical exact anchors. Epsilon
    # representative pruning is a display/frontier policy and must never change
    # either exact feasible argmin.
    fastest = min(eligible, key=_fastest_key)
    reliable = tuple(item for item in frontier if item.reliability_score >= policy.reliability_floor)
    stable = min(reliable or frontier, key=lambda item: _stable_key(item, policy))
    public_candidates = tuple(item for item in eligible if item.taxi_cost.upper_krw == 0)
    public = min(public_candidates, key=_fastest_key) if public_candidates else None

    cost_tiers: dict[int, EvaluatedCandidate] = {}
    efficiency_pool = {
        item.route_id: item for item in (*frontier, *((public,) if public is not None else ()))
    }
    for candidate in efficiency_pool.values():
        cost = candidate.taxi_cost.upper_krw
        current = cost_tiers.get(cost)
        if current is None or (
            _efficient_duration_seconds(candidate, policy),
            _fastest_key(candidate),
        ) < (
            _efficient_duration_seconds(current, policy),
            _fastest_key(current),
        ):
            cost_tiers[cost] = candidate
    ordered_tiers = tuple(cost_tiers[cost] for cost in sorted(cost_tiers))
    marginal: list[tuple[float, int, int, str, EvaluatedCandidate]] = []
    for cheaper, candidate in zip(ordered_tiers, ordered_tiers[1:]):
        additional_cost = candidate.taxi_cost.upper_krw - cheaper.taxi_cost.upper_krw
        saved_seconds = _efficient_duration_seconds(
            cheaper, policy
        ) - _efficient_duration_seconds(candidate, policy)
        if (
            additional_cost <= 0
            or saved_seconds < policy.minimum_efficient_gain_seconds
        ):
            continue
        marginal.append(
            (
                -(saved_seconds / additional_cost),
                -saved_seconds,
                additional_cost,
                candidate.route_id,
                candidate,
            )
        )
    if marginal:
        efficient = min(marginal)[4]
        positive_gain = True
    else:
        efficient = public or ordered_tiers[0]
        positive_gain = False

    reasons: dict[str, set[str]] = {}

    def add(candidate: EvaluatedCandidate | None, code: str) -> None:
        if candidate is not None:
            reasons.setdefault(candidate.route_id, set()).add(code)

    if public is not None and fastest.total_duration.p50_seconds < public.total_duration.p50_seconds:
        add(fastest, "FASTER_THAN_PUBLIC_TRANSIT")
    if fastest.taxi_cost.upper_krw > 0 and fastest.taxi_cost.upper_krw <= constraints.taxi_budget_krw:
        add(fastest, "WITHIN_STRICT_TAXI_BUDGET")
    add(stable, "LOWER_P90_ARRIVAL_TIME")
    if stable.transfer_risk <= min(item.transfer_risk for item in frontier):
        add(stable, "LOW_TRANSFER_RISK")
    add(
        efficient,
        "BEST_MARGINAL_TIME_SAVING" if positive_gain else "NO_MEANINGFUL_GAIN_FROM_MORE_BUDGET",
    )
    by_route_id = {item.route_id: item for item in frontier}
    by_route_id[fastest.route_id] = fastest
    if public is not None:
        by_route_id[public.route_id] = public
    updated = _with_reasons(
        tuple(sorted(by_route_id.values(), key=lambda item: item.route_id)),
        reasons,
    )
    return updated, RecommendationSet(
        fastest=fastest.route_id,
        stable=stable.route_id,
        efficient=efficient.route_id,
        public_transit_only=public.route_id if public else None,
    )
