"""Explicit fixture-only Provider→Mapping→Bus→Optimizer API composition.

This module is never imported by the fail-closed default container. It consumes
sanitized fixture adapters and canonical package values only; no caller-selected
path, URL, model artifact, raw provider object, or live capability enters it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from routing_api.application import (
    Clock,
    OptimizeCommand,
    RequestContext,
    RoutingUnavailableError,
    UseCaseResult,
)
from routing_api.fixture_scenarios import FixtureFault, IntegratedFixtureScenario
from routing_api.workspace_packages import activate_workspace_packages

try:
    import bus_intelligence_core as _bus_intelligence_core  # noqa: F401
    import provider_core as _provider_core  # noqa: F401
    import routing_domain as _routing_domain  # noqa: F401
except ModuleNotFoundError as exc:
    if exc.name not in {"bus_intelligence_core", "provider_core", "routing_domain"}:
        raise
    # Explicit fixture mode may run directly from a source checkout. Installed
    # deployments consume the internal wheels and never activate checkout paths.
    activate_workspace_packages()

from bus_intelligence_core import (  # noqa: E402
    BusIntelligenceEngine,
    BusIntelligenceRequest,
    BusIntelligenceResult,
    EtaPrediction,
    SeatRiskPrediction,
    VehicleObservation,
)
from provider_core.adapters import FixtureScenario, FixtureTransitAdapter  # noqa: E402
from provider_core.capabilities import foundation_capability_registry  # noqa: E402
from provider_core.canonical import (  # noqa: E402
    CanonicalItinerary,
    CanonicalLeg,
    Coordinate as ProviderCoordinate,
)
from provider_core.envelope import ProviderEnvelope, ProviderStatus  # noqa: E402
from provider_core.requests import TransitSearchRequest  # noqa: E402
from provider_core.resilience import Deadline  # noqa: E402
from routing_domain import (  # noqa: E402
    BusWaitContribution,
    CandidateSeed,
    LegCost,
    LegSpec,
    MoneyRange as DomainMoneyRange,
    RouteConstraints as DomainRouteConstraints,
    RouteOptimizer,
    StaticLegEvaluator,
    TimeEstimate as DomainTimeEstimate,
)
from transport_mapping import (  # noqa: E402
    CanonicalRouteCandidate,
    ProviderMappingInput,
    StopSignal,
    ValidityWindow,
    map_candidate,
)
from transport_mapping.models import Coordinate as MappingCoordinate  # noqa: E402


MAPPING_VERSION = "0.1.0-planned"
_ALLOWLISTED_CANONICAL_TARGETS = {
    "sanitized-route-100": (
        "fixture-gbis-route-s100",
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
    ),
    "sanitized-r1-route-701": (
        "fixture-gbis-route-r1-701",
        "00000000-0000-4000-8000-000000000101",
        "00000000-0000-4000-8000-000000000102",
    ),
    "sanitized-r2-route-702": (
        "fixture-gbis-route-r2-702",
        "00000000-0000-4000-8000-000000000201",
        "00000000-0000-4000-8000-000000000202",
    ),
    "sanitized-r3-route-703": (
        "fixture-gbis-route-r3-703",
        "00000000-0000-4000-8000-000000000301",
        "00000000-0000-4000-8000-000000000302",
    ),
    "sanitized-r4-route-704": (
        "fixture-gbis-route-r4-704",
        "00000000-0000-4000-8000-000000000401",
        "00000000-0000-4000-8000-000000000402",
    ),
}
_REPLAY_REQUEST_BUNDLES = {
    "R1": ((127.187456, 37.222345), (127.111159, 37.394761), "2026-08-24T07:40:00+09:00"),
    "R2": ((127.111159, 37.394761), (127.187456, 37.222345), "2026-08-24T18:10:00+09:00"),
    "R3": ((127.051, 37.289), (127.111159, 37.394761), "2026-08-24T08:05:00+09:00"),
    "R4": ((127.111159, 37.394761), (127.051, 37.289), "2026-08-24T19:20:00+09:00"),
}


class _FixtureEtaPredictor:
    def __init__(self, available: bool) -> None:
        self.available = available

    def predict(self, value) -> EtaPrediction | None:
        if not self.available:
            return None
        offset = 120 if value.vehicle_ref.endswith("1") else 600
        return EtaPrediction(
            p50_arrival_at=value.observed_at + timedelta(seconds=offset),
            p90_arrival_at=value.observed_at + timedelta(seconds=offset + 120),
            source="POSITION_MODEL",
            model_version="eta-fixture-0.1.0",
            confidence=0.8,
            model_readiness="FIXTURE_ONLY",
        )


class _FixtureSeatRiskPredictor:
    def __init__(self, available: bool, scenario: IntegratedFixtureScenario) -> None:
        self.available = available
        self.scenario = scenario

    def predict(self, value) -> SeatRiskPrediction | None:
        if not self.available:
            return None
        no_seat = (
            self.scenario.first_no_seat_probability
            if value.vehicle_ref.endswith("1")
            else self.scenario.second_no_seat_probability
        )
        return SeatRiskPrediction(
            no_seat_probability=no_seat,
            low_seat2_probability=min(1.0, no_seat + 0.15),
            low_seat5_probability=min(1.0, no_seat + 0.30),
            model_version="seat-fixture-0.1.0",
            confidence=0.8,
            model_readiness="FIXTURE_ONLY",
        )


@dataclass(frozen=True, slots=True)
class _IntegratedValues:
    envelope: ProviderEnvelope[tuple[CanonicalItinerary, ...]]
    itinerary: CanonicalItinerary
    provider_leg: CanonicalLeg
    mapping: object
    mapping_target: CanonicalRouteCandidate
    bus: BusIntelligenceResult
    user_arrival_at: datetime


def _provider_scenario(scenario: IntegratedFixtureScenario) -> FixtureScenario:
    fault_scenario = {
        FixtureFault.PROVIDER_EMPTY: FixtureScenario.EMPTY,
        FixtureFault.PROVIDER_TIMEOUT: FixtureScenario.TIMEOUT,
        FixtureFault.PROVIDER_RATE_LIMITED: FixtureScenario.RATE_LIMITED,
        FixtureFault.PROVIDER_SCHEMA_DRIFT: FixtureScenario.SCHEMA_DRIFT,
    }.get(scenario.fault)
    if fault_scenario is not None:
        return fault_scenario
    if scenario.fault in {
        FixtureFault.MAPPING_LOW,
        FixtureFault.ETA_UNAVAILABLE,
        FixtureFault.SEAT_UNAVAILABLE,
    }:
        return FixtureScenario.R1_SUCCESS
    return {
        "R1": FixtureScenario.R1_SUCCESS,
        "R2": FixtureScenario.R2_SUCCESS,
        "R3": FixtureScenario.R3_SUCCESS,
        "R4": FixtureScenario.R4_SUCCESS,
    }.get(scenario.scenario_id, FixtureScenario.SUCCESS)


def _aware_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _coordinates_equal(canonical: object, requested: object) -> bool:
    if not isinstance(requested, Mapping):
        return False
    try:
        return all(
            abs(float(getattr(canonical, axis)) - float(requested[axis])) <= 1e-6
            for axis in ("lon", "lat")
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _mapping_coordinates_equal(requested: object, expected: tuple[float, float]) -> bool:
    if not isinstance(requested, Mapping):
        return False
    try:
        return all(
            abs(float(requested[axis]) - expected[index]) <= 1e-6
            for index, axis in enumerate(("lon", "lat"))
        )
    except (KeyError, TypeError, ValueError):
        return False


def _mapping_input(leg: CanonicalLeg) -> ProviderMappingInput:
    if leg.transit is None:
        raise RoutingUnavailableError("fixture BUS leg lacks canonical transit evidence")
    transit = leg.transit
    terminals = transit.terminal_names
    return ProviderMappingInput(
        provider="SANITIZED_TRANSIT_FIXTURE",
        external_route_id=transit.external_route_id,
        route_name=transit.route_label,
        route_type=transit.route_type,
        boarding=StopSignal(
            name=leg.from_stop.name,
            coordinate=MappingCoordinate(leg.from_stop.coordinate.lon, leg.from_stop.coordinate.lat),
            external_id=leg.from_stop.external_id,
            sequence=transit.boarding_sequence,
        ),
        alighting=StopSignal(
            name=leg.to_stop.name,
            coordinate=MappingCoordinate(leg.to_stop.coordinate.lon, leg.to_stop.coordinate.lat),
            external_id=leg.to_stop.external_id,
            sequence=transit.alighting_sequence,
        ),
        direction=transit.direction,
        branch_id=transit.branch_id,
        origin_terminal=terminals[0] if terminals else None,
        destination_terminal=terminals[-1] if terminals else None,
    )


def _mapping_target(
    source: ProviderMappingInput,
    evaluated_at: datetime,
    fault: FixtureFault,
) -> CanonicalRouteCandidate:
    direction = "fixture-opposite-direction" if fault is FixtureFault.MAPPING_LOW else source.direction
    try:
        route_id, boarding_id, alighting_id = _ALLOWLISTED_CANONICAL_TARGETS[
            source.external_route_id
        ]
    except KeyError as exc:
        raise RoutingUnavailableError("fixture route is not allowlisted for mapping") from exc
    return CanonicalRouteCandidate(
        route_id=route_id,
        route_name=source.route_name,
        route_type=source.route_type,
        boarding=StopSignal(
            name=source.boarding.name,
            coordinate=source.boarding.coordinate,
            external_id=boarding_id,
            sequence=source.boarding.sequence,
        ),
        alighting=StopSignal(
            name=source.alighting.name,
            coordinate=source.alighting.coordinate,
            external_id=alighting_id,
            sequence=source.alighting.sequence,
        ),
        direction=direction,
        branch_id=source.branch_id,
        origin_terminal=source.origin_terminal,
        destination_terminal=source.destination_terminal,
        validity=ValidityWindow(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        geometry_similarity_to_provider=1.0,
        live_vehicle_exists=None,
    )


def _bus_result(
    scenario: IntegratedFixtureScenario,
    mapping,
    target: CanonicalRouteCandidate,
    departure_at: datetime,
    optional_allowed: bool,
) -> BusIntelligenceResult:
    observations: tuple[VehicleObservation, ...] = ()
    if optional_allowed:
        observations = tuple(
            VehicleObservation(
                vehicle_ref=f"fixture-vehicle-{index}",
                route_id=target.route_id,
                direction=target.direction or "UNKNOWN",
                boarding_stop_id=target.boarding.external_id or "fixture-gbis-stop-a",
                observed_at=departure_at,
                official_eta=None,
                remain_seat_observed=4,
                future_target_remaining_seats=None,
            )
            for index in (1, 2)
        )
    engine = BusIntelligenceEngine(
        _FixtureEtaPredictor(
            optional_allowed and scenario.fault is not FixtureFault.ETA_UNAVAILABLE
        ),
        _FixtureSeatRiskPredictor(
            optional_allowed and scenario.fault is not FixtureFault.SEAT_UNAVAILABLE,
            scenario,
        ),
    )
    return engine.enrich(
        BusIntelligenceRequest(
            mapping_grade=str(mapping.grade),
            mapping_allows_bus_intelligence=mapping.allows_bus_intelligence,
            mapping_score=mapping.score,
            mapping_version=mapping.mapping_version,
            user_arrival_at=departure_at,
            evaluated_at=departure_at,
            target_stop_id=target.alighting.external_id or "fixture-gbis-stop-b",
            service_type="SEATED",
            observations=observations,
        )
    )


class _LegacyIntegratedFixtureOptimizeRouteUseCase:
    """One deterministic fan-in path, enabled only by explicit DI/local mode."""

    def __init__(self, scenario: IntegratedFixtureScenario, clock: Clock) -> None:
        self._scenario = scenario
        self._clock = clock

    def execute(self, command: OptimizeCommand, context: RequestContext) -> UseCaseResult:
        payload = command.payload
        departure_at = _aware_timestamp(payload["departureTime"])
        origin = payload["origin"]["coordinate"]  # type: ignore[index]
        destination = payload["destination"]["coordinate"]  # type: ignore[index]
        replay_id = (
            "R1"
            if self._scenario.fault
            in {
                FixtureFault.MAPPING_LOW,
                FixtureFault.ETA_UNAVAILABLE,
                FixtureFault.SEAT_UNAVAILABLE,
            }
            else self._scenario.scenario_id
        )
        expected_bundle = _REPLAY_REQUEST_BUNDLES.get(replay_id)
        if expected_bundle is not None:
            expected_origin, expected_destination, expected_departure = expected_bundle
            if not (
                _mapping_coordinates_equal(origin, expected_origin)
                and _mapping_coordinates_equal(destination, expected_destination)
                and departure_at == _aware_timestamp(expected_departure)
            ):
                raise RoutingUnavailableError(
                    "fixture scenario does not match its allowlisted replay request"
                )
        remaining_ms = max(
            1,
            min(
                1_800,
                int((context.effective_deadline - self._clock.now()).total_seconds() * 1000),
            ),
        )
        envelope = FixtureTransitAdapter(_provider_scenario(self._scenario)).search(
            TransitSearchRequest(
                origin=ProviderCoordinate(float(origin["lon"]), float(origin["lat"])),
                destination=ProviderCoordinate(
                    float(destination["lon"]), float(destination["lat"])
                ),
                departure_time=departure_at,
                max_itineraries=5,
            ),
            deadline=Deadline.after_ms(remaining_ms),
        )
        if envelope.status is not ProviderStatus.OK or not envelope.payload:
            raise RoutingUnavailableError(
                f"fixture baseline unavailable: {envelope.status.value}"
            )
        itinerary = envelope.payload[0]
        if not (
            _coordinates_equal(itinerary.legs[0].from_stop.coordinate, origin)
            and _coordinates_equal(itinerary.legs[-1].to_stop.coordinate, destination)
        ):
            raise RoutingUnavailableError(
                "fixture canonical endpoints do not match the routing request"
            )
        provider_leg = next(
            (leg for leg in itinerary.legs if leg.mode.value == "BUS"),
            None,
        )
        if provider_leg is None:
            raise RoutingUnavailableError("fixture itinerary has no BUS leg")

        source = _mapping_input(provider_leg)
        target = _mapping_target(source, departure_at, self._scenario.fault)
        mapping = map_candidate(
            source,
            target,
            evaluated_at=departure_at,
            mapping_version=MAPPING_VERSION,
        )
        bus = _bus_result(
            self._scenario,
            mapping,
            target,
            departure_at,
            context.optional_enrichment_allowed,
        )
        values = _IntegratedValues(
            envelope,
            itinerary,
            provider_leg,
            mapping,
            target,
            bus,
            departure_at,
        )
        response = self._optimize_and_project(payload, values, departure_at)
        warnings = tuple(response["warningCodes"])  # type: ignore[arg-type]
        return UseCaseResult(
            response=response,
            optional_enrichment_complete=bus.enrichment_applied,
            warning_codes=warnings,
        )

    def _optimize_and_project(
        self,
        payload: Mapping[str, object],
        values: _IntegratedValues,
        departure_at: datetime,
    ) -> Mapping[str, object]:
        leg = values.provider_leg
        bus_wait = None
        if (
            values.bus.enrichment_applied
            and values.bus.expected_wait_seconds is not None
            and values.bus.p90_wait_seconds is not None
        ):
            bus_wait = BusWaitContribution(
                values.bus.expected_wait_seconds,
                values.bus.p90_wait_seconds,
            )
        seed = CandidateSeed(
            candidate_key=f"{self._scenario.scenario_id.lower()}-fixture-provider",
            pattern="TRANSIT_ONLY",
            legs=(
                LegSpec(
                    leg_id=leg.leg_id,
                    mode=leg.mode.value,
                    from_ref=leg.from_stop.external_id or "fixture-stop-a",
                    to_ref=leg.to_stop.external_id or "fixture-stop-b",
                    evaluator_key="fixture-provider-leg",
                    distance_meters=leg.distance_meters,
                    bus_wait=bus_wait,
                    topology_ref=(
                        values.mapping_target.route_id
                        if values.mapping.allows_bus_intelligence
                        else (
                            leg.transit.external_route_id
                            if leg.transit is not None
                            else leg.leg_id
                        )
                    ),
                ),
            ),
            transfer_count=0,
            coarse_p50_seconds=leg.duration.p50_seconds
            + (bus_wait.expected_wait_seconds if bus_wait else 0),
            coarse_taxi_upper_krw=0,
        )
        evaluator = StaticLegEvaluator(
            {
                "fixture-provider-leg": LegCost(
                    wait=DomainTimeEstimate(0, 0),
                    travel=DomainTimeEstimate(
                        leg.duration.p50_seconds,
                        leg.duration.p90_seconds,
                    ),
                    fare=DomainMoneyRange(
                        leg.fare.expected_krw,
                        leg.fare.lower_krw,
                        leg.fare.upper_krw,
                    ),
                    reliability_score=0.9,
                )
            }
        )
        raw_constraints = payload["constraints"]  # type: ignore[index]
        raw_budget = raw_constraints["taxiBudget"]  # type: ignore[index]
        constraints = DomainRouteConstraints(
            taxi_budget_krw=int(raw_budget["maxAmount"]),  # type: ignore[index]
            strict_taxi_budget=bool(raw_budget["strict"]),  # type: ignore[index]
            max_walk_seconds=int(raw_constraints["maxWalkSeconds"]),  # type: ignore[index]
            max_transfers=int(raw_constraints["maxTransfers"]),  # type: ignore[index]
            max_taxi_legs=int(raw_constraints["maxTaxiLegs"]),  # type: ignore[index]
            allowed_modes=frozenset(raw_constraints["allowedModes"]),  # type: ignore[index]
            allow_taxi_bridge=bool(raw_constraints.get("allowTaxiBridge", False)),  # type: ignore[union-attr]
        )
        optimized = RouteOptimizer(evaluator).optimize(
            (seed,),
            departure_at,
            constraints,
            provider_call_count=1,
        )
        now = self._clock.now().astimezone(timezone.utc)
        provider_status = self._provider_status(values.envelope)
        if not optimized.routes:
            return {
                "contractVersion": "1.0",
                "requestId": str(payload["requestId"]),
                "status": "NO_FEASIBLE_ROUTE",
                "generatedAt": now.isoformat(),
                "expiresAt": (now + timedelta(seconds=120)).isoformat(),
                "computation": self._computation(
                    optimized,
                    (
                        values.mapping.mapping_version
                        if values.mapping.allows_bus_intelligence
                        else None
                    ),
                ),
                "recommendations": {
                    "fastest": None,
                    "stable": None,
                    "efficient": None,
                    "publicTransitOnly": None,
                },
                "routes": [],
                "paretoRouteIds": [],
                "providerStatus": provider_status,
                "modelVersions": [],
                "warningCodes": [],
            }

        pareto_ids = frozenset(optimized.pareto_route_ids)
        routes = [
            self._route(item, values, now, pareto_ids) for item in optimized.routes
        ]
        warnings = set(values.bus.warnings)
        requested = set(payload["requestedRecommendations"])  # type: ignore[arg-type]
        return {
            "contractVersion": "1.0",
            "requestId": str(payload["requestId"]),
            "status": "PARTIAL",
            "generatedAt": now.isoformat(),
            "expiresAt": (now + timedelta(seconds=120)).isoformat(),
            "computation": self._computation(
                optimized,
                (
                    values.mapping.mapping_version
                    if values.mapping.allows_bus_intelligence
                    else None
                ),
            ),
            "recommendations": {
                "fastest": (
                    optimized.recommendations.fastest if "FASTEST" in requested else None
                ),
                "stable": (
                    optimized.recommendations.stable if "STABLE" in requested else None
                ),
                "efficient": (
                    optimized.recommendations.efficient if "EFFICIENT" in requested else None
                ),
                "publicTransitOnly": (
                    optimized.recommendations.public_transit_only
                    if "PUBLIC_TRANSIT_ONLY" in requested
                    else None
                ),
            },
            "routes": routes,
            "paretoRouteIds": list(optimized.pareto_route_ids),
            "providerStatus": provider_status,
            "modelVersions": self._model_versions(values),
            "warningCodes": sorted(warnings),
        }

    @staticmethod
    def _model_versions(values: _IntegratedValues) -> list[Mapping[str, str]]:
        if not values.bus.enrichment_applied:
            return []
        unique = {
            (item.purpose, item.version)
            for item in values.bus.model_provenance
            if item.purpose in {"BUS_ETA", "SEAT_RISK"}
        }
        return [
            {"purpose": purpose, "version": version}
            for purpose, version in sorted(unique)
        ]

    @staticmethod
    def _computation(
        optimized, mapping_version: str | None
    ) -> Mapping[str, object]:
        return {
            "durationMs": 0,
            "rankingPolicyVersion": optimized.ranking_policy_version,
            "mappingVersion": mapping_version,
            "candidateCounts": {
                "generated": optimized.counts.generated,
                "coarsePruned": max(0, optimized.counts.supplied - optimized.counts.generated),
                "fullyEvaluated": optimized.counts.fully_evaluated,
                "pareto": optimized.counts.pareto,
            },
            "cache": {"fixture": False},
        }

    @staticmethod
    def _provider_status(envelope: ProviderEnvelope) -> list[Mapping[str, object]]:
        values: list[Mapping[str, object]] = [
            {
                "provider": envelope.provider,
                "operation": envelope.operation,
                "status": envelope.status.value,
                "latencyMs": envelope.latency_ms,
                "cache": envelope.cache_hit,
                "messageCode": envelope.message_code,
            }
        ]
        values.extend(
            {
                "provider": capability.provider,
                "operation": capability.operation,
                "status": "DISABLED",
                "latencyMs": 0,
                "cache": False,
                "messageCode": None,
            }
            for capability in foundation_capability_registry().all()
        )
        return values

    def _route(
        self,
        candidate,
        values: _IntegratedValues,
        now: datetime,
        pareto_ids: frozenset[str],
    ) -> Mapping[str, object]:
        bus_projection = self._bus_projection(values)
        route_provenance = self._provenance(values, now)
        leg_by_id = {values.provider_leg.leg_id: values.provider_leg}
        legs = [
            self._leg(
                evaluated_leg,
                leg_by_id[evaluated_leg.leg_id],
                values.mapping_target,
                values.mapping.allows_bus_intelligence,
                bus_projection,
                route_provenance,
            )
            for evaluated_leg in candidate.legs
        ]
        origin = "MODEL_PREDICTED" if values.bus.enrichment_applied else "PROVIDER_ESTIMATE"
        warnings = sorted(set(candidate.warning_codes) | set(values.bus.warnings))
        return {
            "routeId": candidate.route_id,
            "pattern": candidate.pattern,
            "totalDuration": self._time_estimate(
                candidate.total_duration.p50_seconds,
                candidate.total_duration.p90_seconds,
                candidate.reliability_score,
                origin,
            ),
            "arrivalAt": {
                "p50": candidate.arrival_at_p50.isoformat(),
                "p90": candidate.arrival_at_p90.isoformat(),
            },
            "taxiCost": self._money(candidate.taxi_cost, "PROVIDER_ESTIMATE"),
            "totalFareExpected": candidate.total_fare_expected_krw,
            "walkSeconds": candidate.walk_seconds,
            "transferCount": candidate.transfer_count,
            "taxiLegCount": candidate.taxi_leg_count,
            "reliabilityScore": candidate.reliability_score,
            "dominance": {"onParetoFrontier": candidate.route_id in pareto_ids},
            "legs": legs,
            "reasonCodes": list(candidate.reason_codes),
            "warningCodes": warnings,
            "provenance": route_provenance,
        }

    @staticmethod
    def _money(value, origin: str) -> Mapping[str, object]:
        return {
            "currency": "KRW",
            "expected": value.expected_krw,
            "lower": value.lower_krw,
            "upper": value.upper_krw,
            "origin": origin,
        }

    @staticmethod
    def _confidence(score: float) -> Mapping[str, object]:
        grade = "HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.55 else "LOW" if score > 0 else "UNKNOWN"
        return {"score": round(score, 6), "grade": grade}

    @classmethod
    def _time_estimate(
        cls, p50: int, p90: int, confidence: float, origin: str
    ) -> Mapping[str, object]:
        return {
            "p50Seconds": p50,
            "p90Seconds": p90,
            "lowerSeconds": None,
            "upperSeconds": None,
            "confidence": cls._confidence(confidence),
            "origin": origin,
        }

    def _leg(
        self,
        evaluated,
        provider_leg: CanonicalLeg,
        mapping_target: CanonicalRouteCandidate,
        mapping_accepted: bool,
        bus_projection: Mapping[str, object] | None,
        provenance: list[Mapping[str, object]],
    ) -> Mapping[str, object]:
        transit = provider_leg.transit
        assert transit is not None
        return {
            "legId": evaluated.leg_id,
            "sequence": evaluated.sequence,
            "mode": evaluated.mode,
            "from": {
                "name": provider_leg.from_stop.name,
                "coordinate": {
                    "lon": provider_leg.from_stop.coordinate.lon,
                    "lat": provider_leg.from_stop.coordinate.lat,
                },
                "canonicalStopId": (
                    mapping_target.boarding.external_id if mapping_accepted else None
                ),
                "providerStopId": provider_leg.from_stop.external_id,
            },
            "to": {
                "name": provider_leg.to_stop.name,
                "coordinate": {
                    "lon": provider_leg.to_stop.coordinate.lon,
                    "lat": provider_leg.to_stop.coordinate.lat,
                },
                "canonicalStopId": (
                    mapping_target.alighting.external_id if mapping_accepted else None
                ),
                "providerStopId": provider_leg.to_stop.external_id,
            },
            "expectedStartAt": (
                evaluated.end_at_p50
                - timedelta(seconds=evaluated.duration.p50_seconds)
            ).isoformat(),
            "expectedEndAt": evaluated.end_at_p50.isoformat(),
            "duration": self._time_estimate(
                evaluated.duration.p50_seconds,
                evaluated.duration.p90_seconds,
                evaluated.reliability_score,
                "MODEL_PREDICTED" if bus_projection is not None else "PROVIDER_ESTIMATE",
            ),
            "distanceMeters": evaluated.distance_meters,
            "fare": self._money(evaluated.fare, "PROVIDER_ESTIMATE"),
            "geometry": {
                "encoding": "GEOJSON",
                "value": {
                    "type": "LineString",
                    "coordinates": [
                        [point.lon, point.lat] for point in provider_leg.geometry
                    ],
                },
            },
            "transit": {
                "routeLabel": transit.route_label,
                "externalRouteId": transit.external_route_id,
                "routeType": transit.route_type,
                "direction": transit.direction,
            },
            "busIntelligence": bus_projection,
            "provenance": provenance,
        }

    def _bus_projection(self, values: _IntegratedValues) -> Mapping[str, object] | None:
        bus = values.bus
        if (
            not bus.enrichment_applied
            or not isinstance(bus.expected_wait_seconds, int)
            or not isinstance(bus.p90_wait_seconds, int)
        ):
            return None
        target = values.mapping_target
        return {
            "mapping": {
                "gbisRouteId": target.route_id,
                "boardingStationId": target.boarding.external_id,
                "alightingStationId": target.alighting.external_id,
                "score": values.mapping.score,
                "grade": str(values.mapping.grade),
                "mappingVersion": values.mapping.mapping_version,
            },
            "userArrivalTime": values.user_arrival_at.isoformat(),
            "candidateVehicles": [
                {
                    "vehicleRef": item.vehicle_ref,
                    "eta": self._time_estimate(
                        item.wait_p50_seconds,
                        item.wait_p90_seconds,
                        item.eta.confidence,
                        {
                            "OFFICIAL": "PROVIDER_ESTIMATE",
                            "POSITION_MODEL": "MODEL_PREDICTED",
                            "HISTORICAL": "HISTORICAL_PROXY",
                        }[item.eta.source],
                    ),
                    "remainSeatObserved": item.remain_seat_observed,
                    "seatRiskAtBoarding": (
                        {
                            "noSeatProbability": item.seat_risk_at_boarding.no_seat_probability,
                            "lowSeat2Probability": item.seat_risk_at_boarding.low_seat2_probability,
                            "lowSeat5Probability": item.seat_risk_at_boarding.low_seat5_probability,
                            "modelVersion": item.seat_risk_at_boarding.model_version,
                        }
                        if item.seat_risk_at_boarding is not None
                        else None
                    ),
                    "boardabilityProxy": item.boardability_proxy,
                }
                for item in bus.candidate_vehicles
            ],
            "expectedWaitSeconds": bus.expected_wait_seconds,
            "p90WaitSeconds": bus.p90_wait_seconds,
            "coverage": bus.coverage,
            "warnings": list(bus.warnings),
        }

    def _provenance(
        self, values: _IntegratedValues, now: datetime
    ) -> list[Mapping[str, object]]:
        age = (
            int((values.envelope.received_at - values.envelope.observed_at).total_seconds())
            if values.envelope.observed_at is not None
            else None
        )
        result: list[Mapping[str, object]] = [
            {
                "provider": values.envelope.provider,
                "origin": "PROVIDER_ESTIMATE",
                "observedAt": (
                    values.envelope.observed_at.isoformat()
                    if values.envelope.observed_at is not None
                    else None
                ),
                "receivedAt": values.envelope.received_at.isoformat(),
                "ageSeconds": age,
                "confidence": self._confidence(0.0),
                "fallbackLevel": 0,
            },
            {
                "provider": f"TRANSPORT_MAPPING/{values.mapping.mapping_version}",
                "origin": "UNKNOWN",
                "observedAt": None,
                "receivedAt": now.isoformat(),
                "ageSeconds": None,
                "confidence": {
                    "score": values.mapping.score,
                    "grade": str(values.mapping.grade),
                },
                "fallbackLevel": 0,
            },
        ]
        result.extend(
            {
                "provider": f"{item.purpose}_FIXTURE/{item.version}",
                "origin": item.origin,
                "observedAt": None,
                "receivedAt": now.isoformat(),
                "ageSeconds": None,
                "confidence": self._confidence(values.bus.confidence_score),
                "fallbackLevel": 1,
            }
            for item in values.bus.model_provenance
        )
        return result


class IntegratedFixtureOptimizeRouteUseCase:
    """Explicit composition-time fixture fan-in.

    Successful replay scenarios use the production-shaped seven-pattern
    orchestration. Fault scenarios retain the focused deterministic fault
    harness so a provider or optional-enrichment failure cannot be confused
    with a caller-selected live mode.
    """

    def __init__(self, scenario: IntegratedFixtureScenario, clock: Clock) -> None:
        if scenario.fault is FixtureFault.NONE:
            from routing_api.fanin_integration import SevenPatternFixtureOptimizeRouteUseCase

            self._delegate = SevenPatternFixtureOptimizeRouteUseCase(scenario, clock)
        else:
            self._delegate = _LegacyIntegratedFixtureOptimizeRouteUseCase(
                scenario, clock
            )

    @property
    def trace(self):
        return getattr(self._delegate, "trace", None)

    def execute(self, command: OptimizeCommand, context: RequestContext) -> UseCaseResult:
        return self._delegate.execute(command, context)
