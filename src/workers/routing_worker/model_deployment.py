"""Fail-closed startup assembly for one verified ETA/Seat production pair.

The Routing DB is lifecycle authority, while an explicitly configured immutable
materialization map is the only bridge from an approved S3 artifact identity to a
local bundle directory.  Neither request values nor environment-only flags can
select or promote a model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from math import isfinite
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from bus_intelligence_core import VerifiedEtaPredictor, VerifiedSeatRiskPredictor

from .dbapi import Connection, ConnectionFactory, Cursor
from .feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)
from .model_jobs.artifact_bundle import ArtifactBundleManifest, BundleFile
from .model_jobs.model_foundation import ArtifactMetadata
from .model_jobs.registry import Deployment, ModelState, RegistryEntry
from .model_serving import (
    VerifiedServingLifecycle,
    build_verified_eta_predictor,
    build_verified_seat_risk_predictor,
)
from .native_lightgbm import (
    LightGbmEtaRuntimeLoader,
    LightGbmSeatRiskRuntimeLoader,
)
from .postgres_serving import (
    PostgresEtaServingFeatureSource,
    PostgresSeatRiskServingFeatureSource,
    ServingSnapshotTimeouts,
)


class ModelDeploymentAssemblyError(ValueError):
    """Raised before a predictor pair can be exposed to a composition root."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SERVING_EVIDENCE_SCHEMA = "worker-serving-evidence-v1"
_SERVING_EVIDENCE_KEYS = frozenset(
    {
        "schemaVersion",
        "artifactFormat",
        "artifactFilename",
        "featureNames",
        "modelCardFilename",
        "modelCardSha256",
        "calibrationFilename",
        "calibrationMethod",
        "calibrationSha256",
        "featureSchemaFilename",
        "featureSchemaSha256",
        "datasetSha256",
        "metricsSha256",
        "validationEvidenceSha256",
        "registryStateVersion",
        "registryUpdatedAt",
    }
)
_REGISTRATION_EVIDENCE_KEYS = frozenset(
    {
        "calibrationSha256",
        "datasetSha256",
        "missingTargetPolicy",
        "modelCardSha256",
        "splitPolicy",
    }
)

_MODEL_PAIR_SNAPSHOT_SQL = """
WITH requested AS (
    SELECT
        %s::varchar AS environment,
        %s::timestamptz AS as_of
)
SELECT
    family.purpose,
    version.id,
    version.version,
    version.status,
    version.artifact_uri,
    version.artifact_sha256,
    version.feature_schema_version,
    version.training_scope,
    version.created_at,
    deployment.id,
    deployment.environment,
    deployment.deployment_state,
    deployment.traffic_fraction,
    deployment.activated_at,
    deployment.deactivated_at
FROM model_family AS family
CROSS JOIN requested AS request
JOIN model_version AS version
  ON version.family_id = family.id
JOIN model_deployment AS deployment
  ON deployment.model_version_id = version.id
WHERE family.purpose IN ('BUS_ETA', 'SEAT_RISK')
  AND version.status = 'ACTIVE'
  AND deployment.environment = request.environment
  AND deployment.deployment_state = 'ACTIVE'
  AND deployment.traffic_fraction = 1
  AND deployment.activated_at IS NOT NULL
  AND deployment.deactivated_at IS NULL
  AND version.created_at <= request.as_of
  AND deployment.activated_at <= request.as_of
ORDER BY family.purpose, version.version, deployment.id
LIMIT 3
""".strip()

_BEGIN_READ_SNAPSHOT_SQL = (
    "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
)
_SET_STATEMENT_TIMEOUT_SQL = (
    "SELECT set_config('statement_timeout', %s, true)"
)
_SET_LOCK_TIMEOUT_SQL = "SELECT set_config('lock_timeout', %s, true)"
_SET_IDLE_TIMEOUT_SQL = (
    "SELECT set_config('idle_in_transaction_session_timeout', %s, true)"
)


def _aware(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ModelDeploymentAssemblyError(f"{field} must be timezone-aware")
    return value


def _text(value: object, field: str, *, maximum_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum_bytes
        or any(ord(character) < 32 for character in value)
    ):
        raise ModelDeploymentAssemblyError(f"{field} is invalid")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ModelDeploymentAssemblyError(f"{field} must be lowercase SHA-256")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not UUID:
        raise ModelDeploymentAssemblyError(f"{field} must be UUID")
    return str(value)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ModelDeploymentAssemblyError(f"{field} must be an integer >= {minimum}")
    return value


def _fraction(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ModelDeploymentAssemblyError(f"{field} must be numeric")
    result = float(value)
    if not isfinite(result) or not 0 <= result <= 1:
        raise ModelDeploymentAssemblyError(f"{field} must be in [0, 1]")
    return result


def _json_mapping(value: object, field: str) -> Mapping[str, object]:
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 65_536:
            raise ModelDeploymentAssemblyError(f"{field} exceeds the size limit")
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ModelDeploymentAssemblyError(f"{field} is invalid JSON") from exc
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ModelDeploymentAssemblyError(f"{field} must be a JSON object")
    return value


def _canonical_s3_uri(value: object) -> str:
    uri = _text(value, "artifact_uri")
    parsed = urlparse(uri)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ModelDeploymentAssemblyError("artifact_uri is not canonical") from exc
    segments = parsed.path.removeprefix("/").split("/")
    if not (
        parsed.scheme == "s3"
        and parsed.netloc
        and parsed.username is None
        and parsed.password is None
        and port is None
        and parsed.path.startswith("/")
        and all(segment not in {"", ".", ".."} for segment in segments)
        and not parsed.query
        and not parsed.fragment
        and "%" not in parsed.path
        and "\\" not in parsed.path
    ):
        raise ModelDeploymentAssemblyError("artifact_uri is not canonical S3 identity")
    return uri


def _evidence(value: object) -> Mapping[str, object]:
    scope = _json_mapping(value, "training_scope")
    if not _REGISTRATION_EVIDENCE_KEYS <= frozenset(scope):
        raise ModelDeploymentAssemblyError(
            "training_scope lacks registration evidence"
        )
    outer_hashes = {
        key: _digest(scope[key], f"training_scope.{key}")
        for key in ("calibrationSha256", "datasetSha256", "modelCardSha256")
    }
    if scope["missingTargetPolicy"] != "EXCLUDE_UNOBSERVED":
        raise ModelDeploymentAssemblyError(
            "training_scope missing-target policy is not serving-safe"
        )
    if scope["splitPolicy"] != "TEMPORAL_TRIP_GROUP_PURGED":
        raise ModelDeploymentAssemblyError(
            "training_scope split policy is not serving-safe"
        )
    if "servingEvidence" not in scope:
        raise ModelDeploymentAssemblyError(
            "training_scope lacks closed servingEvidence"
        )
    evidence = _json_mapping(scope["servingEvidence"], "servingEvidence")
    if frozenset(evidence) != _SERVING_EVIDENCE_KEYS:
        raise ModelDeploymentAssemblyError("servingEvidence schema is not exact")
    if evidence["schemaVersion"] != _SERVING_EVIDENCE_SCHEMA:
        raise ModelDeploymentAssemblyError("servingEvidence schema version mismatch")
    for key, outer_digest in outer_hashes.items():
        if _digest(evidence[key], f"servingEvidence.{key}") != outer_digest:
            raise ModelDeploymentAssemblyError(
                f"training_scope and servingEvidence {key} differ"
            )
    return evidence


@dataclass(frozen=True, slots=True)
class ActiveModelDeployment:
    family: str
    artifact_uri: str
    manifest: ArtifactBundleManifest
    lifecycle: VerifiedServingLifecycle

    def __post_init__(self) -> None:
        if self.family not in {"ETA", "SEAT_RISK"}:
            raise ModelDeploymentAssemblyError("active model family is invalid")
        _canonical_s3_uri(self.artifact_uri)
        if self.manifest.artifact.model_family != self.family:
            raise ModelDeploymentAssemblyError("active model manifest family mismatch")
        if self.lifecycle.registry_entry.artifact != self.manifest.artifact:
            raise ModelDeploymentAssemblyError("active model lifecycle/manifest mismatch")


@dataclass(frozen=True, slots=True)
class ActiveModelPair:
    eta: ActiveModelDeployment
    seat_risk: ActiveModelDeployment
    environment: str

    def __post_init__(self) -> None:
        if type(self.eta) is not ActiveModelDeployment or self.eta.family != "ETA":
            raise ModelDeploymentAssemblyError("active pair ETA family mismatch")
        if (
            type(self.seat_risk) is not ActiveModelDeployment
            or self.seat_risk.family != "SEAT_RISK"
        ):
            raise ModelDeploymentAssemblyError("active pair Seat Risk family mismatch")
        if self.environment not in {"staging", "prod"}:
            raise ModelDeploymentAssemblyError(
                "active pair environment must be staging or prod"
            )
        if any(
            item.lifecycle.deployment.environment != self.environment
            for item in (self.eta, self.seat_risk)
        ):
            raise ModelDeploymentAssemblyError("active pair environment mismatch")


def _decode_active_row(
    row: tuple[Any, ...],
    *,
    as_of: datetime,
) -> ActiveModelDeployment:
    if len(row) != 15:
        raise ModelDeploymentAssemblyError("active lifecycle row schema drift")
    purpose = _text(row[0], "model purpose", maximum_bytes=64)
    expected = {
        "BUS_ETA": ("ETA", ETA_SCHEMA_VERSION, ETA_FEATURE_NAMES),
        "SEAT_RISK": ("SEAT_RISK", SEAT_SCHEMA_VERSION, SEAT_FEATURE_NAMES),
    }
    if purpose not in expected:
        raise ModelDeploymentAssemblyError("active lifecycle purpose is unsupported")
    family, schema_version, feature_names = expected[purpose]
    _uuid(row[1], "model_version.id")
    model_version = _text(row[2], "model version", maximum_bytes=128)
    if row[3] != "ACTIVE":
        raise ModelDeploymentAssemblyError("model_version is not exactly ACTIVE")
    artifact_uri = _canonical_s3_uri(row[4])
    artifact_sha256 = _digest(row[5], "artifact_sha256")
    if row[6] != schema_version:
        raise ModelDeploymentAssemblyError("feature schema version mismatch")
    evidence = _evidence(row[7])
    created_at = _aware(row[8], "model created_at")
    if created_at > as_of:
        raise ModelDeploymentAssemblyError("model created_at is after startup as_of")
    deployment_id = _uuid(row[9], "model_deployment.id")
    environment = _text(row[10], "deployment environment", maximum_bytes=32)
    if environment not in {"staging", "prod"}:
        raise ModelDeploymentAssemblyError(
            "deployment environment must be staging or prod"
        )
    if row[11] != "ACTIVE" or _fraction(row[12], "traffic_fraction") != 1.0:
        raise ModelDeploymentAssemblyError(
            "deployment must be exactly ACTIVE at full traffic"
        )
    activated_at = _aware(row[13], "deployment activated_at")
    if activated_at > as_of:
        raise ModelDeploymentAssemblyError(
            "deployment activated_at is after startup as_of"
        )
    if row[14] is not None:
        raise ModelDeploymentAssemblyError("active deployment is already deactivated")

    raw_feature_names = evidence["featureNames"]
    if (
        not isinstance(raw_feature_names, list)
        or any(not isinstance(item, str) for item in raw_feature_names)
        or tuple(raw_feature_names) != feature_names
    ):
        raise ModelDeploymentAssemblyError("servingEvidence feature order mismatch")
    artifact_format = _text(
        evidence["artifactFormat"], "artifact format", maximum_bytes=64
    )
    artifact_filename = _text(
        evidence["artifactFilename"], "artifact filename", maximum_bytes=255
    )
    metadata = ArtifactMetadata(
        model_family=family,
        model_version=model_version,
        artifact_filename=artifact_filename,
        artifact_format=artifact_format,
        artifact_sha256=artifact_sha256,
        feature_schema_version=schema_version,
        feature_names=feature_names,
    )
    model_card = BundleFile(
        _text(evidence["modelCardFilename"], "model-card filename", maximum_bytes=255),
        _digest(evidence["modelCardSha256"], "model-card digest"),
    )
    calibration = BundleFile(
        _text(
            evidence["calibrationFilename"],
            "calibration filename",
            maximum_bytes=255,
        ),
        _digest(evidence["calibrationSha256"], "calibration digest"),
    )
    feature_schema = BundleFile(
        _text(
            evidence["featureSchemaFilename"],
            "feature-schema filename",
            maximum_bytes=255,
        ),
        _digest(evidence["featureSchemaSha256"], "feature-schema digest"),
    )
    manifest = ArtifactBundleManifest(
        artifact=metadata,
        calibration=calibration,
        model_card=model_card,
        feature_schema=feature_schema,
        dataset_sha256=_digest(evidence["datasetSha256"], "dataset digest"),
        metrics_sha256=_digest(evidence["metricsSha256"], "metrics digest"),
    )
    validation_digest = _digest(
        evidence["validationEvidenceSha256"], "validation evidence digest"
    )
    state_version = _integer(
        evidence["registryStateVersion"], "registry state version", minimum=1
    )
    registry_updated_at_text = _text(
        evidence["registryUpdatedAt"], "registry updated_at", maximum_bytes=64
    )
    try:
        registry_updated_at = datetime.fromisoformat(registry_updated_at_text)
    except ValueError as exc:
        raise ModelDeploymentAssemblyError(
            "registry updated_at is not ISO 8601"
        ) from exc
    _aware(registry_updated_at, "registry updated_at")
    if registry_updated_at < created_at:
        raise ModelDeploymentAssemblyError(
            "registry updated_at precedes model creation"
        )
    if registry_updated_at > as_of:
        raise ModelDeploymentAssemblyError(
            "registry updated_at is after startup as_of"
        )
    if activated_at < registry_updated_at:
        raise ModelDeploymentAssemblyError(
            "deployment activation predates registry readiness"
        )
    entry = RegistryEntry(
        artifact=metadata,
        model_card_sha256=model_card.sha256,
        state=ModelState.ACTIVE,
        state_version=state_version,
        registered_at=created_at,
        updated_at=registry_updated_at,
        validation_evidence_sha256=validation_digest,
    )
    deployment = Deployment(
        model_version=model_version,
        environment=environment,
        state=ModelState.ACTIVE,
        traffic_fraction=1.0,
        activated_at=activated_at,
    )
    lifecycle = VerifiedServingLifecycle(
        registry_entry=entry,
        deployment=deployment,
        deployment_id=deployment_id,
        calibration_method=_text(
            evidence["calibrationMethod"],
            "calibration method",
            maximum_bytes=64,
        ),
        calibration_sha256=calibration.sha256,
        feature_schema_sha256=feature_schema.sha256,
        validation_evidence_sha256=validation_digest,
    )
    return ActiveModelDeployment(family, artifact_uri, manifest, lifecycle)


def _pair_snapshot_rows(
    factory: ConnectionFactory,
    environment: str,
    as_of: datetime,
    timeouts: ServingSnapshotTimeouts,
) -> tuple[tuple[Any, ...], ...]:
    try:
        return _pair_snapshot_rows_unwrapped(factory, environment, as_of, timeouts)
    except ModelDeploymentAssemblyError:
        raise
    except Exception as exc:
        raise ModelDeploymentAssemblyError(
            "Routing-DB active model pair read failed"
        ) from exc


def _pair_snapshot_rows_unwrapped(
    factory: ConnectionFactory,
    environment: str,
    as_of: datetime,
    timeouts: ServingSnapshotTimeouts,
) -> tuple[tuple[Any, ...], ...]:
    connection: Connection | None = None
    cursor: Cursor | None = None
    try:
        connection = factory()
        cursor = connection.cursor()
        cursor.execute(_BEGIN_READ_SNAPSHOT_SQL)
        cursor.execute(
            _SET_STATEMENT_TIMEOUT_SQL,
            (f"{timeouts.statement_ms}ms",),
        )
        cursor.execute(_SET_LOCK_TIMEOUT_SQL, (f"{timeouts.lock_ms}ms",))
        cursor.execute(
            _SET_IDLE_TIMEOUT_SQL,
            (f"{timeouts.idle_in_transaction_ms}ms",),
        )
        cursor.execute(_MODEL_PAIR_SNAPSHOT_SQL, (environment, as_of))
        rows = cursor.fetchall()
        if not isinstance(rows, list) or any(type(row) is not tuple for row in rows):
            raise ModelDeploymentAssemblyError(
                "database driver returned a non-tuple lifecycle row collection"
            )
        return tuple(rows)
    finally:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                try:
                    if cursor is not None:
                        cursor.close()
                finally:
                    connection.close()


class PostgresActiveModelPairSource:
    """Read the exact ETA/Seat ACTIVE pair from one immutable DB snapshot."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        as_of: datetime,
        timeouts: ServingSnapshotTimeouts = ServingSnapshotTimeouts(),
    ) -> None:
        if not callable(connection_factory):
            raise ModelDeploymentAssemblyError(
                "model lifecycle connection factory must be callable"
            )
        if type(timeouts) is not ServingSnapshotTimeouts:
            raise ModelDeploymentAssemblyError(
                "model lifecycle timeouts must be ServingSnapshotTimeouts"
            )
        self._as_of = _aware(as_of, "model lifecycle startup as_of")
        self._connection_factory = connection_factory
        self._timeouts = timeouts

    def load(self, environment: str) -> ActiveModelPair:
        if environment not in {"staging", "prod"}:
            raise ModelDeploymentAssemblyError(
                "model pair environment must be staging or prod"
            )
        rows = _pair_snapshot_rows(
            self._connection_factory,
            environment,
            self._as_of,
            self._timeouts,
        )
        if len(rows) != 2:
            raise ModelDeploymentAssemblyError(
                "exactly one ACTIVE ETA and one ACTIVE Seat Risk row are required"
            )
        try:
            decoded = tuple(
                _decode_active_row(row, as_of=self._as_of) for row in rows
            )
        except ModelDeploymentAssemblyError:
            raise
        except Exception as exc:
            raise ModelDeploymentAssemblyError(
                "ACTIVE model lifecycle evidence is invalid"
            ) from exc
        by_family = {item.family: item for item in decoded}
        if len(by_family) != 2 or set(by_family) != {"ETA", "SEAT_RISK"}:
            raise ModelDeploymentAssemblyError(
                "ACTIVE model pair family rows are missing or ambiguous"
            )
        return ActiveModelPair(by_family["ETA"], by_family["SEAT_RISK"], environment)


@dataclass(frozen=True, slots=True)
class ApprovedBundleMaterialization:
    family: str
    model_version: str
    artifact_uri: str
    artifact_sha256: str
    bundle_directory: Path

    def __post_init__(self) -> None:
        if self.family not in {"ETA", "SEAT_RISK"}:
            raise ModelDeploymentAssemblyError("materialization family is invalid")
        _text(self.model_version, "materialization model version", maximum_bytes=128)
        _canonical_s3_uri(self.artifact_uri)
        _digest(self.artifact_sha256, "materialization artifact digest")
        if not isinstance(self.bundle_directory, Path):
            raise ModelDeploymentAssemblyError(
                "materialization bundle directory must be a Path"
            )

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.family,
            self.model_version,
            self.artifact_uri,
            self.artifact_sha256,
        )


class FixedArtifactBundleResolver:
    """Resolve only pre-approved identities beneath one fixed local bundle root."""

    def __init__(
        self,
        *,
        bundle_root: Path,
        materializations: tuple[ApprovedBundleMaterialization, ...],
    ) -> None:
        if not isinstance(bundle_root, Path) or bundle_root.is_symlink():
            raise ModelDeploymentAssemblyError("bundle root must be a non-symlink Path")
        try:
            root = bundle_root.resolve(strict=True)
        except OSError as exc:
            raise ModelDeploymentAssemblyError("bundle root does not exist") from exc
        if not root.is_dir():
            raise ModelDeploymentAssemblyError("bundle root must be a directory")
        entries: dict[tuple[str, str, str, str], Path] = {}
        for materialization in materializations:
            if type(materialization) is not ApprovedBundleMaterialization:
                raise ModelDeploymentAssemblyError(
                    "bundle materialization type is invalid"
                )
            candidate = materialization.bundle_directory
            if candidate.is_symlink():
                raise ModelDeploymentAssemblyError(
                    "bundle materialization cannot be a symbolic link"
                )
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise ModelDeploymentAssemblyError(
                    "bundle materialization does not exist"
                ) from exc
            if not resolved.is_dir() or not resolved.is_relative_to(root):
                raise ModelDeploymentAssemblyError(
                    "bundle materialization escaped the fixed root"
                )
            if materialization.key in entries:
                raise ModelDeploymentAssemblyError(
                    "duplicate approved bundle materialization"
                )
            entries[materialization.key] = resolved
        object.__setattr__(self, "_root", root)
        object.__setattr__(self, "_entries", MappingProxyType(entries))

    def resolve(self, deployment: ActiveModelDeployment) -> Path:
        if type(deployment) is not ActiveModelDeployment:
            raise ModelDeploymentAssemblyError(
                "bundle resolution requires an active deployment record"
            )
        artifact = deployment.manifest.artifact
        key = (
            deployment.family,
            artifact.model_version,
            deployment.artifact_uri,
            artifact.artifact_sha256,
        )
        try:
            return self._entries[key]
        except KeyError as exc:
            raise ModelDeploymentAssemblyError(
                "ACTIVE artifact has no approved fixed materialization"
            ) from exc


@dataclass(frozen=True, slots=True)
class VerifiedModelPredictorPair:
    eta: VerifiedEtaPredictor
    seat_risk: VerifiedSeatRiskPredictor
    environment: str

    def __post_init__(self) -> None:
        if type(self.eta) is not VerifiedEtaPredictor:
            raise ModelDeploymentAssemblyError("verified pair ETA wrapper is invalid")
        if type(self.seat_risk) is not VerifiedSeatRiskPredictor:
            raise ModelDeploymentAssemblyError(
                "verified pair Seat Risk wrapper is invalid"
            )
        if self.environment not in {"staging", "prod"}:
            raise ModelDeploymentAssemblyError(
                "verified pair environment must be staging or prod"
            )
        if (
            self.eta.attestation.deployment_environment != self.environment
            or self.seat_risk.attestation.deployment_environment != self.environment
        ):
            raise ModelDeploymentAssemblyError(
                "verified pair wrapper environment mismatch"
            )


class VerifiedModelPairAssembler:
    """Startup-only production assembler; construction does not enable any model."""

    def __init__(
        self,
        *,
        lifecycle_source: PostgresActiveModelPairSource,
        bundle_resolver: FixedArtifactBundleResolver,
        eta_feature_source: PostgresEtaServingFeatureSource,
        seat_risk_feature_source: PostgresSeatRiskServingFeatureSource,
        eta_runtime_loader: LightGbmEtaRuntimeLoader,
        seat_risk_runtime_loader: LightGbmSeatRiskRuntimeLoader,
        environment: str,
    ) -> None:
        exact = (
            (lifecycle_source, PostgresActiveModelPairSource, "lifecycle source"),
            (bundle_resolver, FixedArtifactBundleResolver, "bundle resolver"),
            (eta_feature_source, PostgresEtaServingFeatureSource, "ETA feature source"),
            (
                seat_risk_feature_source,
                PostgresSeatRiskServingFeatureSource,
                "Seat Risk feature source",
            ),
            (eta_runtime_loader, LightGbmEtaRuntimeLoader, "ETA runtime loader"),
            (
                seat_risk_runtime_loader,
                LightGbmSeatRiskRuntimeLoader,
                "Seat Risk runtime loader",
            ),
        )
        for value, expected, name in exact:
            if type(value) is not expected:
                raise ModelDeploymentAssemblyError(f"{name} type is not production-exact")
        if environment not in {"staging", "prod"}:
            raise ModelDeploymentAssemblyError(
                "assembler environment must be staging or prod"
            )
        self._lifecycle_source = lifecycle_source
        self._bundle_resolver = bundle_resolver
        self._eta_feature_source = eta_feature_source
        self._seat_risk_feature_source = seat_risk_feature_source
        self._eta_runtime_loader = eta_runtime_loader
        self._seat_risk_runtime_loader = seat_risk_runtime_loader
        self._environment = environment

    def assemble(self) -> VerifiedModelPredictorPair:
        try:
            pair = self._lifecycle_source.load(self._environment)
            eta_directory = self._bundle_resolver.resolve(pair.eta)
            seat_directory = self._bundle_resolver.resolve(pair.seat_risk)
            eta = build_verified_eta_predictor(
                bundle_directory=eta_directory,
                manifest=pair.eta.manifest,
                lifecycle=pair.eta.lifecycle,
                feature_source=self._eta_feature_source,
                runtime_loader=self._eta_runtime_loader,
            )
            seat_risk = build_verified_seat_risk_predictor(
                bundle_directory=seat_directory,
                manifest=pair.seat_risk.manifest,
                lifecycle=pair.seat_risk.lifecycle,
                feature_source=self._seat_risk_feature_source,
                runtime_loader=self._seat_risk_runtime_loader,
            )
            return VerifiedModelPredictorPair(eta, seat_risk, self._environment)
        except ModelDeploymentAssemblyError:
            raise
        except Exception as exc:
            raise ModelDeploymentAssemblyError(
                "verified model pair assembly failed"
            ) from exc


__all__ = [
    "ActiveModelDeployment",
    "ActiveModelPair",
    "ApprovedBundleMaterialization",
    "FixedArtifactBundleResolver",
    "ModelDeploymentAssemblyError",
    "PostgresActiveModelPairSource",
    "VerifiedModelPairAssembler",
    "VerifiedModelPredictorPair",
]
