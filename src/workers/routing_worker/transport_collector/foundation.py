"""Packaged pure collector primitives for deterministic ingestion and replay.

This module deliberately has no database or provider dependency.  Persistence
adapters can translate these values to the canonical Routing DB tables without
making online requests depend on a worker framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from typing import Any, Mapping


class CollectorInvariantError(ValueError):
    """Raised when collector input cannot be represented safely."""


class CheckpointConflictError(CollectorInvariantError):
    """Raised for two different events at the same source watermark."""


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CollectorInvariantError(f"{field_name} must be timezone-aware")


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CollectorInvariantError("cursor must be canonical JSON data") from exc


@dataclass(frozen=True)
class CanonicalTripIdentity:
    """Versioned identity that prevents adjacent snapshots crossing trips."""

    route_id: str
    direction: str
    vehicle_token: str
    service_date: date
    inferred_start_at: datetime
    station_sequence_reset: int
    identity_version: str = "trip-identity-foundation-v1"

    def __post_init__(self) -> None:
        for field_name in ("route_id", "direction", "vehicle_token", "identity_version"):
            if not getattr(self, field_name).strip():
                raise CollectorInvariantError(f"{field_name} must not be blank")
        _require_aware(self.inferred_start_at, "inferred_start_at")
        if self.station_sequence_reset < 0:
            raise CollectorInvariantError("station_sequence_reset must be >= 0")

    @property
    def key(self) -> str:
        """Return a stable, non-plate-revealing trip key."""

        payload = {
            "direction": self.direction,
            "identityVersion": self.identity_version,
            "inferredStartAt": self.inferred_start_at.isoformat(),
            "routeId": self.route_id,
            "serviceDate": self.service_date.isoformat(),
            "stationSequenceReset": self.station_sequence_reset,
            "vehicleToken": self.vehicle_token,
        }
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ObservationMetadata:
    """Keep source observation, validity, and ingestion clocks distinct."""

    observed_at: datetime
    valid_at: datetime
    ingested_at: datetime
    source: str
    schema_version: str
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("observed_at", "valid_at", "ingested_at"):
            _require_aware(getattr(self, name), name)
        if not self.source.strip() or not self.schema_version.strip():
            raise CollectorInvariantError("source and schema_version must not be blank")
        normalized = tuple(sorted(set(self.quality_flags)))
        if any(not flag.strip() for flag in normalized):
            raise CollectorInvariantError("quality flags must not be blank")
        if self.ingested_at < self.observed_at:
            normalized = tuple(sorted((*normalized, "SOURCE_CLOCK_AHEAD")))
        object.__setattr__(self, "quality_flags", normalized)


@dataclass(frozen=True)
class CheckpointState:
    source_id: str
    partition_key: str
    last_observed_at: datetime
    last_success_at: datetime
    cursor_json: str
    last_event_key: str

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.partition_key.strip():
            raise CollectorInvariantError("checkpoint source and partition must not be blank")
        _require_aware(self.last_observed_at, "last_observed_at")
        _require_aware(self.last_success_at, "last_success_at")
        if not self.last_event_key.strip():
            raise CollectorInvariantError("last_event_key must not be blank")


@dataclass(frozen=True)
class CheckpointEvent:
    source_id: str
    partition_key: str
    observed_at: datetime
    completed_at: datetime
    cursor: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.partition_key.strip():
            raise CollectorInvariantError("event source and partition must not be blank")
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.completed_at, "completed_at")
        _canonical_json(self.cursor)

    @property
    def cursor_json(self) -> str:
        return _canonical_json(self.cursor)

    @property
    def idempotency_key(self) -> str:
        payload = {
            "cursor": json.loads(self.cursor_json),
            "observedAt": self.observed_at.isoformat(),
            "partitionKey": self.partition_key,
            "sourceId": self.source_id,
        }
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CheckpointAdvance:
    state: CheckpointState
    disposition: str


def advance_checkpoint(
    current: CheckpointState | None, event: CheckpointEvent
) -> CheckpointAdvance:
    """Advance a source partition exactly once and never move its watermark back."""

    if current is not None:
        if (current.source_id, current.partition_key) != (
            event.source_id,
            event.partition_key,
        ):
            raise CollectorInvariantError("event does not belong to checkpoint partition")
        if event.observed_at < current.last_observed_at:
            return CheckpointAdvance(current, "STALE")
        if event.observed_at == current.last_observed_at:
            if (
                event.idempotency_key == current.last_event_key
                and event.cursor_json == current.cursor_json
            ):
                return CheckpointAdvance(current, "DUPLICATE")
            raise CheckpointConflictError(
                "different event encountered at the current checkpoint watermark"
            )

    state = CheckpointState(
        source_id=event.source_id,
        partition_key=event.partition_key,
        last_observed_at=event.observed_at,
        last_success_at=event.completed_at,
        cursor_json=event.cursor_json,
        last_event_key=event.idempotency_key,
    )
    return CheckpointAdvance(state, "ADVANCED")
