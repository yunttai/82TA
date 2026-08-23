from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import unittest

from provider_core.canonical import (
    CanonicalItinerary,
    CanonicalLeg,
    CanonicalStop,
    Coordinate,
    DataOrigin,
    MoneyRange,
    TimeEstimate,
    TransitDescriptor,
    TravelMode,
)
from provider_core.envelope import Freshness, classify_freshness


class CanonicalValueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.a = CanonicalStop("A", Coordinate(127.1, 37.4), "a", 1)
        self.b = CanonicalStop("B", Coordinate(127.2, 37.5), "b", 2)
        self.start = datetime(2026, 8, 23, 8, 0, tzinfo=timezone(timedelta(hours=9)))

    def make_leg(self) -> CanonicalLeg:
        return CanonicalLeg(
            leg_id="leg-1",
            sequence=0,
            mode=TravelMode.BUS,
            from_stop=self.a,
            to_stop=self.b,
            duration=TimeEstimate(600, 720, DataOrigin.PROVIDER_ESTIMATE),
            distance_meters=3000,
            fare=MoneyRange(2800, 2800, 2800, DataOrigin.PROVIDER_ESTIMATE),
            expected_start_at=self.start,
            expected_end_at=self.start + timedelta(seconds=600),
            transit=TransitDescriptor(route_label="S-1", boarding_sequence=1, alighting_sequence=2),
            geometry=(self.a.coordinate, self.b.coordinate),
        )

    def test_values_are_immutable_and_itinerary_is_valid(self) -> None:
        itinerary = CanonicalItinerary("route-1", (self.make_leg(),))
        self.assertEqual(itinerary.legs[0].duration.p90_seconds, 720)
        with self.assertRaises(FrozenInstanceError):
            itinerary.itinerary_id = "changed"  # type: ignore[misc]

    def test_p90_must_not_be_below_p50(self) -> None:
        with self.assertRaisesRegex(ValueError, "p90"):
            TimeEstimate(100, 99, DataOrigin.PROVIDER_ESTIMATE)

    def test_unknown_and_zero_are_distinct(self) -> None:
        zero = MoneyRange(0, 0, 0, DataOrigin.PROVIDER_ESTIMATE)
        self.assertEqual(zero.upper_krw, 0)
        self.assertIsNone(TransitDescriptor().live_vehicle_observed)

    def test_transit_mode_requires_descriptor(self) -> None:
        with self.assertRaisesRegex(ValueError, "TransitDescriptor"):
            CanonicalLeg(
                "leg", 0, TravelMode.BUS, self.a, self.b,
                TimeEstimate(10, 10, DataOrigin.PROVIDER_ESTIMATE), 1,
                MoneyRange(0, 0, 0, DataOrigin.PROVIDER_ESTIMATE),
            )

    def test_naive_times_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            CanonicalLeg(
                "leg", 0, TravelMode.WALK, self.a, self.b,
                TimeEstimate(10, 10, DataOrigin.PROVIDER_ESTIMATE), 1,
                MoneyRange(0, 0, 0, DataOrigin.PROVIDER_ESTIMATE),
                expected_start_at=datetime(2026, 8, 23, 8, 0),
            )

    def test_freshness_preserves_unknown_and_stale(self) -> None:
        self.assertEqual(
            classify_freshness(received_at=self.start, observed_at=None, maximum_age_seconds=60),
            Freshness.UNKNOWN,
        )
        self.assertEqual(
            classify_freshness(
                received_at=self.start,
                observed_at=self.start - timedelta(seconds=61),
                maximum_age_seconds=60,
            ),
            Freshness.STALE,
        )


if __name__ == "__main__":
    unittest.main()
