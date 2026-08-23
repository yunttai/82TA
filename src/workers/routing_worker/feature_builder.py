"""One versioned train/serve feature builder for ETA and Seat Risk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from types import MappingProxyType
from typing import Mapping

from bus_intelligence_core import (
    DEFAULT_ETA_FEATURE_CONTEXT_POLICY,
    DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY,
    ETA_CONTEXT_FEATURE_NAMES,
    ETA_CONTEXT_SERVING_SCHEMA_VERSION,
    SEAT_RISK_CONTEXT_FEATURE_NAMES,
    SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
    ContextFeatureVector,
    EtaFeatureContext,
    FeatureContextPolicy,
    SeatRiskFeatureContext,
    build_eta_context_features,
    build_seat_risk_context_features,
)
from .data_quality.dataset_foundation import DatasetInvariantError
from .feature_schema import (
    ETA_CORE_FEATURE_NAMES,
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_CORE_FEATURE_NAMES,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)


@dataclass(frozen=True, slots=True)
class NormalizedFeatureObservation:
    trip_id: str
    route_id: str
    direction: str
    observed_at: datetime
    ingested_at: datetime
    valid_at: datetime
    current_station_sequence: int
    target_station_sequence: int
    recent_segment_seconds_1: float | None = None
    recent_segment_seconds_3: float | None = None
    recent_segment_seconds_5: float | None = None
    historical_segment_seconds: float | None = None
    headway_seconds: float | None = None
    current_remaining_seats: int | None = None
    current_crowded_code: int | None = None
    capacity_confidence: float | None = None
    recent_seat_delta: float | None = None
    query_at: datetime | None = None
    eta_feature_context: EtaFeatureContext | None = None
    seat_risk_feature_context: SeatRiskFeatureContext | None = None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.trip_id, self.route_id, self.direction)):
            raise DatasetInvariantError("trip, route and direction must not be blank")
        query_at = self.valid_at if self.query_at is None else self.query_at
        object.__setattr__(self, "query_at", query_at)
        for name in ("observed_at", "ingested_at", "valid_at", "query_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise DatasetInvariantError(f"{name} must be timezone-aware")
        if any(
            value > query_at
            for value in (self.observed_at, self.ingested_at, self.valid_at)
        ):
            raise DatasetInvariantError(
                "feature observation, ingestion and validity clocks must be available as-of query_at"
            )
        if self.valid_at < self.observed_at:
            raise DatasetInvariantError("valid_at cannot precede observed_at")
        if self.eta_feature_context is not None and not isinstance(
            self.eta_feature_context, EtaFeatureContext
        ):
            raise DatasetInvariantError("ETA context must use EtaFeatureContext")
        if self.seat_risk_feature_context is not None and not isinstance(
            self.seat_risk_feature_context, SeatRiskFeatureContext
        ):
            raise DatasetInvariantError(
                "Seat Risk context must use SeatRiskFeatureContext"
            )
        if self.current_station_sequence < 0:
            raise DatasetInvariantError("current station sequence must be non-negative")
        if self.target_station_sequence < self.current_station_sequence:
            raise DatasetInvariantError("target sequence cannot precede current sequence")
        if self.current_remaining_seats is not None and self.current_remaining_seats < 0:
            raise DatasetInvariantError("remaining seats must be non-negative")
        if self.capacity_confidence is not None and not 0 <= self.capacity_confidence <= 1:
            raise DatasetInvariantError("capacity confidence must be in [0, 1]")
        numeric = (
            self.recent_segment_seconds_1,
            self.recent_segment_seconds_3,
            self.recent_segment_seconds_5,
            self.historical_segment_seconds,
            self.headway_seconds,
            self.recent_seat_delta,
        )
        if any(value is not None and not isfinite(value) for value in numeric):
            raise DatasetInvariantError("numeric features must be finite")
        normalized_flags = tuple(sorted(set(self.quality_flags)))
        if any(not value.strip() for value in normalized_flags):
            raise DatasetInvariantError("quality flags must not be blank")
        object.__setattr__(self, "quality_flags", normalized_flags)


@dataclass(frozen=True, slots=True)
class FeatureVector:
    family: str
    schema_version: str
    feature_names: tuple[str, ...]
    values: tuple[object, ...]
    missing_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.feature_names) != len(self.values):
            raise DatasetInvariantError("feature names and values must have equal length")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise DatasetInvariantError("feature names must be unique")

    @property
    def as_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(dict(zip(self.feature_names, self.values, strict=True)))


def _common(observation: NormalizedFeatureObservation) -> dict[str, object]:
    # Model freshness is observation age at the immutable train/serve as-of clock.
    # Ingestion lag remains a separately validated data-quality property.
    freshness = int(
        (observation.query_at - observation.observed_at).total_seconds()
    )
    return {
        "route_id": observation.route_id,
        "direction": observation.direction,
        "current_station_sequence": observation.current_station_sequence,
        "target_station_sequence": observation.target_station_sequence,
        "remaining_stops": observation.target_station_sequence - observation.current_station_sequence,
        "headway_seconds": observation.headway_seconds,
        "observed_hour": observation.observed_at.hour,
        "day_of_week": observation.observed_at.weekday(),
        "freshness_seconds": freshness,
    }


def _vector(
    family: str,
    version: str,
    values: dict[str, object],
    quality_flags: tuple[str, ...],
    context: ContextFeatureVector,
) -> FeatureVector:
    if context.family != family:
        raise DatasetInvariantError("context vector family does not match feature family")
    if set(values) & set(context.feature_names):
        raise DatasetInvariantError("context feature collides with a core feature")
    combined = {**values, **dict(context.as_mapping)}
    missing = tuple(
        sorted(
            set(quality_flags)
            | set(context.missing_flags)
            | {name for name, value in combined.items() if value is None}
        )
    )
    combined["missing_flags"] = "|".join(missing)
    names = tuple(combined)
    return FeatureVector(
        family, version, names, tuple(combined[name] for name in names), missing
    )


def build_eta_features(
    observation: NormalizedFeatureObservation,
    *,
    context_policy: FeatureContextPolicy = DEFAULT_ETA_FEATURE_CONTEXT_POLICY,
) -> FeatureVector:
    values = _common(observation)
    values.update(
        {
            "recent_segment_seconds_1": observation.recent_segment_seconds_1,
            "recent_segment_seconds_3": observation.recent_segment_seconds_3,
            "recent_segment_seconds_5": observation.recent_segment_seconds_5,
            "historical_segment_seconds": observation.historical_segment_seconds,
        }
    )
    ordered = {name: values[name] for name in ETA_CORE_FEATURE_NAMES}
    context = build_eta_context_features(
        observation.eta_feature_context,
        observation.query_at,
        policy=context_policy,
    )
    if (
        context.schema_version != ETA_CONTEXT_SERVING_SCHEMA_VERSION
        or context.feature_names != ETA_CONTEXT_FEATURE_NAMES
    ):
        raise DatasetInvariantError("ETA serving context schema drift")
    result = _vector(
        "ETA", ETA_SCHEMA_VERSION, ordered, observation.quality_flags, context
    )
    if result.feature_names != ETA_FEATURE_NAMES:
        raise DatasetInvariantError("ETA full feature schema drift")
    return result


def build_seat_features(
    observation: NormalizedFeatureObservation,
    *,
    context_policy: FeatureContextPolicy = DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY,
) -> FeatureVector:
    values = _common(observation)
    values.update(
        {
            "current_remaining_seats": observation.current_remaining_seats,
            "current_crowded_code": observation.current_crowded_code,
            "capacity_confidence": observation.capacity_confidence,
            "recent_seat_delta": observation.recent_seat_delta,
        }
    )
    ordered = {name: values[name] for name in SEAT_CORE_FEATURE_NAMES}
    context = build_seat_risk_context_features(
        observation.seat_risk_feature_context,
        observation.query_at,
        policy=context_policy,
    )
    if (
        context.schema_version != SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION
        or context.feature_names != SEAT_RISK_CONTEXT_FEATURE_NAMES
    ):
        raise DatasetInvariantError("Seat Risk serving context schema drift")
    result = _vector(
        "SEAT_RISK", SEAT_SCHEMA_VERSION, ordered, observation.quality_flags, context
    )
    if result.feature_names != SEAT_FEATURE_NAMES:
        raise DatasetInvariantError("Seat Risk full feature schema drift")
    return result


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    dataset_version: str
    feature_schema_version: str
    target_schema_version: str
    row_count: int
    content_sha256: str
    created_at: datetime


def make_dataset_snapshot(
    *, dataset_version: str, feature_schema_version: str,
    target_schema_version: str, rows: tuple[Mapping[str, object], ...], created_at: datetime,
) -> DatasetSnapshot:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise DatasetInvariantError("snapshot created_at must be timezone-aware")
    if not all(value.strip() for value in (dataset_version, feature_schema_version, target_schema_version)):
        raise DatasetInvariantError("dataset and schema versions must not be blank")
    try:
        payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    except (TypeError, ValueError) as exc:
        raise DatasetInvariantError("dataset rows must be canonical JSON") from exc
    return DatasetSnapshot(
        dataset_version, feature_schema_version, target_schema_version, len(rows),
        sha256(payload.encode("utf-8")).hexdigest(), created_at,
    )
