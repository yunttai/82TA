"""Fail-closed production composition for the private Routing application.

This module contains no environment-driven capability promotion.  Runtime
adapters still enforce provider-core evidence and schema gates; this factory
only wires typed ports when every required durable dependency was injected.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Iterable, Mapping

from bus_intelligence_core import (
    EtaPredictor,
    SeatRiskPredictor,
    VerifiedEtaPredictor,
    VerifiedEtaPredictorAttestation,
    VerifiedSeatRiskPredictor,
    VerifiedSeatRiskPredictorAttestation,
)
from provider_core.capabilities import CapabilityRegistry, foundation_capability_registry
from provider_core.canonical import CanonicalItinerary, CanonicalLeg
from provider_core.envelope import ProviderEnvelope, ProviderStatus
from provider_core.named import ProviderAdapterSuite, ProviderAdapterSuiteConfig
from provider_core.context_queries import GitsTrafficCorridorQuery, KmaWeatherQuery
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from transport_mapping import (
    CatalogQuery,
    DisabledGitsRoadLinkIdentityRepository,
    PostgisGbisCatalogRepository,
    PostgisGitsRoadLinkIdentityRepository,
    PostgresAcceptedHighMappingRepository,
    PostgresMappingReviewRepository,
    TransportMappingPipeline,
    candidate_fingerprint,
    enrich_selected_gits_road_link_target,
)

from routing_api.application import Clock, UnavailableOptimizeRouteUseCase
from routing_api.fanin_integration import (
    BusObservationQuery,
    CanonicalFanInOptimizeRouteUseCase,
    CanonicalTransitEvidence,
    FanInDependencies,
    BusContextProviderPort,
    TaxiDispatchEstimator,
)
from routing_api.persistence.ports import OptimizationResultRepository


_TRANSIT_ROUTE_OPERATIONS = (
    ("KAKAO_PUBLIC_TRANSIT", "search_current"),
    ("TMAP_TRANSIT", "search"),
    ("ODSAY", "search"),
)


class FallbackTransitSearch:
    """Kakao primary, then TMAP, then ODsay; EMPTY is not success."""

    def __init__(self, adapters: Iterable[object]) -> None:
        self._adapters = tuple(adapters)
        if len(self._adapters) != 3:
            raise ValueError("transit fallback requires Kakao, TMAP and ODsay")
        self._attempts: ContextVar[tuple[ProviderEnvelope, ...]] = ContextVar(
            f"transit_fallback_attempts_{id(self)}", default=()
        )

    @property
    def attempts(self) -> tuple[ProviderEnvelope, ...]:
        return self._attempts.get()

    def search(
        self, request: TransitSearchRequest, *, deadline: Deadline
    ) -> ProviderEnvelope[tuple[CanonicalItinerary, ...]]:
        self._attempts.set(())
        attempts: list[ProviderEnvelope] = []
        for adapter in self._adapters:
            envelope = adapter.search(request, deadline=deadline)
            attempts.append(envelope)
            if (
                envelope.status is ProviderStatus.OK
                and isinstance(envelope.payload, tuple)
                and any(isinstance(item, CanonicalItinerary) for item in envelope.payload)
            ):
                self._attempts.set(tuple(attempts))
                return envelope
        self._attempts.set(tuple(attempts))
        return attempts[-1]


class NamedProductionProviderPorts:
    """Typed façade over the bounded named provider suite."""

    def __init__(self, suite: ProviderAdapterSuite) -> None:
        self._suite = suite
        self._transit = FallbackTransitSearch(
            (suite.kakao_transit, suite.tmap, suite.odsay)
        )

    @property
    def transit_attempts(self) -> tuple[ProviderEnvelope, ...]:
        return self._transit.attempts

    @property
    def last_transit_envelopes(self) -> tuple[ProviderEnvelope, ...]:
        return self._transit.attempts

    @property
    def transit_call_cap(self) -> int:
        return 3

    @property
    def last_transit_attempt_count(self) -> int:
        return len(self._transit.attempts)

    def transit(self, request: TransitSearchRequest, *, deadline: Deadline):
        return self._transit.search(request, deadline=deadline)

    def walk(self, request: TransitSearchRequest, *, deadline: Deadline):
        return self._suite.kakao_walk.route(request, deadline=deadline)

    def taxi(self, request: TransitSearchRequest, *, deadline: Deadline):
        return self._suite.kakao_mobility.route(request, deadline=deadline)

    def arrivals(self, query: BusObservationQuery, *, deadline: Deadline):
        return self._suite.gbis.arrivals(
            query.boarding_station_id, deadline=deadline
        )

    def locations(self, query: BusObservationQuery, *, deadline: Deadline):
        return self._suite.gbis.locations(query.route_id, deadline=deadline)



class NamedProductionBusContextPort:
    """Expose only operation-scoped context adapters that passed every live gate."""

    def __init__(
        self,
        suite: ProviderAdapterSuite,
        enabled_operations: frozenset[str],
    ) -> None:
        allowed = frozenset({"weather_context", "traffic_context"})
        if len(enabled_operations) > 2 or not enabled_operations <= allowed:
            raise ValueError("production BUS context operation subset is invalid")
        self._suite = suite
        self._enabled_operations = enabled_operations

    @property
    def enabled_operations(self) -> frozenset[str]:
        return self._enabled_operations

    def weather(self, query: KmaWeatherQuery, *, deadline: Deadline):
        if "weather_context" not in self._enabled_operations:
            raise RuntimeError("KMA weather context operation is not executable")
        return self._suite.kma.context_query(query, deadline=deadline)

    def traffic(self, query: GitsTrafficCorridorQuery, *, deadline: Deadline):
        if "traffic_context" not in self._enabled_operations:
            raise RuntimeError("GITS traffic context operation is not executable")
        return self._suite.gits.context_query(query, deadline=deadline)


class PostgisMappingResolver:
    def __init__(self, database, *, gits_identity_repository=None) -> None:
        self._gits_identity_repository = (
            gits_identity_repository
            if gits_identity_repository is not None
            else DisabledGitsRoadLinkIdentityRepository()
        )
        self._catalog = PostgisGbisCatalogRepository(database)
        self._pipeline = TransportMappingPipeline(
            self._catalog,
            PostgresMappingReviewRepository(database),
            PostgresAcceptedHighMappingRepository(database),
        )

    def __call__(
        self, evidence: CanonicalTransitEvidence, evaluated_at: datetime
    ):
        result = self._pipeline.map_bus_leg(
            evidence.provider_code,
            evidence.leg,
            evaluated_at=evaluated_at,
            mapping_version="0.1.0-planned",
        )
        target = None
        if result.selected is not None:
            records = self._catalog.find_candidates(
                CatalogQuery(source=result.source, as_of=evaluated_at)
            )
            target = next(
                (
                    value
                    for value in records
                    if candidate_fingerprint(value)
                    == result.selected.candidate_fingerprint
                ),
                None,
            )
        if target is None:
            raise RuntimeError("accepted mapping target is unavailable")
        if result.selected_resolution is not None:
            target = enrich_selected_gits_road_link_target(
                target,
                result.selected_resolution,
                self._gits_identity_repository,
                as_of=evaluated_at,
            )
        return result, target


class ProductionOptimizeRouteUseCase(CanonicalFanInOptimizeRouteUseCase):
    """Generic production-shaped use case; construction requires durable ports."""

    def __init__(
        self,
        clock: Clock,
        dependencies: FanInDependencies,
        *,
        capability_registry: CapabilityRegistry,
        executable_operations: frozenset[tuple[str, str]],
        model_projection: tuple[Mapping[str, str], ...],
        deployment_environment: str,
    ) -> None:
        if dependencies.persistence is None:
            raise ValueError("production optimization persistence is required")
        if not any(
            (provider, operation) in executable_operations
            for provider, operation in _TRANSIT_ROUTE_OPERATIONS
        ):
            raise ValueError("required production provider runtime gate is disabled")
        expected_models = _verified_model_projection(
            dependencies.eta_predictor,
            dependencies.seat_predictor,
            deployment_environment,
        )
        if expected_models is None or tuple(map(dict, expected_models)) != tuple(
            map(dict, model_projection)
        ):
            raise ValueError("production model projection is not attested")
        self.capability_registry = capability_registry
        self.executable_operations = executable_operations
        # Store only the immutable projection freshly derived from exact Bus-core
        # attestations; never retain a caller-owned mutable mapping.
        self.model_projection = expected_models
        super().__init__(
            "production",
            clock,
            dependencies=dependencies,
        )


@dataclass(frozen=True, slots=True)
class ProductionCompositionDependencies:
    """Explicit deployment-owned inputs; never populated from ambient secrets.

    The factory consumes provider-core's operation-scoped configuration and
    Routing-owned durable adapters.  Capability evidence remains an independent
    gate and cannot be promoted by merely supplying credentials or transports.
    """

    provider_config: ProviderAdapterSuiteConfig | None = None
    mapping_database: object | None = None
    persistence: OptimizationResultRepository | None = None
    eta_predictor: EtaPredictor | None = None
    seat_predictor: SeatRiskPredictor | None = None
    taxi_dispatch: TaxiDispatchEstimator | None = None
    capability_registry: CapabilityRegistry | None = None
    deployment_environment: str | None = None


def _verified_model_projection(
    eta_predictor: object,
    seat_predictor: object,
    deployment_environment: str | None,
) -> tuple[Mapping[str, str], ...] | None:
    """Accept only exact Bus-core verified wrappers bound to one environment."""

    if deployment_environment not in {"staging", "prod"}:
        return None
    if type(eta_predictor) is not VerifiedEtaPredictor or type(
        seat_predictor
    ) is not VerifiedSeatRiskPredictor:
        return None
    eta = eta_predictor.attestation
    seat = seat_predictor.attestation
    if (
        type(eta) is not VerifiedEtaPredictorAttestation
        or type(seat) is not VerifiedSeatRiskPredictorAttestation
        or eta.family != "ETA"
        or seat.family != "SEAT_RISK"
        or eta.deployment_environment != deployment_environment
        or seat.deployment_environment != deployment_environment
        or eta.deployment_state != "ACTIVE"
        or seat.deployment_state != "ACTIVE"
        or eta.readiness != "ACTIVE"
        or seat.readiness != "ACTIVE"
        or eta.calibrated is not True
        or seat.calibrated is not True
        or eta.artifact_sha256 != eta.verified_artifact_sha256
        or seat.artifact_sha256 != seat.verified_artifact_sha256
        or eta.calibration_sha256 != eta.verified_calibration_sha256
        or seat.calibration_sha256 != seat.verified_calibration_sha256
        or not eta.full_feature_schema_version.strip()
        or not seat.full_feature_schema_version.strip()
        or not eta.model_version.strip()
        or not seat.model_version.strip()
    ):
        return None
    return (
        MappingProxyType(
            {"purpose": "BUS_ETA", "version": eta.model_version, "state": "ACTIVE"}
        ),
        MappingProxyType(
            {"purpose": "SEAT_RISK", "version": seat.model_version, "state": "ACTIVE"}
        ),
    )


def _capability_registry_signature(registry: CapabilityRegistry) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                item.provider,
                item.operation,
                item.documentation_state.value,
                item.key_verification_state.value,
                item.production_state.value,
                item.fixture_only,
            )
            for item in registry.all()
        )
    )


def coherent_production_capability_registry(
    dependencies: ProductionCompositionDependencies,
) -> CapabilityRegistry | None:
    """Return the suite's single registry, rejecting split-brain evidence."""

    if type(dependencies) is not ProductionCompositionDependencies:
        return None
    if dependencies.provider_config is None:
        return None
    configured = dependencies.provider_config.capabilities
    injected = dependencies.capability_registry
    if injected is not None and (
        _capability_registry_signature(injected)
        != _capability_registry_signature(configured)
    ):
        return None
    return configured


def _executable_provider_operations(
    suite: ProviderAdapterSuite,
    config: ProviderAdapterSuiteConfig,
) -> frozenset[tuple[str, str]]:
    """Evaluate the exact invoke gates, including immutable operation bindings."""

    adapters = (
        suite.kakao_transit,
        suite.kakao_walk,
        suite.kakao_mobility,
        suite.gbis,
        suite.kma,
        suite.gits,
        suite.tmap,
        suite.odsay,
    )
    executable: set[tuple[str, str]] = set()
    for adapter in adapters:
        for operation in adapter.operations:
            spec = adapter.endpoint_spec(operation)
            key = (spec.provider, operation)
            decision = adapter.runtime_evidence.assess(
                adapter.capabilities.get(*key),
                provider=spec.provider,
                operation=operation,
                response_schema_verified=spec.response_schema_verified,
                response_schema_version=spec.response_schema_version,
                now=adapter.clock(),
            )
            if (
                decision.executable
                and key in config.binding_map
                and spec.url is not None
                and spec.auth is not None
            ):
                executable.add(key)
    return frozenset(executable)


def build_injected_production_use_case(
    clock: Clock,
    dependencies: ProductionCompositionDependencies,
):
    """Assemble typed production ports only after every fail-closed gate passes."""

    if type(dependencies) is not ProductionCompositionDependencies:
        return UnavailableOptimizeRouteUseCase()
    registry = coherent_production_capability_registry(dependencies)
    if registry is None:
        return UnavailableOptimizeRouteUseCase()
    if not any(
        registry.enabled(provider, operation)
        for provider, operation in _TRANSIT_ROUTE_OPERATIONS
    ):
        return UnavailableOptimizeRouteUseCase()
    if any(
        value is None
        for value in (
            dependencies.provider_config,
            dependencies.mapping_database,
            dependencies.persistence,
            dependencies.eta_predictor,
            dependencies.seat_predictor,
        )
    ):
        return UnavailableOptimizeRouteUseCase()
    model_projection = _verified_model_projection(
        dependencies.eta_predictor,
        dependencies.seat_predictor,
        dependencies.deployment_environment,
    )
    if model_projection is None:
        return UnavailableOptimizeRouteUseCase()
    assert dependencies.provider_config is not None
    suite = ProviderAdapterSuite.from_config(dependencies.provider_config)
    executable_operations = _executable_provider_operations(
        suite, dependencies.provider_config
    )
    if not any(
        operation in executable_operations for operation in _TRANSIT_ROUTE_OPERATIONS
    ):
        return UnavailableOptimizeRouteUseCase()
    context_operations = frozenset(
        operation
        for provider, operation in executable_operations
        if (provider, operation)
        in {("KMA", "weather_context"), ("GITS", "traffic_context")}
    )
    context_port: BusContextProviderPort | None = (
        NamedProductionBusContextPort(suite, context_operations)
        if context_operations
        else None
    )
    gits_identity_repository = (
        PostgisGitsRoadLinkIdentityRepository(dependencies.mapping_database)
        if ("GITS", "traffic_context") in executable_operations
        else DisabledGitsRoadLinkIdentityRepository()
    )
    fan_in = FanInDependencies(
        providers=NamedProductionProviderPorts(suite),
        mapping=PostgisMappingResolver(
            dependencies.mapping_database,
            gits_identity_repository=gits_identity_repository,
        ),
        eta_predictor=dependencies.eta_predictor,
        seat_predictor=dependencies.seat_predictor,
        context=context_port,
        taxi_dispatch=dependencies.taxi_dispatch,
        persistence=dependencies.persistence,
        fixture_only=False,
    )
    return ProductionOptimizeRouteUseCase(
        clock,
        fan_in,
        capability_registry=registry,
        executable_operations=executable_operations,
        model_projection=model_projection,
        deployment_environment=dependencies.deployment_environment,
    )


def build_default_production_use_case(
    clock: Clock,
    *,
    provider_suite: ProviderAdapterSuite | None = None,
    mapping_database=None,
    persistence: OptimizationResultRepository | None = None,
    eta_predictor: EtaPredictor | None = None,
    seat_predictor: SeatRiskPredictor | None = None,
    taxi_dispatch: TaxiDispatchEstimator | None = None,
    capability_registry: CapabilityRegistry | None = None,
):
    """Compose production only from explicit dependencies and verified evidence.

    With the current canonical foundation registry this returns unavailable
    before constructing/calling a provider adapter, which is the deployed
    zero-network-call default.
    """

    registry = capability_registry or foundation_capability_registry()
    if not any(
        registry.enabled(provider, operation)
        for provider, operation in _TRANSIT_ROUTE_OPERATIONS
    ):
        return UnavailableOptimizeRouteUseCase()
    if any(
        value is None
        for value in (
            provider_suite,
            mapping_database,
            persistence,
            eta_predictor,
            seat_predictor,
        )
    ):
        return UnavailableOptimizeRouteUseCase()
    # A pre-built suite does not expose the operation-scoped immutable config
    # needed to prove binding/runtime/schema equivalence. Keep this legacy seam
    # unavailable rather than guessing effective live capabilities.
    return UnavailableOptimizeRouteUseCase()
