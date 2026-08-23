from datetime import datetime, timedelta, timezone
import unittest

from collector_foundation import ObservationMetadata
from collector_runtime import (
    BatchCommitResult,
    CollectedObservation,
    CollectorPolicy,
    InMemoryQuota,
    QuotaWindow,
    collect_batch,
)


UTC = timezone.utc


class MemoryRepository:
    def __init__(self):
        self.checkpoints = {}
        self.observations = {}
        self.dead_letters = []

    def checkpoint(self, source_id, partition_key):
        return self.checkpoints.get((source_id, partition_key))

    def has_observation(self, dedupe_key):
        return dedupe_key in self.observations

    def commit_batch(self, observations, checkpoint):
        inserted = duplicate = 0
        for item in observations:
            if item.dedupe_key in self.observations:
                duplicate += 1
            else:
                self.observations[item.dedupe_key] = item
                inserted += 1
        self.checkpoints[(checkpoint.source_id, checkpoint.partition_key)] = checkpoint
        return BatchCommitResult(inserted, duplicate)

    def dead_letter(self, item):
        self.dead_letters.append(item)


class CollectorRuntimeTest(unittest.TestCase):
    def observation(self, at, natural="vehicle-1"):
        return CollectedObservation(
            "gbis", "route-1", natural,
            ObservationMetadata(at, at, at + timedelta(seconds=1), "GBIS", "v1"),
            {"tripId": "opaque", "remainingSeats": None},
        )

    def test_batch_checkpoint_and_dedupe_are_atomic_and_idempotent(self):
        now = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        rows = (self.observation(now - timedelta(seconds=2)), self.observation(now - timedelta(seconds=1), "vehicle-2"))
        repository = MemoryRepository()
        quota = InMemoryQuota(QuotaWindow(3, 60))
        first = collect_batch(
            rows, source_id="gbis", partition_key="route-1", now=now, cursor={"page": 1},
            repository=repository, quota=quota, policy=CollectorPolicy(60),
        )
        retry = collect_batch(
            rows, source_id="gbis", partition_key="route-1", now=now + timedelta(seconds=1),
            cursor={"page": 1}, repository=repository, quota=quota, policy=CollectorPolicy(60),
        )
        self.assertEqual(first.accepted, 2)
        self.assertEqual(retry.duplicate, 2)
        self.assertEqual(len(repository.observations), 2)

    def test_stale_and_invalid_rows_go_to_sanitized_dlq(self):
        now = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        repository = MemoryRepository()
        result = collect_batch(
            (self.observation(now - timedelta(minutes=5)),), source_id="gbis",
            partition_key="route-1", now=now, cursor={}, repository=repository,
            quota=InMemoryQuota(QuotaWindow(1, 60)), policy=CollectorPolicy(30),
            validate=lambda _: ("SCHEMA_DRIFT",),
        )
        self.assertEqual((result.accepted, result.rejected), (0, 1))
        self.assertEqual(repository.dead_letters[0].reason, "SCHEMA_DRIFT|STALE_OBSERVATION")
        self.assertEqual(repository.dead_letters[0].safe_summary, (("schemaVersion", "v1"),))

    def test_quota_exhaustion_does_not_call_or_advance(self):
        now = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        quota = InMemoryQuota(QuotaWindow(1, 60))
        repository = MemoryRepository()
        quota.reserve("gbis", now)
        result = collect_batch(
            (), source_id="gbis", partition_key="route-1", now=now, cursor={},
            repository=repository, quota=quota, policy=CollectorPolicy(30),
        )
        self.assertTrue(result.quota_limited)
        self.assertIsNone(result.checkpoint)


if __name__ == "__main__":
    unittest.main()
