"""Durable feature-source ports and complete train/serve vector builders.

The ports deliberately expose only normalized Routing feature records. A production
adapter may read a reviewed Routing DB/cache view, but raw Provider payloads, Service
identity, wall-clock fallback, and future target outcomes are outside this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from bus_intelligence_core import (
    DEFAULT_ETA_FEATURE_CONTEXT_POLICY,
    DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY,
    EtaCompleteFeatureVector,
    EtaPredictorInput,
    FeatureContextPolicy,
    SeatRiskCompleteFeatureVector,
    SeatRiskPredictorInput,
)

from .feature_builder import (
    FeatureVector,
    NormalizedFeatureObservation,
    build_eta_features,
    build_seat_features,
)
from .feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)


class ServingFeatureSourceError(ValueError):
    """Raised when a durable source cannot prove an as-of complete core record."""


def _aware(value: datetime | None, name: str) -> datetime:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ServingFeatureSourceError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class ServingFeaturePolicy:
    maximum_core_age_seconds: int = 180

    def __post_init__(self) -> None:
        if (
            not isinstance(self.maximum_core_age_seconds, int)
            or isinstance(self.maximum_core_age_seconds, bool)
            or self.maximum_core_age_seconds < 0
        ):
            raise ServingFeatureSourceError(
                "maximum core feature age must be a non-negative integer"
            )


@dataclass(frozen=True, slots=True)
class EtaServingFeatureRecord:
    vehicle_ref: str
    boarding_stop_id: str
    observation: NormalizedFeatureObservation

    def __post_init__(self) -> None:
        if not self.vehicle_ref.strip() or not self.boarding_stop_id.strip():
            raise ServingFeatureSourceError("ETA serving feature identity is required")
        if not isinstance(self.observation, NormalizedFeatureObservation):
            raise ServingFeatureSourceError(
                "ETA source must return a normalized feature observation"
            )


@dataclass(frozen=True, slots=True)
class SeatRiskServingFeatureRecord:
    vehicle_ref: str
    boarding_stop_id: str
    target_stop_id: str
    observation: NormalizedFeatureObservation

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.vehicle_ref,
                self.boarding_stop_id,
                self.target_stop_id,
            )
        ):
            raise ServingFeatureSourceError(
                "Seat Risk serving feature identity is required"
            )
        if not isinstance(self.observation, NormalizedFeatureObservation):
            raise ServingFeatureSourceError(
                "Seat Risk source must return a normalized feature observation"
            )


class EtaServingFeatureSource(Protocol):
    """Durable ETA source; load must be one immutable as-of lookup or return None."""

    def load(self, value: EtaPredictorInput) -> EtaServingFeatureRecord | None: ...


class SeatRiskServingFeatureSource(Protocol):
    """Durable Seat source; load must be one immutable as-of lookup or return None."""

    def load(
        self, value: SeatRiskPredictorInput
    ) -> SeatRiskServingFeatureRecord | None: ...


_ETA_REQUIRED_CORE = (
    "recent_segment_seconds_1",
    "recent_segment_seconds_3",
    "recent_segment_seconds_5",
    "historical_segment_seconds",
    "headway_seconds",
)
_SEAT_REQUIRED_CORE = (
    "current_remaining_seats",
    "current_crowded_code",
    "capacity_confidence",
    "recent_seat_delta",
    "headway_seconds",
)


def _validate_core(
    observation: NormalizedFeatureObservation,
    *,
    query_at: datetime,
    observed_at: datetime,
    route_id: str,
    direction: str,
    required: tuple[str, ...],
    policy: ServingFeaturePolicy,
) -> None:
    if observation.route_id != route_id or observation.direction != direction:
        raise ServingFeatureSourceError("durable feature route/direction mismatch")
    if observation.observed_at != observed_at:
        raise ServingFeatureSourceError("durable feature observation clock mismatch")
    if observation.query_at != query_at:
        raise ServingFeatureSourceError("durable feature as-of clock mismatch")
    age = (query_at - observation.observed_at).total_seconds()
    if age < 0:
        raise ServingFeatureSourceError("future core feature observation is forbidden")
    if age > policy.maximum_core_age_seconds:
        raise ServingFeatureSourceError("stale core feature observation is forbidden")
    missing = tuple(name for name in required if getattr(observation, name) is None)
    if missing:
        raise ServingFeatureSourceError(
            f"required core serving features are missing: {missing}"
        )


def _eta_complete(value: FeatureVector) -> EtaCompleteFeatureVector:
    if (
        value.family != "ETA"
        or value.schema_version != ETA_SCHEMA_VERSION
        or value.feature_names != ETA_FEATURE_NAMES
    ):
        raise ServingFeatureSourceError("ETA complete feature schema drift")
    return EtaCompleteFeatureVector(
        value.schema_version,
        value.feature_names,
        value.values,
        value.missing_flags,
    )


def _seat_complete(value: FeatureVector) -> SeatRiskCompleteFeatureVector:
    if (
        value.family != "SEAT_RISK"
        or value.schema_version != SEAT_SCHEMA_VERSION
        or value.feature_names != SEAT_FEATURE_NAMES
    ):
        raise ServingFeatureSourceError("Seat Risk complete feature schema drift")
    return SeatRiskCompleteFeatureVector(
        value.schema_version,
        value.feature_names,
        value.values,
        value.missing_flags,
    )


class DurableEtaCompleteVectorBuilder:
    family = "ETA"
    feature_schema_version = ETA_SCHEMA_VERSION
    feature_names = ETA_FEATURE_NAMES

    def __init__(
        self,
        source: EtaServingFeatureSource,
        *,
        policy: ServingFeaturePolicy = ServingFeaturePolicy(),
        context_policy: FeatureContextPolicy = DEFAULT_ETA_FEATURE_CONTEXT_POLICY,
    ) -> None:
        if not callable(getattr(source, "load", None)):
            raise ServingFeatureSourceError("ETA durable feature source is invalid")
        self._source = source
        self._policy = policy
        self._context_policy = context_policy

    def build(self, value: EtaPredictorInput) -> EtaCompleteFeatureVector | None:
        if not isinstance(value, EtaPredictorInput):
            raise ServingFeatureSourceError("ETA builder input family mismatch")
        query_at = _aware(value.prediction_at, "ETA prediction_at")
        _aware(value.observed_at, "ETA observed_at")
        record = self._source.load(value)
        if record is None:
            return None
        if type(record) is not EtaServingFeatureRecord:
            raise ServingFeatureSourceError("ETA source record family mismatch")
        if (record.vehicle_ref, record.boarding_stop_id) != (
            value.vehicle_ref,
            value.boarding_stop_id,
        ):
            raise ServingFeatureSourceError("ETA durable feature identity mismatch")
        source = record.observation
        if source.seat_risk_feature_context is not None:
            raise ServingFeatureSourceError("Seat Risk context entered the ETA source")
        if source.eta_feature_context not in (None, value.feature_context):
            raise ServingFeatureSourceError("ETA source/request context mismatch")
        observation = replace(
            source,
            query_at=query_at,
            eta_feature_context=value.feature_context,
            seat_risk_feature_context=None,
        )
        _validate_core(
            observation,
            query_at=query_at,
            observed_at=value.observed_at,
            route_id=value.route_id,
            direction=value.direction,
            required=_ETA_REQUIRED_CORE,
            policy=self._policy,
        )
        return _eta_complete(
            build_eta_features(observation, context_policy=self._context_policy)
        )


class DurableSeatRiskCompleteVectorBuilder:
    family = "SEAT_RISK"
    feature_schema_version = SEAT_SCHEMA_VERSION
    feature_names = SEAT_FEATURE_NAMES

    def __init__(
        self,
        source: SeatRiskServingFeatureSource,
        *,
        policy: ServingFeaturePolicy = ServingFeaturePolicy(),
        context_policy: FeatureContextPolicy = DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY,
    ) -> None:
        if not callable(getattr(source, "load", None)):
            raise ServingFeatureSourceError(
                "Seat Risk durable feature source is invalid"
            )
        self._source = source
        self._policy = policy
        self._context_policy = context_policy

    def build(
        self, value: SeatRiskPredictorInput
    ) -> SeatRiskCompleteFeatureVector | None:
        if not isinstance(value, SeatRiskPredictorInput):
            raise ServingFeatureSourceError("Seat Risk builder input family mismatch")
        query_at = _aware(value.prediction_at, "Seat Risk prediction_at")
        _aware(value.observed_at, "Seat Risk observed_at")
        record = self._source.load(value)
        if record is None:
            return None
        if type(record) is not SeatRiskServingFeatureRecord:
            raise ServingFeatureSourceError("Seat Risk source record family mismatch")
        if (
            record.vehicle_ref,
            record.boarding_stop_id,
            record.target_stop_id,
        ) != (value.vehicle_ref, value.boarding_stop_id, value.target_stop_id):
            raise ServingFeatureSourceError(
                "Seat Risk durable feature identity mismatch"
            )
        source = record.observation
        if source.eta_feature_context is not None:
            raise ServingFeatureSourceError("ETA context entered the Seat Risk source")
        if source.seat_risk_feature_context not in (None, value.feature_context):
            raise ServingFeatureSourceError("Seat Risk source/request context mismatch")
        observation = replace(
            source,
            query_at=query_at,
            eta_feature_context=None,
            seat_risk_feature_context=value.feature_context,
        )
        _validate_core(
            observation,
            query_at=query_at,
            observed_at=value.observed_at,
            route_id=value.route_id,
            direction=value.direction,
            required=_SEAT_REQUIRED_CORE,
            policy=self._policy,
        )
        return _seat_complete(
            build_seat_features(observation, context_policy=self._context_policy)
        )


__all__ = [
    "DurableEtaCompleteVectorBuilder",
    "DurableSeatRiskCompleteVectorBuilder",
    "EtaServingFeatureRecord",
    "EtaServingFeatureSource",
    "SeatRiskServingFeatureRecord",
    "SeatRiskServingFeatureSource",
    "ServingFeaturePolicy",
    "ServingFeatureSourceError",
]
