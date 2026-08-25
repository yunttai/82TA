"""PostgreSQL durable adapters constrained to the canonical Routing DBML tables.

All SQL identifiers are closed source constants. Every runtime value uses DB-API
parameters. The adapter receives a connection factory; it never imports Django,
reads Service DB configuration, or creates a network connection by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import PurePosixPath
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from .dbapi import ConnectionFactory, Cursor, read_only, transactional
from .vocabulary import (
    VocabularyError,
    VocabularyMigrationPlan,
    plan_vocabulary_migration,
    persisted_model_purpose,
    require_deployment_environment,
)


class DurableRepositoryError(ValueError):
    pass


CANONICAL_MODEL_STATES = frozenset(
    {"REGISTERED", "VALIDATED", "SHADOW", "CANARY", "ACTIVE", "RETIRED", "REJECTED"}
)
SAFE_FORBIDDEN_FIELDS = frozenset(
    {
        "apiKey", "email", "password", "plate", "plateNumber", "raw",
        "rawPayload", "secret", "socialId", "userId", "user_id", "vehiclePlate",
    }
)
MODEL_TRANSITIONS = {
    "REGISTERED": frozenset({"VALIDATED", "REJECTED"}),
    "VALIDATED": frozenset({"SHADOW", "REJECTED"}),
    "SHADOW": frozenset({"CANARY", "REJECTED"}),
    "CANARY": frozenset({"ACTIVE", "REJECTED"}),
    "ACTIVE": frozenset({"RETIRED"}),
    "RETIRED": frozenset(),
    "REJECTED": frozenset(),
}
OBSERVATION_TYPES = frozenset({"ARRIVAL", "LOCATION"})
QUALITY_STATUSES = frozenset({"PASS", "FAIL", "RUNNING"})
COLLECTION_STATUSES = frozenset({"READY", "QUOTA_LIMITED", "STALE", "IMPORTED"})
_HASH = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# Closed SQL constants. No function concatenates a caller-provided identifier.
SQL = {
    "checkpoint_get": "SELECT last_observed_at, last_success_at, cursor, status FROM ingestion_checkpoint WHERE source_id = %s AND partition_key = %s",
    "checkpoint_dedupe_insert": "INSERT INTO ingestion_checkpoint (id, source_id, partition_key, last_observed_at, last_success_at, status, cursor) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (source_id, partition_key) DO NOTHING",
    "checkpoint_upsert": "INSERT INTO ingestion_checkpoint (id, source_id, partition_key, last_observed_at, last_success_at, status, cursor) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (source_id, partition_key) DO UPDATE SET last_observed_at = EXCLUDED.last_observed_at, last_success_at = EXCLUDED.last_success_at, status = EXCLUDED.status, cursor = EXCLUDED.cursor WHERE ingestion_checkpoint.last_observed_at IS NULL OR EXCLUDED.last_observed_at >= ingestion_checkpoint.last_observed_at",
    "advisory_lock": "SELECT pg_advisory_xact_lock(%s)",
    "arrival_insert": "INSERT INTO bus_arrival_observation (trip_id, stop_id, provider_eta_seconds, remaining_seats, observed_at, predicted_arrival_at, ingested_at, source, quality_flags) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
    "location_insert": "INSERT INTO bus_location_observation (trip_id, stop_id, station_sequence, remaining_seats, crowded_code, coordinate, observed_at, ingested_at, source, quality_flags) VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s)",
    "quality_insert": "INSERT INTO data_quality_run (id, source_id, dataset_version, status, metrics, violations, started_at, finished_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
    "model_family_insert": "INSERT INTO model_family (id, purpose, target_definition, owner) VALUES (%s, %s, %s, %s) ON CONFLICT (purpose) DO UPDATE SET purpose = EXCLUDED.purpose RETURNING id, purpose, target_definition, owner",
    "model_family_vocabulary_inventory": "SELECT purpose, COUNT(*) FROM model_family GROUP BY purpose ORDER BY purpose",
    "model_version_insert": "INSERT INTO model_version (id, family_id, version, status, artifact_uri, artifact_sha256, feature_schema_version, training_scope, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (version) DO NOTHING",
    "model_version_get": "SELECT family_id, status, artifact_uri, artifact_sha256, feature_schema_version, training_scope FROM model_version WHERE version = %s FOR SHARE",
    "model_metric_insert": "INSERT INTO model_metric (id, model_version_id, split_name, slice_key, metrics, evaluated_at) VALUES (%s, %s, %s, %s, %s, %s)",
    "model_state_lock": "SELECT status FROM model_version WHERE version = %s FOR UPDATE",
    "model_state_update": "UPDATE model_version SET status = %s WHERE version = %s AND status = %s",
    "deployment_current_lock": "SELECT id, deployment_state, traffic_fraction FROM model_deployment WHERE model_version_id = %s AND environment = %s AND deactivated_at IS NULL FOR UPDATE",
    "deployment_retired_history_lock": "SELECT id, deployment_state, activated_at, deactivated_at FROM model_deployment WHERE model_version_id = %s AND environment = %s AND deployment_state = %s AND activated_at IS NOT NULL AND deactivated_at IS NOT NULL ORDER BY deactivated_at DESC LIMIT 1 FOR UPDATE",
    "deployment_deactivate": "UPDATE model_deployment SET deactivated_at = %s WHERE id = %s AND deactivated_at IS NULL",
    "deployment_retire": "UPDATE model_deployment SET deactivated_at = %s, deployment_state = %s WHERE id = %s AND deployment_state = %s AND deactivated_at IS NULL",
    "deployment_insert": "INSERT INTO model_deployment (id, model_version_id, environment, deployment_state, traffic_fraction, activated_at, deactivated_at) VALUES (%s, %s, %s, %s, %s, %s, NULL)",
    "deployment_environment_vocabulary_inventory": "SELECT environment, COUNT(*) FROM model_deployment GROUP BY environment ORDER BY environment",
    "prediction_insert": "INSERT INTO prediction_audit (model_version_id, request_id, entity_key, input_summary, prediction, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
}


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DurableRepositoryError(f"{field} must be timezone-aware")


def _uuid(value: object, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise DurableRepositoryError(f"{field} must be UUID") from exc


def _json(value: object, field: str) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DurableRepositoryError(f"{field} must be canonical JSON") from exc


def _expect_rowcount(cursor: Cursor, expected: set[int], operation: str) -> None:
    if cursor.rowcount not in expected:
        raise DurableRepositoryError(
            f"unexpected rowcount for {operation}: {cursor.rowcount}"
        )


def _advisory_key(value: str) -> int:
    raw = int.from_bytes(sha256(value.encode("utf-8")).digest()[:8], "big", signed=False)
    return raw - (1 << 64) if raw >= (1 << 63) else raw


def _safe_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _reject_forbidden(value: object, forbidden: frozenset[str]) -> None:
    if isinstance(value, Mapping):
        canonical_forbidden = {_safe_key(item) for item in forbidden}
        if canonical_forbidden & {_safe_key(item) for item in value}:
            raise DurableRepositoryError("safe metadata contains forbidden fields")
        for nested in value.values():
            _reject_forbidden(nested, forbidden)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_forbidden(nested, forbidden)


@dataclass(frozen=True, slots=True)
class DurableCheckpoint:
    source_id: str
    partition_key: str
    last_observed_at: datetime
    last_success_at: datetime
    cursor: Mapping[str, Any]
    status: str = "READY"

    def __post_init__(self) -> None:
        _uuid(self.source_id, "source_id")
        if not self.partition_key.strip() or self.status not in COLLECTION_STATUSES:
            raise DurableRepositoryError("checkpoint partition/status is invalid")
        _aware(self.last_observed_at, "last_observed_at")
        _aware(self.last_success_at, "last_success_at")
        _json(self.cursor, "checkpoint cursor")


@dataclass(frozen=True, slots=True)
class DurableObservation:
    observation_type: str
    dedupe_key: str
    trip_id: str
    stop_id: str | None
    observed_at: datetime
    ingested_at: datetime
    source: str
    quality_flags: tuple[str, ...] = ()
    provider_eta_seconds: int | None = None
    predicted_arrival_at: datetime | None = None
    remaining_seats: int | None = None
    station_sequence: int | None = None
    crowded_code: int | None = None

    def __post_init__(self) -> None:
        if self.observation_type not in OBSERVATION_TYPES:
            raise DurableRepositoryError("observation type is not allowlisted")
        if not _HASH.fullmatch(self.dedupe_key):
            raise DurableRepositoryError("dedupe key must be SHA-256")
        _uuid(self.trip_id, "trip_id")
        if self.stop_id is not None:
            _uuid(self.stop_id, "stop_id")
        for value, field in ((self.observed_at, "observed_at"), (self.ingested_at, "ingested_at")):
            _aware(value, field)
        if self.predicted_arrival_at is not None:
            _aware(self.predicted_arrival_at, "predicted_arrival_at")
        if not self.source.strip() or any(not flag.strip() for flag in self.quality_flags):
            raise DurableRepositoryError("source/quality flags are invalid")
        if self.remaining_seats is not None and self.remaining_seats < 0:
            raise DurableRepositoryError("remaining seats must be non-negative or NULL")
        if self.provider_eta_seconds is not None and self.provider_eta_seconds < 0:
            raise DurableRepositoryError("provider ETA must be non-negative or NULL")
        if self.station_sequence is not None and self.station_sequence < 0:
            raise DurableRepositoryError("station sequence must be non-negative or NULL")
        if self.observation_type == "ARRIVAL" and self.stop_id is None:
            raise DurableRepositoryError("arrival observation requires stop_id")

    @property
    def content_sha256(self) -> str:
        payload = {
            "crowdedCode": self.crowded_code,
            "ingestedAt": self.ingested_at.isoformat(),
            "observedAt": self.observed_at.isoformat(),
            "observationType": self.observation_type,
            "predictedArrivalAt": None if self.predicted_arrival_at is None else self.predicted_arrival_at.isoformat(),
            "providerEtaSeconds": self.provider_eta_seconds,
            "qualityFlags": tuple(sorted(set(self.quality_flags))),
            "remainingSeats": self.remaining_seats,
            "source": self.source,
            "stationSequence": self.station_sequence,
            "stopId": self.stop_id,
            "tripId": self.trip_id,
        }
        return sha256(_json(payload, "observation content").encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BatchCommitResult:
    inserted: int
    duplicate: int


@dataclass(frozen=True, slots=True)
class QualityRunRecord:
    source_id: str
    dataset_version: str
    status: str
    metrics: Mapping[str, Any]
    violations: tuple[str, ...]
    started_at: datetime
    finished_at: datetime | None

    def __post_init__(self) -> None:
        _uuid(self.source_id, "source_id")
        if not self.dataset_version.strip() or self.status not in QUALITY_STATUSES:
            raise DurableRepositoryError("quality dataset/status is invalid")
        _aware(self.started_at, "started_at")
        if self.finished_at is not None:
            _aware(self.finished_at, "finished_at")
        if (self.status == "RUNNING") != (self.finished_at is None):
            raise DurableRepositoryError("RUNNING quality state must be unfinished and terminal states finished")
        _json(self.metrics, "quality metrics")
        _json(self.violations, "quality violations")
        _reject_forbidden(self.metrics, SAFE_FORBIDDEN_FIELDS)


@dataclass(frozen=True, slots=True)
class ModelRegistration:
    family_id: str
    model_version_id: str
    family: str
    version: str
    target_definition: str
    owner: str
    artifact_uri: str
    artifact_sha256: str
    feature_schema_version: str
    training_scope: Mapping[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        _uuid(self.family_id, "family_id")
        _uuid(self.model_version_id, "model_version_id")
        if not isinstance(self.family, str) or self.family not in {"ETA", "SEAT_RISK"}:
            raise DurableRepositoryError(
                "worker training family must be ETA or SEAT_RISK"
            )
        strings = (
            self.version, self.target_definition, self.owner, self.artifact_uri,
            self.feature_schema_version,
        )
        if not all(value.strip() for value in strings):
            raise DurableRepositoryError("model registration strings must not be blank")
        if not _HASH.fullmatch(self.artifact_sha256):
            raise DurableRepositoryError("artifact hash must be SHA-256")
        artifact = urlsplit(self.artifact_uri)
        if (
            artifact.scheme != "gs" or not artifact.hostname or artifact.username
            or artifact.password or artifact.query or artifact.fragment or ".." in artifact.path.split("/")
        ):
            raise DurableRepositoryError("artifact URI must be a credential-free fixed gs URI")
        if PurePosixPath(artifact.path).suffix.casefold() not in {".json", ".txt"}:
            raise DurableRepositoryError(
                "model artifact must use an allowlisted non-pickle format"
            )
        _aware(self.created_at, "model created_at")
        _json(self.training_scope, "training scope")
        _reject_forbidden(self.training_scope, SAFE_FORBIDDEN_FIELDS)
        required_scope = {
            "calibrationSha256", "datasetSha256", "missingTargetPolicy",
            "modelCardSha256", "splitPolicy",
        }
        if not required_scope <= set(self.training_scope):
            raise DurableRepositoryError("training scope lacks dataset/calibration/card/split evidence")
        for key in ("calibrationSha256", "datasetSha256", "modelCardSha256"):
            if not isinstance(self.training_scope[key], str) or not _HASH.fullmatch(self.training_scope[key]):
                raise DurableRepositoryError(f"{key} must be SHA-256")
        if self.training_scope["missingTargetPolicy"] != "EXCLUDE_UNOBSERVED":
            raise DurableRepositoryError("missing targets must be excluded")
        if self.training_scope["splitPolicy"] != "TEMPORAL_TRIP_GROUP_PURGED":
            raise DurableRepositoryError("model split must be temporal and trip-group purged")
        expected_prefix = "eta-" if self.family == "ETA" else "seat-risk-"
        if not self.feature_schema_version.startswith(expected_prefix):
            raise DurableRepositoryError("feature schema does not match model family")


@dataclass(frozen=True, slots=True)
class DeploymentRecord:
    deployment_id: str
    model_version_id: str
    environment: str
    state: str
    traffic_fraction: float
    activated_at: datetime

    def __post_init__(self) -> None:
        _uuid(self.deployment_id, "deployment_id")
        _uuid(self.model_version_id, "model_version_id")
        try:
            require_deployment_environment(self.environment)
        except VocabularyError as exc:
            raise DurableRepositoryError(str(exc)) from exc
        if self.state not in {"SHADOW", "CANARY", "ACTIVE"}:
            raise DurableRepositoryError("deployment state is invalid")
        if not isfinite(self.traffic_fraction) or not 0 <= self.traffic_fraction <= 1:
            raise DurableRepositoryError("traffic fraction is invalid")
        if self.state == "SHADOW" and self.traffic_fraction != 0:
            raise DurableRepositoryError("SHADOW traffic must be zero")
        if self.state == "CANARY" and not 0 < self.traffic_fraction < 1:
            raise DurableRepositoryError("CANARY traffic must be between zero and one")
        if self.state == "ACTIVE" and self.traffic_fraction != 1:
            raise DurableRepositoryError("ACTIVE traffic must be one")
        _aware(self.activated_at, "activated_at")


@dataclass(frozen=True, slots=True)
class DeploymentDeactivation:
    model_version_id: str
    environment: str
    deactivated_at: datetime

    def __post_init__(self) -> None:
        _uuid(self.model_version_id, "model_version_id")
        try:
            require_deployment_environment(self.environment)
        except VocabularyError as exc:
            raise DurableRepositoryError(str(exc)) from exc
        _aware(self.deactivated_at, "deactivated_at")


@dataclass(frozen=True, slots=True)
class ModelMetricRecord:
    model_version_id: str
    split_name: str
    slice_key: str
    metrics: Mapping[str, Any]
    evaluated_at: datetime

    def __post_init__(self) -> None:
        _uuid(self.model_version_id, "model_version_id")
        if not self.split_name.strip() or not self.slice_key.strip():
            raise DurableRepositoryError("model metric split/slice must not be blank")
        _json(self.metrics, "model metrics")
        _reject_forbidden(self.metrics, SAFE_FORBIDDEN_FIELDS)
        _aware(self.evaluated_at, "model metric evaluated_at")


class PostgresWorkerRepository:
    """Routing-owned worker persistence using only canonical DBML tables."""

    def __init__(self, connection_factory: ConnectionFactory, *, source_id: str) -> None:
        self._factory = connection_factory
        self.source_id = _uuid(source_id, "source_id")

    def load_checkpoint(self, partition_key: str) -> tuple[Any, ...] | None:
        if not partition_key.strip():
            raise DurableRepositoryError("partition key must not be blank")
        return read_only(
            self._factory,
            lambda cursor: self._checkpoint_row(cursor, partition_key),
        )

    def inventory_vocabulary(self) -> VocabularyMigrationPlan:
        """Inventory legacy aliases without mutating or normalizing persisted rows."""

        def operation(cursor: Cursor) -> VocabularyMigrationPlan:
            cursor.execute(SQL["model_family_vocabulary_inventory"])
            purpose_counts = self._inventory_counts(cursor.fetchall(), "purpose")
            cursor.execute(SQL["deployment_environment_vocabulary_inventory"])
            environment_counts = self._inventory_counts(
                cursor.fetchall(), "environment"
            )
            try:
                return plan_vocabulary_migration(
                    purpose_counts=purpose_counts,
                    environment_counts=environment_counts,
                )
            except VocabularyError as exc:
                raise DurableRepositoryError(str(exc)) from exc

        return read_only(self._factory, operation)

    @staticmethod
    def _inventory_counts(
        rows: Iterable[tuple[Any, ...]], label: str
    ) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in rows:
            if (
                len(row) != 2
                or not isinstance(row[0], str)
                or isinstance(row[1], bool)
                or not isinstance(row[1], int)
                or row[1] < 0
                or row[0] in result
            ):
                raise DurableRepositoryError(f"{label} vocabulary inventory is invalid")
            result[row[0]] = row[1]
        return result

    def has_dedupe(self, dedupe_key: str) -> bool:
        if not _HASH.fullmatch(dedupe_key):
            raise DurableRepositoryError("dedupe key must be SHA-256")
        return self.load_checkpoint(f"dedupe:{dedupe_key}") is not None

    def _checkpoint_row(self, cursor: Cursor, partition_key: str) -> tuple[Any, ...] | None:
        cursor.execute(SQL["checkpoint_get"], (self.source_id, partition_key))
        return cursor.fetchone()

    def commit_observations(
        self, observations: Iterable[DurableObservation], checkpoint: DurableCheckpoint
    ) -> BatchCommitResult:
        rows = tuple(observations)
        if checkpoint.source_id != self.source_id:
            raise DurableRepositoryError("checkpoint source does not match repository")
        if len({row.dedupe_key for row in rows}) != len(rows):
            raise DurableRepositoryError("batch contains duplicate natural keys")

        def operation(cursor: Cursor) -> BatchCommitResult:
            inserted = duplicate = 0
            for row in rows:
                cursor.execute(SQL["advisory_lock"], (_advisory_key(row.dedupe_key),))
                dedupe_partition = f"dedupe:{row.dedupe_key}"
                cursor.execute(
                    SQL["checkpoint_dedupe_insert"],
                    (
                        str(uuid4()), self.source_id, dedupe_partition, row.observed_at,
                        checkpoint.last_success_at, "READY",
                        _json(
                            {
                                "observationSha256": row.content_sha256,
                                "schema": "observation-dedupe-v1",
                            },
                            "dedupe cursor",
                        ),
                    ),
                )
                _expect_rowcount(cursor, {0, 1}, "observation dedupe")
                if cursor.rowcount == 0:
                    cursor.execute(SQL["checkpoint_get"], (self.source_id, dedupe_partition))
                    existing = cursor.fetchone()
                    if existing is None:
                        raise DurableRepositoryError("dedupe conflict row disappeared")
                    cursor_value = json.loads(existing[2]) if isinstance(existing[2], str) else existing[2]
                    if not isinstance(cursor_value, Mapping) or cursor_value.get("observationSha256") != row.content_sha256:
                        raise DurableRepositoryError("natural-key conflict has different normalized content")
                    duplicate += 1
                    continue
                self._insert_observation(cursor, row)
                inserted += 1
            cursor.execute(
                SQL["checkpoint_upsert"],
                (
                    str(uuid4()), self.source_id, checkpoint.partition_key,
                    checkpoint.last_observed_at, checkpoint.last_success_at,
                    checkpoint.status, _json(checkpoint.cursor, "checkpoint cursor"),
                ),
            )
            _expect_rowcount(cursor, {1}, "checkpoint upsert")
            return BatchCommitResult(inserted, duplicate)

        return transactional(self._factory, operation)

    def _insert_observation(self, cursor: Cursor, row: DurableObservation) -> None:
        flags = _json(tuple(sorted(set(row.quality_flags))), "quality flags")
        if row.observation_type == "ARRIVAL":
            cursor.execute(
                SQL["arrival_insert"],
                (
                    row.trip_id, row.stop_id, row.provider_eta_seconds,
                    row.remaining_seats, row.observed_at, row.predicted_arrival_at,
                    row.ingested_at, row.source, flags,
                ),
            )
        else:
            cursor.execute(
                SQL["location_insert"],
                (
                    row.trip_id, row.stop_id, row.station_sequence, row.remaining_seats,
                    row.crowded_code, row.observed_at, row.ingested_at, row.source, flags,
                ),
            )
        _expect_rowcount(cursor, {1}, "observation insert")

    def write_dead_letter(
        self, *, dedupe_key: str, reason: str, occurred_at: datetime,
        safe_summary: Mapping[str, Any],
    ) -> str:
        if not _HASH.fullmatch(dedupe_key) or not reason.strip():
            raise DurableRepositoryError("DLQ key/reason is invalid")
        forbidden = {"raw", "rawPayload", "plate", "email", "userId", "secret"}
        _reject_forbidden(safe_summary, frozenset(forbidden))
        record = QualityRunRecord(
            self.source_id, f"dlq:{dedupe_key}", "FAIL",
            {"deadLetterCount": 1, "summary": dict(safe_summary)}, (reason,),
            occurred_at, occurred_at,
        )
        return self.write_quality_run(record)

    def write_quality_run(self, record: QualityRunRecord) -> str:
        run_id = str(uuid4())

        def operation(cursor: Cursor) -> str:
            cursor.execute(
                SQL["quality_insert"],
                (
                    run_id, record.source_id, record.dataset_version, record.status,
                    _json(record.metrics, "quality metrics"),
                    _json(record.violations, "quality violations"),
                    record.started_at, record.finished_at,
                ),
            )
            _expect_rowcount(cursor, {1}, "quality run insert")
            return run_id

        return transactional(self._factory, operation)

    def update_collection_state(
        self, *, partition_key: str, observed_at: datetime, updated_at: datetime,
        status: str, quota_remaining: int, freshness_seconds: int | None,
    ) -> None:
        if status not in COLLECTION_STATUSES or quota_remaining < 0:
            raise DurableRepositoryError("collection state is invalid")
        if freshness_seconds is not None and freshness_seconds < 0:
            raise DurableRepositoryError("freshness must be non-negative or NULL")
        checkpoint = DurableCheckpoint(
            self.source_id, partition_key, observed_at, updated_at,
            {
                "freshnessSeconds": freshness_seconds,
                "quotaRemaining": quota_remaining,
                "schema": "collection-state-v1",
            }, status,
        )
        self.commit_observations((), checkpoint)

    def insert_legacy_lineage(self, record: Any, *, imported_at: datetime) -> bool:
        """Persist RI-240 LegacyImportRecord lineage using checkpoint uniqueness."""

        _aware(imported_at, "legacy imported_at")
        lineage = getattr(record, "lineage_key", "")
        source_hash = getattr(record, "source_sha256", "")
        source_table = getattr(record, "source_table", "")
        source_primary_key = getattr(record, "source_primary_key", "")
        normalized_json = getattr(record, "normalized_json", "")
        if not _HASH.fullmatch(lineage) or not _HASH.fullmatch(source_hash):
            raise DurableRepositoryError("legacy lineage hashes are invalid")
        if not _IDENTIFIER.fullmatch(str(source_table)):
            raise DurableRepositoryError("legacy source table is invalid")
        try:
            normalized = json.loads(normalized_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise DurableRepositoryError("legacy normalized JSON is invalid") from exc
        _reject_forbidden(normalized, SAFE_FORBIDDEN_FIELDS)
        partition = f"legacy:{lineage}"

        def operation(cursor: Cursor) -> bool:
            cursor.execute(SQL["advisory_lock"], (_advisory_key(partition),))
            cursor.execute(
                SQL["checkpoint_dedupe_insert"],
                (
                    str(uuid4()), self.source_id, partition, imported_at, imported_at,
                    "IMPORTED",
                    _json(
                        {
                            "normalized": normalized,
                            "sourcePrimaryKeySha256": sha256(str(source_primary_key).encode("utf-8")).hexdigest(),
                            "sourceSha256": source_hash,
                            "sourceTable": str(source_table),
                        },
                        "legacy lineage cursor",
                    ),
                ),
            )
            _expect_rowcount(cursor, {0, 1}, "legacy lineage insert")
            inserted = cursor.rowcount == 1
            if not inserted:
                cursor.execute(SQL["checkpoint_get"], (self.source_id, partition))
                existing = cursor.fetchone()
                if existing is None:
                    raise DurableRepositoryError("legacy lineage conflict row disappeared")
                stored = json.loads(existing[2]) if isinstance(existing[2], str) else existing[2]
                expected_primary_hash = sha256(str(source_primary_key).encode("utf-8")).hexdigest()
                if (
                    not isinstance(stored, Mapping)
                    or stored.get("sourceSha256") != source_hash
                    or stored.get("sourceTable") != str(source_table)
                    or stored.get("sourcePrimaryKeySha256") != expected_primary_hash
                    or stored.get("normalized") != normalized
                ):
                    raise DurableRepositoryError("legacy lineage conflict has different content")
            return inserted

        return transactional(self._factory, operation)

    def write_reconciliation(
        self, *, dataset_version: str, expected_rows: int, imported_rows: int,
        duplicate_rows: int, started_at: datetime, finished_at: datetime,
        violations: tuple[str, ...] = (),
    ) -> str:
        if min(expected_rows, imported_rows, duplicate_rows) < 0:
            raise DurableRepositoryError("reconciliation counts must be non-negative")
        status = "PASS" if expected_rows == imported_rows + duplicate_rows and not violations else "FAIL"
        return self.write_quality_run(
            QualityRunRecord(
                self.source_id, dataset_version, status,
                {
                    "duplicateRows": duplicate_rows,
                    "expectedRows": expected_rows,
                    "importedRows": imported_rows,
                },
                violations, started_at, finished_at,
            )
        )

    def register_model(self, record: ModelRegistration) -> bool:
        try:
            purpose = persisted_model_purpose(record.family)
        except VocabularyError as exc:
            raise DurableRepositoryError(str(exc)) from exc

        def operation(cursor: Cursor) -> bool:
            cursor.execute(
                SQL["model_family_insert"],
                (record.family_id, purpose, record.target_definition, record.owner),
            )
            _expect_rowcount(cursor, {1}, "model family insert")
            family_row = cursor.fetchone()
            if family_row is None or len(family_row) != 4:
                raise DurableRepositoryError("model family upsert did not return id")
            family_id = _uuid(family_row[0], "persisted family_id")
            actual_family = (family_row[1], family_row[2], family_row[3])
            expected_family = (purpose, record.target_definition, record.owner)
            if actual_family != expected_family:
                raise DurableRepositoryError(
                    "model family conflict has different immutable metadata"
                )
            cursor.execute(
                SQL["model_version_insert"],
                (
                    record.model_version_id, family_id, record.version, "REGISTERED",
                    record.artifact_uri, record.artifact_sha256,
                    record.feature_schema_version,
                    _json(record.training_scope, "training scope"), record.created_at,
                ),
            )
            _expect_rowcount(cursor, {0, 1}, "model version insert")
            inserted = cursor.rowcount == 1
            if not inserted:
                cursor.execute(SQL["model_version_get"], (record.version,))
                existing = cursor.fetchone()
                expected_scope = _json(record.training_scope, "training scope")
                if existing is None:
                    raise DurableRepositoryError("model version conflict row disappeared")
                stored_scope = _json(existing[5], "stored training scope") if not isinstance(existing[5], str) else _json(json.loads(existing[5]), "stored training scope")
                expected = (
                    family_id, "REGISTERED", record.artifact_uri, record.artifact_sha256,
                    record.feature_schema_version, expected_scope,
                )
                actual = (str(existing[0]), existing[1], existing[2], existing[3], existing[4], stored_scope)
                if actual != expected:
                    raise DurableRepositoryError("model version conflict has different immutable metadata")
            return inserted

        return transactional(self._factory, operation)

    def write_model_metric(self, record: ModelMetricRecord) -> str:
        metric_id = str(uuid4())

        def operation(cursor: Cursor) -> str:
            cursor.execute(
                SQL["model_metric_insert"],
                (
                    metric_id, record.model_version_id, record.split_name,
                    record.slice_key, _json(record.metrics, "model metrics"),
                    record.evaluated_at,
                ),
            )
            _expect_rowcount(cursor, {1}, "model metric insert")
            return metric_id

        return transactional(self._factory, operation)

    def transition_model(
        self, *, version: str, expected_state: str, target_state: str,
        deployment: DeploymentRecord | None = None,
        deactivation: DeploymentDeactivation | None = None,
    ) -> None:
        if not version.strip():
            raise DurableRepositoryError("model version must not be blank")
        if expected_state not in CANONICAL_MODEL_STATES or target_state not in CANONICAL_MODEL_STATES:
            raise DurableRepositoryError("unregistered model state")
        if target_state not in MODEL_TRANSITIONS[expected_state]:
            raise DurableRepositoryError("invalid canonical model transition")
        deployment_states = {"SHADOW", "CANARY", "ACTIVE"}
        if (target_state in deployment_states) != (deployment is not None):
            raise DurableRepositoryError("deployment record must exactly match deployment lifecycle states")
        if deployment is not None and deployment.state != target_state:
            raise DurableRepositoryError("deployment state does not match model target state")
        leaves_deployment = expected_state in deployment_states and target_state not in deployment_states
        if leaves_deployment != (deactivation is not None):
            raise DurableRepositoryError("leaving a deployed state requires exact interval deactivation")
        if deployment is not None and deactivation is not None:
            raise DurableRepositoryError("transition cannot deploy and terminally deactivate together")

        def operation(cursor: Cursor) -> None:
            cursor.execute(SQL["model_state_lock"], (version,))
            row = cursor.fetchone()
            if row is None or row[0] != expected_state:
                raise DurableRepositoryError("model state conflict")
            cursor.execute(SQL["model_state_update"], (target_state, version, expected_state))
            _expect_rowcount(cursor, {1}, "model state update")
            if deployment is not None:
                self._insert_deployment(cursor, deployment, expected_state=expected_state)
            if deactivation is not None:
                self._deactivate_deployment(
                    cursor,
                    deactivation,
                    expected_state=expected_state,
                    target_state=target_state,
                )

        transactional(self._factory, operation)

    def _insert_deployment(
        self, cursor: Cursor, record: DeploymentRecord, *, expected_state: str,
    ) -> None:
        cursor.execute(
            SQL["deployment_current_lock"],
            (record.model_version_id, record.environment),
        )
        current = cursor.fetchone()
        expected_deployment_states = {"SHADOW", "CANARY", "ACTIVE"}
        if expected_state in expected_deployment_states:
            if current is None or current[1] != expected_state:
                raise DurableRepositoryError("current deployment does not match model lifecycle")
            cursor.execute(SQL["deployment_deactivate"], (record.activated_at, current[0]))
            _expect_rowcount(cursor, {1}, "previous deployment deactivation")
        elif current is not None:
            raise DurableRepositoryError("unexpected deployment exists before SHADOW")
        cursor.execute(
            SQL["deployment_insert"],
            (
                record.deployment_id, record.model_version_id, record.environment,
                record.state, record.traffic_fraction, record.activated_at,
            ),
        )
        _expect_rowcount(cursor, {1}, "deployment insert")

    def _deactivate_deployment(
        self, cursor: Cursor, record: DeploymentDeactivation, *,
        expected_state: str, target_state: str,
    ) -> None:
        cursor.execute(
            SQL["deployment_current_lock"],
            (record.model_version_id, record.environment),
        )
        current = cursor.fetchone()
        if current is None or current[1] != expected_state:
            raise DurableRepositoryError("deployment interval does not match model lifecycle")
        if target_state == "RETIRED":
            cursor.execute(
                SQL["deployment_retire"],
                (record.deactivated_at, "RETIRED", current[0], expected_state),
            )
        else:
            cursor.execute(
                SQL["deployment_deactivate"], (record.deactivated_at, current[0])
            )
        _expect_rowcount(cursor, {1}, "terminal deployment deactivation")

    def rollback_model(
        self, *, failed_version: str, failed_model_id: str, restore_version: str,
        restore_model_id: str, environment: str, occurred_at: datetime,
    ) -> None:
        """Retire current ACTIVE and reactivate a previously RETIRED version atomically."""

        try:
            require_deployment_environment(environment)
        except VocabularyError as exc:
            raise DurableRepositoryError(str(exc)) from exc
        if (
            not failed_version.strip() or not restore_version.strip()
            or failed_version == restore_version or failed_model_id == restore_model_id
        ):
            raise DurableRepositoryError("rollback models must be distinct and non-blank")
        _aware(occurred_at, "rollback occurred_at")
        failed_id = _uuid(failed_model_id, "failed_model_id")
        restore_id = _uuid(restore_model_id, "restore_model_id")

        def operation(cursor: Cursor) -> None:
            for version, expected in ((failed_version, "ACTIVE"), (restore_version, "RETIRED")):
                cursor.execute(SQL["model_state_lock"], (version,))
                row = cursor.fetchone()
                if row is None or row[0] != expected:
                    raise DurableRepositoryError("rollback model state conflict")
            cursor.execute(
                SQL["deployment_retired_history_lock"],
                (restore_id, environment, "RETIRED"),
            )
            history = cursor.fetchone()
            if history is None or len(history) != 4 or history[1] != "RETIRED":
                raise DurableRepositoryError(
                    "rollback target has no retired deployment history in environment"
                )
            history_activated_at, history_deactivated_at = history[2], history[3]
            if (
                not isinstance(history_activated_at, datetime)
                or not isinstance(history_deactivated_at, datetime)
            ):
                raise DurableRepositoryError("rollback target deployment history is invalid")
            _aware(history_activated_at, "rollback history activated_at")
            _aware(history_deactivated_at, "rollback history deactivated_at")
            if (
                history_deactivated_at <= history_activated_at
                or history_deactivated_at > occurred_at
            ):
                raise DurableRepositoryError("rollback target deployment history is invalid")
            cursor.execute(SQL["deployment_current_lock"], (failed_id, environment))
            current = cursor.fetchone()
            if current is None or current[1] != "ACTIVE" or float(current[2]) != 1.0:
                raise DurableRepositoryError("active deployment is absent")
            cursor.execute(SQL["model_state_update"], ("RETIRED", failed_version, "ACTIVE"))
            _expect_rowcount(cursor, {1}, "failed model retirement")
            cursor.execute(SQL["model_state_update"], ("ACTIVE", restore_version, "RETIRED"))
            _expect_rowcount(cursor, {1}, "restore model activation")
            cursor.execute(
                SQL["deployment_retire"],
                (occurred_at, "RETIRED", current[0], "ACTIVE"),
            )
            _expect_rowcount(cursor, {1}, "deployment deactivation")
            cursor.execute(
                SQL["deployment_insert"],
                (str(uuid4()), restore_id, environment, "ACTIVE", 1.0, occurred_at),
            )
            _expect_rowcount(cursor, {1}, "rollback deployment insert")

        transactional(self._factory, operation)

    def write_prediction_audit(
        self, *, model_version_id: str, model_version: str, request_id: str,
        entity_key: str, feature_schema_version: str,
        input_summary: Mapping[str, Any], prediction: Mapping[str, float],
        created_at: datetime,
    ) -> None:
        model_id = _uuid(model_version_id, "model_version_id")
        _aware(created_at, "prediction created_at")
        if not all(value.strip() for value in (model_version, request_id, entity_key, feature_schema_version)):
            raise DurableRepositoryError("prediction audit identity is invalid")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            for value in prediction.values()
        ):
            raise DurableRepositoryError("prediction values must be finite numbers")
        entity_hash = sha256(entity_key.encode("utf-8")).hexdigest()
        safe_input = {
            "featureSchemaVersion": feature_schema_version,
            "inputSha256": sha256(_json(input_summary, "input summary").encode("utf-8")).hexdigest(),
            "modelVersion": model_version,
        }
        _reject_forbidden(input_summary, SAFE_FORBIDDEN_FIELDS)

        def operation(cursor: Cursor) -> None:
            cursor.execute(
                SQL["prediction_insert"],
                (
                    model_id, request_id, entity_hash, _json(safe_input, "safe input"),
                    _json(prediction, "prediction"), created_at,
                ),
            )
            _expect_rowcount(cursor, {1}, "prediction audit insert")

        transactional(self._factory, operation)
