from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from routing_domain.evaluators import StaticLegEvaluator
from routing_domain.models import MoneyRange, RouteConstraints, TimeEstimate, TransferRequirement
from routing_domain.optimizer import RouteOptimizer
from routing_domain.policy import CandidateCaps, EpsilonPolicy
from routing_domain.strategy_generation import (
    AccessHub,
    BoundedStrategyGenerator,
    CanonicalTransitTopology,
    EgressHub,
    EnrichmentKind,
    EntryTimeBasis,
    QuoteReadiness,
    StrategyGenerationInput,
    StrategyGenerationPolicy,
    TaxiBridge,
    TaxiQuote,
    TransitBaseline,
    TransitLegInput,
    UpstreamHub,
    WalkQuote,
)


KST = timezone(timedelta(hours=9))
DEPARTURE = datetime(2026, 8, 24, 7, 0, tzinfo=KST)
ORIGIN = "origin"
DESTINATION = "destination"


def money(upper: int) -> MoneyRange:
    return MoneyRange(expected_krw=upper * 9 // 10, lower_krw=upper * 8 // 10, upper_krw=upper)


def topology(
    route: str,
    start: str,
    end: str,
    board_sequence: int,
    alight_sequence: int,
    *,
    direction: str = "OUTBOUND",
) -> CanonicalTransitTopology:
    return CanonicalTransitTopology(
        route_ref=route,
        direction=direction,
        board_stop_ref=start,
        alight_stop_ref=end,
        board_sequence=board_sequence,
        alight_sequence=alight_sequence,
    )


def transit(
    leg_id: str,
    mode: str,
    route: str,
    start: str,
    end: str,
    board_sequence: int,
    alight_sequence: int,
    seconds: int,
    *,
    scheduled: datetime | None = None,
    readiness: QuoteReadiness = QuoteReadiness.EXACT,
    mapping_ready: bool = True,
    bus_requested: bool = False,
) -> TransitLegInput:
    return TransitLegInput(
        leg_id=leg_id,
        mode=mode,
        topology=topology(route, start, end, board_sequence, alight_sequence),
        evaluator_key=f"cost:{leg_id}",
        duration=TimeEstimate(seconds, seconds + 120),
        lower_bound_seconds=max(0, seconds - 120),
        scheduled_departure_at=scheduled,
        readiness=readiness,
        mapping_ready=mapping_ready,
        bus_intelligence_requested=bus_requested,
    )


def taxi(
    quote_id: str,
    start: str,
    end: str,
    *,
    drive: int = 300,
    dispatch: int = 120,
    upper: int = 5_000,
    readiness: QuoteReadiness = QuoteReadiness.EXACT,
    topology_ref: str | None = None,
) -> TaxiQuote:
    return TaxiQuote(
        quote_id=quote_id,
        from_ref=start,
        to_ref=end,
        evaluator_key=f"cost:{quote_id}",
        dispatch_wait=TimeEstimate(dispatch, dispatch + 60),
        drive_duration=TimeEstimate(drive, drive + 120),
        fare=money(upper),
        distance_meters=3_000,
        lower_bound_dispatch_seconds=max(0, dispatch - 60),
        lower_bound_drive_seconds=max(0, drive - 120),
        readiness=readiness,
        topology_ref=topology_ref,
    )


def full_baseline(*, first_seconds: int = 900) -> TransitBaseline:
    return TransitBaseline(
        "full",
        (
            transit("full-bus", "BUS", "route-bus", ORIGIN, "hub-a", 10, 20, first_seconds),
            transit("full-subway", "SUBWAY", "line-s", "hub-a", "hub-b", 1, 8, 900),
            transit("full-train", "TRAIN", "line-t", "hub-b", DESTINATION, 3, 10, 900),
        ),
        coarse_risk=0.2,
    )


def constraints(*, budget: int = 20_000, bridge: bool = True) -> RouteConstraints:
    return RouteConstraints(
        taxi_budget_krw=budget,
        strict_taxi_budget=True,
        max_walk_seconds=3_600,
        max_transfers=5,
        max_taxi_legs=2,
        allowed_modes=frozenset({"WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"}),
        allow_taxi_bridge=bridge,
    )


def complete_inputs() -> StrategyGenerationInput:
    full = full_baseline()
    inbound = TransitBaseline(
        "bridge-in",
        (transit("bridge-in-bus", "BUS", "route-in", ORIGIN, "bridge-left", 1, 5, 600),),
    )
    outbound = TransitBaseline(
        "bridge-out",
        (transit("bridge-out-subway", "SUBWAY", "route-out", "bridge-right", DESTINATION, 2, 9, 600),),
    )
    upstream_leg = transit(
        "upstream-bus",
        "BUS",
        "route-bus",
        "upstream-stop",
        "hub-a",
        5,
        20,
        750,
    )
    return StrategyGenerationInput(
        origin_ref=ORIGIN,
        destination_ref=DESTINATION,
        departure_at=DEPARTURE,
        transit_baselines=(full, inbound, outbound),
        access_hubs=(AccessHub("access-a", "full", 1, taxi("access-taxi", ORIGIN, "hub-a")),),
        egress_hubs=(EgressHub("egress-b", "full", 1, taxi("egress-taxi", "hub-b", DESTINATION)),),
        upstream_hubs=(UpstreamHub("upstream", "full", 0, upstream_leg, taxi("upstream-taxi", ORIGIN, "upstream-stop")),),
        taxi_bridges=(TaxiBridge("bridge", "bridge-in", 0, "bridge-out", 0, taxi("bridge-taxi", "bridge-left", "bridge-right"), TransferRequirement(60, 120)),),
        taxi_only_quotes=(taxi("taxi-only", ORIGIN, DESTINATION, drive=1500, upper=15_000),),
    )


class StrategyGenerationTests(unittest.TestCase):
    def test_generates_all_seven_canonical_patterns(self) -> None:
        batch = BoundedStrategyGenerator().generate(complete_inputs(), constraints())
        self.assertEqual(
            {item.seed.pattern for item in batch.candidates},
            {
                "TRANSIT_ONLY",
                "TAXI_TRANSIT",
                "TRANSIT_TAXI",
                "TAXI_TRANSIT_TAXI",
                "TAXI_ONLY",
                "UPSTREAM_STOP_TAXI_TRANSIT",
                "TRANSIT_TAXI_BRIDGE_TRANSIT",
            },
        )
        self.assertEqual(batch.policy_version, "strategy-1.0.0")
        self.assertTrue(all(item.seed.coarse_taxi_upper_krw <= 20_000 for item in batch.candidates))

    def test_generation_is_deterministic_under_input_reversal(self) -> None:
        values = complete_inputs()
        reversed_values = replace(
            values,
            transit_baselines=tuple(reversed(values.transit_baselines)),
            access_hubs=tuple(reversed(values.access_hubs)),
            egress_hubs=tuple(reversed(values.egress_hubs)),
            upstream_hubs=tuple(reversed(values.upstream_hubs)),
            taxi_bridges=tuple(reversed(values.taxi_bridges)),
            taxi_only_quotes=tuple(reversed(values.taxi_only_quotes)),
        )
        generator = BoundedStrategyGenerator()
        self.assertEqual(generator.generate(values, constraints()), generator.generate(reversed_values, constraints()))

    def test_taxi_dispatch_wait_is_separate_from_drive_and_propagated(self) -> None:
        quote = taxi("separate", ORIGIN, DESTINATION, drive=600, dispatch=180, upper=10_000)
        batch = BoundedStrategyGenerator().generate(
            StrategyGenerationInput(ORIGIN, DESTINATION, DEPARTURE, (), taxi_only_quotes=(quote,)),
            constraints(),
        )
        cost = batch.costs()[quote.evaluator_key]
        self.assertEqual(cost.wait, TimeEstimate(180, 240))
        self.assertEqual(cost.travel, TimeEstimate(600, 720))
        route = RouteOptimizer(StaticLegEvaluator(batch.costs())).optimize(batch.seeds, DEPARTURE, constraints()).routes[0]
        self.assertEqual(route.legs[0].start_at_p50, DEPARTURE + timedelta(seconds=180))
        self.assertEqual(route.total_duration, TimeEstimate(780, 960))

    def test_upstream_same_route_direction_and_sequence_win_and_lose(self) -> None:
        baseline = TransitBaseline(
            "upstream-base",
            (transit("slow-bus", "BUS", "route-u", ORIGIN, DESTINATION, 10, 30, 2_400),),
        )
        valid_leg = transit("upstream-fast", "BUS", "route-u", "upstream", DESTINATION, 5, 30, 600)
        winning = StrategyGenerationInput(
            ORIGIN,
            DESTINATION,
            DEPARTURE,
            (baseline,),
            upstream_hubs=(UpstreamHub("valid", "upstream-base", 0, valid_leg, taxi("to-upstream", ORIGIN, "upstream", drive=240, dispatch=60)),),
        )
        batch = BoundedStrategyGenerator().generate(winning, constraints())
        result = RouteOptimizer(
            StaticLegEvaluator(batch.costs()), epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0)
        ).optimize(batch.seeds, DEPARTURE, constraints())
        selected = {item.route_id: item for item in result.routes}[result.recommendations.fastest]
        self.assertEqual(selected.pattern, "UPSTREAM_STOP_TAXI_TRANSIT")

        losing_quote = taxi("slow-to-upstream", ORIGIN, "upstream", drive=2_400, dispatch=600)
        losing = replace(
            winning,
            upstream_hubs=(UpstreamHub("slow", "upstream-base", 0, valid_leg, losing_quote),),
        )
        losing_batch = BoundedStrategyGenerator(
            policy=StrategyGenerationPolicy(coarse_time_slack_seconds=10_000)
        ).generate(losing, constraints())
        losing_result = RouteOptimizer(
            StaticLegEvaluator(losing_batch.costs()), epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0)
        ).optimize(losing_batch.seeds, DEPARTURE, constraints())
        fastest = {item.route_id: item for item in losing_result.routes}[losing_result.recommendations.fastest]
        self.assertEqual(fastest.pattern, "TRANSIT_ONLY")

        wrong_direction = replace(
            valid_leg,
            topology=topology("route-u", "upstream", DESTINATION, 5, 30, direction="INBOUND"),
        )
        invalid = replace(
            winning,
            upstream_hubs=(UpstreamHub("wrong", "upstream-base", 0, wrong_direction, taxi("wrong-taxi", ORIGIN, "upstream")),),
        )
        rejected = BoundedStrategyGenerator().generate(invalid, constraints()).rejected
        self.assertIn("UPSTREAM_ROUTE_DIRECTION_MISMATCH", {item.reason for item in rejected})

    def test_bridge_win_and_impossible_fixed_connection_loss(self) -> None:
        public = TransitBaseline(
            "public",
            (transit("public-slow", "BUS", "public-route", ORIGIN, DESTINATION, 1, 20, 3_000),),
        )
        inbound = TransitBaseline(
            "in",
            (transit("inbound", "BUS", "in-route", ORIGIN, "left", 1, 3, 360),),
        )
        outbound_leg = transit("outbound", "SUBWAY", "out-route", "right", DESTINATION, 2, 9, 480)
        outbound = TransitBaseline("out", (outbound_leg,))
        bridge = TaxiBridge("fast", "in", 0, "out", 0, taxi("cross", "left", "right", drive=180, dispatch=60), TransferRequirement(30, 60))
        inputs = StrategyGenerationInput(ORIGIN, DESTINATION, DEPARTURE, (public, inbound, outbound), taxi_bridges=(bridge,))
        batch = BoundedStrategyGenerator().generate(inputs, constraints())
        result = RouteOptimizer(
            StaticLegEvaluator(batch.costs()), epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0)
        ).optimize(batch.seeds, DEPARTURE, constraints())
        fastest = {item.route_id: item for item in result.routes}[result.recommendations.fastest]
        self.assertEqual(fastest.pattern, "TRANSIT_TAXI_BRIDGE_TRANSIT")

        impossible_leg = replace(outbound_leg, scheduled_departure_at=DEPARTURE + timedelta(seconds=100))
        impossible = replace(
            inputs,
            transit_baselines=(public, inbound, TransitBaseline("out", (impossible_leg,))),
        )
        rejected = BoundedStrategyGenerator().generate(impossible, constraints()).rejected
        self.assertIn("TAXI_BRIDGE_CONNECTION_INFEASIBLE", {item.reason for item in rejected})

    def test_budget_equal_upper_passes_and_one_won_over_is_pruned(self) -> None:
        at_limit = taxi("at-limit", ORIGIN, DESTINATION, upper=10_000, topology_ref="taxi:limit")
        over = taxi("over", ORIGIN, DESTINATION, upper=10_001, topology_ref="taxi:over")
        batch = BoundedStrategyGenerator().generate(
            StrategyGenerationInput(ORIGIN, DESTINATION, DEPARTURE, (), taxi_only_quotes=(over, at_limit)),
            constraints(budget=10_000),
        )
        self.assertEqual(tuple(item.seed.candidate_key for item in batch.candidates), ("taxi-only:at-limit",))
        self.assertIn("COARSE_TAXI_BUDGET", {item.reason for item in batch.rejected})

    def test_exact_enrichment_plan_is_typed_deduplicated_and_call_bounded(self) -> None:
        first = taxi("coarse-a", ORIGIN, DESTINATION, drive=200, readiness=QuoteReadiness.COARSE, topology_ref="taxi:a")
        second = taxi("coarse-b", ORIGIN, DESTINATION, drive=400, readiness=QuoteReadiness.COARSE, topology_ref="taxi:b")
        cap = CandidateCaps(provider_calls=1)
        batch = BoundedStrategyGenerator(caps=cap).generate(
            StrategyGenerationInput(ORIGIN, DESTINATION, DEPARTURE, (), taxi_only_quotes=(second, first)),
            constraints(),
        )
        self.assertEqual(batch.unique_provider_calls, 1)
        self.assertEqual(len(batch.exact_enrichment_plan), 1)
        self.assertEqual(len(batch.candidates), 1)
        self.assertEqual(batch.candidates[0].exact_enrichment[0].kind, EnrichmentKind.TAXI)
        self.assertIn("PROVIDER_CALL_CAP", {item.reason for item in batch.rejected})

    def test_exactification_plan_is_topological_and_entry_time_identifies_quotes(self) -> None:
        batch = BoundedStrategyGenerator().generate(complete_inputs(), constraints())
        plans = {item.candidate_key: item for item in batch.exactification_plan.candidates}
        public = plans["transit:full"]
        access = plans["access:access-a"]

        self.assertEqual(
            tuple(step.leg_sequence for step in public.steps),
            tuple(range(len(public.steps))),
        )
        self.assertIs(public.steps[0].entry_time_basis, EntryTimeBasis.REQUEST_DEPARTURE)
        self.assertTrue(
            all(
                following.entry_time_basis is EntryTimeBasis.PREDECESSOR_P50_END
                and following.predecessor_step_key == previous.step_key
                for previous, following in zip(public.steps, public.steps[1:])
            )
        )
        first_ready = public.steps[0].ready_at(DEPARTURE)
        second_ready = public.steps[1].ready_at(
            DEPARTURE,
            predecessor_p50_end_at=DEPARTURE + timedelta(seconds=900),
        )
        self.assertEqual(first_ready, DEPARTURE)
        self.assertEqual(second_ready, DEPARTURE + timedelta(seconds=900))
        with self.assertRaisesRegex(ValueError, "cannot precede departure"):
            public.steps[1].ready_at(
                DEPARTURE,
                predecessor_p50_end_at=DEPARTURE - timedelta(seconds=1),
            )

        public_shared = next(
            step
            for step in public.steps
            if (step.from_ref, step.to_ref) == ("hub-a", "hub-b")
        )
        access_shared = next(
            step
            for step in access.steps
            if (step.from_ref, step.to_ref) == ("hub-a", "hub-b")
        )
        early = DEPARTURE + timedelta(seconds=300)
        late = DEPARTURE + timedelta(seconds=900)
        self.assertEqual(
            public_shared.quote_identity(late),
            public_shared.quote_identity(late),
        )
        self.assertNotEqual(
            public_shared.quote_identity(early).quote_key,
            public_shared.quote_identity(late).quote_key,
        )
        self.assertEqual(
            public_shared.quote_identity(late).quote_key,
            access_shared.quote_identity(late).quote_key,
        )
        self.assertEqual(
            public_shared.quote_identity(late).quote_key,
            public_shared.quote_identity(late.astimezone(timezone.utc)).quote_key,
        )
        self.assertNotEqual(
            public_shared.quote_identity(late).quote_key,
            access_shared.quote_identity(early).quote_key,
        )
        self.assertEqual(
            {item.leg_sequence for item in batch.exactification_plan.ready_steps(())},
            {0},
        )
        with self.assertRaisesRegex(ValueError, "topological prefix"):
            public.ready_steps((public.steps[1].step_key,))

    def test_candidate_scoped_time_dependent_quotes_are_not_deduplicated_across_call_cap(self) -> None:
        walk = WalkQuote(
            quote_id="walk-to-stop",
            from_ref=ORIGIN,
            to_ref="shared-stop",
            evaluator_key="cost:walk-to-stop",
            duration=TimeEstimate(300, 360),
            distance_meters=350,
            lower_bound_seconds=240,
        )
        shared_bus = transit(
            "shared-coarse-bus",
            "BUS",
            "route-shared",
            "shared-stop",
            DESTINATION,
            1,
            10,
            900,
            readiness=QuoteReadiness.COARSE,
        )
        baseline = TransitBaseline("shared", (walk, shared_bus))
        inputs = StrategyGenerationInput(
            ORIGIN,
            DESTINATION,
            DEPARTURE,
            (baseline,),
            access_hubs=(
                AccessHub(
                    "shared-access",
                    "shared",
                    1,
                    taxi("shared-access-taxi", ORIGIN, "shared-stop"),
                ),
            ),
        )

        batch = BoundedStrategyGenerator(caps=CandidateCaps(provider_calls=1)).generate(
            inputs,
            constraints(),
        )

        self.assertEqual(batch.unique_provider_calls, 1)
        self.assertEqual(batch.exactification_plan.logical_provider_calls, 1)
        self.assertEqual(len(batch.candidates), 1)
        self.assertIn("PROVIDER_CALL_CAP", {item.reason for item in batch.rejected})

    def test_final_optimizer_revalidates_exact_chronology_transfer_budget_and_rankings(self) -> None:
        batch = BoundedStrategyGenerator().generate(complete_inputs(), constraints())
        exact = RouteOptimizer(
            StaticLegEvaluator(batch.costs()),
            epsilon=EpsilonPolicy(0, 0, 0, 0, 0.0),
        ).optimize(
            batch.seeds,
            DEPARTURE,
            constraints(),
            provider_call_count=batch.unique_provider_calls,
        )
        returned = {item.route_id: item for item in exact.routes}
        self.assertTrue(returned)
        self.assertTrue(
            all(
                previous.end_at_p50 <= following.ready_at_p50
                and previous.end_at_p90 <= following.ready_at_p90
                for route in exact.routes
                for previous, following in zip(route.legs, route.legs[1:])
            )
        )
        self.assertTrue(
            all(route.taxi_cost.upper_krw <= constraints().taxi_budget_krw for route in exact.routes)
        )
        recommendation_ids = {
            exact.recommendations.fastest,
            exact.recommendations.stable,
            exact.recommendations.efficient,
            exact.recommendations.public_transit_only,
        } - {None}
        self.assertLessEqual(recommendation_ids, set(returned))
        self.assertLessEqual(set(exact.pareto_route_ids), set(returned))
        public_id = exact.recommendations.public_transit_only
        self.assertIsNotNone(public_id)
        assert public_id is not None
        self.assertEqual(returned[public_id].taxi_cost.upper_krw, 0)

        dual_taxi = next(
            item.seed
            for item in batch.candidates
            if item.seed.pattern == "TAXI_TRANSIT_TAXI"
        )
        over_budget_costs = batch.costs()
        for leg in dual_taxi.legs:
            if leg.mode == "TAXI":
                original = over_budget_costs[leg.evaluator_key]
                over_budget_costs[leg.evaluator_key] = replace(
                    original,
                    fare=MoneyRange(5_500, 5_000, 6_000),
                )
        rejected = RouteOptimizer(StaticLegEvaluator(over_budget_costs)).optimize(
            (dual_taxi,),
            DEPARTURE,
            constraints(budget=10_000),
        )
        self.assertFalse(rejected.routes)
        self.assertIn("STRICT_TAXI_BUDGET", {item.reason for item in rejected.rejected})

        missed_transfer = replace(
            dual_taxi,
            candidate_key="exact-transfer-miss",
            pattern="TAXI_TRANSIT_TAXI",
            legs=tuple(
                replace(
                    leg,
                    scheduled_departure_at=DEPARTURE + timedelta(seconds=1),
                    transfer_requirement=TransferRequirement(60, 120),
                )
                if index == 1
                else leg
                for index, leg in enumerate(dual_taxi.legs)
            ),
        )
        transfer_rejected = RouteOptimizer(StaticLegEvaluator(batch.costs())).optimize(
            (missed_transfer,),
            DEPARTURE,
            constraints(),
        )
        self.assertIn(
            "TRANSFER_INFEASIBLE",
            {item.reason for item in transfer_rejected.rejected},
        )

    def test_bus_mapping_and_intelligence_requests_are_separate_and_shared(self) -> None:
        bus = transit(
            "needs-enrichment",
            "BUS",
            "route-e",
            ORIGIN,
            DESTINATION,
            1,
            10,
            900,
            mapping_ready=False,
            bus_requested=True,
        )
        baseline = TransitBaseline("needs-enrichment", (bus,))
        batch = BoundedStrategyGenerator().generate(
            StrategyGenerationInput(ORIGIN, DESTINATION, DEPARTURE, (baseline,)),
            constraints(),
        )
        self.assertEqual(
            {item.kind for item in batch.candidates[0].exact_enrichment},
            {EnrichmentKind.MAPPING, EnrichmentKind.BUS_INTELLIGENCE},
        )
        self.assertEqual(batch.unique_provider_calls, 2)

    def test_bus_exactification_orders_movement_mapping_and_intelligence(self) -> None:
        bus = transit(
            "coarse-bus-chain",
            "BUS",
            "route-chain",
            ORIGIN,
            DESTINATION,
            1,
            10,
            900,
            readiness=QuoteReadiness.COARSE,
            mapping_ready=False,
            bus_requested=True,
        )
        batch = BoundedStrategyGenerator().generate(
            StrategyGenerationInput(
                ORIGIN,
                DESTINATION,
                DEPARTURE,
                (TransitBaseline("coarse-bus-chain", (bus,)),),
            ),
            constraints(),
        )
        step = batch.exactification_plan.candidates[0].steps[0]
        self.assertEqual(
            tuple(item.kind for item in step.enrichment),
            (
                EnrichmentKind.TRANSIT,
                EnrichmentKind.MAPPING,
                EnrichmentKind.BUS_INTELLIGENCE,
            ),
        )
        self.assertEqual(
            step.enrichment[1].depends_on_request_keys,
            (step.enrichment[0].request_key,),
        )
        self.assertEqual(
            step.enrichment[2].depends_on_request_keys,
            (step.enrichment[1].request_key,),
        )

    def test_coarse_walk_quote_is_canonical_and_planned_for_exact_enrichment(self) -> None:
        walk = WalkQuote(
            quote_id="walk-access",
            from_ref=ORIGIN,
            to_ref="bus-stop",
            evaluator_key="cost:walk-access",
            duration=TimeEstimate(300, 420),
            distance_meters=350,
            lower_bound_seconds=240,
            readiness=QuoteReadiness.COARSE,
        )
        bus = transit("walk-bus", "BUS", "route-w", "bus-stop", DESTINATION, 1, 10, 900)
        batch = BoundedStrategyGenerator().generate(
            StrategyGenerationInput(
                ORIGIN,
                DESTINATION,
                DEPARTURE,
                (TransitBaseline("walk-baseline", (walk, bus)),),
            ),
            constraints(),
        )
        self.assertEqual(batch.candidates[0].seed.pattern, "TRANSIT_ONLY")
        self.assertEqual(batch.exact_enrichment_plan[0].kind, EnrichmentKind.WALK)
        self.assertEqual(batch.costs()[walk.evaluator_key].travel, TimeEstimate(300, 420))

    def test_duplicate_topology_and_hub_caps_are_deterministic(self) -> None:
        duplicate_a = taxi("provider-a", ORIGIN, DESTINATION, drive=300)
        duplicate_b = taxi("provider-b", ORIGIN, DESTINATION, drive=310)
        duplicate_batch = BoundedStrategyGenerator().generate(
            StrategyGenerationInput(ORIGIN, DESTINATION, DEPARTURE, (), taxi_only_quotes=(duplicate_b, duplicate_a)),
            constraints(),
        )
        self.assertEqual(len(duplicate_batch.candidates), 1)
        self.assertIn("DUPLICATE_TOPOLOGY", {item.reason for item in duplicate_batch.rejected})

        baseline = full_baseline()
        hubs = tuple(
            AccessHub(
                f"hub-{index:02d}",
                "full",
                1,
                taxi(
                    f"hub-taxi-{index:02d}",
                    ORIGIN,
                    "hub-a",
                    drive=100 + index,
                    topology_ref=f"taxi:hub-{index:02d}",
                ),
            )
            for index in range(20)
        )
        policy = StrategyGenerationPolicy(max_access_per_baseline=2)
        generator = BoundedStrategyGenerator(policy=policy)
        forward = generator.generate(
            StrategyGenerationInput(ORIGIN, DESTINATION, DEPARTURE, (baseline,), access_hubs=hubs),
            constraints(),
        )
        reverse = generator.generate(
            StrategyGenerationInput(ORIGIN, DESTINATION, DEPARTURE, (baseline,), access_hubs=tuple(reversed(hubs))),
            constraints(),
        )
        self.assertEqual(forward, reverse)
        self.assertEqual(sum(item.seed.pattern == "TAXI_TRANSIT" for item in forward.candidates), 2)
        self.assertEqual(sum(item.reason == "ACCESS_HUB_CAP" for item in forward.rejected), 18)

    def test_upstream_options_are_bounded_per_canonical_route(self) -> None:
        baseline = TransitBaseline(
            "upstream-cap-base",
            (transit("cap-base", "BUS", "route-cap", ORIGIN, DESTINATION, 20, 40, 1_200),),
        )
        options = tuple(
            UpstreamHub(
                f"up-{index}",
                "upstream-cap-base",
                0,
                transit(
                    f"up-leg-{index}",
                    "BUS",
                    "route-cap",
                    f"up-stop-{index}",
                    DESTINATION,
                    index + 1,
                    40,
                    900,
                ),
                taxi(
                    f"up-taxi-{index}",
                    ORIGIN,
                    f"up-stop-{index}",
                    drive=100 + index,
                    topology_ref=f"taxi:up-{index}",
                ),
            )
            for index in range(6)
        )
        batch = BoundedStrategyGenerator(caps=CandidateCaps(upstream_per_route=2)).generate(
            StrategyGenerationInput(
                ORIGIN,
                DESTINATION,
                DEPARTURE,
                (baseline,),
                upstream_hubs=tuple(reversed(options)),
            ),
            constraints(),
        )
        self.assertEqual(
            sum(item.seed.pattern == "UPSTREAM_STOP_TAXI_TRANSIT" for item in batch.candidates),
            2,
        )
        self.assertEqual(
            sum(item.reason == "UPSTREAM_PER_ROUTE_CAP" for item in batch.rejected),
            4,
        )

    def test_coarse_time_bound_prevents_unbounded_slow_options(self) -> None:
        baseline = TransitBaseline(
            "quick-public",
            (transit("quick", "BUS", "quick-route", ORIGIN, DESTINATION, 1, 2, 600),),
        )
        slow = taxi("very-slow", ORIGIN, DESTINATION, drive=20_000, dispatch=1_000, topology_ref="taxi:slow")
        batch = BoundedStrategyGenerator(
            policy=StrategyGenerationPolicy(coarse_time_slack_seconds=300)
        ).generate(
            StrategyGenerationInput(ORIGIN, DESTINATION, DEPARTURE, (baseline,), taxi_only_quotes=(slow,)),
            constraints(),
        )
        self.assertEqual({item.seed.pattern for item in batch.candidates}, {"TRANSIT_ONLY"})
        self.assertIn("COARSE_TIME_BOUND", {item.reason for item in batch.rejected})

    def test_candidate_and_call_bounds_hold_across_dense_input_sizes(self) -> None:
        caps = CandidateCaps(
            coarse_combinations=12,
            pre_pareto=7,
            exact_taxi=6,
            provider_calls=4,
        )
        generator = BoundedStrategyGenerator(
            caps=caps,
            policy=StrategyGenerationPolicy(max_taxi_only=50),
        )
        for size in (1, 4, 10, 50):
            quotes = tuple(
                taxi(
                    f"dense-{size}-{index}",
                    ORIGIN,
                    DESTINATION,
                    drive=200 + index,
                    readiness=QuoteReadiness.COARSE,
                    topology_ref=f"taxi:dense-{size}-{index}",
                )
                for index in range(size)
            )
            inputs = StrategyGenerationInput(
                ORIGIN,
                DESTINATION,
                DEPARTURE,
                (),
                taxi_only_quotes=quotes,
            )
            forward = generator.generate(inputs, constraints())
            reverse = generator.generate(
                replace(inputs, taxi_only_quotes=tuple(reversed(quotes))),
                constraints(),
            )
            self.assertEqual(forward, reverse)
            self.assertLessEqual(len(forward.candidates), caps.pre_pareto)
            self.assertLessEqual(forward.unique_provider_calls, caps.provider_calls)
            self.assertEqual(
                len({item.seed.topology_key for item in forward.candidates}),
                len(forward.candidates),
            )
            self.assertTrue(
                all(
                    item.seed.coarse_taxi_upper_krw <= constraints().taxi_budget_krw
                    for item in forward.candidates
                )
            )

    def test_conflicting_canonical_ids_and_untyped_readiness_fail_closed(self) -> None:
        shared_id_a = taxi("shared", ORIGIN, DESTINATION, drive=200)
        shared_id_b = taxi("shared", ORIGIN, DESTINATION, drive=300)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            StrategyGenerationInput(
                ORIGIN,
                DESTINATION,
                DEPARTURE,
                (),
                access_hubs=(AccessHub("a", "missing", 0, shared_id_a),),
                taxi_only_quotes=(shared_id_b,),
            )
        with self.assertRaisesRegex(ValueError, "QuoteReadiness"):
            replace(shared_id_a, readiness="EXACT")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
