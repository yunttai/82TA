"""Fail-closed verification for immutable model, calibration and card bundles."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from .model_foundation import ArtifactIntegrityError, ArtifactMetadata, verify_artifact


_HASH = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class BundleFile:
    filename: str
    sha256: str
    maximum_bytes: int = 4_194_304

    def __post_init__(self) -> None:
        path = Path(self.filename)
        if path.is_absolute() or path.name != self.filename:
            raise ArtifactIntegrityError("bundle filename must be plain and relative")
        if not _HASH.fullmatch(self.sha256):
            raise ArtifactIntegrityError("bundle file hash must be lowercase SHA-256")
        if self.maximum_bytes <= 0:
            raise ArtifactIntegrityError("bundle file size limit must be positive")


@dataclass(frozen=True, slots=True)
class ArtifactBundleManifest:
    artifact: ArtifactMetadata
    calibration: BundleFile | None
    model_card: BundleFile
    feature_schema: BundleFile
    dataset_sha256: str
    metrics_sha256: str

    def __post_init__(self) -> None:
        for digest in (self.dataset_sha256, self.metrics_sha256):
            if not _HASH.fullmatch(digest):
                raise ArtifactIntegrityError("dataset and metrics hashes must be SHA-256")
        names = [self.artifact.artifact_filename, self.model_card.filename, self.feature_schema.filename]
        if self.calibration is not None:
            names.append(self.calibration.filename)
        if len(names) != len(set(names)):
            raise ArtifactIntegrityError("bundle filenames must be unique")
        if Path(self.model_card.filename).suffix.lower() != ".md":
            raise ArtifactIntegrityError("model card must be Markdown")
        if Path(self.feature_schema.filename).suffix.lower() != ".json":
            raise ArtifactIntegrityError("feature schema must be JSON")
        if self.calibration is not None and Path(self.calibration.filename).suffix.lower() != ".json":
            raise ArtifactIntegrityError("calibration artifact must be inert JSON")


@dataclass(frozen=True, slots=True)
class BundleVerification:
    artifact_sha256: str
    verified_files: tuple[str, ...]


def _verify_file(root: Path, item: BundleFile) -> None:
    candidate = root / item.filename
    if candidate.is_symlink():
        raise ArtifactIntegrityError("symbolic links are forbidden in artifact bundles")
    path = candidate.resolve(strict=True)
    if path.parent != root or not path.is_file() or path.stat().st_size > item.maximum_bytes:
        raise ArtifactIntegrityError("bundle file escapes root, is invalid, or exceeds limit")
    digest = sha256(path.read_bytes()).hexdigest()
    if digest != item.sha256:
        raise ArtifactIntegrityError(f"bundle file SHA-256 mismatch: {item.filename}")


def verify_bundle(
    directory: Path, manifest: ArtifactBundleManifest, *,
    runtime_feature_schema_version: str, runtime_feature_names: tuple[str, ...],
) -> BundleVerification:
    root = directory.resolve(strict=True)
    artifact = verify_artifact(
        root, manifest.artifact,
        runtime_feature_schema_version=runtime_feature_schema_version,
        runtime_feature_names=runtime_feature_names,
    )
    files = [manifest.model_card, manifest.feature_schema]
    if manifest.calibration is not None:
        files.append(manifest.calibration)
    for item in files:
        _verify_file(root, item)
    return BundleVerification(
        artifact.artifact_sha256,
        tuple(sorted((manifest.artifact.artifact_filename, *(item.filename for item in files)))),
    )
