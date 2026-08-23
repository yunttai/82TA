from __future__ import annotations

import itertools
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from routing_domain.evaluation import CandidateEvaluationError, CandidateEvaluator
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
from routing_domain.policy import CandidateCaps, EpsilonPolicy


KST = timezone(timedelta(hours=9))
DEPARTURE = datetime(2026, 8, 24, 7, 0, tzinfo=KST)
ZERO = MoneyRange.zero()
ZERO_EPSILON = EpsilonPolicy(0, 0, 0, 0, 0.0)


def money(upper: int) -> MoneyRange:
    return MoneyRange(
        expected_krw=upper * 9 // 10,
        lower_krw=upper * 8 // 10,
        upper_krw=upper,
    )


def cost(
    travel_p50: int,
    travel_p90: int,
    *,
    wait_p50: int = 0,
    wait_p90: int = 0,
    taxi_upper: int = 0,
    reliability: float = 1.0,
    next_service_wait: TimeEstimate | None = None,
) -> LegCost:
    return LegCost(
        wait=TimeEstimate(wait_p50, wait_p90),
        travel=TimeEstimate(travel_p50, travel_p90),
        fare=money(taxi_upper) if taxi_upper else ZERO,
        reliability_score=reliability,
        next_service_wait=next_service_wait,
    )


def seed(
    key: str,
    pattern: str,
    modes: tuple[str, ...],
    *,
    coarse_p50: int = 0,
    coarse_taxi_upper: int = 0,
    transfer_requirements: tuple[TransferRequirement, ...] | None = None,
    scheduled_departures: tuple[datetime | None, ...] | None = None,
    bus_waits: tuple[BusWaitContribution | None, ...] | None = None,
) -> CandidateSeed:
    requirements = transfer_requirements or tuple(TransferRequirement() for _ in modes)
    schedules = scheduled_departures or tuple(None for _ in modes)
    waits = bus_waits or tuple(None for _ in modes)
    if not (len(modes) == len(requirements) == len(schedules) == len(waits)):
        raise ValueError("leg metadata must match modes")
    legs = tuple(
        LegSpec(
            leg_id=f"{key}-{index}",
            mode=mode,
            from_ref=f"{key}-node-{index}",
            to_ref=f"{key}-node-{index + 1}",
            evaluator_key=f"{key}-{index}",
            scheduled_departure_at=schedules[index],
            transfer_requirement=requirements[index],
            bus_wait=waits[index],
            topology_ref=f"{key}:{mode}:{index}",
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
        coarse_p50_seconds=coarse_p50,
        coarse_taxi_upper_krw=coarse_taxi_upper,
    )


def constraints(
    *,
    budget: int = 20_000,
    max_walk: int = 3_600,
    max_transfers: int = 4,
    max_taxi_legs: int = 3,
) -> RouteConstraints:
    return RouteConstraints(
        taxi_budget_krw=budget,
        strict_taxi_budget=True,
        max_walk_seconds=max_walk,
        max_transfers=max_transfers,
        max_taxi_legs=max_taxi_legs,
        allowed_modes=frozenset({"WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"}),
        allow_taxi_bridge=True,
    )


def by_candidate_key(result) -> dict[str, object]:
    return {route.candidate_key: route for route in result.routes}


class ScheduledConnectionEvaluator:
    """Expose the next service after a P90-only missed connection."""

    next_service = DEPARTURE + timedelta(seconds=1_600)

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        if leg.evaluator_key == "connection-0":
            return cost(700, 900)
        if leg.evaluator_key != "connection-1":
            raise ValueError(f"unknown leg: {leg.evaluator_key}")
        wait = max(0, int((self.next_service - entry_at).total_seconds()))
        return cost(
            400,
            500,
            next_service_wait=TimeEstimate(wait, wait),
        )


class ContextualEvaluator:
    def __init__(self, *, incident: bool) -> None:
        self.incident = incident

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        del entry_at
        if leg.evaluator_key == "context-taxi-0":
            return cost(
                1_200 if self.incident else 300,
                1_500 if self.incident else 420,
                wait_p50=120,
                wait_p90=180,
                taxi_upper=5_000,
            )
        if leg.evaluator_key == "context-public-0":
            return cost(900, 1_050)
        raise ValueError(f"unknown leg: {leg.evaluator_key}")


class NonFifoNextServiceEvaluator:
    """Return individually valid but mutually inconsistent quantile services."""

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        if leg.evaluator_key == "non-fifo-0":
            return cost(700, 900)
        if leg.evaluator_key != "non-fifo-1":
            raise ValueError(f"unknown leg: {leg.evaluator_key}")
        ready_p50 = DEPARTURE + timedelta(seconds=1_100)
        ready_p90 = DEPARTURE + timedelta(seconds=1_300)
        if entry_at == ready_p50:
            next_wait = TimeEstimate(500, 500)
        elif entry_at == ready_p90:
            next_wait = TimeEstimate(100, 100)
        else:
            next_wait = TimeEstimate(0, 0)
        return cost(400, 500, next_service_wait=next_wait)


class RI390ExactFastestTests(unittest.TestCase):
    def test_fastest_is_global_exact_p50_argmin_even_when_epsilon_prefers_slower_route(self) -> None:
        exact_fastest = seed(
            "epsilon-exact-fastest",
            "TAXI_ONLY",
            ("TAXI",),
            coarse_p50=100,
            coarse_taxi_upper=100,
        )
        epsilon_preferred = seed(
            "epsilon-slower",
            "TRANSIT_ONLY",
            ("BUS",),
            coarse_p50=110,
        )
        evaluator = StaticLegEvaluator(
            {
                "epsilon-exact-fastest-0": cost(100, 200, taxi_upper=100),
                "epsilon-slower-0": cost(110, 110),
            }
        )

        result = RouteOptimizer(evaluator).optimize(
            (epsilon_preferred, exact_fastest), DEPARTURE, constraints()
        )

        returned = by_candidate_key(result)
        self.assertIn("epsilon-exact-fastest", returned)
        self.assertEqual(
            result.recommendations.fastest,
            returned["epsilon-exact-fastest"].route_id,
        )
        self.assertIn(result.recommendations.fastest, {route.route_id for route in result.routes})

    def test_public_transit_anchor_survives_taxi_cost_epsilon(self) -> None:
        public = seed("epsilon-public", "TRANSIT_ONLY", ("BUS",), coarse_p50=1_000)
        taxi = seed(
            "epsilon-taxi",
            "TAXI_ONLY",
            ("TAXI",),
            coarse_p50=900,
            coarse_taxi_upper=100,
        )
        result = RouteOptimizer(
            StaticLegEvaluator(
                {
                    "epsilon-public-0": cost(1_000, 1_000),
                    "epsilon-taxi-0": cost(900, 900, taxi_upper=100),
                }
            )
        ).optimize((taxi, public), DEPARTURE, constraints())

        returned = by_candidate_key(result)
        self.assertIn("epsilon-public", returned)
        self.assertEqual(
            result.recommendations.public_transit_only,
            returned["epsilon-public"].route_id,
        )
        self.assertEqual(returned["epsilon-public"].taxi_cost.upper_krw, 0)
        recommendation_ids = {
            result.recommendations.fastest,
            result.recommendations.stable,
            result.recommendations.efficient,
            result.recommendations.public_transit_only,
        } - {None}
        self.assertLessEqual(recommendation_ids, {route.route_id for route in result.routes})

    def test_pre_pareto_cap_cannot_silently_drop_uncertified_true_fastest(self) -> None:
        caps = CandidateCaps(coarse_combinations=3, pre_pareto=2)
        candidates = (
            seed("lower-bound-decoy-a", "TAXI_ONLY", ("TAXI",), coarse_p50=1),
            seed("lower-bound-decoy-b", "TAXI_ONLY", ("TAXI",), coarse_p50=2),
            seed("lower-bound-true-fastest", "TAXI_ONLY", ("TAXI",), coarse_p50=3),
        )
        evaluator = StaticLegEvaluator(
            {
                "lower-bound-decoy-a-0": cost(1_000, 1_000, taxi_upper=100),
                "lower-bound-decoy-b-0": cost(900, 900, taxi_upper=200),
                "lower-bound-true-fastest-0": cost(100, 100, taxi_upper=300),
            }
        )
        result = RouteOptimizer(evaluator, caps=caps, epsilon=ZERO_EPSILON).optimize(
            tuple(reversed(candidates)), DEPARTURE, constraints()
        )

        returned = by_candidate_key(result)
        self.assertIn("lower-bound-true-fastest", returned)
        self.assertEqual(
            result.recommendations.fastest,
            returned["lower-bound-true-fastest"].route_id,
        )

    def test_fastest_matches_exhaustive_feasible_oracle_and_is_order_independent(self) -> None:
        candidates = (
            seed("oracle-public", "TRANSIT_ONLY", ("BUS",), coarse_p50=10),
            seed(
                "oracle-taxi-a",
                "TAXI_ONLY",
                ("TAXI",),
                coarse_p50=20,
                coarse_taxi_upper=1_000,
            ),
            seed(
                "oracle-taxi-b",
                "TAXI_ONLY",
                ("TAXI",),
                coarse_p50=30,
                coarse_taxi_upper=2_000,
            ),
            seed(
                "oracle-taxi-c",
                "TAXI_ONLY",
                ("TAXI",),
                coarse_p50=40,
                coarse_taxi_upper=3_000,
            ),
        )
        costs = {
            "oracle-public-0": cost(800, 900, reliability=0.9),
            "oracle-taxi-a-0": cost(600, 850, taxi_upper=1_000, reliability=0.8),
            "oracle-taxi-b-0": cost(590, 800, taxi_upper=2_000, reliability=0.95),
            "oracle-taxi-c-0": cost(590, 1_000, taxi_upper=3_000, reliability=0.7),
        }
        # Independent one-leg arithmetic oracle: every wait is zero, so total
        # P50 is the supplied travel P50. B and C tie at the exact minimum;
        # rank-0.2.0 deterministically prefers B's higher reliability.
        input_p50 = {
            "oracle-public": 800,
            "oracle-taxi-a": 600,
            "oracle-taxi-b": 590,
            "oracle-taxi-c": 590,
        }
        self.assertEqual(min(input_p50.values()), 590)
        expected = candidates[2]
        optimizer = RouteOptimizer(StaticLegEvaluator(costs))

        observed = set()
        for ordering in itertools.permutations(candidates):
            result = optimizer.optimize(ordering, DEPARTURE, constraints())
            observed.add(result.recommendations.fastest)
            self.assertEqual(result.recommendations.fastest, expected.route_id)
            self.assertIn(expected.route_id, {route.route_id for route in result.routes})
        self.assertEqual(observed, {expected.route_id})

    def test_exact_mode_deduplicates_topology_after_exact_evaluation(self) -> None:
        coarse_first = seed(
            "duplicate-coarse-first",
            "TAXI_ONLY",
            ("TAXI",),
            coarse_p50=1,
            coarse_taxi_upper=1_000,
        )
        exact_fast_leg = replace(
            coarse_first.legs[0],
            leg_id="duplicate-exact-fast-0",
            evaluator_key="duplicate-exact-fast-0",
        )
        exact_fast = replace(
            coarse_first,
            candidate_key="duplicate-exact-fast",
            legs=(exact_fast_leg,),
            coarse_p50_seconds=2,
        )
        result = RouteOptimizer(
            StaticLegEvaluator(
                {
                    "duplicate-coarse-first-0": cost(1_000, 1_000, taxi_upper=1_000),
                    "duplicate-exact-fast-0": cost(100, 100, taxi_upper=1_000),
                }
            ),
            epsilon=ZERO_EPSILON,
        ).optimize((exact_fast, coarse_first), DEPARTURE, constraints())

        returned = by_candidate_key(result)
        self.assertEqual(set(returned), {"duplicate-exact-fast"})
        self.assertEqual(
            result.recommendations.fastest,
            returned["duplicate-exact-fast"].route_id,
        )

    def test_uncertified_coarse_taxi_upper_cannot_reject_exact_feasible_winner(self) -> None:
        taxi = seed(
            "coarse-upper-taxi",
            "TAXI_ONLY",
            ("TAXI",),
            coarse_p50=100,
            coarse_taxi_upper=10_001,
        )
        public = seed("coarse-upper-public", "TRANSIT_ONLY", ("BUS",), coarse_p50=900)
        result = RouteOptimizer(
            StaticLegEvaluator(
                {
                    "coarse-upper-taxi-0": cost(100, 120, taxi_upper=9_000),
                    "coarse-upper-public-0": cost(900, 1_000),
                }
            ),
            epsilon=ZERO_EPSILON,
        ).optimize((public, taxi), DEPARTURE, constraints(budget=10_000))

        returned = by_candidate_key(result)
        self.assertIn("coarse-upper-taxi", returned)
        self.assertEqual(
            result.recommendations.fastest,
            returned["coarse-upper-taxi"].route_id,
        )

    def test_exact_candidate_cap_fails_closed_when_global_argmin_is_uncertified(self) -> None:
        caps = CandidateCaps(coarse_combinations=2, pre_pareto=2)
        candidates = tuple(
            seed(
                f"uncertified-{index}",
                "TAXI_ONLY",
                ("TAXI",),
                coarse_p50=index,
            )
            for index in range(3)
        )
        evaluator = StaticLegEvaluator(
            {
                f"uncertified-{index}-0": cost(300 - index, 300 - index)
                for index in range(3)
            }
        )

        with self.assertRaisesRegex(ValueError, "EXACT_CANDIDATE_CAP_UNCERTIFIED"):
            RouteOptimizer(evaluator, caps=caps, epsilon=ZERO_EPSILON).optimize(
                candidates, DEPARTURE, constraints()
            )


class RI390ChronologyTests(unittest.TestCase):
    def test_taxi_bus_walk_topology_can_be_the_actual_fastest(self) -> None:
        taxi_bus_walk = seed(
            "taxi-bus-walk",
            "TAXI_TRANSIT",
            ("TAXI", "BUS", "WALK"),
            coarse_p50=1_000,
            coarse_taxi_upper=4_000,
            bus_waits=(None, BusWaitContribution(120, 300), None),
        )
        public = seed("taxi-bus-walk-public", "TRANSIT_ONLY", ("BUS",), coarse_p50=2_000)
        result = RouteOptimizer(
            StaticLegEvaluator(
                {
                    "taxi-bus-walk-0": cost(
                        240,
                        360,
                        wait_p50=120,
                        wait_p90=240,
                        taxi_upper=4_000,
                    ),
                    "taxi-bus-walk-1": cost(600, 780),
                    "taxi-bus-walk-2": cost(120, 180),
                    "taxi-bus-walk-public-0": cost(1_500, 1_800),
                }
            ),
            epsilon=ZERO_EPSILON,
        ).optimize((public, taxi_bus_walk), DEPARTURE, constraints())

        returned = by_candidate_key(result)
        selected = returned["taxi-bus-walk"]
        self.assertEqual(result.recommendations.fastest, selected.route_id)
        self.assertEqual(tuple(leg.mode for leg in selected.legs), ("TAXI", "BUS", "WALK"))
        self.assertEqual(selected.total_duration.p50_seconds, 1_200)

    def test_fast_drive_loses_after_dispatch_wait_is_included(self) -> None:
        taxi = seed(
            "dispatch-taxi",
            "TAXI_ONLY",
            ("TAXI",),
            coarse_taxi_upper=5_000,
        )
        public = seed("dispatch-public", "TRANSIT_ONLY", ("BUS",))
        result = RouteOptimizer(
            StaticLegEvaluator(
                {
                    "dispatch-taxi-0": cost(
                        200,
                        240,
                        wait_p50=700,
                        wait_p90=900,
                        taxi_upper=5_000,
                    ),
                    "dispatch-public-0": cost(800, 900),
                }
            ),
            epsilon=ZERO_EPSILON,
        ).optimize((taxi, public), DEPARTURE, constraints())

        returned = by_candidate_key(result)
        self.assertLess(200, returned["dispatch-public"].total_duration.p50_seconds)
        self.assertEqual(
            result.recommendations.fastest,
            returned["dispatch-public"].route_id,
        )

    def test_seat_proxy_next_vehicle_wait_reverses_the_winner(self) -> None:
        bus = seed("seat-bus", "TRANSIT_ONLY", ("BUS",))
        delayed_bus = replace(
            bus,
            candidate_key="seat-bus-delayed",
            legs=(replace(bus.legs[0], bus_wait=BusWaitContribution(600, 1_200)),),
        )
        alternative = seed("seat-subway", "TRANSIT_ONLY", ("SUBWAY",))
        evaluator = StaticLegEvaluator(
            {
                "seat-bus-0": cost(600, 720),
                "seat-subway-0": cost(900, 1_000),
            }
        )
        raw = RouteOptimizer(evaluator, epsilon=ZERO_EPSILON).optimize(
            (bus, alternative), DEPARTURE, constraints()
        )
        enriched = RouteOptimizer(evaluator, epsilon=ZERO_EPSILON).optimize(
            (delayed_bus, alternative), DEPARTURE, constraints()
        )

        self.assertEqual(raw.recommendations.fastest, by_candidate_key(raw)["seat-bus"].route_id)
        self.assertEqual(
            enriched.recommendations.fastest,
            by_candidate_key(enriched)["seat-subway"].route_id,
        )

    def test_p50_catch_and_p90_miss_uses_next_service_instead_of_rejecting_route(self) -> None:
        connection = seed(
            "connection",
            "TRANSIT_ONLY",
            ("BUS", "SUBWAY"),
            transfer_requirements=(TransferRequirement(), TransferRequirement(60, 120)),
            scheduled_departures=(None, DEPARTURE + timedelta(seconds=1_000)),
        )

        evaluated = CandidateEvaluator(ScheduledConnectionEvaluator()).evaluate(
            connection, DEPARTURE
        )

        second = evaluated.legs[1]
        self.assertEqual(second.start_at_p50, DEPARTURE + timedelta(seconds=1_000))
        self.assertEqual(second.start_at_p90, DEPARTURE + timedelta(seconds=1_600))
        self.assertEqual(evaluated.total_duration, TimeEstimate(1_400, 2_100))
        self.assertIn("TRANSFER_MARGIN_LOW", evaluated.warning_codes)

    def test_connector_walk_p50_miss_uses_explicit_next_service_evidence(self) -> None:
        connection = seed(
            "connection",
            "TRANSIT_ONLY",
            ("BUS", "SUBWAY"),
            transfer_requirements=(
                TransferRequirement(),
                TransferRequirement(400, 400, connector_walk_seconds=400),
            ),
            scheduled_departures=(None, DEPARTURE + timedelta(seconds=1_000)),
        )

        evaluated = CandidateEvaluator(ScheduledConnectionEvaluator()).evaluate(
            connection, DEPARTURE
        )

        second = evaluated.legs[1]
        self.assertIsNotNone(second.transfer_margin)
        assert second.transfer_margin is not None
        self.assertEqual(second.transfer_margin.p50_seconds, -100)
        self.assertEqual(second.start_at_p50, DEPARTURE + timedelta(seconds=1_600))
        self.assertEqual(second.start_at_p90, DEPARTURE + timedelta(seconds=1_600))
        self.assertEqual(evaluated.total_duration, TimeEstimate(2_000, 2_100))
        self.assertEqual(evaluated.walk_seconds, 400)

    def test_scheduled_miss_without_explicit_next_service_evidence_fails_closed(self) -> None:
        connection = seed(
            "missing-next-service",
            "TRANSIT_ONLY",
            ("BUS", "SUBWAY"),
            transfer_requirements=(
                TransferRequirement(),
                TransferRequirement(400, 400, connector_walk_seconds=400),
            ),
            scheduled_departures=(None, DEPARTURE + timedelta(seconds=1_000)),
        )
        evaluator = StaticLegEvaluator(
            {
                "missing-next-service-0": cost(700, 900),
                "missing-next-service-1": cost(400, 500),
            }
        )

        with self.assertRaisesRegex(CandidateEvaluationError, "TRANSFER_INFEASIBLE"):
            CandidateEvaluator(evaluator).evaluate(connection, DEPARTURE)

    def test_non_fifo_next_service_quantiles_fail_closed_without_phantom_clamping(self) -> None:
        connection = seed(
            "non-fifo",
            "TRANSIT_ONLY",
            ("BUS", "SUBWAY"),
            transfer_requirements=(
                TransferRequirement(),
                TransferRequirement(400, 400, connector_walk_seconds=400),
            ),
            scheduled_departures=(None, DEPARTURE + timedelta(seconds=1_000)),
        )

        with self.assertRaises(CandidateEvaluationError):
            CandidateEvaluator(NonFifoNextServiceEvaluator()).evaluate(
                connection, DEPARTURE
            )

    def test_scheduled_bus_does_not_double_count_schedule_margin_and_bus_wait(self) -> None:
        scheduled_bus = seed(
            "scheduled-bus",
            "TRANSIT_ONLY",
            ("BUS",),
            scheduled_departures=(DEPARTURE + timedelta(seconds=300),),
            bus_waits=(BusWaitContribution(300, 900),),
        )
        evaluated = CandidateEvaluator(
            StaticLegEvaluator({"scheduled-bus-0": cost(600, 900)})
        ).evaluate(scheduled_bus, DEPARTURE)

        self.assertEqual(evaluated.legs[0].start_at_p50, DEPARTURE + timedelta(seconds=300))
        self.assertEqual(evaluated.legs[0].start_at_p90, DEPARTURE + timedelta(seconds=900))
        self.assertEqual(evaluated.total_duration, TimeEstimate(900, 1_800))

    def test_authoritative_bus_wait_makes_schedule_offset_irrelevant_to_time_and_risk(self) -> None:
        observed = []
        for offset in (300, 60, -60):
            scheduled_bus = seed(
                f"bus-wait-offset-{offset}",
                "TRANSIT_ONLY",
                ("BUS",),
                scheduled_departures=(DEPARTURE + timedelta(seconds=offset),),
                bus_waits=(BusWaitContribution(300, 900),),
            )
            evaluated = CandidateEvaluator(
                StaticLegEvaluator(
                    {f"bus-wait-offset-{offset}-0": cost(600, 900)}
                )
            ).evaluate(scheduled_bus, DEPARTURE)
            observed.append(
                (
                    evaluated.total_duration,
                    evaluated.transfer_risk,
                    evaluated.warning_codes,
                )
            )

        self.assertEqual(
            observed,
            [(TimeEstimate(900, 1_800), 0.0, ())] * 3,
        )

    def test_connector_transfer_time_is_subject_to_max_walk_constraint(self) -> None:
        connector = seed(
            "connector-walk",
            "TRANSIT_ONLY",
            ("BUS", "SUBWAY"),
            transfer_requirements=(
                TransferRequirement(),
                TransferRequirement(300, 360, connector_walk_seconds=300),
            ),
            scheduled_departures=(None, DEPARTURE + timedelta(seconds=1_000)),
        )
        result = RouteOptimizer(
            StaticLegEvaluator(
                {
                    "connector-walk-0": cost(100, 120),
                    "connector-walk-1": cost(300, 360),
                }
            ),
            epsilon=ZERO_EPSILON,
        ).optimize((connector,), DEPARTURE, constraints(max_walk=299))

        self.assertFalse(result.routes)
        self.assertIn("MAX_WALK", {item.reason for item in result.rejected})

    def test_traffic_incident_context_reverses_the_winner(self) -> None:
        taxi = seed(
            "context-taxi",
            "TAXI_ONLY",
            ("TAXI",),
            coarse_taxi_upper=5_000,
        )
        public = seed("context-public", "TRANSIT_ONLY", ("BUS",))
        normal = RouteOptimizer(
            ContextualEvaluator(incident=False), epsilon=ZERO_EPSILON
        ).optimize((taxi, public), DEPARTURE, constraints())
        incident = RouteOptimizer(
            ContextualEvaluator(incident=True), epsilon=ZERO_EPSILON
        ).optimize((taxi, public), DEPARTURE, constraints())

        self.assertEqual(
            normal.recommendations.fastest,
            by_candidate_key(normal)["context-taxi"].route_id,
        )
        self.assertEqual(
            incident.recommendations.fastest,
            by_candidate_key(incident)["context-public"].route_id,
        )

    def test_egress_walk_prevents_wrong_core_only_winner(self) -> None:
        multimodal = seed(
            "egress-multimodal",
            "TAXI_TRANSIT",
            ("TAXI", "BUS", "WALK"),
            coarse_taxi_upper=3_000,
        )
        public = seed("egress-public", "TRANSIT_ONLY", ("BUS",))
        result = RouteOptimizer(
            StaticLegEvaluator(
                {
                    "egress-multimodal-0": cost(100, 120, taxi_upper=3_000),
                    "egress-multimodal-1": cost(500, 600),
                    "egress-multimodal-2": cost(500, 600),
                    "egress-public-0": cost(1_000, 1_100),
                }
            ),
            epsilon=ZERO_EPSILON,
        ).optimize((multimodal, public), DEPARTURE, constraints())

        returned = by_candidate_key(result)
        self.assertLess(600, returned["egress-public"].total_duration.p50_seconds)
        self.assertEqual(
            result.recommendations.fastest,
            returned["egress-public"].route_id,
        )

    def test_multiple_taxi_upper_sum_accepts_exact_boundary_and_rejects_one_won_over(self) -> None:
        at_boundary = seed(
            "two-taxi-boundary",
            "TAXI_TRANSIT_TAXI",
            ("TAXI", "BUS", "TAXI"),
            coarse_taxi_upper=10_000,
        )
        evaluator = StaticLegEvaluator(
            {
                "two-taxi-boundary-0": cost(100, 120, taxi_upper=5_000),
                "two-taxi-boundary-1": cost(300, 360),
                "two-taxi-boundary-2": cost(100, 120, taxi_upper=5_000),
            }
        )
        accepted = RouteOptimizer(evaluator, epsilon=ZERO_EPSILON).optimize(
            (at_boundary,), DEPARTURE, constraints(budget=10_000)
        )
        self.assertEqual(accepted.routes[0].taxi_cost.upper_krw, 10_000)

        over_costs = dict(evaluator.costs)
        over_costs["two-taxi-boundary-2"] = cost(100, 120, taxi_upper=5_001)
        rejected = RouteOptimizer(
            StaticLegEvaluator(over_costs), epsilon=ZERO_EPSILON
        ).optimize((at_boundary,), DEPARTURE, constraints(budget=10_000))
        self.assertFalse(rejected.routes)
        self.assertIn("STRICT_TAXI_BUDGET", {item.reason for item in rejected.rejected})

if __name__ == "__main__":
    unittest.main()
