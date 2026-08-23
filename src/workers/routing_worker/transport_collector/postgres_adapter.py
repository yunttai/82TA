"""Bridge RI-240 collector ports to the durable PostgreSQL repository."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Callable, Mapping

from .foundation import CheckpointState, CollectorInvariantError
from .runtime import BatchCommitResult, CollectedObservation, DeadLetter
from ..repositories import (
    DurableCheckpoint,
    DurableObservation,
    PostgresWorkerRepository,
)


_ARRIVAL_KEYS = frozenset(
    {
        "observationType", "tripId", "stopId", "providerEtaSeconds",
        "remainingSeats", "predictedArrivalAt",
    }
)
_LOCATION_KEYS = frozenset(
    {
        "observationType", "tripId", "stopId", "stationSequence",
        "remainingSeats", "crowdedCode",
    }
)


def _optional_time(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CollectorInvariantError("predictedArrivalAt must be ISO 8601 string or null")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CollectorInvariantError("predictedArrivalAt must be timezone-aware")
    return parsed


class PostgresCollectorAdapter:
    def __init__(
        self, repository: PostgresWorkerRepository, *, source_code: str,
    ) -> None:
        if not source_code.strip():
            raise CollectorInvariantError("source code must not be blank")
        self.repository = repository
        self.source_code = source_code

    def checkpoint(self, source_id: str, partition_key: str) -> CheckpointState | None:
        self._source(source_id)
        row = self.repository.load_checkpoint(partition_key)
        if row is None:
            return None
        last_observed_at, last_success_at, cursor_value, _status = row
        cursor = json.loads(cursor_value) if isinstance(cursor_value, str) else cursor_value
        if not isinstance(cursor, Mapping):
            raise CollectorInvariantError("durable checkpoint cursor is invalid")
        stored_cursor = cursor.get("cursor")
        last_event_key = cursor.get("lastEventKey")
        if not isinstance(stored_cursor, Mapping) or not isinstance(last_event_key, str):
            raise CollectorInvariantError("durable checkpoint schema is invalid")
        return CheckpointState(
            source_id, partition_key, last_observed_at, last_success_at,
            json.dumps(stored_cursor, sort_keys=True, separators=(",", ":")),
            last_event_key,
        )

    def has_observation(self, dedupe_key: str) -> bool:
        return self.repository.has_dedupe(dedupe_key)

    def commit_batch(
        self, observations: tuple[CollectedObservation, ...], checkpoint: CheckpointState,
    ) -> BatchCommitResult:
        self._source(checkpoint.source_id)
        durable_rows = tuple(self._convert(item) for item in observations)
        durable_checkpoint = DurableCheckpoint(
            source_id=self.repository.source_id,
            partition_key=checkpoint.partition_key,
            last_observed_at=checkpoint.last_observed_at,
            last_success_at=checkpoint.last_success_at,
            cursor={
                "cursor": json.loads(checkpoint.cursor_json),
                "lastEventKey": checkpoint.last_event_key,
                "schema": "collector-checkpoint-v1",
            },
            status="READY",
        )
        result = self.repository.commit_observations(durable_rows, durable_checkpoint)
        return BatchCommitResult(result.inserted, result.duplicate)

    def dead_letter(self, item: DeadLetter) -> None:
        self._source(item.source_id)
        self.repository.write_dead_letter(
            dedupe_key=item.dedupe_key,
            reason=item.reason,
            occurred_at=item.occurred_at,
            safe_summary=dict(item.safe_summary),
        )

    def _source(self, source_id: str) -> None:
        if source_id != self.source_code:
            raise CollectorInvariantError("collector source does not match durable adapter")

    def _convert(self, item: CollectedObservation) -> DurableObservation:
        self._source(item.source_id)
        value = dict(item.normalized)
        observation_type = value.get("observationType")
        allowed = _ARRIVAL_KEYS if observation_type == "ARRIVAL" else _LOCATION_KEYS if observation_type == "LOCATION" else None
        if allowed is None or set(value) != allowed:
            raise CollectorInvariantError("normalized observation keys do not match closed schema")
        return DurableObservation(
            observation_type=observation_type,
            dedupe_key=item.dedupe_key,
            trip_id=value["tripId"],
            stop_id=value["stopId"],
            observed_at=item.metadata.observed_at,
            ingested_at=item.metadata.ingested_at,
            source=item.metadata.source,
            quality_flags=item.metadata.quality_flags,
            provider_eta_seconds=value.get("providerEtaSeconds"),
            predicted_arrival_at=_optional_time(value.get("predictedArrivalAt")),
            remaining_seats=value.get("remainingSeats"),
            station_sequence=value.get("stationSequence"),
            crowded_code=value.get("crowdedCode"),
        )
