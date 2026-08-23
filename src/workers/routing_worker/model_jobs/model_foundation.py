"""Dataset metadata and non-executing model artifact integrity checks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

from bus_intelligence_core import (
    ETA_CONTEXT_FEATURE_NAMES,
    ETA_CONTEXT_SERVING_SCHEMA_VERSION,
    SEAT_RISK_CONTEXT_FEATURE_NAMES,
    SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
)
from ..feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)
from ..feature_encoding import FEATURE_ENCODING_VERSION

class ModelFoundationError(ValueError):
    """Base error for invalid model metadata or artifact input."""


class ArtifactIntegrityError(ModelFoundationError):
    """Raised when bytes, path, format, or schema do not match metadata."""


@dataclass(frozen=True)
class FeatureTargetMetadata:
    model_family: str
    feature_schema_version: str
    feature_names: tuple[str, ...]
    target_names: tuple[str, ...]
    training_label_names: tuple[str, ...]
    target_definition: str
    context_schema_version: str
    context_feature_names: tuple[str, ...]
    feature_encoding_version: str
    missing_target_policy: str = "EXCLUDE_UNOBSERVED"
    split_policy: str = "TEMPORAL_TRIP_GROUP_PURGED"

    def __post_init__(self) -> None:
        if self.model_family not in {"ETA", "SEAT_RISK"}:
            raise ModelFoundationError("model_family must be ETA or SEAT_RISK")
        if (
            not self.feature_schema_version.strip()
            or not self.target_definition.strip()
            or not self.context_schema_version.strip()
            or self.feature_encoding_version != FEATURE_ENCODING_VERSION
        ):
            raise ModelFoundationError("schema version and target definition are required")
        if not self.feature_names or not self.target_names or not self.training_label_names:
            raise ModelFoundationError("features and targets must not be empty")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise ModelFoundationError("feature names must be unique")
        if len(set(self.target_names)) != len(self.target_names):
            raise ModelFoundationError("target names must be unique")
        if len(set(self.training_label_names)) != len(self.training_label_names):
            raise ModelFoundationError("training label names must be unique")
        if set(self.feature_names) & (
            set(self.target_names) | set(self.training_label_names)
        ):
            raise ModelFoundationError("target leakage: target appears in feature schema")
        if not self.context_feature_names or len(set(self.context_feature_names)) != len(
            self.context_feature_names
        ):
            raise ModelFoundationError("context feature names must be non-empty and unique")
        expected_context = {
            "ETA": (
                ETA_CONTEXT_SERVING_SCHEMA_VERSION,
                ETA_CONTEXT_FEATURE_NAMES,
            ),
            "SEAT_RISK": (
                SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
                SEAT_RISK_CONTEXT_FEATURE_NAMES,
            ),
        }[self.model_family]
        if (
            self.context_schema_version,
            self.context_feature_names,
        ) != expected_context:
            raise ModelFoundationError(
                "context schema must match the model family serving schema"
            )
        expected_suffix = self.context_feature_names + ("missing_flags",)
        if self.feature_names[-len(expected_suffix):] != expected_suffix:
            raise ModelFoundationError(
                "full feature schema must end with the serving context schema"
            )

def eta_feature_target_metadata() -> FeatureTargetMetadata:
    return FeatureTargetMetadata(
        model_family="ETA",
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
        target_names=("eta_seconds",),
        training_label_names=("eta_seconds",),
        target_definition=(
            "integer seconds from feature observation time to the first later "
            "eligible target-stop observation on the same canonical trip"
        ),
        context_schema_version=ETA_CONTEXT_SERVING_SCHEMA_VERSION,
        context_feature_names=ETA_CONTEXT_FEATURE_NAMES,
        feature_encoding_version=FEATURE_ENCODING_VERSION,
    )


def seat_risk_feature_target_metadata() -> FeatureTargetMetadata:
    return FeatureTargetMetadata(
        model_family="SEAT_RISK",
        feature_schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
        target_names=(
            "no_seat_at_target",
            "low_seat_le_2_at_target",
            "low_seat_le_5_at_target",
        ),
        training_label_names=("seat_ordinal_class",),
        target_definition=(
            "four-class ordinal remaining-seat label (0, 1-2, 3-5, >5) from the "
            "first later eligible target-stop observation on the same trip, projected "
            "to cumulative no-seat/low-seat threshold probabilities"
        ),
        context_schema_version=SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
        context_feature_names=SEAT_RISK_CONTEXT_FEATURE_NAMES,
        feature_encoding_version=FEATURE_ENCODING_VERSION,
    )


_ALLOWED_FORMAT_SUFFIXES = {
    "LIGHTGBM_TEXT": {".txt"},
    "LIGHTGBM_JSON": {".json"},
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ArtifactMetadata:
    model_family: str
    model_version: str
    artifact_filename: str
    artifact_format: str
    artifact_sha256: str
    feature_schema_version: str
    feature_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.model_family not in {"ETA", "SEAT_RISK"}:
            raise ModelFoundationError("artifact model_family must be ETA or SEAT_RISK")
        if not self.model_version.strip() or not self.feature_schema_version.strip():
            raise ModelFoundationError("model and feature schema versions are required")
        filename = Path(self.artifact_filename)
        if filename.is_absolute() or filename.name != self.artifact_filename:
            raise ArtifactIntegrityError("artifact_filename must be a plain relative filename")
        allowed_suffixes = _ALLOWED_FORMAT_SUFFIXES.get(self.artifact_format)
        if allowed_suffixes is None or filename.suffix.lower() not in allowed_suffixes:
            raise ArtifactIntegrityError("artifact format or suffix is not allowlisted")
        if not _SHA256.fullmatch(self.artifact_sha256):
            raise ArtifactIntegrityError("artifact_sha256 must be lowercase SHA-256")
        if not self.feature_names or len(set(self.feature_names)) != len(self.feature_names):
            raise ModelFoundationError("artifact feature_names must be non-empty and unique")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactMetadata":
        expected = {
            "modelFamily",
            "modelVersion",
            "artifactFilename",
            "artifactFormat",
            "artifactSha256",
            "featureSchemaVersion",
            "featureNames",
        }
        if set(value) != expected:
            raise ModelFoundationError("artifact metadata keys do not match schema")
        feature_names = value["featureNames"]
        if not isinstance(feature_names, list) or not all(
            isinstance(item, str) for item in feature_names
        ):
            raise ModelFoundationError("featureNames must be a list of strings")
        scalar_keys = expected - {"featureNames"}
        if not all(isinstance(value[key], str) for key in scalar_keys):
            raise ModelFoundationError("artifact metadata scalar fields must be strings")
        return cls(
            model_family=value["modelFamily"],
            model_version=value["modelVersion"],
            artifact_filename=value["artifactFilename"],
            artifact_format=value["artifactFormat"],
            artifact_sha256=value["artifactSha256"],
            feature_schema_version=value["featureSchemaVersion"],
            feature_names=tuple(feature_names),
        )


@dataclass(frozen=True)
class ArtifactVerification:
    verified: bool
    artifact_sha256: str
    byte_size: int
    feature_schema_version: str


def load_artifact_metadata(path: Path, *, max_bytes: int = 1_048_576) -> ArtifactMetadata:
    if path.stat().st_size > max_bytes:
        raise ArtifactIntegrityError("metadata exceeds size limit")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ArtifactIntegrityError(f"duplicate metadata key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactIntegrityError("metadata is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ArtifactIntegrityError("metadata root must be an object")
    return ArtifactMetadata.from_mapping(value)


def verify_artifact(
    bundle_directory: Path,
    metadata: ArtifactMetadata,
    *,
    runtime_feature_schema_version: str,
    runtime_feature_names: tuple[str, ...],
    max_artifact_bytes: int = 268_435_456,
) -> ArtifactVerification:
    """Verify inert bytes and exact train/serve schema without loading a model."""

    base = bundle_directory.resolve(strict=True)
    candidate = base / metadata.artifact_filename
    if candidate.is_symlink():
        raise ArtifactIntegrityError("symbolic-link artifacts are not accepted")
    artifact = candidate.resolve(strict=True)
    if artifact.parent != base or not artifact.is_file():
        raise ArtifactIntegrityError("artifact escapes bundle directory or is not a file")
    size = artifact.stat().st_size
    if size > max_artifact_bytes:
        raise ArtifactIntegrityError("artifact exceeds size limit")
    if runtime_feature_schema_version != metadata.feature_schema_version:
        raise ArtifactIntegrityError("feature schema version mismatch")
    if runtime_feature_names != metadata.feature_names:
        raise ArtifactIntegrityError("feature schema name/order mismatch")

    digest = sha256()
    with artifact.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != metadata.artifact_sha256:
        raise ArtifactIntegrityError("artifact SHA-256 mismatch")
    return ArtifactVerification(
        verified=True,
        artifact_sha256=actual_sha256,
        byte_size=size,
        feature_schema_version=metadata.feature_schema_version,
    )
