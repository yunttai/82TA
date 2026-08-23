from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from provider_core.canonical import (
    Coordinate,
    DataOrigin,
    TimeEstimate as ProviderTimeEstimate,
)
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from routing_api.application import (
    OptimizeCommand,
    RequestContext,
    RoutingCapacityExceeded,
    RoutingUnavailableError,
)
from routing_api.fanin_integration import (
    _BusLegSnapshot,
    CanonicalFanInOptimizeRouteUseCase,
    _ProviderOperationBudget,
    _RequestModelInferenceBudget,
    _RequestScopedLegEvaluator,
    _canonical_movement_source,
    _canonicalize_returned_itineraries,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.tests.test_api import FakeClock, _request_payload
from routing_api.tests.test_fixture_integration import (
    _CausalProviderPorts,
    _SCENARIO_DEPARTURES,
    _SCENARIO_ENDPOINTS,
)
from routing_domain import (
    BoundedStrategyGenerator,
    CandidateCaps,
    GraphSearchUncertifiedError,
    CanonicalTransitTopology,
    LegCost,
    LegSpec,
    MoneyRange,
    OptimalityUncertifiedError,
    QuoteReadiness,
    RouteConstraints,
    RouteOptimizer,
    StaticLegEvaluator,
    StrategyGenerationInput,
    TaxiQuote,
    TimeEstimate,
)


class _MultipleItineraryProviders(_CausalProviderPorts):
    def __init__(self, base, *, order: tuple[str, ...]) -> None:
        super().__init__(base)
        self._order = order

    def transit(self, request, *, deadline):
        envelope = super().transit(request, deadline=deadline)
        if (
            (request.origin.lon, request.origin.lat) != _SCENARIO_ENDPOINTS["R1"][0]
            or (request.destination.lon, request.destination.lat)
            != _SCENARIO_ENDPOINTS["R1"][1]
        ):
            return envelope
        template = envelope.payload[0]
        durations = {"slow": (1_500, 1_800), "fast": (240, 360)}
        values = {}
        for name, (p50, p90) in durations.items():
            leg = replace(
                template.legs[0],
                leg_id=f"{name}-leg",
                duration=ProviderTimeEstimate(
                    p50,
                    p90,
                    DataOrigin.PROVIDER_ESTIMATE,
                    lower_seconds=max(0, p50 - 60),
                ),
            )
            values[name] = replace(
                template,
                itinerary_id=f"{name}-itinerary",
                legs=(leg,),
            )
        payload = tuple(values[name] for name in self._order)
        return replace(envelope, payload=payload, normalized_count=len(payload))


class _MappingRecorder:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.itinerary_ids: list[str] = []

    def __call__(self, evidence, evaluated_at):
        self.itinerary_ids.append(evidence.itinerary_id)
        return self._delegate(evidence, evaluated_at)


def _run(order: tuple[str, ...]):
    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    mapping = _MappingRecorder(base.mapping)
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "ri392",
        clock,
        dependencies=replace(
            base,
            providers=_MultipleItineraryProviders(base.providers, order=order),
            mapping=mapping,
        ),
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0],
        "lat": destination[1],
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "ri392-correlation",
        "ri392-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    result = use_case.execute(OptimizeCommand(payload), context)
    return result.response, use_case.trace, mapping


def test_later_itinerary_can_be_exact_fastest_and_receives_bus_mapping() -> None:
    response, trace, mapping = _run(("slow", "fast"))

    fastest_id = response["recommendations"]["fastest"]
    fastest = next(route for route in response["routes"] if route["routeId"] == fastest_id)
    assert fastest["totalDuration"]["p50Seconds"] < 1_000
    assert trace.returned_itinerary_count == 2
    assert trace.admitted_itinerary_count == 2
    assert trace.deduplicated_itinerary_count == 0
    assert trace.finite_payload_complete is True
    assert trace.network_global_complete is False
    # The later payload member is independently exactified through mapping and
    # Bus Intelligence; it is not aliased to payload[0] provenance.
    assert "fast-itinerary" in mapping.itinerary_ids
    assert trace.provider_call_count <= 64


def test_payload_permutation_is_deterministic() -> None:
    forward, forward_trace, _ = _run(("slow", "fast"))
    reverse, reverse_trace, _ = _run(("fast", "slow"))

    assert forward["recommendations"] == reverse["recommendations"]
    assert forward["routes"] == reverse["routes"]
    assert forward["paretoRouteIds"] == reverse["paretoRouteIds"]
    assert forward_trace.coarse_patterns == reverse_trace.coarse_patterns
    assert forward_trace.exact_patterns == reverse_trace.exact_patterns


def test_exact_duplicate_is_deduplicated_without_extra_bus_mapping() -> None:
    response, trace, mapping = _run(("fast", "fast"))

    assert response["routes"]
    assert trace.returned_itinerary_count == 2
    assert trace.admitted_itinerary_count == 1
    assert trace.deduplicated_itinerary_count == 1
    assert mapping.itinerary_ids.count("fast-itinerary") == 1


def test_conflicting_duplicate_provider_itinerary_id_fails_closed() -> None:
    class ConflictingIds(_MultipleItineraryProviders):
        def transit(self, request, *, deadline):
            envelope = super().transit(request, deadline=deadline)
            if len(envelope.payload) != 2:
                return envelope
            return replace(
                envelope,
                payload=(
                    envelope.payload[0],
                    replace(envelope.payload[1], itinerary_id=envelope.payload[0].itinerary_id),
                ),
            )

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "ri392-conflict",
        clock,
        dependencies=replace(
            base,
            providers=ConflictingIds(base.providers, order=("slow", "fast")),
        ),
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "ri392-conflict-correlation",
        "ri392-conflict-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )

    with pytest.raises(RoutingUnavailableError, match="conflicting content"):
        use_case.execute(OptimizeCommand(payload), context)


def test_payload_count_and_requested_bound_are_fail_closed() -> None:
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    request = _request_payload()
    request["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    request["destination"]["coordinate"] = {
        "lon": destination[0],
        "lat": destination[1],
    }
    envelope = base.providers.transit(
        # Reuse the adapter's canonical request shape through the multi-provider
        # wrapper, which records an actual bounded transit attempt.
        TransitSearchRequest(
            Coordinate(*origin),
            Coordinate(*destination),
            datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"]),
            max_itineraries=5,
        ),
        deadline=Deadline.after_ms(100),
    )
    with pytest.raises(RoutingUnavailableError, match="requested itinerary bound"):
        _canonicalize_returned_itineraries(
            envelope.payload * 6,
            request["origin"]["coordinate"],
            request["destination"]["coordinate"],
            max_itineraries=5,
        )
    mismatched = replace(envelope, normalized_count=2)
    assert _canonical_movement_source(
        mismatched,
        "BUS",
        expected_from=origin,
        expected_to=destination,
    ) is None


def test_same_endpoint_selector_prefers_expected_topology_and_provenance() -> None:
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    request = TransitSearchRequest(
        Coordinate(*origin),
        Coordinate(*destination),
        datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"]),
        max_itineraries=5,
    )
    envelope = base.providers.transit(
        request,
        deadline=Deadline.after_ms(100),
    )
    template = envelope.payload[0]
    leg_a = replace(
        template.legs[0],
        leg_id="topology-a-leg",
        transit=replace(template.legs[0].transit, external_route_id="route-a"),
    )
    leg_b = replace(
        template.legs[0],
        leg_id="topology-b-leg",
        transit=replace(template.legs[0].transit, external_route_id="route-b"),
    )
    multi = replace(
        envelope,
        payload=(
            replace(template, itinerary_id="topology-a", legs=(leg_a,)),
            replace(template, itinerary_id="topology-b", legs=(leg_b,)),
        ),
        normalized_count=2,
    )
    descriptor = leg_b.transit
    expected = CanonicalTransitTopology(
        descriptor.external_route_id,
        descriptor.direction,
        "origin",
        "destination",
        descriptor.boarding_sequence,
        descriptor.alighting_sequence,
        descriptor.branch_id,
    ).fingerprint

    selected = _canonical_movement_source(
        multi,
        "BUS",
        expected_from=origin,
        expected_to=destination,
        expected_topology_ref=expected,
    )
    assert selected is not None
    assert selected.itinerary_id == "topology-b"
    assert selected.leg.leg_id == "topology-b-leg"


def test_provider_endpoint_selector_accepts_small_road_snap_but_rejects_drift() -> None:
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    request = TransitSearchRequest(
        Coordinate(*origin),
        Coordinate(*destination),
        datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"]),
        max_itineraries=1,
    )
    envelope = base.providers.taxi(request, deadline=Deadline.after_ms(100))
    itinerary = envelope.payload[0]
    template = itinerary.legs[0]

    snapped = replace(
        template,
        from_stop=replace(
            template.from_stop,
            coordinate=Coordinate(origin[0] + 0.000005, origin[1]),
        ),
        to_stop=replace(
            template.to_stop,
            coordinate=Coordinate(destination[0], destination[1] - 0.000005),
        ),
    )
    snapped_envelope = replace(
        envelope,
        payload=(replace(itinerary, legs=(snapped,)),),
        normalized_count=1,
    )
    selected = _canonical_movement_source(
        snapped_envelope,
        "TAXI",
        expected_from=origin,
        expected_to=destination,
    )
    assert selected is not None
    assert selected.leg is snapped

    drifted = replace(
        snapped,
        from_stop=replace(
            snapped.from_stop,
            coordinate=Coordinate(origin[0] + 0.0005, origin[1]),
        ),
    )
    drifted_envelope = replace(
        envelope,
        payload=(replace(itinerary, legs=(drifted,)),),
        normalized_count=1,
    )
    assert _canonical_movement_source(
        drifted_envelope,
        "TAXI",
        expected_from=origin,
        expected_to=destination,
    ) is None


def test_projection_anchors_accepted_provider_snap_to_canonical_nodes() -> None:
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    request = TransitSearchRequest(
        Coordinate(*origin),
        Coordinate(*destination),
        datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"]),
        max_itineraries=1,
    )
    envelope = base.providers.taxi(request, deadline=Deadline.after_ms(100))
    template = envelope.payload[0].legs[0]
    snapped = replace(
        template,
        from_stop=replace(
            template.from_stop,
            coordinate=Coordinate(origin[0] + 0.000005, origin[1]),
        ),
        to_stop=replace(
            template.to_stop,
            coordinate=Coordinate(destination[0], destination[1] - 0.000005),
        ),
    )

    projection = CanonicalFanInOptimizeRouteUseCase._projection_from_leg(
        snapped,
        expected_start=origin,
        expected_end=destination,
    )

    assert projection.from_coordinate == origin
    assert projection.to_coordinate == destination
    provider_geometry = tuple((item.lon, item.lat) for item in snapped.geometry)
    assert projection.geometry == provider_geometry or projection.geometry == (
        origin,
        destination,
    )


def _ri394_frontier_input(*, count: int, coarse: bool) -> StrategyGenerationInput:
    quotes = []
    for index in range(count):
        is_late_winner = index == count - 1
        p50 = 2 if is_late_winner else 1_000 + index
        quotes.append(
            TaxiQuote(
                quote_id=f"ri394-{index:02d}",
                from_ref="origin",
                to_ref="destination",
                evaluator_key=f"ri394-cost-{index:02d}",
                dispatch_wait=TimeEstimate(1, 1),
                drive_duration=TimeEstimate(p50 - 1, p50),
                fare=MoneyRange(1_000, 1_000, 1_000),
                distance_meters=1_000,
                lower_bound_dispatch_seconds=0,
                lower_bound_drive_seconds=(1 if is_late_winner else 0),
                readiness=QuoteReadiness.COARSE if coarse else QuoteReadiness.EXACT,
                topology_ref=f"ri394:{index:02d}",
            )
        )
    return StrategyGenerationInput(
        "origin",
        "destination",
        datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"]),
        (),
        taxi_only_quotes=tuple(quotes),
    )


def _ri394_constraints() -> RouteConstraints:
    return RouteConstraints(
        taxi_budget_krw=10_000,
        strict_taxi_budget=True,
        max_walk_seconds=7_200,
        max_transfers=8,
        max_taxi_legs=3,
        allowed_modes=frozenset({"WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"}),
        allow_taxi_bridge=True,
    )


def _ri394_use_case(*, provider_operation_cap: int = 64):
    clock = FakeClock()
    scenario = fixture_scenario("R1")
    return (
        CanonicalFanInOptimizeRouteUseCase(
            "ri394-frontier",
            clock,
            dependencies=fixture_fan_in_dependencies(scenario),
            provider_operation_cap=provider_operation_cap,
        ),
        clock,
    )


def test_ri394_candidate_21_is_evaluated_and_can_be_exact_fastest() -> None:
    use_case, clock = _ri394_use_case()
    inputs = _ri394_frontier_input(count=21, coarse=False)
    constraints = _ri394_constraints()
    context = RequestContext(
        "ri394-correlation",
        "ri394-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    generator = BoundedStrategyGenerator(
        caps=CandidateCaps(coarse_combinations=30, pre_pareto=20)
    )

    complete = use_case._build_complete_strategy_batch(
        generator,
        inputs,
        constraints,
        context,
        _ProviderOperationBudget(64),
    )
    assert len(complete.candidates) == 21
    assert complete.candidates[-1].seed.candidate_key == "taxi-only:ri394-20"
    optimized = RouteOptimizer(StaticLegEvaluator(complete.costs())).optimize(
        complete.seeds,
        inputs.departure_at,
        constraints,
    )
    assert optimized.recommendations.fastest == complete.candidates[-1].seed.route_id


def test_ri394_frontier_cap_boundary_fails_as_capacity_never_provider_failure() -> None:
    inputs = _ri394_frontier_input(count=21, coarse=True)
    constraints = _ri394_constraints()
    generator = BoundedStrategyGenerator(
        caps=CandidateCaps(
            coarse_combinations=30,
            pre_pareto=20,
            provider_calls=64,
        )
    )

    capped, clock = _ri394_use_case(provider_operation_cap=20)
    context = RequestContext(
        "ri394-cap-correlation",
        "ri394-cap-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    with pytest.raises(RoutingCapacityExceeded, match="CALL_CAP_UNCERTIFIED"):
        capped._build_complete_strategy_batch(
            generator,
            inputs,
            constraints,
            context,
            _ProviderOperationBudget(20),
        )

    boundary, boundary_clock = _ri394_use_case(provider_operation_cap=21)
    boundary_context = replace(
        context,
        client_deadline=boundary_clock.now() + timedelta(seconds=6),
        effective_deadline=boundary_clock.now() + timedelta(seconds=6),
    )
    complete = boundary._build_complete_strategy_batch(
        generator,
        inputs,
        constraints,
        boundary_context,
        _ProviderOperationBudget(21),
    )
    assert len(complete.candidates) == 21
    assert complete.unique_provider_calls == 21


def test_ri394_complete_frontier_is_input_permutation_deterministic() -> None:
    forward = _ri394_frontier_input(count=21, coarse=False)
    reverse = replace(forward, taxi_only_quotes=tuple(reversed(forward.taxi_only_quotes)))
    constraints = _ri394_constraints()
    generator = BoundedStrategyGenerator(
        caps=CandidateCaps(coarse_combinations=30, pre_pareto=20)
    )
    use_case, clock = _ri394_use_case()
    context = RequestContext(
        "ri394-permutation-correlation",
        "ri394-permutation-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )

    first = use_case._build_complete_strategy_batch(
        generator, forward, constraints, context, _ProviderOperationBudget(64)
    )
    second = use_case._build_complete_strategy_batch(
        generator, reverse, constraints, context, _ProviderOperationBudget(64)
    )
    assert first == second


def test_ri394_production_execute_never_ranks_truncated_candidate_21(
    monkeypatch,
) -> None:
    from routing_api import fanin_integration

    inputs = _ri394_frontier_input(count=21, coarse=True)
    monkeypatch.setattr(
        fanin_integration,
        "_coarse_strategy_inputs",
        lambda *args, **kwargs: inputs,
    )
    use_case, clock = _ri394_use_case(provider_operation_cap=20)
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0],
        "lat": destination[1],
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "ri394-production-cap-correlation",
        "ri394-production-cap-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )

    with pytest.raises(RoutingCapacityExceeded, match="CALL_CAP_UNCERTIFIED"):
        use_case.execute(OptimizeCommand(payload), context)
    assert use_case.trace is None


def test_ri395_production_trace_proves_graph_search_and_recombination() -> None:
    response, trace, _ = _run(("slow", "fast"))

    assert trace.graph_expansion_count > 0
    assert trace.graph_seed_count > 0
    assert trace.graph_recombined_count > 0
    budget = _request_payload()["constraints"]["taxiBudget"]["maxAmount"]
    assert all(route["taxiCost"]["upper"] <= budget for route in response["routes"])


def test_ri395_production_uses_graph_entrypoint_without_seed_reoptimization(
    monkeypatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    original_graph = RouteOptimizer.optimize_graph

    def track_graph(self, *args, **kwargs):
        calls.append(tuple(kwargs.get("pattern_hints", ())))
        return original_graph(self, *args, **kwargs)

    def forbid_seed_reoptimization(*args, **kwargs):
        del args, kwargs
        raise AssertionError("production graph paths must not be evaluated twice")

    monkeypatch.setattr(RouteOptimizer, "optimize_graph", track_graph)
    monkeypatch.setattr(RouteOptimizer, "optimize", forbid_seed_reoptimization)

    response, trace, _ = _run(("slow", "fast"))

    assert response["routes"]
    assert len(calls) == 1
    assert calls[0]
    assert trace.graph_expansion_count > 0
    assert trace.finite_payload_complete is True
    assert trace.network_global_complete is False


def test_ri395_request_scoped_bus_evaluator_is_reentrant_and_ready_only() -> None:
    class NullPredictor:
        def predict(self, value):
            del value
            return None

    cancellation = threading.Event()
    leg = LegSpec("bus-leg", "BUS", "origin", "destination", "bus-cost", topology_ref="bus-topology")
    base = LegCost(
        TimeEstimate(120, 180),
        TimeEstimate(600, 720),
        MoneyRange(1_500, 1_500, 1_500),
        0.8,
        warning_codes=("READY_EVIDENCE",),
    )
    snapshot = _BusLegSnapshot(
        "bus-topology", None, None, None, None, None, None, "SEATED", leg_id=leg.leg_id
    )
    evaluator = _RequestScopedLegEvaluator(
        {"bus-cost": base},
        (snapshot,),
        NullPredictor(),
        NullPredictor(),
        _RequestModelInferenceBudget(cancellation),
    )
    first_at = datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"])
    second_at = first_at + timedelta(seconds=30)

    first = evaluator.evaluate(leg, first_at)
    second = evaluator.evaluate(leg, second_at)
    assert evaluator.evaluate(leg, first_at) == first
    assert evaluator.evaluate(leg, second_at) == second
    travel = evaluator.evaluate_travel(
        leg,
        first_at + timedelta(seconds=first.wait.p50_seconds),
        first,
    )
    assert travel.wait == TimeEstimate(0, 0)
    assert travel.reliability_score == first.reliability_score
    assert travel.warning_codes == first.warning_codes
    assert len(evaluator.evaluations) == 2


@pytest.mark.parametrize(
    ("uncertified", "expected"),
    (
        (
            GraphSearchUncertifiedError("GRAPH_COMPLETE_PATH_CAP_UNCERTIFIED"),
            "GRAPH_COMPLETE_PATH_CAP_UNCERTIFIED",
        ),
        (
            OptimalityUncertifiedError("EXACT_CANDIDATE_CAP_UNCERTIFIED"),
            "EXACT_CANDIDATE_CAP_UNCERTIFIED",
        ),
    ),
)
def test_ri395_graph_or_optimizer_cap_is_capacity_not_provider_unavailable(
    monkeypatch,
    uncertified,
    expected,
) -> None:
    from routing_api import fanin_integration

    def fail_graph(*args, **kwargs):
        del args, kwargs
        raise uncertified

    monkeypatch.setattr(fanin_integration.RouteOptimizer, "optimize_graph", fail_graph)
    clock = FakeClock()
    scenario = fixture_scenario("R1")
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "ri395-cap",
        clock,
        dependencies=fixture_fan_in_dependencies(scenario),
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0],
        "lat": destination[1],
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "ri395-cap-correlation",
        "ri395-cap-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )

    with pytest.raises(RoutingCapacityExceeded, match=expected):
        use_case.execute(OptimizeCommand(payload), context)
    assert use_case.trace is None
