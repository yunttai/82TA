from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

WORKERS = Path(__file__).parents[1]
if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))

from collector_foundation import CheckpointState, ObservationMetadata
from collector_runtime import CollectedObservation, DeadLetter
from collector_postgres_adapter import PostgresCollectorAdapter
from routing_worker.repositories import BatchCommitResult


UTC = timezone.utc
NOW = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)


class RecordingRepository:
    source_id = "11111111-1111-1111-1111-111111111111"

    def __init__(self):
        self.committed = None
        self.dlq = None

    def load_checkpoint(self, partition_key):
        return None

    def has_dedupe(self, dedupe_key):
        return False

    def commit_observations(self, rows, checkpoint):
        self.committed = (rows, checkpoint)
        return BatchCommitResult(len(rows), 0)

    def write_dead_letter(self, **values):
        self.dlq = values


class PostgresCollectorAdapterTest(unittest.TestCase):
    def test_normalized_arrival_is_strictly_converted_and_null_seat_is_preserved(self):
        repository = RecordingRepository()
        adapter = PostgresCollectorAdapter(repository, source_code="gbis")
        metadata = ObservationMetadata(NOW, NOW, NOW + timedelta(seconds=1), "GBIS", "v1")
        item = CollectedObservation(
            "gbis", "route-1", "vehicle-1", metadata,
            {
                "observationType": "ARRIVAL",
                "tripId": "22222222-2222-2222-2222-222222222222",
                "stopId": "33333333-3333-3333-3333-333333333333",
                "providerEtaSeconds": 90,
                "remainingSeats": None,
                "predictedArrivalAt": "2026-08-23T01:01:30+00:00",
            },
        )
        checkpoint = CheckpointState(
            "gbis", "route-1", NOW, NOW + timedelta(seconds=2), "{}", "a" * 64,
        )
        result = adapter.commit_batch((item,), checkpoint)
        self.assertEqual((result.inserted, result.duplicate), (1, 0))
        durable = repository.committed[0][0]
        self.assertIsNone(durable.remaining_seats)
        self.assertEqual(durable.provider_eta_seconds, 90)

    def test_raw_or_extra_shape_is_rejected_before_repository(self):
        repository = RecordingRepository()
        adapter = PostgresCollectorAdapter(repository, source_code="gbis")
        item = CollectedObservation(
            "gbis", "route-1", "vehicle-1",
            ObservationMetadata(NOW, NOW, NOW, "GBIS", "v1"),
            {
                "observationType": "ARRIVAL", "tripId": "x", "stopId": "y",
                "providerEtaSeconds": 1, "remainingSeats": 1,
                "predictedArrivalAt": None, "rawPayload": {},
            },
        )
        checkpoint = CheckpointState("gbis", "route-1", NOW, NOW, "{}", "a" * 64)
        with self.assertRaises(ValueError):
            adapter.commit_batch((item,), checkpoint)
        self.assertIsNone(repository.committed)

    def test_dead_letter_contains_only_sanitized_summary(self):
        repository = RecordingRepository()
        adapter = PostgresCollectorAdapter(repository, source_code="gbis")
        adapter.dead_letter(
            DeadLetter("gbis", "route-1", "a" * 64, "SCHEMA_DRIFT", NOW, (("schemaVersion", "v1"),))
        )
        self.assertEqual(repository.dlq["safe_summary"], {"schemaVersion": "v1"})


if __name__ == "__main__":
    unittest.main()
