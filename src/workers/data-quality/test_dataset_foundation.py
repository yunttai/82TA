from datetime import datetime, timedelta, timezone
import unittest

from dataset_foundation import (
    DatasetInvariantError,
    DatasetSample,
    NullableTarget,
    TargetStopLabels,
    TargetStopObservation,
    build_target_stop_labels,
    temporal_trip_group_split,
)


UTC = timezone.utc


class DatasetFoundationTest(unittest.TestCase):
    def test_absent_future_observation_is_unobserved_not_negative(self) -> None:
        cutoff = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        labels = build_target_stop_labels(
            trip_id="trip-1",
            target_stop_id="target",
            feature_observed_at=cutoff,
            observations=[
                TargetStopObservation(
                    "trip-1", "target", cutoff - timedelta(seconds=1), 0
                ),
                TargetStopObservation(
                    "other-trip", "target", cutoff + timedelta(seconds=60), 0
                ),
            ],
        )
        for target in (
            labels.eta_seconds,
            labels.no_seat,
            labels.low_seat_le_2,
            labels.low_seat_le_5,
            labels.seat_ordinal_class,
        ):
            self.assertFalse(target.has_target)
            self.assertIsNone(target.value)
            self.assertIsNone(target.observed_at)

    def test_eta_and_seat_targets_are_separate(self) -> None:
        cutoff = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        labels = build_target_stop_labels(
            trip_id="trip-1",
            target_stop_id="target",
            feature_observed_at=cutoff,
            observations=[
                TargetStopObservation(
                    "trip-1", "target", cutoff + timedelta(seconds=90), None
                )
            ],
        )
        self.assertTrue(labels.eta_seconds.has_target)
        self.assertEqual(labels.eta_seconds.value, 90)
        self.assertFalse(labels.no_seat.has_target)
        self.assertIsNone(labels.no_seat.value)
        self.assertFalse(labels.seat_ordinal_class.has_target)
        self.assertIsNone(labels.seat_ordinal_class.value)

    def test_observed_zero_seats_is_a_real_positive_target(self) -> None:
        cutoff = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        labels = build_target_stop_labels(
            trip_id="trip-1",
            target_stop_id="target",
            feature_observed_at=cutoff,
            observations=[
                TargetStopObservation(
                    "trip-1", "target", cutoff + timedelta(seconds=30), 0
                )
            ],
        )
        self.assertTrue(labels.no_seat.has_target)
        self.assertIs(labels.no_seat.value, True)
        self.assertEqual(labels.seat_ordinal_class.value, 0)

    def test_observed_seats_map_to_one_nullable_ordinal_training_target(self) -> None:
        cutoff = datetime(2026, 8, 23, 1, 0, tzinfo=UTC)
        expected = {0: 0, 1: 1, 2: 1, 3: 2, 5: 2, 6: 3, 40: 3}
        for remaining, ordinal in expected.items():
            with self.subTest(remaining=remaining):
                observed_at = cutoff + timedelta(seconds=remaining + 1)
                labels = build_target_stop_labels(
                    trip_id="trip-1",
                    target_stop_id="target",
                    feature_observed_at=cutoff,
                    observations=[
                        TargetStopObservation(
                            "trip-1", "target", observed_at, remaining
                        )
                    ],
                )
                self.assertTrue(labels.seat_ordinal_class.has_target)
                self.assertEqual(labels.seat_ordinal_class.value, ordinal)
                self.assertEqual(labels.seat_ordinal_class.observed_at, observed_at)
                self.assertEqual(
                    (
                        labels.no_seat.value,
                        labels.low_seat_le_2.value,
                        labels.low_seat_le_5.value,
                    ),
                    (remaining == 0, remaining <= 2, remaining <= 5),
                )

    def test_temporal_split_purges_boundary_crossing_trip(self) -> None:
        validation_start = datetime(2026, 8, 20, tzinfo=UTC)
        test_start = datetime(2026, 8, 22, tzinfo=UTC)
        samples = [
            DatasetSample("train-row", "train-trip", validation_start - timedelta(days=1)),
            DatasetSample("valid-row", "valid-trip", validation_start),
            DatasetSample("test-row", "test-trip", test_start),
            DatasetSample("cross-a", "cross-trip", validation_start - timedelta(seconds=1)),
            DatasetSample("cross-b", "cross-trip", validation_start + timedelta(seconds=1)),
        ]
        split = temporal_trip_group_split(
            samples,
            validation_start=validation_start,
            test_start=test_start,
        )
        self.assertEqual(split.train, ("train-row",))
        self.assertEqual(split.validation, ("valid-row",))
        self.assertEqual(split.test, ("test-row",))
        self.assertEqual(split.purged, ("cross-a", "cross-b"))
        self.assertEqual(split.purged_trip_ids, ("cross-trip",))

    def test_direct_target_labels_reject_inconsistent_training_targets(self) -> None:
        observed = datetime(2026, 8, 23, 1, 1, tzinfo=UTC)
        later = observed + timedelta(seconds=1)
        eta = NullableTarget(True, 60, observed)
        present = lambda value, at=observed: NullableTarget(True, value, at)
        missing = NullableTarget(False, None, None)

        with self.assertRaisesRegex(DatasetInvariantError, "non-negative integer"):
            TargetStopLabels(
                NullableTarget(True, -1, observed),
                missing,
                missing,
                missing,
                missing,
            )
        with self.assertRaisesRegex(DatasetInvariantError, "all-present or all-missing"):
            TargetStopLabels(eta, present(False), present(True), missing, present(1))
        with self.assertRaisesRegex(DatasetInvariantError, "share observed_at"):
            TargetStopLabels(
                eta,
                present(False),
                present(True),
                present(True, later),
                present(1),
            )
        with self.assertRaisesRegex(DatasetInvariantError, "exactly match"):
            TargetStopLabels(
                eta,
                present(True),
                present(False),
                present(True),
                present(0),
            )
        with self.assertRaisesRegex(DatasetInvariantError, "exactly match"):
            TargetStopLabels(
                eta,
                present(False),
                present(True),
                present(True),
                present(2),
            )


if __name__ == "__main__":
    unittest.main()
