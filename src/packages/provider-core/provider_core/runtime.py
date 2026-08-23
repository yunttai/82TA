"""Immutable, exact-operation evidence gates for live Provider execution.

Capability labels and runtime evidence are deliberately separate.  Source code,
environment booleans, fixture availability, or a credential alone cannot promote an
operation.  A composition root must inject short-lived evidence bound to the exact
provider, operation, evidence kind, version, and artifact hash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping

from .canonical import require_aware
from .capabilities import (
    Capability,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
)


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class RuntimeEvidenceKind(StrEnum):
    KEY_VERIFICATION = "KEY_VERIFICATION"
    PRODUCTION_APPROVAL = "PRODUCTION_APPROVAL"
    RESPONSE_SCHEMA = "RESPONSE_SCHEMA"


class RuntimeGateReason(StrEnum):
    DOCUMENTATION_NOT_CONFIRMED = "DOCUMENTATION_NOT_CONFIRMED"
    KEY_STATE_NOT_VERIFIED = "KEY_STATE_NOT_VERIFIED"
    PRODUCTION_NOT_APPROVED = "PRODUCTION_NOT_APPROVED"
    FIXTURE_ONLY = "FIXTURE_ONLY"
    RESPONSE_SCHEMA_NOT_VERIFIED = "RESPONSE_SCHEMA_NOT_VERIFIED"
    RESPONSE_SCHEMA_VERSION_MISSING = "RESPONSE_SCHEMA_VERSION_MISSING"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_NOT_YET_VALID = "EVIDENCE_NOT_YET_VALID"
    EVIDENCE_EXPIRED = "EVIDENCE_EXPIRED"
    RESPONSE_SCHEMA_VERSION_MISMATCH = "RESPONSE_SCHEMA_VERSION_MISMATCH"


@dataclass(frozen=True, slots=True)
class RuntimeEvidence:
    provider: str
    operation: str
    kind: RuntimeEvidenceKind
    evidence_id: str
    artifact_sha256: str
    version: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.provider, "provider"),
            (self.operation, "operation"),
            (self.evidence_id, "evidence_id"),
            (self.version, "version"),
        ):
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"runtime evidence {name} is invalid")
        if not _SHA256.fullmatch(self.artifact_sha256):
            raise ValueError("runtime evidence artifact_sha256 must be lowercase SHA-256")
        require_aware(self.issued_at, "issued_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("runtime evidence expiry must follow issue time")

    @property
    def key(self) -> tuple[str, str, RuntimeEvidenceKind]:
        return self.provider, self.operation, self.kind


@dataclass(frozen=True, slots=True)
class RuntimeGateDecision:
    executable: bool
    reasons: tuple[RuntimeGateReason, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True, init=False)
class ProviderRuntimeEvidenceConfig:
    """Immutable evidence registry; there is intentionally no environment parser."""

    _entries: Mapping[tuple[str, str, RuntimeEvidenceKind], RuntimeEvidence]

    def __init__(self, evidence: Iterable[RuntimeEvidence] = ()) -> None:
        entries: dict[tuple[str, str, RuntimeEvidenceKind], RuntimeEvidence] = {}
        for item in evidence:
            if item.key in entries:
                raise ValueError(f"duplicate runtime evidence: {item.key!r}")
            entries[item.key] = item
        object.__setattr__(self, "_entries", MappingProxyType(entries))

    def get(
        self,
        provider: str,
        operation: str,
        kind: RuntimeEvidenceKind,
    ) -> RuntimeEvidence | None:
        return self._entries.get((provider, operation, kind))

    def assess(
        self,
        capability: Capability,
        *,
        provider: str,
        operation: str,
        response_schema_verified: bool,
        response_schema_version: str | None,
        now: datetime,
    ) -> RuntimeGateDecision:
        require_aware(now, "runtime evidence evaluation time")
        if capability.provider != provider or capability.operation != operation:
            raise ValueError("capability does not match exact provider operation")

        reasons: list[RuntimeGateReason] = []
        if capability.documentation_state is not DocumentationState.DOCUMENTED:
            reasons.append(RuntimeGateReason.DOCUMENTATION_NOT_CONFIRMED)
        if capability.key_verification_state is not KeyVerificationState.KEY_VERIFIED:
            reasons.append(RuntimeGateReason.KEY_STATE_NOT_VERIFIED)
        if capability.production_state is not ProductionState.PRODUCTION_APPROVED:
            reasons.append(RuntimeGateReason.PRODUCTION_NOT_APPROVED)
        if capability.fixture_only:
            reasons.append(RuntimeGateReason.FIXTURE_ONLY)
        if not response_schema_verified:
            reasons.append(RuntimeGateReason.RESPONSE_SCHEMA_NOT_VERIFIED)
        if response_schema_version is None or not _IDENTIFIER.fullmatch(response_schema_version):
            reasons.append(RuntimeGateReason.RESPONSE_SCHEMA_VERSION_MISSING)

        evidence_ids: list[str] = []
        for kind in RuntimeEvidenceKind:
            item = self.get(provider, operation, kind)
            if item is None:
                reasons.append(RuntimeGateReason.EVIDENCE_MISSING)
                continue
            evidence_ids.append(item.evidence_id)
            if now < item.issued_at:
                reasons.append(RuntimeGateReason.EVIDENCE_NOT_YET_VALID)
            if now >= item.expires_at:
                reasons.append(RuntimeGateReason.EVIDENCE_EXPIRED)
            if (
                kind is RuntimeEvidenceKind.RESPONSE_SCHEMA
                and response_schema_version is not None
                and item.version != response_schema_version
            ):
                reasons.append(RuntimeGateReason.RESPONSE_SCHEMA_VERSION_MISMATCH)

        unique_reasons = tuple(dict.fromkeys(reasons))
        return RuntimeGateDecision(
            executable=not unique_reasons,
            reasons=unique_reasons,
            evidence_ids=tuple(sorted(evidence_ids)),
        )

    def all(self) -> tuple[RuntimeEvidence, ...]:
        return tuple(self._entries.values())
