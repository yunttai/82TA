from datetime import date, datetime, timedelta, timezone
import unittest

from collector_foundation import (
    CanonicalTripIdentity,
    CheckpointConflictError,
    CheckpointEvent,
    ObservationMetadata,
    advance_checkpoint,
)


UTC = timezone.utc


class CollectorFoundationTest(unittest.TestCase):
    def test_trip_identity_is_stable_and_reset_sensitive(self) -> None:
        base = dict(
            route_id="route-1",
            direction="UP",
            vehicle_token="tokenized-vehicle",
            service_date=date(2026, 8, 23),
            inferred_start_at=datetime(2026, 8, 23, 0, 0, tzinfo=UTC),
        )
        first = CanonicalTripIdentity(**base, station_sequence_reset=0)
        same = CanonicalTripIdentity(**base, station_sequence_reset=0)
        next_trip = CanonicalTripIdentity(**base, station_sequence_reset=1)
        self.assertEqual(first.key, same.key)
        self.assertNotEqual(first.key, next_trip.key)
        self.assertNotIn("tokenized-vehicle", first.key)

    def test_observation_clocks_remain_distinct_and_skew_is_flagged(self) -> None:
        observed = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        metadata = ObservationMetadata(
            observed_at=observed,
            valid_at=observed + timedelta(seconds=30),
            ingested_at=observed - timedelta(seconds=1),
            source="fixture",
            schema_version="v1",
            quality_flags=("MISSING_OPTIONAL_FIELD", "MISSING_OPTIONAL_FIELD"),
        )
        self.assertEqual(
            metadata.quality_flags,
            ("MISSING_OPTIONAL_FIELD", "SOURCE_CLOCK_AHEAD"),
        )
        self.assertNotEqual(metadata.observed_at, metadata.valid_at)

    def test_checkpoint_retry_is_idempotent_and_stale_input_cannot_regress(self) -> None:
        watermark = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        event = CheckpointEvent(
            source_id="gbis",
            partition_key="route-1",
            observed_at=watermark,
            completed_at=watermark + timedelta(seconds=2),
            cursor={"page": 2, "nested": {"offset": 5}},
        )
        first = advance_checkpoint(None, event)
        retry = advance_checkpoint(first.state, event)
        stale = advance_checkpoint(
            first.state,
            CheckpointEvent(
                source_id="gbis",
                partition_key="route-1",
                observed_at=watermark - timedelta(seconds=1),
                completed_at=watermark + timedelta(seconds=3),
                cursor={"page": 1},
            ),
        )
        self.assertEqual(first.disposition, "ADVANCED")
        self.assertEqual(retry.disposition, "DUPLICATE")
        self.assertIs(retry.state, first.state)
        self.assertEqual(stale.disposition, "STALE")
        self.assertIs(stale.state, first.state)

    def test_checkpoint_rejects_ambiguous_same_watermark(self) -> None:
        watermark = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        first = advance_checkpoint(
            None,
            CheckpointEvent(
                "gbis", "route-1", watermark, watermark, {"page": 1}
            ),
        )
        with self.assertRaises(CheckpointConflictError):
            advance_checkpoint(
                first.state,
                CheckpointEvent(
                    "gbis", "route-1", watermark, watermark, {"page": 2}
                ),
            )


if __name__ == "__main__":
    unittest.main()
