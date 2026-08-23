from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from routing_domain.evaluators import StaticLegEvaluator
from routing_domain.models import CandidateSeed, LegCost, LegSpec, MoneyRange, RouteConstraints, TimeEstimate
from routing_domain.optimizer import RouteOptimizer
from routing_domain.pareto import exactly_dominates
from routing_domain.policy import EpsilonPolicy
from routing_domain.replay_fixtures import build_r1_r4_scenarios


KST = timezone(timedelta(hours=9))
DEPARTURE = datetime(2026, 8, 23, 7, 0, tzinfo=KST)


def leg_cost(p50: int, p90: int, fare_upper: int = 0, reliability: float = 1.0) -> LegCost:
    return LegCost(
        TimeEstimate(0, 0),
        TimeEstimate(p50, p90),
        MoneyRange(int(fare_upper * 0.9), int(fare_upper * 0.8), fare_upper),
        reliability,
    )


def candidate(key: str, pattern: str, modes: tuple[str, ...], coarse_upper: int = 0) -> CandidateSeed:
    legs = tuple(
        LegSpec(f"{key}-{index}", mode, f"{key}-{index}", f"{key}-{index + 1}", f"{key}-{index}")
        for index, mode in enumerate(modes)
    )
    return CandidateSeed(key, pattern, legs, max(0, sum(mode in {"BUS", "SUBWAY", "GTX", "TRAIN"} for mode in modes) - 1), 1000, coarse_upper)


def constraints(budget: int = 20_000, strict: bool = True) -> RouteConstraints:
    return RouteConstraints(budget, strict, 2000, 4, 3, frozenset({"WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"}), True)


class OptimizerTests(unittest.TestCase):
    def test_sum_of_every_taxi_upper_is_strict_budget_basis(self) -> None:
        seed = candidate("two-taxi", "TAXI_TRANSIT_TAXI", ("TAXI", "BUS", "TAXI"), coarse_upper=10_000)
        evaluator = StaticLegEvaluator(
            {
                "two-taxi-0": leg_cost(300, 400, 6_000),
                "two-taxi-1": leg_cost(900, 1200, 0),
                "two-taxi-2": leg_cost(300, 400, 6_000),
            }
        )
        result = RouteOptimizer(evaluator).optimize((seed,), DEPARTURE, constraints(10_000))
        self.assertEqual(result.routes, ())
        self.assertIn("STRICT_TAXI_BUDGET", {item.reason for item in result.rejected})

    def test_budget_is_upper_bound_even_when_request_strict_flag_is_false(self) -> None:
        seed = candidate("taxi", "TAXI_ONLY", ("TAXI",), coarse_upper=10_000)
        result = RouteOptimizer(StaticLegEvaluator({"taxi-0": leg_cost(300, 400, 12_000)})).optimize(
            (seed,), DEPARTURE, constraints(10_000, strict=False)
        )
        self.assertFalse(result.routes)

    def test_pareto_and_four_rankings_are_deterministic(self) -> None:
        seeds = (
            candidate("public", "TRANSIT_ONLY", ("BUS",)),
            candidate("fast", "TAXI_ONLY", ("TAXI",), 10_000),
            candidate("stable", "TAXI_ONLY", ("TAXI",), 8_000),
            candidate("efficient", "TAXI_ONLY", ("TAXI",), 2_000),
        )
        evaluator = StaticLegEvaluator(
            {
                "public-0": leg_cost(3600, 5000, 0, 0.8),
                "fast-0": leg_cost(2400, 4200, 10_000, 0.7),
                "stable-0": leg_cost(3000, 3400, 8_000, 0.99),
                "efficient-0": leg_cost(3200, 4500, 2_000, 0.9),
            }
        )
        optimizer = RouteOptimizer(evaluator, epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0))
        first = optimizer.optimize(seeds, DEPARTURE, constraints())
        second = optimizer.optimize(tuple(reversed(seeds)), DEPARTURE, constraints())
        self.assertEqual(first, second)
        by_key = {item.candidate_key: item for item in first.routes}
        self.assertEqual(first.recommendations.fastest, by_key["fast"].route_id)
        self.assertEqual(first.recommendations.stable, by_key["stable"].route_id)
        self.assertEqual(first.recommendations.efficient, by_key["fast"].route_id)
        self.assertEqual(first.recommendations.public_transit_only, by_key["public"].route_id)
        self.assertIn("FASTER_THAN_PUBLIC_TRANSIT", by_key["fast"].reason_codes)
        self.assertIn("LOWER_P90_ARRIVAL_TIME", by_key["stable"].reason_codes)
        self.assertIn("BEST_MARGINAL_TIME_SAVING", by_key["fast"].reason_codes)
        returned = {item.route_id for item in first.routes}
        self.assertTrue(set(first.pareto_route_ids) <= returned)
        self.assertTrue(
            all(
                recommendation in returned
                for recommendation in (
                    first.recommendations.fastest,
                    first.recommendations.stable,
                    first.recommendations.efficient,
                    first.recommendations.public_transit_only,
                )
            )
        )
        self.assertFalse(
            any(
                exactly_dominates(left, right)
                for left in first.routes
                for right in first.routes
                if left is not right
            )
        )

    def test_fastest_tie_prefers_reliability_before_p90(self) -> None:
        reliable = candidate("reliable", "TAXI_ONLY", ("TAXI",), 1_000)
        low_p90 = candidate("low-p90", "TAXI_ONLY", ("TAXI",), 1_000)
        evaluator = StaticLegEvaluator(
            {
                "reliable-0": leg_cost(1000, 2000, 1_000, 0.99),
                "low-p90-0": leg_cost(1000, 1100, 1_000, 0.8),
            }
        )
        result = RouteOptimizer(
            evaluator,
            epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0),
        ).optimize((low_p90, reliable), DEPARTURE, constraints())
        by_key = {item.candidate_key: item for item in result.routes}
        self.assertEqual(result.recommendations.fastest, by_key["reliable"].route_id)

    def test_efficient_uses_successive_marginal_gain_not_public_average(self) -> None:
        seeds = (
            candidate("public-marginal", "TRANSIT_ONLY", ("BUS",)),
            candidate("tier-1", "TAXI_ONLY", ("TAXI",), 10),
            candidate("tier-2", "TAXI_ONLY", ("TAXI",), 1_000),
            candidate("tier-3", "TAXI_ONLY", ("TAXI",), 1_010),
        )
        evaluator = StaticLegEvaluator(
            {
                "public-marginal-0": leg_cost(1000, 2500, 0, 0.5),
                "tier-1-0": leg_cost(900, 2000, 10, 0.5),
                "tier-2-0": leg_cost(900, 1000, 1_000, 0.95),
                "tier-3-0": leg_cost(790, 900, 1_010, 0.8),
            }
        )
        result = RouteOptimizer(
            evaluator,
            epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0),
        ).optimize(seeds, DEPARTURE, constraints())
        by_key = {item.candidate_key: item for item in result.routes}
        # Public-average would select tier-1 (100/10); successive marginal
        # selects tier-3 ((900-790)/(1010-1000)).
        self.assertEqual(result.recommendations.efficient, by_key["tier-3"].route_id)

    def test_efficient_no_positive_gain_returns_public_without_threshold(self) -> None:
        public = candidate("public-no-gain", "TRANSIT_ONLY", ("BUS",))
        safer_taxi = candidate("safer-no-gain", "TAXI_ONLY", ("TAXI",), 100)
        evaluator = StaticLegEvaluator(
            {
                "public-no-gain-0": leg_cost(1000, 1200, 0, 0.8),
                "safer-no-gain-0": leg_cost(1100, 1100, 100, 0.99),
            }
        )
        result = RouteOptimizer(
            evaluator,
            epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0),
        ).optimize((safer_taxi, public), DEPARTURE, constraints())
        by_key = {item.candidate_key: item for item in result.routes}
        selected = by_key["public-no-gain"]
        self.assertEqual(result.recommendations.efficient, selected.route_id)
        self.assertIn("NO_MEANINGFUL_GAIN_FROM_MORE_BUDGET", selected.reason_codes)

    def test_exactly_dominated_candidate_is_removed_with_nonzero_epsilon(self) -> None:
        better = candidate("better", "TRANSIT_ONLY", ("BUS",))
        worse = candidate("worse", "TRANSIT_ONLY", ("BUS",))
        evaluator = StaticLegEvaluator({"better-0": leg_cost(1000, 1200), "worse-0": leg_cost(1010, 1210)})
        result = RouteOptimizer(evaluator).optimize((better, worse), DEPARTURE, constraints())
        self.assertEqual(result.counts.pareto, 1)

    def test_r1_r4_fixture_builders_are_replay_stable(self) -> None:
        scenarios = build_r1_r4_scenarios()
        self.assertEqual(tuple(item.replay_id for item in scenarios), ("R1", "R2", "R3", "R4"))
        for scenario in scenarios:
            optimizer = RouteOptimizer(scenario.evaluator)
            first = optimizer.optimize(scenario.seeds, scenario.departure_at, scenario.constraints)
            second = optimizer.optimize(scenario.seeds, scenario.departure_at, scenario.constraints)
            self.assertEqual(first, second)
            self.assertIsNotNone(first.recommendations.public_transit_only)
            self.assertTrue(all(route.total_duration.p90_seconds >= route.total_duration.p50_seconds for route in first.routes))
            self.assertTrue(all(route.taxi_cost.upper_krw <= scenario.constraints.taxi_budget_krw for route in first.routes))
            for route in first.routes:
                for previous, current in zip(route.legs, route.legs[1:]):
                    self.assertGreaterEqual(current.ready_at_p50, previous.end_at_p50)
                    self.assertGreaterEqual(current.ready_at_p90, previous.end_at_p90)


if __name__ == "__main__":
    unittest.main()
