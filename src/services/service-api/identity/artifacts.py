from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


_ARTIFACT_REF = re.compile(
    r"^fernet-file:(?P<name>[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json\.fernet)$"
)


class ArtifactStoreUnavailable(RuntimeError):
    pass


class ArtifactIntegrityError(RuntimeError):
    pass


class DataRightsArtifactStore(Protocol):
    def put(self, *, job_id: UUID, payload: dict[str, Any]) -> str: ...

    def delete(self, *, artifact_ref: str) -> None: ...


class EncryptedFilesystemArtifactStore:
    """Private, encrypted-at-rest export store for a configured mounted volume.

    References never expose a filesystem path. The configured directory and key are
    deployment secrets and are not returned through the Public API.
    """

    def __init__(self, *, directory: str | Path, encryption_key: str) -> None:
        self._directory = Path(directory)
        if self._directory.exists() and self._directory.is_symlink():
            raise ArtifactStoreUnavailable("Artifact directory must not be a symbolic link.")
        try:
            self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self._directory, 0o700)
            self._directory = self._directory.resolve(strict=True)
            self._fernet = Fernet(encryption_key.encode("ascii"))
        except (OSError, UnicodeEncodeError, ValueError) as exc:
            raise ArtifactStoreUnavailable("Encrypted artifact storage is unavailable.") from exc

    def put(self, *, job_id: UUID, payload: dict[str, Any]) -> str:
        name = f"{job_id}.json.fernet"
        target = self._directory / name
        plaintext = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encrypted = self._fernet.encrypt(plaintext)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._directory,
                prefix=f".{job_id}.",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.chmod(temporary.fileno(), 0o600)
                temporary.write(encrypted)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
            os.chmod(target, 0o600)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ArtifactStoreUnavailable("Unable to persist encrypted export artifact.") from exc
        return f"fernet-file:{name}"

    def read(self, *, artifact_ref: str) -> dict[str, Any]:
        path = self._path_for_ref(artifact_ref)
        try:
            plaintext = self._fernet.decrypt(path.read_bytes())
            payload = json.loads(plaintext)
        except (OSError, InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError("Export artifact could not be verified.") from exc
        if not isinstance(payload, dict):
            raise ArtifactIntegrityError("Export artifact payload is not an object.")
        return payload

    def delete(self, *, artifact_ref: str) -> None:
        try:
            self._path_for_ref(artifact_ref).unlink(missing_ok=True)
        except OSError as exc:
            raise ArtifactStoreUnavailable("Unable to delete export artifact.") from exc

    def _path_for_ref(self, artifact_ref: str) -> Path:
        matched = _ARTIFACT_REF.fullmatch(artifact_ref)
        if matched is None:
            raise ArtifactIntegrityError("Artifact reference is invalid.")
        path = self._directory / matched.group("name")
        if path.parent != self._directory:
            raise ArtifactIntegrityError("Artifact reference escaped its storage boundary.")
        return path


def configured_artifact_store() -> DataRightsArtifactStore:
    backend = settings.DATA_RIGHTS_ARTIFACT_BACKEND
    if backend == "encrypted-filesystem":
        return EncryptedFilesystemArtifactStore(
            directory=settings.DATA_RIGHTS_ARTIFACT_DIRECTORY,
            encryption_key=settings.DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY,
        )
    raise ArtifactStoreUnavailable("Data export artifact storage is disabled.")
