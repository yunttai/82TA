from datetime import datetime, timedelta, timezone
from importlib import resources
import unittest

from provider_core.canonical import Coordinate
from provider_core.context import (
    BusArrivalObservation, BusLocationObservation, BusRouteRecord,
    BusStationRecord, TrafficLinkContext, WeatherContext,
)
from provider_core.envelope import ProviderStatus, QualityFlag
from provider_core.http import AuthInjection, HttpRequest, HttpResponse, SensitiveValue
from provider_core.named import (
    ENDPOINT_SPECS, GbisAdapter, GitsTrafficAdapter, KakaoMobilityDirectionsAdapter,
    KakaoTransitAdapter, KakaoWalkAdapter, KmaContextAdapter, OdsayTransitAdapter,
    ProviderAdapterSuite, ProviderFixtureScenario, TmapTransitAdapter,
)
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from provider_core.telemetry import MemoryTelemetrySink
from provider_core.validation import InputValidationError, SchemaValidationError


KST = timezone(timedelta(hours=9))


class NoCallTransport:
    def __init__(self) -> None:
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        raise AssertionError("disabled provider attempted network I/O")


class NamedProviderSuiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = NoCallTransport()
        self.telemetry = MemoryTelemetrySink()
        self.now = datetime(2026, 8, 24, 7, 0, tzinfo=KST)
        self.deadline = Deadline.after_ms(1000, clock=lambda: 10.0)
        self.request = TransitSearchRequest(
            Coordinate(127.10, 37.39), Coordinate(127.11, 37.40), self.now,
        )

    def test_officially_pinned_endpoints_are_exact_https_and_unpinned_are_none(self) -> None:
        urls = [spec.url for spec in ENDPOINT_SPECS if spec.url is not None]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(all(url.startswith("https://") and "?" not in url for url in urls))
        lookup = {(spec.provider, spec.operation): spec.url for spec in ENDPOINT_SPECS}
        self.assertEqual(lookup[("KAKAO_PUBLIC_TRANSIT", "search_current")], "https://dapi.kakao.com/v2/routing/publictraffic")
        self.assertEqual(lookup[("KAKAO_WALK", "route")], "https://dapi.kakao.com/v2/routing/walk")
        self.assertEqual(lookup[("KAKAO_DIRECTIONS", "route_current")], "https://apis-navi.kakaomobility.com/v1/directions")
        self.assertIsNone(lookup[("GITS", "traffic_context")])
        self.assertEqual(
            lookup[("GBIS_V2", "locations")],
            "https://apis.data.go.kr/6410000/buslocationservice/v2/getBusLocationListv2",
        )
        self.assertIsNone(lookup[("GBIS_V2", "stations")])
        verified = {
            (spec.provider, spec.operation): spec.response_schema_version
            for spec in ENDPOINT_SPECS
            if spec.response_schema_verified
        }
        self.assertEqual(
            verified,
            {
                (
                    "KAKAO_DIRECTIONS",
                    "route_current",
                ): "kakao-directions.v1.current-route.20260824",
                (
                    "KAKAO_PUBLIC_TRANSIT",
                    "search_current",
                ): "kakao.public-transit.rest.v2.2026-08-24",
                (
                    "KAKAO_WALK",
                    "route",
                ): "kakao.walk.rest.v2.2026-08-24",
                (
                    "GBIS_V2",
                    "arrivals",
                ): "gbis.bus-arrival.rest.v2.2026-08-25",
                (
                    "GBIS_V2",
                    "locations",
                ): "gbis.bus-location.rest.v2.2026-08-25",
            },
        )

    def test_all_named_operations_are_disabled_by_default_and_burn_zero_quota(self) -> None:
        suite = ProviderAdapterSuite(
            self.transport, telemetry=self.telemetry, clock=lambda: self.now,
        )
        outcomes = [
            suite.kakao_transit.search(self.request, deadline=self.deadline),
            suite.kakao_walk.route(self.request, deadline=self.deadline),
            suite.kakao_mobility.route(self.request, deadline=self.deadline),
            suite.kakao_mobility.many_destinations(self.request.origin, (self.request.destination,), deadline=self.deadline),
            suite.kakao_mobility.many_origins((self.request.origin,), self.request.destination, deadline=self.deadline),
            suite.kakao_mobility.future(self.request, deadline=self.deadline),
            suite.gbis.arrivals("sanitized-station", deadline=self.deadline),
            suite.gbis.locations("sanitized-route", deadline=self.deadline),
            suite.gbis.routes("SAN-100", deadline=self.deadline),
            suite.gbis.stations(self.request.origin, deadline=self.deadline),
            suite.kma.context(nx=62, ny=123, coordinate=self.request.origin, observed_at=self.now, deadline=self.deadline),
            suite.gits.context(self.request.origin, self.request.destination, observed_at=self.now, deadline=self.deadline),
            suite.tmap.search(self.request, deadline=self.deadline),
            suite.odsay.search(self.request, deadline=self.deadline),
        ]
        self.assertTrue(all(item.status is ProviderStatus.DISABLED for item in outcomes))
        self.assertTrue(all(item.latency_ms == 0 and not item.cache_hit for item in outcomes))
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(len(self.telemetry.events), len(outcomes))
        for event in self.telemetry.events:
            self.assertEqual(event.provider_call_count, 0)
            self.assertEqual(event.quota_units, 0)
            self.assertIsNone(event.estimated_cost_microunits)

    def test_provider_specific_fixture_matrix_preserves_all_outcomes(self) -> None:
        adapters = (
            (KakaoTransitAdapter(self.transport), ("search_current",)),
            (KakaoWalkAdapter(self.transport), ("route",)),
            (KakaoMobilityDirectionsAdapter(self.transport), ("route_current", "many_destinations", "many_origins", "route_future")),
            (GbisAdapter(self.transport), ("arrivals", "locations", "routes", "stations")),
            (KmaContextAdapter(self.transport), ("weather_context",)),
            (GitsTrafficAdapter(self.transport), ("traffic_context",)),
            (TmapTransitAdapter(self.transport), ("search",)),
            (OdsayTransitAdapter(self.transport), ("search",)),
        )
        expected = {
            ProviderFixtureScenario.SUCCESS: ProviderStatus.OK,
            ProviderFixtureScenario.EMPTY: ProviderStatus.OK,
            ProviderFixtureScenario.ERROR: ProviderStatus.UNAVAILABLE,
            ProviderFixtureScenario.RATE_LIMITED: ProviderStatus.RATE_LIMITED,
            ProviderFixtureScenario.SCHEMA_DRIFT: ProviderStatus.BAD_RESPONSE,
        }
        for adapter, operations in adapters:
            for operation in operations:
                for scenario, status in expected.items():
                    with self.subTest(provider=adapter.provider, operation=operation, scenario=scenario):
                        result = adapter.fixture(operation, scenario)
                        self.assertEqual(result.status, status)
                        self.assertIn(QualityFlag.SANITIZED_FIXTURE, result.quality_flags)
                        if scenario is ProviderFixtureScenario.EMPTY:
                            self.assertEqual(result.payload, ())
                            self.assertIn(QualityFlag.EMPTY_RESULT, result.quality_flags)
                        if scenario in {ProviderFixtureScenario.ERROR, ProviderFixtureScenario.RATE_LIMITED, ProviderFixtureScenario.SCHEMA_DRIFT}:
                            self.assertIsNone(result.payload)
        self.assertEqual(self.transport.calls, [])

    def test_non_route_fixtures_normalize_to_explicit_canonical_context_types(self) -> None:
        gbis = GbisAdapter(self.transport)
        self.assertIsInstance(gbis.fixture("arrivals", ProviderFixtureScenario.SUCCESS).payload[0], BusArrivalObservation)
        arrival = gbis.fixture("arrivals", ProviderFixtureScenario.SUCCESS).payload[0]
        self.assertIsNone(arrival.remaining_seats)
        location = gbis.fixture("locations", ProviderFixtureScenario.SUCCESS).payload[0]
        self.assertIsInstance(location, BusLocationObservation)
        self.assertIsNotNone(arrival.vehicle_token)
        self.assertEqual(arrival.vehicle_join_key, location.vehicle_join_key)
        self.assertIsInstance(gbis.fixture("routes", ProviderFixtureScenario.SUCCESS).payload[0], BusRouteRecord)
        self.assertIsInstance(gbis.fixture("stations", ProviderFixtureScenario.SUCCESS).payload[0], BusStationRecord)
        self.assertIsInstance(KmaContextAdapter(self.transport).fixture("weather_context", ProviderFixtureScenario.SUCCESS).payload[0], WeatherContext)
        self.assertIsInstance(GitsTrafficAdapter(self.transport).fixture("traffic_context", ProviderFixtureScenario.SUCCESS).payload[0], TrafficLinkContext)

    def test_credentials_are_injected_but_never_rendered(self) -> None:
        credential = SensitiveValue("fixture-secret-must-not-render")
        request = HttpRequest("GET", "https://api.example.invalid/path")
        injected = AuthInjection("header", "Authorization", "KakaoAK ").apply(request, credential)
        self.assertEqual(injected.safe_summary()["headers"]["Authorization"], "***")
        self.assertNotIn("fixture-secret-must-not-render", repr(injected))
        query_injected = AuthInjection("query", "serviceKey").apply(request, credential)
        self.assertEqual(query_injected.safe_summary()["query"]["serviceKey"], "***")

    def test_response_size_content_type_and_json_root_are_strict(self) -> None:
        with self.assertRaises(SchemaValidationError):
            HttpResponse(200, "text/html", b"{}").json_object(maximum_bytes=10)
        with self.assertRaises(SchemaValidationError):
            HttpResponse(200, "application/json", b"{}" * 10).json_object(maximum_bytes=2)
        with self.assertRaises(SchemaValidationError):
            HttpResponse(200, "application/json", b"[]").json_object(maximum_bytes=10)

    def test_input_bounds_and_closed_fixture_enum(self) -> None:
        mobility = KakaoMobilityDirectionsAdapter(self.transport)
        with self.assertRaises(InputValidationError):
            mobility.many_destinations(self.request.origin, (), deadline=self.deadline)
        with self.assertRaises(InputValidationError):
            KmaContextAdapter(self.transport).context(nx=0, ny=120, coordinate=self.request.origin, observed_at=self.now, deadline=self.deadline)
        with self.assertRaises(InputValidationError):
            GitsTrafficAdapter(self.transport).context(self.request.destination, self.request.origin, observed_at=self.now, deadline=self.deadline)
        with self.assertRaises(ValueError):
            ProviderFixtureScenario("../../caller-path")

    def test_named_fixture_files_contain_no_secret_or_raw_identity_fields(self) -> None:
        fixture_root = resources.files("provider_core").joinpath("fixtures")
        names = (
            "named_kakao_transit.json", "named_kakao_walk.json", "named_kakao_mobility.json",
            "named_gbis.json", "named_kma.json", "named_gits.json", "named_tmap.json", "named_odsay.json",
        )
        for name in names:
            text = fixture_root.joinpath(name).read_text(encoding="utf-8")
            for forbidden in ("apiKey\"", "serviceKey\"", "Authorization\"", "plateNumber", "email", "phone"):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
