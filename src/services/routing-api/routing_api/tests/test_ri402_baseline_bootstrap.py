"""RI-402 truthful production baseline and deployment bootstrap evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import os
import sys
import threading
import tomllib
from unittest.mock import patch

import pytest
from setuptools import find_namespace_packages

from provider_core.canonical import (
    CanonicalLeg,
    CanonicalStop,
    Coordinate,
    DataOrigin,
    MoneyRange as ProviderMoneyRange,
    TimeEstimate as ProviderTimeEstimate,
    TransitDescriptor,
    TravelMode,
)
from provider_core.named import ProviderAdapterSuite, ProviderAdapterSuiteConfig
from routing_api.application import OptimizeCommand, RequestContext, RoutingUnavailableError
from routing_deployment.baseline import (
    ConservativeTaxiDispatchEstimator,
    DjangoHistoricalBusWaitEstimator,
    LazyDjangoOptimizationResultRepository,
    _conservative_headway_wait,
    _historical_wait,
    build_dependencies,
)
from routing_deployment.bootstrap import (
    PRODUCTION_DEPENDENCIES_FACTORY_ENV,
    ProductionBootstrapError,
    bootstrap_from_environment,
    bootstrap_production_dependencies,
)
from routing_deployment.gbis_live import GbisLiveBusWaitEstimator
from routing_api.fanin_integration import (
    CanonicalFanInOptimizeRouteUseCase,
    InMemoryOptimizationPersistence,
    _coarse_strategy_inputs,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.production_composition import (
    ProductionCompositionDependencies,
    ProductionOptimizeRouteUseCase,
    UnavailableEtaPredictor,
    UnavailableMappingResolver,
    UnavailableSeatRiskPredictor,
    build_injected_production_use_case,
)
from routing_api.tests.test_api import FakeClock, _request_payload
from routing_api.tests.test_fixture_integration import _enabled_transit_registry
from routing_domain import (
    BoundedStrategyGenerator,
    CanonicalTransitTopology,
    MoneyRange,
    QuoteReadiness,
    RouteConstraints,
    RouteOptimizer,
    TimeEstimate,
    TransitBaseline,
    TransitLegInput,
    WalkQuote,
)


def _factory_module(name: str, attribute: str, value) -> ModuleType:
    module = ModuleType(name)
    setattr(module, attribute, value)
    return module


def test_bootstrap_absence_preserves_default_and_exact_factory_registers_once() -> None:
    dependencies = ProductionCompositionDependencies()
    with patch(
        "routing_deployment.bootstrap.register_production_dependencies"
    ) as register:
        assert bootstrap_from_environment({}) is None
        assert bootstrap_production_dependencies(lambda: dependencies) is dependencies
    register.assert_called_once_with(dependencies)


def test_deployment_package_is_in_the_distribution_and_outside_routing_api() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    discovery = config["tool"]["setuptools"]["packages"]["find"]
    discovered = set(
        find_namespace_packages(
            where=str(project_root),
            include=discovery["include"],
            exclude=discovery["exclude"],
        )
    )
    assert "routing_deployment" in discovered
    assert not (project_root / "routing_api" / "deployment" / "__init__.py").exists()


def test_bootstrap_factory_lookup_is_strict_and_sanitizes_factory_failure() -> None:
    secret = "must-not-escape-bootstrap"

    def failing_factory():
        raise RuntimeError(secret)

    module_name = "ri402_failing_factory"
    module = _factory_module(module_name, "build", failing_factory)
    with patch.dict(sys.modules, {module_name: module}):
        with pytest.raises(ProductionBootstrapError) as captured:
            bootstrap_from_environment(
                {PRODUCTION_DEPENDENCIES_FACTORY_ENV: f"{module_name}:build"}
            )
    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is not None
    assert captured.value.__suppress_context__ is True

    for invalid in ("", "module", "module:call:extra", "bad-name:call"):
        if not invalid:
            continue
        with pytest.raises(ProductionBootstrapError):
            bootstrap_from_environment(
                {PRODUCTION_DEPENDENCIES_FACTORY_ENV: invalid}
            )


def test_concrete_baseline_factory_consumes_exact_provider_config_without_keys() -> None:
    registry = _enabled_transit_registry()
    provider_config = ProviderAdapterSuiteConfig(capabilities=registry)
    module_name = "ri402_provider_config_factory"
    module = _factory_module(module_name, "build", lambda: provider_config)
    with patch.dict(sys.modules, {module_name: module}):
        dependencies = build_dependencies(
            {
                "ROUTING_PROVIDER_CONFIG_FACTORY": f"{module_name}:build",
                "ROUTING_RUNTIME_ENVIRONMENT": "STAGING",
            }
        )

    assert type(dependencies) is ProductionCompositionDependencies
    assert dependencies.provider_config is provider_config
    assert dependencies.capability_registry is registry
    assert type(dependencies.persistence) is LazyDjangoOptimizationResultRepository
    assert dependencies.mapping_database is None
    assert dependencies.eta_predictor is None
    assert dependencies.seat_predictor is None
    assert type(dependencies.taxi_dispatch) is ConservativeTaxiDispatchEstimator
    assert type(dependencies.bus_wait) is DjangoHistoricalBusWaitEstimator
    assert dependencies.deployment_environment == "staging"

    dispatch = dependencies.taxi_dispatch.estimate(
        SimpleNamespace(),
        evaluated_at=datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc),
    )
    assert (dispatch.wait.p50_seconds, dispatch.wait.p90_seconds) == (180, 420)
    assert dispatch.origin == "HISTORICAL_PROXY"
    assert dispatch.source == "CONSERVATIVE_BASELINE_POLICY"


def test_bus_wait_uses_prior_service_days_at_the_candidate_arrival_time() -> None:
    seoul = timezone(timedelta(hours=9))
    arrival_at = datetime(2026, 8, 24, 8, 0, tzinfo=seoul)
    estimate = _historical_wait(
        (
            datetime(2026, 8, 17, 8, 5, tzinfo=seoul),
            datetime(2026, 8, 18, 8, 7, tzinfo=seoul),
            # Weekend service must not contaminate a weekday estimate.
            datetime(2026, 8, 22, 8, 1, tzinfo=seoul),
        ),
        arrival_at,
    )

    assert estimate is not None
    assert (estimate.p50_seconds, estimate.p90_seconds) == (360, 420)


def test_empty_history_proxy_is_nonzero_and_changes_with_entry_time() -> None:
    seoul = timezone(timedelta(hours=9))
    leg = SimpleNamespace(
        transit=SimpleNamespace(route_label="M5107"),
        from_stop=SimpleNamespace(name="경기대후문"),
    )
    first = _conservative_headway_wait(
        leg, datetime(2026, 8, 24, 8, 0, tzinfo=seoul)
    )
    second = _conservative_headway_wait(
        leg, datetime(2026, 8, 24, 8, 1, tzinfo=seoul)
    )

    assert first.p50_seconds > 0
    assert first.p90_seconds >= first.p50_seconds
    assert second.p50_seconds > 0
    assert second.p50_seconds != first.p50_seconds


def _canonical_bus_leg() -> CanonicalLeg:
    return CanonicalLeg(
        leg_id="kakao-bus-1",
        sequence=1,
        mode=TravelMode.BUS,
        from_stop=CanonicalStop(
            "명지대",
            Coordinate(127.18854958, 37.22425832),
        ),
        to_stop=CanonicalStop(
            "동원로얄듀크.용인등기소",
            Coordinate(127.205, 37.236),
        ),
        duration=ProviderTimeEstimate(900, 1_020, DataOrigin.PROVIDER_ESTIMATE),
        distance_meters=8_000,
        fare=ProviderMoneyRange(2_800, 2_800, 2_800, DataOrigin.PROVIDER_ESTIMATE),
        transit=TransitDescriptor(route_label="5001-1A / 5001-1B"),
    )


def _gbis_document(
    collection: str, rows: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "response": {
            "msgHeader": {"resultCode": 0, "resultMessage": "정상적으로 처리되었습니다."},
            "msgBody": {collection: rows},
        }
    }


def test_gbis_live_wait_maps_kakao_identity_and_refreshes_each_request() -> None:
    calls: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    def fetch(endpoint: str, query: tuple[tuple[str, str], ...]):
        calls.append((endpoint, query))
        if "getBusStationAroundListv2" in endpoint:
            return _gbis_document(
                "busStationAroundList",
                [
                    {
                        "stationId": "228000191",
                        "stationName": "명지대",
                        "x": 127.18855,
                        "y": 37.22426,
                        "distance": 20,
                    }
                ],
            )
        if "getBusStationViaRouteListv2" in endpoint:
            return _gbis_document(
                "busRouteList",
                [
                    {"routeId": "228000430", "routeName": "5001-1A"},
                    {"routeId": "228000177", "routeName": "5001-1B"},
                    {"routeId": "228000184", "routeName": "5600"},
                ],
            )
        return _gbis_document(
            "busArrivalList",
            [
                {
                    "routeId": "228000430",
                    "predictTime1": 2,
                    "predictTime2": 9,
                }
            ],
        )

    class NoFallback:
        def estimate(self, leg, *, arrival_at, evaluated_at):
            del leg, arrival_at, evaluated_at
            raise AssertionError("usable live arrival must not fall back")

    estimator = GbisLiveBusWaitEstimator(
        "test-key-never-sent-to-the-fixture",
        NoFallback(),
        fetch_json=fetch,
    )
    seoul = timezone(timedelta(hours=9))
    evaluated_at = datetime(2026, 8, 24, 8, 0, tzinfo=seoul)
    arrival_at = evaluated_at + timedelta(minutes=5)

    first = estimator.estimate(
        _canonical_bus_leg(),
        arrival_at=arrival_at,
        evaluated_at=evaluated_at,
    )
    assert first is not None
    assert first.origin == "PROVIDER_ESTIMATE"
    assert first.source == "GBIS_V2_LIVE_ARRIVAL"
    assert (first.wait.p50_seconds, first.wait.p90_seconds) == (240, 360)
    assert len(calls) == 3
    assert all("test-key" not in repr(call) for call in calls)

    # Candidate legs in one request share the arrival snapshot but evaluate it
    # at their own entry time.
    second = estimator.estimate(
        _canonical_bus_leg(),
        arrival_at=arrival_at + timedelta(minutes=1),
        evaluated_at=evaluated_at,
    )
    assert second is not None
    assert second.wait.p50_seconds == 180
    assert len(calls) == 3

    # A new request has a new evaluated_at and must fetch arrivals again. Static
    # station/route identity remains safely reusable.
    third = estimator.estimate(
        _canonical_bus_leg(),
        arrival_at=arrival_at + timedelta(seconds=1),
        evaluated_at=evaluated_at + timedelta(seconds=1),
    )
    assert third is not None
    assert len(calls) == 4


def test_gbis_empty_live_arrival_uses_explicit_historical_fallback() -> None:
    def fetch(endpoint: str, query: tuple[tuple[str, str], ...]):
        del query
        if "getBusStationAroundListv2" in endpoint:
            return _gbis_document(
                "busStationAroundList",
                [
                    {
                        "stationId": "228000191",
                        "stationName": "명지대",
                        "x": 127.18855,
                        "y": 37.22426,
                        "distance": 20,
                    }
                ],
            )
        if "getBusStationViaRouteListv2" in endpoint:
            return _gbis_document(
                "busRouteList",
                [{"routeId": "228000430", "routeName": "5001-1A"}],
            )
        return _gbis_document("busArrivalList", [])

    class HistoricalFallback:
        def estimate(self, leg, *, arrival_at, evaluated_at):
            del leg, arrival_at, evaluated_at
            from routing_api.fanin_integration import BusWaitEstimate

            return BusWaitEstimate(
                TimeEstimate(480, 720),
                "BUS_ARRIVAL_OBSERVATION_HISTORY",
                "bus-wait-history-1.0.0",
                origin="HISTORICAL_PROXY",
            )

    estimator = GbisLiveBusWaitEstimator(
        "test-key",
        HistoricalFallback(),
        fetch_json=fetch,
    )
    evaluated_at = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
    estimate = estimator.estimate(
        _canonical_bus_leg(),
        arrival_at=evaluated_at + timedelta(minutes=5),
        evaluated_at=evaluated_at,
    )

    assert estimate is not None
    assert estimate.origin == "HISTORICAL_PROXY"
    assert estimate.wait.p50_seconds == 480
    assert "test-key" not in repr(estimator)


def test_production_hybrids_use_real_returned_transit_stops() -> None:
    def walk(name: str, start: str, end: str) -> WalkQuote:
        return WalkQuote(
            name,
            start,
            end,
            f"cost:{name}",
            TimeEstimate(120, 180),
            500,
            lower_bound_seconds=60,
            readiness=QuoteReadiness.COARSE,
        )

    def transit(name: str, mode: str, start: str, end: str) -> TransitLegInput:
        return TransitLegInput(
            name,
            mode,
            CanonicalTransitTopology(name, "OUTBOUND", start, end, 0, 1),
            f"cost:{name}",
            TimeEstimate(600, 720),
            MoneyRange.zero(),
            lower_bound_seconds=480,
            readiness=QuoteReadiness.COARSE,
        )

    baseline = TransitBaseline(
        "live-returned",
        (
            walk("origin-walk", "origin", "rail-in"),
            transit("rail", "SUBWAY", "rail-in", "rail-out"),
            walk("transfer-walk", "rail-out", "bus-in"),
            transit("bus", "BUS", "bus-in", "bus-out"),
            walk("destination-walk", "bus-out", "destination"),
        ),
    )
    departure = datetime(2026, 8, 24, 8, 0, tzinfo=timezone(timedelta(hours=9)))
    inputs = _coarse_strategy_inputs(
        departure,
        100_000,
        route_suffix="production",
        canonical_baselines=(baseline,),
    )

    assert inputs.access_hubs[0].taxi_quote.to_ref == "rail-in"
    assert inputs.egress_hubs[0].taxi_quote.from_ref == "bus-out"
    assert inputs.taxi_bridges[0].taxi_quote.from_ref == "rail-out"
    assert inputs.taxi_bridges[0].taxi_quote.to_ref == "bus-in"
    search = BoundedStrategyGenerator().build_search_space(
        inputs,
        RouteConstraints(
            taxi_budget_krw=100_000,
            strict_taxi_budget=True,
            max_walk_seconds=10_000,
            max_transfers=5,
            max_taxi_legs=2,
            allowed_modes=frozenset({"WALK", "TAXI", "BUS", "SUBWAY"}),
            allow_taxi_bridge=True,
        ),
    )
    patterns = {item.seed.pattern for item in search.candidates}
    assert {
        "TAXI_TRANSIT",
        "TRANSIT_TAXI",
        "TAXI_TRANSIT_TAXI",
        "TRANSIT_TAXI_BRIDGE_TRANSIT",
    } <= patterns

    faster_bus_baselines = tuple(
        TransitBaseline(
            f"faster-bus-{index}",
            (
                walk(f"bus-walk-in-{index}", "origin", f"bus-in-{index}"),
                transit(
                    f"bus-only-{index}",
                    "BUS",
                    f"bus-in-{index}",
                    f"bus-out-{index}",
                ),
                walk(
                    f"bus-walk-out-{index}",
                    f"bus-out-{index}",
                    "destination",
                ),
            ),
        )
        for index in range(3)
    )
    diverse = _coarse_strategy_inputs(
        departure,
        100_000,
        route_suffix="production",
        canonical_baselines=(*faster_bus_baselines, baseline),
    )

    # A rail itinerary outside the three fastest raw baselines must still enter
    # the bounded hybrid pool; otherwise Taxi→Rail and Bus→Taxi→Rail are
    # impossible to discover regardless of their exact live costs.
    assert any(
        item.baseline_id == baseline.baseline_id
        and item.taxi_quote.to_ref == "rail-in"
        for item in diverse.access_hubs
    )
    assert any(
        item.outbound_baseline_id == baseline.baseline_id
        for item in diverse.taxi_bridges
    )


def test_local_live_baseline_is_explicit_dev_provenance_and_fixture_free() -> None:
    registry = _enabled_transit_registry()
    provider_config = ProviderAdapterSuiteConfig(capabilities=registry)
    module_name = "ri402_local_live_provider_config_factory"
    module = _factory_module(module_name, "build", lambda: provider_config)
    environment = {
        "ROUTING_PROVIDER_CONFIG_FACTORY": f"{module_name}:build",
        "ROUTING_RUNTIME_ENVIRONMENT": "DEVELOPMENT",
    }
    with patch.dict(sys.modules, {module_name: module}):
        with pytest.raises(ProductionBootstrapError, match="explicit local live"):
            build_dependencies(environment)
        dependencies = build_dependencies(
            {**environment, "ROUTING_LOCAL_LIVE_E2E": "true"}
        )
        gbis_dependencies = build_dependencies(
            {
                **environment,
                "ROUTING_LOCAL_LIVE_E2E": "true",
                "GBIS_SERVICE_KEY": "local-live-gbis-test-key",
                "ROUTING_PROVIDER_HTTPS_PROXY_URL": "http://routing-egress-proxy:3128",
            }
        )

    assert dependencies.deployment_environment == "dev"
    assert dependencies.provider_config is provider_config
    assert dependencies.mapping_database is None
    assert dependencies.eta_predictor is None
    assert dependencies.seat_predictor is None
    assert type(dependencies.taxi_dispatch) is ConservativeTaxiDispatchEstimator
    assert type(dependencies.bus_wait) is DjangoHistoricalBusWaitEstimator
    assert type(gbis_dependencies.bus_wait) is GbisLiveBusWaitEstimator


def test_concrete_baseline_factory_defaults_to_reviewed_kakao_target_fail_closed() -> None:
    with patch.dict(
        os.environ,
        {"ROUTING_RUNTIME_ENVIRONMENT": "STAGING"},
        clear=True,
    ):
        with pytest.raises(ProductionBootstrapError, match="provider config factory failed"):
            build_dependencies()


def test_baseline_factory_rejects_untrusted_runtime_or_provider_config_shape() -> None:
    module_name = "ri402_invalid_provider_config_factory"
    module = _factory_module(module_name, "build", lambda: object())
    with patch.dict(sys.modules, {module_name: module}):
        with pytest.raises(ProductionBootstrapError, match="invalid boundary"):
            build_dependencies(
                {
                    "ROUTING_PROVIDER_CONFIG_FACTORY": f"{module_name}:build",
                    "ROUTING_RUNTIME_ENVIRONMENT": "PRODUCTION",
                }
            )
        with pytest.raises(ProductionBootstrapError, match="explicit local live"):
            build_dependencies(
                {
                    "ROUTING_PROVIDER_CONFIG_FACTORY": f"{module_name}:build",
                    "ROUTING_RUNTIME_ENVIRONMENT": "TEST",
                }
            )


def test_injected_baseline_requires_provider_evidence_persistence_and_atomic_enrichment() -> None:
    class NoNetwork:
        def send(self, request):
            raise AssertionError("composition must not perform provider I/O")

    registry = _enabled_transit_registry()
    config = ProviderAdapterSuiteConfig(capabilities=registry)
    baseline = ProductionCompositionDependencies(
        provider_config=config,
        persistence=InMemoryOptimizationPersistence(),
        capability_registry=registry,
        deployment_environment="staging",
    )
    suite = ProviderAdapterSuite(NoNetwork())
    with (
        patch.object(ProviderAdapterSuite, "from_config", return_value=suite) as build,
        patch(
            "routing_api.production_composition._executable_provider_operations",
            return_value=frozenset(
                {
                    ("KAKAO_PUBLIC_TRANSIT", "search_current"),
                    ("KAKAO_WALK", "route"),
                    ("KAKAO_DIRECTIONS", "route_current"),
                }
            ),
        ),
        patch(
            "routing_api.production_composition.PostgisMappingResolver",
            side_effect=AssertionError("baseline must not construct PostGIS mapping"),
        ) as mapping,
    ):
        use_case = build_injected_production_use_case(FakeClock(), baseline)

    assert isinstance(use_case, ProductionOptimizeRouteUseCase)
    assert use_case.baseline_degraded is True
    assert use_case.model_projection == ()
    assert type(use_case._dependencies.mapping) is UnavailableMappingResolver
    assert type(use_case._dependencies.eta_predictor) is UnavailableEtaPredictor
    assert type(use_case._dependencies.seat_predictor) is UnavailableSeatRiskPredictor
    build.assert_called_once_with(config)
    mapping.assert_not_called()

    for invalid in (
        replace(baseline, persistence=None),
        replace(baseline, deployment_environment=None),
        replace(baseline, mapping_database=object()),
        replace(baseline, eta_predictor=object()),
        replace(baseline, seat_predictor=object()),
    ):
        with patch.object(
            ProviderAdapterSuite,
            "from_config",
            side_effect=AssertionError("invalid boundary constructed provider suite"),
        ) as provider_build:
            unavailable = build_injected_production_use_case(FakeClock(), invalid)
        with pytest.raises(RoutingUnavailableError):
            unavailable.execute(None, None)
        provider_build.assert_not_called()


def test_dev_provenance_accepts_only_the_degraded_live_provider_baseline() -> None:
    class NoNetwork:
        def send(self, request):
            raise AssertionError("composition must not perform provider I/O")

    registry = _enabled_transit_registry()
    config = ProviderAdapterSuiteConfig(capabilities=registry)
    baseline = ProductionCompositionDependencies(
        provider_config=config,
        persistence=InMemoryOptimizationPersistence(),
        capability_registry=registry,
        deployment_environment="dev",
    )
    suite = ProviderAdapterSuite(NoNetwork())
    with (
        patch.object(ProviderAdapterSuite, "from_config", return_value=suite),
        patch(
            "routing_api.production_composition._executable_provider_operations",
            return_value=frozenset({("KAKAO_PUBLIC_TRANSIT", "search_current")}),
        ),
    ):
        use_case = build_injected_production_use_case(FakeClock(), baseline)
    assert isinstance(use_case, ProductionOptimizeRouteUseCase)
    assert use_case.baseline_degraded is True

    full_shape = replace(
        baseline,
        mapping_database=object(),
        eta_predictor=object(),
        seat_predictor=object(),
    )
    unavailable = build_injected_production_use_case(FakeClock(), full_shape)
    with pytest.raises(RoutingUnavailableError):
        unavailable.execute(None, None)


def test_production_baseline_reaches_graph_optimizer_but_never_claims_complete() -> None:
    clock = FakeClock(wall=datetime(2026, 8, 23, 22, 40, tzinfo=timezone.utc))
    base = fixture_fan_in_dependencies(fixture_scenario("R1"))
    dependencies = replace(
        base,
        mapping=UnavailableMappingResolver(),
        eta_predictor=UnavailableEtaPredictor(),
        seat_predictor=UnavailableSeatRiskPredictor(),
        persistence=InMemoryOptimizationPersistence(),
        fixture_only=False,
    )
    use_case = ProductionOptimizeRouteUseCase(
        clock,
        dependencies,
        capability_registry=_enabled_transit_registry(),
        executable_operations=frozenset(
            {("KAKAO_PUBLIC_TRANSIT", "search_current")}
        ),
        model_projection=(),
        deployment_environment="staging",
        baseline_degraded=True,
    )
    payload = _request_payload()
    payload["origin"]["coordinate"] = {"lon": 127.187456, "lat": 37.222345}
    payload["destination"]["coordinate"] = {"lon": 127.111159, "lat": 37.394761}
    payload["departureTime"] = "2026-08-24T07:40:00+09:00"
    context = RequestContext(
        "ri402-correlation",
        "ri402-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )

    original = RouteOptimizer.optimize_graph
    with patch(
        "routing_api.fanin_integration.RouteOptimizer.optimize_graph",
        autospec=True,
        side_effect=original,
    ) as optimizer:
        response = use_case.execute(OptimizeCommand(payload), context).response

    assert optimizer.called
    assert response["routes"]
    assert response["status"] == "PARTIAL"
    assert response["modelVersions"] == []
    assert response["computation"]["mappingVersion"] is None
    assert "BUS_MAPPING_LOW_CONFIDENCE" in response["warningCodes"]
    assert all(
        leg["busIntelligence"] is None
        for route in response["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    )
    assert any(
        "BUS_MAPPING_LOW_CONFIDENCE" in route["warningCodes"]
        for route in response["routes"]
        if any(leg["mode"] == "BUS" for leg in route["legs"])
    )


def test_baseline_degradation_is_scoped_to_routes_that_actually_use_bus() -> None:
    use_case = object.__new__(ProductionOptimizeRouteUseCase)
    use_case.baseline_degraded = True
    no_bus = SimpleNamespace(
        routes=(SimpleNamespace(legs=(SimpleNamespace(mode="TAXI"),)),)
    )
    with patch.object(
        CanonicalFanInOptimizeRouteUseCase,
        "_composition_is_verified",
        return_value=True,
    ) as base:
        assert use_case._composition_is_verified(object(), no_bus) is True
    base.assert_called_once()

    with_bus = SimpleNamespace(
        routes=(SimpleNamespace(legs=(SimpleNamespace(mode="BUS"),)),)
    )
    with patch.object(
        CanonicalFanInOptimizeRouteUseCase,
        "_composition_is_verified",
        side_effect=AssertionError("BUS baseline must not claim verified"),
    ):
        assert use_case._composition_is_verified(object(), with_bus) is False
