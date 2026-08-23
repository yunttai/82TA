from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from django.test.utils import override_settings
from bus_intelligence_core import (
    BusIntelligenceResult,
    ModelProvenance,
    SeatRiskPrediction,
    VerifiedEtaPredictor,
    VerifiedEtaPredictorAttestation,
    VerifiedSeatRiskPredictor,
    VerifiedSeatRiskPredictorAttestation,
)

from provider_core.adapters import FixtureTransitAdapter
from provider_core.capabilities import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
    foundation_capability_registry,
)
from provider_core.canonical import (
    CanonicalItinerary,
    Coordinate as ProviderCoordinate,
    CanonicalStop,
    DataOrigin,
    MoneyRange as ProviderMoneyRange,
    TimeEstimate as ProviderTimeEstimate,
    TransitDescriptor,
    TravelMode,
)
from provider_core.context import BusArrivalObservation, BusLocationObservation
from provider_core.envelope import ProviderStatus
from provider_core.named import (
    ProviderAdapterSuite,
    ProviderAdapterSuiteConfig,
    ProviderFixtureScenario,
)
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from routing_api.application import InMemoryIdempotencyStore, RoutingApiApplication
from routing_api.application import OptimizeCommand, RequestContext, RoutingUnavailableError
from routing_api.auth import Hs256ServiceBearerVerifier
from routing_api.capabilities import foundation_capability_projection
from routing_api.contract import CanonicalContractValidator
from routing_api.container import (
    _reset_application_composition_for_tests,
    build_application,
    get_application,
    register_production_dependencies,
)
from routing_api.fixture_integration import IntegratedFixtureOptimizeRouteUseCase
from routing_api.fanin_integration import (
    BusObservationQuery,
    CanonicalFanInOptimizeRouteUseCase,
    FanInDependencies,
    InMemoryOptimizationPersistence,
    SevenPatternFixtureOptimizeRouteUseCase,
    _ProviderOperationBudget,
    _expanded_provider_operation_units,
    _service_type,
    fixture_fan_in_dependencies,
)
from routing_domain import EnrichmentKind, ExactEnrichmentRequest
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.fixture_scenarios import FixtureFault
from routing_api.fanin_integration import _bus_result, _mapping_pipeline
from routing_api.settings import _strict_boolean
from routing_api.production_composition import (
    FallbackTransitSearch,
    PostgisMappingResolver,
    ProductionCompositionDependencies,
    ProductionOptimizeRouteUseCase,
    build_default_production_use_case,
    build_injected_production_use_case,
)
from routing_api.tests.test_api import FakeClock, SECRET, _request_payload, _token

_SCENARIO_ENDPOINTS = {
    "R1": ((127.187456, 37.222345), (127.111159, 37.394761)),
    "R2": ((127.111159, 37.394761), (127.187456, 37.222345)),
    "R3": ((127.051, 37.289), (127.111159, 37.394761)),
    "R4": ((127.111159, 37.394761), (127.051, 37.289)),
}
_SCENARIO_DEPARTURES = {
    "R1": "2026-08-24T07:40:00+09:00",
    "R2": "2026-08-24T18:10:00+09:00",
    "R3": "2026-08-24T08:05:00+09:00",
    "R4": "2026-08-24T19:20:00+09:00",
}


def _verified_model_pair(
    environment: str = "staging",
) -> tuple[VerifiedEtaPredictor, VerifiedSeatRiskPredictor]:
    """Build exact Bus-core wrapper instances without importing worker code."""

    class Builder:
        def __init__(self, family: str, schema: str, names: tuple[str, ...]) -> None:
            self.family = family
            self.feature_schema_version = schema
            self.feature_names = names

        def build(self, value):
            return None

    class Runtime:
        def __init__(
            self,
            family: str,
            version: str,
            artifact_sha256: str,
            artifact_format: str,
            calibration_sha256: str,
        ) -> None:
            self.family = family
            self.model_version = version
            self.artifact_sha256 = artifact_sha256
            self.artifact_format = artifact_format
            self.calibration_sha256 = calibration_sha256

        def predict(self, value):
            return None

    eta_names = ("eta_feature", "missing_flags")
    seat_names = ("seat_feature", "missing_flags")
    eta_attestation = VerifiedEtaPredictorAttestation(
        family="ETA",
        model_version="eta-production-1",
        full_feature_schema_version="eta-full-v1",
        ordered_feature_names=eta_names,
        artifact_sha256="a" * 64,
        verified_artifact_sha256="a" * 64,
        artifact_format="LIGHTGBM_TEXT",
        deployment_id="eta-deployment-1",
        deployment_environment=environment,
        deployment_state="ACTIVE",
        readiness="ACTIVE",
        calibrated=True,
        calibration_method="CONFORMAL",
        calibration_sha256="b" * 64,
        verified_calibration_sha256="b" * 64,
    )
    seat_attestation = VerifiedSeatRiskPredictorAttestation(
        family="SEAT_RISK",
        model_version="seat-production-1",
        full_feature_schema_version="seat-full-v1",
        ordered_feature_names=seat_names,
        artifact_sha256="c" * 64,
        verified_artifact_sha256="c" * 64,
        artifact_format="LIGHTGBM_JSON",
        deployment_id="seat-deployment-1",
        deployment_environment=environment,
        deployment_state="ACTIVE",
        readiness="ACTIVE",
        calibrated=True,
        calibration_method="ISOTONIC",
        calibration_sha256="d" * 64,
        verified_calibration_sha256="d" * 64,
    )
    eta = VerifiedEtaPredictor(
        Builder("ETA", "eta-full-v1", eta_names),
        Runtime("ETA", "eta-production-1", "a" * 64, "LIGHTGBM_TEXT", "b" * 64),
        eta_attestation,
        expected_feature_schema_version="eta-full-v1",
        expected_feature_names=eta_names,
        required_environment=environment,
    )
    seat = VerifiedSeatRiskPredictor(
        Builder("SEAT_RISK", "seat-full-v1", seat_names),
        Runtime(
            "SEAT_RISK",
            "seat-production-1",
            "c" * 64,
            "LIGHTGBM_JSON",
            "d" * 64,
        ),
        seat_attestation,
        expected_feature_schema_version="seat-full-v1",
        expected_feature_names=seat_names,
        required_environment=environment,
    )
    return eta, seat


def _enabled_transit_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        (
            Capability(
                "KAKAO_PUBLIC_TRANSIT",
                "search_current",
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )


def test_fixture_opt_in_setting_rejects_ambiguous_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROUTING_TEST_BOOLEAN", "yes")
    with pytest.raises(ImproperlyConfigured, match="must be exactly true or false"):
        _strict_boolean("ROUTING_TEST_BOOLEAN")


@pytest.mark.parametrize(
    ("route_type", "expected"),
    [
        ("GENERAL_BUS", "GENERAL"),
        ("SEAT_BUS", "SEATED"),
        ("직행좌석", "SEATED"),
        ("unverified-premium", None),
        (None, None),
    ],
)
def test_route_type_service_classification_is_explicit_and_fail_safe(
    route_type, expected
) -> None:
    assert _service_type(route_type) == expected


def _application(scenario_id: str, clock: FakeClock) -> RoutingApiApplication:
    return RoutingApiApplication(
        verifier=Hs256ServiceBearerVerifier(
            secret=SECRET,
            issuer="service-api",
            audience="routing-api",
            now=clock.now,
        ),
        contract=CanonicalContractValidator(),
        use_case=IntegratedFixtureOptimizeRouteUseCase(
            fixture_scenario(scenario_id), clock
        ),
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version="fixture-integration-test",
        capability_projection=foundation_capability_projection(),
        backend_state=f"fixture-only:{scenario_id}",
    )


def _post(
    scenario_id: str,
    requested: list[str] | None = None,
    departure: str | None = None,
    *,
    allow_taxi_bridge: bool | None = None,
    taxi_budget: int | None = None,
):
    clock = FakeClock()
    app = _application(scenario_id, clock)
    payload = _request_payload()
    optional_faults = {"MAPPING_LOW", "ETA_UNAVAILABLE", "SEAT_UNAVAILABLE"}
    origin, destination = _SCENARIO_ENDPOINTS.get(
        scenario_id,
        _SCENARIO_ENDPOINTS["R1"]
        if scenario_id in optional_faults
        else ((127.1, 37.4), (127.11, 37.41)),
    )
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}  # type: ignore[index]
    payload["destination"]["coordinate"] = {  # type: ignore[index]
        "lon": destination[0],
        "lat": destination[1],
    }
    if scenario_id in _SCENARIO_DEPARTURES:
        payload["departureTime"] = _SCENARIO_DEPARTURES[scenario_id]
    elif scenario_id in optional_faults:
        payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    if departure is not None:
        payload["departureTime"] = departure
    if requested is not None:
        payload["requestedRecommendations"] = requested
    if allow_taxi_bridge is not None:
        payload["constraints"]["allowTaxiBridge"] = allow_taxi_bridge  # type: ignore[index]
    if taxi_budget is not None:
        payload["constraints"]["taxiBudget"]["maxAmount"] = taxi_budget  # type: ignore[index]
    payload["requestId"] = f"01J{scenario_id.replace('_', '')}FIXTURE"
    headers = {
        "HTTP_AUTHORIZATION": f"Bearer {_token(clock)}",
        "HTTP_X_CORRELATION_ID": f"corr-{scenario_id.lower()}",
        "HTTP_X_REQUEST_DEADLINE": (clock.now() + timedelta(seconds=6)).isoformat(),
        "HTTP_IDEMPOTENCY_KEY": f"idem-{scenario_id.lower()}-fixture",
    }
    with patch("routing_api.views.get_application", return_value=app):
        response = Client().post(
            "/v1/routes/optimize",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )
    return response, payload, app


class _CausalProviderPorts:
    """Injected canonical envelopes with one independently variable signal."""

    _TOKEN = "veh_" + "a" * 64

    def __init__(
        self,
        base,
        *,
        transit_seconds: int | None = None,
        taxi_upper_krw: int | None = None,
        eta_seconds: int = 240,
        remaining_seats: int | None = 7,
    ) -> None:
        self._base = base
        self._transit_seconds = transit_seconds
        self._taxi_upper = taxi_upper_krw
        self._eta_seconds = eta_seconds
        self._remaining_seats = remaining_seats
        self.queries: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
        self.request_departures: list[
            tuple[str, tuple[float, float], tuple[float, float], datetime]
        ] = []

    @property
    def transit_call_cap(self):
        return self._base.transit_call_cap

    @property
    def last_transit_attempt_count(self):
        return self._base.last_transit_attempt_count

    @staticmethod
    def _replace_leg(envelope, transform):
        itinerary = envelope.payload[0]
        leg = transform(itinerary.legs[0])
        return replace(
            envelope,
            payload=(replace(itinerary, legs=(leg,)),),
            normalized_count=1,
        )

    def transit(self, request, *, deadline):
        envelope = self._base.transit(request, deadline=deadline)
        origin = (request.origin.lon, request.origin.lat)
        destination = (request.destination.lon, request.destination.lat)
        self.queries.append(("TRANSIT", origin, destination))
        self.request_departures.append(
            ("TRANSIT", origin, destination, request.departure_time)
        )
        r1_origin, r1_destination = _SCENARIO_ENDPOINTS["R1"]
        hub_a = (
            r1_origin[0] + (r1_destination[0] - r1_origin[0]) * 0.35,
            r1_origin[1] + (r1_destination[1] - r1_origin[1]) * 0.35,
        )
        bridge_left = (
            r1_origin[0] + (r1_destination[0] - r1_origin[0]) * 0.42,
            r1_origin[1] + (r1_destination[1] - r1_origin[1]) * 0.42,
        )
        upstream = (
            r1_origin[0] + (r1_destination[0] - r1_origin[0]) * 0.12,
            r1_origin[1] + (r1_destination[1] - r1_origin[1]) * 0.12,
        )
        if (origin, destination) == (r1_origin, r1_destination):
            if self._transit_seconds is None:
                return envelope
            return self._replace_leg(
                envelope,
                lambda leg: replace(
                    leg,
                    duration=ProviderTimeEstimate(
                        self._transit_seconds,
                        self._transit_seconds + 300,
                        DataOrigin.PROVIDER_ESTIMATE,
                    ),
                ),
            )
        mode = (
            TravelMode.BUS
            if origin in {r1_origin, upstream}
            and destination in {r1_destination, bridge_left}
            else TravelMode.SUBWAY
        )
        result = self._request_scoped_route(
            envelope,
            request,
            mode,
            duration_seconds=self._transit_seconds,
        )
        itinerary = result.payload[0]
        leg = itinerary.legs[0]
        if origin == upstream and destination == r1_destination:
            baseline = envelope.payload[0].legs[0].transit
            leg = replace(
                leg,
                transit=TransitDescriptor(
                    route_label=baseline.route_label,
                    external_route_id=baseline.external_route_id,
                    route_type=baseline.route_type,
                    direction=baseline.direction,
                    branch_id=baseline.branch_id,
                    boarding_sequence=2,
                    alighting_sequence=27,
                ),
            )
        bridge_right = (
            r1_origin[0] + (r1_destination[0] - r1_origin[0]) * 0.58,
            r1_origin[1] + (r1_destination[1] - r1_origin[1]) * 0.58,
        )
        if origin == bridge_right and destination == r1_destination:
            start = request.departure_time + timedelta(hours=3)
            leg = replace(
                leg,
                expected_start_at=start,
                expected_end_at=start + timedelta(seconds=leg.duration.p50_seconds),
            )
        return replace(result, payload=(replace(itinerary, legs=(leg,)),))

    def walk(self, request, *, deadline):
        self.queries.append(("WALK", (request.origin.lon, request.origin.lat), (request.destination.lon, request.destination.lat)))
        self.request_departures.append(
            (
                "WALK",
                (request.origin.lon, request.origin.lat),
                (request.destination.lon, request.destination.lat),
                request.departure_time,
            )
        )
        return self._request_scoped_route(
            self._base.walk(request, deadline=deadline),
            request,
            TravelMode.WALK,
        )

    def taxi(self, request, *, deadline):
        envelope = self._base.taxi(request, deadline=deadline)
        self.queries.append(("TAXI", (request.origin.lon, request.origin.lat), (request.destination.lon, request.destination.lat)))
        self.request_departures.append(
            (
                "TAXI",
                (request.origin.lon, request.origin.lat),
                (request.destination.lon, request.destination.lat),
                request.departure_time,
            )
        )
        return self._request_scoped_route(
            envelope, request, TravelMode.TAXI, fare_upper=self._taxi_upper
        )

    def _request_scoped_route(
        self,
        envelope,
        request,
        mode,
        *,
        duration_seconds=None,
        fare_upper=None,
    ):
        def transform(leg):
            duration = leg.duration
            if duration_seconds is not None:
                duration = ProviderTimeEstimate(
                    duration_seconds,
                    duration_seconds + 300,
                    DataOrigin.PROVIDER_ESTIMATE,
                )
            fare = leg.fare
            if fare_upper is not None:
                fare = ProviderMoneyRange(
                    fare_upper, fare_upper, fare_upper, DataOrigin.PROVIDER_ESTIMATE
                )
            transit = None
            if mode in {TravelMode.BUS, TravelMode.SUBWAY, TravelMode.GTX, TravelMode.TRAIN}:
                transit = TransitDescriptor(
                    route_label=f"CAUSAL-{mode.value}",
                    external_route_id=(
                        f"causal-{mode.value.lower()}-"
                        f"{request.origin.lon:.6f}-{request.destination.lon:.6f}"
                    ),
                    route_type="SEAT_BUS" if mode is TravelMode.BUS else None,
                    direction="OUTBOUND",
                    boarding_sequence=1,
                    alighting_sequence=2,
                )
            return replace(
                leg,
                mode=mode,
                from_stop=CanonicalStop(
                    "causal-from",
                    ProviderCoordinate(request.origin.lon, request.origin.lat),
                    external_id=f"causal-from-{request.origin.lon:.6f}",
                    sequence=1,
                ),
                to_stop=CanonicalStop(
                    "causal-to",
                    ProviderCoordinate(request.destination.lon, request.destination.lat),
                    external_id=f"causal-to-{request.destination.lon:.6f}",
                    sequence=2,
                ),
                duration=duration,
                fare=fare,
                transit=transit,
                geometry=(
                    ProviderCoordinate(request.origin.lon, request.origin.lat),
                    ProviderCoordinate(request.destination.lon, request.destination.lat),
                ),
                expected_start_at=request.departure_time,
                expected_end_at=request.departure_time
                + timedelta(seconds=duration.p50_seconds),
            )

        result = self._replace_leg(envelope, transform)
        fingerprint = sha256(
            (
                f"{mode.value}:{request.origin.lon:.6f},{request.origin.lat:.6f}>"
                f"{request.destination.lon:.6f},{request.destination.lat:.6f}:"
                f"{request.departure_time.astimezone(timezone.utc).isoformat()}"
            ).encode("utf-8")
        ).hexdigest()
        return replace(result, fingerprint=fingerprint)

    def arrivals(self, query, *, deadline):
        envelope = self._base.arrivals(query, deadline=deadline)
        value = BusArrivalObservation(
            route_external_id=query.route_id,
            station_external_id=query.boarding_station_id,
            eta_seconds=self._eta_seconds,
            remaining_seats=self._remaining_seats,
            observed_at=query.evaluated_at,
            vehicle_token=self._TOKEN,
        )
        return replace(
            envelope,
            observed_at=query.evaluated_at,
            status=ProviderStatus.OK,
            normalized_count=1,
            payload=(value,),
        )

    def locations(self, query, *, deadline):
        envelope = self._base.locations(query, deadline=deadline)
        value = BusLocationObservation(
            route_external_id=query.route_id,
            vehicle_token=self._TOKEN,
            stop_sequence=1,
            coordinate=ProviderCoordinate(127.15, 37.30),
            observed_at=query.evaluated_at,
        )
        return replace(
            envelope,
            observed_at=query.evaluated_at,
            status=ProviderStatus.OK,
            normalized_count=1,
            payload=(value,),
        )


def _causal_response(*, persistence=None, **provider_changes):
    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    dependencies = replace(
        base,
        providers=_CausalProviderPorts(base.providers, **provider_changes),
        persistence=persistence,
    )
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario, clock, dependencies=dependencies
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    payload["constraints"]["taxiBudget"]["maxAmount"] = 20_000
    payload["constraints"]["allowTaxiBridge"] = True
    context = RequestContext(
        "causal-correlation",
        "causal-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    return use_case.execute(OptimizeCommand(payload), context).response


def _mapped_bus(response):
    return next(
        leg
        for route in response["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS" and leg["busIntelligence"] is not None
    )


def test_exact_provider_queries_are_segment_scoped_and_generate_all_seven_patterns() -> None:
    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = _CausalProviderPorts(base.providers, taxi_upper_krw=2_500)
    dependencies = replace(base, providers=providers)
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario, clock, dependencies=dependencies
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    payload["constraints"]["allowTaxiBridge"] = True
    context = RequestContext(
        "segment-correlation",
        "segment-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    outcome = use_case.execute(OptimizeCommand(payload), context)
    response = outcome.response
    expected = {
        "TRANSIT_ONLY",
        "TAXI_TRANSIT",
        "TRANSIT_TAXI",
        "TAXI_TRANSIT_TAXI",
        "TAXI_ONLY",
        "UPSTREAM_STOP_TAXI_TRANSIT",
        "TRANSIT_TAXI_BRIDGE_TRANSIT",
    }
    assert set(use_case.trace.exact_patterns) == expected
    assert CanonicalContractValidator().validate_optimize_response(response) == ()
    assert any(
        kind == "TAXI" and start != origin and end != destination
        for kind, start, end in providers.queries
    )
    assert any(kind == "TRANSIT" and (start, end) != (origin, destination) for kind, start, end in providers.queries)
    assert response["computation"]["cache"]["exactEnrichmentResolved"] is True


def test_exact_quotes_use_candidate_p50_entry_and_do_not_reuse_later_movement() -> None:
    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = _CausalProviderPorts(base.providers, taxi_upper_krw=2_500)
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario, clock, dependencies=replace(base, providers=providers)
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    payload["constraints"]["allowTaxiBridge"] = True
    context = RequestContext(
        "entry-time-correlation",
        "entry-time-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    use_case.execute(OptimizeCommand(payload), context)

    grouped: dict[
        tuple[str, tuple[float, float], tuple[float, float]], set[datetime]
    ] = {}
    for kind, start, end, departure_at in providers.request_departures:
        grouped.setdefault((kind, start, end), set()).add(departure_at)
    repeated = [values for values in grouped.values() if len(values) > 1]
    assert repeated, "same movement at distinct candidate entry times was reused"
    assert any(max(values) > min(values) for values in repeated)
    taxi_departures = [
        value
        for kind, start, _, value in providers.request_departures
        if kind == "TAXI" and start == origin
    ]
    assert taxi_departures
    assert all(
        value > datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"])
        for value in taxi_departures
    )


def test_taxi_movement_is_never_reused_before_dispatch_identity_is_known() -> None:
    class TaxiStep:
        mode = "TAXI"
        from_ref = "origin"
        to_ref = "destination"

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    use_case = SevenPatternFixtureOptimizeRouteUseCase(scenario, clock)
    departure = datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"])
    assert use_case._reusable_canonical_step(  # type: ignore[arg-type]
        TaxiStep(),
        departure,
        departure,
        {("TAXI", "origin", "destination"): object()},
        {("TAXI", "origin", "destination"): object()},
    ) is None


def test_same_depth_exact_provider_calls_are_bounded_and_concurrent() -> None:
    class DelayedProviders(_CausalProviderPorts):
        def __init__(self, base):
            super().__init__(base, taxi_upper_krw=2_500)
            self._guard = threading.Lock()
            self._active = 0
            self.maximum_active = 0

        def _delay(self):
            with self._guard:
                self._active += 1
                self.maximum_active = max(self.maximum_active, self._active)
            sleep(0.05)
            with self._guard:
                self._active -= 1

        def transit(self, request, *, deadline):
            if (
                (request.origin.lon, request.origin.lat),
                (request.destination.lon, request.destination.lat),
            ) != _SCENARIO_ENDPOINTS["R1"]:
                self._delay()
            return super().transit(request, deadline=deadline)

        def walk(self, request, *, deadline):
            self._delay()
            return super().walk(request, deadline=deadline)

        def taxi(self, request, *, deadline):
            self._delay()
            return super().taxi(request, deadline=deadline)

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = DelayedProviders(base.providers)
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario, clock, dependencies=replace(base, providers=providers)
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    payload["constraints"]["allowTaxiBridge"] = True
    context = RequestContext(
        "parallel-correlation",
        "parallel-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    use_case.execute(OptimizeCommand(payload), context)
    assert 2 <= providers.maximum_active <= 8


def test_optional_exact_calls_do_not_start_inside_serialization_reserve() -> None:
    class StartCountingProviders(_CausalProviderPorts):
        def __init__(self, base):
            super().__init__(base)
            self.exact_starts = 0

        def transit(self, request, *, deadline):
            if (
                (request.origin.lon, request.origin.lat),
                (request.destination.lon, request.destination.lat),
            ) != _SCENARIO_ENDPOINTS["R1"]:
                self.exact_starts += 1
            return super().transit(request, deadline=deadline)

        def walk(self, request, *, deadline):
            self.exact_starts += 1
            return super().walk(request, deadline=deadline)

        def taxi(self, request, *, deadline):
            self.exact_starts += 1
            return super().taxi(request, deadline=deadline)

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = StartCountingProviders(base.providers)
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario, clock, dependencies=replace(base, providers=providers)
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "start-gate-correlation",
        "start-gate-idempotency",
        clock.now() + timedelta(seconds=1.7),
        clock.now() + timedelta(seconds=1.7),
        True,
        threading.Event(),
    )
    outcome = use_case.execute(OptimizeCommand(payload), context)
    assert outcome.response["routes"]
    assert providers.exact_starts == 0
    assert use_case.trace.provider_call_count == 1


def test_production_observation_as_of_is_not_future_journey_departure() -> None:
    class AsOfProviders(_CausalProviderPorts):
        def __init__(self, base):
            super().__init__(base, eta_seconds=240)
            self.observation_times: list[datetime] = []

        def arrivals(self, query, *, deadline):
            self.observation_times.append(query.evaluated_at)
            return super().arrivals(query, deadline=deadline)

    class MappingTimes:
        def __init__(self, delegate):
            self._delegate = delegate
            self.values: list[datetime] = []

        def __call__(self, evidence, evaluated_at):
            self.values.append(evaluated_at)
            return self._delegate(evidence, evaluated_at)

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = AsOfProviders(base.providers)
    mapping = MappingTimes(base.mapping)
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "future-as-of",
        clock,
        dependencies=replace(
            base,
            providers=providers,
            mapping=mapping,
            fixture_only=False,
        ),
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    departure = datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"])
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = departure.isoformat()
    context = RequestContext(
        "future-as-of-correlation",
        "future-as-of-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), context).response
    assert providers.observation_times
    assert set(providers.observation_times) == {clock.now()}
    assert mapping.values and all(value >= departure for value in mapping.values)
    assert all(
        leg["busIntelligence"] is None
        for route in response["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    )


def test_fan_in_dependency_default_is_production_safe_not_fixture_time_travel() -> None:
    fixture = fixture_fan_in_dependencies(fixture_scenario("R1"))
    dependencies = FanInDependencies(
        providers=fixture.providers,
        mapping=fixture.mapping,
        eta_predictor=fixture.eta_predictor,
        seat_predictor=fixture.seat_predictor,
    )
    assert dependencies.fixture_only is False
    assert fixture.fixture_only is True


def test_provider_duration_is_causal_for_exact_transit_timing() -> None:
    faster = _causal_response(transit_seconds=600)
    slower = _causal_response(transit_seconds=1_200)
    fast_leg = _mapped_bus(faster)
    slow_leg = _mapped_bus(slower)
    assert slow_leg["duration"]["p50Seconds"] - fast_leg["duration"]["p50Seconds"] == 600


def test_provider_fare_is_causal_for_taxi_cost_and_strict_feasibility() -> None:
    affordable = _causal_response(taxi_upper_krw=2_500)
    expensive = _causal_response(taxi_upper_krw=12_000)
    assert any(route["taxiCost"]["upper"] == 2_500 for route in affordable["routes"])
    assert all(route["taxiCost"]["upper"] <= 20_000 for route in expensive["routes"])
    assert not any(
        route["pattern"] == "TAXI_TRANSIT_TAXI" for route in expensive["routes"]
    )


def test_gbis_eta_is_causal_and_future_or_wrong_route_is_unobserved() -> None:
    early = _causal_response(eta_seconds=120)
    late = _causal_response(eta_seconds=600)
    assert _mapped_bus(late)["busIntelligence"]["expectedWaitSeconds"] > _mapped_bus(early)["busIntelligence"]["expectedWaitSeconds"]
    default, _, _ = _post("R1")
    assert all(
        leg["busIntelligence"] is None
        for route in default.json()["routes"]
        for leg in route["legs"]
    )


def test_seat_observation_changes_seat_risk_without_changing_eta_provenance() -> None:
    seats_available = _causal_response(remaining_seats=9)
    seats_low = _causal_response(remaining_seats=1)
    available_bus = _mapped_bus(seats_available)["busIntelligence"]
    low_bus = _mapped_bus(seats_low)["busIntelligence"]
    assert low_bus["candidateVehicles"][0]["seatRiskAtBoarding"]["noSeatProbability"] > available_bus["candidateVehicles"][0]["seatRiskAtBoarding"]["noSeatProbability"]
    assert low_bus["candidateVehicles"][0]["eta"] == available_bus["candidateVehicles"][0]["eta"]
    assert seats_low["modelVersions"] == [
        {"purpose": "SEAT_RISK", "version": "seat-fixture-0.1.0"}
    ]


def test_subway_only_baseline_routes_without_mapping_or_gbis() -> None:
    class SubwayProviders(_CausalProviderPorts):
        def transit(self, request, *, deadline):
            envelope = self._base.transit(request, deadline=deadline)
            self._last_transit_attempt_count = 1
            return self._request_scoped_route(
                envelope, request, TravelMode.SUBWAY, duration_seconds=900
            )

        def arrivals(self, query, *, deadline):
            raise AssertionError("subway-only route must not call GBIS arrivals")

        def locations(self, query, *, deadline):
            raise AssertionError("subway-only route must not call GBIS locations")

    class NoMapping:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, evidence, evaluated_at):
            self.calls += 1
            raise AssertionError("subway-only route must not invoke mapping")

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    mapping = NoMapping()
    dependencies = replace(
        base,
        providers=SubwayProviders(base.providers, taxi_upper_krw=2_500),
        mapping=mapping,
    )
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "subway-only", clock, dependencies=dependencies
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "subway-correlation", "subway-idempotency",
        clock.now() + timedelta(seconds=6), clock.now() + timedelta(seconds=6),
        True, threading.Event(),
    )
    outcome = use_case.execute(OptimizeCommand(payload), context)
    response = outcome.response
    assert response["routes"]
    assert any(
        leg["mode"] == "SUBWAY"
        for route in response["routes"] for leg in route["legs"]
    )
    assert all(
        leg["busIntelligence"] is None
        for route in response["routes"] for leg in route["legs"]
    )
    assert outcome.optional_enrichment_complete is True
    assert not any(code.startswith("BUS_") for code in response["warningCodes"])
    assert response["modelVersions"] == []
    assert mapping.calls == 0


def test_mapping_timeout_is_fail_soft_for_valid_transit_route() -> None:
    class TimeoutMapping:
        def __call__(self, evidence, evaluated_at):
            raise TimeoutError("routing PostGIS timeout")

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    dependencies = replace(
        base,
        providers=_CausalProviderPorts(base.providers, taxi_upper_krw=2_500),
        mapping=TimeoutMapping(),
    )
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario, clock, dependencies=dependencies
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "mapping-timeout-correlation", "mapping-timeout-idempotency",
        clock.now() + timedelta(seconds=6), clock.now() + timedelta(seconds=6),
        True, threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), context).response
    assert response["routes"], use_case.trace
    assert response["routes"]
    assert response["computation"]["mappingVersion"] is None
    assert all(
        leg["busIntelligence"] is None
        for route in response["routes"] for leg in route["legs"]
    )
    assert CanonicalContractValidator().validate_optimize_response(response) == ()


@pytest.mark.parametrize("scenario_id", ["R1", "R2", "R3", "R4"])
def test_r1_r4_runs_full_fixture_fan_in_with_contract_valid_projection(
    scenario_id: str,
) -> None:
    response, request, app = _post(scenario_id)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "PARTIAL"
    assert body["contractVersion"] == "1.0"
    assert CanonicalContractValidator().validate_optimize_response(body) == ()

    route_ids = {route["routeId"] for route in body["routes"]}
    assert route_ids
    assert set(body["paretoRouteIds"]) <= route_ids
    assert all(value is None or value in route_ids for value in body["recommendations"].values())
    route = next(
        route
        for route in body["routes"]
        if any(
            leg["mode"] == "BUS"
            and leg["from"]["canonicalStopId"] is not None
            for leg in route["legs"]
        )
    )
    assert route["totalDuration"]["p90Seconds"] >= route["totalDuration"]["p50Seconds"]
    assert route["taxiCost"]["upper"] <= request["constraints"]["taxiBudget"]["maxAmount"]
    assert "PROVIDER_PARTIAL_FAILURE" not in body["warningCodes"]
    first_leg = next(
        leg
        for leg in route["legs"]
        if leg["mode"] == "BUS" and leg["from"]["canonicalStopId"] is not None
    )
    suffix = int(scenario_id[-1]) * 100
    assert first_leg["from"]["canonicalStopId"].endswith(f"{suffix + 1:012d}")
    assert first_leg["to"]["canonicalStopId"].endswith(f"{suffix + 2:012d}")
    assert first_leg["from"]["providerStopId"] == f"sanitized-{scenario_id.lower()}-stop-origin"
    assert first_leg["to"]["providerStopId"] == f"sanitized-{scenario_id.lower()}-stop-destination"
    assert first_leg["from"]["coordinate"] == request["origin"]["coordinate"]
    assert first_leg["to"]["coordinate"] == request["destination"]["coordinate"]
    start = datetime.fromisoformat(first_leg["expectedStartAt"])
    end = datetime.fromisoformat(first_leg["expectedEndAt"])
    assert start <= end
    assert int((end - start).total_seconds()) == first_leg["duration"]["p50Seconds"]

    # The provider-core named GBIS fixture is for a different route/time.  The
    # request-scoped join rejects it instead of replaying it as future evidence.
    assert first_leg["busIntelligence"] is None
    assert "BUS_DATA_UNAVAILABLE" in body["warningCodes"]
    assert body["modelVersions"] == []
    provenance = {item["provider"] for item in route["provenance"]}
    assert "SANITIZED_TRANSIT_FIXTURE" in provenance
    assert any(value.startswith("TRANSPORT_MAPPING/") for value in provenance)
    assert not any(value.startswith("BUS_ETA_FIXTURE/") for value in provenance)
    assert not any(value.startswith("SEAT_RISK_FIXTURE/") for value in provenance)

    fixture_status = next(
        item for item in body["providerStatus"] if item["provider"] == "SANITIZED_TRANSIT_FIXTURE"
    )
    assert fixture_status["status"] == "OK"
    live_statuses = [
        item
        for item in body["providerStatus"]
        if item["provider"] != "SANITIZED_TRANSIT_FIXTURE"
        and not item["provider"].startswith("FIXTURE::")
    ]
    assert live_statuses and all(item["status"] == "DISABLED" for item in live_statuses)
    capabilities = app.capabilities()
    assert not any(capabilities["features"].values())


def test_r1_r4_have_distinct_topology_and_continuous_corridor_endpoints() -> None:
    route_ids = set()
    for scenario_id in ("R1", "R2", "R3", "R4"):
        response, request, _ = _post(scenario_id)
        assert response.status_code == 200, response.content
        for route in response.json()["routes"]:
            route_ids.add(route["routeId"])
            legs = route["legs"]
            assert legs[0]["from"]["coordinate"] == request["origin"]["coordinate"]
            assert legs[-1]["to"]["coordinate"] == request["destination"]["coordinate"]
            assert all(
                previous["to"]["coordinate"] == following["from"]["coordinate"]
                for previous, following in zip(legs, legs[1:])
            )
    assert len(route_ids) >= 4


def test_named_fixture_drops_unresolved_segments_after_coarse_plan() -> None:
    # The normalized named taxi fixture upper quote is 7,800 KRW, so two-taxi
    # patterns require at least 15,600 KRW under the strict upper-sum rule.
    response, request, app = _post(
        "R1", allow_taxi_bridge=True, taxi_budget=16_000
    )
    assert response.status_code == 200, response.content
    trace = app._use_case.trace  # type: ignore[attr-defined]
    expected = {
        "TRANSIT_ONLY",
        "TAXI_TRANSIT",
        "TRANSIT_TAXI",
        "TAXI_TRANSIT_TAXI",
        "TAXI_ONLY",
        "UPSTREAM_STOP_TAXI_TRANSIT",
        "TRANSIT_TAXI_BRIDGE_TRANSIT",
    }
    assert set(trace.coarse_patterns) == expected
    assert set(trace.exact_patterns) == {"TRANSIT_ONLY"}
    assert trace.exact_plan
    assert len(trace.exact_plan) == len({item[0] for item in trace.exact_plan})
    assert {kind for _, kind in trace.exact_plan} >= {
        "WALK", "TAXI", "MAPPING", "BUS_INTELLIGENCE"
    }
    assert trace.provider_call_count <= 64
    # Authoritative candidate-chain exactification settles only operations that
    # actually started; descendants of an unresolved step are never invoked.
    assert trace.provider_call_count == 10
    assert response.json()["computation"]["cache"]["providerCallCount"] == trace.provider_call_count
    fixture_operations = [
        item
        for item in response.json()["routes"][0]["provenance"]
        if item["provider"].startswith("FIXTURE::")
    ]
    assert trace.provider_call_count == 1 + len(fixture_operations)
    assert "COARSE_TAXI_BUDGET" in trace.rejected_reasons
    assert "TAXI_BRIDGE_CONNECTION_INFEASIBLE" in trace.rejected_reasons
    assert "UPSTREAM_ROUTE_DIRECTION_MISMATCH" in trace.rejected_reasons
    assert response.json()["computation"]["cache"]["exactEnrichmentResolved"] is True
    registry_operations = {
        (item.provider, item.operation) for item in foundation_capability_registry().all()
    }
    live_statuses = {
        (item["provider"], item["operation"]): item["status"]
        for item in response.json()["providerStatus"]
        if (item["provider"], item["operation"]) in registry_operations
    }
    assert len(registry_operations) == 14
    assert live_statuses == {key: "DISABLED" for key in registry_operations}
    assert all(
        route["taxiCost"]["upper"]
        <= request["constraints"]["taxiBudget"]["maxAmount"]
        for route in response.json()["routes"]
    )


def test_expanded_bus_operations_are_rejected_atomically_at_cap_boundary() -> None:
    budget = _ProviderOperationBudget(64)
    budget.reserve(63)
    request = ExactEnrichmentRequest(
        "bus:boundary",
        EnrichmentKind.BUS_INTELLIGENCE,
        "boarding-stop",
        "target-stop",
    )
    assert _expanded_provider_operation_units(request) == 2
    with pytest.raises(RoutingUnavailableError, match="operation cap"):
        budget.reserve(_expanded_provider_operation_units(request))
    assert budget.consumed == 63


def test_transit_fallback_worst_case_is_reserved_before_first_attempt() -> None:
    class ThreeAttemptPorts(_CausalProviderPorts):
        def __init__(self, base):
            super().__init__(base)
            self.calls = 0

        @property
        def transit_call_cap(self):
            return 3

        def transit(self, request, *, deadline):
            self.calls += 1
            return super().transit(request, deadline=deadline)

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = ThreeAttemptPorts(base.providers)
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario,
        clock,
        dependencies=replace(base, providers=providers),
        provider_operation_cap=2,
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "fallback-cap-correlation", "fallback-cap-idempotency",
        clock.now() + timedelta(seconds=6), clock.now() + timedelta(seconds=6),
        True, threading.Event(),
    )
    with pytest.raises(RoutingUnavailableError, match="operation cap"):
        use_case.execute(OptimizeCommand(payload), context)
    assert providers.calls == 0


def test_cap_is_reserved_before_any_gbis_fixture_operation(monkeypatch) -> None:
    from provider_core.named import GbisAdapter

    calls: list[str] = []
    original = GbisAdapter.fixture

    def recording_fixture(self, operation, scenario):
        calls.append(operation)
        return original(self, operation, scenario)

    monkeypatch.setattr(GbisAdapter, "fixture", recording_fixture)
    clock = FakeClock()
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        fixture_scenario("R1"), clock, provider_operation_cap=2
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}  # type: ignore[index]
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}  # type: ignore[index]
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "cap-correlation",
        "cap-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    with pytest.raises(RoutingUnavailableError, match="operation cap"):
        use_case.execute(OptimizeCommand(payload), context)
    assert calls == []


def test_mapping_pipeline_result_is_the_only_bus_enrichment_gate() -> None:
    clock = FakeClock()
    scenario = fixture_scenario("R1")
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}  # type: ignore[index]
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}  # type: ignore[index]
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    from provider_core.adapters import FixtureScenario, FixtureTransitAdapter
    from provider_core.canonical import Coordinate
    from provider_core.requests import TransitSearchRequest
    from provider_core.resilience import Deadline

    departure = datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"])
    envelope = FixtureTransitAdapter(FixtureScenario.R1_SUCCESS).search(
        TransitSearchRequest(
            Coordinate(*origin), Coordinate(*destination), departure
        ),
        deadline=Deadline.after_ms(1000),
    )
    leg = envelope.payload[0].legs[0]
    mapping, target = _mapping_pipeline(leg, departure, FixtureFault.MAPPING_LOW)
    assert mapping.allows_bus_intelligence is False
    assert mapping.selected is not None
    assert str(mapping.selected.grade) in {"MEDIUM", "LOW"}
    dependencies = fixture_fan_in_dependencies(scenario)
    query = BusObservationQuery(
        target.route_id,
        target.boarding.external_id,
        departure,
    )
    bus = _bus_result(
        mapping,
        target,
        departure,
        True,
        dependencies.providers.arrivals(query, deadline=Deadline.after_ms(1000)),
        dependencies.providers.locations(query, deadline=Deadline.after_ms(1000)),
        dependencies.eta_predictor,
        dependencies.seat_predictor,
        query,
        service_type="SEATED",
    )
    assert bus.enrichment_applied is False
    assert bus.expected_wait_seconds is None
    assert bus.p90_wait_seconds is None
    assert bus.candidate_vehicles == ()


def test_optimization_persistence_port_receives_only_hash_candidates_legs_and_provenance() -> None:
    clock = FakeClock()
    persistence = InMemoryOptimizationPersistence()
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        fixture_scenario("R1"), clock, persistence=persistence
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}  # type: ignore[index]
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}  # type: ignore[index]
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "persist-correlation",
        "persist-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    outcome = use_case.execute(OptimizeCommand(payload), context)
    assert outcome.response["computation"]["cache"]["optimizationPersistence"] == "PERSISTED"
    assert len(persistence.values) == 1
    stored = persistence.values[0]
    assert len(stored.run.request_fingerprint) == 64
    assert stored.candidates and stored.legs
    assert not hasattr(stored.run, "user_id")
    assert all(item.provenance for item in stored.legs)
    assert stored.run.provider_summary["envelopes"]
    assert all(
        {"provider", "operation", "fingerprint", "schemaVersion", "status"}
        <= set(item)
        for item in stored.run.provider_summary["envelopes"]
    )
    assert all(item.geometry_wkt is not None for item in stored.legs)
    assert all(
        any(
            isinstance(value, dict) and value.get("fingerprint")
            for value in item.provenance
        )
        for item in stored.legs
    )
    assert all(
        item.transport_route_id is None
        or (item.from_stop_id is not None and item.to_stop_id is not None)
        for item in stored.legs
    )


def test_persistence_includes_available_bus_and_transfer_values_without_fake_mapping_id() -> None:
    persistence = InMemoryOptimizationPersistence()
    response = _causal_response(
        persistence=persistence,
        taxi_upper_krw=2_500,
        eta_seconds=180,
        remaining_seats=3,
    )
    assert response["routes"]
    stored = persistence.values[0]
    assert stored.bus_enrichments
    assert all(item.entity_mapping_id is None for item in stored.bus_enrichments)
    assert all(
        item.p90_wait_seconds >= item.expected_wait_seconds
        for item in stored.bus_enrichments
    )
    per_leg_fingerprints = [
        {
            item["fingerprint"]
            for item in leg.provenance
            if isinstance(item, dict) and item.get("fingerprint")
        }
        for leg in stored.legs
    ]
    assert all(
        len(
            {
                item["fingerprint"]
                for item in leg.provenance
                if isinstance(item, dict)
                and item.get("fingerprint")
                and item.get("operation") not in {"arrivals", "locations"}
            }
        ) == 1
        for leg in stored.legs
    )
    assert len(set().union(*per_leg_fingerprints)) > 1


def test_optimization_persistence_failure_is_explicit_and_does_not_corrupt_route() -> None:
    class FailingPersistence:
        def persist(self, value) -> None:
            raise RuntimeError("database unavailable")

    clock = FakeClock()
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        fixture_scenario("R1"), clock, persistence=FailingPersistence()
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}  # type: ignore[index]
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}  # type: ignore[index]
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "persist-failure-correlation",
        "persist-failure-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    outcome = use_case.execute(OptimizeCommand(payload), context)
    assert outcome.response["routes"]
    assert outcome.response["computation"]["cache"]["optimizationPersistence"] == "FAILED"
    assert CanonicalContractValidator().validate_optimize_response(outcome.response) == ()


def test_replay_scenario_fails_closed_when_departure_bundle_does_not_match() -> None:
    response, _, _ = _post("R1", departure="2026-08-24T07:41:00+09:00")
    assert response.status_code == 503
    assert response.json()["code"] == "TRANSIT_PROVIDER_UNAVAILABLE"


@pytest.mark.parametrize(
    ("scenario_id", "warning"),
    [
        ("MAPPING_LOW", "BUS_MAPPING_LOW_CONFIDENCE"),
        ("ETA_UNAVAILABLE", "BUS_DATA_UNAVAILABLE"),
        ("SEAT_UNAVAILABLE", "BUS_DATA_UNAVAILABLE"),
    ],
)
def test_mapping_or_separate_predictor_unavailable_projects_entire_bus_object_null(
    scenario_id: str,
    warning: str,
) -> None:
    response, _, _ = _post(scenario_id)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "PARTIAL"
    assert body["routes"][0]["legs"][0]["busIntelligence"] is None
    assert warning in body["warningCodes"]
    assert body["modelVersions"] == []
    if scenario_id == "MAPPING_LOW":
        leg = body["routes"][0]["legs"][0]
        assert body["computation"]["mappingVersion"] is None
        assert leg["from"]["canonicalStopId"] is None
        assert leg["to"]["canonicalStopId"] is None
        assert leg["from"]["providerStopId"] == "sanitized-r1-stop-origin"
        assert leg["to"]["providerStopId"] == "sanitized-r1-stop-destination"
        mapping_provenance = next(
            item
            for item in body["routes"][0]["provenance"]
            if item["provider"].startswith("TRANSPORT_MAPPING/")
        )
        assert mapping_provenance["confidence"]["grade"] == "LOW"


@pytest.mark.parametrize(
    ("requested", "expected_nonnull"),
    [(["FASTEST"], {"fastest"}), ([], set())],
)
def test_only_requested_recommendation_types_are_populated(
    requested: list[str], expected_nonnull: set[str]
) -> None:
    response, _, _ = _post("R1", requested)
    assert response.status_code == 200, response.content
    recommendations = response.json()["recommendations"]
    assert set(recommendations) == {
        "fastest",
        "stable",
        "efficient",
        "publicTransitOnly",
    }
    assert {
        key for key, value in recommendations.items() if value is not None
    } == expected_nonnull


@pytest.mark.parametrize(
    "scenario_id",
    [
        "PROVIDER_EMPTY",
        "PROVIDER_TIMEOUT",
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_SCHEMA_DRIFT",
    ],
)
def test_required_provider_faults_fail_closed_with_registered_problem(
    scenario_id: str,
) -> None:
    response, _, _ = _post(scenario_id)
    assert response.status_code == 503
    assert response.json()["code"] == "TRANSIT_PROVIDER_UNAVAILABLE"


def test_capabilities_are_derived_from_every_foundation_registry_provider() -> None:
    projection = foundation_capability_projection()
    expected_providers = {
        item.provider for item in foundation_capability_registry().all()
    }
    actual_providers = {item["provider"] for item in projection.providers}
    assert actual_providers == expected_providers
    assert not any(projection.features.values())
    assert all(item["keyVerificationState"] == "UNVERIFIED" for item in projection.providers)
    assert all(item["productionState"] == "UNAPPROVED" for item in projection.providers)
    assert all(item["health"] == "DISABLED" for item in projection.providers)


def test_container_default_is_503_without_source_activation_and_r1_is_integrated_200() -> None:
    clock = FakeClock(wall=datetime.now(timezone.utc))
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}  # type: ignore[index]
    payload["destination"]["coordinate"] = {  # type: ignore[index]
        "lon": destination[0],
        "lat": destination[1],
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    headers = {
        "HTTP_AUTHORIZATION": f"Bearer {_token(clock)}",
        "HTTP_X_CORRELATION_ID": "corr-container-regression",
        "HTTP_X_REQUEST_DEADLINE": (clock.now() + timedelta(seconds=6)).isoformat(),
        "HTTP_IDEMPOTENCY_KEY": "idem-container-regression",
    }

    get_application.cache_clear()
    with override_settings(
        ROUTING_FIXTURE_SCENARIO="",
        ROUTING_SERVICE_JWT_SECRET=SECRET.decode("utf-8"),
    ), patch("routing_api.workspace_packages.activate_workspace_packages") as activate:
        default = Client().post(
            "/v1/routes/optimize",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )
        assert default.status_code == 503
        assert default.json()["code"] == "TRANSIT_PROVIDER_UNAVAILABLE"
        assert get_application().readiness()["checks"]["backend"] == "unavailable"
        activate.assert_not_called()

    get_application.cache_clear()
    with override_settings(
        ROUTING_FIXTURE_SCENARIO="R1",
        ROUTING_ALLOW_FIXTURE_BACKEND=True,
        ROUTING_RUNTIME_ENVIRONMENT="TEST",
        ROUTING_SERVICE_JWT_SECRET=SECRET.decode("utf-8"),
    ):
        integrated = Client().post(
            "/v1/routes/optimize",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )
        assert integrated.status_code == 200, integrated.content
        assert get_application().readiness()["checks"]["backend"] == "fixture-only:R1"
        version = Client().get(
            "/v1/version",
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )
        assert version.status_code == 200
        assert version.json()["contractVersion"] == "1.1.0"
        assert version.json()["rankingPolicyVersion"] == "rank-0.1.1"
        assert (
            version.json()["rankingPolicyVersion"]
            == integrated.json()["computation"]["rankingPolicyVersion"]
        )
        assert version.json()["models"] == []
    get_application.cache_clear()


def test_production_factory_is_zero_call_unavailable_with_foundation_capabilities() -> None:
    class CountingTransport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request):
            self.calls += 1
            raise AssertionError("disabled production factory attempted network")

    transport = CountingTransport()
    use_case = build_default_production_use_case(
        FakeClock(), provider_suite=ProviderAdapterSuite(transport)
    )
    with pytest.raises(RoutingUnavailableError):
        use_case.execute(None, None)
    assert transport.calls == 0


def test_injected_production_factory_is_typed_and_still_capability_gated() -> None:
    class NoNetwork:
        def send(self, request):
            raise AssertionError("injectable factory test attempted network")

    scenario = fixture_scenario("R1")
    fixture = fixture_fan_in_dependencies(scenario)
    eta_predictor, seat_predictor = _verified_model_pair()
    registry = CapabilityRegistry(
        (
            Capability(
                "KAKAO_PUBLIC_TRANSIT",
                "search_current",
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )
    configured = ProviderAdapterSuiteConfig(capabilities=registry)
    dependencies = ProductionCompositionDependencies(
        provider_config=configured,  # type: ignore[arg-type]
        mapping_database=object(),
        persistence=InMemoryOptimizationPersistence(),
        eta_predictor=eta_predictor,
        seat_predictor=seat_predictor,
        taxi_dispatch=fixture.taxi_dispatch,
        capability_registry=registry,
        deployment_environment="staging",
    )
    suite = ProviderAdapterSuite(NoNetwork())
    with (
        patch.object(ProviderAdapterSuite, "from_config", return_value=suite) as build,
        patch(
            "routing_api.production_composition._executable_provider_operations",
            return_value=frozenset(
                {("KAKAO_PUBLIC_TRANSIT", "search_current")}
            ),
        ),
        patch(
            "routing_api.production_composition.PostgisMappingResolver",
            return_value=fixture.mapping,
        ),
    ):
        use_case = build_injected_production_use_case(FakeClock(), dependencies)
    assert isinstance(use_case, ProductionOptimizeRouteUseCase)
    assert tuple(map(dict, use_case.model_projection)) == (
        {"purpose": "BUS_ETA", "version": "eta-production-1", "state": "ACTIVE"},
        {
            "purpose": "SEAT_RISK",
            "version": "seat-production-1",
            "state": "ACTIVE",
        },
    )
    assert use_case._dependencies.taxi_dispatch is fixture.taxi_dispatch
    assert use_case._dependencies.context is None
    build.assert_called_once_with(configured)

    with (
        patch.object(ProviderAdapterSuite, "from_config", return_value=suite),
        patch(
            "routing_api.production_composition._executable_provider_operations",
            return_value=frozenset(
                {
                    ("KAKAO_PUBLIC_TRANSIT", "search_current"),
                    ("KMA", "weather_context"),
                }
            ),
        ),
        patch(
            "routing_api.production_composition.PostgisMappingResolver",
            return_value=fixture.mapping,
        ),
    ):
        with_context = build_injected_production_use_case(FakeClock(), dependencies)
    assert isinstance(with_context, ProductionOptimizeRouteUseCase)
    assert with_context._dependencies.context is not None
    assert with_context._dependencies.context.enabled_operations == frozenset(
        {"weather_context"}
    )

    with (
        patch.object(ProviderAdapterSuite, "from_config", return_value=suite),
        patch(
            "routing_api.production_composition._executable_provider_operations",
            return_value=frozenset(
                {("KAKAO_PUBLIC_TRANSIT", "search_current")}
            ),
        ),
        patch(
            "routing_api.production_composition.PostgisMappingResolver",
            return_value=fixture.mapping,
        ),
    ):
        transit_only = build_injected_production_use_case(
            FakeClock(), replace(dependencies, taxi_dispatch=None)
        )
    assert isinstance(transit_only, ProductionOptimizeRouteUseCase)
    assert transit_only._dependencies.taxi_dispatch is None

    with patch.object(
        ProviderAdapterSuite,
        "from_config",
        side_effect=AssertionError("disabled capability constructed providers"),
    ):
        unavailable = build_injected_production_use_case(
            FakeClock(),
            replace(
                dependencies,
                capability_registry=foundation_capability_registry(),
            ),
        )
    with pytest.raises(RoutingUnavailableError):
        unavailable.execute(None, None)


@pytest.mark.parametrize(
    "invalid_models",
    ["generic", "swapped", "inactive", "uncalibrated", "environment"],
)
def test_production_model_boundary_rejects_unverified_pairs_before_provider_suite(
    invalid_models: str,
) -> None:
    registry = _enabled_transit_registry()
    eta, seat = _verified_model_pair()
    if invalid_models == "generic":
        eta_value, seat_value = object(), object()
    elif invalid_models == "swapped":
        eta_value, seat_value = seat, eta
    elif invalid_models == "inactive":
        object.__setattr__(eta.attestation, "readiness", "INACTIVE")
        eta_value, seat_value = eta, seat
    elif invalid_models == "uncalibrated":
        object.__setattr__(seat.attestation, "calibrated", False)
        eta_value, seat_value = eta, seat
    else:
        eta_value, seat_value = eta, seat
    deployment_environment = "prod" if invalid_models == "environment" else "staging"
    dependencies = ProductionCompositionDependencies(
        provider_config=ProviderAdapterSuiteConfig(capabilities=registry),
        mapping_database=object(),
        persistence=InMemoryOptimizationPersistence(),
        eta_predictor=eta_value,  # type: ignore[arg-type]
        seat_predictor=seat_value,  # type: ignore[arg-type]
        capability_registry=registry,
        deployment_environment=deployment_environment,
    )
    with patch.object(
        ProviderAdapterSuite,
        "from_config",
        side_effect=AssertionError("invalid model pair constructed provider suite"),
    ) as build:
        unavailable = build_injected_production_use_case(FakeClock(), dependencies)
    with pytest.raises(RoutingUnavailableError):
        unavailable.execute(None, None)
    build.assert_not_called()


def test_verified_model_pair_is_projected_consistently_across_runtime_endpoints() -> None:
    class NoNetwork:
        def send(self, request):
            raise AssertionError("capability projection attempted provider I/O")

    scenario = fixture_scenario("R1")
    fixture = fixture_fan_in_dependencies(scenario)
    eta, seat = _verified_model_pair()
    registry = _enabled_transit_registry()
    dependencies = ProductionCompositionDependencies(
        provider_config=ProviderAdapterSuiteConfig(capabilities=registry),
        mapping_database=object(),
        persistence=InMemoryOptimizationPersistence(),
        eta_predictor=eta,
        seat_predictor=seat,
        capability_registry=registry,
        deployment_environment="staging",
    )
    suite = ProviderAdapterSuite(NoNetwork())
    with (
        patch.object(ProviderAdapterSuite, "from_config", return_value=suite),
        patch(
            "routing_api.production_composition._executable_provider_operations",
            return_value=frozenset({("KAKAO_PUBLIC_TRANSIT", "search_current")}),
        ),
        patch(
            "routing_api.production_composition.PostgisMappingResolver",
            return_value=fixture.mapping,
        ),
        override_settings(
            ROUTING_FIXTURE_SCENARIO=None,
            ROUTING_SERVICE_JWT_SECRET=SECRET.decode("utf-8"),
        ),
    ):
        application = build_application(
            production_dependencies=dependencies,
            clock=FakeClock(),
        )

    capabilities = application.capabilities()
    assert capabilities["features"]["busEtaModel"] is True
    assert capabilities["features"]["busSeatRisk"] is True
    assert capabilities["models"] == [
        {"purpose": "BUS_ETA", "version": "eta-production-1", "state": "ACTIVE"},
        {
            "purpose": "SEAT_RISK",
            "version": "seat-production-1",
            "state": "ACTIVE",
        },
    ]
    assert application.version()["models"] == [
        {"purpose": "BUS_ETA", "version": "eta-production-1"},
        {"purpose": "SEAT_RISK", "version": "seat-production-1"},
    ]
    assert application.readiness()["checks"] == {
        "contract": "ready",
        "backend": "production",
        "providers": "ready",
        "models": "ready",
    }


def test_registered_verified_dependencies_reach_the_cached_process_application() -> None:
    missing = object()
    worker_before = sys.modules.get("routing_worker", missing)

    class NoNetwork:
        def send(self, request):
            raise AssertionError("process composition projection attempted provider I/O")

    scenario = fixture_scenario("R1")
    fixture = fixture_fan_in_dependencies(scenario)
    eta, seat = _verified_model_pair()
    registry = _enabled_transit_registry()
    dependencies = ProductionCompositionDependencies(
        provider_config=ProviderAdapterSuiteConfig(capabilities=registry),
        mapping_database=object(),
        persistence=InMemoryOptimizationPersistence(),
        eta_predictor=eta,
        seat_predictor=seat,
        capability_registry=registry,
        deployment_environment="staging",
    )
    suite = ProviderAdapterSuite(NoNetwork())

    _reset_application_composition_for_tests()
    try:
        register_production_dependencies(dependencies)
        with (
            patch.object(ProviderAdapterSuite, "from_config", return_value=suite),
            patch(
                "routing_api.production_composition._executable_provider_operations",
                return_value=frozenset(
                    {("KAKAO_PUBLIC_TRANSIT", "search_current")}
                ),
            ),
            patch(
                "routing_api.production_composition.PostgisMappingResolver",
                return_value=fixture.mapping,
            ),
            override_settings(
                ROUTING_FIXTURE_SCENARIO=None,
                ROUTING_SERVICE_JWT_SECRET=SECRET.decode("utf-8"),
            ),
        ):
            application = get_application()

        assert application.readiness()["checks"] == {
            "contract": "ready",
            "backend": "production",
            "providers": "ready",
            "models": "ready",
        }
        assert application.version()["models"] == [
            {"purpose": "BUS_ETA", "version": "eta-production-1"},
            {"purpose": "SEAT_RISK", "version": "seat-production-1"},
        ]
        assert sys.modules.get("routing_worker", missing) is worker_before
    finally:
        _reset_application_composition_for_tests()


def test_gits_identity_repository_is_zero_io_when_operation_is_not_executable() -> None:
    class NoNetwork:
        def send(self, request):
            raise AssertionError("disabled GITS composition attempted provider I/O")

    scenario = fixture_scenario("R1")
    fixture = fixture_fan_in_dependencies(scenario)
    eta, seat = _verified_model_pair()
    registry = _enabled_transit_registry()
    dependencies = ProductionCompositionDependencies(
        provider_config=ProviderAdapterSuiteConfig(capabilities=registry),
        mapping_database=object(),
        persistence=InMemoryOptimizationPersistence(),
        eta_predictor=eta,
        seat_predictor=seat,
        capability_registry=registry,
        deployment_environment="staging",
    )
    suite = ProviderAdapterSuite(NoNetwork())
    with (
        patch.object(ProviderAdapterSuite, "from_config", return_value=suite),
        patch(
            "routing_api.production_composition._executable_provider_operations",
            return_value=frozenset({("KAKAO_PUBLIC_TRANSIT", "search_current")}),
        ),
        patch(
            "routing_api.production_composition.PostgisGitsRoadLinkIdentityRepository",
            side_effect=AssertionError("disabled GITS identity queried database"),
        ) as gits_repository,
        patch(
            "routing_api.production_composition.PostgisMappingResolver",
            return_value=fixture.mapping,
        ),
    ):
        use_case = build_injected_production_use_case(FakeClock(), dependencies)
    assert isinstance(use_case, ProductionOptimizeRouteUseCase)
    assert use_case._dependencies.context is None
    gits_repository.assert_not_called()


def test_executable_gits_operation_injects_one_durable_identity_repository() -> None:
    class NoNetwork:
        def send(self, request):
            raise AssertionError("GITS composition test attempted provider I/O")

    registry = CapabilityRegistry(
        _enabled_transit_registry().all()
        + (
            Capability(
                "GITS",
                "traffic_context",
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )
    eta, seat = _verified_model_pair()
    database = object()
    dependencies = ProductionCompositionDependencies(
        provider_config=ProviderAdapterSuiteConfig(capabilities=registry),
        mapping_database=database,
        persistence=InMemoryOptimizationPersistence(),
        eta_predictor=eta,
        seat_predictor=seat,
        capability_registry=registry,
        deployment_environment="staging",
    )
    suite = ProviderAdapterSuite(NoNetwork())
    gits_repository = object()
    mapping = Mock()
    with (
        patch.object(ProviderAdapterSuite, "from_config", return_value=suite),
        patch(
            "routing_api.production_composition._executable_provider_operations",
            return_value=frozenset(
                {
                    ("KAKAO_PUBLIC_TRANSIT", "search_current"),
                    ("GITS", "traffic_context"),
                }
            ),
        ),
        patch(
            "routing_api.production_composition.PostgisGitsRoadLinkIdentityRepository",
            return_value=gits_repository,
        ) as build_gits_repository,
        patch(
            "routing_api.production_composition.PostgisMappingResolver",
            return_value=mapping,
        ) as build_mapping,
    ):
        use_case = build_injected_production_use_case(FakeClock(), dependencies)

    assert isinstance(use_case, ProductionOptimizeRouteUseCase)
    assert use_case._dependencies.context.enabled_operations == frozenset(
        {"traffic_context"}
    )
    build_gits_repository.assert_called_once_with(database)
    build_mapping.assert_called_once_with(
        database,
        gits_identity_repository=gits_repository,
    )


def test_postgis_mapping_enriches_selected_gits_identity_exactly_once() -> None:
    resolver = object.__new__(PostgisMappingResolver)
    target = object()
    enriched = object()
    resolution = object()
    selected = SimpleNamespace(candidate_fingerprint="selected")
    result = SimpleNamespace(
        selected=selected,
        selected_resolution=resolution,
        source="KAKAO_TRANSIT",
    )
    resolver._pipeline = Mock()
    resolver._pipeline.map_bus_leg.return_value = result
    resolver._catalog = Mock()
    resolver._catalog.find_candidates.return_value = (target,)
    resolver._gits_identity_repository = Mock()
    evidence = SimpleNamespace(provider_code="KAKAO_TRANSIT", leg=object())
    evaluated_at = datetime(2026, 8, 23, tzinfo=timezone.utc)

    with (
        patch(
            "routing_api.production_composition.candidate_fingerprint",
            return_value="selected",
        ),
        patch(
            "routing_api.production_composition.enrich_selected_gits_road_link_target",
            return_value=enriched,
        ) as enrich,
    ):
        mapped_result, mapped_target = resolver(evidence, evaluated_at)

    assert mapped_result is result
    assert mapped_target is enriched
    enrich.assert_called_once_with(
        target,
        resolution,
        resolver._gits_identity_repository,
        as_of=evaluated_at,
    )


def test_injected_production_registry_mismatch_fails_before_suite_construction() -> None:
    enabled_registry = CapabilityRegistry(
        (
            Capability(
                "KAKAO_PUBLIC_TRANSIT",
                "search_current",
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )
    dependencies = ProductionCompositionDependencies(
        provider_config=ProviderAdapterSuiteConfig(
            capabilities=foundation_capability_registry()
        ),
        mapping_database=object(),
        persistence=InMemoryOptimizationPersistence(),
        eta_predictor=object(),  # type: ignore[arg-type]
        seat_predictor=object(),  # type: ignore[arg-type]
        capability_registry=enabled_registry,
    )
    with patch.object(
        ProviderAdapterSuite,
        "from_config",
        side_effect=AssertionError("split-brain registry constructed adapters"),
    ) as build:
        unavailable = build_injected_production_use_case(FakeClock(), dependencies)
    with pytest.raises(RoutingUnavailableError):
        unavailable.execute(None, None)
    build.assert_not_called()


def test_coherent_enabled_registry_without_schema_runtime_evidence_stays_unavailable() -> None:
    registry = CapabilityRegistry(
        (
            Capability(
                "KAKAO_PUBLIC_TRANSIT",
                "search_current",
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )
    scenario = fixture_scenario("R1")
    fixture = fixture_fan_in_dependencies(scenario)
    dependencies = ProductionCompositionDependencies(
        provider_config=ProviderAdapterSuiteConfig(capabilities=registry),
        mapping_database=object(),
        persistence=InMemoryOptimizationPersistence(),
        eta_predictor=fixture.eta_predictor,
        seat_predictor=fixture.seat_predictor,
        capability_registry=registry,
    )
    use_case = build_injected_production_use_case(FakeClock(), dependencies)
    with pytest.raises(RoutingUnavailableError):
        use_case.execute(None, None)

    with override_settings(
        ROUTING_FIXTURE_SCENARIO=None,
        ROUTING_SERVICE_JWT_SECRET=SECRET.decode("utf-8"),
    ):
        application = build_application(
            production_dependencies=dependencies,
            clock=FakeClock(),
        )
    assert not any(application.capabilities()["features"].values())
    assert all(
        item["health"] == "DISABLED"
        for item in application.capabilities()["providers"]
    )
    assert application.readiness()["checks"]["backend"] == "unavailable"
    assert application.readiness()["checks"]["providers"] == "disabled"


def test_django_application_builder_does_not_project_registry_without_runtime_gate() -> None:
    marker = object()
    registry = CapabilityRegistry(
        (
            Capability(
                "TMAP_TRANSIT",
                "search",
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )
    dependencies = ProductionCompositionDependencies(
        provider_config=ProviderAdapterSuiteConfig(capabilities=registry),
        capability_registry=registry,
    )
    with (
        override_settings(
            ROUTING_FIXTURE_SCENARIO=None,
            ROUTING_SERVICE_JWT_SECRET=SECRET.decode("utf-8"),
        ),
        patch(
            "routing_api.production_composition.build_injected_production_use_case",
            return_value=marker,
        ) as injected,
    ):
        application = build_application(
            production_dependencies=dependencies,
            clock=FakeClock(),
        )
    assert application._use_case is marker
    injected.assert_called_once()
    capabilities = application.capabilities()
    assert capabilities["features"]["currentTransit"] is False
    assert {item["provider"] for item in capabilities["providers"]} == {
        item.provider for item in foundation_capability_registry().all()
    }
    assert all(item["health"] == "DISABLED" for item in capabilities["providers"])
    assert application.readiness()["checks"]["backend"] == "unavailable"
    assert application.readiness()["checks"]["providers"] == "disabled"


def test_transit_fallback_is_kakao_then_tmap_then_odsay_and_empty_is_not_success() -> None:
    class NoNetwork:
        def send(self, request):
            raise AssertionError("fixture adapter attempted network")

    suite = ProviderAdapterSuite(NoNetwork())
    empty = suite.kakao_transit.fixture(
        "search_current", ProviderFixtureScenario.EMPTY
    )
    tmap_success = suite.tmap.fixture("search", ProviderFixtureScenario.SUCCESS)
    odsay_success = suite.odsay.fixture("search", ProviderFixtureScenario.SUCCESS)
    calls: list[str] = []

    class Adapter:
        def __init__(self, name, envelope):
            self.name = name
            self.envelope = envelope

        def search(self, request, *, deadline):
            calls.append(self.name)
            return self.envelope

    fallback = FallbackTransitSearch(
        (
            Adapter("KAKAO", empty),
            Adapter("TMAP", tmap_success),
            Adapter("ODSAY", odsay_success),
        )
    )
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    result = fallback.search(
        TransitSearchRequest(
            ProviderCoordinate(*origin),
            ProviderCoordinate(*destination),
            datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"]),
        ),
        deadline=Deadline.after_ms(1000),
    )
    assert result.provider == "TMAP_TRANSIT"
    assert calls == ["KAKAO", "TMAP"]


def test_concurrent_fallback_attempts_and_operation_settlement_are_request_local() -> None:
    class Adapter:
        def __init__(self, name, success, empty):
            self.name = name
            self.success = success
            self.empty = empty

        def search(self, request, *, deadline):
            del deadline
            fingerprint = request.fingerprint()
            if self.name == "KAKAO" and request.origin.lon < 127.0:
                return replace(
                    self.success,
                    provider="KAKAO_PUBLIC_TRANSIT",
                    operation="search_current",
                    fingerprint=fingerprint,
                )
            if self.name == "KAKAO":
                return replace(self.empty, fingerprint=fingerprint)
            return replace(self.success, fingerprint=fingerprint)

    class NoNetwork:
        def send(self, request):
            raise AssertionError("fixture adapter attempted network")

    suite = ProviderAdapterSuite(NoNetwork())
    success = suite.tmap.fixture("search", ProviderFixtureScenario.SUCCESS)
    empty = suite.kakao_transit.fixture(
        "search_current", ProviderFixtureScenario.EMPTY
    )
    fallback = FallbackTransitSearch(
        (
            Adapter("KAKAO", success, empty),
            Adapter("TMAP", success, empty),
            Adapter("ODSAY", success, empty),
        )
    )
    departure = datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"])
    requests = (
        TransitSearchRequest(
            ProviderCoordinate(126.9, 37.2),
            ProviderCoordinate(127.1, 37.4),
            departure,
        ),
        TransitSearchRequest(
            ProviderCoordinate(127.2, 37.2),
            ProviderCoordinate(127.1, 37.4),
            departure,
        ),
    )
    gate = threading.Barrier(2)

    def invoke(request):
        selected = fallback.search(request, deadline=Deadline.after_ms(1000))
        gate.wait()
        attempts = fallback.attempts
        budget = _ProviderOperationBudget(3)
        budget.reserve(3)
        budget.release(3 - len(attempts))
        return selected, attempts, budget.consumed

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(invoke, requests))
    assert [len(attempts) for _, attempts, _ in results] == [1, 2]
    assert [consumed for _, _, consumed in results] == [1, 2]
    assert [
        [item.provider for item in attempts] for _, attempts, _ in results
    ] == [["KAKAO_PUBLIC_TRANSIT"], ["KAKAO_PUBLIC_TRANSIT", "TMAP_TRANSIT"]]
    assert all(
        {item.fingerprint for item in attempts} == {request.fingerprint()}
        for request, (_, attempts, _) in zip(requests, results)
    )


def test_fallback_and_fixture_attempt_context_is_cleared_before_exception() -> None:
    class ToggleAdapter:
        def __init__(self, envelope):
            self.envelope = envelope
            self.fail = False

        def search(self, request, *, deadline):
            del request, deadline
            if self.fail:
                raise RuntimeError("provider transport failed before envelope")
            return self.envelope

    class NoNetwork:
        def send(self, request):
            raise AssertionError("fixture adapter attempted network")

    suite = ProviderAdapterSuite(NoNetwork())
    success = suite.tmap.fixture("search", ProviderFixtureScenario.SUCCESS)
    primary = ToggleAdapter(success)
    fallback = FallbackTransitSearch(
        (primary, ToggleAdapter(success), ToggleAdapter(success))
    )
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    request = TransitSearchRequest(
        ProviderCoordinate(*origin),
        ProviderCoordinate(*destination),
        datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"]),
    )
    fallback.search(request, deadline=Deadline.after_ms(1000))
    assert len(fallback.attempts) == 1
    primary.fail = True
    with pytest.raises(RuntimeError, match="provider transport failed"):
        fallback.search(request, deadline=Deadline.after_ms(1000))
    assert fallback.attempts == ()

    fixture_providers = fixture_fan_in_dependencies(
        fixture_scenario("R1")
    ).providers
    fixture_providers.transit(request, deadline=Deadline.after_ms(1000))
    assert fixture_providers.last_transit_attempt_count == 1
    with patch.object(
        FixtureTransitAdapter,
        "search",
        side_effect=RuntimeError("fixture failed before envelope"),
    ):
        with pytest.raises(RuntimeError, match="fixture failed"):
            fixture_providers.transit(request, deadline=Deadline.after_ms(1000))
    assert fixture_providers.last_transit_attempt_count == 0
    assert fixture_providers.last_transit_envelopes == ()


def test_fallback_attempt_order_is_preserved_in_status_and_persistence() -> None:
    class TwoAttemptProviders(_CausalProviderPorts):
        def __init__(self, base):
            super().__init__(base, taxi_upper_krw=2_500)
            self._attempts = ()

        @property
        def transit_call_cap(self):
            return 3

        @property
        def last_transit_attempt_count(self):
            return 2

        @property
        def last_transit_envelopes(self):
            return self._attempts

        def transit(self, request, *, deadline):
            selected = replace(
                super().transit(request, deadline=deadline),
                provider="TMAP_TRANSIT",
            )
            primary = replace(
                selected,
                provider="KAKAO_PUBLIC_TRANSIT",
                status=ProviderStatus.UNAVAILABLE,
                payload=None,
                normalized_count=0,
                schema_version=None,
            )
            self._attempts = (primary, selected)
            return selected

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    persistence = InMemoryOptimizationPersistence()
    dependencies = replace(
        base,
        providers=TwoAttemptProviders(base.providers),
        persistence=persistence,
        fixture_only=False,
    )
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "fallback-order", clock, dependencies=dependencies
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "fallback-order-correlation",
        "fallback-order-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), context).response
    assert [item["provider"] for item in response["providerStatus"][:2]] == [
        "KAKAO_PUBLIC_TRANSIT",
        "TMAP_TRANSIT",
    ]
    attempts = persistence.values[0].run.provider_summary["envelopes"]
    assert [item["provider"] for item in attempts[:2]] == [
        "KAKAO_PUBLIC_TRANSIT",
        "TMAP_TRANSIT",
    ]


def test_production_use_case_never_projects_fixture_route_or_provenance_names() -> None:
    class ProductionProviders(_CausalProviderPorts):
        def transit(self, request, *, deadline):
            return replace(
                super().transit(request, deadline=deadline),
                provider="KAKAO_PUBLIC_TRANSIT",
            )

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = ProductionProviders(base.providers, taxi_upper_krw=2_500)

    class CapturingMapping:
        def __init__(self) -> None:
            self.providers: list[str] = []

        def __call__(self, evidence, evaluated_at):
            self.providers.append(evidence.provider_code)
            return base.mapping(evidence, evaluated_at)

    mapping = CapturingMapping()
    eta_predictor, seat_predictor = _verified_model_pair()

    dependencies = replace(
        base,
        providers=providers,
        mapping=mapping,
        eta_predictor=eta_predictor,
        seat_predictor=seat_predictor,
        persistence=InMemoryOptimizationPersistence(),
        fixture_only=False,
    )
    registry = CapabilityRegistry(
        (
            Capability(
                "KAKAO_PUBLIC_TRANSIT",
                "search_current",
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )
    use_case = ProductionOptimizeRouteUseCase(
        clock,
        dependencies,
        capability_registry=registry,
        executable_operations=frozenset(
            {("KAKAO_PUBLIC_TRANSIT", "search_current")}
        ),
        model_projection=(
            {
                "purpose": "BUS_ETA",
                "version": "eta-production-1",
                "state": "ACTIVE",
            },
            {
                "purpose": "SEAT_RISK",
                "version": "seat-production-1",
                "state": "ACTIVE",
            },
        ),
        deployment_environment="staging",
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    payload["constraints"]["allowTaxiBridge"] = True
    context = RequestContext(
        "production-correlation",
        "production-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), context).response
    assert mapping.providers and set(mapping.providers) == {"KAKAO_TRANSIT"}
    assert all("fixture" not in route["routeId"].lower() for route in response["routes"])
    assert all(
        "fixture" not in item["provider"].lower()
        for route in response["routes"]
        for item in route["provenance"]
    )
    assert response["providerStatus"]
    assert any(
        item["provider"] == "KAKAO_PUBLIC_TRANSIT" and item["status"] == "OK"
        for item in response["providerStatus"]
    )
    assert all(
        "fixture" not in item["provider"].lower()
        for item in response["providerStatus"]
    )
    assert all(
        leg["transit"] is None
        or "fixture" not in (leg["transit"]["externalRouteId"] or "").lower()
        for route in response["routes"]
        for leg in route["legs"]
    )


@pytest.mark.parametrize(
    ("allow_fixture", "runtime_environment"),
    [(False, "TEST"), (True, "PRODUCTION"), (True, "STAGING")],
)
def test_container_never_serves_fixture_without_both_nonproduction_gates(
    allow_fixture: bool, runtime_environment: str
) -> None:
    clock = FakeClock(wall=datetime.now(timezone.utc))
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}  # type: ignore[index]
    payload["destination"]["coordinate"] = {"lon": destination[0], "lat": destination[1]}  # type: ignore[index]
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    headers = {
        "HTTP_AUTHORIZATION": f"Bearer {_token(clock)}",
        "HTTP_X_CORRELATION_ID": "corr-fixture-gate",
        "HTTP_X_REQUEST_DEADLINE": (clock.now() + timedelta(seconds=6)).isoformat(),
        "HTTP_IDEMPOTENCY_KEY": f"idem-fixture-gate-{runtime_environment.lower()}-{allow_fixture}",
    }
    get_application.cache_clear()
    try:
        with override_settings(
            ROUTING_FIXTURE_SCENARIO="R1",
            ROUTING_ALLOW_FIXTURE_BACKEND=allow_fixture,
            ROUTING_RUNTIME_ENVIRONMENT=runtime_environment,
            ROUTING_SERVICE_JWT_SECRET=SECRET.decode("utf-8"),
        ):
            response = Client().post(
                "/v1/routes/optimize",
                data=json.dumps(payload),
                content_type="application/json",
                **headers,
            )
            assert response.status_code == 503
            assert response.json()["code"] == "TRANSIT_PROVIDER_UNAVAILABLE"
            assert get_application().readiness()["checks"]["backend"] == "fixture-blocked"
    finally:
        get_application.cache_clear()


def test_unimplemented_admin_operations_remain_fail_closed_404() -> None:
    response = Client().post(
        "/internal/admin/cache/invalidate",
        data=json.dumps({"namespace": "fixture"}),
        content_type="application/json",
    )
    assert response.status_code == 404


def test_canonical_walk_bus_walk_bus_is_preserved_and_bus_plans_are_per_leg() -> None:
    class MultiLegProviders(_CausalProviderPorts):
        def transit(self, request, *, deadline):
            envelope = self._base.transit(request, deadline=deadline)
            origin, destination = _SCENARIO_ENDPOINTS["R1"]
            if (request.origin.lon, request.origin.lat) != origin or (
                request.destination.lon, request.destination.lat
            ) != destination:
                result = self._request_scoped_route(
                    envelope, request, TravelMode.BUS
                )
                itinerary = result.payload[0]
                leg = itinerary.legs[0]
                descriptor = envelope.payload[0].legs[0].transit
                return replace(
                    result,
                    payload=(
                        replace(
                            itinerary,
                            legs=(
                                replace(
                                    leg,
                                    transit=replace(
                                        descriptor,
                                        boarding_sequence=leg.from_stop.sequence,
                                        alighting_sequence=leg.to_stop.sequence,
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            template = envelope.payload[0].legs[0]
            departure = request.departure_time
            points = (
                origin,
                _between(origin, destination, 0.1),
                _between(origin, destination, 0.45),
                _between(origin, destination, 0.55),
                destination,
            )

            def stop(index):
                return CanonicalStop(
                    f"multi-stop-{index}",
                    ProviderCoordinate(*points[index]),
                    external_id=f"multi-stop-{index}",
                    sequence=index,
                )

            modes = (TravelMode.WALK, TravelMode.BUS, TravelMode.WALK, TravelMode.BUS)
            starts = (0, 30, 90, 120)
            durations = (30, 60, 30, 60)
            legs = []
            for index, (mode, offset, seconds) in enumerate(
                zip(modes, starts, durations)
            ):
                descriptor = None
                if mode is TravelMode.BUS:
                    descriptor = replace(
                        template.transit,
                        boarding_sequence=4 + index * 10,
                        alighting_sequence=10 + index * 10,
                    )
                legs.append(
                    replace(
                        template,
                        leg_id=f"multi-{index}",
                        sequence=index,
                        mode=mode,
                        from_stop=(
                            replace(
                                stop(index),
                                sequence=4 + index * 10,
                            )
                            if mode is TravelMode.BUS else stop(index)
                        ),
                        to_stop=(
                            replace(
                                stop(index + 1),
                                sequence=10 + index * 10,
                            )
                            if mode is TravelMode.BUS else stop(index + 1)
                        ),
                        duration=ProviderTimeEstimate(
                            seconds, seconds + 60, DataOrigin.PROVIDER_ESTIMATE
                        ),
                        distance_meters=seconds,
                        fare=(
                            ProviderMoneyRange(
                                0, 0, 0, DataOrigin.PROVIDER_ESTIMATE
                            )
                            if mode is TravelMode.WALK else template.fare
                        ),
                        expected_start_at=None,
                        expected_end_at=None,
                        transit=descriptor,
                        geometry=(
                            ProviderCoordinate(*points[index]),
                            ProviderCoordinate(*points[index + 1]),
                        ),
                    )
                )
            result = replace(
                envelope,
                payload=(CanonicalItinerary("multi-itinerary", tuple(legs)),),
                normalized_count=1,
                fingerprint="b" * 64,
            )
            self._base._transit_attempts.set((result,))
            return result

    def _between(origin, destination, fraction):
        return (
            origin[0] + (destination[0] - origin[0]) * fraction,
            origin[1] + (destination[1] - origin[1]) * fraction,
        )

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = MultiLegProviders(base.providers, eta_seconds=1_000)

    class MixedMapping:
        def __call__(self, evidence, evaluated_at):
            first_bus_from = _between(
                _SCENARIO_ENDPOINTS["R1"][0],
                _SCENARIO_ENDPOINTS["R1"][1],
                0.1,
            )
            fault = (
                FixtureFault.NONE
                if (
                    evidence.leg.from_stop.coordinate.lon,
                    evidence.leg.from_stop.coordinate.lat,
                )
                == first_bus_from
                else FixtureFault.MAPPING_LOW
            )
            return _mapping_pipeline(evidence.leg, evaluated_at, fault)

    use_case = CanonicalFanInOptimizeRouteUseCase(
        "multi-leg",
        clock,
        dependencies=replace(
            base,
            providers=providers,
            mapping=MixedMapping(),
        ),
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    payload["constraints"]["maxWalkSeconds"] = 7_200
    context = RequestContext(
        "multi-leg-correlation",
        "multi-leg-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), context).response
    preserved = next((
        route for route in response["routes"]
        if [leg["mode"] for leg in route["legs"]]
        == ["WALK", "BUS", "WALK", "BUS"]
    ), None)
    assert preserved is not None, (
        use_case.trace.exact_patterns,
        use_case.trace.rejected_reasons,
        [[leg["mode"] for leg in route["legs"]] for route in response["routes"]],
    )
    first_bus, second_bus = preserved["legs"][1], preserved["legs"][3]
    assert first_bus["busIntelligence"] is not None
    assert first_bus["busIntelligence"]["userArrivalTime"] > payload["departureTime"]
    assert second_bus["busIntelligence"] is None
    first_providers = {item["provider"] for item in first_bus["provenance"]}
    second_providers = {item["provider"] for item in second_bus["provenance"]}
    assert any(item.startswith("TRANSPORT_MAPPING/") for item in first_providers)
    assert any(item.endswith("/arrivals") for item in first_providers)
    assert any("SEAT_RISK" in item for item in first_providers)
    assert not any(item.startswith("TRANSPORT_MAPPING/") for item in second_providers)
    assert not any("BUS_ETA" in item or "SEAT_RISK" in item for item in second_providers)
    assert sum(kind == "BUS_INTELLIGENCE" for _, kind in use_case.trace.exact_plan) == 2
    assert first_bus["from"]["coordinate"] == preserved["legs"][0]["to"]["coordinate"]
    assert second_bus["from"]["coordinate"] == preserved["legs"][2]["to"]["coordinate"]


def test_two_bus_model_versions_remain_leg_local_on_wire_and_in_persistence() -> None:
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    midpoint = (
        (origin[0] + destination[0]) / 2,
        (origin[1] + destination[1]) / 2,
    )

    class TwoBusProviders(_CausalProviderPorts):
        def transit(self, request, *, deadline):
            envelope = self._base.transit(request, deadline=deadline)
            request_points = (
                (request.origin.lon, request.origin.lat),
                (request.destination.lon, request.destination.lat),
            )
            if request_points != (origin, destination):
                result = self._request_scoped_route(
                    envelope, request, TravelMode.BUS, duration_seconds=90
                )
                itinerary = result.payload[0]
                leg = itinerary.legs[0]
                descriptor = envelope.payload[0].legs[0].transit
                result = replace(
                    result,
                    payload=(
                        replace(
                            itinerary,
                            legs=(
                                replace(
                                    leg,
                                    transit=replace(
                                        descriptor,
                                        boarding_sequence=leg.from_stop.sequence,
                                        alighting_sequence=leg.to_stop.sequence,
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
                self._base._transit_attempts.set((result,))
                return result

            template = envelope.payload[0].legs[0]

            def bus_leg(index, start, end, start_sequence, end_sequence):
                return replace(
                    template,
                    leg_id=f"version-bus-{index}",
                    sequence=index,
                    from_stop=CanonicalStop(
                        f"version-stop-{index}",
                        ProviderCoordinate(*start),
                        external_id=f"version-stop-{index}",
                        sequence=start_sequence,
                    ),
                    to_stop=CanonicalStop(
                        f"version-stop-{index + 1}",
                        ProviderCoordinate(*end),
                        external_id=f"version-stop-{index + 1}",
                        sequence=end_sequence,
                    ),
                    duration=ProviderTimeEstimate(
                        90, 120, DataOrigin.PROVIDER_ESTIMATE
                    ),
                    expected_start_at=None,
                    expected_end_at=None,
                    transit=replace(
                        template.transit,
                        boarding_sequence=start_sequence,
                        alighting_sequence=end_sequence,
                    ),
                    geometry=(ProviderCoordinate(*start), ProviderCoordinate(*end)),
                )

            result = replace(
                envelope,
                payload=(
                    CanonicalItinerary(
                        "version-two-bus",
                        (
                            bus_leg(0, origin, midpoint, 1, 10),
                            bus_leg(1, midpoint, destination, 11, 20),
                        ),
                    ),
                ),
                normalized_count=1,
                fingerprint="d" * 64,
            )
            self._base._transit_attempts.set((result,))
            return result

    route_ids = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    )

    class DistinctMapping:
        def __call__(self, evidence, evaluated_at):
            mapping, target = _mapping_pipeline(
                evidence.leg, evaluated_at, FixtureFault.NONE
            )
            index = 0 if evidence.leg.from_stop.coordinate.lon == origin[0] else 1
            route_id = route_ids[index]
            return (
                replace(
                    mapping,
                    selected=replace(mapping.selected, route_id=route_id),
                ),
                replace(
                    target,
                    route_id=route_id,
                    boarding=replace(
                        target.boarding, external_id=f"version-board-{index}"
                    ),
                    alighting=replace(
                        target.alighting, external_id=f"version-alight-{index}"
                    ),
                ),
            )

    class DistinctBusEngine:
        def __init__(self, eta_predictor, seat_predictor):
            del eta_predictor, seat_predictor

        def enrich(self, request):
            first = request.target_stop_id == "version-alight-0"
            return BusIntelligenceResult(
                enrichment_applied=True,
                candidate_vehicles=(),
                expected_wait_seconds=300 if first else 900,
                p90_wait_seconds=360 if first else 960,
                coverage="FIXTURE_ONLY",
                confidence_score=0.9,
                confidence_grade="HIGH",
                warnings=(),
                model_provenance=(
                    ModelProvenance(
                        "BUS_ETA",
                        "eta-z-first" if first else "eta-a-second",
                        "MODEL_PREDICTED",
                        "FIXTURE_ONLY",
                    ),
                    ModelProvenance(
                        "SEAT_RISK",
                        "seat-z-first" if first else "seat-a-second",
                        "MODEL_PREDICTED",
                        "FIXTURE_ONLY",
                    ),
                ),
            )

    clock = FakeClock()
    base = fixture_fan_in_dependencies(fixture_scenario("R1"))
    persistence = InMemoryOptimizationPersistence()
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "two-bus-model-versions",
        clock,
        dependencies=replace(
            base,
            providers=TwoBusProviders(base.providers),
            mapping=DistinctMapping(),
            persistence=persistence,
        ),
    )
    payload = _request_payload()
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "version-correlation",
        "version-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    with patch(
        "routing_api.fanin_integration.BusIntelligenceEngine",
        DistinctBusEngine,
    ):
        response = use_case.execute(OptimizeCommand(payload), context).response
    route = next(
        (
            route
            for route in response["routes"]
            if [leg["mode"] for leg in route["legs"]] == ["BUS", "BUS"]
        ),
        None,
    )
    assert route is not None, (
        use_case.trace.exact_patterns,
        use_case.trace.rejected_reasons,
        [[leg["mode"] for leg in item["legs"]] for item in response["routes"]],
    )
    expected_versions = (
        ("eta-z-first", "seat-z-first"),
        ("eta-a-second", "seat-a-second"),
    )
    for leg, (eta_version, seat_version) in zip(route["legs"], expected_versions):
        providers = {item["provider"] for item in leg["provenance"]}
        assert f"BUS_ETA_FIXTURE/{eta_version}" in providers
        assert f"SEAT_RISK_FIXTURE/{seat_version}" in providers
        assert not any(
            other in provider
            for other_pair in expected_versions
            if other_pair != (eta_version, seat_version)
            for other in other_pair
            for provider in providers
        )
    assert {
        (item["purpose"], item["version"]) for item in response["modelVersions"]
    } == {
        ("BUS_ETA", "eta-z-first"),
        ("BUS_ETA", "eta-a-second"),
        ("SEAT_RISK", "seat-z-first"),
        ("SEAT_RISK", "seat-a-second"),
    }

    rows = sorted(
        (
            item
            for item in persistence.values[0].bus_enrichments
            if item.route_key == route["routeId"]
        ),
        key=lambda item: item.leg_sequence,
    )
    assert [
        (item.eta_model_version, item.seat_model_version) for item in rows
    ] == list(expected_versions)
    assert all(item.entity_mapping_id is None for item in rows)


def test_missing_taxi_dispatch_estimate_drops_taxi_candidates_never_uses_zero() -> None:
    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    providers = _CausalProviderPorts(base.providers, taxi_upper_krw=2_500)
    use_case = SevenPatternFixtureOptimizeRouteUseCase(
        scenario,
        clock,
        dependencies=replace(
            base,
            providers=providers,
            taxi_dispatch=None,
        ),
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    payload["constraints"]["allowTaxiBridge"] = True
    context = RequestContext(
        "dispatch-correlation",
        "dispatch-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), context).response
    assert response["routes"]
    assert all(
        leg["mode"] != "TAXI"
        for route in response["routes"]
        for leg in route["legs"]
    )
    assert all("TAXI" not in pattern for pattern in use_case.trace.exact_patterns)


def test_gbis_arrival_and_location_stage_runs_in_parallel_and_keeps_order() -> None:
    class DelayedProviders:
        def arrivals(self, query, *, deadline):
            del query, deadline
            sleep(0.15)
            return "arrivals"

        def locations(self, query, *, deadline):
            del query, deadline
            sleep(0.15)
            return "locations"

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "parallel-gbis", clock, dependencies=fixture_fan_in_dependencies(scenario)
    )
    context = RequestContext(
        "parallel-correlation",
        "parallel-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    query = BusObservationQuery("route", "station", clock.now())
    started = monotonic()
    values = use_case._fetch_bus_observations(context, DelayedProviders(), query)
    elapsed = monotonic() - started
    assert values == ("arrivals", "locations")
    assert elapsed < 0.27


def test_bus_result_uses_propagated_arrival_with_fixed_as_of_and_mixed_mapping() -> None:
    scenario = fixture_scenario("R1")
    dependencies = fixture_fan_in_dependencies(scenario)
    providers = _CausalProviderPorts(dependencies.providers, eta_seconds=300)
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    departure = datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"])
    envelope = providers.transit(
        TransitSearchRequest(
            ProviderCoordinate(*origin),
            ProviderCoordinate(*destination),
            departure,
        ),
        deadline=Deadline.after_ms(1_000),
    )
    leg = envelope.payload[0].legs[0]
    high, high_target = _mapping_pipeline(leg, departure, FixtureFault.NONE)
    query = BusObservationQuery(
        high_target.route_id,
        high_target.boarding.external_id,
        departure,
    )
    arrivals = providers.arrivals(query, deadline=Deadline.after_ms(1_000))
    locations = providers.locations(query, deadline=Deadline.after_ms(1_000))
    early = _bus_result(
        high,
        high_target,
        departure + timedelta(seconds=60),
        True,
        arrivals,
        locations,
        dependencies.eta_predictor,
        dependencies.seat_predictor,
        query,
        service_type="SEATED",
        evaluated_at=departure,
    )
    late = _bus_result(
        high,
        high_target,
        departure + timedelta(seconds=360),
        True,
        arrivals,
        locations,
        dependencies.eta_predictor,
        dependencies.seat_predictor,
        query,
        service_type="SEATED",
        evaluated_at=departure,
    )
    low, low_target = _mapping_pipeline(leg, departure, FixtureFault.MAPPING_LOW)
    low_result = _bus_result(
        low,
        low_target,
        departure + timedelta(seconds=60),
        True,
        arrivals,
        locations,
        dependencies.eta_predictor,
        dependencies.seat_predictor,
        query,
        service_type="SEATED",
        evaluated_at=departure,
    )
    assert early.enrichment_applied is True
    assert early.candidate_vehicles[0].wait_p50_seconds == 240
    assert late.enrichment_applied is False
    assert late.expected_wait_seconds is None
    assert low_result.enrichment_applied is False
    assert low_result.expected_wait_seconds is None


def test_wire_leg_provenance_excludes_unrelated_provider_and_bus_models() -> None:
    response = _causal_response(taxi_upper_krw=2_500)
    for route in response["routes"]:
        for leg in route["legs"]:
            providers = [item["provider"] for item in leg["provenance"]]
            causal_suppliers = [
                item for item in providers
                if item.startswith("FIXTURE::") and "/" in item
                and "GBIS" not in item
            ]
            assert len(causal_suppliers) <= 1
            if leg["mode"] != "BUS":
                assert not any(item.startswith("TRANSPORT_MAPPING/") for item in providers)
                assert not any("BUS_ETA" in item or "SEAT_RISK" in item for item in providers)


def test_later_exact_upstream_bus_gets_its_own_mapping_bus_and_persistence() -> None:
    class UpstreamWins(_CausalProviderPorts):
        def transit(self, request, *, deadline):
            origin, destination = _SCENARIO_ENDPOINTS["R1"]
            upstream = (
                origin[0] + (destination[0] - origin[0]) * 0.12,
                origin[1] + (destination[1] - origin[1]) * 0.12,
            )
            if (request.origin.lon, request.origin.lat) == origin and (
                request.destination.lon, request.destination.lat
            ) == destination:
                envelope = self._base.transit(request, deadline=deadline)
                self.queries.append(("TRANSIT", origin, destination))
                return self._replace_leg(
                    envelope,
                    lambda leg: replace(
                        leg,
                        duration=ProviderTimeEstimate(
                            3_000, 3_300, DataOrigin.PROVIDER_ESTIMATE
                        ),
                    ),
                )
            result = super().transit(request, deadline=deadline)
            if (request.origin.lon, request.origin.lat) == upstream:
                return self._replace_leg(
                    result,
                    lambda leg: replace(
                        leg,
                        duration=ProviderTimeEstimate(
                            60, 90, DataOrigin.PROVIDER_ESTIMATE
                        ),
                        from_stop=replace(leg.from_stop, sequence=2),
                        to_stop=replace(leg.to_stop, sequence=27),
                        expected_start_at=None,
                        expected_end_at=None,
                    ),
                )
            return result

        def taxi(self, request, *, deadline):
            result = super().taxi(request, deadline=deadline)
            origin, destination = _SCENARIO_ENDPOINTS["R1"]
            upstream = (
                origin[0] + (destination[0] - origin[0]) * 0.12,
                origin[1] + (destination[1] - origin[1]) * 0.12,
            )
            if (request.origin.lon, request.origin.lat) == origin and (
                request.destination.lon, request.destination.lat
            ) == upstream:
                return self._replace_leg(
                    result,
                    lambda leg: replace(
                        leg,
                        duration=ProviderTimeEstimate(
                            30, 45, DataOrigin.PROVIDER_ESTIMATE
                        ),
                    ),
                )
            return self._replace_leg(
                result,
                lambda leg: replace(
                    leg,
                    duration=ProviderTimeEstimate(
                        5_000, 5_300, DataOrigin.PROVIDER_ESTIMATE
                    ),
                    fare=ProviderMoneyRange(
                        9_000, 9_000, 9_000, DataOrigin.PROVIDER_ESTIMATE
                    ),
                ),
            )

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    persistence = InMemoryOptimizationPersistence()
    providers = UpstreamWins(
        base.providers,
        taxi_upper_krw=500,
        eta_seconds=900,
    )
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "upstream-high",
        clock,
        dependencies=replace(
            base,
            providers=providers,
            persistence=persistence,
        ),
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "upstream-correlation",
        "upstream-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), context).response
    upstream_route = next((
        route for route in response["routes"]
        if route["pattern"] == "UPSTREAM_STOP_TAXI_TRANSIT"
    ), None)
    assert upstream_route is not None, (
        use_case.trace.exact_patterns,
        use_case.trace.rejected_reasons,
        [route["pattern"] for route in response["routes"]],
    )
    bus = upstream_route["legs"][1]
    assert bus["busIntelligence"] is not None
    assert bus["busIntelligence"]["userArrivalTime"] > payload["departureTime"]
    assert bus["from"]["canonicalStopId"] is not None
    stored = persistence.values[0]
    assert any(
        item.route_key == upstream_route["routeId"] and item.leg_sequence == 1
        for item in stored.bus_enrichments
    )


def test_optional_slow_gbis_keeps_valid_route_partial_with_null_bus() -> None:
    class SlowLocations(_CausalProviderPorts):
        def locations(self, query, *, deadline):
            sleep(0.8)
            return super().locations(query, deadline=deadline)

    clock = FakeClock()
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "slow-gbis",
        clock,
        dependencies=replace(
            base,
            providers=SlowLocations(base.providers),
        ),
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    context = RequestContext(
        "slow-gbis-correlation",
        "slow-gbis-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    result = use_case.execute(OptimizeCommand(payload), context)
    assert result.response["routes"]
    assert result.response["status"] == "PARTIAL"
    assert all(
        leg["busIntelligence"] is None
        for route in result.response["routes"]
        for leg in route["legs"]
        if leg["mode"] == "BUS"
    )


@pytest.mark.parametrize(
    ("seat_available", "expected_status"),
    [(True, "COMPLETE"), (False, "PARTIAL")],
)
def test_production_shaped_complete_requires_full_seated_coverage(
    seat_available, expected_status
) -> None:
    class VerifiedProviders(_CausalProviderPorts):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._attempts = ()

        @property
        def last_transit_attempt_count(self):
            return len(self._attempts)

        @property
        def last_transit_envelopes(self):
            return self._attempts

        def transit(self, request, *, deadline):
            value = replace(
                super().transit(request, deadline=deadline),
                provider="KAKAO_PUBLIC_TRANSIT",
            )
            self._attempts = (value,)
            return value

        def walk(self, request, *, deadline):
            return replace(
                super().walk(request, deadline=deadline),
                provider="KAKAO_WALK",
            )

        def taxi(self, request, *, deadline):
            return replace(
                super().taxi(request, deadline=deadline),
                provider="KAKAO_MOBILITY",
            )

        def arrivals(self, query, *, deadline):
            return replace(
                super().arrivals(query, deadline=deadline), provider="GBIS"
            )

        def locations(self, query, *, deadline):
            return replace(
                super().locations(query, deadline=deadline), provider="GBIS"
            )

    class ActiveSeatPredictor:
        def predict(self, value):
            if not seat_available:
                return None
            return SeatRiskPrediction(
                no_seat_probability=0.1,
                low_seat2_probability=0.2,
                low_seat5_probability=0.3,
                model_version="seat-active-1.0.0",
                confidence=0.9,
                model_readiness="ACTIVE",
            )

    # This injected verified snapshot is evaluated at the journey instant;
    # production must never use a future departure as the observation clock.
    clock = FakeClock(
        wall=datetime.fromisoformat(_SCENARIO_DEPARTURES["R1"])
    )
    scenario = fixture_scenario("R1")
    base = fixture_fan_in_dependencies(scenario)
    persistence = InMemoryOptimizationPersistence()
    providers = VerifiedProviders(
        base.providers,
        transit_seconds=600,
        taxi_upper_krw=9_000,
    )
    use_case = CanonicalFanInOptimizeRouteUseCase(
        "verified-status",
        clock,
        dependencies=replace(
            base,
            providers=providers,
            seat_predictor=ActiveSeatPredictor(),
            persistence=persistence,
            fixture_only=False,
        ),
    )
    payload = _request_payload()
    origin, destination = _SCENARIO_ENDPOINTS["R1"]
    payload["origin"]["coordinate"] = {"lon": origin[0], "lat": origin[1]}
    payload["destination"]["coordinate"] = {
        "lon": destination[0], "lat": destination[1]
    }
    payload["departureTime"] = _SCENARIO_DEPARTURES["R1"]
    payload["constraints"]["allowTaxiBridge"] = True
    payload["constraints"]["taxiBudget"]["maxAmount"] = 50_000
    context = RequestContext(
        "verified-correlation",
        "verified-idempotency",
        clock.now() + timedelta(seconds=6),
        clock.now() + timedelta(seconds=6),
        True,
        threading.Event(),
    )
    response = use_case.execute(OptimizeCommand(payload), context).response
    assert any(leg["mode"] == "BUS" for route in response["routes"] for leg in route["legs"])
    assert response["status"] == expected_status
