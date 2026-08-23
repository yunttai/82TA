from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from routing_domain.candidate_generation import OptimalityUncertifiedError
from routing_domain.models import MoneyRange, RouteConstraints, TimeEstimate
from routing_domain.policy import CandidateCaps
from routing_domain.strategy_generation import (
    BoundedStrategyGenerator,
    QuoteReadiness,
    StrategyGenerationInput,
    StrategyGenerationPolicy,
    TaxiQuote,
)


KST = timezone(timedelta(hours=9))
DEPARTURE = datetime(2026, 8, 24, 7, 0, tzinfo=KST)
ORIGIN = "origin"
DESTINATION = "destination"


def taxi(
    key: str,
    *,
    drive: int,
    upper: int = 1_000,
    coarse: bool = False,
) -> TaxiQuote:
    return TaxiQuote(
        quote_id=key,
        from_ref=ORIGIN,
        to_ref=DESTINATION,
        evaluator_key=f"cost:{key}",
        dispatch_wait=TimeEstimate(120, 180),
        drive_duration=TimeEstimate(drive, drive + 120),
        fare=MoneyRange(upper, upper, upper),
        distance_meters=3_000,
        lower_bound_dispatch_seconds=60,
        lower_bound_drive_seconds=max(0, drive - 120),
        readiness=QuoteReadiness.COARSE if coarse else QuoteReadiness.EXACT,
        topology_ref=f"taxi:{key}",
    )


def inputs(*quotes: TaxiQuote) -> StrategyGenerationInput:
    return StrategyGenerationInput(
        ORIGIN,
        DESTINATION,
        DEPARTURE,
        (),
        taxi_only_quotes=tuple(quotes),
    )


def constraints(*, budget: int = 10_000) -> RouteConstraints:
    return RouteConstraints(
        taxi_budget_krw=budget,
        strict_taxi_budget=True,
        max_walk_seconds=3_600,
        max_transfers=4,
        max_taxi_legs=2,
        allowed_modes=frozenset({"WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"}),
        allow_taxi_bridge=True,
    )


def test_search_space_retains_pre_pareto_k_plus_one_and_bypasses_soft_caps() -> None:
    quotes = (
        taxi("a", drive=200),
        taxi("b", drive=300),
        # Coarse fare is deliberately above budget: only exact evaluation may
        # prove strict-budget infeasibility.
        taxi("c", drive=400, upper=10_001),
    )
    generator = BoundedStrategyGenerator(
        caps=CandidateCaps(coarse_combinations=4, pre_pareto=2),
        policy=StrategyGenerationPolicy(max_taxi_only=1),
    )

    space = generator.build_search_space(inputs(*reversed(quotes)), constraints())
    assert tuple(item.seed.candidate_key for item in space.candidates) == (
        "taxi-only:a",
        "taxi-only:b",
        "taxi-only:c",
    )
    assert "COARSE_TAXI_BUDGET" not in {item.reason for item in space.rejected}

    frontier = space.open_frontier()
    first = frontier.next_exactification_batch()
    assert tuple(item.seed.candidate_key for item in first.candidates) == (
        "taxi-only:a",
        "taxi-only:b",
    )
    assert first.min_unseen_p50_lower_bound == quotes[2].lower_bound_seconds
    assert not first.scope_exhausted
    second = frontier.next_exactification_batch()
    assert tuple(item.seed.candidate_key for item in second.candidates) == (
        "taxi-only:c",
    )
    assert second.scope_exhausted


def test_equal_lower_bound_stays_unseen_and_identity_order_is_deterministic() -> None:
    a = taxi("equal-a", drive=300)
    b = taxi("equal-b", drive=300)
    space = BoundedStrategyGenerator(
        caps=CandidateCaps(coarse_combinations=3, pre_pareto=1)
    ).build_search_space(inputs(b, a), constraints())

    frontier = space.open_frontier()
    first = frontier.next_exactification_batch()
    assert first.candidates[0].seed.candidate_key == "taxi-only:equal-a"
    assert first.min_unseen_p50_lower_bound == first.candidates[0].seed.coarse_p50_seconds
    assert not first.scope_exhausted


def test_search_space_and_batches_are_input_permutation_deterministic() -> None:
    quotes = tuple(taxi(f"perm-{index}", drive=200 + index * 10) for index in range(4))
    generator = BoundedStrategyGenerator(
        caps=CandidateCaps(coarse_combinations=5, pre_pareto=2)
    )
    forward = generator.build_search_space(inputs(*quotes), constraints())
    reverse = generator.build_search_space(inputs(*reversed(quotes)), constraints())

    assert forward == reverse
    assert forward.open_frontier().next_exactification_batch() == reverse.open_frontier().next_exactification_batch()


def test_exact_provider_unit_boundary_forms_contiguous_batches() -> None:
    quotes = tuple(
        taxi(f"provider-{index}", drive=200 + index * 10, coarse=True)
        for index in range(3)
    )
    space = BoundedStrategyGenerator(
        caps=CandidateCaps(
            coarse_combinations=4,
            pre_pareto=3,
            provider_calls=2,
        )
    ).build_search_space(inputs(*quotes), constraints())
    frontier = space.open_frontier()

    first = frontier.next_exactification_batch()
    assert len(first.candidates) == 2
    assert first.logical_provider_calls == 2
    assert first.exactification_plan.logical_provider_calls == 2
    assert not first.scope_exhausted

    second = frontier.next_exactification_batch()
    assert len(second.candidates) == 1
    assert second.logical_provider_calls == 1
    assert second.scope_exhausted


def test_finite_scope_over_hard_combination_cap_fails_closed() -> None:
    quotes = tuple(taxi(f"hard-{index}", drive=200 + index) for index in range(3))
    generator = BoundedStrategyGenerator(
        caps=CandidateCaps(coarse_combinations=2, pre_pareto=2)
    )

    with pytest.raises(
        OptimalityUncertifiedError,
        match="EXACT_CANDIDATE_CAP_UNCERTIFIED",
    ):
        generator.build_search_space(inputs(*quotes), constraints())


def test_candidate_larger_than_provider_batch_cap_fails_closed_without_cursor_loss() -> None:
    quote = taxi("two-units", drive=200, coarse=True)
    # Replacing readiness creates one taxi enrichment. Add a second unit through
    # the immutable request plan to exercise the candidate-atomic boundary.
    space = BoundedStrategyGenerator(
        caps=CandidateCaps(coarse_combinations=2, pre_pareto=1, provider_calls=2)
    ).build_search_space(inputs(quote), constraints())
    candidate = space.candidates[0]
    request = candidate.exact_enrichment[0]
    two_unit = replace(request, call_units=2)
    exact_step = candidate.exactification.steps[0]
    amended_candidate = replace(
        candidate,
        exact_enrichment=(two_unit,),
        exactification=replace(
            candidate.exactification,
            steps=(replace(exact_step, enrichment=(two_unit,)),),
        ),
    )
    amended_space = replace(space, candidates=(amended_candidate,))
    frontier = amended_space.open_frontier()

    with pytest.raises(
        OptimalityUncertifiedError,
        match="CANDIDATE_PROVIDER_CALL_CAP_UNCERTIFIED",
    ):
        frontier.next_exactification_batch(logical_provider_call_cap=1)
    assert frontier.min_unseen_p50_lower_bound is not None


def test_tampered_search_space_and_batch_invariants_fail_fast() -> None:
    a = taxi("invariant-a", drive=200)
    b = taxi("invariant-b", drive=300)
    space = BoundedStrategyGenerator(
        caps=CandidateCaps(coarse_combinations=3, pre_pareto=1)
    ).build_search_space(inputs(a, b), constraints())

    with pytest.raises(ValueError, match="deterministic frontier order"):
        replace(space, candidates=tuple(reversed(space.candidates)))

    batch = space.open_frontier().next_exactification_batch()
    with pytest.raises(ValueError, match="unseen lower bound contradicts exhaustion"):
        replace(batch, scope_exhausted=True)
