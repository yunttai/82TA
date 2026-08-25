from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest
from uuid import UUID

from routing_worker.repositories import (
    BatchCommitResult,
    CANONICAL_MODEL_STATES,
    DeploymentDeactivation,
    DeploymentRecord,
    DurableCheckpoint,
    DurableObservation,
    DurableRepositoryError,
    ModelMetricRecord,
    ModelRegistration,
    PostgresWorkerRepository,
    QualityRunRecord,
    SQL,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
SOURCE_ID = "11111111-1111-1111-1111-111111111111"
TRIP_ID = "22222222-2222-2222-2222-222222222222"
STOP_ID = "33333333-3333-3333-3333-333333333333"
FAMILY_ID = "44444444-4444-4444-4444-444444444444"
MODEL_ID = "55555555-5555-5555-5555-555555555555"
OLD_MODEL_ID = "66666666-6666-6666-6666-666666666666"


@dataclass
class Step:
    contains: str
    rowcount: int = -1
    row: tuple | None = None
    rows: tuple[tuple, ...] = ()
    error: Exception | None = None


class FakeCursor:
    def __init__(self, steps):
        self.steps = list(steps)
        self.statements = []
        self.rowcount = -1
        self.row = None
        self.rows = ()
        self.closed = False

    def execute(self, operation, parameters=()):
        if not self.steps:
            raise AssertionError(f"unexpected SQL: {operation}")
        step = self.steps.pop(0)
        if step.contains not in operation:
            raise AssertionError(f"expected {step.contains!r}, got {operation!r}")
        self.statements.append((operation, parameters))
        self.rowcount = step.rowcount
        self.row = step.row
        self.rows = step.rows
        if step.error is not None:
            raise step.error

    def fetchone(self):
        return self.row

    def fetchall(self):
        return list(self.rows)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, steps):
        self.cursor_value = FakeCursor(steps)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class QueueFactory:
    def __init__(self, *connections):
        self.connections = list(connections)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.connections.pop(0)


def observation():
    return DurableObservation(
        "ARRIVAL", "a" * 64, TRIP_ID, STOP_ID, NOW, NOW + timedelta(seconds=1),
        "GBIS", ("SCHEMA_VALIDATED",), provider_eta_seconds=90,
        predicted_arrival_at=NOW + timedelta(seconds=90), remaining_seats=None,
    )


def checkpoint():
    return DurableCheckpoint(
        SOURCE_ID, "route-1", NOW, NOW + timedelta(seconds=2), {"page": 1}, "READY"
    )


class PostgresRepositoryTest(unittest.TestCase):
    def test_sql_uses_only_closed_canonical_routing_table_identifiers(self):
        allowed = {
            "bus_arrival_observation", "bus_location_observation", "data_quality_run",
            "ingestion_checkpoint", "model_deployment", "model_family", "model_metric",
            "model_version", "prediction_audit",
        }
        referenced = set()
        import re

        for statement in SQL.values():
            referenced.update(
                match.group(1)
                for match in re.finditer(r"(?:FROM|INTO|UPDATE)\s+([a-z_]+)", statement)
            )
            self.assertNotIn("{", statement)
        self.assertEqual(referenced, allowed)

    def test_observation_and_checkpoint_commit_atomically_with_parameterized_sql(self):
        connection = FakeConnection((
            Step("SET TRANSACTION"), Step("pg_advisory_xact_lock"),
            Step("INSERT INTO ingestion_checkpoint", 1),
            Step("INSERT INTO bus_arrival_observation", 1),
            Step("INSERT INTO ingestion_checkpoint", 1),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        result = repository.commit_observations((observation(),), checkpoint())
        self.assertEqual(result, BatchCommitResult(1, 0))
        self.assertEqual((connection.commits, connection.rollbacks), (1, 0))
        self.assertTrue(connection.closed and connection.cursor_value.closed)
        for sql, parameters in connection.cursor_value.statements:
            self.assertNotIn(TRIP_ID, sql)
            self.assertNotIn(STOP_ID, sql)
            self.assertIsInstance(parameters, tuple)
        self.assertFalse(connection.cursor_value.steps)

    def test_checkpoint_read_is_explicitly_read_only_and_closes_snapshot(self):
        row = (NOW, NOW, {"page": 1}, "READY")
        connection = FakeConnection((
            Step("SET TRANSACTION READ ONLY"),
            Step("SELECT last_observed_at", row=row),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)

        self.assertEqual(repository.load_checkpoint("route-1"), row)
        self.assertEqual((connection.commits, connection.rollbacks), (0, 1))
        self.assertTrue(connection.closed and connection.cursor_value.closed)
        self.assertFalse(connection.cursor_value.steps)

    def test_vocabulary_inventory_is_read_only_and_reports_alias_collisions(self):
        connection = FakeConnection((
            Step("SET TRANSACTION READ ONLY"),
            Step(
                "SELECT purpose, COUNT(*)",
                rows=(("BUS_ETA", 1), ("ETA", 2), ("SEAT_RISK", 1)),
            ),
            Step(
                "SELECT environment, COUNT(*)",
                rows=(("STAGING", 2), ("prod", 1), ("staging", 1)),
            ),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)

        plan = repository.inventory_vocabulary()

        self.assertFalse(plan.executable)
        self.assertEqual(
            plan.blockers,
            (
                "purpose collision: ETA->BUS_ETA",
                "environment collision: STAGING->staging",
            ),
        )
        self.assertEqual((connection.commits, connection.rollbacks), (0, 1))
        self.assertTrue(connection.closed and connection.cursor_value.closed)

    def test_dedupe_conflict_skips_observation_but_advances_checkpoint(self):
        existing_cursor = json.dumps(
            {"observationSha256": observation().content_sha256, "schema": "observation-dedupe-v1"}
        )
        connection = FakeConnection((
            Step("SET TRANSACTION"), Step("pg_advisory_xact_lock"),
            Step("INSERT INTO ingestion_checkpoint", 0),
            Step("SELECT last_observed_at", row=(NOW, NOW, existing_cursor, "READY")),
            Step("INSERT INTO ingestion_checkpoint", 1),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        result = repository.commit_observations((observation(),), checkpoint())
        self.assertEqual(result, BatchCommitResult(0, 1))
        self.assertFalse(any("bus_arrival_observation" in sql for sql, _ in connection.cursor_value.statements))

    def test_any_insert_failure_rolls_back_dedupe_and_checkpoint(self):
        connection = FakeConnection((
            Step("SET TRANSACTION"), Step("pg_advisory_xact_lock"),
            Step("INSERT INTO ingestion_checkpoint", 1),
            Step("INSERT INTO bus_arrival_observation", error=RuntimeError("db down")),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        with self.assertRaisesRegex(RuntimeError, "db down"):
            repository.commit_observations((observation(),), checkpoint())
        self.assertEqual((connection.commits, connection.rollbacks), (0, 1))
        self.assertTrue(connection.closed and connection.cursor_value.closed)

    def test_bad_rowcount_fails_and_rolls_back(self):
        connection = FakeConnection((
            Step("SET TRANSACTION"), Step("pg_advisory_xact_lock"),
            Step("INSERT INTO ingestion_checkpoint", 2),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        with self.assertRaisesRegex(DurableRepositoryError, "rowcount"):
            repository.commit_observations((observation(),), checkpoint())
        self.assertEqual(connection.rollbacks, 1)

    def test_same_natural_key_with_different_content_is_conflict_not_duplicate(self):
        connection = FakeConnection((
            Step("SET TRANSACTION"), Step("pg_advisory_xact_lock"),
            Step("INSERT INTO ingestion_checkpoint", 0),
            Step(
                "SELECT last_observed_at",
                row=(NOW, NOW, json.dumps({"observationSha256": "f" * 64}), "READY"),
            ),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        with self.assertRaisesRegex(DurableRepositoryError, "different normalized content"):
            repository.commit_observations((observation(),), checkpoint())
        self.assertEqual(connection.rollbacks, 1)

    def test_quota_and_freshness_state_is_checkpointed_without_observation(self):
        connection = FakeConnection((
            Step("SET TRANSACTION"), Step("INSERT INTO ingestion_checkpoint", 1),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        repository.update_collection_state(
            partition_key="route-1", observed_at=NOW, updated_at=NOW,
            status="QUOTA_LIMITED", quota_remaining=0, freshness_seconds=None,
        )
        sql, parameters = connection.cursor_value.statements[-1]
        cursor_value = json.loads(parameters[-1])
        self.assertEqual(cursor_value["quotaRemaining"], 0)
        self.assertIsNone(cursor_value["freshnessSeconds"])

    def test_dlq_rejects_nested_raw_or_identity_fields_before_connection(self):
        factory = QueueFactory()
        repository = PostgresWorkerRepository(factory, source_id=SOURCE_ID)
        with self.assertRaises(DurableRepositoryError):
            repository.write_dead_letter(
                dedupe_key="a" * 64, reason="SCHEMA_DRIFT", occurred_at=NOW,
                safe_summary={"nested": {"email": "forbidden@example.test"}},
            )
        self.assertEqual(factory.calls, 0)

    def test_quality_and_metric_records_use_canonical_tables(self):
        quality_connection = FakeConnection((Step("SET TRANSACTION"), Step("INSERT INTO data_quality_run", 1)))
        metric_connection = FakeConnection((Step("SET TRANSACTION"), Step("INSERT INTO model_metric", 1)))
        repository = PostgresWorkerRepository(
            QueueFactory(quality_connection, metric_connection), source_id=SOURCE_ID
        )
        run_id = repository.write_quality_run(
            QualityRunRecord(SOURCE_ID, "dataset-v1", "PASS", {"coverage": 1}, (), NOW, NOW)
        )
        metric_id = repository.write_model_metric(
            ModelMetricRecord(MODEL_ID, "test", "route:R1", {"mae": 10}, NOW)
        )
        UUID(run_id)
        UUID(metric_id)

    def test_legacy_lineage_insert_if_absent_and_reconciliation(self):
        data_quality = Path(__file__).parents[1] / "data-quality"
        sys.path.insert(0, str(data_quality))
        try:
            from legacy_sqlite import make_import_record

            record = make_import_record(
                source_sha256="b" * 64, source_table="arrival", source_primary_key=1,
                normalized={"tripId": TRIP_ID, "remainingSeats": None},
            )
        finally:
            sys.path.remove(str(data_quality))
        inserted_connection = FakeConnection((
            Step("SET TRANSACTION"), Step("pg_advisory_xact_lock"),
            Step("INSERT INTO ingestion_checkpoint", 1),
        ))
        duplicate_connection = FakeConnection((
            Step("SET TRANSACTION"), Step("pg_advisory_xact_lock"),
            Step("INSERT INTO ingestion_checkpoint", 0),
            Step(
                "SELECT last_observed_at",
                row=(
                    NOW,
                    NOW,
                    json.dumps(
                        {
                            "normalized": {"remainingSeats": None, "tripId": TRIP_ID},
                            "sourcePrimaryKeySha256": sha256(b"1").hexdigest(),
                            "sourceSha256": "b" * 64,
                            "sourceTable": "arrival",
                        }
                    ),
                    "IMPORTED",
                ),
            ),
        ))
        reconciliation_connection = FakeConnection((
            Step("SET TRANSACTION"), Step("INSERT INTO data_quality_run", 1),
        ))
        repository = PostgresWorkerRepository(
            QueueFactory(inserted_connection, duplicate_connection, reconciliation_connection),
            source_id=SOURCE_ID,
        )
        self.assertTrue(repository.insert_legacy_lineage(record, imported_at=NOW))
        self.assertFalse(repository.insert_legacy_lineage(record, imported_at=NOW))
        repository.write_reconciliation(
            dataset_version="legacy-v1", expected_rows=2, imported_rows=1,
            duplicate_rows=1, started_at=NOW, finished_at=NOW,
        )
        parameters = inserted_connection.cursor_value.statements[-1][1]
        self.assertNotIn("remainingSeats", inserted_connection.cursor_value.statements[-1][0])
        self.assertIn("normalized", json.loads(parameters[-1]))

    def test_registration_and_canonical_transition_deployment_are_atomic(self):
        registration_connection = FakeConnection((
            Step(
                "SET TRANSACTION"
            ),
            Step(
                "INSERT INTO model_family",
                1,
                (FAMILY_ID, "BUS_ETA", "target ETA", "routing-ml"),
            ),
            Step("INSERT INTO model_version", 1),
        ))
        transition_connection = FakeConnection((
            Step("SET TRANSACTION"), Step("SELECT status", row=("VALIDATED",)),
            Step("UPDATE model_version", 1),
            Step("SELECT id", row=None), Step("INSERT INTO model_deployment", 1),
        ))
        repository = PostgresWorkerRepository(
            QueueFactory(registration_connection, transition_connection), source_id=SOURCE_ID
        )
        registration = ModelRegistration(
            FAMILY_ID, MODEL_ID, "ETA", "eta-v1", "target ETA", "routing-ml",
            "gs://approved-models/eta-v1/model.txt", "a" * 64,
            "eta-feature-foundation-v1",
            {
                "calibrationSha256": "c" * 64,
                "datasetSha256": "b" * 64,
                "missingTargetPolicy": "EXCLUDE_UNOBSERVED",
                "modelCardSha256": "d" * 64,
                "splitPolicy": "TEMPORAL_TRIP_GROUP_PURGED",
            },
            NOW,
        )
        self.assertTrue(repository.register_model(registration))
        family_parameters = registration_connection.cursor_value.statements[1][1]
        self.assertEqual(family_parameters[1], "BUS_ETA")
        self.assertNotEqual(family_parameters[1], "ETA")
        deployment = DeploymentRecord(
            "77777777-7777-7777-7777-777777777777", MODEL_ID,
            "staging", "SHADOW", 0.0, NOW,
        )
        repository.transition_model(
            version="eta-v1", expected_state="VALIDATED", target_state="SHADOW",
            deployment=deployment,
        )
        self.assertEqual(transition_connection.commits, 1)
        with self.assertRaises(DurableRepositoryError):
            repository.transition_model(
                version="eta-v1", expected_state="ACTIVE", target_state="ROLLED_BACK"
            )

    def test_model_registration_conflict_checks_immutable_metadata_and_rolls_back(self):
        connection = FakeConnection((
            Step(
                "SET TRANSACTION"
            ),
            Step(
                "INSERT INTO model_family",
                1,
                (FAMILY_ID, "BUS_ETA", "target ETA", "routing-ml"),
            ),
            Step("INSERT INTO model_version", 0),
            Step(
                "SELECT family_id",
                row=(FAMILY_ID, "REGISTERED", "gs://approved-models/other/model.txt", "f" * 64, "eta-feature-foundation-v1", {}),
            ),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        registration = ModelRegistration(
            FAMILY_ID, MODEL_ID, "ETA", "eta-v1", "target ETA", "routing-ml",
            "gs://approved-models/eta-v1/model.txt", "a" * 64,
            "eta-feature-foundation-v1",
            {
                "calibrationSha256": "c" * 64, "datasetSha256": "b" * 64,
                "missingTargetPolicy": "EXCLUDE_UNOBSERVED", "modelCardSha256": "d" * 64,
                "splitPolicy": "TEMPORAL_TRIP_GROUP_PURGED",
            }, NOW,
        )
        with self.assertRaisesRegex(DurableRepositoryError, "different immutable metadata"):
            repository.register_model(registration)
        self.assertEqual(connection.rollbacks, 1)

    def test_model_family_purpose_conflict_checks_immutable_metadata_and_rolls_back(self):
        connection = FakeConnection((
            Step("SET TRANSACTION"),
            Step(
                "INSERT INTO model_family",
                1,
                (FAMILY_ID, "BUS_ETA", "different target", "routing-ml"),
            ),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        registration = ModelRegistration(
            FAMILY_ID, MODEL_ID, "ETA", "eta-v1", "target ETA", "routing-ml",
            "gs://approved-models/eta-v1/model.txt", "a" * 64,
            "eta-feature-foundation-v1",
            {
                "calibrationSha256": "c" * 64, "datasetSha256": "b" * 64,
                "missingTargetPolicy": "EXCLUDE_UNOBSERVED", "modelCardSha256": "d" * 64,
                "splitPolicy": "TEMPORAL_TRIP_GROUP_PURGED",
            }, NOW,
        )

        with self.assertRaisesRegex(DurableRepositoryError, "model family conflict"):
            repository.register_model(registration)

        self.assertEqual((connection.commits, connection.rollbacks), (0, 1))
        self.assertFalse(
            any("INSERT INTO model_version" in sql for sql, _ in connection.cursor_value.statements)
        )

    def test_registration_and_deployment_records_reject_persisted_aliases(self):
        common = dict(
            family_id=FAMILY_ID,
            model_version_id=MODEL_ID,
            version="eta-v1",
            target_definition="target ETA",
            owner="routing-ml",
            artifact_uri="gs://approved-models/eta-v1/model.txt",
            artifact_sha256="a" * 64,
            feature_schema_version="eta-feature-foundation-v1",
            training_scope={
                "calibrationSha256": "c" * 64,
                "datasetSha256": "b" * 64,
                "missingTargetPolicy": "EXCLUDE_UNOBSERVED",
                "modelCardSha256": "d" * 64,
                "splitPolicy": "TEMPORAL_TRIP_GROUP_PURGED",
            },
            created_at=NOW,
        )
        for family in ("BUS_ETA", "CALIBRATION", "TAXI_DISPATCH_WAIT", "eta"):
            with self.subTest(family=family):
                with self.assertRaises(DurableRepositoryError):
                    ModelRegistration(family=family, **common)
        for artifact_uri in (
            "gs://approved-models/eta-v1/model.pkl",
            "gs://approved-models/eta-v1/model.pickle",
            "gs://approved-models/eta-v1/model.joblib",
        ):
            with self.subTest(artifact_uri=artifact_uri):
                with self.assertRaisesRegex(DurableRepositoryError, "non-pickle"):
                    ModelRegistration(family="ETA", **{**common, "artifact_uri": artifact_uri})
        for environment in ("DEVELOPMENT", "STAGING", "PRODUCTION", "production"):
            with self.subTest(environment=environment):
                with self.assertRaises(DurableRepositoryError):
                    DeploymentRecord(
                        "77777777-7777-7777-7777-777777777777",
                        MODEL_ID,
                        environment,
                        "ACTIVE",
                        1.0,
                        NOW,
                    )

    def test_worker_and_repository_model_state_sets_remain_equal(self):
        model_jobs = Path(__file__).parents[1] / "model-jobs"
        sys.path.insert(0, str(model_jobs))
        try:
            from registry import ModelState

            self.assertEqual(CANONICAL_MODEL_STATES, frozenset(item.value for item in ModelState))
        finally:
            sys.path.remove(str(model_jobs))

    def test_django_canonical_environments_are_used_unchanged_in_worker_sql(self):
        for index, environment in enumerate(("dev", "staging", "prod"), start=7):
            with self.subTest(environment=environment):
                connection = FakeConnection((
                    Step("SET TRANSACTION"),
                    Step("SELECT status", row=("VALIDATED",)),
                    Step("UPDATE model_version", 1),
                    Step("SELECT id", row=None),
                    Step("INSERT INTO model_deployment", 1),
                ))
                repository = PostgresWorkerRepository(
                    QueueFactory(connection), source_id=SOURCE_ID
                )
                repository.transition_model(
                    version="eta-v1",
                    expected_state="VALIDATED",
                    target_state="SHADOW",
                    deployment=DeploymentRecord(
                        f"{index}7777777-7777-7777-7777-777777777777",
                        MODEL_ID,
                        environment,
                        "SHADOW",
                        0.0,
                        NOW,
                    ),
                )
                insert = connection.cursor_value.statements[-1]
                self.assertIn("INSERT INTO model_deployment", insert[0])
                self.assertEqual(insert[1][2], environment)
                self.assertNotIn(environment.upper(), insert[1])

    def test_retirement_atomically_closes_active_deployment_interval(self):
        connection = FakeConnection((
            Step("SET TRANSACTION"), Step("SELECT status", row=("ACTIVE",)),
            Step("UPDATE model_version", 1),
            Step("SELECT id", row=("88888888-8888-8888-8888-888888888888", "ACTIVE", 1.0)),
            Step("UPDATE model_deployment", 1),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        repository.transition_model(
            version="eta-v1", expected_state="ACTIVE", target_state="RETIRED",
            deactivation=DeploymentDeactivation(MODEL_ID, "prod", NOW),
        )
        self.assertEqual(connection.commits, 1)
        self.assertEqual(
            connection.cursor_value.statements[-1][1],
            (NOW, "RETIRED", "88888888-8888-8888-8888-888888888888", "ACTIVE"),
        )

    def test_rollback_uses_only_active_and_retired_then_deactivates_interval(self):
        connection = FakeConnection((
            Step("SET TRANSACTION"),
            Step("SELECT status", row=("ACTIVE",)),
            Step("SELECT status", row=("RETIRED",)),
            Step(
                "SELECT id, deployment_state, activated_at",
                row=(
                    "99999999-9999-9999-9999-999999999999",
                    "RETIRED",
                    NOW - timedelta(hours=2),
                    NOW - timedelta(hours=1),
                ),
            ),
            Step("SELECT id", row=("88888888-8888-8888-8888-888888888888", "ACTIVE", 1.0)),
            Step("UPDATE model_version", 1), Step("UPDATE model_version", 1),
            Step("UPDATE model_deployment", 1), Step("INSERT INTO model_deployment", 1),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        repository.rollback_model(
            failed_version="eta-new", failed_model_id=MODEL_ID,
            restore_version="eta-old", restore_model_id=OLD_MODEL_ID,
            environment="prod", occurred_at=NOW,
        )
        state_values = [
            parameters[0] for sql, parameters in connection.cursor_value.statements
            if "UPDATE model_version" in sql
        ]
        self.assertEqual(state_values, ["RETIRED", "ACTIVE"])
        self.assertNotIn("ROLLED_BACK", state_values)
        history_statement = next(
            (sql, parameters)
            for sql, parameters in connection.cursor_value.statements
            if "activated_at IS NOT NULL" in sql
        )
        self.assertEqual(history_statement[1], (OLD_MODEL_ID, "prod", "RETIRED"))

    def test_rollback_without_retired_history_in_target_environment_rolls_back(self):
        connection = FakeConnection((
            Step("SET TRANSACTION"),
            Step("SELECT status", row=("ACTIVE",)),
            Step("SELECT status", row=("RETIRED",)),
            Step("SELECT id, deployment_state, activated_at", row=None),
        ))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)

        with self.assertRaisesRegex(DurableRepositoryError, "no retired deployment history"):
            repository.rollback_model(
                failed_version="eta-new", failed_model_id=MODEL_ID,
                restore_version="eta-old", restore_model_id=OLD_MODEL_ID,
                environment="prod", occurred_at=NOW,
            )

        self.assertEqual((connection.commits, connection.rollbacks), (0, 1))
        self.assertFalse(
            any("UPDATE model_version" in sql for sql, _ in connection.cursor_value.statements)
        )
        self.assertEqual(
            connection.cursor_value.statements[-1][1],
            (OLD_MODEL_ID, "prod", "RETIRED"),
        )

    def test_rollback_rejects_non_retired_or_open_history_defensively(self):
        for history in (
            (
                "99999999-9999-9999-9999-999999999999",
                "ACTIVE",
                NOW - timedelta(hours=2),
                NOW - timedelta(hours=1),
            ),
            (
                "99999999-9999-9999-9999-999999999999",
                "RETIRED",
                NOW - timedelta(hours=2),
                None,
            ),
        ):
            with self.subTest(history=history):
                connection = FakeConnection((
                    Step("SET TRANSACTION"),
                    Step("SELECT status", row=("ACTIVE",)),
                    Step("SELECT status", row=("RETIRED",)),
                    Step("SELECT id, deployment_state, activated_at", row=history),
                ))
                repository = PostgresWorkerRepository(
                    QueueFactory(connection), source_id=SOURCE_ID
                )

                with self.assertRaises(DurableRepositoryError):
                    repository.rollback_model(
                        failed_version="eta-new", failed_model_id=MODEL_ID,
                        restore_version="eta-old", restore_model_id=OLD_MODEL_ID,
                        environment="prod", occurred_at=NOW,
                    )

                self.assertEqual((connection.commits, connection.rollbacks), (0, 1))

    def test_prediction_audit_persists_only_hashes_of_entity_and_input(self):
        connection = FakeConnection((Step("SET TRANSACTION"), Step("INSERT INTO prediction_audit", 1)))
        repository = PostgresWorkerRepository(QueueFactory(connection), source_id=SOURCE_ID)
        repository.write_prediction_audit(
            model_version_id=MODEL_ID, model_version="eta-v1", request_id="opaque-request",
            entity_key="tokenized-vehicle", feature_schema_version="eta-feature-foundation-v1",
            input_summary={"route": "R1", "remainingStops": 3}, prediction={"p50": 100.0},
            created_at=NOW,
        )
        sql, parameters = connection.cursor_value.statements[-1]
        self.assertNotIn("tokenized-vehicle", sql)
        self.assertNotIn("tokenized-vehicle", parameters)
        self.assertNotIn("R1", parameters)


if __name__ == "__main__":
    unittest.main()
