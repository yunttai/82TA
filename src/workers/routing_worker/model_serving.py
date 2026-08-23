"""Verified native-model runtime adapters and predictor composition factories.

Artifact and calibration paths are fixed at composition time, verified before a
native loader is called, and never accepted from a prediction request. The loaders
remain injected so importing this package cannot load bytes or imply LightGBM/model
availability.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol

from bus_intelligence_core import (
    EtaCompleteFeatureVector,
    EtaNativePrediction,
    VERIFIED_ETA_CALIBRATION_METHODS,
    VERIFIED_SEAT_RISK_CALIBRATION_METHODS,
    SeatRiskCompleteFeatureVector,
    SeatRiskNativePrediction,
    VerifiedEtaPredictor,
    VerifiedEtaPredictorAttestation,
    VerifiedSeatRiskPredictor,
    VerifiedSeatRiskPredictorAttestation,
)

from .feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)
from .model_jobs.artifact_bundle import ArtifactBundleManifest, verify_bundle
from .model_jobs.model_foundation import ArtifactIntegrityError
from .model_jobs.registry import Deployment, ModelState, RegistryEntry
from .serving_features import (
    DurableEtaCompleteVectorBuilder,
    DurableSeatRiskCompleteVectorBuilder,
    EtaServingFeatureSource,
    SeatRiskServingFeatureSource,
    ServingFeaturePolicy,
)


class ModelServingConfigurationError(ValueError):
    """Raised before native loading when serving evidence is not exact."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class VerifiedServingLifecycle:
    registry_entry: RegistryEntry
    deployment: Deployment
    deployment_id: str
    calibration_method: str
    calibration_sha256: str
    feature_schema_sha256: str
    validation_evidence_sha256: str

    def __post_init__(self) -> None:
        if type(self.registry_entry) is not RegistryEntry:
            raise ModelServingConfigurationError("registry lifecycle evidence is required")
        if type(self.deployment) is not Deployment:
            raise ModelServingConfigurationError("deployment lifecycle evidence is required")
        if not self.deployment_id.strip() or not self.calibration_method.strip():
            raise ModelServingConfigurationError(
                "deployment identity and calibration method are required"
            )
        allowed_calibration = {
            "ETA": VERIFIED_ETA_CALIBRATION_METHODS,
            "SEAT_RISK": VERIFIED_SEAT_RISK_CALIBRATION_METHODS,
        }.get(self.registry_entry.artifact.model_family, frozenset())
        if self.calibration_method not in allowed_calibration:
            raise ModelServingConfigurationError(
                "calibration method does not match the model family"
            )
        if self.deployment.environment not in {"staging", "prod"}:
            raise ModelServingConfigurationError(
                "verified serving environment must be staging or prod"
            )
        if (
            self.registry_entry.state is not ModelState.ACTIVE
            or self.deployment.state is not ModelState.ACTIVE
            or self.deployment.traffic_fraction != 1
        ):
            raise ModelServingConfigurationError(
                "registry and full-traffic deployment must both be ACTIVE"
            )
        if (
            self.deployment.model_version
            != self.registry_entry.artifact.model_version
        ):
            raise ModelServingConfigurationError(
                "registry and deployment model versions differ"
            )
        if self.deployment.activated_at < self.registry_entry.updated_at:
            raise ModelServingConfigurationError(
                "deployment activation predates registry readiness"
            )
        digests = (
            self.calibration_sha256,
            self.feature_schema_sha256,
            self.validation_evidence_sha256,
        )
        if any(_SHA256.fullmatch(value) is None for value in digests):
            raise ModelServingConfigurationError(
                "serving lifecycle digests must be lowercase SHA-256"
            )
        if (
            self.registry_entry.validation_evidence_sha256
            != self.validation_evidence_sha256
        ):
            raise ModelServingConfigurationError(
                "validation evidence digest does not match the registry"
            )


class EtaNativeSession(Protocol):
    def predict(self, values: tuple[object, ...]) -> EtaNativePrediction | None: ...


class SeatRiskNativeSession(Protocol):
    def predict(
        self, values: tuple[object, ...]
    ) -> SeatRiskNativePrediction | None: ...


class EtaNativeRuntimeLoader(Protocol):
    """Load one verified ETA native artifact/calibration pair at composition time."""

    def load(
        self,
        *,
        artifact_path: Path,
        artifact_format: str,
        calibration_path: Path,
        calibration_method: str,
        feature_schema_path: Path,
        feature_schema_version: str,
        feature_names: tuple[str, ...],
    ) -> EtaNativeSession: ...


class SeatRiskNativeRuntimeLoader(Protocol):
    """Load one verified Seat Risk artifact/calibration pair at composition time."""

    def load(
        self,
        *,
        artifact_path: Path,
        artifact_format: str,
        calibration_path: Path,
        calibration_method: str,
        feature_schema_path: Path,
        feature_schema_version: str,
        feature_names: tuple[str, ...],
    ) -> SeatRiskNativeSession: ...


class _VerifiedRuntimeIdentity:
    def __init__(
        self,
        *,
        family: str,
        model_version: str,
        artifact_sha256: str,
        artifact_format: str,
        calibration_sha256: str,
        feature_schema_version: str,
        feature_names: tuple[str, ...],
    ) -> None:
        self.family = family
        self.model_version = model_version
        self.artifact_sha256 = artifact_sha256
        self.artifact_format = artifact_format
        self.calibration_sha256 = calibration_sha256
        self.feature_schema_version = feature_schema_version
        self.feature_names = feature_names


class VerifiedEtaNativeRuntime(_VerifiedRuntimeIdentity):
    def __init__(self, *, session: EtaNativeSession, **identity: object) -> None:
        if not callable(getattr(session, "predict", None)):
            raise ModelServingConfigurationError("ETA native session is invalid")
        super().__init__(**identity)
        if self.family != "ETA":
            raise ModelServingConfigurationError("ETA runtime family mismatch")
        self._session = session

    def predict(
        self, value: EtaCompleteFeatureVector
    ) -> EtaNativePrediction | None:
        if type(value) is not EtaCompleteFeatureVector:
            return None
        if (
            value.schema_version != self.feature_schema_version
            or value.feature_names != self.feature_names
        ):
            return None
        output = self._session.predict(value.values)
        return output if type(output) is EtaNativePrediction else None


class VerifiedSeatRiskNativeRuntime(_VerifiedRuntimeIdentity):
    def __init__(self, *, session: SeatRiskNativeSession, **identity: object) -> None:
        if not callable(getattr(session, "predict", None)):
            raise ModelServingConfigurationError(
                "Seat Risk native session is invalid"
            )
        super().__init__(**identity)
        if self.family != "SEAT_RISK":
            raise ModelServingConfigurationError("Seat Risk runtime family mismatch")
        self._session = session

    def predict(
        self, value: SeatRiskCompleteFeatureVector
    ) -> SeatRiskNativePrediction | None:
        if type(value) is not SeatRiskCompleteFeatureVector:
            return None
        if (
            value.schema_version != self.feature_schema_version
            or value.feature_names != self.feature_names
        ):
            return None
        output = self._session.predict(value.values)
        return output if type(output) is SeatRiskNativePrediction else None


@dataclass(frozen=True, slots=True)
class _VerifiedBundle:
    root: Path
    artifact_path: Path
    calibration_path: Path
    feature_schema_path: Path
    artifact_sha256: str
    calibration_sha256: str


def _verify_lifecycle_manifest(
    *,
    lifecycle: VerifiedServingLifecycle,
    manifest: ArtifactBundleManifest,
    family: str,
) -> None:
    if type(lifecycle) is not VerifiedServingLifecycle:
        raise ModelServingConfigurationError(
            "verified serving lifecycle object is required"
        )
    entry = lifecycle.registry_entry
    deployment = lifecycle.deployment
    if entry.artifact.model_family != family:
        raise ModelServingConfigurationError("registry model family mismatch")
    if entry.artifact != manifest.artifact:
        raise ModelServingConfigurationError(
            "registry artifact metadata does not match the bundle manifest"
        )
    if entry.model_card_sha256 != manifest.model_card.sha256:
        raise ModelServingConfigurationError(
            "registry model-card digest does not match the bundle"
        )
    if manifest.calibration is None:
        raise ModelServingConfigurationError(
            "verified serving requires a calibration artifact"
        )
    if lifecycle.calibration_sha256 != manifest.calibration.sha256:
        raise ModelServingConfigurationError(
            "lifecycle calibration digest does not match the bundle"
        )
    if lifecycle.feature_schema_sha256 != manifest.feature_schema.sha256:
        raise ModelServingConfigurationError(
            "lifecycle feature-schema digest does not match the bundle"
        )
    if deployment.model_version != manifest.artifact.model_version:
        raise ModelServingConfigurationError(
            "deployment model version does not match the bundle"
        )


def _verify_serving_bundle(
    *,
    directory: Path,
    manifest: ArtifactBundleManifest,
    family: str,
    schema_version: str,
    feature_names: tuple[str, ...],
) -> _VerifiedBundle:
    if manifest.artifact.model_family != family:
        raise ModelServingConfigurationError("artifact family mismatch")
    if manifest.artifact.feature_schema_version != schema_version:
        raise ModelServingConfigurationError("artifact feature schema version mismatch")
    if manifest.artifact.feature_names != feature_names:
        raise ModelServingConfigurationError("artifact feature name/order mismatch")
    if manifest.calibration is None:
        raise ModelServingConfigurationError(
            "verified serving requires a calibration artifact"
        )
    try:
        verification = verify_bundle(
            directory,
            manifest,
            runtime_feature_schema_version=schema_version,
            runtime_feature_names=feature_names,
        )
        root = directory.resolve(strict=True)
        artifact_path = (root / manifest.artifact.artifact_filename).resolve(strict=True)
        calibration_path = (root / manifest.calibration.filename).resolve(strict=True)
        feature_schema_path = (root / manifest.feature_schema.filename).resolve(strict=True)
    except (ArtifactIntegrityError, OSError) as exc:
        raise ModelServingConfigurationError("serving artifact bundle verification failed") from exc
    if verification.artifact_sha256 != manifest.artifact.artifact_sha256:
        raise ModelServingConfigurationError("verified artifact digest mismatch")
    if (
        artifact_path.parent != root
        or calibration_path.parent != root
        or feature_schema_path.parent != root
    ):
        raise ModelServingConfigurationError("serving artifact path escaped its bundle")
    return _VerifiedBundle(
        root,
        artifact_path,
        calibration_path,
        feature_schema_path,
        verification.artifact_sha256,
        manifest.calibration.sha256,
    )


def build_verified_eta_predictor(
    *,
    bundle_directory: Path,
    manifest: ArtifactBundleManifest,
    lifecycle: VerifiedServingLifecycle,
    feature_source: EtaServingFeatureSource,
    runtime_loader: EtaNativeRuntimeLoader,
    feature_policy: ServingFeaturePolicy = ServingFeaturePolicy(),
    source: str = "POSITION_MODEL",
) -> VerifiedEtaPredictor:
    builder = DurableEtaCompleteVectorBuilder(feature_source, policy=feature_policy)
    if not callable(getattr(runtime_loader, "load", None)):
        raise ModelServingConfigurationError("ETA native runtime loader is invalid")
    _verify_lifecycle_manifest(
        lifecycle=lifecycle,
        manifest=manifest,
        family="ETA",
    )
    verified = _verify_serving_bundle(
        directory=bundle_directory,
        manifest=manifest,
        family="ETA",
        schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    session = runtime_loader.load(
        artifact_path=verified.artifact_path,
        artifact_format=manifest.artifact.artifact_format,
        calibration_path=verified.calibration_path,
        calibration_method=lifecycle.calibration_method,
        feature_schema_path=verified.feature_schema_path,
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    runtime = VerifiedEtaNativeRuntime(
        session=session,
        family="ETA",
        model_version=manifest.artifact.model_version,
        artifact_sha256=verified.artifact_sha256,
        artifact_format=manifest.artifact.artifact_format,
        calibration_sha256=verified.calibration_sha256,
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    attestation = VerifiedEtaPredictorAttestation(
        family="ETA",
        model_version=manifest.artifact.model_version,
        full_feature_schema_version=ETA_SCHEMA_VERSION,
        ordered_feature_names=ETA_FEATURE_NAMES,
        artifact_sha256=manifest.artifact.artifact_sha256,
        verified_artifact_sha256=verified.artifact_sha256,
        artifact_format=manifest.artifact.artifact_format,
        deployment_id=lifecycle.deployment_id,
        deployment_environment=lifecycle.deployment.environment,
        deployment_state=lifecycle.deployment.state.value,
        readiness=lifecycle.registry_entry.state.value,
        calibrated=True,
        calibration_method=lifecycle.calibration_method,
        calibration_sha256=manifest.calibration.sha256,
        verified_calibration_sha256=verified.calibration_sha256,
        source=source,
    )
    return VerifiedEtaPredictor(
        builder,
        runtime,
        attestation,
        expected_feature_schema_version=ETA_SCHEMA_VERSION,
        expected_feature_names=ETA_FEATURE_NAMES,
        required_environment=lifecycle.deployment.environment,
    )


def build_verified_seat_risk_predictor(
    *,
    bundle_directory: Path,
    manifest: ArtifactBundleManifest,
    lifecycle: VerifiedServingLifecycle,
    feature_source: SeatRiskServingFeatureSource,
    runtime_loader: SeatRiskNativeRuntimeLoader,
    feature_policy: ServingFeaturePolicy = ServingFeaturePolicy(),
    origin: str = "MODEL_PREDICTED",
) -> VerifiedSeatRiskPredictor:
    builder = DurableSeatRiskCompleteVectorBuilder(
        feature_source, policy=feature_policy
    )
    if not callable(getattr(runtime_loader, "load", None)):
        raise ModelServingConfigurationError(
            "Seat Risk native runtime loader is invalid"
        )
    _verify_lifecycle_manifest(
        lifecycle=lifecycle,
        manifest=manifest,
        family="SEAT_RISK",
    )
    verified = _verify_serving_bundle(
        directory=bundle_directory,
        manifest=manifest,
        family="SEAT_RISK",
        schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
    )
    session = runtime_loader.load(
        artifact_path=verified.artifact_path,
        artifact_format=manifest.artifact.artifact_format,
        calibration_path=verified.calibration_path,
        calibration_method=lifecycle.calibration_method,
        feature_schema_path=verified.feature_schema_path,
        feature_schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
    )
    runtime = VerifiedSeatRiskNativeRuntime(
        session=session,
        family="SEAT_RISK",
        model_version=manifest.artifact.model_version,
        artifact_sha256=verified.artifact_sha256,
        artifact_format=manifest.artifact.artifact_format,
        calibration_sha256=verified.calibration_sha256,
        feature_schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
    )
    attestation = VerifiedSeatRiskPredictorAttestation(
        family="SEAT_RISK",
        model_version=manifest.artifact.model_version,
        full_feature_schema_version=SEAT_SCHEMA_VERSION,
        ordered_feature_names=SEAT_FEATURE_NAMES,
        artifact_sha256=manifest.artifact.artifact_sha256,
        verified_artifact_sha256=verified.artifact_sha256,
        artifact_format=manifest.artifact.artifact_format,
        deployment_id=lifecycle.deployment_id,
        deployment_environment=lifecycle.deployment.environment,
        deployment_state=lifecycle.deployment.state.value,
        readiness=lifecycle.registry_entry.state.value,
        calibrated=True,
        calibration_method=lifecycle.calibration_method,
        calibration_sha256=manifest.calibration.sha256,
        verified_calibration_sha256=verified.calibration_sha256,
        origin=origin,
    )
    return VerifiedSeatRiskPredictor(
        builder,
        runtime,
        attestation,
        expected_feature_schema_version=SEAT_SCHEMA_VERSION,
        expected_feature_names=SEAT_FEATURE_NAMES,
        required_environment=lifecycle.deployment.environment,
    )


__all__ = [
    "EtaNativeRuntimeLoader",
    "EtaNativeSession",
    "ModelServingConfigurationError",
    "SeatRiskNativeRuntimeLoader",
    "SeatRiskNativeSession",
    "VerifiedEtaNativeRuntime",
    "VerifiedServingLifecycle",
    "VerifiedSeatRiskNativeRuntime",
    "build_verified_eta_predictor",
    "build_verified_seat_risk_predictor",
]
