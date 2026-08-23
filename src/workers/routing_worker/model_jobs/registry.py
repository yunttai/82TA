"""Immutable model registry lifecycle, deployment and rollback primitives."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from math import isfinite
import re
from typing import Iterable, Mapping

from .model_foundation import ArtifactMetadata, ModelFoundationError


DEPLOYMENT_ENVIRONMENTS = frozenset({"dev", "staging", "prod"})


class RegistryError(ModelFoundationError):
    pass


class ModelState(StrEnum):
    REGISTERED = "REGISTERED"
    VALIDATED = "VALIDATED"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


_TRANSITIONS = {
    ModelState.REGISTERED: {ModelState.VALIDATED, ModelState.REJECTED},
    ModelState.VALIDATED: {ModelState.SHADOW, ModelState.REJECTED},
    ModelState.SHADOW: {ModelState.CANARY, ModelState.REJECTED},
    ModelState.CANARY: {ModelState.ACTIVE, ModelState.REJECTED},
    ModelState.ACTIVE: {ModelState.RETIRED},
    ModelState.RETIRED: set(),
    ModelState.REJECTED: set(),
}


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RegistryError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ModelCard:
    model_family: str
    model_version: str
    intended_use: str
    training_scope: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...]
    dataset_sha256: str
    metrics_sha256: str
    created_at: datetime

    def __post_init__(self) -> None:
        _aware(self.created_at, "model card created_at")
        if not all(value.strip() for value in (self.model_family, self.model_version, self.intended_use)):
            raise RegistryError("model card identity and intended use are required")
        for digest in (self.dataset_sha256, self.metrics_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise RegistryError("model card digests must be lowercase SHA-256")
        if not self.limitations:
            raise RegistryError("model card must disclose at least one limitation")

    def render_markdown(self) -> str:
        scope = "\n".join(f"- {key}: {value}" for key, value in self.training_scope)
        limitations = "\n".join(f"- {item}" for item in self.limitations)
        return (
            f"# {self.model_family} {self.model_version}\n\n"
            f"## Intended use\n\n{self.intended_use}\n\n"
            f"## Training scope\n\n{scope}\n\n"
            f"## Limitations\n\n{limitations}\n\n"
            f"Dataset SHA-256: `{self.dataset_sha256}`  \n"
            f"Metrics SHA-256: `{self.metrics_sha256}`\n"
        )


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    artifact: ArtifactMetadata
    model_card_sha256: str
    state: ModelState
    state_version: int
    registered_at: datetime
    updated_at: datetime
    validation_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        _aware(self.registered_at, "registered_at")
        _aware(self.updated_at, "updated_at")
        if self.updated_at < self.registered_at:
            raise RegistryError("registry update cannot precede registration")
        if self.state_version < 1:
            raise RegistryError("registry state version must be positive")
        if not re.fullmatch(r"[0-9a-f]{64}", self.model_card_sha256):
            raise RegistryError("model card hash must be lowercase SHA-256")
        if self.state is not ModelState.REGISTERED and self.validation_evidence_sha256 is None:
            if self.state is not ModelState.REJECTED:
                raise RegistryError("validated lifecycle states require validation evidence")


@dataclass(frozen=True, slots=True)
class RegistryEvent:
    model_version: str
    from_state: ModelState
    to_state: ModelState
    actor: str
    reason: str
    occurred_at: datetime
    event_sha256: str


def register(
    artifact: ArtifactMetadata, *, model_card: ModelCard, registered_at: datetime
) -> RegistryEntry:
    _aware(registered_at, "registered_at")
    if (model_card.model_family, model_card.model_version) != (
        artifact.model_family, artifact.model_version,
    ):
        raise RegistryError("model card identity does not match artifact")
    model_card_markdown = model_card.render_markdown()
    return RegistryEntry(
        artifact=artifact,
        model_card_sha256=sha256(model_card_markdown.encode("utf-8")).hexdigest(),
        state=ModelState.REGISTERED,
        state_version=1,
        registered_at=registered_at,
        updated_at=registered_at,
    )


def transition(
    entry: RegistryEntry, to_state: ModelState, *, actor: str, reason: str,
    occurred_at: datetime, validation_evidence_sha256: str | None = None,
) -> tuple[RegistryEntry, RegistryEvent]:
    _aware(occurred_at, "transition occurred_at")
    if occurred_at < entry.updated_at:
        raise RegistryError("transition time cannot regress")
    if to_state not in _TRANSITIONS[entry.state]:
        raise RegistryError(f"invalid model transition {entry.state}->{to_state}")
    if not actor.strip() or not reason.strip():
        raise RegistryError("transition actor and reason are required")
    evidence = validation_evidence_sha256 or entry.validation_evidence_sha256
    if to_state is ModelState.VALIDATED:
        if evidence is None or not re.fullmatch(r"[0-9a-f]{64}", evidence):
            raise RegistryError("VALIDATED requires immutable validation evidence hash")
    updated = replace(
        entry, state=to_state, state_version=entry.state_version + 1,
        updated_at=occurred_at, validation_evidence_sha256=evidence,
    )
    payload = json.dumps(
        {
            "actor": actor,
            "at": occurred_at.isoformat(),
            "from": entry.state,
            "modelVersion": entry.artifact.model_version,
            "reason": reason,
            "stateVersion": updated.state_version,
            "to": to_state,
        }, sort_keys=True, separators=(",", ":")
    )
    event = RegistryEvent(
        entry.artifact.model_version, entry.state, to_state, actor, reason,
        occurred_at, sha256(payload.encode("utf-8")).hexdigest(),
    )
    return updated, event


@dataclass(frozen=True, slots=True)
class Deployment:
    model_version: str
    environment: str
    state: ModelState
    traffic_fraction: float
    activated_at: datetime
    previous_model_version: str | None = None

    def __post_init__(self) -> None:
        _aware(self.activated_at, "deployment activated_at")
        if self.environment not in DEPLOYMENT_ENVIRONMENTS:
            raise RegistryError("deployment environment must be dev, staging, or prod")
        if not self.model_version.strip():
            raise RegistryError("deployment model version must not be blank")
        if not 0 <= self.traffic_fraction <= 1:
            raise RegistryError("deployment traffic fraction must be in [0, 1]")
        expected = {
            ModelState.SHADOW: lambda value: value == 0,
            ModelState.CANARY: lambda value: 0 < value < 1,
            ModelState.ACTIVE: lambda value: value == 1,
        }
        if self.state not in expected or not expected[self.state](self.traffic_fraction):
            raise RegistryError("deployment traffic does not match lifecycle state")


@dataclass(frozen=True, slots=True)
class RollbackPlan:
    failed_model_version: str
    restore_model_version: str
    environment: str
    reason: str
    planned_at: datetime

    def __post_init__(self) -> None:
        if self.environment not in DEPLOYMENT_ENVIRONMENTS:
            raise RegistryError("rollback environment must be dev, staging, or prod")
        if not all(
            value.strip()
            for value in (
                self.failed_model_version,
                self.restore_model_version,
                self.reason,
            )
        ):
            raise RegistryError("rollback model versions and reason are required")
        _aware(self.planned_at, "rollback planned_at")


def plan_rollback(
    active: Deployment, candidates: Iterable[RegistryEntry], *, reason: str, planned_at: datetime,
) -> RollbackPlan:
    if active.state is not ModelState.ACTIVE:
        raise RegistryError("rollback source must be ACTIVE")
    entries = tuple(candidates)
    active_entry = next(
        (item for item in entries if item.artifact.model_version == active.model_version), None
    )
    if active_entry is None:
        raise RegistryError("active deployment is absent from registry candidates")
    eligible = [
        item for item in entries
        if item.artifact.model_family == active_entry.artifact.model_family
        and item.artifact.model_version != active.model_version
        and item.state in {ModelState.ACTIVE, ModelState.RETIRED}
    ]
    if not eligible:
        raise RegistryError("no prior integrity-validated model is available for rollback")
    restore = max(eligible, key=lambda item: (item.updated_at, item.artifact.model_version))
    _aware(planned_at, "rollback planned_at")
    if not reason.strip():
        raise RegistryError("rollback reason must not be blank")
    return RollbackPlan(active.model_version, restore.artifact.model_version, active.environment, reason, planned_at)


@dataclass(frozen=True, slots=True)
class PredictionAudit:
    model_version: str
    request_id: str
    entity_key_hash: str
    feature_schema_version: str
    input_summary_sha256: str
    prediction: tuple[tuple[str, float], ...]
    created_at: datetime


def prediction_audit(
    *, model_version: str, request_id: str, entity_key: str,
    feature_schema_version: str, input_summary: Mapping[str, object],
    prediction: Mapping[str, float], created_at: datetime,
) -> PredictionAudit:
    _aware(created_at, "prediction audit created_at")
    if not all(value.strip() for value in (model_version, request_id, entity_key, feature_schema_version)):
        raise RegistryError("prediction audit identity must not be blank")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
        for value in prediction.values()
    ):
        raise RegistryError("prediction audit outputs must be finite numeric values")
    summary = json.dumps(input_summary, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return PredictionAudit(
        model_version=model_version,
        request_id=request_id,
        entity_key_hash=sha256(entity_key.encode("utf-8")).hexdigest(),
        feature_schema_version=feature_schema_version,
        input_summary_sha256=sha256(summary.encode("utf-8")).hexdigest(),
        prediction=tuple(sorted((key, float(value)) for key, value in prediction.items())),
        created_at=created_at,
    )
