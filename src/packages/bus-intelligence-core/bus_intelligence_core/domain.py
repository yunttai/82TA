"""Immutable values used by Bus Intelligence.

String values at this internal boundary intentionally follow the canonical code
registry without redefining its enums. Validation is limited to invariants owned
by this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite

from .feature_context import EtaFeatureContext, SeatRiskFeatureContext


MODEL_READINESS_VALUES = frozenset(
    {
        "UNVERIFIED",
        "FIXTURE_ONLY",
        "REGISTERED",
        "VALIDATED",
        "SHADOW",
        "CANARY",
        "ACTIVE",
        "RETIRED",
        "REJECTED",
    }
)


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def require_probability(value: float, field_name: str) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ModelProvenance:
    purpose: str
    version: str
    origin: str
    readiness: str = "UNVERIFIED"

    def __post_init__(self) -> None:
        if not self.purpose or not self.version or not self.origin:
            raise ValueError("model provenance fields must be non-empty")
        if self.readiness not in MODEL_READINESS_VALUES:
            raise ValueError("unsupported model readiness")


@dataclass(frozen=True, slots=True)
class EtaPrediction:
    """Absolute arrival distribution for a vehicle at the boarding stop."""

    p50_arrival_at: datetime
    p90_arrival_at: datetime
    source: str
    model_version: str | None = None
    confidence: float = 1.0
    warnings: tuple[str, ...] = field(default_factory=tuple)
    model_readiness: str = "UNVERIFIED"

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings))
        require_aware(self.p50_arrival_at, "p50_arrival_at")
        require_aware(self.p90_arrival_at, "p90_arrival_at")
        if self.p90_arrival_at < self.p50_arrival_at:
            raise ValueError("ETA p90 must be at or after p50")
        if self.source not in {"OFFICIAL", "POSITION_MODEL", "HISTORICAL"}:
            raise ValueError("unsupported ETA source")
        if self.source != "OFFICIAL" and not self.model_version:
            raise ValueError("fallback ETA must identify its version")
        if self.source == "OFFICIAL" and self.model_version is not None:
            raise ValueError("official ETA cannot claim a model version")
        require_probability(self.confidence, "ETA confidence")
        if self.model_readiness not in MODEL_READINESS_VALUES:
            raise ValueError("unsupported ETA model readiness")


@dataclass(frozen=True, slots=True)
class SeatRiskPrediction:
    """Target-stop seat risk, separate from ETA and actual boarding outcome."""

    no_seat_probability: float
    low_seat2_probability: float
    low_seat5_probability: float | None
    model_version: str
    confidence: float
    origin: str = "MODEL_PREDICTED"
    warnings: tuple[str, ...] = field(default_factory=tuple)
    model_readiness: str = "UNVERIFIED"

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings))
        require_probability(self.no_seat_probability, "no-seat probability")
        require_probability(self.low_seat2_probability, "low-seat-2 probability")
        if self.low_seat5_probability is not None:
            require_probability(self.low_seat5_probability, "low-seat-5 probability")
        if self.no_seat_probability > self.low_seat2_probability:
            raise ValueError("P(no seat) cannot exceed P(at most 2 seats)")
        if (
            self.low_seat5_probability is not None
            and self.low_seat2_probability > self.low_seat5_probability
        ):
            raise ValueError("P(at most 2 seats) cannot exceed P(at most 5 seats)")
        if not self.model_version:
            raise ValueError("Seat Risk must identify its model version")
        require_probability(self.confidence, "Seat Risk confidence")
        if self.origin not in {"MODEL_PREDICTED", "HISTORICAL_PROXY"}:
            raise ValueError("unsupported Seat Risk origin")
        if self.model_readiness not in MODEL_READINESS_VALUES:
            raise ValueError("unsupported Seat Risk model readiness")


@dataclass(frozen=True, slots=True)
class VehicleObservation:
    """Canonical vehicle signal; no raw Provider fields are accepted.

    `future_target_remaining_seats` is an optional observed label for replay and
    evaluation only. It is never copied into predictor inputs. Absence remains
    ``None`` and therefore cannot become a negative class.
    """

    vehicle_ref: str
    route_id: str
    direction: str
    boarding_stop_id: str
    observed_at: datetime
    official_eta: EtaPrediction | None = None
    remain_seat_observed: int | None = None
    future_target_remaining_seats: int | None = None

    def __post_init__(self) -> None:
        for name in ("vehicle_ref", "route_id", "direction", "boarding_stop_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        require_aware(self.observed_at, "observed_at")
        if self.official_eta is not None and self.official_eta.source != "OFFICIAL":
            raise ValueError("official_eta must have OFFICIAL source")
        if self.remain_seat_observed is not None and self.remain_seat_observed < 0:
            raise ValueError("observed remaining seats cannot be negative")
        if (
            self.future_target_remaining_seats is not None
            and self.future_target_remaining_seats < 0
        ):
            raise ValueError("future observed remaining seats cannot be negative")

    @property
    def has_future_target_observation(self) -> bool:
        return self.future_target_remaining_seats is not None


@dataclass(frozen=True, slots=True)
class BusIntelligenceRequest:
    mapping_grade: str
    mapping_allows_bus_intelligence: bool
    mapping_score: float
    mapping_version: str
    user_arrival_at: datetime
    evaluated_at: datetime
    target_stop_id: str
    service_type: str
    observations: tuple[VehicleObservation, ...]
    eta_feature_context: EtaFeatureContext | None = None
    seat_risk_feature_context: SeatRiskFeatureContext | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observations", tuple(self.observations))
        if not isinstance(self.mapping_allows_bus_intelligence, bool):
            raise ValueError("mapping_allows_bus_intelligence must be boolean")
        require_probability(self.mapping_score, "mapping score")
        require_aware(self.user_arrival_at, "user_arrival_at")
        require_aware(self.evaluated_at, "evaluated_at")
        if not self.mapping_grade or not self.mapping_version or not self.target_stop_id:
            raise ValueError("mapping and target fields must be non-empty")
        if self.service_type not in {"SEATED", "GENERAL"}:
            raise ValueError("service_type must be SEATED or GENERAL")
        if self.eta_feature_context is not None and not isinstance(
            self.eta_feature_context, EtaFeatureContext
        ):
            raise ValueError("eta_feature_context must be ETA-specific")
        if self.seat_risk_feature_context is not None and not isinstance(
            self.seat_risk_feature_context, SeatRiskFeatureContext
        ):
            raise ValueError("seat_risk_feature_context must be Seat Risk-specific")


@dataclass(frozen=True, slots=True)
class CandidateVehicle:
    vehicle_ref: str
    eta: EtaPrediction
    wait_p50_seconds: int
    wait_p90_seconds: int
    remain_seat_observed: int | None
    seat_risk_at_boarding: SeatRiskPrediction | None
    boardability_proxy: float | None
    future_target_remaining_seats: int | None
    future_target_observed: bool

    def __post_init__(self) -> None:
        if self.wait_p50_seconds < 0 or self.wait_p90_seconds < self.wait_p50_seconds:
            raise ValueError("candidate wait must be non-negative and p90 >= p50")
        if self.boardability_proxy is not None:
            require_probability(self.boardability_proxy, "boardability proxy")
        if self.future_target_observed != (self.future_target_remaining_seats is not None):
            raise ValueError("future target observation flag/value mismatch")


@dataclass(frozen=True, slots=True)
class BusIntelligenceResult:
    enrichment_applied: bool
    candidate_vehicles: tuple[CandidateVehicle, ...]
    expected_wait_seconds: int | None
    p90_wait_seconds: int | None
    coverage: str
    confidence_score: float
    confidence_grade: str
    warnings: tuple[str, ...]
    model_provenance: tuple[ModelProvenance, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_vehicles", tuple(self.candidate_vehicles))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "model_provenance", tuple(self.model_provenance))
        require_probability(self.confidence_score, "confidence score")
        if self.enrichment_applied:
            if self.expected_wait_seconds is None or self.p90_wait_seconds is None:
                raise ValueError("applied enrichment requires numeric waits")
        elif self.expected_wait_seconds is not None or self.p90_wait_seconds is not None:
            raise ValueError("ineligible enrichment must not expose zero-like waits")
        if self.expected_wait_seconds is not None and self.expected_wait_seconds < 0:
            raise ValueError("expected wait cannot be negative")
        if self.p90_wait_seconds is not None and self.p90_wait_seconds < 0:
            raise ValueError("p90 wait cannot be negative")
        if (
            self.expected_wait_seconds is not None
            and self.p90_wait_seconds is not None
            and self.p90_wait_seconds < self.expected_wait_seconds
        ):
            raise ValueError("p90 wait must be greater than or equal to expected wait")
