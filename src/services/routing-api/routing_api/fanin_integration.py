"""Production-shaped Routing fan-in over explicitly injected typed ports.

The generic use case consumes immutable canonical values.  Offline fixtures
are isolated behind fixture dependencies; production composition injects
verified provider, mapping, model, and persistence adapters.
"""

from __future__ import annotations

from contextvars import ContextVar
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from decimal import Decimal
from threading import BoundedSemaphore, Event, Lock
from time import monotonic
from typing import Callable, Mapping, Protocol, TypeVar
from uuid import UUID

from bus_intelligence_core import (
    BusIntelligenceEngine,
    BusIntelligenceRequest,
    BusIntelligenceResult,
    CalibratedSeatRiskPredictor,
    EtaPrediction,
    EtaPredictor,
    EtaFallbackChain,
    GuardedEtaPredictor,
    IdentityProbabilityCalibrator,
    RawSeatRiskScore,
    RuntimeModelSpec,
    SeatRiskPrediction,
    SeatRiskPredictor,
    VehicleObservation,
    EtaFeatureContext,
    SeatRiskFeatureContext,
    TrafficFeatureContext,
    WeatherFeatureContext,
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_SCHEMA_VERSION,
)
from provider_core.adapters import FixtureScenario, FixtureTransitAdapter
from provider_core.capabilities import foundation_capability_registry
from provider_core.canonical import CanonicalItinerary, CanonicalLeg, Coordinate
from provider_core.context import (
    BusArrivalObservation,
    BusLocationObservation,
    TrafficLinkContext,
    WeatherContext,
)
from provider_core.context_queries import GitsTrafficCorridorQuery, KmaWeatherQuery
from provider_core.envelope import ProviderEnvelope, ProviderStatus
from provider_core.named import (
    ProviderAdapterSuite,
    ProviderFixtureScenario,
)
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from routing_domain import (
    AccessHub,
    BoundedStrategyGenerator,
    BusWaitContribution,
    CandidateCaps,
    CandidateSeed,
    CanonicalRoutingGraph,
    CanonicalTransitTopology,
    EgressHub,
    EnrichmentKind,
    ExactificationPlan,
    ExactificationStep,
    ExactQuoteIdentity,
    GraphSearchCaps,
    GraphSearchUncertifiedError,
    LegCost,
    LegSpec,
    MoneyRange,
    OptimalityUncertifiedError,
    QuoteReadiness,
    RouteConstraints,
    RouteOptimizer,
    StaticLegEvaluator,
    StrategyCandidate,
    StrategyGenerationBatch,
    StrategyGenerationInput,
    StrategyRejection,
    TaxiBridge,
    TaxiQuote,
    TimeEstimate,
    TransitBaseline,
    TransitLegInput,
    TransferRequirement,
    UpstreamHub,
    WalkQuote,
)
from transport_mapping import (
    InMemoryGbisCatalogRepository,
    InMemoryMappingReviewRepository,
    MappingPipelineResult,
    GitsRoadLinkIdentity,
    TransportMappingPipeline,
)

from routing_api.application import (
    Clock,
    OptimizeCommand,
    RequestContext,
    RoutingDeadlineExceeded,
    RoutingCapacityExceeded,
    RoutingUnavailableError,
    UseCaseResult,
)
from routing_api.fixture_scenarios import IntegratedFixtureScenario
from routing_api.persistence.ports import OptimizationResultRepository
from routing_api.persistence.records import (
    OptimizationBusLegEnrichmentRecord,
    OptimizationCandidateRecord,
    OptimizationLegRecord,
    OptimizationResultRecord,
    OptimizationRunRecord,
    OptimizationTransferEvaluationRecord,
)
from routing_api.fixture_integration import (
    MAPPING_VERSION,
    _REPLAY_REQUEST_BUNDLES,
    _aware_timestamp,
    _coordinates_equal,
    _mapping_coordinates_equal,
    _mapping_input,
    _mapping_target,
    _provider_scenario,
)


_MODEL_INFERENCE_TARGET_SECONDS = 0.300
_MODEL_INFERENCE_HARD_SECONDS = 0.400
_MODEL_INFERENCE_MAX_INFLIGHT = 8
_MODEL_INFERENCE_EXECUTOR = ThreadPoolExecutor(
    max_workers=_MODEL_INFERENCE_MAX_INFLIGHT,
    thread_name_prefix="routing-model-inference",
)
_MODEL_INFERENCE_ADMISSION = BoundedSemaphore(_MODEL_INFERENCE_MAX_INFLIGHT)
_InferenceValue = TypeVar("_InferenceValue")


@dataclass(frozen=True, slots=True)
class ModelInferenceTrace:
    target_ms: int
    hard_cap_ms: int
    elapsed_ms: int
    started: int
    completed: int
    failures: int
    timeouts: int
    cancellations: int
    admission_rejections: int
    target_exceeded: bool
    hard_exhausted: bool


class _RequestModelInferenceBudget:
    """One fail-soft wall-clock model budget shared by the whole optimize request.

    The process semaphore is acquired before submission, so the fixed executor can
    never accumulate an unbounded queue.  A timed-out non-cooperative call retains
    its permit through the future's completion callback even though the caller stops
    waiting at the request-local hard cap.
    """

    def __init__(
        self,
        cancellation: Event,
        *,
        executor: ThreadPoolExecutor | None = None,
        admission: BoundedSemaphore | None = None,
        timer: Callable[[], float] = monotonic,
        target_seconds: float = _MODEL_INFERENCE_TARGET_SECONDS,
        hard_seconds: float = _MODEL_INFERENCE_HARD_SECONDS,
    ) -> None:
        if target_seconds <= 0 or hard_seconds <= 0 or target_seconds > hard_seconds:
            raise ValueError("model inference target/hard budget is invalid")
        self._cancellation = cancellation
        self._executor = executor or _MODEL_INFERENCE_EXECUTOR
        self._admission = admission or _MODEL_INFERENCE_ADMISSION
        self._timer = timer
        self._target_seconds = target_seconds
        self._hard_seconds = hard_seconds
        self._lock = Lock()
        self._started_at: float | None = None
        self._hard_deadline: float | None = None
        self._last_observed_at: float | None = None
        self._closed = False
        self._hard_exhausted = False
        self._started = 0
        self._completed = 0
        self._failures = 0
        self._timeouts = 0
        self._cancellations = 0
        self._admission_rejections = 0

    def run(self, work: Callable[[], _InferenceValue]) -> _InferenceValue | None:
        with self._lock:
            now = self._timer()
            self._last_observed_at = now
            if self._cancellation.is_set() or self._closed:
                self._closed = True
                return None
            if self._started_at is None:
                self._started_at = now
                self._hard_deadline = now + self._hard_seconds
            assert self._hard_deadline is not None
            remaining = self._hard_deadline - now
            if remaining <= 0:
                self._closed = True
                self._hard_exhausted = True
                return None
            if not self._admission.acquire(blocking=False):
                self._admission_rejections += 1
                self._closed = True
                return None
            self._started += 1

        try:
            future: Future[_InferenceValue] = self._executor.submit(work)
        except BaseException:
            self._admission.release()
            with self._lock:
                self._failures += 1
                self._closed = True
                self._last_observed_at = self._timer()
            return None
        future.add_done_callback(lambda _: self._admission.release())
        while not future.done():
            if self._cancellation.is_set():
                future.cancel()
                with self._lock:
                    self._cancellations += 1
                    self._closed = True
                    self._last_observed_at = self._timer()
                return None
            with self._lock:
                assert self._hard_deadline is not None
                remaining = self._hard_deadline - self._timer()
            if remaining <= 0:
                future.cancel()
                with self._lock:
                    self._timeouts += 1
                    self._closed = True
                    self._hard_exhausted = True
                    self._last_observed_at = self._timer()
                return None
            wait((future,), timeout=min(0.01, remaining))
        try:
            result = future.result()
        except BaseException:
            with self._lock:
                observed = self._timer()
                self._last_observed_at = observed
                assert self._hard_deadline is not None
                if self._cancellation.is_set():
                    self._cancellations += 1
                    self._closed = True
                elif observed >= self._hard_deadline:
                    self._timeouts += 1
                    self._closed = True
                    self._hard_exhausted = True
                else:
                    # A single family/runtime failure must not consume the other
                    # family's remaining absolute request budget.
                    self._failures += 1
            return None
        with self._lock:
            observed = self._timer()
            self._last_observed_at = observed
            assert self._hard_deadline is not None
            if self._cancellation.is_set():
                self._cancellations += 1
                self._closed = True
                return None
            if observed >= self._hard_deadline:
                # A Future may become done just after the wait-loop's final budget
                # check. Never accept a result merely because scheduling jitter let
                # the loop exit before observing the hard boundary.
                self._timeouts += 1
                self._closed = True
                self._hard_exhausted = True
                return None
            self._completed += 1
        return result

    @property
    def trace(self) -> ModelInferenceTrace:
        with self._lock:
            if self._started_at is None:
                elapsed = 0.0
            else:
                observed = self._last_observed_at or self._timer()
                elapsed = min(self._hard_seconds, max(0.0, observed - self._started_at))
            return ModelInferenceTrace(
                target_ms=round(self._target_seconds * 1000),
                hard_cap_ms=round(self._hard_seconds * 1000),
                elapsed_ms=round(elapsed * 1000),
                started=self._started,
                completed=self._completed,
                failures=self._failures,
                timeouts=self._timeouts,
                cancellations=self._cancellations,
                admission_rejections=self._admission_rejections,
                target_exceeded=elapsed > self._target_seconds,
                hard_exhausted=self._hard_exhausted,
            )


class _BudgetedEtaPredictor:
    def __init__(
        self, predictor: EtaPredictor, budget: _RequestModelInferenceBudget
    ) -> None:
        self._predictor = predictor
        self._budget = budget

    def predict(self, value):
        return self._budget.run(lambda: self._predictor.predict(value))


class _BudgetedSeatRiskPredictor:
    def __init__(
        self, predictor: SeatRiskPredictor, budget: _RequestModelInferenceBudget
    ) -> None:
        self._predictor = predictor
        self._budget = budget

    def predict(self, value):
        return self._budget.run(lambda: self._predictor.predict(value))


@dataclass(frozen=True, slots=True)
class FanInTrace:
    coarse_patterns: tuple[str, ...]
    exact_patterns: tuple[str, ...]
    exact_plan: tuple[tuple[str, str], ...]
    provider_call_count: int
    rejected_reasons: tuple[str, ...]
    persistence_status: str
    model_inference: ModelInferenceTrace
    returned_itinerary_count: int
    admitted_itinerary_count: int
    deduplicated_itinerary_count: int
    finite_payload_complete: bool
    network_global_complete: bool
    graph_expansion_count: int
    graph_seed_count: int
    graph_recombined_count: int


@dataclass(slots=True)
class _ProviderOperationBudget:
    """Counts expanded operations before any adapter invocation."""

    limit: int
    consumed: int = 0
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("provider operation cap must be positive")
        self._lock = Lock()

    def reserve(self, units: int) -> None:
        if units < 0:
            raise ValueError("provider operation units cannot be negative")
        with self._lock:
            if self.consumed + units > self.limit:
                raise RoutingUnavailableError("provider operation cap exceeded")
            self.consumed += units

    def try_reserve(self, units: int) -> bool:
        if units < 0:
            raise ValueError("provider operation units cannot be negative")
        with self._lock:
            if self.consumed + units > self.limit:
                return False
            self.consumed += units
            return True

    def release(self, units: int) -> None:
        with self._lock:
            if units < 0 or units > self.consumed:
                raise ValueError("provider operation release is invalid")
            self.consumed -= units


def _expanded_provider_operation_units(request) -> int:
    """Translate one logical exact request into conservative provider units."""

    if request.kind is EnrichmentKind.BUS_INTELLIGENCE:
        # GBIS arrival and location are distinct quota/cost operations.
        return request.call_units * 2
    if request.kind in {EnrichmentKind.WALK, EnrichmentKind.TAXI}:
        return request.call_units
    # Mapping is a bounded Routing DB/catalog lookup. TRANSIT was already
    # fetched by the required baseline operation in this composition.
    return 0


class InMemoryOptimizationPersistence:
    """Narrow test adapter; it stores no request body, identity, or raw payload."""

    def __init__(self) -> None:
        self.values: list[OptimizationResultRecord] = []

    def persist(self, value: OptimizationResultRecord) -> None:
        self.values.append(value)


class _NoNetworkTransport:
    def send(self, request):
        raise AssertionError("offline fixture composition attempted network I/O")


class FanInProviderPorts(Protocol):
    """Typed provider boundary consumed by orchestration.

    Implementations return only normalized envelopes.  The use case never
    receives provider JSON, credentials, URLs, or an escape hatch to a raw
    transport.
    """

    def transit(
        self, request: TransitSearchRequest, *, deadline: Deadline
    ) -> ProviderEnvelope[tuple[CanonicalItinerary, ...]]: ...

    @property
    def transit_call_cap(self) -> int: ...

    @property
    def last_transit_attempt_count(self) -> int: ...

    @property
    def last_transit_envelopes(self) -> tuple[ProviderEnvelope, ...]: ...

    def walk(
        self, request: TransitSearchRequest, *, deadline: Deadline
    ) -> ProviderEnvelope[tuple[CanonicalItinerary, ...]]: ...

    def taxi(
        self, request: TransitSearchRequest, *, deadline: Deadline
    ) -> ProviderEnvelope[tuple[CanonicalItinerary, ...]]: ...

    def arrivals(
        self, query: "BusObservationQuery", *, deadline: Deadline
    ) -> ProviderEnvelope[tuple[BusArrivalObservation, ...]]: ...

    def locations(
        self, query: "BusObservationQuery", *, deadline: Deadline
    ) -> ProviderEnvelope[tuple[BusLocationObservation, ...]]: ...


_BUS_CONTEXT_OPERATIONS = frozenset({"weather_context", "traffic_context"})


class BusContextProviderPort(Protocol):
    """Optional, explicitly gated KMA/GITS boundary for one mapped BUS leg."""

    @property
    def enabled_operations(self) -> frozenset[str]: ...

    def weather(
        self, query: KmaWeatherQuery, *, deadline: Deadline
    ) -> ProviderEnvelope[tuple[WeatherContext, ...]]: ...

    def traffic(
        self, query: GitsTrafficCorridorQuery, *, deadline: Deadline
    ) -> ProviderEnvelope[tuple[TrafficLinkContext, ...]]: ...


@dataclass(frozen=True, slots=True)
class BusObservationQuery:
    route_id: str
    boarding_station_id: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if not self.route_id.strip() or not self.boarding_station_id.strip():
            raise ValueError("GBIS query route/station must be nonblank")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("GBIS query time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CanonicalTransitEvidence:
    provider_code: str
    envelope_fingerprint: str
    itinerary_id: str
    leg: CanonicalLeg

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.provider_code,
                self.envelope_fingerprint,
                self.itinerary_id,
            )
        ):
            raise ValueError("transit evidence identifiers must be nonblank")


class MappingResolver(Protocol):
    def __call__(
        self, evidence: CanonicalTransitEvidence, evaluated_at: datetime
    ) -> tuple[MappingPipelineResult, object]: ...


@dataclass(frozen=True, slots=True)
class TaxiDispatchEstimate:
    wait: TimeEstimate
    source: str
    version: str
    origin: str = "HISTORICAL_PROXY"

    def __post_init__(self) -> None:
        if (
            not self.source.strip()
            or not self.version.strip()
            or self.origin not in {"PROVIDER_ESTIMATE", "MODEL_PREDICTED", "HISTORICAL_PROXY"}
        ):
            raise ValueError("taxi dispatch provenance must be nonblank")


class TaxiDispatchEstimator(Protocol):
    def estimate(
        self, request: TransitSearchRequest, *, evaluated_at: datetime
    ) -> TaxiDispatchEstimate | None: ...


@dataclass(frozen=True, slots=True)
class BusWaitEstimate:
    """Entry-time Bus wait supplied by an injected live/model/history source."""

    wait: TimeEstimate
    source: str
    version: str
    origin: str = "HISTORICAL_PROXY"

    def __post_init__(self) -> None:
        if (
            not self.source.strip()
            or not self.version.strip()
            or self.origin not in {"PROVIDER_ESTIMATE", "MODEL_PREDICTED", "HISTORICAL_PROXY"}
        ):
            raise ValueError("bus wait provenance must be nonblank")


class BusWaitEstimator(Protocol):
    def estimate(
        self,
        leg: CanonicalLeg,
        *,
        arrival_at: datetime,
        evaluated_at: datetime,
    ) -> BusWaitEstimate | None: ...


@dataclass(frozen=True, slots=True)
class FanInDependencies:
    providers: FanInProviderPorts
    mapping: MappingResolver
    eta_predictor: EtaPredictor
    seat_predictor: SeatRiskPredictor
    context: BusContextProviderPort | None = None
    taxi_dispatch: TaxiDispatchEstimator | None = None
    bus_wait: BusWaitEstimator | None = None
    bus_intelligence_enabled: bool = True
    persistence: OptimizationResultRepository | None = None
    fixture_only: bool = False

    def __post_init__(self) -> None:
        if self.context is None:
            return
        operations = self.context.enabled_operations
        if (
            not isinstance(operations, frozenset)
            or len(operations) > 2
            or not operations <= _BUS_CONTEXT_OPERATIONS
        ):
            raise ValueError("BUS context operations must be an explicit bounded subset")


class _FixtureMappingResolver:
    def __init__(self, scenario: IntegratedFixtureScenario) -> None:
        self._fault = scenario.fault

    def __call__(self, evidence: CanonicalTransitEvidence, evaluated_at: datetime):
        return _mapping_pipeline(evidence.leg, evaluated_at, self._fault)


class _FixtureTaxiDispatchEstimator:
    def estimate(self, request, *, evaluated_at):
        del request, evaluated_at
        return TaxiDispatchEstimate(
            TimeEstimate(90, 150),
            "FIXTURE_POLICY",
            "taxi-dispatch-fixture-0.1.0",
        )


class _FixtureBusWaitEstimator:
    """Deterministic non-zero history proxy for closed fixture scenarios."""

    def estimate(self, leg, *, arrival_at, evaluated_at):
        del evaluated_at
        route_label = (
            leg.transit.route_label
            if leg.transit is not None and leg.transit.route_label is not None
            else "FIXTURE_BUS"
        )
        headway = 600
        phase = int.from_bytes(
            sha256(f"{route_label}|{leg.from_stop.name}".encode("utf-8")).digest()[:4],
            "big",
        ) % headway
        second = arrival_at.hour * 3600 + arrival_at.minute * 60 + arrival_at.second
        wait = (phase - second) % headway
        if wait < 45:
            wait += headway
        return BusWaitEstimate(
            TimeEstimate(wait, wait + 180),
            "FIXTURE_BUS_ARRIVAL_HISTORY",
            "fixture-bus-wait-1.0.0",
            origin="HISTORICAL_PROXY",
        )


class _FixtureProviderPorts:
    """Closed adapter set: provider-core fixtures only, never live transport."""

    def __init__(self, scenario: IntegratedFixtureScenario) -> None:
        self._scenario = scenario
        self._suite = ProviderAdapterSuite(_NoNetworkTransport())
        self._transit_attempts: ContextVar[tuple[ProviderEnvelope, ...]] = ContextVar(
            f"fixture_transit_attempts_{id(self)}", default=()
        )

    @property
    def transit_call_cap(self) -> int:
        return 1

    @property
    def last_transit_attempt_count(self) -> int:
        return len(self._transit_attempts.get())

    @property
    def last_transit_envelopes(self) -> tuple[ProviderEnvelope, ...]:
        return self._transit_attempts.get()

    def transit(self, request: TransitSearchRequest, *, deadline: Deadline):
        self._transit_attempts.set(())
        result = FixtureTransitAdapter(_provider_scenario(self._scenario)).search(
            request, deadline=deadline
        )
        self._transit_attempts.set((result,))
        return result

    def walk(self, request: TransitSearchRequest, *, deadline: Deadline):
        del request, deadline
        return self._suite.kakao_walk.fixture("route", ProviderFixtureScenario.SUCCESS)

    def taxi(self, request: TransitSearchRequest, *, deadline: Deadline):
        del request, deadline
        return self._suite.kakao_mobility.fixture(
            "route_current", ProviderFixtureScenario.SUCCESS
        )

    def arrivals(self, query: BusObservationQuery, *, deadline: Deadline):
        del query, deadline
        scenario = (
            ProviderFixtureScenario.EMPTY
            if self._scenario.fault.value == "ETA_UNAVAILABLE"
            else ProviderFixtureScenario.SUCCESS
        )
        return self._suite.gbis.fixture("arrivals", scenario)

    def locations(self, query: BusObservationQuery, *, deadline: Deadline):
        del query, deadline
        return self._suite.gbis.fixture("locations", ProviderFixtureScenario.SUCCESS)


class _FixtureEtaPredictor:
    def __init__(self, available: bool) -> None:
        self.spec = RuntimeModelSpec(
            purpose="BUS_ETA",
            version="eta-fixture-0.1.0",
            readiness="FIXTURE_ONLY",
            feature_schema_version="eta-schema-v2",
            allow_fixture_only=True,
        )
        self.available = available

    def predict(self, value) -> EtaPrediction | None:
        if not self.available or not self.spec.can_serve("eta-schema-v2"):
            return None
        seconds = 120 if value.vehicle_ref.endswith("1") else 600
        return EtaPrediction(
            p50_arrival_at=value.prediction_at + timedelta(seconds=seconds),
            p90_arrival_at=value.prediction_at + timedelta(seconds=seconds + 120),
            source="POSITION_MODEL",
            model_version=self.spec.version,
            confidence=0.82,
            model_readiness=self.spec.readiness,
        )


class _FixtureSeatPredictor:
    def __init__(self, scenario: IntegratedFixtureScenario, available: bool) -> None:
        self.spec = RuntimeModelSpec(
            purpose="SEAT_RISK",
            version="seat-fixture-0.1.0",
            readiness="FIXTURE_ONLY",
            feature_schema_version="seat-schema-v2",
            calibrated=True,
            allow_fixture_only=True,
        )
        self.scenario = scenario
        self.available = available

    def predict(self, value) -> SeatRiskPrediction | None:
        if not self.available or not self.spec.can_serve("seat-schema-v2"):
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
            model_version=self.spec.version,
            confidence=0.8,
            model_readiness=self.spec.readiness,
        )


class _NullPredictor:
    def predict(self, value):
        del value
        return None


class _FixtureSeatScorer:
    def __init__(self, scenario: IntegratedFixtureScenario) -> None:
        self._scenario = scenario

    def score(self, value) -> RawSeatRiskScore | None:
        if self._scenario.fault.value == "SEAT_UNAVAILABLE":
            return None
        # The fixture scorer is an injected model boundary.  Provider remaining
        # seats remain an observed feature (or None); they are never interpreted
        # as a future target-stop label.
        probability = self._scenario.first_no_seat_probability
        if value.remain_seat_observed is not None:
            probability = min(1.0, max(0.0, 1.0 - value.remain_seat_observed / 10.0))
        return RawSeatRiskScore(
            no_seat_score=probability,
            low_seat2_score=min(1.0, probability + 0.15),
            low_seat5_score=min(1.0, probability + 0.30),
            confidence=0.8,
        )


def fixture_fan_in_dependencies(
    scenario: IntegratedFixtureScenario,
) -> FanInDependencies:
    eta_spec = RuntimeModelSpec(
        purpose="BUS_ETA",
        version="eta-fixture-0.1.0",
        readiness="FIXTURE_ONLY",
        feature_schema_version="eta-schema-v2",
        allow_fixture_only=True,
    )
    eta = EtaFallbackChain(
        GuardedEtaPredictor(
            _FixtureEtaPredictor(scenario.fault.value != "ETA_UNAVAILABLE"),
            eta_spec,
            serving_feature_schema_version="eta-schema-v2",
            required_source="POSITION_MODEL",
            max_input_age_seconds=180,
        ),
        _NullPredictor(),
    )
    seat_spec = RuntimeModelSpec(
        purpose="SEAT_RISK",
        version="seat-fixture-0.1.0",
        readiness="FIXTURE_ONLY",
        feature_schema_version="seat-schema-v2",
        calibrated=True,
        allow_fixture_only=True,
    )
    calibrator = IdentityProbabilityCalibrator()
    seat = CalibratedSeatRiskPredictor(
        _FixtureSeatScorer(scenario),
        seat_spec,
        serving_feature_schema_version="seat-schema-v2",
        no_seat_calibrator=calibrator,
        low_seat2_calibrator=calibrator,
        low_seat5_calibrator=calibrator,
    )
    return FanInDependencies(
        providers=_FixtureProviderPorts(scenario),
        mapping=_FixtureMappingResolver(scenario),
        eta_predictor=eta,
        seat_predictor=seat,
        taxi_dispatch=_FixtureTaxiDispatchEstimator(),
        bus_wait=_FixtureBusWaitEstimator(),
        fixture_only=True,
    )


@dataclass(frozen=True, slots=True)
class _LegProjection:
    name_from: str
    name_to: str
    from_coordinate: tuple[float, float]
    to_coordinate: tuple[float, float]
    provider_from_id: str | None
    provider_to_id: str | None
    transit: Mapping[str, object] | None
    geometry: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class _Composition:
    provider_envelopes: tuple[ProviderEnvelope, ...]
    baseline_envelope: ProviderEnvelope
    provider_leg: CanonicalLeg
    movement_envelopes: tuple[
        tuple[tuple[str, str, str], ProviderEnvelope], ...
    ]
    taxi_dispatches: tuple[
        tuple[tuple[str, str, str], TaxiDispatchEstimate], ...
    ]
    bus_snapshots: tuple["_BusLegSnapshot", ...]
    bus_evaluations: tuple["_BusLegEvaluation", ...]
    exact_input: StrategyGenerationInput
    projection: Mapping[tuple[str, str, str], _LegProjection]
    exact_plan: tuple[tuple[str, str], ...]
    provider_call_count: int
    coarse_patterns: tuple[str, ...]
    rejected_reasons: tuple[str, ...]
    leg_envelopes: tuple[tuple[str, ProviderEnvelope], ...] = ()
    leg_dispatches: tuple[tuple[str, TaxiDispatchEstimate], ...] = ()
    leg_projections: tuple[tuple[str, _LegProjection], ...] = ()


@dataclass(frozen=True, slots=True)
class _BusLegSnapshot:
    topology_ref: str
    evidence: CanonicalTransitEvidence
    mapping: MappingPipelineResult | None
    target: object | None
    query: BusObservationQuery | None
    arrivals: ProviderEnvelope | None
    locations: ProviderEnvelope | None
    service_type: str | None
    leg_id: str | None = None
    weather: ProviderEnvelope | None = None
    traffic: ProviderEnvelope | None = None
    eta_feature_context: EtaFeatureContext | None = None
    seat_risk_feature_context: SeatRiskFeatureContext | None = None
    context_required_operations: frozenset[str] = frozenset()
    context_complete: bool = True
    fallback_wait: BusWaitEstimate | None = None

    @property
    def mapping_allows_intelligence(self) -> bool:
        return (
            self.mapping is not None
            and self.mapping.allows_bus_intelligence
            and self.mapping.selected is not None
            and self.target is not None
        )


def _fixture_envelope_at(
    envelope: ProviderEnvelope | None,
    evaluated_at: datetime,
) -> ProviderEnvelope | None:
    """Bind sanitized fixture transport metadata to the replay request clock.

    Fixture payloads contain scenario-local timestamps for their synthetic
    observations. Those timestamps are not the time at which this replay
    fetched or received the fixture, and projecting them as such can place
    provenance after the response that contains it. Keep the payload intact,
    but make the transport envelope causal with the request evaluation clock.
    """

    if envelope is None:
        return None
    observed_at = evaluated_at if envelope.observed_at is not None else None
    return replace(
        envelope,
        fetched_at=evaluated_at,
        received_at=evaluated_at,
        observed_at=observed_at,
    )


def _align_fixture_provenance_clock(
    composition: _Composition,
    evaluated_at: datetime,
) -> _Composition:
    """Return one fixture composition whose projected envelopes share one clock."""

    aligned_by_identity: dict[int, ProviderEnvelope] = {}

    def aligned(envelope: ProviderEnvelope) -> ProviderEnvelope:
        identity = id(envelope)
        existing = aligned_by_identity.get(identity)
        if existing is not None:
            return existing
        value = _fixture_envelope_at(envelope, evaluated_at)
        assert value is not None
        aligned_by_identity[identity] = value
        return value

    return replace(
        composition,
        provider_envelopes=tuple(aligned(item) for item in composition.provider_envelopes),
        baseline_envelope=aligned(composition.baseline_envelope),
        movement_envelopes=tuple(
            (key, aligned(envelope))
            for key, envelope in composition.movement_envelopes
        ),
        bus_snapshots=tuple(
            replace(
                snapshot,
                arrivals=_fixture_envelope_at(snapshot.arrivals, evaluated_at),
                locations=_fixture_envelope_at(snapshot.locations, evaluated_at),
                weather=_fixture_envelope_at(snapshot.weather, evaluated_at),
                traffic=_fixture_envelope_at(snapshot.traffic, evaluated_at),
            )
            for snapshot in composition.bus_snapshots
        ),
        leg_envelopes=tuple(
            (key, aligned(envelope))
            for key, envelope in composition.leg_envelopes
        ),
    )


@dataclass(frozen=True, slots=True)
class _BusOptionalGroup:
    arrivals: ProviderEnvelope | None = None
    locations: ProviderEnvelope | None = None
    weather: ProviderEnvelope | None = None
    traffic: ProviderEnvelope | None = None
    eta_feature_context: EtaFeatureContext | None = None
    seat_risk_feature_context: SeatRiskFeatureContext | None = None
    required_operations: frozenset[str] = frozenset()
    context_complete: bool = True
    started_units: int = 0

    @property
    def envelopes(self) -> tuple[ProviderEnvelope, ...]:
        return tuple(
            item
            for item in (self.arrivals, self.locations, self.weather, self.traffic)
            if item is not None
        )


@dataclass(frozen=True, slots=True)
class _BusLegEvaluation:
    leg_id: str
    topology_ref: str
    user_arrival_at: datetime
    result: BusIntelligenceResult


@dataclass(frozen=True, slots=True)
class _ExactStepOutcome:
    step: ExactificationStep
    identity: ExactQuoteIdentity
    provider_departure_at: datetime
    end_at_p50: datetime | None
    canonical_leg: CanonicalLeg | None
    envelope: ProviderEnvelope | None
    attempts: tuple[ProviderEnvelope, ...]
    dispatch: TaxiDispatchEstimate | None
    snapshot: _BusLegSnapshot | None
    reserved_units: int
    actual_units: int
    reason: str | None = None
    source_itinerary_id: str | None = None

    @property
    def resolved(self) -> bool:
        return (
            self.reason is None
            and self.canonical_leg is not None
            and self.envelope is not None
            and self.end_at_p50 is not None
        )


def _service_type(route_type: str | None) -> str | None:
    """Map only explicit canonical route classifications; never infer SEATED."""

    if route_type is None:
        return None
    normalized = "".join(route_type.upper().split())
    if normalized in {
        "GENERAL",
        "LOCAL",
        "CITY",
        "GENERAL_BUS",
        "GENERALBUS",
        "일반",
        "시내일반",
        "마을버스",
    }:
        return "GENERAL"
    if normalized in {
        "SEATED",
        "EXPRESS_SEATED",
        "DIRECT_SEATED",
        "SEAT_BUS",
        "SEATBUS",
        "좌석",
        "직행좌석",
        "광역급행",
        "M버스",
    }:
        return "SEATED"
    return None


def _unique_provider_envelopes(composition: _Composition) -> tuple[ProviderEnvelope, ...]:
    """Preserve actual call order, adding the selected baseline only if absent."""

    values = list(composition.provider_envelopes)
    if not any(item is composition.baseline_envelope for item in values):
        values.insert(0, composition.baseline_envelope)
    return tuple(values)


def _provider_envelope_projection_key(envelope: ProviderEnvelope) -> tuple[object, ...]:
    """Stable logical order for canonical arrays fed by concurrent fan-in."""

    return (
        envelope.provider,
        envelope.operation,
        envelope.fingerprint,
        envelope.status.value,
        envelope.message_code or "",
        envelope.received_at,
        envelope.latency_ms,
        envelope.cache_hit,
    )


def _coordinates_between(
    origin: tuple[float, float], destination: tuple[float, float], fraction: float
) -> tuple[float, float]:
    return (
        origin[0] + (destination[0] - origin[0]) * fraction,
        origin[1] + (destination[1] - origin[1]) * fraction,
    )


def _topology(route: str, start: str, end: str, board: int, alight: int) -> CanonicalTransitTopology:
    return CanonicalTransitTopology(route, "OUTBOUND", start, end, board, alight)


def _transit(
    leg_id: str,
    mode: str,
    route: str,
    start: str,
    end: str,
    board: int,
    alight: int,
    seconds: int,
    *,
    mapping_ready: bool = True,
    bus_requested: bool = False,
    bus_wait: BusWaitContribution | None = None,
    scheduled: datetime | None = None,
    provider_leg: CanonicalLeg | None = None,
    readiness: QuoteReadiness = QuoteReadiness.EXACT,
) -> TransitLegInput:
    duration = (
        TimeEstimate(provider_leg.duration.p50_seconds, provider_leg.duration.p90_seconds)
        if provider_leg is not None
        else TimeEstimate(seconds, seconds + 180)
    )
    fare = (
        MoneyRange(
            provider_leg.fare.expected_krw,
            provider_leg.fare.lower_krw,
            provider_leg.fare.upper_krw,
        )
        if provider_leg is not None
        else MoneyRange(1_500, 1_500, 1_500)
    )
    return TransitLegInput(
        leg_id=leg_id,
        mode=mode,
        topology=_topology(route, start, end, board, alight),
        evaluator_key=f"cost:{leg_id}",
        duration=duration,
        fare=fare,
        lower_bound_seconds=(
            provider_leg.duration.lower_seconds or 0
            if provider_leg is not None
            else max(0, seconds - 120)
        ),
        reliability_score=0.86,
        scheduled_departure_at=scheduled,
        mapping_ready=mapping_ready,
        bus_intelligence_requested=bus_requested,
        bus_wait=bus_wait,
        readiness=readiness,
    )


def _taxi(
    quote_id: str,
    start: str,
    end: str,
    upper: int,
    *,
    readiness: QuoteReadiness,
    drive_seconds: int = 360,
    provider_leg: CanonicalLeg | None = None,
) -> TaxiQuote:
    dispatch = TimeEstimate(0, 0) if provider_leg is not None else TimeEstimate(90, 150)
    drive = (
        TimeEstimate(provider_leg.duration.p50_seconds, provider_leg.duration.p90_seconds)
        if provider_leg is not None
        else TimeEstimate(drive_seconds, drive_seconds + 180)
    )
    fare = (
        MoneyRange(
            provider_leg.fare.expected_krw,
            provider_leg.fare.lower_krw,
            provider_leg.fare.upper_krw,
        )
        if provider_leg is not None
        else MoneyRange(upper * 9 // 10, upper * 8 // 10, upper)
    )
    return TaxiQuote(
        quote_id=quote_id,
        from_ref=start,
        to_ref=end,
        evaluator_key=f"cost:{quote_id}",
        dispatch_wait=dispatch,
        drive_duration=drive,
        fare=fare,
        distance_meters=(provider_leg.distance_meters if provider_leg is not None else max(500, drive_seconds * 8)),
        lower_bound_dispatch_seconds=0 if provider_leg is not None else 60,
        lower_bound_drive_seconds=(
            provider_leg.duration.lower_seconds or 0
            if provider_leg is not None
            else max(0, drive_seconds - 120)
        ),
        readiness=readiness,
        reliability_score=0.82,
        topology_ref=f"fixture-taxi:{quote_id}",
    )


def _walk(readiness: QuoteReadiness, provider_leg: CanonicalLeg | None = None) -> WalkQuote:
    return WalkQuote(
        quote_id="walk-egress",
        from_ref="hub-b",
        to_ref="destination",
        evaluator_key="cost:walk-egress",
        duration=(
            TimeEstimate(provider_leg.duration.p50_seconds, provider_leg.duration.p90_seconds)
            if provider_leg is not None
            else TimeEstimate(300, 420)
        ),
        distance_meters=(provider_leg.distance_meters if provider_leg is not None else 380),
        lower_bound_seconds=(provider_leg.duration.lower_seconds or 0 if provider_leg is not None else 240),
        readiness=readiness,
        reliability_score=0.95,
        topology_ref="fixture-walk:hub-b>destination",
    )


def _coordinate_registry(
    origin_raw: Mapping[str, object], destination_raw: Mapping[str, object]
) -> Mapping[str, tuple[float, float]]:
    origin = (float(origin_raw["lon"]), float(origin_raw["lat"]))
    destination = (float(destination_raw["lon"]), float(destination_raw["lat"]))
    return {
        "origin": origin,
        "upstream-stop": _coordinates_between(origin, destination, 0.12),
        "hub-a": _coordinates_between(origin, destination, 0.35),
        "bridge-left": _coordinates_between(origin, destination, 0.42),
        "bridge-right": _coordinates_between(origin, destination, 0.58),
        "hub-b": _coordinates_between(origin, destination, 0.78),
        "destination": destination,
    }


@dataclass(frozen=True, slots=True)
class _CanonicalMovementSource:
    leg: CanonicalLeg
    envelope: ProviderEnvelope
    itinerary_id: str
    routing_topology_ref: str | None = None


def _canonical_itinerary_identity(itinerary: CanonicalItinerary) -> str:
    """Hash every routing-relevant normalized value, excluding opaque source IDs.

    Provider itinerary/leg IDs are provenance, not route semantics.  Excluding
    them lets exact semantic duplicates collapse, while timing, fare, topology,
    stops and geometry remain in the identity so a potentially faster option is
    never discarded as a duplicate.
    """

    def timestamp(value: datetime | None) -> str | None:
        return value.astimezone(timezone.utc).isoformat() if value is not None else None

    material = []
    for leg in itinerary.legs:
        descriptor = leg.transit
        material.append(
            {
                "sequence": leg.sequence,
                "mode": leg.mode.value,
                "from": {
                    "name": leg.from_stop.name,
                    "coordinate": [leg.from_stop.coordinate.lon, leg.from_stop.coordinate.lat],
                    "externalId": leg.from_stop.external_id,
                    "sequence": leg.from_stop.sequence,
                },
                "to": {
                    "name": leg.to_stop.name,
                    "coordinate": [leg.to_stop.coordinate.lon, leg.to_stop.coordinate.lat],
                    "externalId": leg.to_stop.external_id,
                    "sequence": leg.to_stop.sequence,
                },
                "duration": {
                    "p50": leg.duration.p50_seconds,
                    "p90": leg.duration.p90_seconds,
                    "lower": leg.duration.lower_seconds,
                    "upper": leg.duration.upper_seconds,
                    "origin": leg.duration.origin.value,
                },
                "distanceMeters": leg.distance_meters,
                "fare": {
                    "expected": leg.fare.expected_krw,
                    "lower": leg.fare.lower_krw,
                    "upper": leg.fare.upper_krw,
                    "origin": leg.fare.origin.value,
                },
                "expectedStartAt": timestamp(leg.expected_start_at),
                "expectedEndAt": timestamp(leg.expected_end_at),
                "transit": (
                    None
                    if descriptor is None
                    else {
                        "routeLabel": descriptor.route_label,
                        "externalRouteId": descriptor.external_route_id,
                        "routeType": descriptor.route_type,
                        "direction": descriptor.direction,
                        "branchId": descriptor.branch_id,
                        "boardingSequence": descriptor.boarding_sequence,
                        "alightingSequence": descriptor.alighting_sequence,
                        "terminalNames": list(descriptor.terminal_names),
                        "liveVehicleObserved": descriptor.live_vehicle_observed,
                    }
                ),
                "geometry": [[point.lon, point.lat] for point in leg.geometry],
            }
        )
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _provider_transit_topology(
    leg: CanonicalLeg,
    from_ref: str,
    to_ref: str,
) -> CanonicalTransitTopology | None:
    """Return topology only when the Provider supplied every mapping-grade field."""

    descriptor = leg.transit
    if (
        descriptor is None
        or descriptor.external_route_id is None
        or descriptor.direction is None
        or descriptor.boarding_sequence is None
        or descriptor.alighting_sequence is None
    ):
        return None
    return CanonicalTransitTopology(
        descriptor.external_route_id,
        descriptor.direction,
        from_ref,
        to_ref,
        descriptor.boarding_sequence,
        descriptor.alighting_sequence,
        descriptor.branch_id,
    )


def _opaque_itinerary_local_topology(
    itinerary_identity: str,
    leg: CanonicalLeg,
    from_ref: str,
    to_ref: str,
) -> CanonicalTransitTopology:
    """Build a graph-only identity without manufacturing Provider identifiers."""

    encoded = json.dumps(
        {
            "itineraryIdentity": itinerary_identity,
            "legSequence": leg.sequence,
            "mode": leg.mode.value,
            "fromRef": from_ref,
            "toRef": to_ref,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    digest = sha256(encoded).hexdigest()
    return CanonicalTransitTopology(
        f"opaque-itinerary-local:{digest}",
        "OPAQUE_FORWARD",
        from_ref,
        to_ref,
        0,
        1,
    )


def _routing_transit_topology(
    itinerary_identity: str,
    leg: CanonicalLeg,
    from_ref: str,
    to_ref: str,
) -> tuple[CanonicalTransitTopology, bool]:
    provider_topology = _provider_transit_topology(leg, from_ref, to_ref)
    if provider_topology is not None:
        return provider_topology, True
    return (
        _opaque_itinerary_local_topology(
            itinerary_identity, leg, from_ref, to_ref
        ),
        False,
    )


def _canonicalize_returned_itineraries(
    payload: object,
    origin_raw: Mapping[str, object],
    destination_raw: Mapping[str, object],
    *,
    max_itineraries: int,
) -> tuple[tuple[str, CanonicalItinerary], ...]:
    """Return the complete finite payload in stable semantic-identity order."""

    if not isinstance(payload, tuple) or not payload:
        raise RoutingUnavailableError("required canonical transit fixture unavailable")
    if len(payload) > max_itineraries:
        raise RoutingUnavailableError("transit payload exceeds requested itinerary bound")
    grouped: dict[str, list[CanonicalItinerary]] = {}
    identity_by_provider_id: dict[str, str] = {}
    for value in payload:
        if not isinstance(value, CanonicalItinerary):
            raise RoutingUnavailableError("transit payload contains a non-canonical itinerary")
        if not (
            _coordinates_equal(value.legs[0].from_stop.coordinate, origin_raw)
            and _coordinates_equal(value.legs[-1].to_stop.coordinate, destination_raw)
        ):
            raise RoutingUnavailableError("fixture canonical endpoints do not match request")
        if not any(
            leg.mode.value in {"BUS", "SUBWAY", "GTX", "TRAIN"}
            for leg in value.legs
        ):
            raise RoutingUnavailableError("required canonical transit baseline unavailable")
        identity = _canonical_itinerary_identity(value)
        previous_identity = identity_by_provider_id.setdefault(
            value.itinerary_id, identity
        )
        if previous_identity != identity:
            raise RoutingUnavailableError(
                "transit payload reuses an itinerary ID for conflicting content"
            )
        grouped.setdefault(identity, []).append(value)

    return tuple(
        (
            identity,
            min(
                values,
                key=lambda itinerary: (
                    itinerary.itinerary_id,
                    tuple(leg.leg_id for leg in itinerary.legs),
                ),
            ),
        )
        for identity, values in sorted(grouped.items())
    )


def _canonical_itinerary_baseline(
    itinerary: CanonicalItinerary,
    envelope: ProviderEnvelope,
    *,
    baseline_id: str = "mapped-public",
    reference_namespace: str | None = None,
    bus_intelligence_enabled: bool = True,
) -> tuple[
    TransitBaseline,
    dict[str, tuple[float, float]],
    dict[tuple[str, str, str, str], _CanonicalMovementSource],
    tuple[tuple[str, CanonicalTransitEvidence], ...],
]:
    """Preserve every normalized itinerary movement and its causal envelope."""

    itinerary_identity = _canonical_itinerary_identity(itinerary)
    namespace = reference_namespace or itinerary_identity
    references = ["origin"]
    references.extend(
        f"provider-stop:{namespace}:{index}"
        for index in range(1, len(itinerary.legs))
    )
    references.append("destination")
    coordinates: dict[str, tuple[float, float]] = {}
    movements: list[WalkQuote | TransitLegInput] = []
    sources: dict[tuple[str, str, str, str], _CanonicalMovementSource] = {}
    bus_evidence: list[tuple[str, CanonicalTransitEvidence]] = []
    provider_code = _mapping_provider_code(envelope.provider)
    provider_quote_readiness = (
        QuoteReadiness.EXACT
        if envelope.provider == "KAKAO_PUBLIC_TRANSIT"
        else QuoteReadiness.COARSE
    )
    for index, leg in enumerate(itinerary.legs):
        source_leg = (
            replace(leg, expected_start_at=None, expected_end_at=None)
            if envelope.provider == "KAKAO_PUBLIC_TRANSIT"
            else leg
        )
        from_ref, to_ref = references[index], references[index + 1]
        coordinates[from_ref] = (
            leg.from_stop.coordinate.lon,
            leg.from_stop.coordinate.lat,
        )
        coordinates[to_ref] = (
            leg.to_stop.coordinate.lon,
            leg.to_stop.coordinate.lat,
        )
        if leg.mode.value == "WALK":
            movement: WalkQuote | TransitLegInput = WalkQuote(
                quote_id=f"provider-walk:{namespace}:{leg.sequence}",
                from_ref=from_ref,
                to_ref=to_ref,
                evaluator_key=f"provider-cost:{namespace}:{leg.sequence}:{leg.leg_id}",
                duration=TimeEstimate(
                    leg.duration.p50_seconds, leg.duration.p90_seconds
                ),
                distance_meters=leg.distance_meters,
                lower_bound_seconds=leg.duration.lower_seconds or 0,
                readiness=provider_quote_readiness,
                reliability_score=0.9,
                topology_ref=f"provider:{leg.leg_id}",
            )
            kind = EnrichmentKind.WALK
        else:
            descriptor = leg.transit
            if descriptor is None:
                raise RoutingUnavailableError(
                    "canonical transit leg lacks descriptor"
                )
            topology, provider_topology_complete = _routing_transit_topology(
                itinerary_identity, leg, from_ref, to_ref
            )
            movement = TransitLegInput(
                leg_id=f"provider-transit:{namespace}:{leg.sequence}",
                mode=leg.mode.value,
                topology=topology,
                evaluator_key=f"provider-cost:{namespace}:{leg.sequence}:{leg.leg_id}",
                duration=TimeEstimate(
                    leg.duration.p50_seconds, leg.duration.p90_seconds
                ),
                fare=MoneyRange(
                    leg.fare.expected_krw,
                    leg.fare.lower_krw,
                    leg.fare.upper_krw,
                ),
                lower_bound_seconds=leg.duration.lower_seconds or 0,
                reliability_score=0.9,
                # Kakao's current journey response supplies duration, not a
                # vehicle departure timestamp. Its parser clock is causal
                # bookkeeping and must not be treated as a fixed connection.
                scheduled_departure_at=(
                    None
                    if envelope.provider == "KAKAO_PUBLIC_TRANSIT"
                    else leg.expected_start_at
                ),
                readiness=provider_quote_readiness,
                mapping_ready=(
                    leg.mode.value != "BUS"
                    or not bus_intelligence_enabled
                    or provider_topology_complete
                ),
                bus_intelligence_requested=(
                    leg.mode.value == "BUS" and bus_intelligence_enabled
                ),
                bus_wait=None,
            )
            kind = EnrichmentKind.TRANSIT
            if leg.mode.value == "BUS":
                bus_evidence.append(
                    (
                        movement.topology.fingerprint,
                        CanonicalTransitEvidence(
                        provider_code=provider_code,
                        envelope_fingerprint=envelope.fingerprint,
                        itinerary_id=itinerary.itinerary_id,
                            leg=source_leg,
                        ),
                    )
                )
        movements.append(movement)
        key = (*_movement_key(kind, from_ref, to_ref), movement.evaluator_key)
        sources[key] = _CanonicalMovementSource(
            source_leg,
            envelope,
            itinerary.itinerary_id,
            (
                movement.topology.fingerprint
                if isinstance(movement, TransitLegInput)
                else None
            ),
        )
    return (
        TransitBaseline(baseline_id, tuple(movements), coarse_risk=0.18),
        coordinates,
        sources,
        tuple(bus_evidence),
    )


def _movement_key(kind: EnrichmentKind, from_ref: str, to_ref: str) -> tuple[str, str, str]:
    return kind.value, from_ref, to_ref


def _exact_transit_movement(
    template: TransitLegInput,
    provider_leg: CanonicalLeg,
    *,
    bus_wait: BusWaitContribution | None,
    mapping_ready: bool,
) -> TransitLegInput | None:
    if provider_leg.transit is None:
        return None
    provider_topology = _provider_transit_topology(
        provider_leg, template.from_ref, template.to_ref
    )
    return TransitLegInput(
        leg_id=template.leg_id,
        mode=provider_leg.mode.value,
        topology=provider_topology or template.topology,
        evaluator_key=template.evaluator_key,
        duration=TimeEstimate(
            provider_leg.duration.p50_seconds, provider_leg.duration.p90_seconds
        ),
        fare=MoneyRange(
            provider_leg.fare.expected_krw,
            provider_leg.fare.lower_krw,
            provider_leg.fare.upper_krw,
        ),
        lower_bound_seconds=provider_leg.duration.lower_seconds or 0,
        reliability_score=template.reliability_score,
        scheduled_departure_at=provider_leg.expected_start_at,
        transfer_requirement=template.transfer_requirement,
        bus_wait=bus_wait if provider_leg.mode.value == "BUS" else None,
        readiness=QuoteReadiness.EXACT,
        mapping_ready=mapping_ready and provider_topology is not None,
        bus_intelligence_requested=False,
    )


def _exact_strategy_input(
    coarse_input: StrategyGenerationInput,
    resolved: Mapping[tuple[str, str, str], CanonicalLeg],
    *,
    taxi_dispatches: Mapping[tuple[str, str, str], TaxiDispatchEstimate] | None = None,
    mapping_ready: bool,
) -> StrategyGenerationInput:
    dispatches = taxi_dispatches or {}
    baselines: dict[str, TransitBaseline] = {}
    for baseline in coarse_input.transit_baselines:
        movements = []
        for movement in baseline.legs:
            kind = EnrichmentKind.WALK if isinstance(movement, WalkQuote) else EnrichmentKind.TRANSIT
            provider_leg = resolved.get(_movement_key(kind, movement.from_ref, movement.to_ref))
            if provider_leg is None:
                movements = []
                break
            if isinstance(movement, WalkQuote):
                if provider_leg.mode.value != "WALK":
                    movements = []
                    break
                movements.append(
                    WalkQuote(
                        quote_id=movement.quote_id,
                        from_ref=movement.from_ref,
                        to_ref=movement.to_ref,
                        evaluator_key=movement.evaluator_key,
                        duration=TimeEstimate(
                            provider_leg.duration.p50_seconds,
                            provider_leg.duration.p90_seconds,
                        ),
                        distance_meters=provider_leg.distance_meters,
                        lower_bound_seconds=provider_leg.duration.lower_seconds or 0,
                        readiness=QuoteReadiness.EXACT,
                        reliability_score=movement.reliability_score,
                        topology_ref=f"provider:{provider_leg.leg_id}",
                    )
                )
            else:
                exact = _exact_transit_movement(
                    movement,
                    provider_leg,
                    # Wait is evaluated at the propagated candidate entry time by
                    # the request-scoped evaluator. A fixed contribution here
                    # would double count and collapse distinct Bus legs.
                    bus_wait=None,
                    mapping_ready=mapping_ready,
                )
                if exact is None:
                    movements = []
                    break
                movements.append(exact)
        if movements:
            baselines[baseline.baseline_id] = TransitBaseline(
                baseline.baseline_id, tuple(movements), baseline.coarse_risk
            )

    def taxi(value: TaxiQuote) -> TaxiQuote | None:
        provider_leg = resolved.get(
            _movement_key(EnrichmentKind.TAXI, value.from_ref, value.to_ref)
        )
        if provider_leg is None or provider_leg.mode.value != "TAXI":
            return None
        dispatch = dispatches.get(
            _movement_key(EnrichmentKind.TAXI, value.from_ref, value.to_ref)
        )
        if dispatch is None:
            # Provider directions duration is drive-only.  Missing dispatch
            # evidence rejects this Taxi-dependent candidate; zero is not an
            # admissible substitute for unknown.
            return None
        return TaxiQuote(
            quote_id=value.quote_id,
            from_ref=value.from_ref,
            to_ref=value.to_ref,
            evaluator_key=value.evaluator_key,
            dispatch_wait=dispatch.wait,
            drive_duration=TimeEstimate(
                provider_leg.duration.p50_seconds, provider_leg.duration.p90_seconds
            ),
            fare=MoneyRange(
                provider_leg.fare.expected_krw,
                provider_leg.fare.lower_krw,
                provider_leg.fare.upper_krw,
            ),
            distance_meters=provider_leg.distance_meters,
            readiness=QuoteReadiness.EXACT,
            reliability_score=value.reliability_score,
            topology_ref=f"provider:{provider_leg.leg_id}",
        )

    access = tuple(
        AccessHub(item.hub_id, item.baseline_id, item.board_leg_index, quote)
        for item in coarse_input.access_hubs
        if item.baseline_id in baselines and (quote := taxi(item.taxi_quote)) is not None
    )
    egress = tuple(
        EgressHub(item.hub_id, item.baseline_id, item.alight_leg_index, quote)
        for item in coarse_input.egress_hubs
        if item.baseline_id in baselines and (quote := taxi(item.taxi_quote)) is not None
    )
    upstream = []
    for item in coarse_input.upstream_hubs:
        quote = taxi(item.taxi_quote)
        provider_leg = resolved.get(
            _movement_key(
                EnrichmentKind.TRANSIT,
                item.upstream_leg.from_ref,
                item.upstream_leg.to_ref,
            )
        )
        exact_leg = (
            _exact_transit_movement(
                item.upstream_leg,
                provider_leg,
                bus_wait=None,
                mapping_ready=True,
            )
            if provider_leg is not None else None
        )
        if item.baseline_id in baselines and quote is not None and exact_leg is not None:
            upstream.append(
                UpstreamHub(
                    item.hub_id, item.baseline_id, item.replace_leg_index, exact_leg, quote
                )
            )
    bridges = tuple(
        TaxiBridge(
            item.bridge_id,
            item.inbound_baseline_id,
            item.inbound_end_index,
            item.outbound_baseline_id,
            item.outbound_start_index,
            quote,
            item.transfer_requirement,
        )
        for item in coarse_input.taxi_bridges
        if item.inbound_baseline_id in baselines
        and item.outbound_baseline_id in baselines
        and (quote := taxi(item.taxi_quote)) is not None
    )
    taxi_only = tuple(
        quote
        for item in coarse_input.taxi_only_quotes
        if (quote := taxi(item)) is not None
    )
    return StrategyGenerationInput(
        origin_ref=coarse_input.origin_ref,
        destination_ref=coarse_input.destination_ref,
        departure_at=coarse_input.departure_at,
        transit_baselines=tuple(baselines.values()),
        access_hubs=access,
        egress_hubs=egress,
        upstream_hubs=tuple(upstream),
        taxi_bridges=bridges,
        taxi_only_quotes=taxi_only,
    )
def _coarse_strategy_inputs(
    departure: datetime,
    budget: int,
    *,
    route_suffix: str,
    main_mode: str = "BUS",
    canonical_baselines: tuple[TransitBaseline, ...] = (),
) -> StrategyGenerationInput:
    readiness = QuoteReadiness.COARSE
    if route_suffix == "production" and canonical_baselines:
        ordered = tuple(
            sorted(
                canonical_baselines,
                key=lambda item: (
                    sum(leg.lower_bound_seconds for leg in item.legs),
                    item.baseline_id,
                ),
            )
        )
        # Preserve the fastest baseline, then spend the remaining bounded hybrid
        # slots on mode diversity.  Pure lower-bound ordering could fill every
        # slot with near-identical Bus itineraries and silently exclude a slightly
        # slower Subway/GTX itinerary before Taxi access/egress/bridge variants
        # were even generated.
        hybrid_baseline_list = [ordered[0]]
        remaining_baselines = list(ordered[1:])

        def transit_modes(value: TransitBaseline) -> frozenset[str]:
            return frozenset(
                leg.mode
                for leg in value.legs
                if isinstance(leg, TransitLegInput)
            )

        covered_modes = set(transit_modes(ordered[0]))
        while remaining_baselines and len(hybrid_baseline_list) < 3:
            selected = max(
                remaining_baselines,
                key=lambda item: len(transit_modes(item) - covered_modes),
            )
            remaining_baselines.remove(selected)
            hybrid_baseline_list.append(selected)
            covered_modes.update(transit_modes(selected))
        hybrid_baselines = tuple(hybrid_baseline_list)
        access_hubs: list[AccessHub] = []
        egress_hubs: list[EgressHub] = []

        for baseline in hybrid_baselines:
            transit_indices = [
                index
                for index, leg in enumerate(baseline.legs)
                if isinstance(leg, TransitLegInput)
            ]
            access_indices = [
                index
                for index in transit_indices
                if baseline.legs[index].from_ref != "origin"
            ]
            if access_indices:
                # Prefer entering directly at the first high-capacity rail leg;
                # otherwise replace the initial access walk with Taxi→Bus.
                board_index = min(
                    access_indices,
                    key=lambda index: (
                        baseline.legs[index].mode not in {"SUBWAY", "GTX", "TRAIN"},
                        index,
                    ),
                )
                board = baseline.legs[board_index]
                skipped = sum(
                    item.lower_bound_seconds for item in baseline.legs[:board_index]
                )
                access_hubs.append(
                    AccessHub(
                        f"live-access:{baseline.baseline_id}:{board_index}",
                        baseline.baseline_id,
                        board_index,
                        _taxi(
                            f"live-access:{baseline.baseline_id}:{board_index}",
                            "origin",
                            board.from_ref,
                            max(0, budget),
                            readiness=readiness,
                            drive_seconds=max(180, min(1_800, skipped // 2)),
                        ),
                    )
                )

            egress_indices = [
                index
                for index in transit_indices
                if baseline.legs[index].to_ref != "destination"
            ]
            if egress_indices:
                alight_index = egress_indices[-1]
                alight = baseline.legs[alight_index]
                skipped = sum(
                    item.lower_bound_seconds
                    for item in baseline.legs[alight_index + 1 :]
                )
                egress_hubs.append(
                    EgressHub(
                        f"live-egress:{baseline.baseline_id}:{alight_index}",
                        baseline.baseline_id,
                        alight_index,
                        _taxi(
                            f"live-egress:{baseline.baseline_id}:{alight_index}",
                            alight.to_ref,
                            "destination",
                            max(0, budget),
                            readiness=readiness,
                            drive_seconds=max(180, min(1_800, skipped // 2)),
                        ),
                    )
                )

        # Ensure at least one Bus→Taxi alternative is evaluated when a returned
        # itinerary contains Bus before its final transit leg.
        bus_egress_keys = {
            (item.baseline_id, item.alight_leg_index) for item in egress_hubs
        }
        for baseline in hybrid_baselines:
            bus_indices = [
                index
                for index, leg in enumerate(baseline.legs)
                if isinstance(leg, TransitLegInput)
                and leg.mode == "BUS"
                and leg.to_ref != "destination"
            ]
            if not bus_indices:
                continue
            index = bus_indices[-1]
            if (baseline.baseline_id, index) not in bus_egress_keys:
                leg = baseline.legs[index]
                egress_hubs.append(
                    EgressHub(
                        f"live-bus-egress:{baseline.baseline_id}:{index}",
                        baseline.baseline_id,
                        index,
                        _taxi(
                            f"live-bus-egress:{baseline.baseline_id}:{index}",
                            leg.to_ref,
                            "destination",
                            max(0, budget),
                            readiness=readiness,
                            drive_seconds=600,
                        ),
                    )
                )
                break

        bridges: list[TaxiBridge] = []
        bridge_modes = (
            ({"BUS"}, {"SUBWAY", "GTX", "TRAIN"}),
            ({"SUBWAY", "GTX", "TRAIN"}, {"BUS"}),
        )
        for inbound_modes, outbound_modes in bridge_modes:
            selected = None
            for inbound in hybrid_baselines:
                for inbound_index, inbound_leg in enumerate(inbound.legs):
                    if not isinstance(inbound_leg, TransitLegInput) or inbound_leg.mode not in inbound_modes:
                        continue
                    for outbound in hybrid_baselines:
                        for outbound_index, outbound_leg in enumerate(outbound.legs):
                            if (
                                not isinstance(outbound_leg, TransitLegInput)
                                or outbound_leg.mode not in outbound_modes
                                or inbound_leg.to_ref == outbound_leg.from_ref
                                or (
                                    inbound.baseline_id == outbound.baseline_id
                                    and inbound_index >= outbound_index
                                )
                            ):
                                continue
                            selected = (
                                inbound,
                                inbound_index,
                                inbound_leg,
                                outbound,
                                outbound_index,
                                outbound_leg,
                            )
                            break
                        if selected is not None:
                            break
                    if selected is not None:
                        break
                if selected is not None:
                    break
            if selected is None:
                continue
            inbound, inbound_index, inbound_leg, outbound, outbound_index, outbound_leg = selected
            bridge_id = (
                f"live-bridge:{inbound.baseline_id}:{inbound_index}:"
                f"{outbound.baseline_id}:{outbound_index}"
            )
            bridges.append(
                TaxiBridge(
                    bridge_id,
                    inbound.baseline_id,
                    inbound_index,
                    outbound.baseline_id,
                    outbound_index,
                    _taxi(
                        bridge_id,
                        inbound_leg.to_ref,
                        outbound_leg.from_ref,
                        max(0, budget),
                        readiness=readiness,
                        drive_seconds=480,
                    ),
                    TransferRequirement(120, 240, 60),
                )
            )

        return StrategyGenerationInput(
            origin_ref="origin",
            destination_ref="destination",
            departure_at=departure,
            transit_baselines=ordered,
            access_hubs=tuple(access_hubs),
            egress_hubs=tuple(egress_hubs),
            taxi_bridges=tuple(bridges),
            taxi_only_quotes=(
                _taxi(
                    "taxi-only",
                    "origin",
                    "destination",
                    max(0, budget),
                    readiness=readiness,
                    drive_seconds=1_200,
                ),
            ),
        )
    mapped_public = TransitBaseline(
        "mapped-public",
        (
            _transit(
                "mapped-public-transit", main_mode, f"canonical-fixture-transit-{route_suffix}",
                "origin", "destination", 10, 20, 600,
                mapping_ready=(main_mode != "BUS"), bus_requested=(main_mode == "BUS"), readiness=readiness,
            ),
        ),
        coarse_risk=0.18,
    )
    full = TransitBaseline(
        "full",
        (
            _transit("full-subway-access", "SUBWAY", f"fixture-line-a-{route_suffix}", "origin", "hub-a", 1, 4, 660, readiness=readiness),
            _transit("full-subway", "SUBWAY", f"fixture-line-s-{route_suffix}", "hub-a", "hub-b", 1, 8, 720, readiness=readiness),
            _walk(readiness),
        ),
        coarse_risk=0.18,
    )
    inbound = TransitBaseline(
        "bridge-in",
        (_transit("bridge-in-bus", "BUS", f"fixture-route-in-{route_suffix}", "origin", "bridge-left", 1, 5, 420, readiness=readiness),),
    )
    outbound = TransitBaseline(
        "bridge-out",
        (_transit("bridge-out-subway", "SUBWAY", f"fixture-route-out-{route_suffix}", "bridge-right", "destination", 2, 9, 480, readiness=readiness),),
    )
    impossible_outbound = TransitBaseline(
        "bridge-out-impossible",
        (_transit(
            "bridge-out-too-early", "SUBWAY", f"fixture-route-out-early-{route_suffix}",
            "bridge-right", "destination", 2, 9, 480,
            scheduled=departure + timedelta(seconds=100), readiness=readiness,
        ),),
    )
    upstream = _transit(
        "upstream-bus", "BUS", f"canonical-fixture-transit-{route_suffix}",
        "upstream-stop", "destination", 5, 20, 540, readiness=readiness,
    )
    primary_canonical = canonical_baselines[0] if canonical_baselines else None
    if primary_canonical is not None:
        canonical_transit = next(
            (
                item
                for item in primary_canonical.legs
                if isinstance(item, TransitLegInput) and item.mode == "BUS"
            ),
            None,
        )
        if canonical_transit is not None:
            upstream = replace(
                upstream,
                topology=CanonicalTransitTopology(
                        canonical_transit.topology.route_ref,
                    canonical_transit.topology.direction,
                    "upstream-stop",
                    canonical_transit.to_ref,
                    max(0, canonical_transit.topology.board_sequence - 1),
                    canonical_transit.topology.alight_sequence,
                        canonical_transit.topology.branch_ref,
                ),
            )
    wrong_upstream = replace(
        upstream,
        leg_id="upstream-wrong-direction",
        evaluator_key="cost:upstream-wrong-direction",
        topology=CanonicalTransitTopology(
            f"canonical-fixture-transit-{route_suffix}", "INBOUND",
            "upstream-stop", "destination", 5, 20,
        ),
    )
    return StrategyGenerationInput(
        origin_ref="origin",
        destination_ref="destination",
        departure_at=departure,
        transit_baselines=(
            *(canonical_baselines or (mapped_public,)),
            full,
            inbound,
            outbound,
            impossible_outbound,
        ),
        access_hubs=(AccessHub("access", "full", 1, _taxi("access", "origin", "hub-a", 2_500, readiness=readiness)),),
        egress_hubs=(EgressHub("egress", "full", 1, _taxi("egress", "hub-b", "destination", 2_500, readiness=readiness)),),
        upstream_hubs=(
            UpstreamHub("upstream-win", "mapped-public", 0, upstream, _taxi("upstream", "origin", "upstream-stop", 2_500, readiness=readiness, drive_seconds=240)),
            UpstreamHub("upstream-loss", "mapped-public", 0, wrong_upstream, _taxi("upstream", "origin", "upstream-stop", 2_500, readiness=readiness, drive_seconds=240)),
        ),
        taxi_bridges=(
            TaxiBridge("bridge-win", "bridge-in", 0, "bridge-out", 0, _taxi("bridge", "bridge-left", "bridge-right", 3_000, readiness=readiness, drive_seconds=180), TransferRequirement(30, 60)),
            TaxiBridge("bridge-loss", "bridge-in", 0, "bridge-out-impossible", 0, _taxi("bridge", "bridge-left", "bridge-right", 3_000, readiness=readiness, drive_seconds=180), TransferRequirement(60, 120)),
        ),
        taxi_only_quotes=(
            _taxi("taxi-only", "origin", "destination", 9_000, readiness=readiness, drive_seconds=1_200),
            _taxi("over-budget", "origin", "destination", budget + 1, readiness=readiness, drive_seconds=1_500),
        ),
    )


def _constraints(payload: Mapping[str, object]) -> RouteConstraints:
    raw = payload["constraints"]
    assert isinstance(raw, Mapping)
    taxi = raw["taxiBudget"]
    assert isinstance(taxi, Mapping)
    return RouteConstraints(
        taxi_budget_krw=int(taxi["maxAmount"]),
        strict_taxi_budget=True,
        max_walk_seconds=int(raw["maxWalkSeconds"]),
        max_transfers=int(raw["maxTransfers"]),
        max_taxi_legs=int(raw["maxTaxiLegs"]),
        allowed_modes=frozenset(raw["allowedModes"]),
        allow_taxi_bridge=bool(raw.get("allowTaxiBridge", False)),
    )


def _mapping_pipeline(provider_leg: CanonicalLeg, departure: datetime, fault=None):
    source = _mapping_input(provider_leg)
    target = _mapping_target(source, departure, fault)
    pipeline = TransportMappingPipeline(
        InMemoryGbisCatalogRepository((target,)),
        InMemoryMappingReviewRepository(),
    )
    return pipeline.map_bus_leg(
        "KAKAO_TRANSIT",
        provider_leg,
        evaluated_at=departure,
        mapping_version=MAPPING_VERSION,
    ), target


def _unavailable_mapping(provider_leg: CanonicalLeg) -> MappingPipelineResult:
    return MappingPipelineResult(
        source=_mapping_input(provider_leg),
        evaluated=(),
        selected=None,
        selected_cache_key=None,
        review_ticket_id=None,
    )


def _joined_vehicle_observations(
    arrivals: ProviderEnvelope,
    locations: ProviderEnvelope,
    *,
    mapping: MappingPipelineResult,
    target,
    query: BusObservationQuery,
) -> tuple[VehicleObservation, ...]:
    """Build live candidates with official ETA taking precedence over position."""

    if not mapping.allows_bus_intelligence:
        return ()
    arrival_values = (
        arrivals.payload
        if arrivals.status is ProviderStatus.OK and isinstance(arrivals.payload, tuple)
        else ()
    )
    location_values = (
        locations.payload
        if locations.status is ProviderStatus.OK and isinstance(locations.payload, tuple)
        else ()
    )
    values: list[VehicleObservation] = []
    arrival_keys: set[tuple[str, str]] = set()
    for value in arrival_values:
        if not isinstance(value, BusArrivalObservation):
            continue
        if (
            value.route_external_id != query.route_id
            or value.station_external_id != query.boarding_station_id
            or value.observed_at > query.evaluated_at
        ):
            continue
        join_key = value.vehicle_join_key
        if join_key is not None:
            arrival_keys.add(join_key)
        official = EtaPrediction(
            p50_arrival_at=value.observed_at + timedelta(seconds=value.eta_seconds),
            p90_arrival_at=value.observed_at + timedelta(seconds=value.eta_seconds),
            source="OFFICIAL",
            confidence=1.0,
        )
        values.append(
            VehicleObservation(
                vehicle_ref=(
                    value.vehicle_token
                    or "arrival_"
                    + sha256(
                        (
                            f"{value.route_external_id}|{value.station_external_id}|"
                            f"{official.p50_arrival_at.isoformat()}"
                        ).encode("utf-8")
                    ).hexdigest()[:24]
                ),
                route_id=target.route_id,
                direction=target.direction or "UNKNOWN",
                boarding_stop_id=target.boarding.external_id or value.station_external_id,
                observed_at=value.observed_at,
                official_eta=official,
                remain_seat_observed=value.remaining_seats,
                future_target_remaining_seats=None,
            )
        )
    # A running vehicle can have a location before GBIS publishes a stop ETA.
    # Preserve it as a model candidate; the ETA arbitrator will use the position
    # model and then its historical predictor, or leave it unknown explicitly.
    for value in location_values:
        if (
            not isinstance(value, BusLocationObservation)
            or value.route_external_id != query.route_id
            or value.observed_at > query.evaluated_at
            or value.vehicle_join_key in arrival_keys
        ):
            continue
        values.append(
            VehicleObservation(
                vehicle_ref=value.vehicle_token,
                route_id=target.route_id,
                direction=target.direction or "UNKNOWN",
                boarding_stop_id=target.boarding.external_id or query.boarding_station_id,
                observed_at=value.observed_at,
                official_eta=None,
                remain_seat_observed=None,
                future_target_remaining_seats=None,
            )
        )
    return tuple(values)


def _bus_result(
    mapping: MappingPipelineResult,
    target,
    arrival: datetime,
    allowed: bool,
    arrivals: ProviderEnvelope,
    locations: ProviderEnvelope,
    eta_predictor,
    seat_predictor,
    query: BusObservationQuery,
    *,
    service_type: str | None,
    evaluated_at: datetime | None = None,
    eta_feature_context: EtaFeatureContext | None = None,
    seat_risk_feature_context: SeatRiskFeatureContext | None = None,
    inference_budget: _RequestModelInferenceBudget | None = None,
) -> BusIntelligenceResult:
    if service_type not in {"GENERAL", "SEATED"}:
        return _unobserved_bus(mapping_allowed=allowed)
    observations = (
        _joined_vehicle_observations(
            arrivals, locations, mapping=mapping, target=target, query=query
        )
        if allowed
        else ()
    )
    budgeted_eta = (
        _BudgetedEtaPredictor(eta_predictor, inference_budget)
        if inference_budget is not None
        else eta_predictor
    )
    budgeted_seat = (
        _BudgetedSeatRiskPredictor(seat_predictor, inference_budget)
        if inference_budget is not None
        else seat_predictor
    )
    result = BusIntelligenceEngine(budgeted_eta, budgeted_seat).enrich(
        BusIntelligenceRequest(
            mapping_grade=(
                str(mapping.selected.grade) if mapping.selected is not None else "UNKNOWN"
            ),
            mapping_allows_bus_intelligence=mapping.allows_bus_intelligence,
            mapping_score=(mapping.selected.score if mapping.selected is not None else 0.0),
            mapping_version=(
                mapping.selected.mapping_version if mapping.selected is not None else "UNAVAILABLE"
            ),
            user_arrival_at=arrival,
            evaluated_at=evaluated_at or query.evaluated_at,
            target_stop_id=target.alighting.external_id or "fixture-target",
            service_type=service_type,
            observations=observations,
            eta_feature_context=eta_feature_context,
            seat_risk_feature_context=(
                seat_risk_feature_context if service_type == "SEATED" else None
            ),
        )
    )
    if (
        isinstance(result.expected_wait_seconds, int)
        and isinstance(result.p90_wait_seconds, int)
        and result.p90_wait_seconds < result.expected_wait_seconds
    ):
        result = replace(result, p90_wait_seconds=result.expected_wait_seconds)
    return result


def _usable_bus_wait(result: BusIntelligenceResult) -> TimeEstimate | None:
    if (
        isinstance(result.expected_wait_seconds, int)
        and isinstance(result.p90_wait_seconds, int)
    ):
        return TimeEstimate(result.expected_wait_seconds, result.p90_wait_seconds)
    # ETA remains valid for a seated bus even when seat-risk is unavailable.
    # Keep boarding risk unknown, but do not throw away the live arrival clock.
    if result.candidate_vehicles:
        candidate = min(
            result.candidate_vehicles,
            key=lambda item: (item.wait_p50_seconds, item.wait_p90_seconds),
        )
        return TimeEstimate(candidate.wait_p50_seconds, candidate.wait_p90_seconds)
    return None


class _RequestScopedLegEvaluator:
    """Add candidate-entry-time Bus wait to exact immutable movement costs."""

    def __init__(
        self,
        costs: Mapping[str, LegCost],
        snapshots: tuple[_BusLegSnapshot, ...],
        eta_predictor: EtaPredictor,
        seat_predictor: SeatRiskPredictor,
        inference_budget: _RequestModelInferenceBudget,
        bus_wait_estimator: BusWaitEstimator | None = None,
        evaluated_at: datetime | None = None,
    ) -> None:
        self._base = StaticLegEvaluator(costs)
        self._snapshots = {item.topology_ref: item for item in snapshots}
        self._snapshots_by_leg = {
            item.leg_id: item for item in snapshots if item.leg_id is not None
        }
        self._eta_predictor = eta_predictor
        self._seat_predictor = seat_predictor
        self._inference_budget = inference_budget
        self._bus_wait_estimator = bus_wait_estimator
        self._evaluated_at = evaluated_at
        self._evaluations: dict[tuple[str, datetime], _BusLegEvaluation] = {}
        self._ready_costs: dict[tuple[str, datetime], LegCost] = {}

    @property
    def evaluations(self) -> tuple[_BusLegEvaluation, ...]:
        return tuple(
            self._evaluations[key]
            for key in sorted(self._evaluations, key=lambda item: (item[0], item[1]))
        )

    def evaluate(self, leg, entry_at: datetime) -> LegCost:
        base = self._base.evaluate(leg, entry_at)
        snapshot = self._snapshots_by_leg.get(leg.leg_id) or self._snapshots.get(
            leg.topology_ref
        )
        if leg.mode != "BUS" or snapshot is None:
            return base
        cache_key = (leg.leg_id, entry_at)
        cached = self._ready_costs.get(cache_key)
        if cached is not None:
            return cached
        if (
            not snapshot.mapping_allows_intelligence
            or snapshot.query is None
            or snapshot.arrivals is None
            or snapshot.locations is None
        ):
            result = _unobserved_bus(
                mapping_allowed=snapshot.mapping_allows_intelligence
            )
        else:
            result = _bus_result(
                snapshot.mapping,
                snapshot.target,
                entry_at,
                True,
                snapshot.arrivals,
                snapshot.locations,
                self._eta_predictor,
                self._seat_predictor,
                snapshot.query,
                service_type=snapshot.service_type,
                evaluated_at=snapshot.query.evaluated_at,
                eta_feature_context=snapshot.eta_feature_context,
                seat_risk_feature_context=snapshot.seat_risk_feature_context,
                inference_budget=self._inference_budget,
            )
        self._evaluations[cache_key] = _BusLegEvaluation(
            leg.leg_id, leg.topology_ref, entry_at, result
        )
        live_wait = _usable_bus_wait(result)
        if live_wait is not None:
            cost = LegCost(
                wait=live_wait,
                travel=base.travel,
                fare=base.fare,
                reliability_score=min(
                    base.reliability_score, result.confidence_score
                ),
                warning_codes=tuple(
                    sorted(
                        (set(base.warning_codes) - {"BUS_WAIT_UNKNOWN"})
                        | set(result.warnings)
                    )
                ),
            )
            self._ready_costs[cache_key] = cost
            return cost
        fallback = None
        if self._bus_wait_estimator is not None:
            fallback = self._bus_wait_estimator.estimate(
                snapshot.evidence.leg,
                arrival_at=entry_at,
                evaluated_at=self._evaluated_at or entry_at,
            )
        if fallback is not None:
            fallback_warnings = set(base.warning_codes) - {"BUS_WAIT_UNKNOWN"}
            reliability = base.reliability_score
            if fallback.origin == "HISTORICAL_PROXY":
                fallback_warnings.add("HISTORICAL_PROXY_USED")
                reliability = min(reliability, 0.72)
            elif fallback.origin == "MODEL_PREDICTED":
                reliability = min(reliability, 0.82)
            else:
                reliability = min(reliability, 0.9)
            cost = LegCost(
                wait=fallback.wait,
                travel=base.travel,
                fare=base.fare,
                reliability_score=reliability,
                warning_codes=tuple(sorted(fallback_warnings)),
            )
            self._ready_costs[cache_key] = cost
            return cost
        if "BUS_WAIT_UNKNOWN" in base.warning_codes:
            raise ValueError("BUS_WAIT_UNKNOWN")
        # A normalized provider schedule can be the explicit fallback when Bus
        # observations are absent. Projection remains null/unobserved; the
        # schedule-derived wait is not mislabeled as Bus Intelligence.
        self._ready_costs[cache_key] = base
        return base

    def evaluate_travel(
        self,
        leg,
        start_at: datetime,
        ready_cost: LegCost | None,
    ) -> LegCost:
        """Evaluate movement without re-selecting a ready-time Bus vehicle."""

        base = self._base.evaluate(leg, start_at)
        if leg.mode != "BUS" or ready_cost is None:
            return base
        return LegCost(
            wait=TimeEstimate(0, 0),
            travel=base.travel,
            fare=base.fare,
            reliability_score=ready_cost.reliability_score,
            warning_codes=ready_cost.warning_codes,
        )


def _canonical_routing_graph(seeds: tuple[CandidateSeed, ...]) -> CanonicalRoutingGraph:
    """Build one deterministic exact graph, rejecting ambiguous edge identity."""

    by_leg_id: dict[str, LegSpec] = {}
    for seed in seeds:
        for leg in seed.legs:
            current = by_leg_id.get(leg.leg_id)
            if current is not None and current != leg:
                raise RoutingUnavailableError("canonical graph leg identity conflict")
            by_leg_id[leg.leg_id] = leg
    return CanonicalRoutingGraph(
        tuple(
            sorted(
                by_leg_id.values(),
                key=lambda leg: (
                    leg.from_ref,
                    leg.to_ref,
                    leg.mode,
                    leg.topology_ref or "-",
                    leg.evaluator_key,
                    leg.leg_id,
                ),
            )
        )
    )


def _unobserved_bus(*, mapping_allowed: bool) -> BusIntelligenceResult:
    return BusIntelligenceResult(
        enrichment_applied=False,
        candidate_vehicles=(),
        expected_wait_seconds=None,
        p90_wait_seconds=None,
        coverage="UNKNOWN" if mapping_allowed else "UNSUPPORTED",
        confidence_score=0.0,
        confidence_grade="UNKNOWN",
        warnings=(
            ("BUS_DATA_UNAVAILABLE",)
            if mapping_allowed
            else ("BUS_MAPPING_LOW_CONFIDENCE",)
        ),
        model_provenance=(),
    )


def _not_applicable_bus() -> BusIntelligenceResult:
    """No Bus leg means no failed Bus enrichment and no Bus warning."""

    return BusIntelligenceResult(
        enrichment_applied=False,
        candidate_vehicles=(),
        expected_wait_seconds=None,
        p90_wait_seconds=None,
        coverage="UNSUPPORTED",
        confidence_score=0.0,
        confidence_grade="UNKNOWN",
        warnings=(),
        model_provenance=(),
    )


def _last_transit_envelopes(providers, result: ProviderEnvelope) -> tuple[ProviderEnvelope, ...]:
    values = getattr(providers, "last_transit_envelopes", None)
    if values is None:
        values = getattr(providers, "transit_attempts", None)
    if isinstance(values, tuple) and values:
        return values
    return (result,)


_PROVIDER_ENDPOINT_SNAP_TOLERANCE_METERS = 25.0


def _provider_endpoint_matches(
    actual: Coordinate,
    expected: tuple[float, float],
) -> bool:
    """Accept only small Provider road/entrance snapping around a requested point."""

    actual_lat = math.radians(actual.lat)
    expected_lat = math.radians(expected[1])
    delta_lat = expected_lat - actual_lat
    delta_lon = math.radians(expected[0] - actual.lon)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(actual_lat)
        * math.cos(expected_lat)
        * math.sin(delta_lon / 2.0) ** 2
    )
    distance_meters = 6_371_000.0 * 2.0 * math.asin(
        min(1.0, math.sqrt(haversine))
    )
    return distance_meters <= _PROVIDER_ENDPOINT_SNAP_TOLERANCE_METERS


def _canonical_movement_source(
    envelope: ProviderEnvelope,
    expected_mode: str,
    *,
    expected_from: tuple[float, float],
    expected_to: tuple[float, float],
    expected_topology_ref: str | None = None,
    expected_from_ref: str = "origin",
    expected_to_ref: str = "destination",
) -> _CanonicalMovementSource | None:
    if (
        envelope.status is not ProviderStatus.OK
        or not isinstance(envelope.payload, tuple)
        or envelope.normalized_count != len(envelope.payload)
    ):
        return None
    candidates: list[
        tuple[bool, str, str, int, str, _CanonicalMovementSource]
    ] = []
    for itinerary in envelope.payload:
        if not isinstance(itinerary, CanonicalItinerary):
            continue
        itinerary_identity = _canonical_itinerary_identity(itinerary)
        for leg in itinerary.legs:
            if leg.mode.value != expected_mode:
                continue
            if not (
                _provider_endpoint_matches(
                    leg.from_stop.coordinate, expected_from
                )
                and _provider_endpoint_matches(
                    leg.to_stop.coordinate, expected_to
                )
            ):
                continue
            topology_matches = expected_topology_ref is None
            routing_topology = None
            if leg.transit is not None:
                routing_topology, _ = _routing_transit_topology(
                    itinerary_identity,
                    leg,
                    expected_from_ref,
                    expected_to_ref,
                )
            if expected_topology_ref is not None:
                topology_matches = (
                    routing_topology is not None
                    and routing_topology.fingerprint == expected_topology_ref
                )
            candidates.append(
                (
                    topology_matches,
                    itinerary_identity,
                    itinerary.itinerary_id,
                    leg.sequence,
                    leg.leg_id,
                    _CanonicalMovementSource(
                        leg,
                        envelope,
                        itinerary.itinerary_id,
                        (
                            routing_topology.fingerprint
                            if routing_topology is not None
                            else None
                        ),
                    ),
                )
            )
    if candidates:
        if expected_topology_ref is not None:
            matching = [item for item in candidates if item[0]]
            if matching:
                candidates = matching
            elif len(candidates) != 1:
                # A single authoritative movement can refine a coarse topology.
                # Multiple nonmatching choices cannot be selected safely.
                return None
        return min(candidates, key=lambda item: item[1:5])[5]
    return None


def _canonical_movement(
    envelope: ProviderEnvelope,
    expected_mode: str,
    *,
    expected_from: tuple[float, float],
    expected_to: tuple[float, float],
    expected_topology_ref: str | None = None,
    expected_from_ref: str = "origin",
    expected_to_ref: str = "destination",
) -> CanonicalLeg | None:
    """Compatibility wrapper for legacy fan-in code; selection is deterministic."""

    source = _canonical_movement_source(
        envelope,
        expected_mode,
        expected_from=expected_from,
        expected_to=expected_to,
        expected_topology_ref=expected_topology_ref,
        expected_from_ref=expected_from_ref,
        expected_to_ref=expected_to_ref,
    )
    return source.leg if source is not None else None


def _mapping_provider_code(provider: str) -> str:
    try:
        return {
            "SANITIZED_TRANSIT_FIXTURE": "KAKAO_TRANSIT",
            "KAKAO_PUBLIC_TRANSIT": "KAKAO_TRANSIT",
            "TMAP_TRANSIT": "TMAP",
            "ODSAY": "ODSAY",
        }[provider]
    except KeyError as exc:
        raise RoutingUnavailableError("transit provider cannot enter mapping") from exc


class CanonicalFanInOptimizeRouteUseCase:
    def __init__(
        self,
        composition_key: str,
        clock: Clock,
        *,
        dependencies: FanInDependencies,
        persistence: OptimizationResultRepository | None = None,
        provider_operation_cap: int | None = None,
        replay_bundle: tuple[Mapping[str, object], Mapping[str, object], str] | None = None,
    ) -> None:
        if not composition_key.strip():
            raise ValueError("composition key must be nonblank")
        self._composition_key = composition_key
        self._clock = clock
        self._dependencies = dependencies
        self._replay_bundle = replay_bundle
        self._persistence = (
            persistence if persistence is not None else self._dependencies.persistence
        )
        default_cap = BoundedStrategyGenerator().caps.provider_calls
        self._provider_operation_cap = (
            default_cap if provider_operation_cap is None else provider_operation_cap
        )
        if not 1 <= self._provider_operation_cap <= default_cap:
            raise ValueError("provider operation cap must be within the domain cap")
        self._trace: FanInTrace | None = None

    @property
    def trace(self) -> FanInTrace | None:
        return self._trace

    def execute(self, command: OptimizeCommand, context: RequestContext) -> UseCaseResult:
        payload = command.payload
        departure = _aware_timestamp(payload["departureTime"])
        request_evaluated_at = self._clock.now()
        observation_as_of = (
            departure if self._dependencies.fixture_only else request_evaluated_at
        )
        inference_budget = _RequestModelInferenceBudget(context.cancellation)
        origin_raw = payload["origin"]["coordinate"]  # type: ignore[index]
        destination_raw = payload["destination"]["coordinate"]  # type: ignore[index]
        expected = self._replay_bundle
        if expected is not None and not (
            _mapping_coordinates_equal(origin_raw, expected[0])
            and _mapping_coordinates_equal(destination_raw, expected[1])
            and departure == _aware_timestamp(expected[2])
        ):
            raise RoutingUnavailableError("fixture scenario does not match its allowlisted replay request")
        self._check_budget(context, "baseline")
        operation_budget = _ProviderOperationBudget(self._provider_operation_cap)
        transit_cap = self._dependencies.providers.transit_call_cap
        operation_budget.reserve(transit_cap)

        envelope = self._dependencies.providers.transit(
            TransitSearchRequest(
                Coordinate(float(origin_raw["lon"]), float(origin_raw["lat"])),
                Coordinate(float(destination_raw["lon"]), float(destination_raw["lat"])),
                departure,
                max_itineraries=5,
            ),
            deadline=Deadline.after_ms(self._remaining_ms(context, 1_800)),
        )
        actual_transit_calls = self._dependencies.providers.last_transit_attempt_count
        if not 1 <= actual_transit_calls <= transit_cap:
            raise RoutingUnavailableError("transit provider attempt accounting invalid")
        operation_budget.release(transit_cap - actual_transit_calls)
        baseline_attempts = _last_transit_envelopes(
            self._dependencies.providers, envelope
        )
        if envelope.status is not ProviderStatus.OK or not envelope.payload:
            raise RoutingUnavailableError("required canonical transit fixture unavailable")
        if not isinstance(envelope.payload, tuple) or envelope.normalized_count != len(
            envelope.payload
        ):
            raise RoutingUnavailableError("transit normalized count does not match payload")
        returned_itinerary_count = len(envelope.payload)
        canonical_itineraries = _canonicalize_returned_itineraries(
            envelope.payload,
            origin_raw,
            destination_raw,
            max_itineraries=5,
        )
        itinerary = canonical_itineraries[0][1]
        provider_leg = next(
            (
                leg
                for leg in itinerary.legs
                if leg.mode.value in {"BUS", "SUBWAY", "GTX", "TRAIN"}
            ),
            None,
        )
        if provider_leg is None:
            raise RoutingUnavailableError("required canonical transit baseline unavailable")
        canonical_baselines: list[TransitBaseline] = []
        canonical_coordinates: dict[str, tuple[float, float]] = {}
        canonical_sources: dict[
            tuple[str, str, str, str], _CanonicalMovementSource
        ] = {}
        bus_evidences: list[tuple[str, CanonicalTransitEvidence]] = []
        for index, (identity, canonical_itinerary) in enumerate(canonical_itineraries):
            baseline_id = "mapped-public" if index == 0 else f"mapped-public:{identity}"
            baseline, coordinates, sources, evidences = _canonical_itinerary_baseline(
                canonical_itinerary,
                envelope,
                baseline_id=baseline_id,
                reference_namespace=identity,
                bus_intelligence_enabled=(
                    self._dependencies.bus_intelligence_enabled
                ),
            )
            canonical_baselines.append(baseline)
            canonical_coordinates.update(coordinates)
            overlap = set(canonical_sources) & set(sources)
            if overlap:
                raise RoutingUnavailableError("canonical itinerary identity collision")
            canonical_sources.update(sources)
            bus_evidences.extend(evidences)

        constraints = _constraints(payload)
        coarse_input = _coarse_strategy_inputs(
            departure,
            constraints.taxi_budget_krw,
            route_suffix=self._composition_key.lower(),
            main_mode=provider_leg.mode.value,
            canonical_baselines=tuple(canonical_baselines),
        )
        default_caps = CandidateCaps()
        generator = BoundedStrategyGenerator(
            caps=replace(
                default_caps,
                transit_baselines=max(
                    default_caps.transit_baselines,
                    len(coarse_input.transit_baselines),
                ),
            )
        )
        coarse = self._build_complete_strategy_batch(
            generator,
            coarse_input,
            constraints,
            context,
            operation_budget,
        )
        plan = tuple((item.request_key, item.kind.value) for item in coarse.exact_enrichment_plan)

        composition, exact = self._resolve_exactification(
            context,
            envelope,
            baseline_attempts,
            provider_leg,
            tuple(bus_evidences),
            departure,
            observation_as_of,
            origin_raw,
            destination_raw,
            coarse_input,
            coarse,
            constraints,
            operation_budget,
            canonical_coordinates,
            canonical_sources,
            inference_budget,
        )
        if self._dependencies.fixture_only:
            composition = _align_fixture_provenance_clock(
                composition,
                request_evaluated_at,
            )
        if exact.exact_enrichment_plan:
            unresolved = ",".join(
                f"{item.kind.value}:{item.from_ref}>{item.to_ref}"
                for item in exact.exact_enrichment_plan
            )
            raise RoutingUnavailableError(
                f"exact enrichment plan was not fully resolved: {unresolved}"
            )
        evaluator = _RequestScopedLegEvaluator(
            exact.costs(),
            composition.bus_snapshots,
            self._dependencies.eta_predictor,
            self._dependencies.seat_predictor,
            inference_budget,
            self._dependencies.bus_wait,
            observation_as_of,
        )
        self._check_budget(context, "graph-search")
        graph = _canonical_routing_graph(exact.seeds)
        try:
            graph_outcome = RouteOptimizer(evaluator).optimize_graph(
                graph,
                composition.exact_input.origin_ref,
                composition.exact_input.destination_ref,
                departure,
                constraints,
                graph_caps=GraphSearchCaps(
                    max_expansions=default_caps.coarse_combinations,
                    max_labels_per_node=default_caps.coarse_combinations,
                    max_complete_paths=default_caps.coarse_combinations,
                    max_legs=12,
                ),
                pattern_hints=exact.seeds,
                provider_call_count=composition.provider_call_count,
            )
        except (GraphSearchUncertifiedError, OptimalityUncertifiedError) as exc:
            raise RoutingCapacityExceeded(str(exc)) from exc
        self._check_budget(context, "graph-search")
        graph_result = graph_outcome.graph_search
        graph_seeds = graph_result.seeds
        exact_topologies = {
            tuple(leg.leg_id for leg in seed.legs) for seed in exact.seeds
        }
        optimized = graph_outcome.optimization
        composition = replace(
            composition, bus_evaluations=evaluator.evaluations
        )
        response = self._project(payload, composition, exact, optimized)
        persistence_status = self._persist(payload, response, optimized, composition)
        if (
            response["status"] == "COMPLETE"
            and persistence_status != "PERSISTED"
        ):
            response["status"] = "PARTIAL"
        computation = dict(response["computation"])
        cache = dict(computation["cache"])
        cache["optimizationPersistence"] = persistence_status
        computation["cache"] = cache
        response["computation"] = computation
        self._trace = FanInTrace(
            coarse_patterns=composition.coarse_patterns,
            # Exact strategy coverage and graph-feasible output are distinct.
            # Keep the established strategy trace here; graph execution has its
            # own expansion/seed/recombination evidence below.
            exact_patterns=tuple(sorted({item.seed.pattern for item in exact.candidates})),
            exact_plan=plan,
            provider_call_count=composition.provider_call_count,
            rejected_reasons=tuple(
                sorted(
                    {
                        item.reason
                        for item in (
                            *coarse.rejected,
                            *exact.rejected,
                            *optimized.rejected,
                            *graph_result.rejected,
                        )
                    }
                )
            ),
            persistence_status=persistence_status,
            model_inference=inference_budget.trace,
            returned_itinerary_count=returned_itinerary_count,
            admitted_itinerary_count=len(canonical_itineraries),
            deduplicated_itinerary_count=(
                returned_itinerary_count - len(canonical_itineraries)
            ),
            finite_payload_complete=True,
            # Providers expose neither source exhaustion nor a lower bound for
            # unreturned routes. This trace deliberately makes no network-global
            # optimality claim.
            network_global_complete=False,
            graph_expansion_count=graph_result.expansion_count,
            graph_seed_count=len(graph_seeds),
            graph_recombined_count=sum(
                tuple(leg.leg_id for leg in seed.legs) not in exact_topologies
                for seed in graph_seeds
            ),
        )
        return UseCaseResult(
            response=response,
            optional_enrichment_complete=self._optional_enrichment_complete(
                composition, optimized
            ),
            warning_codes=tuple(response["warningCodes"]),
        )

    def _build_complete_strategy_batch(
        self,
        generator: BoundedStrategyGenerator,
        coarse_input: StrategyGenerationInput,
        constraints: RouteConstraints,
        context: RequestContext,
        operation_budget: _ProviderOperationBudget,
    ) -> StrategyGenerationBatch:
        """Exhaust the finite LB-ordered frontier or fail without ranking it."""

        try:
            search_space = generator.build_search_space(coarse_input, constraints)
        except OptimalityUncertifiedError as exc:
            raise RoutingCapacityExceeded(str(exc)) from exc

        frontier = search_space.open_frontier()
        candidates: list[StrategyCandidate] = []
        requests = {}
        costs = {}
        logical_calls = 0
        while not frontier.scope_exhausted:
            self._check_budget(context, "strategy-frontier")
            remaining = self._provider_operation_cap - operation_budget.consumed - logical_calls
            if remaining <= 0:
                raise RoutingCapacityExceeded(
                    "EXACT_PROVIDER_CALL_CAP_UNCERTIFIED"
                )
            try:
                batch = frontier.next_exactification_batch(
                    logical_provider_call_cap=min(
                        search_space.logical_provider_call_cap,
                        remaining,
                    )
                )
            except OptimalityUncertifiedError as exc:
                raise RoutingCapacityExceeded(str(exc)) from exc
            if not batch.candidates:
                raise RoutingCapacityExceeded(
                    "EXACT_FRONTIER_PROGRESS_UNCERTIFIED"
                )
            candidates.extend(batch.candidates)
            logical_calls += batch.logical_provider_calls
            for request in batch.exact_enrichment_plan:
                requests.setdefault(request.request_key, request)
            for key, cost in batch.cost_catalog:
                current = costs.setdefault(key, cost)
                if current != cost:
                    raise RoutingCapacityExceeded(
                        "EXACT_COST_IDENTITY_CONFLICT"
                    )

        exactification_plan = ExactificationPlan(
            candidates=tuple(item.exactification for item in candidates),
            candidate_cap=max(1, len(candidates)),
            logical_provider_call_cap=self._provider_operation_cap,
        )
        return StrategyGenerationBatch(
            candidates=tuple(candidates),
            rejected=search_space.rejected,
            exact_enrichment_plan=tuple(requests.values()),
            cost_catalog=tuple(sorted(costs.items())),
            unique_provider_calls=logical_calls,
            policy_version=search_space.policy_version,
            exactification_plan=exactification_plan,
        )

    def _resolve_exactification(
        self,
        context: RequestContext,
        envelope: ProviderEnvelope,
        baseline_attempts: tuple[ProviderEnvelope, ...],
        provider_leg: CanonicalLeg,
        bus_evidences: tuple[tuple[str, CanonicalTransitEvidence], ...],
        departure: datetime,
        observation_as_of: datetime,
        origin_raw: Mapping[str, object],
        destination_raw: Mapping[str, object],
        coarse_input: StrategyGenerationInput,
        coarse: StrategyGenerationBatch,
        constraints: RouteConstraints,
        operation_budget: _ProviderOperationBudget,
        canonical_coordinates: Mapping[str, tuple[float, float]],
        canonical_sources: Mapping[
            tuple[str, str, str, str], _CanonicalMovementSource
        ],
        inference_budget: _RequestModelInferenceBudget,
    ) -> tuple[_Composition, StrategyGenerationBatch]:
        """Resolve the authoritative candidate/leg dependency plan.

        Provider I/O stays here in the application layer.  The pure plan supplies
        topology and predecessor relations; the final RouteOptimizer still owns
        P50/P90 chronology, feasibility, Pareto and ranking.
        """

        del bus_evidences, constraints
        plan = coarse.exactification_plan
        if plan.logical_provider_calls > plan.logical_provider_call_cap:
            raise RoutingCapacityExceeded("domain exactification call cap invalid")
        candidate_priority = {
            candidate.candidate_key: index
            for index, candidate in enumerate(plan.candidates)
        }

        coordinates = _coordinate_registry(origin_raw, destination_raw)
        coordinates.update(canonical_coordinates)
        providers = self._dependencies.providers
        provider_envelopes: list[ProviderEnvelope] = list(baseline_attempts)
        outcomes: dict[str, _ExactStepOutcome] = {}
        failed_candidates: dict[str, str] = {}
        maximum_depth = max(
            (len(candidate.steps) for candidate in plan.candidates), default=0
        )

        for depth in range(maximum_depth):
            ready: list[tuple[ExactificationStep, datetime, int]] = []
            for candidate in plan.candidates:
                if candidate.candidate_key in failed_candidates or depth >= len(candidate.steps):
                    continue
                step = candidate.steps[depth]
                predecessor_end = None
                if step.predecessor_step_key is not None:
                    predecessor = outcomes.get(step.predecessor_step_key)
                    if predecessor is None or not predecessor.resolved:
                        failed_candidates[candidate.candidate_key] = (
                            predecessor.reason if predecessor is not None else "EXACT_PREDECESSOR_UNRESOLVED"
                        ) or "EXACT_PREDECESSOR_UNRESOLVED"
                        continue
                    predecessor_end = predecessor.end_at_p50
                entry_at = step.ready_at(
                    departure, predecessor_p50_end_at=predecessor_end
                )
                reusable = self._reusable_canonical_step(
                    step,
                    entry_at,
                    departure,
                    canonical_sources,
                )
                units = self._exact_step_reservation_units(
                    step, reusable is not None
                )
                ready.append((step, entry_at, units))

            if not ready:
                continue

            provider_units = sum(units for _, _, units in ready)
            stage_reserved = operation_budget.try_reserve(provider_units)
            if not stage_reserved:
                raise RoutingCapacityExceeded(
                    "provider operation cap exhausted before exactification stage"
                )

            executor = ThreadPoolExecutor(
                max_workers=min(8, len(ready)),
                thread_name_prefix="routing-exact-depth",
            )
            future_items: dict[
                Future[_ExactStepOutcome], tuple[ExactificationStep, datetime, int]
            ] = {}
            try:
                for step, entry_at, units in sorted(
                    ready,
                    key=lambda item: (
                        candidate_priority[item[0].candidate_key],
                        item[0].leg_sequence,
                        item[0].quote_identity(item[1]).quote_key,
                    ),
                ):
                    future = executor.submit(
                        self._execute_exact_step,
                        context,
                        step,
                        entry_at,
                        departure,
                        observation_as_of,
                        coordinates,
                        canonical_sources,
                        units,
                        inference_budget,
                    )
                    future_items[future] = (step, entry_at, units)

                timeout = max(
                    0.0,
                    min(
                        5.4,
                        (context.effective_deadline - self._clock.now()).total_seconds()
                        - 1.1,
                    ),
                )
                done, pending = wait(tuple(future_items), timeout=timeout)
                for future in pending:
                    step, _, units = future_items[future]
                    if future.cancel():
                        operation_budget.release(units)
                    failed_candidates[step.candidate_key] = "EXACT_DEADLINE"

                for future in sorted(
                    done,
                    key=lambda value: (
                        candidate_priority[future_items[value][0].candidate_key],
                        future_items[value][0].leg_sequence,
                    ),
                ):
                    step, entry_at, units = future_items[future]
                    try:
                        outcome = future.result()
                    except Exception:
                        outcome = _ExactStepOutcome(
                            step=step,
                            identity=step.quote_identity(entry_at),
                            provider_departure_at=entry_at,
                            end_at_p50=None,
                            canonical_leg=None,
                            envelope=None,
                            attempts=(),
                            dispatch=None,
                            snapshot=None,
                            reserved_units=units,
                            actual_units=units,
                            reason="EXACT_PROVIDER_FAILURE",
                        )
                    if not 0 <= outcome.actual_units <= units:
                        failed_candidates[step.candidate_key] = "PROVIDER_ATTEMPT_ACCOUNTING"
                        continue
                    operation_budget.release(units - outcome.actual_units)
                    outcomes[step.step_key] = outcome
                    provider_envelopes.extend(outcome.attempts)
                    if not outcome.resolved:
                        failed_candidates[step.candidate_key] = (
                            outcome.reason or "EXACT_UNRESOLVED"
                        )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

        coarse_by_key = {
            candidate.seed.candidate_key: candidate for candidate in coarse.candidates
        }
        selected: list[StrategyCandidate] = []
        rejected: list[StrategyRejection] = []
        costs: dict[str, LegCost] = {}
        leg_envelopes: dict[str, ProviderEnvelope] = {}
        leg_dispatches: dict[str, TaxiDispatchEstimate] = {}
        leg_projections: dict[str, _LegProjection] = {}
        movement_envelopes: dict[tuple[str, str, str], ProviderEnvelope] = {}
        movement_dispatches: dict[
            tuple[str, str, str], TaxiDispatchEstimate
        ] = {}
        snapshots: list[_BusLegSnapshot] = []

        for candidate_plan in plan.candidates:
            source = coarse_by_key[candidate_plan.candidate_key]
            if candidate_plan.candidate_key in failed_candidates:
                rejected.append(
                    StrategyRejection(
                        candidate_plan.candidate_key,
                        failed_candidates[candidate_plan.candidate_key],
                    )
                )
                continue
            exact_legs: list[LegSpec] = []
            exact_p50 = 0
            exact_taxi_upper = 0
            for step, coarse_leg in zip(candidate_plan.steps, source.seed.legs):
                outcome = outcomes.get(step.step_key)
                if outcome is None or not outcome.resolved:
                    rejected.append(
                        StrategyRejection(
                            candidate_plan.candidate_key, "EXACT_UNRESOLVED"
                        )
                    )
                    exact_legs = []
                    break
                assert outcome.canonical_leg is not None
                assert outcome.envelope is not None
                exact_leg, cost = self._exact_leg_and_cost(coarse_leg, outcome)
                exact_legs.append(exact_leg)
                costs[exact_leg.evaluator_key] = cost
                exact_p50 += cost.wait.p50_seconds + cost.travel.p50_seconds
                if exact_leg.mode == "TAXI" and cost.fare is not None:
                    exact_taxi_upper += cost.fare.upper_krw
                leg_envelopes[exact_leg.leg_id] = outcome.envelope
                leg_projections[exact_leg.leg_id] = self._projection_from_leg(
                    outcome.canonical_leg,
                    expected_start=coordinates[exact_leg.from_ref],
                    expected_end=coordinates[exact_leg.to_ref],
                )
                kind = self._enrichment_kind(exact_leg.mode)
                movement_envelopes.setdefault(
                    _movement_key(kind, exact_leg.from_ref, exact_leg.to_ref),
                    outcome.envelope,
                )
                if outcome.dispatch is not None:
                    leg_dispatches[exact_leg.leg_id] = outcome.dispatch
                    movement_dispatches.setdefault(
                        _movement_key(
                            EnrichmentKind.TAXI,
                            exact_leg.from_ref,
                            exact_leg.to_ref,
                        ),
                        outcome.dispatch,
                    )
                if outcome.snapshot is not None:
                    snapshots.append(
                        replace(outcome.snapshot, leg_id=exact_leg.leg_id)
                    )
            if not exact_legs:
                continue
            exact_seed = replace(
                source.seed,
                legs=tuple(exact_legs),
                coarse_p50_seconds=exact_p50,
                coarse_taxi_upper_krw=exact_taxi_upper,
            )
            selected.append(
                StrategyCandidate(exact_seed, (), source.exactification)
            )

        survivor_keys = {item.seed.candidate_key for item in selected}
        exact_plan = ExactificationPlan(
            candidates=tuple(
                item
                for item in plan.candidates
                if item.candidate_key in survivor_keys
            ),
            candidate_cap=plan.candidate_cap,
            logical_provider_call_cap=plan.logical_provider_call_cap,
        )
        exact = StrategyGenerationBatch(
            candidates=tuple(selected),
            rejected=tuple(sorted(rejected, key=lambda item: (item.candidate_key, item.reason))),
            exact_enrichment_plan=(),
            cost_catalog=tuple(sorted(costs.items())),
            unique_provider_calls=operation_budget.consumed,
            policy_version=coarse.policy_version,
            exactification_plan=exact_plan,
        )
        projection = self._projection_catalog(
            provider_leg,
            origin_raw,
            destination_raw,
            {
                self._movement_key_for_leg(step, outcome.canonical_leg): outcome.canonical_leg
                for step in plan.steps
                if (outcome := outcomes.get(step.step_key)) is not None
                and outcome.canonical_leg is not None
            },
        )
        composition = _Composition(
            provider_envelopes=tuple(provider_envelopes),
            baseline_envelope=envelope,
            provider_leg=provider_leg,
            movement_envelopes=tuple(movement_envelopes.items()),
            taxi_dispatches=tuple(movement_dispatches.items()),
            bus_snapshots=tuple(
                sorted(
                    snapshots,
                    key=lambda item: (item.leg_id or "", item.topology_ref),
                )
            ),
            bus_evaluations=(),
            exact_input=coarse_input,
            projection=projection,
            exact_plan=tuple(
                (item.request_key, item.kind.value)
                for item in coarse.exact_enrichment_plan
            ),
            provider_call_count=operation_budget.consumed,
            coarse_patterns=tuple(
                sorted({item.seed.pattern for item in coarse.candidates})
            ),
            rejected_reasons=tuple(
                sorted({item.reason for item in (*coarse.rejected, *rejected)})
            ),
            leg_envelopes=tuple(sorted(leg_envelopes.items())),
            leg_dispatches=tuple(sorted(leg_dispatches.items())),
            leg_projections=tuple(sorted(leg_projections.items())),
        )
        return composition, exact

    @staticmethod
    def _enrichment_kind(mode: str) -> EnrichmentKind:
        if mode == "WALK":
            return EnrichmentKind.WALK
        if mode == "TAXI":
            return EnrichmentKind.TAXI
        return EnrichmentKind.TRANSIT

    @classmethod
    def _movement_key_for_leg(
        cls, step: ExactificationStep, leg: CanonicalLeg
    ) -> tuple[str, str, str]:
        return _movement_key(
            cls._enrichment_kind(leg.mode.value), step.from_ref, step.to_ref
        )

    def _reusable_canonical_step(
        self,
        step: ExactificationStep,
        entry_at: datetime,
        quoted_at: datetime,
        canonical_sources: Mapping[
            tuple[str, str, str, str], _CanonicalMovementSource
        ],
        legacy_envelopes: Mapping[tuple[str, str, str], ProviderEnvelope] | None = None,
    ) -> _CanonicalMovementSource | None:
        del legacy_envelopes
        # Taxi Provider departure is entry plus the separately sourced dispatch
        # wait. The baseline movement catalog has no proof for that post-dispatch
        # request identity, so Taxi is never reusable in the first implementation.
        if step.mode == "TAXI":
            return None
        key = (
            *_movement_key(
                self._enrichment_kind(step.mode), step.from_ref, step.to_ref
            ),
            step.evaluator_key,
        )
        source = canonical_sources.get(key)
        if source is None or source.leg.mode.value != step.mode:
            return None
        if (
            step.mode in {"BUS", "SUBWAY", "GTX", "TRAIN"}
            and step.topology_ref is not None
            and source.routing_topology_ref != step.topology_ref
        ):
            return None
        movement_kind = self._enrichment_kind(step.mode)
        enrichment = getattr(step, "enrichment", None)
        if enrichment is not None and not any(
            request.kind is movement_kind for request in enrichment
        ):
            # An EXACT movement came from the request-scoped atomic itinerary.
            # Reuse its in-vehicle/walk duration at the candidate entry time;
            # Bus waiting is still recomputed below from live/history evidence.
            # Re-running a full journey search for each sliced itinerary leg is
            # neither the same quote nor a useful traffic refresh.
            return source
        # The first movement is the departure-scoped baseline quote and remains
        # reusable at the request departure even when a Provider reports a later
        # scheduled vehicle time.  A later movement belongs to the same atomic
        # Provider itinerary only when candidate chronology reaches that leg's
        # exact expected-start instant.  Re-querying an individual transit leg is
        # not equivalent: journey planners normally return a new access/egress
        # itinerary around that leg.  Without a later-leg timestamp, fail closed.
        if step.leg_sequence == 0:
            if entry_at != quoted_at:
                return None
        else:
            expected_entry_at = source.leg.expected_start_at
            if expected_entry_at is None or entry_at != expected_entry_at:
                return None
        return source

    def _exact_step_reservation_units(
        self, step: ExactificationStep, movement_reused: bool
    ) -> int:
        units = 0
        bus_intelligence_reserved = False
        for request in step.enrichment:
            if request.kind is EnrichmentKind.TRANSIT:
                if not movement_reused:
                    units += self._dependencies.providers.transit_call_cap * request.call_units
            elif request.kind in {EnrichmentKind.WALK, EnrichmentKind.TAXI}:
                if not movement_reused:
                    units += request.call_units
            elif request.kind is EnrichmentKind.BUS_INTELLIGENCE:
                units += request.call_units * 2
                bus_intelligence_reserved = True
        # Exact BUS movements discovered outside the baseline flat enrichment
        # plan still require an arrivals+locations pair after HIGH mapping.
        # Reserve both operations before the worker starts; unused units are
        # released deterministically when mapping is not accepted.
        if (
            step.mode == "BUS"
            and self._dependencies.bus_intelligence_enabled
            and not bus_intelligence_reserved
        ):
            units += 2
        if (
            step.mode == "BUS"
            and self._dependencies.bus_intelligence_enabled
            and self._dependencies.context is not None
        ):
            units += len(self._dependencies.context.enabled_operations)
        return units

    def _optional_provider_start_allowed(self, context: RequestContext) -> bool:
        return (
            context.optional_enrichment_allowed
            and not context.cancellation.is_set()
            and self._clock.now()
            < context.effective_deadline - timedelta(seconds=1.75)
        )

    def _execute_exact_step(
        self,
        context: RequestContext,
        step: ExactificationStep,
        entry_at: datetime,
        journey_departure: datetime,
        observation_as_of: datetime,
        coordinates: Mapping[str, tuple[float, float]],
        canonical_sources: Mapping[
            tuple[str, str, str, str], _CanonicalMovementSource
        ],
        reserved_units: int,
        inference_budget: _RequestModelInferenceBudget,
    ) -> _ExactStepOutcome:
        identity = step.quote_identity(entry_at)
        reusable = self._reusable_canonical_step(
            step,
            entry_at,
            journey_departure,
            canonical_sources,
        )
        provider_departure = entry_at
        dispatch = None
        attempts: list[ProviderEnvelope] = []
        actual_units = 0
        result: ProviderEnvelope | None = None
        canonical_leg: CanonicalLeg | None = None
        source_itinerary_id: str | None = None

        if step.mode == "TAXI":
            request_at_ready = TransitSearchRequest(
                Coordinate(*coordinates[step.from_ref]),
                Coordinate(*coordinates[step.to_ref]),
                entry_at,
                max_itineraries=1,
            )
            if self._dependencies.taxi_dispatch is None:
                return _ExactStepOutcome(
                    step, identity, entry_at, None, None, None, (), None, None,
                    reserved_units, 0, "TAXI_DISPATCH_WAIT_UNKNOWN",
                )
            dispatch = self._dependencies.taxi_dispatch.estimate(
                request_at_ready, evaluated_at=entry_at
            )
            if dispatch is None:
                return _ExactStepOutcome(
                    step, identity, entry_at, None, None, None, (), None, None,
                    reserved_units, 0, "TAXI_DISPATCH_WAIT_UNKNOWN",
                )
            provider_departure = entry_at + timedelta(
                seconds=dispatch.wait.p50_seconds
            )

        if reusable is not None:
            canonical_leg = reusable.leg
            result = reusable.envelope
            source_itinerary_id = reusable.itinerary_id
        else:
            if not self._optional_provider_start_allowed(context):
                return _ExactStepOutcome(
                    step, identity, provider_departure, None, None, None, (),
                    dispatch, None, reserved_units, 0, "EXACT_START_GATE",
                )
            request = TransitSearchRequest(
                Coordinate(*coordinates[step.from_ref]),
                Coordinate(*coordinates[step.to_ref]),
                provider_departure,
                max_itineraries=1,
            )
            deadline_ms = 1_200 if step.mode in {"BUS", "SUBWAY", "GTX", "TRAIN"} else 900
            deadline = Deadline.after_ms(self._remaining_ms(context, deadline_ms))
            if step.mode == "WALK":
                result = self._dependencies.providers.walk(request, deadline=deadline)
                attempts.append(result)
                actual_units += 1
            elif step.mode == "TAXI":
                result = self._dependencies.providers.taxi(request, deadline=deadline)
                attempts.append(result)
                actual_units += 1
            else:
                result = self._dependencies.providers.transit(request, deadline=deadline)
                transit_attempts = _last_transit_envelopes(
                    self._dependencies.providers, result
                )
                attempts.extend(transit_attempts)
                actual_units += len(transit_attempts)
            selected_source = _canonical_movement_source(
                result,
                step.mode,
                expected_from=coordinates[step.from_ref],
                expected_to=coordinates[step.to_ref],
                expected_topology_ref=step.topology_ref,
                expected_from_ref=step.from_ref,
                expected_to_ref=step.to_ref,
            )
            if selected_source is not None:
                canonical_leg = selected_source.leg
                source_itinerary_id = selected_source.itinerary_id

        if result is None or canonical_leg is None:
            return _ExactStepOutcome(
                step, identity, provider_departure, None, None, result,
                tuple(attempts), dispatch, None, reserved_units, actual_units,
                "EXACT_CANONICAL_UNRESOLVED",
            )
        if canonical_leg.mode.value in {"BUS", "SUBWAY", "GTX", "TRAIN"} and (
            source_itinerary_id is None
        ):
            return _ExactStepOutcome(
                step,
                identity,
                provider_departure,
                None,
                canonical_leg,
                result,
                tuple(attempts),
                dispatch,
                None,
                reserved_units,
                actual_units,
                "EXACT_ITINERARY_PROVENANCE_UNRESOLVED",
            )

        snapshot = None
        bus_wait = 0
        bus_wait_observed = False
        if (
            step.mode == "BUS"
            and canonical_leg.transit is not None
            and isinstance(result.payload, tuple)
            and result.payload
        ):
            provider_topology = _provider_transit_topology(
                canonical_leg, step.from_ref, step.to_ref
            )
            topology_ref = (
                provider_topology.fingerprint
                if provider_topology is not None
                else step.topology_ref
            )
            if topology_ref is None:
                return _ExactStepOutcome(
                    step, identity, provider_departure, None, canonical_leg, result,
                    tuple(attempts), dispatch, None, reserved_units, actual_units,
                    "EXACT_TOPOLOGY_UNRESOLVED",
                )
            evidence = CanonicalTransitEvidence(
                _mapping_provider_code(result.provider),
                result.fingerprint,
                source_itinerary_id,
                canonical_leg,
            )
            mapping, target = self._resolve_mapping(evidence, entry_at)
            query = None
            arrivals = None
            locations = None
            weather = None
            traffic = None
            eta_feature_context = None
            seat_risk_feature_context = None
            service_type = _service_type(
                getattr(target, "route_type", None) if target is not None else None
            )
            if (
                mapping is not None
                and mapping.allows_bus_intelligence
                and target is not None
                and service_type in {"GENERAL", "SEATED"}
                and self._optional_provider_start_allowed(context)
            ):
                query = BusObservationQuery(
                    target.route_id,
                    target.boarding.external_id or "UNAVAILABLE",
                    observation_as_of,
                )
                group = self._fetch_bus_optional_group(
                    context,
                    self._dependencies.providers,
                    self._dependencies.context,
                    query,
                    target,
                    canonical_leg,
                    service_type,
                )
                arrivals = group.arrivals
                locations = group.locations
                weather = group.weather
                traffic = group.traffic
                eta_feature_context = group.eta_feature_context
                seat_risk_feature_context = group.seat_risk_feature_context
                actual_units += group.started_units
                attempts.extend(group.envelopes)
            snapshot = _BusLegSnapshot(
                topology_ref,
                evidence,
                mapping,
                target,
                query,
                arrivals,
                locations,
                service_type,
                step.leg_id,
                weather,
                traffic,
                eta_feature_context,
                seat_risk_feature_context,
                group.required_operations if query is not None else frozenset(),
                group.context_complete if query is not None else True,
            )
            if (
                snapshot.mapping_allows_intelligence
                and query is not None
                and arrivals is not None
                and locations is not None
            ):
                bus = _bus_result(
                    mapping,
                    target,
                    entry_at,
                    True,
                    arrivals,
                    locations,
                    self._dependencies.eta_predictor,
                    self._dependencies.seat_predictor,
                    query,
                    service_type=service_type,
                    evaluated_at=observation_as_of,
                    eta_feature_context=eta_feature_context,
                    seat_risk_feature_context=seat_risk_feature_context,
                    inference_budget=inference_budget,
                )
                live_wait = _usable_bus_wait(bus)
                if live_wait is not None:
                    bus_wait = live_wait.p50_seconds
                    bus_wait_observed = True

            if not bus_wait_observed and self._dependencies.bus_wait is not None:
                fallback_wait = self._dependencies.bus_wait.estimate(
                    canonical_leg,
                    arrival_at=entry_at,
                    evaluated_at=observation_as_of,
                )
                if fallback_wait is not None:
                    bus_wait = fallback_wait.wait.p50_seconds
                    bus_wait_observed = True
                    snapshot = replace(snapshot, fallback_wait=fallback_wait)

        if (
            step.mode == "BUS"
            and canonical_leg.expected_start_at is None
            and not bus_wait_observed
        ):
            return _ExactStepOutcome(
                step,
                identity,
                provider_departure,
                None,
                canonical_leg,
                result,
                tuple(attempts),
                dispatch,
                snapshot,
                reserved_units,
                actual_units,
                "BUS_WAIT_UNKNOWN",
            )

        start_at = provider_departure
        if canonical_leg.expected_start_at is not None:
            if canonical_leg.expected_start_at < entry_at:
                return _ExactStepOutcome(
                    step, identity, provider_departure, None, canonical_leg, result,
                    tuple(attempts), dispatch, snapshot, reserved_units, actual_units,
                    "TRANSFER_INFEASIBLE",
                )
            start_at = max(start_at, canonical_leg.expected_start_at)
        if step.mode == "BUS":
            start_at = max(start_at, entry_at + timedelta(seconds=bus_wait))
        end_at = start_at + timedelta(
            seconds=canonical_leg.duration.p50_seconds
        )
        return _ExactStepOutcome(
            step,
            identity,
            provider_departure,
            end_at,
            canonical_leg,
            result,
            tuple(attempts),
            dispatch,
            snapshot,
            reserved_units,
            actual_units,
            source_itinerary_id=source_itinerary_id,
        )

    @staticmethod
    def _exact_leg_and_cost(
        coarse_leg: LegSpec, outcome: _ExactStepOutcome
    ) -> tuple[LegSpec, LegCost]:
        assert outcome.canonical_leg is not None
        provider_leg = outcome.canonical_leg
        topology_ref = coarse_leg.topology_ref
        if provider_leg.transit is not None:
            descriptor = provider_leg.transit
            if (
                descriptor.external_route_id is not None
                and descriptor.direction is not None
                and descriptor.boarding_sequence is not None
                and descriptor.alighting_sequence is not None
            ):
                topology_ref = CanonicalTransitTopology(
                    descriptor.external_route_id,
                    descriptor.direction,
                    coarse_leg.from_ref,
                    coarse_leg.to_ref,
                    descriptor.boarding_sequence,
                    descriptor.alighting_sequence,
                    descriptor.branch_id,
                ).fingerprint
        evaluator_key = (
            f"exact:{outcome.identity.quote_key}:"
            f"{outcome.step.candidate_key}:{outcome.step.leg_sequence}"
        )
        warning_codes: tuple[str, ...] = ()
        reliability_score = 0.9
        if outcome.dispatch is not None:
            wait_cost = outcome.dispatch.wait
            warning_codes = ("TAXI_DISPATCH_WAIT_ESTIMATED",)
        elif provider_leg.mode.value == "BUS":
            fallback_wait = (
                outcome.snapshot.fallback_wait
                if outcome.snapshot is not None
                else None
            )
            if fallback_wait is not None:
                wait_cost = fallback_wait.wait
                if fallback_wait.origin == "HISTORICAL_PROXY":
                    warning_codes = ("HISTORICAL_PROXY_USED",)
                    reliability_score = 0.72
                elif fallback_wait.origin == "MODEL_PREDICTED":
                    reliability_score = 0.82
            elif provider_leg.expected_start_at is None:
                wait_cost = TimeEstimate(0, 0)
                warning_codes = ("BUS_WAIT_UNKNOWN",)
            else:
                provider_wait = max(
                    0,
                    int(
                        (
                            provider_leg.expected_start_at
                            - outcome.provider_departure_at
                        ).total_seconds()
                    ),
                )
                wait_cost = TimeEstimate(provider_wait, provider_wait)
        else:
            wait_cost = TimeEstimate(0, 0)
        exact_leg = replace(
            coarse_leg,
            evaluator_key=evaluator_key,
            distance_meters=provider_leg.distance_meters,
            scheduled_departure_at=(
                provider_leg.expected_start_at
                if provider_leg.mode.value in {"SUBWAY", "GTX", "TRAIN"}
                else None
            ),
            bus_wait=None,
            topology_ref=topology_ref,
        )
        return exact_leg, LegCost(
            wait=wait_cost,
            travel=TimeEstimate(
                provider_leg.duration.p50_seconds,
                provider_leg.duration.p90_seconds,
            ),
            fare=MoneyRange(
                provider_leg.fare.expected_krw,
                provider_leg.fare.lower_krw,
                provider_leg.fare.upper_krw,
            ),
            reliability_score=reliability_score,
            warning_codes=warning_codes,
        )

    @staticmethod
    def _projection_from_leg(
        leg: CanonicalLeg,
        *,
        expected_start: tuple[float, float],
        expected_end: tuple[float, float],
    ) -> _LegProjection:
        """Project Provider evidence onto the admitted canonical graph edge.

        Road and station Providers commonly snap request coordinates by a few
        metres.  The exactifier already verifies that snap against the bounded
        tolerance; the response must still expose the canonical graph nodes so
        adjacent legs and the requested route endpoints remain exactly joined.
        Provider geometry is retained as evidence of the travelled path.
        """

        descriptor = leg.transit
        transit = (
            {
                "routeLabel": descriptor.route_label,
                "externalRouteId": descriptor.external_route_id,
                "routeType": descriptor.route_type,
                "direction": descriptor.direction,
            }
            if descriptor is not None
            else None
        )
        start = expected_start
        end = expected_end
        geometry = tuple((item.lon, item.lat) for item in leg.geometry)
        return _LegProjection(
            leg.from_stop.name,
            leg.to_stop.name,
            start,
            end,
            leg.from_stop.external_id,
            leg.to_stop.external_id,
            transit,
            geometry or (start, end),
        )

    def _resolve_exact(
        self,
        context: RequestContext,
        envelope: ProviderEnvelope,
        baseline_attempts: tuple[ProviderEnvelope, ...],
        provider_leg: CanonicalLeg,
        bus_evidences: tuple[tuple[str, CanonicalTransitEvidence], ...],
        departure: datetime,
        origin_raw: Mapping[str, object],
        destination_raw: Mapping[str, object],
        coarse_input: StrategyGenerationInput,
        coarse,
        constraints: RouteConstraints,
        operation_budget: _ProviderOperationBudget,
        canonical_coordinates: Mapping[str, tuple[float, float]],
        canonical_resolved: Mapping[tuple[str, str, str], CanonicalLeg],
        canonical_envelopes: Mapping[
            tuple[str, str, str], ProviderEnvelope
        ],
    ) -> _Composition:
        provider_envelopes: list[ProviderEnvelope] = list(baseline_attempts)
        seen: set[str] = set()
        evidence_by_topology = dict(bus_evidences)
        all_bus_evidences = list(bus_evidences)
        snapshots: dict[str, _BusLegSnapshot] = {}
        resolved: dict[tuple[str, str, str], CanonicalLeg] = dict(
            canonical_resolved
        )
        resolved_envelopes: dict[
            tuple[str, str, str], ProviderEnvelope
        ] = dict(canonical_envelopes)
        taxi_dispatches: dict[
            tuple[str, str, str], TaxiDispatchEstimate
        ] = {}
        providers = self._dependencies.providers
        coordinates = _coordinate_registry(origin_raw, destination_raw)
        coordinates.update(canonical_coordinates)
        transit_modes = {
            (movement.from_ref, movement.to_ref): movement.mode
            for baseline in coarse_input.transit_baselines
            for movement in baseline.legs
            if isinstance(movement, TransitLegInput)
        }
        transit_modes.update(
            {
                (item.upstream_leg.from_ref, item.upstream_leg.to_ref): item.upstream_leg.mode
                for item in coarse_input.upstream_hubs
            }
        )
        main_key = _movement_key(EnrichmentKind.TRANSIT, "origin", "destination")
        if _canonical_movement(
            envelope,
            provider_leg.mode.value,
            expected_from=coordinates["origin"],
            expected_to=coordinates["destination"],
        ) is not None:
            resolved[main_key] = provider_leg
            resolved_envelopes[main_key] = envelope
        if not context.optional_enrichment_allowed:
            for topology_ref, evidence in bus_evidences:
                mapping, target = self._resolve_mapping(evidence, departure)
                snapshots[topology_ref] = _BusLegSnapshot(
                    topology_ref,
                    evidence,
                    mapping,
                    target,
                    None,
                    None,
                    None,
                    _service_type(
                        getattr(target, "route_type", None)
                        if target is not None else None
                    ),
                )
            minimal_exact = _exact_strategy_input(
                coarse_input,
                resolved,
                taxi_dispatches=taxi_dispatches,
                mapping_ready=True,
            )
            return _Composition(
                provider_envelopes=tuple(provider_envelopes),
                baseline_envelope=envelope,
                provider_leg=provider_leg,
                movement_envelopes=tuple(resolved_envelopes.items()),
                taxi_dispatches=tuple(taxi_dispatches.items()),
                bus_snapshots=tuple(snapshots.values()),
                bus_evaluations=(),
                exact_input=minimal_exact,
                projection=self._projection_catalog(
                    provider_leg, origin_raw, destination_raw, resolved
                ),
                exact_plan=tuple(
                    (item.request_key, item.kind.value)
                    for item in coarse.exact_enrichment_plan
                ),
                provider_call_count=operation_budget.consumed,
                coarse_patterns=tuple(
                    sorted({item.seed.pattern for item in coarse.candidates})
                ),
                rejected_reasons=tuple(
                    sorted({item.reason for item in coarse.rejected})
                ),
            )
        for request in coarse.exact_enrichment_plan:
            if request.request_key in seen:
                continue
            # Reserve the fully expanded operation set before the first adapter
            # call so BUS cannot partially consume arrivals then exceed on
            # locations.
            operation_budget.reserve(_expanded_provider_operation_units(request))
            seen.add(request.request_key)
            self._check_budget(context, request.kind.value)
            from_coordinate = coordinates[request.from_ref]
            to_coordinate = coordinates[request.to_ref]
            provider_request = TransitSearchRequest(
                Coordinate(*from_coordinate),
                Coordinate(*to_coordinate),
                departure,
                max_itineraries=1,
            )
            if request.kind is EnrichmentKind.WALK:
                result = providers.walk(
                    provider_request,
                    deadline=Deadline.after_ms(self._remaining_ms(context, 900)),
                )
                provider_envelopes.append(result)
                value = _canonical_movement(
                    result,
                    "WALK",
                    expected_from=from_coordinate,
                    expected_to=to_coordinate,
                )
                if value is not None:
                    key = _movement_key(request.kind, request.from_ref, request.to_ref)
                    resolved[key] = value
                    resolved_envelopes[key] = result
            elif request.kind is EnrichmentKind.TAXI:
                result = providers.taxi(
                    provider_request,
                    deadline=Deadline.after_ms(self._remaining_ms(context, 900)),
                )
                provider_envelopes.append(result)
                value = _canonical_movement(
                    result,
                    "TAXI",
                    expected_from=from_coordinate,
                    expected_to=to_coordinate,
                )
                if value is not None:
                    key = _movement_key(request.kind, request.from_ref, request.to_ref)
                    resolved[key] = value
                    resolved_envelopes[key] = result
                    if self._dependencies.taxi_dispatch is not None:
                        estimate = self._dependencies.taxi_dispatch.estimate(
                            provider_request, evaluated_at=departure
                        )
                        if estimate is not None:
                            taxi_dispatches[key] = estimate
            elif request.kind is EnrichmentKind.TRANSIT:
                key = _movement_key(request.kind, request.from_ref, request.to_ref)
                if key in resolved:
                    continue
                transit_cap = providers.transit_call_cap * request.call_units
                operation_budget.reserve(transit_cap)
                result = providers.transit(
                    provider_request,
                    deadline=Deadline.after_ms(self._remaining_ms(context, 1_200)),
                )
                actual_transit_calls = (
                    providers.last_transit_attempt_count * request.call_units
                )
                if not request.call_units <= actual_transit_calls <= transit_cap:
                    raise RoutingUnavailableError(
                        "transit provider attempt accounting invalid"
                    )
                operation_budget.release(transit_cap - actual_transit_calls)
                provider_envelopes.extend(_last_transit_envelopes(providers, result))
                expected_mode = transit_modes.get((request.from_ref, request.to_ref))
                source = (
                    _canonical_movement_source(
                        result,
                        expected_mode,
                        expected_from=from_coordinate,
                        expected_to=to_coordinate,
                        expected_from_ref=request.from_ref,
                        expected_to_ref=request.to_ref,
                    )
                    if expected_mode is not None else None
                )
                if source is not None:
                    value = source.leg
                    resolved[key] = value
                    resolved_envelopes[key] = result
                    if value.mode.value == "BUS" and value.transit is not None:
                        descriptor = value.transit
                        if (
                            descriptor.external_route_id is not None
                            and descriptor.direction is not None
                            and descriptor.boarding_sequence is not None
                            and descriptor.alighting_sequence is not None
                            and isinstance(result.payload, tuple)
                            and result.payload
                        ):
                            topology_ref = CanonicalTransitTopology(
                                descriptor.external_route_id,
                                descriptor.direction,
                                request.from_ref,
                                request.to_ref,
                                descriptor.boarding_sequence,
                                descriptor.alighting_sequence,
                                descriptor.branch_id,
                            ).fingerprint
                            evidence = CanonicalTransitEvidence(
                                _mapping_provider_code(result.provider),
                                result.fingerprint,
                                source.itinerary_id,
                                value,
                            )
                            evidence_by_topology[topology_ref] = evidence
                            all_bus_evidences.append((topology_ref, evidence))
            elif request.kind is EnrichmentKind.MAPPING:
                topology_ref = request.request_key.removeprefix("mapping:")
                evidence = evidence_by_topology.get(topology_ref)
                if evidence is not None and topology_ref not in snapshots:
                    mapping, target = self._resolve_mapping(evidence, departure)
                    snapshots[topology_ref] = _BusLegSnapshot(
                        topology_ref,
                        evidence,
                        mapping,
                        target,
                        None,
                        None,
                        None,
                        _service_type(
                            getattr(target, "route_type", None)
                            if target is not None else None
                        ),
                    )
            elif request.kind is EnrichmentKind.BUS_INTELLIGENCE:
                topology_ref = request.request_key.removeprefix("bus:")
                evidence = evidence_by_topology.get(topology_ref)
                if evidence is None:
                    continue
                snapshot = snapshots.get(topology_ref)
                if snapshot is None:
                    mapping, target = self._resolve_mapping(evidence, departure)
                    snapshot = _BusLegSnapshot(
                        topology_ref,
                        evidence,
                        mapping,
                        target,
                        None,
                        None,
                        None,
                        _service_type(
                            getattr(target, "route_type", None)
                            if target is not None else None
                        ),
                    )
                mapping, target = snapshot.mapping, snapshot.target
                if mapping is None or not mapping.allows_bus_intelligence or target is None:
                    snapshots[topology_ref] = snapshot
                    continue
                query = BusObservationQuery(
                    route_id=target.route_id,
                    boarding_station_id=(target.boarding.external_id or "UNAVAILABLE"),
                    evaluated_at=departure,
                )
                arrivals, locations = self._fetch_bus_observations(
                    context, providers, query
                )
                provider_envelopes.extend(
                    item for item in (arrivals, locations) if item is not None
                )
                snapshots[topology_ref] = replace(
                    snapshot,
                    query=query,
                    arrivals=arrivals,
                    locations=locations,
                )
        for topology_ref, evidence in all_bus_evidences:
            if topology_ref not in snapshots:
                mapping, target = self._resolve_mapping(evidence, departure)
                snapshots[topology_ref] = _BusLegSnapshot(
                    topology_ref,
                    evidence,
                    mapping,
                    target,
                    None,
                    None,
                    None,
                    _service_type(
                        getattr(target, "route_type", None)
                        if target is not None else None
                    ),
                )
            snapshot = snapshots[topology_ref]
            if (
                context.optional_enrichment_allowed
                and snapshot.mapping_allows_intelligence
                and snapshot.query is None
            ):
                target = snapshot.target
                query = BusObservationQuery(
                    route_id=target.route_id,
                    boarding_station_id=(
                        target.boarding.external_id or "UNAVAILABLE"
                    ),
                    evaluated_at=departure,
                )
                arrivals, locations = self._fetch_bus_observations(
                    context, providers, query
                )
                provider_envelopes.extend(
                    item for item in (arrivals, locations) if item is not None
                )
                snapshots[topology_ref] = replace(
                    snapshot,
                    query=query,
                    arrivals=arrivals,
                    locations=locations,
                )
        exact_input = _exact_strategy_input(
            coarse_input,
            resolved,
            taxi_dispatches=taxi_dispatches,
            mapping_ready=True,
        )
        projection = self._projection_catalog(
            provider_leg,
            origin_raw,
            destination_raw,
            resolved,
        )
        return _Composition(
            provider_envelopes=tuple(provider_envelopes),
            baseline_envelope=envelope,
            provider_leg=provider_leg,
            movement_envelopes=tuple(resolved_envelopes.items()),
            taxi_dispatches=tuple(taxi_dispatches.items()),
            bus_snapshots=tuple(
                snapshots[key] for key in sorted(snapshots)
            ),
            bus_evaluations=(),
            exact_input=exact_input,
            projection=projection,
            exact_plan=tuple((item.request_key, item.kind.value) for item in coarse.exact_enrichment_plan),
            provider_call_count=operation_budget.consumed,
            coarse_patterns=tuple(sorted({item.seed.pattern for item in coarse.candidates})),
            rejected_reasons=tuple(sorted({item.reason for item in coarse.rejected})),
        )

    def _fetch_bus_observations(self, context, providers, query):
        """Fetch independent GBIS operations concurrently within one stage."""

        self._check_budget(context, "BUS_INTELLIGENCE")
        timeout_ms = self._remaining_ms(context, 700)
        deadline = Deadline.after_ms(timeout_ms)
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="routing-gbis")
        try:
            futures = (
                executor.submit(providers.arrivals, query, deadline=deadline),
                executor.submit(providers.locations, query, deadline=deadline),
            )
            done, pending = wait(futures, timeout=timeout_ms / 1000.0)
            if pending:
                for future in pending:
                    future.cancel()
                return None, None
            values = []
            for future in futures:
                try:
                    values.append(future.result())
                except Exception:
                    # Both operations are optional.  A failed half cannot be
                    # joined and therefore remains explicitly unobserved.
                    values.append(None)
            return tuple(values)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _fetch_bus_optional_group(
        self,
        context: RequestContext,
        providers: FanInProviderPorts,
        context_port: BusContextProviderPort | None,
        query: BusObservationQuery,
        target,
        canonical_leg: CanonicalLeg,
        service_type: str | None,
    ) -> _BusOptionalGroup:
        """Run one mapped BUS optional group with deterministic settlement.

        The caller reserved the entire expanded group before this worker began.
        Query construction is fail-soft and skipped operations consume no actual
        units; every submitted operation consumes exactly one unit even when its
        adapter returns an error envelope or raises.
        """

        required_operations = (
            context_port.enabled_operations if context_port is not None else frozenset()
        )
        if not self._optional_provider_start_allowed(context):
            return _BusOptionalGroup(
                required_operations=required_operations,
                context_complete=not required_operations,
            )
        self._check_budget(context, "BUS_INTELLIGENCE")
        jobs: list[tuple[str, Callable[[Deadline], ProviderEnvelope]]] = [
            ("arrivals", lambda deadline: providers.arrivals(query, deadline=deadline)),
            ("locations", lambda deadline: providers.locations(query, deadline=deadline)),
        ]
        if context_port is not None:
            boarding = getattr(getattr(target, "boarding", None), "coordinate", None)
            if "weather_context" in context_port.enabled_operations and boarding is not None:
                try:
                    weather_query = KmaWeatherQuery.from_coordinate(
                        Coordinate(boarding.lon, boarding.lat), query.evaluated_at
                    )
                except (TypeError, ValueError, AttributeError):
                    weather_query = None
                if weather_query is not None:
                    jobs.append(
                        (
                            "weather",
                            lambda deadline, value=weather_query: context_port.weather(
                                value, deadline=deadline
                            ),
                        )
                    )
            if "traffic_context" in context_port.enabled_operations:
                traffic_query = self._traffic_context_query(
                    target, canonical_leg, query.evaluated_at
                )
                if traffic_query is not None:
                    jobs.append(
                        (
                            "traffic",
                            lambda deadline, value=traffic_query: context_port.traffic(
                                value, deadline=deadline
                            ),
                        )
                    )

        timeout_ms = self._remaining_ms(context, 700)
        deadline = Deadline.after_ms(timeout_ms)
        executor = ThreadPoolExecutor(
            max_workers=min(4, len(jobs)), thread_name_prefix="routing-bus-optional"
        )
        futures: dict[Future[ProviderEnvelope], str] = {}
        values: dict[str, ProviderEnvelope | None] = {}
        try:
            # The whole fully-reserved group made one start decision above.
            # Submission itself is non-blocking, so no adapter can delay a later
            # sibling until after the optional-start cutoff.
            for name, call in jobs:
                futures[executor.submit(call, deadline)] = name
            done, pending = wait(tuple(futures), timeout=timeout_ms / 1000.0)
            for future in pending:
                future.cancel()
            for future in done:
                name = futures[future]
                try:
                    values[name] = future.result()
                except Exception:
                    values[name] = None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        weather = self._weather_feature(values.get("weather"), query.evaluated_at)
        traffic = self._traffic_feature(values.get("traffic"), query.evaluated_at)
        eta_context = (
            EtaFeatureContext(weather=weather, traffic=traffic)
            if weather is not None or traffic is not None
            else None
        )
        seat_context = (
            SeatRiskFeatureContext(weather=weather, traffic=traffic)
            if service_type == "SEATED" and (weather is not None or traffic is not None)
            else None
        )
        resolved_eta = eta_context.as_of(query.evaluated_at) if eta_context else None
        context_complete = (
            ("weather_context" not in required_operations)
            or (resolved_eta is not None and resolved_eta.weather is not None)
        ) and (
            ("traffic_context" not in required_operations)
            or (resolved_eta is not None and resolved_eta.traffic is not None)
        )
        return _BusOptionalGroup(
            arrivals=values.get("arrivals"),
            locations=values.get("locations"),
            weather=values.get("weather"),
            traffic=values.get("traffic"),
            eta_feature_context=eta_context,
            seat_risk_feature_context=seat_context,
            required_operations=required_operations,
            context_complete=context_complete,
            started_units=len(futures),
        )

    @staticmethod
    def _traffic_context_query(
        target, canonical_leg: CanonicalLeg, observed_at: datetime
    ) -> GitsTrafficCorridorQuery | None:
        identity = getattr(target, "gits_road_link_identity", None)
        if (
            not isinstance(identity, GitsRoadLinkIdentity)
            or not identity.validity.contains(observed_at)
        ):
            # A bounding box alone is not evidence that a returned road link is
            # relevant to this mapped BUS corridor.
            return None
        relevant = identity.link_external_ids
        geometry = tuple(getattr(target, "geometry", ()) or ())
        if not geometry:
            boarding = getattr(getattr(target, "boarding", None), "coordinate", None)
            alighting = getattr(getattr(target, "alighting", None), "coordinate", None)
            if boarding is not None and alighting is not None:
                geometry = (boarding, alighting)
        if not geometry:
            geometry = tuple(canonical_leg.geometry)
        try:
            corridor = tuple(Coordinate(item.lon, item.lat) for item in geometry)
            return GitsTrafficCorridorQuery.from_corridor(
                corridor,
                observed_at,
                relevant_link_external_ids=tuple(relevant),
                maximum_links=min(512, max(1, len(relevant))),
            )
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _weather_feature(
        envelope: ProviderEnvelope | None, evaluated_at: datetime
    ) -> WeatherFeatureContext | None:
        if (
            envelope is None
            or envelope.status is not ProviderStatus.OK
            or not isinstance(envelope.payload, tuple)
            or len(envelope.payload) != 1
            or not isinstance(envelope.payload[0], WeatherContext)
        ):
            return None
        value = envelope.payload[0]
        # Future weather remains typed so Bus Core records FUTURE_EXCLUDED.
        return WeatherFeatureContext(
            observed_at=value.observed_at,
            schema_version=WEATHER_CONTEXT_SCHEMA_VERSION,
            temperature_c=value.temperature_c,
            precipitation_mm=value.precipitation_mm,
        )

    @staticmethod
    def _traffic_feature(
        envelope: ProviderEnvelope | None, evaluated_at: datetime
    ) -> TrafficFeatureContext | None:
        if (
            envelope is None
            or envelope.status is not ProviderStatus.OK
            or not isinstance(envelope.payload, tuple)
        ):
            return None
        # The adapter has already constrained link IDs to the exact query. Future
        # rows are excluded before aggregation so they cannot skew a valid as-of
        # summary.  Oldest observation time is the conservative freshness bound.
        typed = tuple(
            item
            for item in envelope.payload
            if isinstance(item, TrafficLinkContext)
        )
        values = tuple(item for item in typed if item.observed_at <= evaluated_at)
        if not values:
            if not typed:
                return None
            # Preserve an all-future typed aggregate so Bus Core can emit its
            # stable FUTURE_EXCLUDED missing reason. Mixed snapshots below use
            # only eligible rows and never blend future values.
            values = typed
        return TrafficFeatureContext(
            observed_at=min(item.observed_at for item in values),
            schema_version=TRAFFIC_CONTEXT_SCHEMA_VERSION,
            speed_kph=sum(item.speed_kph for item in values) / len(values),
            travel_time_seconds=sum(item.travel_time_seconds for item in values),
            incident_present=None,
        )

    def _projection_catalog(
        self, provider_leg, origin_raw, destination_raw, resolved=None
    ):
        origin = (float(origin_raw["lon"]), float(origin_raw["lat"]))
        destination = (float(destination_raw["lon"]), float(destination_raw["lat"]))
        points = {
            "origin": origin,
            "upstream-stop": _coordinates_between(origin, destination, 0.12),
            "hub-a": _coordinates_between(origin, destination, 0.35),
            "bridge-left": _coordinates_between(origin, destination, 0.42),
            "bridge-right": _coordinates_between(origin, destination, 0.58),
            "hub-b": _coordinates_between(origin, destination, 0.78),
            "destination": destination,
        }
        values: dict[tuple[str, str, str], _LegProjection] = {}
        movements = (
            ("BUS", "origin", "destination", "Transit", f"canonical-transit-{self._composition_key.lower()}"),
            ("SUBWAY", "origin", "hub-a", "Subway Access", f"line-a-{self._composition_key.lower()}"),
            ("SUBWAY", "hub-a", "hub-b", "Subway", f"line-s-{self._composition_key.lower()}"),
            ("WALK", "hub-b", "destination", None, None),
            ("BUS", "origin", "bridge-left", "Bridge Bus", f"route-in-{self._composition_key.lower()}"),
            ("SUBWAY", "bridge-right", "destination", "Bridge Subway", f"route-out-{self._composition_key.lower()}"),
            ("BUS", "upstream-stop", "destination", "Transit", f"canonical-transit-{self._composition_key.lower()}"),
        )
        for mode, start, end, label, route in movements:
            transit = None if label is None else {
                "routeLabel": label,
                "externalRouteId": route,
                "routeType": None,
                "direction": "OUTBOUND",
            }
            values[(mode, start, end)] = _LegProjection(
                name_from=start,
                name_to=end,
                from_coordinate=points[start],
                to_coordinate=points[end],
                provider_from_id=(provider_leg.from_stop.external_id if (mode, start, end) == ("BUS", "origin", "destination") else f"fixture-{start}"),
                provider_to_id=(provider_leg.to_stop.external_id if (mode, start, end) == ("BUS", "origin", "destination") else f"fixture-{end}"),
                transit=transit,
                geometry=(points[start], points[end]),
            )
        taxi_pairs = (
            ("origin", "hub-a"),
            ("hub-b", "destination"),
            ("origin", "upstream-stop"),
            ("bridge-left", "bridge-right"),
            ("origin", "destination"),
        )
        for start, end in taxi_pairs:
            values[("TAXI", start, end)] = _LegProjection(
                start, end, points[start], points[end], None, None, None, (points[start], points[end])
            )
        for (_, start, end), leg in (resolved or {}).items():
            points.setdefault(
                start,
                (leg.from_stop.coordinate.lon, leg.from_stop.coordinate.lat),
            )
            points.setdefault(
                end,
                (leg.to_stop.coordinate.lon, leg.to_stop.coordinate.lat),
            )
            descriptor = leg.transit
            transit = (
                {
                    "routeLabel": descriptor.route_label,
                    "externalRouteId": descriptor.external_route_id,
                    "routeType": descriptor.route_type,
                    "direction": descriptor.direction,
                }
                if descriptor is not None else None
            )
            geometry = tuple((item.lon, item.lat) for item in leg.geometry)
            values[(leg.mode.value, start, end)] = _LegProjection(
                name_from=leg.from_stop.name,
                name_to=leg.to_stop.name,
                from_coordinate=points[start],
                to_coordinate=points[end],
                provider_from_id=leg.from_stop.external_id,
                provider_to_id=leg.to_stop.external_id,
                transit=transit,
                geometry=geometry or (points[start], points[end]),
            )
        return values

    def _project(self, payload, composition, exact, optimized):
        now = self._clock.now().astimezone(timezone.utc)
        mapping_versions = {
            item.mapping.selected.mapping_version
            for item in composition.bus_snapshots
            if item.mapping_allows_intelligence
        }
        mapping_version = (
            next(iter(mapping_versions)) if len(mapping_versions) == 1 else None
        )
        provider_status = self._provider_status(composition)
        if not optimized.routes:
            return {
                "contractVersion": "1.0",
                "requestId": str(payload["requestId"]),
                "status": "NO_FEASIBLE_ROUTE",
                "generatedAt": now.isoformat(),
                "expiresAt": (now + timedelta(seconds=120)).isoformat(),
                "computation": self._computation(
                    optimized, exact, mapping_version, composition.provider_call_count
                ),
                "recommendations": {"fastest": None, "stable": None, "efficient": None, "publicTransitOnly": None},
                "routes": [],
                "paretoRouteIds": [],
                "providerStatus": provider_status,
                "modelVersions": [],
                "warningCodes": [],
            }
        pareto = frozenset(optimized.pareto_route_ids)
        routes = [self._route(item, composition, pareto, now) for item in optimized.routes]
        requested = set(payload["requestedRecommendations"])
        recommendations = optimized.recommendations
        warnings = {
            code
            for item in composition.bus_evaluations
            for code in item.result.warnings
        }
        exact_patterns = {item.seed.pattern for item in exact.candidates}
        if any(
            item.status is not ProviderStatus.OK
            for item in _unique_provider_envelopes(composition)
        ):
            warnings.add("PROVIDER_PARTIAL_FAILURE")
        warnings = sorted(warnings)
        return {
            "contractVersion": "1.0",
            "requestId": str(payload["requestId"]),
            "status": (
                "COMPLETE"
                if self._composition_is_verified(composition, optimized)
                else "PARTIAL"
            ),
            "generatedAt": now.isoformat(),
            "expiresAt": (now + timedelta(seconds=120)).isoformat(),
            "computation": self._computation(
                optimized, exact, mapping_version, composition.provider_call_count
            ),
            "recommendations": {
                "fastest": recommendations.fastest if "FASTEST" in requested else None,
                "stable": recommendations.stable if "STABLE" in requested else None,
                "efficient": recommendations.efficient if "EFFICIENT" in requested else None,
                "publicTransitOnly": recommendations.public_transit_only if "PUBLIC_TRANSIT_ONLY" in requested else None,
            },
            "routes": routes,
            "paretoRouteIds": list(optimized.pareto_route_ids),
            "providerStatus": provider_status,
            "modelVersions": self._model_versions(composition.bus_evaluations),
            "warningCodes": warnings,
        }

    @staticmethod
    def _computation(optimized, exact, mapping_version, provider_call_count):
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
            "cache": {
                "fixture": False,
                "strategyPolicyVersion": exact.policy_version,
                "exactEnrichmentResolved": True,
                "providerCallCount": provider_call_count,
            },
        }

    def _route(self, candidate, composition, pareto, now):
        provenance = self._provenance(composition, now)
        legs = [self._leg(value, composition, now) for value in candidate.legs]
        bus_results = [
            value.result
            for leg in candidate.legs
            if (value := self._bus_evaluation(composition, leg)) is not None
        ]
        bus_applied = any(item.enrichment_applied for item in bus_results)
        return {
            "routeId": candidate.route_id,
            "pattern": candidate.pattern,
            "totalDuration": self._time(candidate.total_duration.p50_seconds, candidate.total_duration.p90_seconds, candidate.reliability_score, "MODEL_PREDICTED" if bus_applied else "PROVIDER_ESTIMATE"),
            "arrivalAt": {"p50": candidate.arrival_at_p50.isoformat(), "p90": candidate.arrival_at_p90.isoformat()},
            "taxiCost": self._money(candidate.taxi_cost, "PROVIDER_ESTIMATE"),
            "totalFareExpected": candidate.total_fare_expected_krw,
            "walkSeconds": candidate.walk_seconds,
            "transferCount": candidate.transfer_count,
            "taxiLegCount": candidate.taxi_leg_count,
            "reliabilityScore": candidate.reliability_score,
            "dominance": {"onParetoFrontier": candidate.route_id in pareto},
            "legs": legs,
            "reasonCodes": list(candidate.reason_codes),
            "warningCodes": sorted(
                set(candidate.warning_codes)
                | {code for item in bus_results for code in item.warnings}
            ),
            "provenance": provenance,
        }

    def _leg(self, evaluated, composition, now):
        projection = dict(composition.leg_projections).get(evaluated.leg_id)
        if projection is None:
            projection = composition.projection[
                (evaluated.mode, evaluated.from_ref, evaluated.to_ref)
            ]
        evaluation = self._bus_evaluation(composition, evaluated)
        snapshot = (
            self._bus_snapshot(
                composition, evaluation.topology_ref, evaluated.leg_id
            )
            if evaluation is not None else None
        )
        is_mapped_bus = snapshot is not None and snapshot.mapping_allows_intelligence
        target = snapshot.target if is_mapped_bus else None
        bus = (
            self._bus_projection(snapshot, evaluation)
            if snapshot is not None and evaluation is not None else None
        )
        return {
            "legId": evaluated.leg_id,
            "sequence": evaluated.sequence,
            "mode": evaluated.mode,
            "from": {
                "name": projection.name_from,
                "coordinate": {"lon": projection.from_coordinate[0], "lat": projection.from_coordinate[1]},
                "canonicalStopId": target.boarding.external_id if target is not None else None,
                "providerStopId": projection.provider_from_id,
            },
            "to": {
                "name": projection.name_to,
                "coordinate": {"lon": projection.to_coordinate[0], "lat": projection.to_coordinate[1]},
                "canonicalStopId": target.alighting.external_id if target is not None else None,
                "providerStopId": projection.provider_to_id,
            },
            "expectedStartAt": (evaluated.end_at_p50 - timedelta(seconds=evaluated.duration.p50_seconds)).isoformat(),
            "expectedEndAt": evaluated.end_at_p50.isoformat(),
            "duration": self._time(evaluated.duration.p50_seconds, evaluated.duration.p90_seconds, evaluated.reliability_score, "MODEL_PREDICTED" if bus is not None else "PROVIDER_ESTIMATE"),
            "distanceMeters": evaluated.distance_meters,
            "fare": self._money(evaluated.fare, "PROVIDER_ESTIMATE"),
            "geometry": {"encoding": "GEOJSON", "value": {"type": "LineString", "coordinates": [[p[0], p[1]] for p in projection.geometry]}},
            "transit": projection.transit,
            "busIntelligence": bus,
            "provenance": self._leg_provenance(
                evaluated, composition, snapshot, evaluation, now
            ),
        }

    def _bus_projection(self, snapshot, evaluation):
        bus = evaluation.result
        mapping = snapshot.mapping
        if (
            mapping is None
            or not mapping.allows_bus_intelligence
            or not bus.enrichment_applied
            or not isinstance(bus.expected_wait_seconds, int)
            or not isinstance(bus.p90_wait_seconds, int)
            or mapping.selected is None
        ):
            return None
        target = snapshot.target
        return {
            "mapping": {
                "gbisRouteId": target.route_id,
                "boardingStationId": target.boarding.external_id,
                "alightingStationId": target.alighting.external_id,
                "score": mapping.selected.score,
                "grade": str(mapping.selected.grade),
                "mappingVersion": mapping.selected.mapping_version,
            },
            "userArrivalTime": evaluation.user_arrival_at.isoformat(),
            "candidateVehicles": [
                {
                    "vehicleRef": item.vehicle_ref,
                    "eta": self._time(item.wait_p50_seconds, item.wait_p90_seconds, item.eta.confidence, {"OFFICIAL": "PROVIDER_ESTIMATE", "POSITION_MODEL": "MODEL_PREDICTED", "HISTORICAL": "HISTORICAL_PROXY"}[item.eta.source]),
                    "remainSeatObserved": item.remain_seat_observed,
                    "seatRiskAtBoarding": ({
                        "noSeatProbability": item.seat_risk_at_boarding.no_seat_probability,
                        "lowSeat2Probability": item.seat_risk_at_boarding.low_seat2_probability,
                        "lowSeat5Probability": item.seat_risk_at_boarding.low_seat5_probability,
                        "modelVersion": item.seat_risk_at_boarding.model_version,
                    } if item.seat_risk_at_boarding is not None else None),
                    "boardabilityProxy": item.boardability_proxy,
                }
                for item in bus.candidate_vehicles
                if item.eta.p50_arrival_at > evaluation.user_arrival_at
            ],
            "expectedWaitSeconds": bus.expected_wait_seconds,
            "p90WaitSeconds": bus.p90_wait_seconds,
            "coverage": bus.coverage,
            "warnings": list(bus.warnings),
        }

    @staticmethod
    def _bus_snapshot(composition, topology_ref, leg_id=None):
        return next(
            (
                item
                for item in composition.bus_snapshots
                if item.topology_ref == topology_ref
                and (leg_id is None or item.leg_id in {None, leg_id})
            ),
            None,
        )

    @staticmethod
    def _bus_evaluation(composition, evaluated):
        return next(
            (
                item
                for item in composition.bus_evaluations
                if item.leg_id == evaluated.leg_id
                and item.user_arrival_at == evaluated.ready_at_p50
            ),
            None,
        )

    def _optional_enrichment_complete(self, composition, optimized) -> bool:
        bus_legs = [
            leg
            for candidate in optimized.routes
            for leg in candidate.legs
            if leg.mode == "BUS"
        ]
        if not bus_legs:
            return True
        for leg in bus_legs:
            evaluation = self._bus_evaluation(composition, leg)
            if evaluation is None or not evaluation.result.enrichment_applied:
                return False
            snapshot = self._bus_snapshot(
                composition, evaluation.topology_ref, leg.leg_id
            )
            if snapshot is None or snapshot.service_type not in {"GENERAL", "SEATED"}:
                return False
            if snapshot.context_required_operations and not snapshot.context_complete:
                return False
            if {
                "BUS_DATA_UNAVAILABLE",
                "ETA_MODEL_FALLBACK",
                "HISTORICAL_PROXY_USED",
                "DATA_STALE",
            } & set(evaluation.result.warnings):
                return False
            if snapshot.service_type == "SEATED" and any(
                item.seat_risk_at_boarding is None
                for item in evaluation.result.candidate_vehicles
            ):
                return False
        return True

    def _composition_is_verified(self, composition, optimized) -> bool:
        if self._dependencies.fixture_only:
            return False
        if not self._optional_enrichment_complete(composition, optimized):
            return False
        if any(
            item.status is not ProviderStatus.OK
            or "FIXTURE" in item.provider.upper()
            or item.schema_version is None
            for item in _unique_provider_envelopes(composition)
        ):
            return False
        return all(
            provenance.readiness in {"ACTIVE", "PRODUCTION_APPROVED", "VERIFIED"}
            for evaluation in composition.bus_evaluations
            if evaluation.result.enrichment_applied
            for provenance in evaluation.result.model_provenance
        )

    def _leg_provenance(
        self, evaluated, composition, snapshot, evaluation, now
    ):
        kind = (
            EnrichmentKind.TAXI
            if evaluated.mode == "TAXI"
            else EnrichmentKind.WALK
            if evaluated.mode == "WALK"
            else EnrichmentKind.TRANSIT
        )
        envelope = dict(composition.leg_envelopes).get(
            evaluated.leg_id
        ) or dict(composition.movement_envelopes).get(
            _movement_key(kind, evaluated.from_ref, evaluated.to_ref)
        )
        values = []
        if envelope is not None:
            values.append(
                {
                    "provider": (
                        f"FIXTURE::{envelope.provider}/{envelope.operation}"
                        if self._dependencies.fixture_only
                        else f"{envelope.provider}/{envelope.operation}"
                    ),
                    "origin": "PROVIDER_ESTIMATE",
                    "observedAt": (
                        envelope.observed_at.isoformat()
                        if envelope.observed_at else None
                    ),
                    "receivedAt": envelope.received_at.isoformat(),
                    "ageSeconds": None,
                    "confidence": self._confidence(0.0),
                    "fallbackLevel": 0,
                }
            )
        if evaluated.mode == "TAXI":
            dispatch = dict(composition.leg_dispatches).get(
                evaluated.leg_id
            ) or dict(composition.taxi_dispatches).get(
                _movement_key(
                    EnrichmentKind.TAXI,
                    evaluated.from_ref,
                    evaluated.to_ref,
                )
            )
            if dispatch is not None:
                values.append(
                    {
                        "provider": f"TAXI_DISPATCH/{dispatch.source}/{dispatch.version}",
                        "origin": dispatch.origin,
                        "observedAt": None,
                        "receivedAt": now.isoformat(),
                        "ageSeconds": None,
                        "confidence": self._confidence(0.0),
                        "fallbackLevel": 1,
                    }
                )
        if snapshot is not None and snapshot.mapping_allows_intelligence:
            for bus_envelope in (
                snapshot.arrivals,
                snapshot.locations,
                snapshot.weather,
                snapshot.traffic,
            ):
                if bus_envelope is None:
                    continue
                values.append(
                    {
                        "provider": (
                            f"FIXTURE::{bus_envelope.provider}/{bus_envelope.operation}"
                            if self._dependencies.fixture_only
                            else f"{bus_envelope.provider}/{bus_envelope.operation}"
                        ),
                        "origin": "PROVIDER_ESTIMATE",
                        "observedAt": (
                            bus_envelope.observed_at.isoformat()
                            if bus_envelope.observed_at else None
                        ),
                        "receivedAt": bus_envelope.received_at.isoformat(),
                        "ageSeconds": None,
                        "confidence": self._confidence(0.0),
                        "fallbackLevel": 0,
                    }
                )
            selected = snapshot.mapping.selected
            values.append(
                {
                    "provider": f"TRANSPORT_MAPPING/{selected.mapping_version}",
                    "origin": "UNKNOWN",
                    "observedAt": None,
                    "receivedAt": now.isoformat(),
                    "ageSeconds": None,
                    "confidence": {
                        "score": selected.score,
                        "grade": str(selected.grade),
                    },
                    "fallbackLevel": 0,
                }
            )
        if evaluation is not None:
            values.extend(
                {
                    "provider": (
                        f"{item.purpose}_FIXTURE/{item.version}"
                        if self._dependencies.fixture_only
                        else f"{item.purpose}/{item.version}"
                    ),
                    "origin": item.origin,
                    "observedAt": None,
                    "receivedAt": now.isoformat(),
                    "ageSeconds": None,
                    "confidence": self._confidence(
                        evaluation.result.confidence_score
                    ),
                    "fallbackLevel": 1,
                }
                for item in evaluation.result.model_provenance
            )
        return values

    def _provider_status(self, composition):
        actual = _unique_provider_envelopes(composition)
        projected = (
            sorted(actual, key=_provider_envelope_projection_key)
            if self._dependencies.fixture_only
            else actual
        )
        statuses = [
            {
                "provider": (
                    f"FIXTURE::{item.provider}"
                    if self._dependencies.fixture_only
                    and item.provider != "SANITIZED_TRANSIT_FIXTURE"
                    else item.provider
                ),
                "operation": item.operation,
                "status": item.status.value,
                "latencyMs": item.latency_ms,
                "cache": item.cache_hit,
                "messageCode": item.message_code,
            }
            for item in projected
        ]
        if self._dependencies.fixture_only:
            # Sanitized fixture execution never promotes a live capability.
            statuses.extend(
                {
                    "provider": item.provider,
                    "operation": item.operation,
                    "status": "DISABLED",
                    "latencyMs": 0,
                    "cache": False,
                    "messageCode": None,
                }
                for item in foundation_capability_registry().all()
            )
        return statuses

    @staticmethod
    def _model_versions(evaluations):
        values = {
            (item.purpose, item.version)
            for evaluation in evaluations
            if evaluation.result.enrichment_applied
            for item in evaluation.result.model_provenance
            if item.purpose in {"BUS_ETA", "SEAT_RISK"}
        }
        return [{"purpose": purpose, "version": version} for purpose, version in sorted(values)]

    @staticmethod
    def _confidence(score):
        grade = "HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.55 else "LOW" if score > 0 else "UNKNOWN"
        return {"score": round(score, 6), "grade": grade}

    @classmethod
    def _time(cls, p50, p90, confidence, origin):
        return {"p50Seconds": p50, "p90Seconds": p90, "lowerSeconds": None, "upperSeconds": None, "confidence": cls._confidence(confidence), "origin": origin}

    @staticmethod
    def _money(value, origin):
        return {"currency": "KRW", "expected": value.expected_krw, "lower": value.lower_krw, "upper": value.upper_krw, "origin": origin}

    def _provenance(self, composition, now):
        result = [{
            "provider": composition.baseline_envelope.provider,
            "origin": "PROVIDER_ESTIMATE",
            "observedAt": composition.baseline_envelope.observed_at.isoformat() if composition.baseline_envelope.observed_at else None,
            "receivedAt": composition.baseline_envelope.received_at.isoformat(),
            "ageSeconds": 0 if composition.baseline_envelope.observed_at else None,
            "confidence": self._confidence(0.0),
            "fallbackLevel": 0,
        }]
        for snapshot in composition.bus_snapshots:
            if snapshot.mapping is None or snapshot.mapping.selected is None:
                continue
            selected = snapshot.mapping.selected
            result.append({
                "provider": f"TRANSPORT_MAPPING/{selected.mapping_version}",
                "origin": "UNKNOWN",
                "observedAt": None,
                "receivedAt": now.isoformat(),
                "ageSeconds": None,
                "confidence": {"score": selected.score, "grade": str(selected.grade)},
                "fallbackLevel": 0,
            })
        actual_without_selected: list[ProviderEnvelope] = []
        skipped_selected = False
        actual = _unique_provider_envelopes(composition)
        projected = (
            sorted(actual, key=_provider_envelope_projection_key)
            if self._dependencies.fixture_only
            else actual
        )
        for item in projected:
            if not skipped_selected and item is composition.baseline_envelope:
                skipped_selected = True
                continue
            actual_without_selected.append(item)
        result.extend({
            "provider": (
                f"FIXTURE::{item.provider}/{item.operation}"
                if self._dependencies.fixture_only
                else f"{item.provider}/{item.operation}"
            ),
            "origin": "PROVIDER_ESTIMATE",
            "observedAt": item.observed_at.isoformat() if item.observed_at else None,
            "receivedAt": item.received_at.isoformat(),
            "ageSeconds": None,
            "confidence": self._confidence(0.0),
            "fallbackLevel": 1,
        } for item in actual_without_selected)
        result.extend({
            "provider": (
                f"{item.purpose}_FIXTURE/{item.version}"
                if self._dependencies.fixture_only
                else f"{item.purpose}/{item.version}"
            ),
            "origin": item.origin,
            "observedAt": None,
            "receivedAt": now.isoformat(),
            "ageSeconds": None,
            "confidence": self._confidence(evaluation.result.confidence_score),
            "fallbackLevel": 1,
        } for evaluation in composition.bus_evaluations
          for item in evaluation.result.model_provenance)
        return result

    def _persist(self, payload, response, optimized, composition):
        if self._persistence is None:
            return "NOT_CONFIGURED"
        fingerprint = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        try:
            origin = payload["origin"]["coordinate"]
            destination = payload["destination"]["coordinate"]
            now = self._clock.now().astimezone(timezone.utc)
            routes_by_id = {item["routeId"]: item for item in response["routes"]}
            def uuid_or_none(value):
                try:
                    return UUID(str(value)) if value else None
                except (TypeError, ValueError, AttributeError):
                    return None

            def leg_response(route_key, sequence):
                return routes_by_id[route_key]["legs"][sequence]

            def geometry_wkt(value):
                geometry = value.get("geometry")
                if not isinstance(geometry, Mapping):
                    return None
                body = geometry.get("value")
                if not isinstance(body, Mapping) or body.get("type") != "LineString":
                    return None
                coordinates = body.get("coordinates")
                if not isinstance(coordinates, list) or len(coordinates) < 2:
                    return None
                return "LINESTRING(" + ",".join(
                    f"{float(point[0])} {float(point[1])}"
                    for point in coordinates
                    if isinstance(point, list) and len(point) == 2
                ) + ")"

            provider_evidence = tuple(
                {
                    "provider": item.provider,
                    "operation": item.operation,
                    "fingerprint": item.fingerprint,
                    "schemaVersion": item.schema_version,
                    "status": item.status.value,
                }
                for item in _unique_provider_envelopes(composition)
            )
            movement_envelopes = dict(composition.movement_envelopes)
            leg_envelopes = dict(composition.leg_envelopes)
            leg_dispatches = dict(composition.leg_dispatches)

            def envelope_evidence(item):
                return {
                    "provider": item.provider,
                    "operation": item.operation,
                    "fingerprint": item.fingerprint,
                    "schemaVersion": item.schema_version,
                    "status": item.status.value,
                }

            def canonical_refs(leg):
                evaluation = self._bus_evaluation(composition, leg)
                snapshot = (
                    self._bus_snapshot(
                        composition, evaluation.topology_ref, leg.leg_id
                    )
                    if evaluation is not None else None
                )
                if snapshot is None or not snapshot.mapping_allows_intelligence:
                    return None, None, None
                target = snapshot.target
                return (
                    uuid_or_none(target.route_id),
                    uuid_or_none(target.boarding.external_id),
                    uuid_or_none(target.alighting.external_id),
                )

            def entity_mapping_uuid(leg):
                evaluation = self._bus_evaluation(composition, leg)
                snapshot = (
                    self._bus_snapshot(
                        composition, evaluation.topology_ref, leg.leg_id
                    )
                    if evaluation is not None else None
                )
                if snapshot is None or not snapshot.mapping_allows_intelligence:
                    return None
                value = getattr(
                    snapshot.mapping, "selected_entity_mapping_id", None
                )
                return uuid_or_none(value)

            def leg_model_versions(leg):
                evaluation = self._bus_evaluation(composition, leg)
                if evaluation is None:
                    return {}
                return {
                    item.purpose: item.version
                    for item in evaluation.result.model_provenance
                }

            def persisted_leg_provenance(leg):
                kind = (
                    EnrichmentKind.TAXI
                    if leg.mode == "TAXI"
                    else EnrichmentKind.WALK
                    if leg.mode == "WALK"
                    else EnrichmentKind.TRANSIT
                )
                envelope = leg_envelopes.get(leg.leg_id) or movement_envelopes.get(
                    _movement_key(kind, leg.from_ref, leg.to_ref)
                )
                values = [envelope_evidence(envelope)] if envelope is not None else []
                if leg.mode == "TAXI":
                    dispatch = leg_dispatches.get(leg.leg_id) or dict(
                        composition.taxi_dispatches
                    ).get(
                        _movement_key(
                            EnrichmentKind.TAXI,
                            leg.from_ref,
                            leg.to_ref,
                        )
                    )
                    if dispatch is not None:
                        values.append(
                            {
                                "kind": "TAXI_DISPATCH",
                                "source": dispatch.source,
                                "version": dispatch.version,
                                "origin": dispatch.origin,
                                "p50Seconds": dispatch.wait.p50_seconds,
                                "p90Seconds": dispatch.wait.p90_seconds,
                            }
                        )
                evaluation = self._bus_evaluation(composition, leg)
                snapshot = (
                    self._bus_snapshot(
                        composition, evaluation.topology_ref, leg.leg_id
                    )
                    if evaluation is not None else None
                )
                if snapshot is not None and snapshot.mapping_allows_intelligence:
                    mapping = snapshot.mapping
                    values.extend(
                        envelope_evidence(item)
                        for item in (
                            snapshot.arrivals,
                            snapshot.locations,
                            snapshot.weather,
                            snapshot.traffic,
                        )
                        if item is not None
                    )
                    values.append(
                        {
                            "kind": "MAPPING",
                            "version": mapping.selected.mapping_version,
                            "score": mapping.selected.score,
                            "grade": str(mapping.selected.grade),
                        }
                    )
                    values.extend(
                        {
                            "kind": "MODEL",
                            "purpose": item.purpose,
                            "version": item.version,
                            "readiness": item.readiness,
                        }
                        for item in evaluation.result.model_provenance
                    )
                return tuple(values)

            self._persistence.persist(OptimizationResultRecord(
                run=OptimizationRunRecord(
                    request_id=str(payload["requestId"]),
                    request_fingerprint=fingerprint,
                    origin_wkt=f"POINT({float(origin['lon'])} {float(origin['lat'])})",
                    destination_wkt=f"POINT({float(destination['lon'])} {float(destination['lat'])})",
                    departure_time=_aware_timestamp(payload["departureTime"]),
                    constraints=dict(payload["constraints"]),
                    status=str(response["status"]),
                    ranking_policy_version=optimized.ranking_policy_version,
                    duration_ms=None,
                    provider_summary={
                        "statuses": response["providerStatus"],
                        "envelopes": provider_evidence,
                    },
                    created_at=now,
                    expires_at=now + timedelta(seconds=120),
                ),
                candidates=tuple(OptimizationCandidateRecord(
                    route_key=item.route_id,
                    pattern=item.pattern,
                    p50_seconds=item.total_duration.p50_seconds,
                    p90_seconds=item.total_duration.p90_seconds,
                    taxi_cost_expected=item.taxi_cost.expected_krw,
                    taxi_cost_upper=item.taxi_cost.upper_krw,
                    total_fare_expected=item.total_fare_expected_krw,
                    walk_seconds=item.walk_seconds,
                    transfer_count=item.transfer_count,
                    reliability_score=Decimal(str(item.reliability_score)),
                    pareto=item.route_id in optimized.pareto_route_ids,
                    reason_codes=item.reason_codes,
                    warning_codes=item.warning_codes,
                ) for item in optimized.routes),
                legs=tuple(OptimizationLegRecord(
                    route_key=candidate.route_id,
                    sequence=leg.sequence,
                    mode=leg.mode,
                    expected_start_at=leg.start_at_p50,
                    expected_end_at=leg.end_at_p50,
                    p50_seconds=leg.duration.p50_seconds,
                    p90_seconds=leg.duration.p90_seconds,
                    fare_expected=leg.fare.expected_krw,
                    provenance=persisted_leg_provenance(leg),
                    transport_route_id=canonical_refs(leg)[0],
                    from_stop_id=canonical_refs(leg)[1],
                    to_stop_id=canonical_refs(leg)[2],
                    geometry_wkt=geometry_wkt(
                        leg_response(candidate.route_id, leg.sequence)
                    ),
                ) for candidate in optimized.routes for leg in candidate.legs),
                bus_enrichments=tuple(
                    OptimizationBusLegEnrichmentRecord(
                        route_key=candidate.route_id,
                        leg_sequence=leg.sequence,
                        entity_mapping_id=entity_mapping_uuid(leg),
                        expected_wait_seconds=bus["expectedWaitSeconds"],
                        p90_wait_seconds=bus["p90WaitSeconds"],
                        boardability_proxy=(
                            Decimal(str(bus["candidateVehicles"][0]["boardabilityProxy"]))
                            if bus["candidateVehicles"]
                            and bus["candidateVehicles"][0]["boardabilityProxy"] is not None
                            else None
                        ),
                        no_seat_probability=(
                            Decimal(str(bus["candidateVehicles"][0]["seatRiskAtBoarding"]["noSeatProbability"]))
                            if bus["candidateVehicles"]
                            and bus["candidateVehicles"][0]["seatRiskAtBoarding"] is not None
                            else None
                        ),
                        coverage=bus["coverage"],
                        eta_model_version=leg_model_versions(leg).get("BUS_ETA"),
                        seat_model_version=leg_model_versions(leg).get("SEAT_RISK"),
                        candidate_vehicles=tuple(bus["candidateVehicles"]),
                    )
                    for candidate in optimized.routes
                    for leg in candidate.legs
                    for bus in (leg_response(candidate.route_id, leg.sequence)["busIntelligence"],)
                    if bus is not None
                ),
                transfer_evaluations=tuple(
                    OptimizationTransferEvaluationRecord(
                        route_key=candidate.route_id,
                        leg_sequence=leg.sequence,
                        available_seconds=(
                            required + leg.transfer_margin.p50_seconds
                        ),
                        required_seconds=required,
                        margin_p50_seconds=leg.transfer_margin.p50_seconds,
                        margin_p90_seconds=leg.transfer_margin.p90_seconds,
                        success_proxy=None,
                        reason_codes=leg.warning_codes,
                    )
                    for candidate in optimized.routes
                    for leg in candidate.legs
                    if leg.transfer_margin is not None
                    for required in (
                        int(
                            (
                                leg.ready_at_p50
                                - (
                                    candidate.departure_at
                                    if leg.sequence == 0
                                    else candidate.legs[leg.sequence - 1].end_at_p50
                                )
                            ).total_seconds()
                        ),
                    )
                ),
            ))
        except Exception:
            return "FAILED"
        return "PERSISTED"

    def _remaining_ms(self, context, cap):
        return max(1, min(cap, int((context.effective_deadline - self._clock.now()).total_seconds() * 1000)))

    def _resolve_mapping(self, evidence, evaluated_at):
        if evidence is None:
            return None, None
        if _provider_transit_topology(
            evidence.leg, "mapping-board", "mapping-alight"
        ) is None:
            return _unavailable_mapping(evidence.leg), None
        try:
            mapping, target = self._dependencies.mapping(evidence, evaluated_at)
        except Exception:
            return _unavailable_mapping(evidence.leg), None
        if not mapping.allows_bus_intelligence:
            return mapping, None
        if target is None:
            return _unavailable_mapping(evidence.leg), None
        return mapping, target

    def _check_budget(self, context, stage):
        if context.cancellation.is_set() or self._clock.now() >= context.effective_deadline:
            raise RoutingDeadlineExceeded(f"routing stage budget exhausted: {stage}")


class SevenPatternFixtureOptimizeRouteUseCase(CanonicalFanInOptimizeRouteUseCase):
    """Closed replay wrapper around the generic canonical fan-in."""

    def __init__(
        self,
        scenario: IntegratedFixtureScenario,
        clock: Clock,
        *,
        dependencies: FanInDependencies | None = None,
        persistence: OptimizationResultRepository | None = None,
        provider_operation_cap: int | None = None,
    ) -> None:
        super().__init__(
            scenario.scenario_id,
            clock,
            dependencies=dependencies or fixture_fan_in_dependencies(scenario),
            persistence=persistence,
            provider_operation_cap=provider_operation_cap,
            replay_bundle=_REPLAY_REQUEST_BUNDLES.get(scenario.scenario_id),
        )
