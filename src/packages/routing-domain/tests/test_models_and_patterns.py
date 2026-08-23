from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from routing_domain.candidate_generation import BoundedCandidateGenerator
from routing_domain.models import BusWaitContribution, CandidateSeed, LegSpec, MoneyRange, RouteConstraints, TimeEstimate
from routing_domain.policy import CandidateCaps, ProviderCallBudget


KST = timezone(timedelta(hours=9))


def leg(leg_id: str, mode: str, start: str, end: str) -> LegSpec:
    return LegSpec(leg_id, mode, start, end, leg_id)


def seed(key: str, pattern: str, legs: tuple[LegSpec, ...], transfers: int = 0) -> CandidateSeed:
    return CandidateSeed(key, pattern, legs, transfers, 1000, 0)


class ValueObjectTests(unittest.TestCase):
    def test_p90_and_money_invariants(self) -> None:
        with self.assertRaises(ValueError):
            TimeEstimate(10, 9)
        with self.assertRaises(ValueError):
            MoneyRange(100, 101, 120)
        with self.assertRaises(ValueError):
            LegSpec("bus", "BUS", "a", "b", "bus", scheduled_departure_at=datetime(2026, 1, 1))

    def test_route_id_is_deterministic_from_topology(self) -> None:
        first = seed("provider-a", "TRANSIT_ONLY", (leg("bus-a", "BUS", "a", "b"),))
        second = seed("provider-b", "TRANSIT_ONLY", (leg("bus-b", "BUS", "a", "b"),))
        self.assertEqual(first.route_id, second.route_id)

    def test_topology_ref_distinguishes_lines_sharing_endpoints(self) -> None:
        first = seed(
            "line-a",
            "TRANSIT_ONLY",
            (LegSpec("bus-a", "BUS", "a", "b", "bus-a", topology_ref="canonical-route-a"),),
        )
        second = seed(
            "line-b",
            "TRANSIT_ONLY",
            (LegSpec("bus-b", "BUS", "a", "b", "bus-b", topology_ref="canonical-route-b"),),
        )
        route_constraints = RouteConstraints(0, True, 1000, 3, 0, frozenset({"BUS"}))
        batch = BoundedCandidateGenerator().generate((first, second), route_constraints)
        self.assertEqual(len(batch.candidates), 2)
        self.assertNotEqual(first.topology_key, second.topology_key)
        self.assertNotEqual(first.route_id, second.route_id)
        with self.assertRaises(ValueError):
            LegSpec("blank", "BUS", "a", "b", "blank", topology_ref="  ")

    def test_all_allowed_patterns_validate(self) -> None:
        cases = (
            seed("p1", "TRANSIT_ONLY", (leg("b1", "BUS", "a", "b"),)),
            seed("p2", "TAXI_TRANSIT", (leg("t2", "TAXI", "a", "b"), leg("b2", "BUS", "b", "c"))),
            seed("p3", "TRANSIT_TAXI", (leg("b3", "BUS", "a", "b"), leg("t3", "TAXI", "b", "c"))),
            seed("p4", "TAXI_TRANSIT_TAXI", (leg("ta4", "TAXI", "a", "b"), leg("b4", "BUS", "b", "c"), leg("tb4", "TAXI", "c", "d"))),
            seed("p5", "TAXI_ONLY", (leg("t5", "TAXI", "a", "b"),)),
            seed("p6", "UPSTREAM_STOP_TAXI_TRANSIT", (leg("t6", "TAXI", "a", "upstream"), leg("b6", "BUS", "upstream", "c"))),
            seed("p7", "TRANSIT_TAXI_BRIDGE_TRANSIT", (leg("b7", "BUS", "a", "b"), leg("t7", "TAXI", "b", "c"), leg("s7", "SUBWAY", "c", "d")), 1),
        )
        constraints = RouteConstraints(20_000, True, 1000, 3, 2, frozenset({"WALK", "TAXI", "BUS", "SUBWAY"}), True)
        batch = BoundedCandidateGenerator().generate(cases, constraints)
        self.assertEqual(len(batch.candidates), len(cases))

    def test_pattern_mismatch_is_rejected(self) -> None:
        bad = seed("bad", "TRANSIT_ONLY", (leg("taxi", "TAXI", "a", "b"),))
        constraints = RouteConstraints(20_000, True, 1000, 3, 2, frozenset({"TAXI"}))
        batch = BoundedCandidateGenerator().generate((bad,), constraints)
        self.assertEqual(batch.rejected, (("bad", "PATTERN_INVALID"),))

    def test_candidate_and_provider_caps_are_hard(self) -> None:
        seeds = tuple(
            seed(f"p{index}", "TRANSIT_ONLY", (leg(f"b{index}", "BUS", f"a{index}", f"b{index}"),))
            for index in range(8)
        )
        caps = CandidateCaps(transit_baselines=3, pre_pareto=4, coarse_combinations=5, provider_calls=2)
        constraints = RouteConstraints(0, True, 1000, 3, 0, frozenset({"BUS"}))
        generator = BoundedCandidateGenerator(caps)
        with self.assertRaises(ValueError):
            generator.generate(seeds, constraints, provider_call_count=3)
        batch = generator.generate(seeds, constraints, provider_call_count=2)
        self.assertEqual(len(batch.candidates), 3)
        self.assertTrue(all(reason == "TRANSIT_BASELINE_CAP" for _, reason in batch.rejected))
        budget = ProviderCallBudget(limit=2).reserve().reserve()
        self.assertEqual(budget.consumed, 2)
        with self.assertRaises(ValueError):
            budget.reserve()

    def test_exact_taxi_and_bus_enrichment_caps_are_hard(self) -> None:
        taxi_seeds = tuple(
            seed(f"taxi-{index}", "TAXI_ONLY", (leg(f"t{index}", "TAXI", f"a{index}", f"b{index}"),))
            for index in range(3)
        )
        bus_seeds = tuple(
            seed(
                f"bus-{index}",
                "TRANSIT_ONLY",
                (
                    LegSpec(
                        f"bus-leg-{index}",
                        "BUS",
                        f"c{index}",
                        f"d{index}",
                        f"bus-cost-{index}",
                        bus_wait=BusWaitContribution(10, 20),
                    ),
                ),
            )
            for index in range(3)
        )
        caps = CandidateCaps(exact_taxi=2, bus_intelligence=2)
        route_constraints = RouteConstraints(20_000, True, 1000, 3, 2, frozenset({"TAXI", "BUS"}))
        batch = BoundedCandidateGenerator(caps).generate(taxi_seeds + bus_seeds, route_constraints)
        reasons = [reason for _, reason in batch.rejected]
        self.assertIn("EXACT_TAXI_CAP", reasons)
        self.assertIn("BUS_INTELLIGENCE_CAP", reasons)


if __name__ == "__main__":
    unittest.main()
