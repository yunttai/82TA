"""Quota-aware, replayable collector orchestration with DLQ evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Any, Callable, Iterable, Mapping, Protocol

from .foundation import (
    CheckpointEvent,
    CheckpointState,
    CollectorInvariantError,
    ObservationMetadata,
    advance_checkpoint,
)


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CollectorInvariantError("normalized observation must be canonical JSON") from exc


@dataclass(frozen=True, slots=True)
class CollectedObservation:
    source_id: str
    partition_key: str
    natural_key: str
    metadata: ObservationMetadata
    normalized: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.source_id, self.partition_key, self.natural_key)):
            raise CollectorInvariantError("collector observation keys must not be blank")
        _canonical(self.normalized)

    @property
    def dedupe_key(self) -> str:
        payload = {
            "naturalKey": self.natural_key,
            "observedAt": self.metadata.observed_at.isoformat(),
            "partitionKey": self.partition_key,
            "schemaVersion": self.metadata.schema_version,
            "sourceId": self.source_id,
        }
        return sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DeadLetter:
    source_id: str
    partition_key: str
    dedupe_key: str
    reason: str
    occurred_at: datetime
    safe_summary: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise CollectorInvariantError("DLQ reason must not be blank")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise CollectorInvariantError("DLQ occurred_at must be timezone-aware")


class CollectorRepository(Protocol):
    def checkpoint(self, source_id: str, partition_key: str) -> CheckpointState | None: ...

    def has_observation(self, dedupe_key: str) -> bool: ...

    def commit_batch(
        self,
        observations: tuple[CollectedObservation, ...],
        checkpoint: CheckpointState,
    ) -> "BatchCommitResult":
        """Atomically upsert dedupe keys and checkpoint in one transaction."""
        ...

    def dead_letter(self, item: DeadLetter) -> None: ...


@dataclass(frozen=True, slots=True)
class QuotaWindow:
    maximum_calls: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.maximum_calls <= 0 or self.window_seconds <= 0:
            raise CollectorInvariantError("quota limits must be positive")


class InMemoryQuota:
    """Deterministic quota primitive; production adapters can use Redis atomics."""

    def __init__(self, policy: QuotaWindow) -> None:
        self.policy = policy
        self._calls: dict[str, list[datetime]] = {}

    def reserve(self, source_id: str, at: datetime) -> bool:
        if at.tzinfo is None or at.utcoffset() is None:
            raise CollectorInvariantError("quota clock must be timezone-aware")
        lower = at - timedelta(seconds=self.policy.window_seconds)
        retained = [item for item in self._calls.get(source_id, []) if item > lower]
        if len(retained) >= self.policy.maximum_calls:
            self._calls[source_id] = retained
            return False
        retained.append(at)
        self._calls[source_id] = retained
        return True


@dataclass(frozen=True, slots=True)
class CollectorPolicy:
    maximum_freshness_seconds: int
    maximum_future_skew_seconds: int = 30

    def __post_init__(self) -> None:
        if self.maximum_freshness_seconds < 0 or self.maximum_future_skew_seconds < 0:
            raise CollectorInvariantError("collector clock bounds must be non-negative")


@dataclass(frozen=True, slots=True)
class CollectionResult:
    accepted: int
    duplicate: int
    stale: int
    rejected: int
    quota_limited: bool
    checkpoint: CheckpointState | None


@dataclass(frozen=True, slots=True)
class BatchCommitResult:
    inserted: int
    duplicate: int

    def __post_init__(self) -> None:
        if self.inserted < 0 or self.duplicate < 0:
            raise CollectorInvariantError("batch commit counts must be non-negative")


def collect_batch(
    observations: Iterable[CollectedObservation],
    *,
    source_id: str,
    partition_key: str,
    now: datetime,
    cursor: Mapping[str, Any],
    repository: CollectorRepository,
    quota: InMemoryQuota,
    policy: CollectorPolicy,
    validate: Callable[[CollectedObservation], tuple[str, ...]] = lambda _: (),
) -> CollectionResult:
    """Validate, dedupe and atomically commit a collector partition batch.

    Repository ``commit_batch`` must persist observations and checkpoint in one
    transaction.  Invalid records go to a sanitized DLQ and never advance the
    checkpoint.  The final accepted record controls the watermark.
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise CollectorInvariantError("collector now must be timezone-aware")
    if not quota.reserve(source_id, now):
        return CollectionResult(0, 0, 0, 0, True, repository.checkpoint(source_id, partition_key))

    accepted = duplicate = stale = rejected = 0
    current = repository.checkpoint(source_id, partition_key)
    pending: list[CollectedObservation] = []
    pending_keys: set[str] = set()
    for item in sorted(observations, key=lambda value: (value.metadata.observed_at, value.dedupe_key)):
        if (item.source_id, item.partition_key) != (source_id, partition_key):
            raise CollectorInvariantError("observation does not belong to collector partition")
        age = int((now - item.metadata.observed_at).total_seconds())
        reasons = list(validate(item))
        if age > policy.maximum_freshness_seconds:
            reasons.append("STALE_OBSERVATION")
        if age < -policy.maximum_future_skew_seconds:
            reasons.append("OBSERVATION_CLOCK_IN_FUTURE")
        if reasons:
            repository.dead_letter(
                DeadLetter(
                    source_id=source_id,
                    partition_key=partition_key,
                    dedupe_key=item.dedupe_key,
                    reason="|".join(sorted(set(reasons))),
                    occurred_at=now,
                    safe_summary=(("schemaVersion", item.metadata.schema_version),),
                )
            )
            rejected += 1
            continue
        if item.dedupe_key in pending_keys or repository.has_observation(item.dedupe_key):
            duplicate += 1
            continue
        if current is not None and item.metadata.observed_at < current.last_observed_at:
            stale += 1
            continue
        pending.append(item)
        pending_keys.add(item.dedupe_key)
    if pending:
        watermark = max(item.metadata.observed_at for item in pending)
        event = CheckpointEvent(
            source_id=source_id,
            partition_key=partition_key,
            observed_at=watermark,
            completed_at=now,
            cursor=cursor,
        )
        advance = advance_checkpoint(current, event)
        if advance.disposition == "ADVANCED":
            committed = repository.commit_batch(tuple(pending), advance.state)
            if committed.inserted + committed.duplicate != len(pending):
                raise CollectorInvariantError("repository batch outcome does not match input")
            current = advance.state
            accepted = committed.inserted
            duplicate += committed.duplicate
        elif advance.disposition == "DUPLICATE":
            duplicate += len(pending)
        else:
            stale += len(pending)
    return CollectionResult(accepted, duplicate, stale, rejected, False, current)
