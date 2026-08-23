from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from routing_domain.models import EvaluatedCandidate, MoneyRange, TimeEstimate
from routing_domain.pareto import epsilon_dominates, exactly_dominates, pareto_frontier
from routing_domain.policy import EpsilonPolicy, RankingPolicy


KST = timezone(timedelta(hours=9))
DEPARTURE = datetime(2026, 8, 23, 7, 0, tzinfo=KST)


def route(
    route_id: str,
    p50: int,
    p90: int,
    taxi_upper: int,
    *,
    walk: int = 0,
    risk: float = 0.0,
) -> EvaluatedCandidate:
    return EvaluatedCandidate(
        route_id=route_id,
        candidate_key=route_id,
        pattern="TRANSIT_ONLY" if taxi_upper == 0 else "TAXI_ONLY",
        topology_key=(("BUS", route_id, f"{route_id}-to", route_id),),
        departure_at=DEPARTURE,
        arrival_at_p50=DEPARTURE + timedelta(seconds=p50),
        arrival_at_p90=DEPARTURE + timedelta(seconds=p90),
        total_duration=TimeEstimate(p50, p90),
        taxi_cost=MoneyRange(taxi_upper, taxi_upper, taxi_upper),
        total_fare_expected_krw=taxi_upper,
        walk_seconds=walk,
        transfer_count=0,
        taxi_leg_count=int(taxi_upper > 0),
        reliability_score=1.0 - risk,
        transfer_risk=risk,
        legs=(),
    )


class ParetoCycleSafetyTests(unittest.TestCase):
    def test_three_way_epsilon_cycle_keeps_one_deterministic_representative(self) -> None:
        # Valid P90>=P50 form of the cycle: A→B, B→C, C→A under defaults.
        a = route("A", 0, 90, 200)
        b = route("B", 60, 60, 100)
        c = route("C", 30, 150, 0)
        epsilon = EpsilonPolicy()
        self.assertTrue(epsilon_dominates(a, b, epsilon))
        self.assertTrue(epsilon_dominates(b, c, epsilon))
        self.assertTrue(epsilon_dominates(c, a, epsilon))

        forward = pareto_frontier((a, b, c), epsilon)
        reverse = pareto_frontier((c, b, a), epsilon)
        self.assertEqual(forward, reverse)
        self.assertEqual(tuple(item.route_id for item in forward), ("A",))

    def test_nonempty_exact_frontier_cannot_be_erased_by_epsilon(self) -> None:
        candidates = (
            route("A", 0, 90, 200),
            route("B", 60, 60, 100),
            route("C", 30, 150, 0),
        )
        self.assertTrue(pareto_frontier(candidates, EpsilonPolicy()))

    def test_output_never_contains_an_exactly_dominated_route(self) -> None:
        candidates = (
            route("better", 100, 150, 0),
            route("dominated", 120, 180, 100),
            route("tradeoff", 80, 220, 200),
        )
        frontier = pareto_frontier(candidates, EpsilonPolicy())
        self.assertFalse(
            any(
                exactly_dominates(left, right)
                for left in frontier
                for right in frontier
                if left is not right
            )
        )
        self.assertNotIn("dominated", {item.route_id for item in frontier})

    def test_zero_epsilon_equals_exact_pareto_and_versions_are_explicit(self) -> None:
        candidates = (
            route("better", 100, 150, 0),
            route("dominated", 120, 180, 100),
            route("tradeoff", 80, 220, 200),
        )
        expected = tuple(
            candidate
            for candidate in sorted(candidates, key=lambda item: (item.route_id, item.candidate_key))
            if not any(
                other is not candidate and exactly_dominates(other, candidate)
                for other in candidates
            )
        )
        zero = EpsilonPolicy(0, 0, 0, 0, 0.0)
        self.assertEqual(
            {item.route_id for item in pareto_frontier(candidates, zero)},
            {item.route_id for item in expected},
        )
        self.assertEqual(zero.representative_policy_version, "epsilon-scc-lexicographic-1.0.0")
        self.assertEqual(RankingPolicy().version, "rank-0.2.0")


if __name__ == "__main__":
    unittest.main()
