from datetime import datetime, timedelta, timezone
import math
import unittest

from provider_core.canonical import Coordinate
from provider_core.context import TrafficLinkContext, WeatherContext
from provider_core.context_queries import (
    GITS_TRAFFIC_QUERY_VERSION,
    GitsTrafficCorridorQuery,
    KMA_GRID_CONVERSION_VERSION,
    KMA_WEATHER_QUERY_VERSION,
    KmaGrid,
    KmaWeatherQuery,
    MAX_TRAFFIC_CORRIDOR_POINTS,
)
from provider_core.envelope import ProviderStatus, QualityFlag
from provider_core.named import (
    GitsTrafficAdapter,
    KmaContextAdapter,
    ProviderFixtureScenario,
)
from provider_core.resilience import Deadline
from provider_core.validation import InputValidationError


KST = timezone(timedelta(hours=9))


class NoCallTransport:
    def __init__(self) -> None:
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        raise AssertionError("disabled context provider attempted network I/O")


class ContextQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinate = Coordinate(127.10, 37.39)
        self.observed_at = datetime(2026, 8, 24, 8, 49, tzinfo=KST)
        self.deadline = Deadline.after_ms(1000, clock=lambda: 10.0)
        self.transport = NoCallTransport()

    def test_kma_projection_and_request_identity_are_versioned_and_deterministic(self) -> None:
        self.assertEqual(KmaGrid.from_coordinate(Coordinate(126.978, 37.5665)), KmaGrid(60, 127))
        self.assertEqual(KmaGrid.from_coordinate(self.coordinate), KmaGrid(62, 123))
        request = KmaWeatherQuery.from_coordinate(self.coordinate, self.observed_at)
        same_instant = KmaWeatherQuery.from_coordinate(
            self.coordinate, self.observed_at.astimezone(timezone.utc)
        )
        self.assertEqual(request.fingerprint(), same_instant.fingerprint())
        self.assertEqual(request.grid.conversion_version, KMA_GRID_CONVERSION_VERSION)
        self.assertEqual(request.identity_version, KMA_WEATHER_QUERY_VERSION)
        self.assertEqual(request.provider_query, (("nx", 62), ("ny", 123), ("dataType", "JSON")))

    def test_kma_grid_coordinate_mismatch_and_naive_time_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            KmaWeatherQuery(self.coordinate, self.observed_at, KmaGrid(60, 120))
        with self.assertRaises(ValueError):
            KmaWeatherQuery.from_coordinate(
                self.coordinate, datetime(2026, 8, 24, 8, 49)
            )
        with self.assertRaises(InputValidationError):
            KmaContextAdapter(self.transport).context(
                nx=60,
                ny=120,
                coordinate=self.coordinate,
                observed_at=self.observed_at,
                deadline=self.deadline,
            )

    def test_disabled_context_calls_keep_capability_false_and_burn_zero_network(self) -> None:
        weather_request = KmaWeatherQuery.from_coordinate(
            self.coordinate, self.observed_at
        )
        traffic_request = GitsTrafficCorridorQuery.from_bounds(
            self.coordinate, Coordinate(127.11, 37.40), self.observed_at
        )
        weather = KmaContextAdapter(self.transport).context_query(
            weather_request, deadline=self.deadline
        )
        traffic = GitsTrafficAdapter(self.transport).context_query(
            traffic_request, deadline=self.deadline
        )
        self.assertEqual(weather.status, ProviderStatus.DISABLED)
        self.assertEqual(traffic.status, ProviderStatus.DISABLED)
        self.assertEqual(weather.fingerprint, weather_request.fingerprint())
        self.assertEqual(traffic.fingerprint, traffic_request.fingerprint())
        self.assertEqual(self.transport.calls, [])

    def test_corridor_query_bounds_points_span_padding_and_link_identity(self) -> None:
        request = GitsTrafficCorridorQuery.from_corridor(
            (self.coordinate, Coordinate(127.11, 37.40)),
            self.observed_at,
            relevant_link_external_ids=("link-b", "link-a"),
            maximum_links=16,
            padding_meters=250,
        )
        reordered = GitsTrafficCorridorQuery.from_corridor(
            (self.coordinate, Coordinate(127.11, 37.40)),
            self.observed_at.astimezone(timezone.utc),
            relevant_link_external_ids=("link-a", "link-b"),
            maximum_links=16,
            padding_meters=250,
        )
        self.assertEqual(request.identity_version, GITS_TRAFFIC_QUERY_VERSION)
        self.assertEqual(request.fingerprint(), reordered.fingerprint())
        self.assertTrue(request.accepts_link("link-a"))
        self.assertFalse(request.accepts_link("link-c"))
        self.assertLess(request.bounding_box.minimum.lon, self.coordinate.lon)
        self.assertGreater(request.bounding_box.maximum.lat, 37.40)
        with self.assertRaises(ValueError):
            GitsTrafficCorridorQuery.from_corridor(
                tuple(self.coordinate for _ in range(MAX_TRAFFIC_CORRIDOR_POINTS + 1)),
                self.observed_at,
            )
        with self.assertRaises(ValueError):
            GitsTrafficCorridorQuery.from_bounds(
                Coordinate(124.5, 33.5), Coordinate(131.5, 39.0), self.observed_at
            )
        with self.assertRaises(ValueError):
            GitsTrafficCorridorQuery.from_corridor(
                (self.coordinate, Coordinate(127.11, 37.40)),
                self.observed_at,
                padding_meters=5_001,
            )

    def test_fixture_context_preserves_zero_and_future_observation_for_downstream_as_of(self) -> None:
        weather_request = KmaWeatherQuery.from_coordinate(
            self.coordinate, self.observed_at
        )
        envelope = KmaContextAdapter(self.transport).fixture_context(
            weather_request, ProviderFixtureScenario.SUCCESS
        )
        self.assertEqual(envelope.status, ProviderStatus.OK)
        self.assertEqual(len(envelope.payload), 1)
        context = envelope.payload[0]
        self.assertIsInstance(context, WeatherContext)
        self.assertEqual(context.precipitation_mm, 0.0)
        self.assertGreater(context.observed_at, weather_request.observed_at)
        self.assertEqual(
            context.observed_at,
            datetime(2026, 8, 24, 8, 50, tzinfo=KST),
        )

    def test_fixture_schema_and_corridor_link_guards_fail_closed(self) -> None:
        weather_request = KmaWeatherQuery.from_coordinate(
            self.coordinate, self.observed_at
        )
        weather_drift = KmaContextAdapter(self.transport).fixture_context(
            weather_request, ProviderFixtureScenario.SCHEMA_DRIFT
        )
        self.assertEqual(weather_drift.status, ProviderStatus.BAD_RESPONSE)
        self.assertIn(QualityFlag.SCHEMA_DRIFT, weather_drift.quality_flags)

        matching = GitsTrafficCorridorQuery.from_bounds(
            self.coordinate,
            Coordinate(127.11, 37.40),
            self.observed_at,
            maximum_links=1,
        )
        traffic = GitsTrafficAdapter(self.transport).fixture_context(
            matching, ProviderFixtureScenario.SUCCESS
        )
        self.assertEqual(traffic.status, ProviderStatus.OK)
        self.assertIsInstance(traffic.payload[0], TrafficLinkContext)

        disallowed = GitsTrafficCorridorQuery.from_corridor(
            (self.coordinate, Coordinate(127.11, 37.40)),
            self.observed_at,
            relevant_link_external_ids=("different-link",),
        )
        rejected = GitsTrafficAdapter(self.transport).fixture_context(
            disallowed, ProviderFixtureScenario.SUCCESS
        )
        self.assertEqual(rejected.status, ProviderStatus.BAD_RESPONSE)
        self.assertIsNone(rejected.payload)
        self.assertIn(QualityFlag.SCHEMA_DRIFT, rejected.quality_flags)

    def test_normalized_context_rejects_nonfinite_but_preserves_observed_zero(self) -> None:
        with self.assertRaises(ValueError):
            WeatherContext(self.coordinate, self.observed_at, math.nan, 0.0)
        with self.assertRaises(ValueError):
            WeatherContext(self.coordinate, self.observed_at, None, None)
        traffic = TrafficLinkContext("link-zero", 0, 0.0, self.observed_at)
        self.assertEqual(traffic.speed_kph, 0)
        self.assertEqual(traffic.travel_time_seconds, 0.0)
        with self.assertRaises(ValueError):
            TrafficLinkContext("link-inf", 0, math.inf, self.observed_at)


if __name__ == "__main__":
    unittest.main()
