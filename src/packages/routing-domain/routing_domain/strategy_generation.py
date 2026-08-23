"""Bounded, provider-independent multimodal strategy generation.

The values in this module are canonical optimizer inputs.  They deliberately do
not model any provider response shape.  A composition layer may normalize
provider results into these immutable values, execute the returned exact
enrichment plan, and then pass the resulting ``CandidateSeed`` objects to the
time-dependent optimizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from hashlib import sha256
from typing import Iterable, TypeAlias

from .candidate_generation import BoundedCandidateGenerator
from .models import (
    BusWaitContribution,
    CandidateSeed,
    LegCost,
    LegSpec,
    MoneyRange,
    RouteConstraints,
    TimeEstimate,
    TransferRequirement,
    TRANSIT_MODES,
)
from .policy import CandidateCaps


class QuoteReadiness(StrEnum):
    COARSE = "COARSE"
    EXACT = "EXACT"


class EnrichmentKind(StrEnum):
    TRANSIT = "TRANSIT"
    WALK = "WALK"
    TAXI = "TAXI"
    MAPPING = "MAPPING"
    BUS_INTELLIGENCE = "BUS_INTELLIGENCE"


class EntryTimeBasis(StrEnum):
    REQUEST_DEPARTURE = "REQUEST_DEPARTURE"
    PREDECESSOR_P50_END = "PREDECESSOR_P50_END"


@dataclass(frozen=True, slots=True)
class CanonicalTransitTopology:
    route_ref: str
    direction: str
    board_stop_ref: str
    alight_stop_ref: str
    board_sequence: int
    alight_sequence: int
    branch_ref: str | None = None

    def __post_init__(self) -> None:
        values = (
            self.route_ref,
            self.direction,
            self.board_stop_ref,
            self.alight_stop_ref,
        )
        if any(not value.strip() for value in values):
            raise ValueError("transit topology references must be nonblank")
        if self.board_stop_ref == self.alight_stop_ref:
            raise ValueError("transit topology endpoints must be distinct")
        if self.board_sequence < 0 or self.alight_sequence <= self.board_sequence:
            raise ValueError("transit topology sequence must move forward")
        if self.branch_ref is not None and not self.branch_ref.strip():
            raise ValueError("branch_ref must be nonblank when supplied")

    @property
    def fingerprint(self) -> str:
        branch = self.branch_ref or "-"
        return (
            f"{self.route_ref}:{self.direction}:{branch}:"
            f"{self.board_stop_ref}@{self.board_sequence}>"
            f"{self.alight_stop_ref}@{self.alight_sequence}"
        )


@dataclass(frozen=True, slots=True)
class TransitLegInput:
    leg_id: str
    mode: str
    topology: CanonicalTransitTopology
    evaluator_key: str
    duration: TimeEstimate
    fare: MoneyRange = field(default_factory=MoneyRange.zero)
    lower_bound_seconds: int = 0
    reliability_score: float = 1.0
    scheduled_departure_at: datetime | None = None
    transfer_requirement: TransferRequirement = field(default_factory=TransferRequirement)
    bus_wait: BusWaitContribution | None = None
    readiness: QuoteReadiness = QuoteReadiness.EXACT
    mapping_ready: bool = True
    bus_intelligence_requested: bool = False

    def __post_init__(self) -> None:
        if not self.leg_id or not self.evaluator_key:
            raise ValueError("transit leg id and evaluator key are required")
        if self.mode not in TRANSIT_MODES:
            raise ValueError("transit leg mode must be canonical transit")
        if self.lower_bound_seconds < 0 or self.lower_bound_seconds > self.duration.p50_seconds:
            raise ValueError("transit lower bound must be within P50 duration")
        if not 0.0 <= self.reliability_score <= 1.0:
            raise ValueError("transit reliability must be between 0 and 1")
        if self.scheduled_departure_at is not None and (
            self.scheduled_departure_at.tzinfo is None
            or self.scheduled_departure_at.utcoffset() is None
        ):
            raise ValueError("scheduled transit departure must be timezone-aware")
        if self.bus_wait is not None and self.mode != "BUS":
            raise ValueError("Bus wait is valid only for BUS legs")
        if self.bus_intelligence_requested and self.mode != "BUS":
            raise ValueError("Bus Intelligence may be requested only for BUS legs")
        if not isinstance(self.readiness, QuoteReadiness):
            raise ValueError("transit readiness must be a QuoteReadiness")

    @property
    def from_ref(self) -> str:
        return self.topology.board_stop_ref

    @property
    def to_ref(self) -> str:
        return self.topology.alight_stop_ref

    def to_leg_spec(self, candidate_key: str, sequence: int) -> LegSpec:
        return LegSpec(
            leg_id=f"{candidate_key}:{sequence}:{self.leg_id}",
            mode=self.mode,
            from_ref=self.from_ref,
            to_ref=self.to_ref,
            evaluator_key=self.evaluator_key,
            scheduled_departure_at=self.scheduled_departure_at,
            transfer_requirement=self.transfer_requirement,
            bus_wait=self.bus_wait,
            topology_ref=self.topology.fingerprint,
        )

    @property
    def cost(self) -> LegCost:
        return LegCost(
            wait=TimeEstimate(0, 0),
            travel=self.duration,
            fare=self.fare,
            reliability_score=self.reliability_score,
        )


@dataclass(frozen=True, slots=True)
class WalkQuote:
    quote_id: str
    from_ref: str
    to_ref: str
    evaluator_key: str
    duration: TimeEstimate
    distance_meters: int
    lower_bound_seconds: int = 0
    readiness: QuoteReadiness = QuoteReadiness.EXACT
    reliability_score: float = 1.0
    topology_ref: str | None = None

    def __post_init__(self) -> None:
        if any(not value for value in (self.quote_id, self.from_ref, self.to_ref, self.evaluator_key)):
            raise ValueError("walk quote references are required")
        if self.from_ref == self.to_ref:
            raise ValueError("walk endpoints must be distinct")
        if self.distance_meters < 0:
            raise ValueError("walk distance must be non-negative")
        if self.lower_bound_seconds < 0 or self.lower_bound_seconds > self.duration.p50_seconds:
            raise ValueError("walk lower bound must be within P50 duration")
        if not 0.0 <= self.reliability_score <= 1.0:
            raise ValueError("walk reliability must be between 0 and 1")
        if self.topology_ref is not None and not self.topology_ref.strip():
            raise ValueError("walk topology_ref must be nonblank when supplied")
        if not isinstance(self.readiness, QuoteReadiness):
            raise ValueError("walk readiness must be a QuoteReadiness")

    def to_leg_spec(self, candidate_key: str, sequence: int) -> LegSpec:
        return LegSpec(
            leg_id=f"{candidate_key}:{sequence}:walk:{self.quote_id}",
            mode="WALK",
            from_ref=self.from_ref,
            to_ref=self.to_ref,
            evaluator_key=self.evaluator_key,
            distance_meters=self.distance_meters,
            topology_ref=self.topology_ref or f"walk:{self.from_ref}>{self.to_ref}",
        )

    @property
    def cost(self) -> LegCost:
        return LegCost(
            wait=TimeEstimate(0, 0),
            travel=self.duration,
            fare=MoneyRange.zero(),
            reliability_score=self.reliability_score,
        )


@dataclass(frozen=True, slots=True)
class TaxiQuote:
    quote_id: str
    from_ref: str
    to_ref: str
    evaluator_key: str
    dispatch_wait: TimeEstimate
    drive_duration: TimeEstimate
    fare: MoneyRange
    distance_meters: int
    lower_bound_dispatch_seconds: int = 0
    lower_bound_drive_seconds: int = 0
    readiness: QuoteReadiness = QuoteReadiness.EXACT
    reliability_score: float = 1.0
    topology_ref: str | None = None

    def __post_init__(self) -> None:
        if any(not value for value in (self.quote_id, self.from_ref, self.to_ref, self.evaluator_key)):
            raise ValueError("taxi quote references are required")
        if self.from_ref == self.to_ref:
            raise ValueError("taxi endpoints must be distinct")
        if self.distance_meters < 0:
            raise ValueError("taxi distance must be non-negative")
        if not 0 <= self.lower_bound_dispatch_seconds <= self.dispatch_wait.p50_seconds:
            raise ValueError("taxi dispatch lower bound must be within P50 wait")
        if not 0 <= self.lower_bound_drive_seconds <= self.drive_duration.p50_seconds:
            raise ValueError("taxi drive lower bound must be within P50 duration")
        if not 0.0 <= self.reliability_score <= 1.0:
            raise ValueError("taxi reliability must be between 0 and 1")
        if self.topology_ref is not None and not self.topology_ref.strip():
            raise ValueError("taxi topology_ref must be nonblank when supplied")
        if not isinstance(self.readiness, QuoteReadiness):
            raise ValueError("taxi readiness must be a QuoteReadiness")

    @property
    def lower_bound_seconds(self) -> int:
        return self.lower_bound_dispatch_seconds + self.lower_bound_drive_seconds

    def to_leg_spec(self, candidate_key: str, sequence: int) -> LegSpec:
        return LegSpec(
            leg_id=f"{candidate_key}:{sequence}:taxi:{self.quote_id}",
            mode="TAXI",
            from_ref=self.from_ref,
            to_ref=self.to_ref,
            evaluator_key=self.evaluator_key,
            distance_meters=self.distance_meters,
            topology_ref=self.topology_ref or f"taxi:{self.from_ref}>{self.to_ref}",
        )

    @property
    def cost(self) -> LegCost:
        # Dispatch is intentionally kept out of drive duration.  CandidateEvaluator
        # propagates it before re-evaluating the drive at the actual movement start.
        return LegCost(
            wait=self.dispatch_wait,
            travel=self.drive_duration,
            fare=self.fare,
            reliability_score=self.reliability_score,
        )


CanonicalMovement: TypeAlias = TransitLegInput | WalkQuote | TaxiQuote
BaselineMovement: TypeAlias = TransitLegInput | WalkQuote


@dataclass(frozen=True, slots=True)
class TransitBaseline:
    baseline_id: str
    legs: tuple[BaselineMovement, ...]
    coarse_risk: float = 0.0

    def __post_init__(self) -> None:
        if not self.baseline_id or not self.legs:
            raise ValueError("transit baseline id and legs are required")
        if not any(isinstance(leg, TransitLegInput) for leg in self.legs):
            raise ValueError("transit baseline must contain transit")
        _validate_continuity(self.legs)
        if not 0.0 <= self.coarse_risk <= 1.0:
            raise ValueError("baseline coarse risk must be between 0 and 1")

    @property
    def from_ref(self) -> str:
        return self.legs[0].from_ref

    @property
    def to_ref(self) -> str:
        return self.legs[-1].to_ref


@dataclass(frozen=True, slots=True)
class AccessHub:
    hub_id: str
    baseline_id: str
    board_leg_index: int
    taxi_quote: TaxiQuote


@dataclass(frozen=True, slots=True)
class EgressHub:
    hub_id: str
    baseline_id: str
    alight_leg_index: int
    taxi_quote: TaxiQuote


@dataclass(frozen=True, slots=True)
class UpstreamHub:
    hub_id: str
    baseline_id: str
    replace_leg_index: int
    upstream_leg: TransitLegInput
    taxi_quote: TaxiQuote


@dataclass(frozen=True, slots=True)
class TaxiBridge:
    bridge_id: str
    inbound_baseline_id: str
    inbound_end_index: int
    outbound_baseline_id: str
    outbound_start_index: int
    taxi_quote: TaxiQuote
    transfer_requirement: TransferRequirement = field(default_factory=TransferRequirement)


@dataclass(frozen=True, slots=True)
class StrategyGenerationInput:
    origin_ref: str
    destination_ref: str
    departure_at: datetime
    transit_baselines: tuple[TransitBaseline, ...]
    access_hubs: tuple[AccessHub, ...] = ()
    egress_hubs: tuple[EgressHub, ...] = ()
    upstream_hubs: tuple[UpstreamHub, ...] = ()
    taxi_bridges: tuple[TaxiBridge, ...] = ()
    taxi_only_quotes: tuple[TaxiQuote, ...] = ()

    def __post_init__(self) -> None:
        if not self.origin_ref or not self.destination_ref or self.origin_ref == self.destination_ref:
            raise ValueError("strategy origin and destination must be distinct")
        if self.departure_at.tzinfo is None or self.departure_at.utcoffset() is None:
            raise ValueError("strategy departure must be timezone-aware")
        baseline_ids = [item.baseline_id for item in self.transit_baselines]
        if len(baseline_ids) != len(set(baseline_ids)):
            raise ValueError("transit baseline ids must be unique")
        _require_unique_ids(self.access_hubs, "hub_id", "access hub")
        _require_unique_ids(self.egress_hubs, "hub_id", "egress hub")
        _require_unique_ids(self.upstream_hubs, "hub_id", "upstream hub")
        _require_unique_ids(self.taxi_bridges, "bridge_id", "taxi bridge")
        _require_unique_ids(self.taxi_only_quotes, "quote_id", "taxi-only quote")

        taxi_quotes = (
            *(item.taxi_quote for item in self.access_hubs),
            *(item.taxi_quote for item in self.egress_hubs),
            *(item.taxi_quote for item in self.upstream_hubs),
            *(item.taxi_quote for item in self.taxi_bridges),
            *self.taxi_only_quotes,
        )
        _require_consistent_values(taxi_quotes, "quote_id", "taxi quote")
        baseline_movements = tuple(
            movement
            for baseline in self.transit_baselines
            for movement in baseline.legs
        )
        _require_consistent_values(
            (item for item in baseline_movements if isinstance(item, WalkQuote)),
            "quote_id",
            "walk quote",
        )
        _require_consistent_values(
            (item for item in baseline_movements if isinstance(item, TransitLegInput)),
            "leg_id",
            "transit leg",
        )


@dataclass(frozen=True, slots=True)
class StrategyGenerationPolicy:
    version: str = "strategy-1.0.0"
    max_access_per_baseline: int = 3
    max_egress_per_baseline: int = 3
    max_taxi_only: int = 4
    max_bridges: int = 8
    coarse_time_slack_seconds: int = 3600

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("strategy policy version is required")
        if min(
            self.max_access_per_baseline,
            self.max_egress_per_baseline,
            self.max_taxi_only,
            self.max_bridges,
        ) <= 0:
            raise ValueError("strategy policy caps must be positive")
        if self.coarse_time_slack_seconds < 0:
            raise ValueError("coarse time slack must be non-negative")


@dataclass(frozen=True, slots=True)
class ExactEnrichmentRequest:
    request_key: str
    kind: EnrichmentKind
    from_ref: str
    to_ref: str
    call_units: int = 1
    depends_on_request_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.request_key or not self.from_ref or not self.to_ref:
            raise ValueError("exact enrichment references are required")
        if self.call_units <= 0:
            raise ValueError("exact enrichment call units must be positive")
        if self.request_key in self.depends_on_request_keys:
            raise ValueError("exact enrichment request cannot depend on itself")
        if len(self.depends_on_request_keys) != len(set(self.depends_on_request_keys)):
            raise ValueError("exact enrichment dependencies must be unique")


@dataclass(frozen=True, slots=True)
class ExactQuoteIdentity:
    quote_key: str
    step_key: str
    candidate_key: str
    leg_sequence: int
    entry_at: datetime

    def __post_init__(self) -> None:
        if not self.quote_key or not self.step_key or not self.candidate_key:
            raise ValueError("exact quote identity references are required")
        if self.leg_sequence < 0:
            raise ValueError("exact quote leg sequence must be non-negative")
        if self.entry_at.tzinfo is None or self.entry_at.utcoffset() is None:
            raise ValueError("exact quote entry time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ExactificationStep:
    """One provider-independent, chronologically dependent candidate movement."""

    step_key: str
    candidate_key: str
    leg_sequence: int
    leg_id: str
    mode: str
    from_ref: str
    to_ref: str
    evaluator_key: str
    topology_ref: str | None
    entry_time_basis: EntryTimeBasis
    predecessor_step_key: str | None
    transfer_p50_seconds: int
    enrichment: tuple[ExactEnrichmentRequest, ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.step_key,
            self.candidate_key,
            self.leg_id,
            self.mode,
            self.from_ref,
            self.to_ref,
            self.evaluator_key,
        )
        if any(not value for value in required):
            raise ValueError("exactification step references are required")
        if self.from_ref == self.to_ref:
            raise ValueError("exactification step endpoints must be distinct")
        if self.leg_sequence < 0 or self.transfer_p50_seconds < 0:
            raise ValueError("exactification sequence and transfer must be non-negative")
        if self.leg_sequence == 0:
            if self.entry_time_basis is not EntryTimeBasis.REQUEST_DEPARTURE:
                raise ValueError("first exactification step must use request departure")
            if self.predecessor_step_key is not None:
                raise ValueError("first exactification step cannot have a predecessor")
        else:
            if self.entry_time_basis is not EntryTimeBasis.PREDECESSOR_P50_END:
                raise ValueError("later exactification step must use predecessor P50 end")
            if not self.predecessor_step_key:
                raise ValueError("later exactification step requires a predecessor")
        if self.topology_ref is not None and not self.topology_ref.strip():
            raise ValueError("exactification topology_ref must be nonblank")
        kinds = [item.kind for item in self.enrichment]
        if len(kinds) != len(set(kinds)):
            raise ValueError("exactification enrichment kinds must be unique per step")
        if any(
            item.from_ref != self.from_ref or item.to_ref != self.to_ref
            for item in self.enrichment
        ):
            raise ValueError("exactification enrichment endpoints must match the step")
        request_keys = {item.request_key for item in self.enrichment}
        if len(request_keys) != len(self.enrichment):
            raise ValueError("exactification enrichment request keys must be unique")
        completed: set[str] = set()
        for request in self.enrichment:
            if not set(request.depends_on_request_keys) <= completed:
                raise ValueError("exactification enrichment must be topologically ordered")
            completed.add(request.request_key)

    @property
    def logical_provider_calls(self) -> int:
        return sum(item.call_units for item in self.enrichment)

    def ready_at(
        self,
        departure_at: datetime,
        *,
        predecessor_p50_end_at: datetime | None = None,
    ) -> datetime:
        if departure_at.tzinfo is None or departure_at.utcoffset() is None:
            raise ValueError("exactification departure must be timezone-aware")
        if self.entry_time_basis is EntryTimeBasis.REQUEST_DEPARTURE:
            if predecessor_p50_end_at is not None:
                raise ValueError("first exactification step cannot consume predecessor time")
            base = departure_at
        else:
            if predecessor_p50_end_at is None:
                raise ValueError("later exactification step requires predecessor P50 end")
            if (
                predecessor_p50_end_at.tzinfo is None
                or predecessor_p50_end_at.utcoffset() is None
            ):
                raise ValueError("predecessor P50 end must be timezone-aware")
            if predecessor_p50_end_at < departure_at:
                raise ValueError("predecessor P50 end cannot precede departure")
            base = predecessor_p50_end_at
        return base + timedelta(seconds=self.transfer_p50_seconds)

    def quote_identity(self, entry_at: datetime) -> ExactQuoteIdentity:
        if entry_at.tzinfo is None or entry_at.utcoffset() is None:
            raise ValueError("exact quote entry time must be timezone-aware")
        material = "|".join(
            (
                self.mode,
                self.from_ref,
                self.to_ref,
                self.topology_ref or "-",
                entry_at.astimezone(timezone.utc).isoformat(),
            )
        )
        return ExactQuoteIdentity(
            quote_key=f"quote_{sha256(material.encode('utf-8')).hexdigest()[:24]}",
            step_key=self.step_key,
            candidate_key=self.candidate_key,
            leg_sequence=self.leg_sequence,
            entry_at=entry_at,
        )


@dataclass(frozen=True, slots=True)
class CandidateExactificationPlan:
    candidate_key: str
    departure_at: datetime
    steps: tuple[ExactificationStep, ...]

    def __post_init__(self) -> None:
        if not self.candidate_key or not self.steps:
            raise ValueError("candidate exactification plan requires steps")
        if self.departure_at.tzinfo is None or self.departure_at.utcoffset() is None:
            raise ValueError("candidate exactification departure must be timezone-aware")
        if any(item.candidate_key != self.candidate_key for item in self.steps):
            raise ValueError("exactification steps must belong to their candidate")
        if tuple(item.leg_sequence for item in self.steps) != tuple(range(len(self.steps))):
            raise ValueError("exactification steps must be contiguous and topological")
        if len({item.step_key for item in self.steps}) != len(self.steps):
            raise ValueError("exactification step keys must be unique")
        for previous, following in zip(self.steps, self.steps[1:]):
            if following.predecessor_step_key != previous.step_key:
                raise ValueError("exactification dependency must reference the previous leg")
            if previous.to_ref != following.from_ref:
                raise ValueError("exactification steps must be continuous")

    @property
    def logical_provider_calls(self) -> int:
        return sum(item.logical_provider_calls for item in self.steps)

    def ready_steps(self, completed_step_keys: Iterable[str]) -> tuple[ExactificationStep, ...]:
        completed = frozenset(completed_step_keys)
        known = {item.step_key for item in self.steps}
        if not completed <= known:
            raise ValueError("completed exactification step is unknown")
        completed_sequences = tuple(
            item.leg_sequence for item in self.steps if item.step_key in completed
        )
        if completed_sequences != tuple(range(len(completed_sequences))):
            raise ValueError("completed exactification steps must form a topological prefix")
        return tuple(
            item
            for item in self.steps
            if item.step_key not in completed
            and (
                item.predecessor_step_key is None
                or item.predecessor_step_key in completed
            )
        )


@dataclass(frozen=True, slots=True)
class ExactificationPlan:
    candidates: tuple[CandidateExactificationPlan, ...]
    candidate_cap: int
    logical_provider_call_cap: int

    def __post_init__(self) -> None:
        if self.candidate_cap <= 0 or self.logical_provider_call_cap <= 0:
            raise ValueError("exactification caps must be positive")
        keys = [item.candidate_key for item in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("exactification candidate keys must be unique")
        if len(self.candidates) > self.candidate_cap:
            raise ValueError("exactification candidate cap exceeded")
        if self.logical_provider_calls > self.logical_provider_call_cap:
            raise ValueError("exactification provider call cap exceeded")

    @property
    def steps(self) -> tuple[ExactificationStep, ...]:
        return tuple(step for candidate in self.candidates for step in candidate.steps)

    @property
    def logical_provider_calls(self) -> int:
        return sum(item.logical_provider_calls for item in self.candidates)

    def ready_steps(self, completed_step_keys: Iterable[str]) -> tuple[ExactificationStep, ...]:
        completed = frozenset(completed_step_keys)
        known = {item.step_key for item in self.steps}
        if not completed <= known:
            raise ValueError("completed exactification step is unknown")
        return tuple(
            step
            for candidate in self.candidates
            for step in candidate.ready_steps(completed & {item.step_key for item in candidate.steps})
        )


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    seed: CandidateSeed
    exact_enrichment: tuple[ExactEnrichmentRequest, ...]
    exactification: CandidateExactificationPlan


@dataclass(frozen=True, slots=True)
class StrategyRejection:
    candidate_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class StrategyGenerationBatch:
    candidates: tuple[StrategyCandidate, ...]
    rejected: tuple[StrategyRejection, ...]
    exact_enrichment_plan: tuple[ExactEnrichmentRequest, ...]
    cost_catalog: tuple[tuple[str, LegCost], ...]
    unique_provider_calls: int
    policy_version: str
    exactification_plan: ExactificationPlan

    @property
    def seeds(self) -> tuple[CandidateSeed, ...]:
        return tuple(item.seed for item in self.candidates)

    def costs(self) -> dict[str, LegCost]:
        return dict(self.cost_catalog)


@dataclass(frozen=True, slots=True)
class _Draft:
    key: str
    pattern: str
    movements: tuple[CanonicalMovement, ...]
    coarse_risk: float

    @property
    def lower_bound_seconds(self) -> int:
        return sum(_lower_bound(item) for item in self.movements)

    @property
    def taxi_upper_krw(self) -> int:
        return sum(
            item.fare.upper_krw for item in self.movements if isinstance(item, TaxiQuote)
        )


def _validate_continuity(movements: Iterable[CanonicalMovement]) -> None:
    values = tuple(movements)
    for previous, following in zip(values, values[1:]):
        if previous.to_ref != following.from_ref:
            raise ValueError("canonical movement endpoints must be continuous")


def _require_unique_ids(values: Iterable[object], attribute: str, label: str) -> None:
    identifiers = [getattr(item, attribute) for item in values]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{label} ids must be unique")


def _require_consistent_values(
    values: Iterable[object], attribute: str, label: str
) -> None:
    seen: dict[str, object] = {}
    for value in values:
        identifier = getattr(value, attribute)
        current = seen.get(identifier)
        if current is not None and current != value:
            raise ValueError(f"{label} id maps to conflicting values")
        seen[identifier] = value


def _lower_bound(movement: CanonicalMovement) -> int:
    if isinstance(movement, TaxiQuote):
        return movement.lower_bound_seconds
    return movement.lower_bound_seconds


def _transfer_count(movements: tuple[CanonicalMovement, ...]) -> int:
    return max(0, sum(isinstance(item, TransitLegInput) for item in movements) - 1)


def _movement_sort_key(movement: CanonicalMovement) -> tuple[int, int, str]:
    upper = movement.fare.upper_krw if isinstance(movement, TaxiQuote) else 0
    identifier = getattr(movement, "quote_id", getattr(movement, "leg_id", ""))
    return (_lower_bound(movement), upper, identifier)


def _enrichment_sort_key(request: ExactEnrichmentRequest) -> tuple[int, str]:
    stage = {
        EnrichmentKind.TRANSIT: 0,
        EnrichmentKind.WALK: 0,
        EnrichmentKind.TAXI: 0,
        EnrichmentKind.MAPPING: 1,
        EnrichmentKind.BUS_INTELLIGENCE: 2,
    }[request.kind]
    return (stage, request.request_key)


class BoundedStrategyGenerator:
    """Generate all seven supported strategies without unbounded graph search."""

    def __init__(
        self,
        *,
        caps: CandidateCaps | None = None,
        policy: StrategyGenerationPolicy | None = None,
    ) -> None:
        self.caps = caps or CandidateCaps()
        self.policy = policy or StrategyGenerationPolicy()

    def generate(
        self,
        inputs: StrategyGenerationInput,
        constraints: RouteConstraints,
    ) -> StrategyGenerationBatch:
        rejected: list[StrategyRejection] = []
        baselines = {
            item.baseline_id: item
            for item in sorted(
                inputs.transit_baselines,
                key=lambda item: (
                    sum(_lower_bound(leg) for leg in item.legs),
                    item.coarse_risk,
                    item.baseline_id,
                ),
            )[: self.caps.transit_baselines]
        }
        for item in inputs.transit_baselines:
            if item.baseline_id not in baselines:
                rejected.append(StrategyRejection(f"transit:{item.baseline_id}", "TRANSIT_BASELINE_CAP"))

        drafts: list[_Draft] = []
        for baseline in baselines.values():
            if baseline.from_ref != inputs.origin_ref or baseline.to_ref != inputs.destination_ref:
                rejected.append(StrategyRejection(f"transit:{baseline.baseline_id}", "BASELINE_ENDPOINT_MISMATCH"))
                continue
            drafts.append(_Draft(f"transit:{baseline.baseline_id}", "TRANSIT_ONLY", baseline.legs, baseline.coarse_risk))

        access = self._select_access(inputs.access_hubs, baselines, inputs, rejected)
        egress = self._select_egress(inputs.egress_hubs, baselines, inputs, rejected)
        for hub in access:
            baseline = baselines[hub.baseline_id]
            movements = (hub.taxi_quote, *baseline.legs[hub.board_leg_index :])
            drafts.append(_Draft(f"access:{hub.hub_id}", "TAXI_TRANSIT", movements, baseline.coarse_risk))
        for hub in egress:
            baseline = baselines[hub.baseline_id]
            movements = (*baseline.legs[: hub.alight_leg_index + 1], hub.taxi_quote)
            drafts.append(_Draft(f"egress:{hub.hub_id}", "TRANSIT_TAXI", movements, baseline.coarse_risk))

        for access_hub in access:
            for egress_hub in egress:
                if access_hub.baseline_id != egress_hub.baseline_id:
                    continue
                if access_hub.board_leg_index > egress_hub.alight_leg_index:
                    continue
                baseline = baselines[access_hub.baseline_id]
                movements = (
                    access_hub.taxi_quote,
                    *baseline.legs[access_hub.board_leg_index : egress_hub.alight_leg_index + 1],
                    egress_hub.taxi_quote,
                )
                drafts.append(
                    _Draft(
                        f"access-egress:{access_hub.hub_id}:{egress_hub.hub_id}",
                        "TAXI_TRANSIT_TAXI",
                        movements,
                        baseline.coarse_risk,
                    )
                )

        taxi_only = sorted(inputs.taxi_only_quotes, key=_movement_sort_key)
        for quote in taxi_only[: self.policy.max_taxi_only]:
            key = f"taxi-only:{quote.quote_id}"
            if quote.from_ref != inputs.origin_ref or quote.to_ref != inputs.destination_ref:
                rejected.append(StrategyRejection(key, "TAXI_ENDPOINT_MISMATCH"))
                continue
            drafts.append(_Draft(key, "TAXI_ONLY", (quote,), 1.0 - quote.reliability_score))
        for quote in taxi_only[self.policy.max_taxi_only :]:
            rejected.append(StrategyRejection(f"taxi-only:{quote.quote_id}", "TAXI_ONLY_CAP"))

        upstream_counts: dict[tuple[str, str, str], int] = {}
        for option in sorted(inputs.upstream_hubs, key=lambda item: (_movement_sort_key(item.taxi_quote), item.hub_id)):
            draft = self._upstream_draft(option, baselines, inputs)
            if isinstance(draft, StrategyRejection):
                rejected.append(draft)
            else:
                topology = option.upstream_leg.topology
                route_key = (
                    topology.route_ref,
                    topology.direction,
                    topology.branch_ref or "-",
                )
                if upstream_counts.get(route_key, 0) >= self.caps.upstream_per_route:
                    rejected.append(
                        StrategyRejection(draft.key, "UPSTREAM_PER_ROUTE_CAP")
                    )
                    continue
                upstream_counts[route_key] = upstream_counts.get(route_key, 0) + 1
                drafts.append(draft)

        bridges = sorted(inputs.taxi_bridges, key=lambda item: (_movement_sort_key(item.taxi_quote), item.bridge_id))
        for bridge in bridges[: self.policy.max_bridges]:
            draft = self._bridge_draft(bridge, baselines, inputs)
            if isinstance(draft, StrategyRejection):
                rejected.append(draft)
            else:
                drafts.append(draft)
        for bridge in bridges[self.policy.max_bridges :]:
            rejected.append(StrategyRejection(f"bridge:{bridge.bridge_id}", "TAXI_BRIDGE_CAP"))

        best_public_lower = min(
            (draft.lower_bound_seconds for draft in drafts if draft.pattern == "TRANSIT_ONLY"),
            default=None,
        )
        seeds: list[CandidateSeed] = []
        draft_by_key: dict[str, _Draft] = {}
        for draft in sorted(
            drafts,
            key=lambda item: (
                item.lower_bound_seconds,
                item.taxi_upper_krw,
                item.coarse_risk,
                item.pattern,
                item.key,
            ),
        ):
            if (
                best_public_lower is not None
                and draft.pattern != "TRANSIT_ONLY"
                and draft.lower_bound_seconds
                > best_public_lower + self.policy.coarse_time_slack_seconds
            ):
                rejected.append(StrategyRejection(draft.key, "COARSE_TIME_BOUND"))
                continue
            _validate_continuity(draft.movements)
            legs = tuple(
                movement.to_leg_spec(draft.key, index)
                for index, movement in enumerate(draft.movements)
            )
            seed = CandidateSeed(
                candidate_key=draft.key,
                pattern=draft.pattern,
                legs=legs,
                transfer_count=_transfer_count(draft.movements),
                coarse_p50_seconds=draft.lower_bound_seconds,
                coarse_taxi_upper_krw=draft.taxi_upper_krw,
                coarse_risk=draft.coarse_risk,
            )
            seeds.append(seed)
            draft_by_key[draft.key] = draft

        admitted = BoundedCandidateGenerator(self.caps).generate(seeds, constraints)
        rejected.extend(StrategyRejection(key, reason) for key, reason in admitted.rejected)

        selected: list[StrategyCandidate] = []
        costs: dict[str, LegCost] = {}
        reserved: dict[str, ExactEnrichmentRequest] = {}
        consumed = 0
        for seed in admitted.candidates:
            draft = draft_by_key[seed.candidate_key]
            requests = self._exact_requests(draft.movements)
            exactification = self._exactification_for(
                seed,
                draft.movements,
                inputs.departure_at,
            )
            added_units = exactification.logical_provider_calls
            if consumed + added_units > self.caps.provider_calls:
                rejected.append(StrategyRejection(seed.candidate_key, "PROVIDER_CALL_CAP"))
                continue
            for request in requests:
                reserved.setdefault(request.request_key, request)
            consumed += added_units
            for movement in draft.movements:
                current = costs.get(movement.evaluator_key)
                if current is not None and current != movement.cost:
                    raise ValueError("evaluator key maps to conflicting canonical costs")
                costs[movement.evaluator_key] = movement.cost
            selected.append(StrategyCandidate(seed, requests, exactification))

        return StrategyGenerationBatch(
            candidates=tuple(selected),
            rejected=tuple(sorted(set(rejected), key=lambda item: (item.candidate_key, item.reason))),
            exact_enrichment_plan=tuple(
                sorted(reserved.values(), key=_enrichment_sort_key)
            ),
            cost_catalog=tuple(sorted(costs.items())),
            unique_provider_calls=consumed,
            policy_version=self.policy.version,
            exactification_plan=ExactificationPlan(
                candidates=tuple(item.exactification for item in selected),
                candidate_cap=self.caps.pre_pareto,
                logical_provider_call_cap=self.caps.provider_calls,
            ),
        )

    def _select_access(
        self,
        values: tuple[AccessHub, ...],
        baselines: dict[str, TransitBaseline],
        inputs: StrategyGenerationInput,
        rejected: list[StrategyRejection],
    ) -> tuple[AccessHub, ...]:
        selected: list[AccessHub] = []
        counts: dict[str, int] = {}
        for hub in sorted(values, key=lambda item: (_movement_sort_key(item.taxi_quote), item.baseline_id, item.hub_id)):
            key = f"access:{hub.hub_id}"
            baseline = baselines.get(hub.baseline_id)
            if baseline is None or not 0 <= hub.board_leg_index < len(baseline.legs):
                rejected.append(StrategyRejection(key, "ACCESS_BASELINE_INVALID"))
                continue
            if baseline.to_ref != inputs.destination_ref:
                rejected.append(StrategyRejection(key, "ACCESS_BASELINE_INVALID"))
                continue
            board = baseline.legs[hub.board_leg_index]
            if not isinstance(board, TransitLegInput):
                rejected.append(StrategyRejection(key, "ACCESS_BOARD_NOT_TRANSIT"))
                continue
            if hub.taxi_quote.from_ref != inputs.origin_ref or hub.taxi_quote.to_ref != board.from_ref:
                rejected.append(StrategyRejection(key, "ACCESS_ENDPOINT_MISMATCH"))
                continue
            if counts.get(hub.baseline_id, 0) >= self.policy.max_access_per_baseline:
                rejected.append(StrategyRejection(key, "ACCESS_HUB_CAP"))
                continue
            counts[hub.baseline_id] = counts.get(hub.baseline_id, 0) + 1
            selected.append(hub)
        return tuple(selected)

    def _select_egress(
        self,
        values: tuple[EgressHub, ...],
        baselines: dict[str, TransitBaseline],
        inputs: StrategyGenerationInput,
        rejected: list[StrategyRejection],
    ) -> tuple[EgressHub, ...]:
        selected: list[EgressHub] = []
        counts: dict[str, int] = {}
        for hub in sorted(values, key=lambda item: (_movement_sort_key(item.taxi_quote), item.baseline_id, item.hub_id)):
            key = f"egress:{hub.hub_id}"
            baseline = baselines.get(hub.baseline_id)
            if baseline is None or not 0 <= hub.alight_leg_index < len(baseline.legs):
                rejected.append(StrategyRejection(key, "EGRESS_BASELINE_INVALID"))
                continue
            if baseline.from_ref != inputs.origin_ref:
                rejected.append(StrategyRejection(key, "EGRESS_BASELINE_INVALID"))
                continue
            alight = baseline.legs[hub.alight_leg_index]
            if not isinstance(alight, TransitLegInput):
                rejected.append(StrategyRejection(key, "EGRESS_ALIGHT_NOT_TRANSIT"))
                continue
            if hub.taxi_quote.from_ref != alight.to_ref or hub.taxi_quote.to_ref != inputs.destination_ref:
                rejected.append(StrategyRejection(key, "EGRESS_ENDPOINT_MISMATCH"))
                continue
            if counts.get(hub.baseline_id, 0) >= self.policy.max_egress_per_baseline:
                rejected.append(StrategyRejection(key, "EGRESS_HUB_CAP"))
                continue
            counts[hub.baseline_id] = counts.get(hub.baseline_id, 0) + 1
            selected.append(hub)
        return tuple(selected)

    @staticmethod
    def _upstream_draft(
        option: UpstreamHub,
        baselines: dict[str, TransitBaseline],
        inputs: StrategyGenerationInput,
    ) -> _Draft | StrategyRejection:
        key = f"upstream:{option.hub_id}"
        baseline = baselines.get(option.baseline_id)
        if baseline is None or not 0 <= option.replace_leg_index < len(baseline.legs):
            return StrategyRejection(key, "UPSTREAM_BASELINE_INVALID")
        if baseline.to_ref != inputs.destination_ref:
            return StrategyRejection(key, "UPSTREAM_BASELINE_INVALID")
        original = baseline.legs[option.replace_leg_index]
        replacement = option.upstream_leg
        if not isinstance(original, TransitLegInput):
            return StrategyRejection(key, "UPSTREAM_REPLACEMENT_NOT_TRANSIT")
        left = original.topology
        right = replacement.topology
        same_service = (
            left.route_ref == right.route_ref
            and left.direction == right.direction
            and left.branch_ref == right.branch_ref
            and left.alight_stop_ref == right.alight_stop_ref
            and left.alight_sequence == right.alight_sequence
            and original.mode == replacement.mode
        )
        if not same_service:
            return StrategyRejection(key, "UPSTREAM_ROUTE_DIRECTION_MISMATCH")
        if right.board_sequence >= left.board_sequence:
            return StrategyRejection(key, "UPSTREAM_SEQUENCE_NOT_EARLIER")
        if option.taxi_quote.from_ref != inputs.origin_ref or option.taxi_quote.to_ref != replacement.from_ref:
            return StrategyRejection(key, "UPSTREAM_ENDPOINT_MISMATCH")
        movements: tuple[CanonicalMovement, ...] = (
            option.taxi_quote,
            replacement,
            *baseline.legs[option.replace_leg_index + 1 :],
        )
        return _Draft(key, "UPSTREAM_STOP_TAXI_TRANSIT", movements, baseline.coarse_risk)

    @staticmethod
    def _bridge_draft(
        bridge: TaxiBridge,
        baselines: dict[str, TransitBaseline],
        inputs: StrategyGenerationInput,
    ) -> _Draft | StrategyRejection:
        key = f"bridge:{bridge.bridge_id}"
        inbound = baselines.get(bridge.inbound_baseline_id)
        outbound = baselines.get(bridge.outbound_baseline_id)
        if inbound is None or outbound is None:
            return StrategyRejection(key, "TAXI_BRIDGE_BASELINE_INVALID")
        if not 0 <= bridge.inbound_end_index < len(inbound.legs) or not 0 <= bridge.outbound_start_index < len(outbound.legs):
            return StrategyRejection(key, "TAXI_BRIDGE_INDEX_INVALID")
        inbound_legs = inbound.legs[: bridge.inbound_end_index + 1]
        outbound_legs = outbound.legs[bridge.outbound_start_index :]
        if inbound.from_ref != inputs.origin_ref or outbound.to_ref != inputs.destination_ref:
            return StrategyRejection(key, "TAXI_BRIDGE_ENDPOINT_MISMATCH")
        if not isinstance(inbound_legs[-1], TransitLegInput) or not isinstance(outbound_legs[0], TransitLegInput):
            return StrategyRejection(key, "TAXI_BRIDGE_TRANSIT_REQUIRED")
        if bridge.taxi_quote.from_ref != inbound_legs[-1].to_ref or bridge.taxi_quote.to_ref != outbound_legs[0].from_ref:
            return StrategyRejection(key, "TAXI_BRIDGE_ENDPOINT_MISMATCH")

        first_outbound = replace(
            outbound_legs[0],
            transfer_requirement=TransferRequirement(
                outbound_legs[0].transfer_requirement.p50_seconds
                + bridge.transfer_requirement.p50_seconds,
                outbound_legs[0].transfer_requirement.p90_seconds
                + bridge.transfer_requirement.p90_seconds,
            ),
        )
        outbound_legs = (first_outbound, *outbound_legs[1:])
        if first_outbound.scheduled_departure_at is not None:
            earliest_p90 = inputs.departure_at + timedelta(
                seconds=sum(_lower_bound(item) for item in inbound_legs)
                + bridge.taxi_quote.lower_bound_seconds
                + bridge.transfer_requirement.p90_seconds
            )
            if earliest_p90 > first_outbound.scheduled_departure_at:
                return StrategyRejection(key, "TAXI_BRIDGE_CONNECTION_INFEASIBLE")
        movements: tuple[CanonicalMovement, ...] = (
            *inbound_legs,
            bridge.taxi_quote,
            *outbound_legs,
        )
        return _Draft(
            key,
            "TRANSIT_TAXI_BRIDGE_TRANSIT",
            movements,
            max(inbound.coarse_risk, outbound.coarse_risk),
        )

    @staticmethod
    def _exact_requests(
        movements: tuple[CanonicalMovement, ...],
    ) -> tuple[ExactEnrichmentRequest, ...]:
        requests: dict[str, ExactEnrichmentRequest] = {}
        for movement in movements:
            for request in BoundedStrategyGenerator._movement_exact_requests(movement):
                requests[request.request_key] = request
        return tuple(sorted(requests.values(), key=_enrichment_sort_key))

    @staticmethod
    def _movement_exact_requests(
        movement: CanonicalMovement,
    ) -> tuple[ExactEnrichmentRequest, ...]:
        requests: list[ExactEnrichmentRequest] = []
        movement_request_key: str | None = None
        if movement.readiness is QuoteReadiness.COARSE:
            if isinstance(movement, TaxiQuote):
                kind = EnrichmentKind.TAXI
                identifier = movement.quote_id
            elif isinstance(movement, WalkQuote):
                kind = EnrichmentKind.WALK
                identifier = movement.quote_id
            else:
                kind = EnrichmentKind.TRANSIT
                identifier = movement.leg_id
            movement_request_key = f"{kind.value.lower()}:{identifier}"
            requests.append(
                ExactEnrichmentRequest(
                    request_key=movement_request_key,
                    kind=kind,
                    from_ref=movement.from_ref,
                    to_ref=movement.to_ref,
                )
            )
        if isinstance(movement, TransitLegInput) and movement.mode == "BUS":
            mapping_request_key: str | None = None
            if not movement.mapping_ready:
                mapping_request_key = f"mapping:{movement.topology.fingerprint}"
                requests.append(
                    ExactEnrichmentRequest(
                        request_key=mapping_request_key,
                        kind=EnrichmentKind.MAPPING,
                        from_ref=movement.from_ref,
                        to_ref=movement.to_ref,
                        depends_on_request_keys=(
                            (movement_request_key,)
                            if movement_request_key is not None
                            else ()
                        ),
                    )
                )
            if movement.bus_intelligence_requested and movement.bus_wait is None:
                predecessor = mapping_request_key or movement_request_key
                requests.append(
                    ExactEnrichmentRequest(
                        request_key=f"bus:{movement.topology.fingerprint}",
                        kind=EnrichmentKind.BUS_INTELLIGENCE,
                        from_ref=movement.from_ref,
                        to_ref=movement.to_ref,
                        depends_on_request_keys=(
                            (predecessor,) if predecessor is not None else ()
                        ),
                    )
                )
        return tuple(requests)

    @staticmethod
    def _exactification_for(
        seed: CandidateSeed,
        movements: tuple[CanonicalMovement, ...],
        departure_at: datetime,
    ) -> CandidateExactificationPlan:
        if len(seed.legs) != len(movements):
            raise ValueError("exactification movements must match candidate legs")
        steps: list[ExactificationStep] = []
        for sequence, (leg, movement) in enumerate(zip(seed.legs, movements, strict=True)):
            step_key = f"{seed.candidate_key}:leg:{sequence}"
            steps.append(
                ExactificationStep(
                    step_key=step_key,
                    candidate_key=seed.candidate_key,
                    leg_sequence=sequence,
                    leg_id=leg.leg_id,
                    mode=leg.mode,
                    from_ref=leg.from_ref,
                    to_ref=leg.to_ref,
                    evaluator_key=leg.evaluator_key,
                    topology_ref=leg.topology_ref,
                    entry_time_basis=(
                        EntryTimeBasis.REQUEST_DEPARTURE
                        if sequence == 0
                        else EntryTimeBasis.PREDECESSOR_P50_END
                    ),
                    predecessor_step_key=(steps[-1].step_key if steps else None),
                    transfer_p50_seconds=leg.transfer_requirement.p50_seconds,
                    enrichment=BoundedStrategyGenerator._movement_exact_requests(
                        movement
                    ),
                )
            )
        return CandidateExactificationPlan(seed.candidate_key, departure_at, tuple(steps))
