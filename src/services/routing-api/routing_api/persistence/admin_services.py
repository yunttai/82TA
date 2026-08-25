from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from urllib.parse import urlparse
from pathlib import PurePosixPath

from .ports import ModelRegistryRepository
from .records import DeploymentRecord, ModelArtifactRecord

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_PURPOSES = frozenset({"BUS_ETA", "SEAT_RISK", "CALIBRATION", "TAXI_DISPATCH_WAIT"})


class AdminAuthorizationError(PermissionError):
    pass


class AdminValidationError(ValueError):
    pass


class AdminConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OperatorClaims:
    subject: str
    roles: frozenset[str]
    environments: frozenset[str]

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise AdminAuthorizationError("operator subject is required")


@dataclass(frozen=True, slots=True)
class AdminAuditEvent:
    event_id: uuid.UUID
    occurred_at: datetime
    action: str
    operator_subject: str
    environment: str
    target: str
    details: tuple[tuple[str, str], ...]


class AuditSink(Protocol):
    def append(self, event: AdminAuditEvent) -> None: ...


class InMemoryImmutableAuditLog:
    """Append-only deterministic adapter; production must bind a durable WORM sink."""

    def __init__(self) -> None:
        self._events: list[AdminAuditEvent] = []

    def append(self, event: AdminAuditEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> tuple[AdminAuditEvent, ...]:
        return tuple(self._events)


class CacheInvalidator(Protocol):
    def invalidate(self, namespace: str, fingerprint: str | None) -> None: ...


class OperatorAuthorizer:
    def __init__(self, *, allowed_environments: frozenset[str]) -> None:
        if not allowed_environments:
            raise ValueError("at least one admin environment must be allowlisted")
        self._allowed_environments = allowed_environments

    def require(self, claims: OperatorClaims, environment: str) -> None:
        if "routing-admin" not in claims.roles:
            raise AdminAuthorizationError("routing-admin operator role is required")
        if environment not in self._allowed_environments or environment not in claims.environments:
            raise AdminAuthorizationError("operator is not authorized for environment")


@dataclass(frozen=True, slots=True)
class CacheInvalidationCommand:
    namespace: str
    environment: str
    fingerprint: str | None = None


class CacheInvalidationService:
    def __init__(
        self,
        *,
        invalidator: CacheInvalidator,
        audit: AuditSink,
        allowed_namespaces: frozenset[str],
        allowed_environments: frozenset[str],
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not allowed_namespaces:
            raise ValueError("at least one cache namespace must be allowlisted")
        self._invalidator = invalidator
        self._audit = audit
        self._allowed_namespaces = allowed_namespaces
        self._authorizer = OperatorAuthorizer(allowed_environments=allowed_environments)
        self._clock = clock

    def invalidate(self, command: CacheInvalidationCommand, claims: OperatorClaims) -> None:
        self._authorizer.require(claims, command.environment)
        if command.namespace not in self._allowed_namespaces:
            raise AdminValidationError("cache namespace is not allowlisted")
        if command.fingerprint is not None and not _SHA256.fullmatch(command.fingerprint):
            raise AdminValidationError("cache fingerprint must be a SHA-256 hex digest")
        self._invalidator.invalidate(command.namespace, command.fingerprint)
        self._audit.append(
            AdminAuditEvent(
                event_id=uuid.uuid4(),
                occurred_at=self._clock(),
                action="CACHE_INVALIDATED",
                operator_subject=claims.subject,
                environment=command.environment,
                target=command.namespace,
                details=(("fingerprint", command.fingerprint or "ALL"),),
            )
        )


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    uri: str
    sha256: str
    feature_schema_version: str


class ArtifactVerifier(Protocol):
    def verify(self, descriptor: ArtifactDescriptor) -> None: ...


class Sha256ArtifactVerifier:
    """Validates immutable GCS artifacts; never accepts a caller-selected local path."""

    def __init__(
        self,
        *,
        loader: Callable[[str], bytes],
        allowed_buckets: frozenset[str],
        allowed_feature_schemas: frozenset[str],
        allowed_extensions: frozenset[str] = frozenset({".onnx", ".txt", ".json"}),
    ) -> None:
        self._loader = loader
        self._allowed_buckets = allowed_buckets
        self._allowed_feature_schemas = allowed_feature_schemas
        normalized_extensions = frozenset(value.lower() for value in allowed_extensions)
        if not normalized_extensions or any(
            not value.startswith(".") or "/" in value or "\\" in value
            for value in normalized_extensions
        ):
            raise ValueError("artifact extension allowlist is invalid")
        self._allowed_extensions = normalized_extensions

    def verify(self, descriptor: ArtifactDescriptor) -> None:
        parsed = urlparse(descriptor.uri)
        try:
            port = parsed.port
        except ValueError as exc:
            raise AdminValidationError("model artifact URI is not canonical") from exc
        path = parsed.path
        segments = path.removeprefix("/").split("/")
        canonical_uri = (
            descriptor.uri == descriptor.uri.strip()
            and parsed.scheme == "gs"
            and parsed.netloc in self._allowed_buckets
            and parsed.username is None
            and parsed.password is None
            and port is None
            and not parsed.query
            and not parsed.fragment
            and path.startswith("/")
            and bool(path.removeprefix("/"))
            and "%" not in path
            and "\\" not in path
            and all(segment not in {"", ".", ".."} for segment in segments)
        )
        if not canonical_uri:
            raise AdminValidationError("model artifact URI is not allowlisted")
        if PurePosixPath(path).suffix.lower() not in self._allowed_extensions:
            raise AdminValidationError("model artifact format is not allowlisted")
        if not _SHA256.fullmatch(descriptor.sha256):
            raise AdminValidationError("model artifact digest is invalid")
        if descriptor.feature_schema_version not in self._allowed_feature_schemas:
            raise AdminValidationError("feature schema is not allowlisted")
        payload = self._loader(descriptor.uri)
        if not isinstance(payload, bytes):
            raise AdminValidationError("model artifact loader must return immutable bytes")
        if hashlib.sha256(payload).hexdigest() != descriptor.sha256.lower():
            raise AdminValidationError("model artifact digest mismatch")


@dataclass(frozen=True, slots=True)
class ModelActivationCommand:
    purpose: str
    version: str
    environment: str
    traffic_fraction: float


@dataclass(frozen=True, slots=True)
class ModelRollbackCommand:
    purpose: str
    target_version: str
    environment: str


class ModelActivationService:
    def __init__(
        self,
        *,
        registry: ModelRegistryRepository,
        verifier: ArtifactVerifier,
        audit: AuditSink,
        allowed_environments: frozenset[str],
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._registry = registry
        self._verifier = verifier
        self._audit = audit
        self._authorizer = OperatorAuthorizer(allowed_environments=allowed_environments)
        self._clock = clock

    @staticmethod
    def _descriptor(artifact: ModelArtifactRecord) -> ArtifactDescriptor:
        return ArtifactDescriptor(
            uri=artifact.artifact_uri,
            sha256=artifact.artifact_sha256,
            feature_schema_version=artifact.feature_schema_version,
        )

    @staticmethod
    def _transition(status: str, traffic_fraction: float) -> tuple[str, str]:
        if status == "VALIDATED" and traffic_fraction == 0:
            return "VALIDATED", "SHADOW"
        if status == "SHADOW" and 0 < traffic_fraction < 1:
            return "SHADOW", "CANARY"
        if status == "CANARY" and traffic_fraction == 1:
            return "CANARY", "ACTIVE"
        raise AdminConflictError("invalid model lifecycle transition")

    def activate(
        self, command: ModelActivationCommand, claims: OperatorClaims
    ) -> DeploymentRecord:
        self._authorizer.require(claims, command.environment)
        if command.purpose not in _PURPOSES or not 0 <= command.traffic_fraction <= 1:
            raise AdminValidationError("invalid model activation command")
        artifact = self._registry.get_artifact(command.purpose, command.version)
        if artifact is None:
            raise AdminConflictError("model version does not exist")
        if artifact.status not in {"VALIDATED", "SHADOW", "CANARY", "ACTIVE"}:
            raise AdminConflictError("model version has not passed validation")
        self._verifier.verify(self._descriptor(artifact))
        deployment = self._registry.get_deployment(
            command.purpose, command.version, command.environment
        )
        current_state = "VALIDATED" if deployment is None else deployment.state
        expected, target = self._transition(current_state, command.traffic_fraction)
        try:
            deployed = self._registry.transition(
                purpose=command.purpose,
                version=command.version,
                environment=command.environment,
                expected_status=expected,
                target_status=target,
                traffic_fraction=command.traffic_fraction,
                occurred_at=self._clock(),
            )
        except ValueError as exc:
            raise AdminConflictError("model lifecycle changed concurrently") from exc
        self._audit.append(
            AdminAuditEvent(
                event_id=uuid.uuid4(),
                occurred_at=self._clock(),
                action="MODEL_TRANSITIONED",
                operator_subject=claims.subject,
                environment=command.environment,
                target=f"{command.purpose}:{command.version}",
                details=(("from", expected), ("to", target), ("traffic", str(command.traffic_fraction))),
            )
        )
        return deployed

    def rollback(
        self, command: ModelRollbackCommand, claims: OperatorClaims
    ) -> DeploymentRecord:
        self._authorizer.require(claims, command.environment)
        if command.purpose not in _PURPOSES:
            raise AdminValidationError("invalid model purpose")
        target = self._registry.get_artifact(command.purpose, command.target_version)
        if target is None:
            raise AdminConflictError("rollback model version does not exist")
        if target.status not in {"ACTIVE", "RETIRED"}:
            raise AdminConflictError("rollback target has not passed activation lifecycle")
        self._verifier.verify(self._descriptor(target))
        try:
            deployed = self._registry.rollback(
                purpose=command.purpose,
                target_version=command.target_version,
                environment=command.environment,
                occurred_at=self._clock(),
            )
        except ValueError as exc:
            raise AdminConflictError("rollback target is not eligible") from exc
        self._audit.append(
            AdminAuditEvent(
                event_id=uuid.uuid4(),
                occurred_at=self._clock(),
                action="MODEL_ROLLED_BACK",
                operator_subject=claims.subject,
                environment=command.environment,
                target=f"{command.purpose}:{command.target_version}",
                details=(),
            )
        )
        return deployed
