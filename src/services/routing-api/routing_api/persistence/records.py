from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping
from uuid import UUID


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _probability(value: Decimal | None, field_name: str) -> None:
    if value is not None and (not value.is_finite() or not Decimal("0") <= value <= Decimal("1")):
        raise ValueError(f"{field_name} must be null or in [0, 1]")


@dataclass(frozen=True, slots=True)
class ProviderOperationRecord:
    provider_code: str
    provider_category: str
    operation: str
    documentation_state: str
    key_verification_state: str
    production_state: str
    health: str
    consecutive_failures: int
    checked_at: datetime
    enabled: bool = False
    config_without_secret: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    source_code: str
    data_type: str
    owner: str
    partition_key: str
    status: str
    cursor: Mapping[str, object]
    last_observed_at: datetime | None
    last_success_at: datetime | None


@dataclass(frozen=True, slots=True)
class MappingRecord:
    provider_entity_id: UUID
    transport_route_id: UUID | None
    transport_stop_id: UUID | None
    direction: str | None
    score: Decimal
    grade: str
    signal_breakdown: Mapping[str, object]
    algorithm_version: str
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True, slots=True)
class ModelArtifactRecord:
    id: UUID
    purpose: str
    version: str
    status: str
    artifact_uri: str
    artifact_sha256: str
    feature_schema_version: str


@dataclass(frozen=True, slots=True)
class DeploymentRecord:
    id: UUID
    purpose: str
    version: str
    environment: str
    state: str
    traffic_fraction: Decimal
    activated_at: datetime | None
    deactivated_at: datetime | None


@dataclass(frozen=True, slots=True)
class OptimizationRunRecord:
    request_id: str
    request_fingerprint: str
    origin_wkt: str
    destination_wkt: str
    departure_time: datetime
    constraints: Mapping[str, object]
    status: str
    ranking_policy_version: str
    duration_ms: int | None
    provider_summary: Mapping[str, object]
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.departure_time, "departure_time"),
            (self.created_at, "created_at"),
            (self.expires_at, "expires_at"),
        ):
            _aware(value, name)
        if self.expires_at <= self.created_at:
            raise ValueError("optimization expiry must follow creation")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("duration_ms must be null or nonnegative")


@dataclass(frozen=True, slots=True)
class OptimizationCandidateRecord:
    route_key: str
    pattern: str
    p50_seconds: int
    p90_seconds: int
    taxi_cost_expected: int
    taxi_cost_upper: int
    total_fare_expected: int
    walk_seconds: int
    transfer_count: int
    reliability_score: Decimal
    pareto: bool
    reason_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.p50_seconds < 0 or self.p90_seconds < self.p50_seconds:
            raise ValueError("candidate duration must satisfy 0 <= P50 <= P90")
        if self.taxi_cost_expected < 0 or self.taxi_cost_upper < self.taxi_cost_expected:
            raise ValueError("candidate taxi cost range is invalid")
        if min(self.total_fare_expected, self.walk_seconds, self.transfer_count) < 0:
            raise ValueError("candidate fare/walk/transfers must be nonnegative")
        _probability(self.reliability_score, "reliability_score")


@dataclass(frozen=True, slots=True)
class OptimizationLegRecord:
    route_key: str
    sequence: int
    mode: str
    expected_start_at: datetime | None
    expected_end_at: datetime | None
    p50_seconds: int
    p90_seconds: int
    fare_expected: int
    provenance: tuple[Mapping[str, object] | str, ...]
    transport_route_id: UUID | None = None
    from_stop_id: UUID | None = None
    to_stop_id: UUID | None = None
    geometry_wkt: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0 or self.p50_seconds < 0 or self.p90_seconds < self.p50_seconds:
            raise ValueError("leg sequence/duration is invalid")
        if self.fare_expected < 0:
            raise ValueError("leg fare must be nonnegative")
        if self.expected_start_at is not None:
            _aware(self.expected_start_at, "expected_start_at")
        if self.expected_end_at is not None:
            _aware(self.expected_end_at, "expected_end_at")
        if (
            self.expected_start_at is not None
            and self.expected_end_at is not None
            and self.expected_end_at < self.expected_start_at
        ):
            raise ValueError("leg end cannot precede start")


@dataclass(frozen=True, slots=True)
class OptimizationBusLegEnrichmentRecord:
    route_key: str
    leg_sequence: int
    entity_mapping_id: UUID | None
    expected_wait_seconds: int
    p90_wait_seconds: int
    boardability_proxy: Decimal | None
    no_seat_probability: Decimal | None
    coverage: str
    eta_model_version: str | None
    seat_model_version: str | None
    candidate_vehicles: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        if self.leg_sequence < 0 or self.expected_wait_seconds < 0:
            raise ValueError("bus leg sequence/wait must be nonnegative")
        if self.p90_wait_seconds < self.expected_wait_seconds:
            raise ValueError("bus P90 wait must be >= expected wait")
        _probability(self.boardability_proxy, "boardability_proxy")
        _probability(self.no_seat_probability, "no_seat_probability")
        if not self.coverage.strip():
            raise ValueError("bus coverage must not be blank")


@dataclass(frozen=True, slots=True)
class OptimizationTransferEvaluationRecord:
    route_key: str
    leg_sequence: int
    available_seconds: int
    required_seconds: int
    margin_p50_seconds: int
    margin_p90_seconds: int
    success_proxy: Decimal | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.leg_sequence < 0 or min(self.available_seconds, self.required_seconds) < 0:
            raise ValueError("transfer sequence/available/required must be nonnegative")
        _probability(self.success_proxy, "success_proxy")


@dataclass(frozen=True, slots=True)
class OptimizationResultRecord:
    run: OptimizationRunRecord
    candidates: tuple[OptimizationCandidateRecord, ...]
    legs: tuple[OptimizationLegRecord, ...]
    bus_enrichments: tuple[OptimizationBusLegEnrichmentRecord, ...] = ()
    transfer_evaluations: tuple[OptimizationTransferEvaluationRecord, ...] = ()

    def __post_init__(self) -> None:
        route_keys = tuple(item.route_key for item in self.candidates)
        if len(route_keys) != len(set(route_keys)):
            raise ValueError("candidate route keys must be unique")
        leg_keys = tuple((item.route_key, item.sequence) for item in self.legs)
        if len(leg_keys) != len(set(leg_keys)) or any(
            route_key not in route_keys for route_key, _ in leg_keys
        ):
            raise ValueError("legs must uniquely reference a persisted candidate")
        if any(
            (item.route_key, item.leg_sequence) not in leg_keys
            for item in (*self.bus_enrichments, *self.transfer_evaluations)
        ):
            raise ValueError("enrichment/transfer must reference a persisted leg")
        budget = self.run.constraints.get("taxiBudget")
        if isinstance(budget, Mapping):
            upper = budget.get("maxAmount")
            if isinstance(upper, int) and not isinstance(upper, bool):
                if any(item.taxi_cost_upper > upper for item in self.candidates):
                    raise ValueError("candidate exceeds strict taxi upper budget")
