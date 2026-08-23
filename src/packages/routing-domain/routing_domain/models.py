"""Immutable canonical inputs and evaluated routing value objects.

These are internal domain values, not copies of the shared API DTOs.  The API
layer owns projection to the canonical OpenAPI contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Final


TRANSIT_MODES: Final[frozenset[str]] = frozenset({"BUS", "SUBWAY", "GTX", "TRAIN"})
KNOWN_MODES: Final[frozenset[str]] = frozenset(
    {"WALK", "WAIT", "TRANSFER", "TAXI", *TRANSIT_MODES}
)
KNOWN_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "TRANSIT_ONLY",
        "TAXI_TRANSIT",
        "TRANSIT_TAXI",
        "TAXI_TRANSIT_TAXI",
        "TAXI_ONLY",
        "TRANSIT_TAXI_BRIDGE_TRANSIT",
        "UPSTREAM_STOP_TAXI_TRANSIT",
    }
)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TimeEstimate:
    p50_seconds: int
    p90_seconds: int

    def __post_init__(self) -> None:
        if self.p50_seconds < 0:
            raise ValueError("p50_seconds must be non-negative")
        if self.p90_seconds < self.p50_seconds:
            raise ValueError("p90_seconds must be greater than or equal to p50_seconds")


@dataclass(frozen=True, slots=True)
class MoneyRange:
    expected_krw: int
    lower_krw: int
    upper_krw: int

    def __post_init__(self) -> None:
        if self.lower_krw < 0:
            raise ValueError("money values must be non-negative")
        if not self.lower_krw <= self.expected_krw <= self.upper_krw:
            raise ValueError("money range must satisfy lower <= expected <= upper")

    @classmethod
    def zero(cls) -> "MoneyRange":
        return cls(expected_krw=0, lower_krw=0, upper_krw=0)


@dataclass(frozen=True, slots=True)
class BusWaitContribution:
    """Bus Intelligence contribution at the user's propagated stop arrival."""

    expected_wait_seconds: int
    p90_wait_seconds: int

    def __post_init__(self) -> None:
        TimeEstimate(self.expected_wait_seconds, self.p90_wait_seconds)


@dataclass(frozen=True, slots=True)
class TransferRequirement:
    """Time needed before boarding a fixed connection."""

    p50_seconds: int = 0
    p90_seconds: int = 0
    connector_walk_seconds: int = 0

    def __post_init__(self) -> None:
        TimeEstimate(self.p50_seconds, self.p90_seconds)
        if not 0 <= self.connector_walk_seconds <= self.p50_seconds:
            raise ValueError(
                "connector_walk_seconds must be within the P50 transfer requirement"
            )


@dataclass(frozen=True, slots=True)
class LegSpec:
    leg_id: str
    mode: str
    from_ref: str
    to_ref: str
    evaluator_key: str
    distance_meters: int = 0
    scheduled_departure_at: datetime | None = None
    transfer_requirement: TransferRequirement = field(default_factory=TransferRequirement)
    bus_wait: BusWaitContribution | None = None
    topology_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.leg_id:
            raise ValueError("leg_id is required")
        if self.mode not in KNOWN_MODES:
            raise ValueError(f"unsupported travel mode: {self.mode}")
        if not self.from_ref or not self.to_ref or self.from_ref == self.to_ref:
            raise ValueError("leg endpoints must be distinct, non-empty references")
        if not self.evaluator_key:
            raise ValueError("evaluator_key is required")
        if self.distance_meters < 0:
            raise ValueError("distance_meters must be non-negative")
        if self.scheduled_departure_at is not None:
            _require_aware(self.scheduled_departure_at, "scheduled_departure_at")
        if self.bus_wait is not None and self.mode != "BUS":
            raise ValueError("Bus wait contribution is valid only for BUS legs")
        if self.topology_ref is not None and not self.topology_ref.strip():
            raise ValueError("topology_ref must be nonblank when supplied")


@dataclass(frozen=True, slots=True)
class LegCost:
    """A time-dependent evaluator result for one supplied entry time.

    ``next_service_wait`` is explicit evidence for a fixed scheduled connection
    missed at that entry time. It is distinct from the ordinary unscheduled wait.
    """

    wait: TimeEstimate
    travel: TimeEstimate
    fare: MoneyRange | None
    reliability_score: float = 1.0
    warning_codes: tuple[str, ...] = ()
    next_service_wait: TimeEstimate | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.reliability_score <= 1.0:
            raise ValueError("reliability_score must be between 0 and 1")
        if len(self.warning_codes) != len(set(self.warning_codes)):
            raise ValueError("warning_codes must be unique")


@dataclass(frozen=True, slots=True)
class CandidateSeed:
    candidate_key: str
    pattern: str
    legs: tuple[LegSpec, ...]
    transfer_count: int
    coarse_p50_seconds: int
    coarse_taxi_upper_krw: int
    coarse_risk: float = 0.0

    def __post_init__(self) -> None:
        if not self.candidate_key:
            raise ValueError("candidate_key is required")
        if self.pattern not in KNOWN_PATTERNS:
            raise ValueError(f"unsupported route pattern: {self.pattern}")
        if not self.legs:
            raise ValueError("candidate must contain at least one leg")
        if self.transfer_count < 0:
            raise ValueError("transfer_count must be non-negative")
        if self.coarse_p50_seconds < 0 or self.coarse_taxi_upper_krw < 0:
            raise ValueError("coarse estimates must be non-negative")
        if not 0.0 <= self.coarse_risk <= 1.0:
            raise ValueError("coarse_risk must be between 0 and 1")
        sequences = [leg.leg_id for leg in self.legs]
        if len(sequences) != len(set(sequences)):
            raise ValueError("leg_id values must be unique within a candidate")

    @property
    def topology_key(self) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(
            (
                leg.mode,
                leg.from_ref,
                leg.to_ref,
                leg.topology_ref or "-",
            )
            for leg in self.legs
        )

    @property
    def route_id(self) -> str:
        fingerprint = "|".join(
            [self.pattern, *[":".join(item) for item in self.topology_key]]
        )
        return f"route_{sha256(fingerprint.encode('utf-8')).hexdigest()[:16]}"


@dataclass(frozen=True, slots=True)
class RouteConstraints:
    taxi_budget_krw: int
    strict_taxi_budget: bool
    max_walk_seconds: int
    max_transfers: int
    max_taxi_legs: int
    allowed_modes: frozenset[str]
    allow_taxi_bridge: bool = False

    def __post_init__(self) -> None:
        if min(
            self.taxi_budget_krw,
            self.max_walk_seconds,
            self.max_transfers,
            self.max_taxi_legs,
        ) < 0:
            raise ValueError("route constraints must be non-negative")
        unknown = self.allowed_modes - KNOWN_MODES
        if unknown:
            raise ValueError(f"unknown allowed modes: {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class TransferMargin:
    p50_seconds: int
    p90_seconds: int


@dataclass(frozen=True, slots=True)
class EvaluatedLeg:
    leg_id: str
    sequence: int
    mode: str
    from_ref: str
    to_ref: str
    ready_at_p50: datetime
    ready_at_p90: datetime
    start_at_p50: datetime
    start_at_p90: datetime
    end_at_p50: datetime
    end_at_p90: datetime
    duration: TimeEstimate
    fare: MoneyRange
    distance_meters: int
    reliability_score: float
    transfer_margin: TransferMargin | None = None
    warning_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "ready_at_p50",
            "ready_at_p90",
            "start_at_p50",
            "start_at_p90",
            "end_at_p50",
            "end_at_p90",
        ):
            _require_aware(getattr(self, name), name)
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if not (
            self.ready_at_p50 <= self.start_at_p50 <= self.end_at_p50
            and self.ready_at_p90 <= self.start_at_p90 <= self.end_at_p90
        ):
            raise ValueError("leg timestamps must be chronological")
        if self.end_at_p90 < self.end_at_p50:
            raise ValueError("P90 leg arrival must not precede P50 leg arrival")

    @property
    def wait_duration(self) -> TimeEstimate:
        """Boarding/dispatch wait after the traveller is ready for this leg."""

        p50_seconds = int((self.start_at_p50 - self.ready_at_p50).total_seconds())
        p90_seconds = int((self.start_at_p90 - self.ready_at_p90).total_seconds())
        return TimeEstimate(p50_seconds, max(p50_seconds, p90_seconds))

    @property
    def travel_duration(self) -> TimeEstimate:
        """In-vehicle or movement time after boarding/dispatch wait completes."""

        p50_seconds = int((self.end_at_p50 - self.start_at_p50).total_seconds())
        p90_seconds = int((self.end_at_p90 - self.start_at_p90).total_seconds())
        return TimeEstimate(p50_seconds, max(p50_seconds, p90_seconds))


@dataclass(frozen=True, slots=True)
class EvaluatedCandidate:
    route_id: str
    candidate_key: str
    pattern: str
    topology_key: tuple[tuple[str, str, str, str], ...]
    departure_at: datetime
    arrival_at_p50: datetime
    arrival_at_p90: datetime
    total_duration: TimeEstimate
    taxi_cost: MoneyRange
    total_fare_expected_krw: int
    walk_seconds: int
    transfer_count: int
    taxi_leg_count: int
    reliability_score: float
    transfer_risk: float
    legs: tuple[EvaluatedLeg, ...]
    reason_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.departure_at, "departure_at")
        _require_aware(self.arrival_at_p50, "arrival_at_p50")
        _require_aware(self.arrival_at_p90, "arrival_at_p90")
        if not self.departure_at <= self.arrival_at_p50 <= self.arrival_at_p90:
            raise ValueError("candidate arrival timestamps must be chronological")
        if not 0.0 <= self.reliability_score <= 1.0:
            raise ValueError("reliability_score must be between 0 and 1")
        if not 0.0 <= self.transfer_risk <= 1.0:
            raise ValueError("transfer_risk must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RecommendationSet:
    fastest: str | None
    stable: str | None
    efficient: str | None
    public_transit_only: str | None


@dataclass(frozen=True, slots=True)
class CandidateCounts:
    supplied: int
    generated: int
    fully_evaluated: int
    feasible: int
    pareto: int


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    candidate_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    routes: tuple[EvaluatedCandidate, ...]
    pareto_route_ids: tuple[str, ...]
    recommendations: RecommendationSet
    counts: CandidateCounts
    rejected: tuple[RejectedCandidate, ...]
    ranking_policy_version: str
