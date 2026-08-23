from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from bus_intelligence_core import (
    BusIntelligenceEngine,
    BusIntelligenceRequest,
    BusIntelligenceResult,
    EnginePolicy,
    EtaPrediction,
    SeatRiskPrediction,
    VehicleObservation,
)
from provider_core import Coordinate as ProviderCoordinate
from provider_core import ProviderEnvelope, ProviderStatus, TransitSearchRequest
from provider_core.adapters import FixtureScenario, FixtureTransitAdapter
from provider_core.resilience import Deadline
from routing_api.application import ApiResult, InMemoryIdempotencyStore, RoutingApiApplication
from routing_api.auth import Hs256ServiceBearerVerifier
from routing_api.capabilities import foundation_capability_projection
from routing_api.contract import CanonicalContractValidator
from routing_api.fixture_integration import IntegratedFixtureOptimizeRouteUseCase
from routing_api.fixture_scenarios import fixture_scenario
from routing_domain.replay_fixtures import ReplayScenario
from transport_mapping import (
    CanonicalRouteCandidate,
    MappingResult,
    ProviderMappingInput,
    StopSignal,
    ValidityWindow,
    map_candidate,
)
from transport_mapping.models import Coordinate as MappingCoordinate


KST = timezone(timedelta(hours=9))
FIXED_NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
JWT_SECRET = b"routing-replay-fixture-secret-value-32bytes"

CORRIDOR_COORDINATES: Mapping[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "MYONGJI_TO_PANGYO": ((127.187456, 37.222345), (127.111159, 37.394761)),
    "PANGYO_TO_MYONGJI": ((127.111159, 37.394761), (127.187456, 37.222345)),
    "GWANGGYO_TO_PANGYO": ((127.0510, 37.2890), (127.111159, 37.394761)),
    "PANGYO_TO_GWANGGYO": ((127.111159, 37.394761), (127.0510, 37.2890)),
}


@dataclass
class FakeClock:
    instant: datetime = FIXED_NOW
    tick: float = 100.0

    def now(self) -> datetime:
        return self.instant

    def monotonic(self) -> float:
        return self.tick


class NoEtaFallback:
    def __init__(self) -> None:
        self.inputs: list[object] = []

    def predict(self, value: object) -> None:
        self.inputs.append(value)
        return None


class FixtureSeatRiskPredictor:
    def __init__(self, values: Mapping[str, float | None]) -> None:
        self.values = values
        self.inputs: list[object] = []

    def predict(self, value: object) -> SeatRiskPrediction | None:
        self.inputs.append(value)
        probability = self.values[getattr(value, "vehicle_ref")]
        if probability is None:
            return None
        return SeatRiskPrediction(
            no_seat_probability=probability,
            low_seat2_probability=min(1.0, probability + 0.05),
            low_seat5_probability=min(1.0, probability + 0.10),
            model_version="fixture-seat-risk-v1",
            confidence=0.9,
            model_readiness="FIXTURE_ONLY",
        )


def provider_request(scenario: ReplayScenario) -> TransitSearchRequest:
    origin, destination = CORRIDOR_COORDINATES[scenario.corridor]
    return TransitSearchRequest(
        origin=ProviderCoordinate(*origin),
        destination=ProviderCoordinate(*destination),
        departure_time=scenario.departure_at,
    )


def run_provider(
    scenario: ReplayScenario,
    fixture_scenario_value: FixtureScenario = FixtureScenario.SUCCESS,
) -> ProviderEnvelope[object]:
    return FixtureTransitAdapter(fixture_scenario_value).search(
        provider_request(scenario),
        deadline=Deadline.after_ms(1_000, clock=lambda: 100.0),
    )


def map_canonical_bus_leg(
    envelope: ProviderEnvelope[object],
    *,
    target_direction: str | None = None,
) -> MappingResult:
    assert envelope.status is ProviderStatus.OK
    assert envelope.payload is not None
    itinerary = envelope.payload[0]  # type: ignore[index]
    leg = itinerary.legs[0]
    transit = leg.transit
    assert transit is not None

    def stop(value: object, sequence: int | None) -> StopSignal:
        coordinate = getattr(value, "coordinate")
        return StopSignal(
            name=getattr(value, "name"),
            coordinate=MappingCoordinate(coordinate.lon, coordinate.lat),
            external_id=getattr(value, "external_id"),
            sequence=sequence,
        )

    boarding = stop(leg.from_stop, transit.boarding_sequence)
    alighting = stop(leg.to_stop, transit.alighting_sequence)
    terminal_names = transit.terminal_names
    source = ProviderMappingInput(
        provider=envelope.provider,
        external_route_id=transit.external_route_id,
        route_name=transit.route_label,
        route_type=transit.route_type,
        boarding=boarding,
        alighting=alighting,
        direction=transit.direction,
        branch_id=transit.branch_id,
        origin_terminal=terminal_names[0] if terminal_names else None,
        destination_terminal=terminal_names[-1] if terminal_names else None,
    )
    evaluated_at = datetime(2026, 8, 23, 8, 0, tzinfo=KST)
    target = CanonicalRouteCandidate(
        route_id="canonical-sanitized-route-100",
        route_name=transit.route_label,
        route_type=transit.route_type,
        boarding=boarding,
        alighting=alighting,
        direction=target_direction if target_direction is not None else transit.direction,
        branch_id=transit.branch_id,
        origin_terminal=terminal_names[0] if terminal_names else None,
        destination_terminal=terminal_names[-1] if terminal_names else None,
        validity=ValidityWindow(evaluated_at - timedelta(days=1), evaluated_at + timedelta(days=1)),
        live_vehicle_exists=transit.live_vehicle_observed,
    )
    return map_candidate(source, target, evaluated_at=evaluated_at)


def bus_intelligence(
    mapping: MappingResult,
    *,
    user_arrival_at: datetime,
    seat_values: Mapping[str, float | None] | None = None,
) -> tuple[BusIntelligenceResult, FixtureSeatRiskPredictor]:
    seat_predictor = FixtureSeatRiskPredictor(
        seat_values or {"fixture-vehicle-1": 0.9, "fixture-vehicle-2": 0.1}
    )
    eta_predictor = NoEtaFallback()
    observations = (
        VehicleObservation(
            "fixture-vehicle-1",
            mapping.route_id,
            "OUTBOUND",
            "canonical-board",
            user_arrival_at - timedelta(seconds=30),
            EtaPrediction(
                user_arrival_at + timedelta(seconds=120),
                user_arrival_at + timedelta(seconds=180),
                "OFFICIAL",
            ),
            4,
            None,
        ),
        VehicleObservation(
            "fixture-vehicle-2",
            mapping.route_id,
            "OUTBOUND",
            "canonical-board",
            user_arrival_at - timedelta(seconds=20),
            EtaPrediction(
                user_arrival_at + timedelta(seconds=900),
                user_arrival_at + timedelta(seconds=960),
                "OFFICIAL",
            ),
            7,
            None,
        ),
    )
    result = BusIntelligenceEngine(
        eta_predictor,
        seat_predictor,
        EnginePolicy(conservative_headway_seconds=900),
    ).enrich(
        BusIntelligenceRequest(
            mapping.grade.value,
            mapping.allows_bus_intelligence,
            mapping.score,
            mapping.mapping_version,
            user_arrival_at,
            user_arrival_at,
            "canonical-target",
            "SEATED",
            observations,
        )
    )
    assert eta_predictor.inputs == []
    return result, seat_predictor


def request_payload(scenario: ReplayScenario) -> dict[str, object]:
    origin, destination = CORRIDOR_COORDINATES[scenario.corridor]
    return {
        "contractVersion": "1.0",
        "requestId": f"REPLAY-{scenario.replay_id}",
        "origin": {"coordinate": {"lon": origin[0], "lat": origin[1]}, "regionHint": None},
        "destination": {
            "coordinate": {"lon": destination[0], "lat": destination[1]},
            "regionHint": None,
        },
        "departureTime": scenario.departure_at.isoformat(),
        "arrivalDeadline": None,
        "constraints": {
            "taxiBudget": {
                "currency": "KRW",
                "maxAmount": scenario.constraints.taxi_budget_krw,
                "strict": scenario.constraints.strict_taxi_budget,
            },
            "maxWalkSeconds": scenario.constraints.max_walk_seconds,
            "maxTransfers": scenario.constraints.max_transfers,
            "maxTaxiLegs": scenario.constraints.max_taxi_legs,
            "allowTaxiBridge": scenario.constraints.allow_taxi_bridge,
            "allowedModes": sorted(scenario.constraints.allowed_modes),
        },
        "preference": {"profile": "BALANCED"},
        "requestedRecommendations": ["FASTEST", "STABLE", "EFFICIENT", "PUBLIC_TRANSIT_ONLY"],
        "clientContext": {"locale": "ko-KR", "timezone": "Asia/Seoul"},
    }


def _segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _token(clock: FakeClock, scenario_id: str) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload = _segment(
        {
            "iss": "service-api",
            "aud": "routing-api",
            "sub": "service-api-replay",
            "jti": f"replay-{scenario_id.lower()}",
            "exp": int((clock.now() + timedelta(minutes=5)).timestamp()),
        }
    )
    signature = hmac.new(JWT_SECRET, f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{header}.{payload}.{encoded_signature}"


def build_integrated_application(
    scenario_id: str,
) -> tuple[RoutingApiApplication, FakeClock]:
    clock = FakeClock()
    application = RoutingApiApplication(
        verifier=Hs256ServiceBearerVerifier(JWT_SECRET, "service-api", "routing-api", now=clock.now),
        contract=CanonicalContractValidator(),
        use_case=IntegratedFixtureOptimizeRouteUseCase(fixture_scenario(scenario_id), clock),
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version="replay-fixture-only",
        capability_projection=foundation_capability_projection(),
        backend_state=f"fixture-only:{scenario_id}",
    )
    return application, clock


def invoke_application(
    application: RoutingApiApplication,
    clock: FakeClock,
    scenario: ReplayScenario,
    scenario_id: str,
    *,
    payload: Mapping[str, object] | None = None,
    idempotency_key: str | None = None,
) -> ApiResult:
    request = dict(payload) if payload is not None else request_payload(scenario)
    request["requestId"] = str(request.get("requestId", f"REPLAY-{scenario_id}"))
    return application.optimize(
        authorization=f"Bearer {_token(clock, scenario_id)}",
        correlation_id=f"correlation-{scenario_id}",
        deadline_header=(clock.now() + timedelta(seconds=6)).isoformat(),
        idempotency_key=idempotency_key or f"idempotency-{scenario_id}",
        content_type="application/json",
        raw_body=json.dumps(request).encode("utf-8"),
    )


def invoke_integrated_private_api(scenario: ReplayScenario, scenario_id: str) -> ApiResult:
    application, clock = build_integrated_application(scenario_id)
    payload = request_payload(scenario)
    payload["requestId"] = f"REPLAY-{scenario_id}"
    return invoke_application(application, clock, scenario, scenario_id, payload=payload)
