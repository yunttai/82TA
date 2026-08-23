"""Deterministic representative selection with canonical reason codes."""

from __future__ import annotations

from dataclasses import replace

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


def _stable_key(candidate: EvaluatedCandidate) -> tuple[object, ...]:
    return (
        candidate.total_duration.p90_seconds,
        candidate.transfer_risk,
        -candidate.reliability_score,
        candidate.total_duration.p50_seconds,
        candidate.walk_seconds,
        candidate.route_id,
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
) -> tuple[tuple[EvaluatedCandidate, ...], RecommendationSet]:
    if not frontier:
        return frontier, RecommendationSet(None, None, None, None)

    fastest = min(frontier, key=_fastest_key)
    reliable = tuple(item for item in frontier if item.reliability_score >= policy.reliability_floor)
    stable = min(reliable or frontier, key=_stable_key)
    public_candidates = tuple(item for item in frontier if item.taxi_cost.upper_krw == 0)
    public = min(public_candidates, key=_fastest_key) if public_candidates else None

    cost_tiers: dict[int, EvaluatedCandidate] = {}
    for candidate in frontier:
        cost = candidate.taxi_cost.upper_krw
        current = cost_tiers.get(cost)
        if current is None or _fastest_key(candidate) < _fastest_key(current):
            cost_tiers[cost] = candidate
    ordered_tiers = tuple(cost_tiers[cost] for cost in sorted(cost_tiers))
    marginal: list[tuple[float, int, int, str, EvaluatedCandidate]] = []
    for cheaper, candidate in zip(ordered_tiers, ordered_tiers[1:]):
        additional_cost = candidate.taxi_cost.upper_krw - cheaper.taxi_cost.upper_krw
        saved_seconds = (
            cheaper.total_duration.p50_seconds
            - candidate.total_duration.p50_seconds
        )
        if additional_cost <= 0 or saved_seconds <= 0:
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
    updated = _with_reasons(frontier, reasons)
    return updated, RecommendationSet(
        fastest=fastest.route_id,
        stable=stable.route_id,
        efficient=efficient.route_id,
        public_transit_only=public.route_id if public else None,
    )
