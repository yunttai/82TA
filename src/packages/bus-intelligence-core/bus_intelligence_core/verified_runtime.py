"""Fail-closed production predictor trust boundaries.

This module owns only immutable attestations, complete-vector identities, and pure
ports. Artifact bytes, databases, worker feature sources, native model loading, and
network I/O remain outside Bus core. Existing generic predictor ports remain valid
for fixtures and explicit fallback composition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from hashlib import sha256
import json
from math import isfinite
import re
from typing import Protocol

from .domain import (
    EtaPrediction,
    SeatRiskPrediction,
    require_aware,
    require_probability,
)
from .ports import EtaPredictorInput, SeatRiskPredictorInput


VERIFIED_MODEL_ARTIFACT_FORMATS = frozenset(
    {"LIGHTGBM_TEXT", "LIGHTGBM_JSON"}
)
VERIFIED_DEPLOYMENT_ENVIRONMENTS = frozenset({"staging", "prod"})
VERIFIED_ETA_CALIBRATION_METHODS = frozenset({"CONFORMAL", "QUANTILE"})
VERIFIED_SEAT_RISK_CALIBRATION_METHODS = frozenset({"ISOTONIC", "PLATT"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VECTOR_VALUE_TYPES = (str, int, float, bool)


class VerifiedPredictorConfigurationError(ValueError):
    """Raised before serving when attested components do not bind exactly."""


def _native_probability(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a numeric probability")
    require_probability(value, field_name)


def _nonblank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerifiedPredictorConfigurationError(f"{field_name} must be non-blank")
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise VerifiedPredictorConfigurationError(
            f"{field_name} must be lowercase SHA-256"
        )
    return value


def _ordered_names(values: tuple[str, ...]) -> tuple[str, ...]:
    names = tuple(values)
    if not names or any(
        not isinstance(value, str) or not value.strip() for value in names
    ):
        raise VerifiedPredictorConfigurationError(
            "ordered_feature_names must be non-empty and non-blank"
        )
    if len(set(names)) != len(names):
        raise VerifiedPredictorConfigurationError(
            "ordered_feature_names must be unique"
        )
    if names[-1] != "missing_flags":
        raise VerifiedPredictorConfigurationError(
            "complete feature schema must end with missing_flags"
        )
    return names


def _validate_attestation(
    *,
    family: str,
    expected_family: str,
    model_version: str,
    full_feature_schema_version: str,
    ordered_feature_names: tuple[str, ...],
    artifact_sha256: str,
    verified_artifact_sha256: str,
    artifact_format: str,
    deployment_id: str,
    deployment_environment: str,
    deployment_state: str,
    readiness: str,
    calibrated: bool,
    calibration_method: str,
    calibration_sha256: str,
    verified_calibration_sha256: str,
) -> tuple[str, ...]:
    if family != expected_family:
        raise VerifiedPredictorConfigurationError(
            f"attestation family must be {expected_family}"
        )
    _nonblank(model_version, "model_version")
    _nonblank(full_feature_schema_version, "full_feature_schema_version")
    names = _ordered_names(ordered_feature_names)
    artifact_digest = _digest(artifact_sha256, "artifact_sha256")
    verified_artifact_digest = _digest(
        verified_artifact_sha256, "verified_artifact_sha256"
    )
    if artifact_digest != verified_artifact_digest:
        raise VerifiedPredictorConfigurationError("artifact SHA-256 is not verified")
    if artifact_format not in VERIFIED_MODEL_ARTIFACT_FORMATS:
        raise VerifiedPredictorConfigurationError(
            "artifact format is not allowlisted"
        )
    _nonblank(deployment_id, "deployment_id")
    if deployment_environment not in VERIFIED_DEPLOYMENT_ENVIRONMENTS:
        raise VerifiedPredictorConfigurationError(
            "verified predictor environment must be staging or prod"
        )
    if deployment_state != "ACTIVE" or readiness != "ACTIVE":
        raise VerifiedPredictorConfigurationError(
            "verified predictor deployment and readiness must both be ACTIVE"
        )
    if calibrated is not True:
        raise VerifiedPredictorConfigurationError(
            "verified predictor requires calibration evidence"
        )
    _nonblank(calibration_method, "calibration_method")
    calibration_digest = _digest(calibration_sha256, "calibration_sha256")
    verified_calibration_digest = _digest(
        verified_calibration_sha256, "verified_calibration_sha256"
    )
    if calibration_digest != verified_calibration_digest:
        raise VerifiedPredictorConfigurationError(
            "calibration SHA-256 is not verified"
        )
    return names


@dataclass(frozen=True, slots=True)
class VerifiedEtaPredictorAttestation:
    family: str
    model_version: str
    full_feature_schema_version: str
    ordered_feature_names: tuple[str, ...]
    artifact_sha256: str
    verified_artifact_sha256: str
    artifact_format: str
    deployment_id: str
    deployment_environment: str
    deployment_state: str
    readiness: str
    calibrated: bool
    calibration_method: str
    calibration_sha256: str
    verified_calibration_sha256: str
    source: str = "POSITION_MODEL"

    def __post_init__(self) -> None:
        names = _validate_attestation(
            family=self.family,
            expected_family="ETA",
            model_version=self.model_version,
            full_feature_schema_version=self.full_feature_schema_version,
            ordered_feature_names=self.ordered_feature_names,
            artifact_sha256=self.artifact_sha256,
            verified_artifact_sha256=self.verified_artifact_sha256,
            artifact_format=self.artifact_format,
            deployment_id=self.deployment_id,
            deployment_environment=self.deployment_environment,
            deployment_state=self.deployment_state,
            readiness=self.readiness,
            calibrated=self.calibrated,
            calibration_method=self.calibration_method,
            calibration_sha256=self.calibration_sha256,
            verified_calibration_sha256=self.verified_calibration_sha256,
        )
        object.__setattr__(self, "ordered_feature_names", names)
        if self.calibration_method not in VERIFIED_ETA_CALIBRATION_METHODS:
            raise VerifiedPredictorConfigurationError(
                "verified ETA calibration method is unsupported"
            )
        if self.source not in {"POSITION_MODEL", "HISTORICAL"}:
            raise VerifiedPredictorConfigurationError(
                "verified ETA source must be POSITION_MODEL or HISTORICAL"
            )


@dataclass(frozen=True, slots=True)
class VerifiedSeatRiskPredictorAttestation:
    family: str
    model_version: str
    full_feature_schema_version: str
    ordered_feature_names: tuple[str, ...]
    artifact_sha256: str
    verified_artifact_sha256: str
    artifact_format: str
    deployment_id: str
    deployment_environment: str
    deployment_state: str
    readiness: str
    calibrated: bool
    calibration_method: str
    calibration_sha256: str
    verified_calibration_sha256: str
    origin: str = "MODEL_PREDICTED"

    def __post_init__(self) -> None:
        names = _validate_attestation(
            family=self.family,
            expected_family="SEAT_RISK",
            model_version=self.model_version,
            full_feature_schema_version=self.full_feature_schema_version,
            ordered_feature_names=self.ordered_feature_names,
            artifact_sha256=self.artifact_sha256,
            verified_artifact_sha256=self.verified_artifact_sha256,
            artifact_format=self.artifact_format,
            deployment_id=self.deployment_id,
            deployment_environment=self.deployment_environment,
            deployment_state=self.deployment_state,
            readiness=self.readiness,
            calibrated=self.calibrated,
            calibration_method=self.calibration_method,
            calibration_sha256=self.calibration_sha256,
            verified_calibration_sha256=self.verified_calibration_sha256,
        )
        object.__setattr__(self, "ordered_feature_names", names)
        if self.calibration_method not in VERIFIED_SEAT_RISK_CALIBRATION_METHODS:
            raise VerifiedPredictorConfigurationError(
                "verified Seat Risk calibration method is unsupported"
            )
        if self.origin not in {"MODEL_PREDICTED", "HISTORICAL_PROXY"}:
            raise VerifiedPredictorConfigurationError(
                "verified Seat Risk origin is unsupported"
            )


def _normalize_vector(
    *,
    family: str,
    schema_version: str,
    feature_names: tuple[str, ...],
    values: tuple[object, ...],
    missing_flags: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[object, ...], tuple[str, ...], str]:
    _nonblank(schema_version, "complete vector schema_version")
    names = _ordered_names(feature_names)
    immutable_values = tuple(values)
    if len(names) != len(immutable_values):
        raise ValueError("complete vector names and values must have equal length")
    for value in immutable_values:
        if value is not None and not isinstance(value, _VECTOR_VALUE_TYPES):
            raise ValueError("complete vector values must be JSON scalar or None")
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("complete vector numeric values must be finite")
    flags = tuple(sorted(set(missing_flags)))
    if any(not isinstance(value, str) or not value.strip() for value in flags):
        raise ValueError("complete vector missing flags must be non-blank")
    if immutable_values[-1] != "|".join(flags):
        raise ValueError("complete vector missing_flags value does not match flags")
    payload = json.dumps(
        [family, schema_version, names, immutable_values, flags],
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return names, immutable_values, flags, sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class EtaCompleteFeatureVector:
    schema_version: str
    feature_names: tuple[str, ...]
    values: tuple[object, ...]
    missing_flags: tuple[str, ...]
    identity_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        names, values, flags, identity = _normalize_vector(
            family="ETA",
            schema_version=self.schema_version,
            feature_names=self.feature_names,
            values=self.values,
            missing_flags=self.missing_flags,
        )
        object.__setattr__(self, "feature_names", names)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "missing_flags", flags)
        object.__setattr__(self, "identity_sha256", identity)


@dataclass(frozen=True, slots=True)
class SeatRiskCompleteFeatureVector:
    schema_version: str
    feature_names: tuple[str, ...]
    values: tuple[object, ...]
    missing_flags: tuple[str, ...]
    identity_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        names, values, flags, identity = _normalize_vector(
            family="SEAT_RISK",
            schema_version=self.schema_version,
            feature_names=self.feature_names,
            values=self.values,
            missing_flags=self.missing_flags,
        )
        object.__setattr__(self, "feature_names", names)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "missing_flags", flags)
        object.__setattr__(self, "identity_sha256", identity)


class EtaCompleteVectorBuilder(Protocol):
    @property
    def family(self) -> str: ...

    @property
    def feature_schema_version(self) -> str: ...

    @property
    def feature_names(self) -> tuple[str, ...]: ...

    def build(self, value: EtaPredictorInput) -> EtaCompleteFeatureVector | None: ...


class SeatRiskCompleteVectorBuilder(Protocol):
    @property
    def family(self) -> str: ...

    @property
    def feature_schema_version(self) -> str: ...

    @property
    def feature_names(self) -> tuple[str, ...]: ...

    def build(
        self, value: SeatRiskPredictorInput
    ) -> SeatRiskCompleteFeatureVector | None: ...


@dataclass(frozen=True, slots=True)
class EtaNativePrediction:
    p50_seconds: int
    p90_seconds: int
    confidence: float
    out_of_distribution: bool = False

    def __post_init__(self) -> None:
        for name in ("p50_seconds", "p90_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"native ETA {name} must be a non-negative integer")
        if self.p90_seconds < self.p50_seconds:
            raise ValueError("native ETA p90 seconds must be at or after p50")
        _native_probability(self.confidence, "native ETA confidence")
        if not isinstance(self.out_of_distribution, bool):
            raise ValueError("native ETA out_of_distribution must be boolean")


@dataclass(frozen=True, slots=True)
class SeatRiskNativePrediction:
    no_seat_probability: float
    low_seat2_probability: float
    low_seat5_probability: float | None
    confidence: float
    out_of_distribution: bool = False

    def __post_init__(self) -> None:
        _native_probability(self.no_seat_probability, "native no-seat probability")
        _native_probability(
            self.low_seat2_probability, "native low-seat-2 probability"
        )
        if self.low_seat5_probability is not None:
            _native_probability(
                self.low_seat5_probability, "native low-seat-5 probability"
            )
        if self.no_seat_probability > self.low_seat2_probability:
            raise ValueError("native no-seat probability exceeds low-seat-2")
        if (
            self.low_seat5_probability is not None
            and self.low_seat2_probability > self.low_seat5_probability
        ):
            raise ValueError("native low-seat-2 probability exceeds low-seat-5")
        _native_probability(self.confidence, "native Seat Risk confidence")
        if not isinstance(self.out_of_distribution, bool):
            raise ValueError("native Seat Risk out_of_distribution must be boolean")


class SafeEtaModelRuntime(Protocol):
    @property
    def family(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def artifact_sha256(self) -> str: ...

    @property
    def artifact_format(self) -> str: ...

    @property
    def calibration_sha256(self) -> str: ...

    def predict(
        self, value: EtaCompleteFeatureVector
    ) -> EtaNativePrediction | None: ...


class SafeSeatRiskModelRuntime(Protocol):
    @property
    def family(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def artifact_sha256(self) -> str: ...

    @property
    def artifact_format(self) -> str: ...

    @property
    def calibration_sha256(self) -> str: ...

    def predict(
        self, value: SeatRiskCompleteFeatureVector
    ) -> SeatRiskNativePrediction | None: ...


def _component_identity(value: object, name: str) -> object:
    try:
        return getattr(value, name)
    except Exception as exc:
        raise VerifiedPredictorConfigurationError(
            f"verified component does not expose {name}"
        ) from exc


def _validate_components(
    *,
    family: str,
    attestation: VerifiedEtaPredictorAttestation
    | VerifiedSeatRiskPredictorAttestation,
    builder: object,
    runtime: object,
    expected_feature_schema_version: str,
    expected_feature_names: tuple[str, ...],
    required_environment: str,
) -> None:
    _nonblank(expected_feature_schema_version, "expected_feature_schema_version")
    names = _ordered_names(expected_feature_names)
    if required_environment not in VERIFIED_DEPLOYMENT_ENVIRONMENTS:
        raise VerifiedPredictorConfigurationError(
            "required_environment must be staging or prod"
        )
    if attestation.deployment_environment != required_environment:
        raise VerifiedPredictorConfigurationError("deployment environment mismatch")
    if attestation.full_feature_schema_version != expected_feature_schema_version:
        raise VerifiedPredictorConfigurationError("full feature schema version drift")
    if attestation.ordered_feature_names != names:
        raise VerifiedPredictorConfigurationError("full feature name/order drift")
    expected_builder = (family, expected_feature_schema_version, names)
    actual_builder = (
        _component_identity(builder, "family"),
        _component_identity(builder, "feature_schema_version"),
        tuple(_component_identity(builder, "feature_names")),
    )
    if actual_builder != expected_builder or not callable(getattr(builder, "build", None)):
        raise VerifiedPredictorConfigurationError("complete-vector builder identity drift")
    expected_runtime = (
        family,
        attestation.model_version,
        attestation.artifact_sha256,
        attestation.artifact_format,
        attestation.calibration_sha256,
    )
    actual_runtime = (
        _component_identity(runtime, "family"),
        _component_identity(runtime, "model_version"),
        _component_identity(runtime, "artifact_sha256"),
        _component_identity(runtime, "artifact_format"),
        _component_identity(runtime, "calibration_sha256"),
    )
    if actual_runtime != expected_runtime or not callable(getattr(runtime, "predict", None)):
        raise VerifiedPredictorConfigurationError("safe runtime identity drift")


def _vector_identity_matches(
    vector: EtaCompleteFeatureVector | SeatRiskCompleteFeatureVector,
    *,
    family: str,
    schema_version: str,
    feature_names: tuple[str, ...],
) -> bool:
    try:
        if (
            vector.schema_version != schema_version
            or vector.feature_names != feature_names
        ):
            return False
        _, _, _, identity = _normalize_vector(
            family=family,
            schema_version=vector.schema_version,
            feature_names=vector.feature_names,
            values=vector.values,
            missing_flags=vector.missing_flags,
        )
        return vector.identity_sha256 == identity
    except Exception:
        return False


class VerifiedEtaPredictor:
    """ETA predictor that binds one builder/runtime pair to an active attestation."""

    family = "ETA"

    def __init__(
        self,
        builder: EtaCompleteVectorBuilder,
        runtime: SafeEtaModelRuntime,
        attestation: VerifiedEtaPredictorAttestation,
        *,
        expected_feature_schema_version: str,
        expected_feature_names: tuple[str, ...],
        required_environment: str,
    ) -> None:
        if type(attestation) is not VerifiedEtaPredictorAttestation:
            raise VerifiedPredictorConfigurationError("ETA attestation type mismatch")
        _validate_components(
            family=self.family,
            attestation=attestation,
            builder=builder,
            runtime=runtime,
            expected_feature_schema_version=expected_feature_schema_version,
            expected_feature_names=expected_feature_names,
            required_environment=required_environment,
        )
        self._builder = builder
        self._runtime = runtime
        self._attestation = attestation

    @property
    def attestation(self) -> VerifiedEtaPredictorAttestation:
        return self._attestation

    def predict(self, value: EtaPredictorInput) -> EtaPrediction | None:
        if type(value) is not EtaPredictorInput:
            return None
        try:
            _validate_components(
                family=self.family,
                attestation=self._attestation,
                builder=self._builder,
                runtime=self._runtime,
                expected_feature_schema_version=(
                    self._attestation.full_feature_schema_version
                ),
                expected_feature_names=self._attestation.ordered_feature_names,
                required_environment=self._attestation.deployment_environment,
            )
        except Exception:
            return None
        if value.prediction_at is None:
            return None
        try:
            require_aware(value.prediction_at, "ETA prediction_at")
        except (AttributeError, TypeError, ValueError):
            return None
        try:
            vector = self._builder.build(value)
        except Exception:
            return None
        if type(vector) is not EtaCompleteFeatureVector:
            return None
        if not _vector_identity_matches(
            vector,
            family=self.family,
            schema_version=self._attestation.full_feature_schema_version,
            feature_names=self._attestation.ordered_feature_names,
        ):
            return None
        try:
            output = self._runtime.predict(vector)
        except Exception:
            return None
        try:
            if type(output) is not EtaNativePrediction:
                return None
            validated_output = EtaNativePrediction(
                output.p50_seconds,
                output.p90_seconds,
                output.confidence,
                output.out_of_distribution,
            )
            if validated_output.out_of_distribution:
                return None
            return EtaPrediction(
                p50_arrival_at=value.prediction_at
                + timedelta(seconds=validated_output.p50_seconds),
                p90_arrival_at=value.prediction_at
                + timedelta(seconds=validated_output.p90_seconds),
                source=self._attestation.source,
                model_version=self._attestation.model_version,
                confidence=validated_output.confidence,
                model_readiness=self._attestation.readiness,
            )
        except Exception:
            return None


class VerifiedSeatRiskPredictor:
    """Seat predictor that binds a separately calibrated active model and vector."""

    family = "SEAT_RISK"

    def __init__(
        self,
        builder: SeatRiskCompleteVectorBuilder,
        runtime: SafeSeatRiskModelRuntime,
        attestation: VerifiedSeatRiskPredictorAttestation,
        *,
        expected_feature_schema_version: str,
        expected_feature_names: tuple[str, ...],
        required_environment: str,
    ) -> None:
        if type(attestation) is not VerifiedSeatRiskPredictorAttestation:
            raise VerifiedPredictorConfigurationError(
                "Seat Risk attestation type mismatch"
            )
        _validate_components(
            family=self.family,
            attestation=attestation,
            builder=builder,
            runtime=runtime,
            expected_feature_schema_version=expected_feature_schema_version,
            expected_feature_names=expected_feature_names,
            required_environment=required_environment,
        )
        self._builder = builder
        self._runtime = runtime
        self._attestation = attestation

    @property
    def attestation(self) -> VerifiedSeatRiskPredictorAttestation:
        return self._attestation

    def predict(self, value: SeatRiskPredictorInput) -> SeatRiskPrediction | None:
        if type(value) is not SeatRiskPredictorInput:
            return None
        try:
            require_aware(value.prediction_at, "Seat Risk prediction_at")
        except (AttributeError, TypeError, ValueError):
            return None
        try:
            _validate_components(
                family=self.family,
                attestation=self._attestation,
                builder=self._builder,
                runtime=self._runtime,
                expected_feature_schema_version=(
                    self._attestation.full_feature_schema_version
                ),
                expected_feature_names=self._attestation.ordered_feature_names,
                required_environment=self._attestation.deployment_environment,
            )
        except Exception:
            return None
        try:
            vector = self._builder.build(value)
        except Exception:
            return None
        if type(vector) is not SeatRiskCompleteFeatureVector:
            return None
        if not _vector_identity_matches(
            vector,
            family=self.family,
            schema_version=self._attestation.full_feature_schema_version,
            feature_names=self._attestation.ordered_feature_names,
        ):
            return None
        try:
            output = self._runtime.predict(vector)
        except Exception:
            return None
        try:
            if type(output) is not SeatRiskNativePrediction:
                return None
            validated_output = SeatRiskNativePrediction(
                output.no_seat_probability,
                output.low_seat2_probability,
                output.low_seat5_probability,
                output.confidence,
                output.out_of_distribution,
            )
            if validated_output.out_of_distribution:
                return None
            return SeatRiskPrediction(
                no_seat_probability=validated_output.no_seat_probability,
                low_seat2_probability=validated_output.low_seat2_probability,
                low_seat5_probability=validated_output.low_seat5_probability,
                model_version=self._attestation.model_version,
                confidence=validated_output.confidence,
                origin=self._attestation.origin,
                model_readiness=self._attestation.readiness,
            )
        except Exception:
            return None


__all__ = [
    "EtaCompleteFeatureVector",
    "EtaCompleteVectorBuilder",
    "EtaNativePrediction",
    "SafeEtaModelRuntime",
    "SafeSeatRiskModelRuntime",
    "SeatRiskCompleteFeatureVector",
    "SeatRiskCompleteVectorBuilder",
    "SeatRiskNativePrediction",
    "VERIFIED_DEPLOYMENT_ENVIRONMENTS",
    "VERIFIED_ETA_CALIBRATION_METHODS",
    "VERIFIED_MODEL_ARTIFACT_FORMATS",
    "VERIFIED_SEAT_RISK_CALIBRATION_METHODS",
    "VerifiedEtaPredictor",
    "VerifiedEtaPredictorAttestation",
    "VerifiedPredictorConfigurationError",
    "VerifiedSeatRiskPredictor",
    "VerifiedSeatRiskPredictorAttestation",
]
