from datetime import datetime, timedelta, timezone
from importlib import resources
import re
import unittest

from provider_core.adapters import FixtureScenario, FixtureTransitAdapter
from provider_core.canonical import Coordinate, TravelMode
from provider_core.envelope import Freshness, ProviderStatus, QualityFlag
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline


class FixtureAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [100.0]
        self.deadline = Deadline.after_ms(1000, clock=lambda: self.now[0])
        self.request = TransitSearchRequest(
            origin=Coordinate(127.1, 37.4),
            destination=Coordinate(127.2, 37.5),
            departure_time=datetime(2026, 8, 23, 8, 0, tzinfo=timezone(timedelta(hours=9))),
        )

    def run_scenario(self, scenario: FixtureScenario):
        return FixtureTransitAdapter(scenario).search(self.request, deadline=self.deadline)

    def test_success_normalizes_without_raw_payload(self) -> None:
        result = self.run_scenario(FixtureScenario.SUCCESS)
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.normalized_count, 1)
        self.assertEqual(result.freshness, Freshness.FRESH)
        self.assertIn(QualityFlag.SCHEMA_VALIDATED, result.quality_flags)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", result.fingerprint))
        itinerary = result.payload[0]  # type: ignore[index]
        self.assertEqual(itinerary.legs[0].mode, TravelMode.BUS)
        self.assertEqual(itinerary.legs[0].transit.external_route_id, "sanitized-route-100")
        self.assertFalse(isinstance(result.payload, dict))

    def test_r1_r4_success_variants_match_requests_and_are_unique_sanitized_topologies(self) -> None:
        replay_cases = (
            (FixtureScenario.R1_SUCCESS, (127.187456, 37.222345), (127.111159, 37.394761), "2026-08-24T07:40:00+09:00"),
            (FixtureScenario.R2_SUCCESS, (127.111159, 37.394761), (127.187456, 37.222345), "2026-08-24T18:10:00+09:00"),
            (FixtureScenario.R3_SUCCESS, (127.0510, 37.2890), (127.111159, 37.394761), "2026-08-24T08:05:00+09:00"),
            (FixtureScenario.R4_SUCCESS, (127.111159, 37.394761), (127.0510, 37.2890), "2026-08-24T19:20:00+09:00"),
        )
        itinerary_ids: set[str] = set()
        route_ids: set[str] = set()
        stop_ids: set[str] = set()
        directions: set[str] = set()
        for scenario, origin, destination, departure_text in replay_cases:
            with self.subTest(scenario=scenario):
                departure = datetime.fromisoformat(departure_text)
                request = TransitSearchRequest(
                    origin=Coordinate(*origin),
                    destination=Coordinate(*destination),
                    departure_time=departure,
                )
                result = FixtureTransitAdapter(scenario).search(request, deadline=self.deadline)
                self.assertEqual(result.status, ProviderStatus.OK)
                self.assertEqual(result.normalized_count, 1)
                self.assertIn(QualityFlag.SANITIZED_FIXTURE, result.quality_flags)
                self.assertNotIsInstance(result.payload, dict)
                itinerary = result.payload[0]  # type: ignore[index]
                first = itinerary.legs[0]
                last = itinerary.legs[-1]
                self.assertEqual(first.from_stop.coordinate, request.origin)
                self.assertEqual(last.to_stop.coordinate, request.destination)
                self.assertEqual(first.geometry[0], request.origin)
                self.assertEqual(last.geometry[-1], request.destination)
                self.assertEqual(first.expected_start_at, departure)
                self.assertEqual(result.observed_at, departure)
                self.assertGreaterEqual(first.duration.p90_seconds, first.duration.p50_seconds)
                self.assertEqual(
                    int((first.expected_end_at - first.expected_start_at).total_seconds()),  # type: ignore[operator]
                    first.duration.p50_seconds,
                )
                self.assertIsNotNone(first.transit)
                itinerary_ids.add(itinerary.itinerary_id)
                route_ids.add(first.transit.external_route_id)  # type: ignore[arg-type,union-attr]
                directions.add(first.transit.direction)  # type: ignore[arg-type,union-attr]
                stop_ids.update((first.from_stop.external_id, last.to_stop.external_id))  # type: ignore[arg-type]
                raw_text = resources.files("provider_core").joinpath(
                    "fixtures", f"transit_{scenario.value}.json"
                ).read_text(encoding="utf-8")
                for forbidden in ("apiKey", "authorization", "credential", "password", "accessToken", "plateNumber"):
                    self.assertNotIn(forbidden, raw_text)
        self.assertEqual(len(itinerary_ids), 4)
        self.assertEqual(len(route_ids), 4)
        self.assertEqual(len(directions), 4)
        self.assertEqual(len(stop_ids), 8)
        with self.assertRaises(ValueError):
            FixtureScenario("../../caller-selected-path")

    def test_empty_is_valid_zero_not_unavailable(self) -> None:
        result = self.run_scenario(FixtureScenario.EMPTY)
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.payload, ())
        self.assertEqual(result.normalized_count, 0)
        self.assertIn(QualityFlag.EMPTY_RESULT, result.quality_flags)

    def test_timeout_is_sanitized_failure(self) -> None:
        result = self.run_scenario(FixtureScenario.TIMEOUT)
        self.assertEqual(result.status, ProviderStatus.TIMEOUT)
        self.assertIsNone(result.payload)
        self.assertIsNone(result.message_code)

    def test_429_is_not_collapsed_into_timeout(self) -> None:
        result = self.run_scenario(FixtureScenario.RATE_LIMITED)
        self.assertEqual(result.status, ProviderStatus.RATE_LIMITED)
        self.assertEqual(result.message_code, "RATE_LIMITED")

    def test_schema_drift_degrades_without_defaults(self) -> None:
        result = self.run_scenario(FixtureScenario.SCHEMA_DRIFT)
        self.assertEqual(result.status, ProviderStatus.BAD_RESPONSE)
        self.assertIsNone(result.payload)
        self.assertIn(QualityFlag.SCHEMA_DRIFT, result.quality_flags)
        self.assertIsNone(result.observed_at)

    def test_expired_deadline_prevents_adapter_work(self) -> None:
        self.now[0] = 102.0
        with self.assertRaises(TimeoutError):
            self.run_scenario(FixtureScenario.SUCCESS)


if __name__ == "__main__":
    unittest.main()
