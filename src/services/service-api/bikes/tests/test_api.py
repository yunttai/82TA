from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from bikes.catalog import (
    BikeCatalog,
    BikeDataSource,
    BikeStation,
    Coordinate,
    build_bike_options,
    cycling_duration_seconds,
    haversine_distance_meters,
    nearest_stations,
)
from journeys.abuse import reset_rate_limits


SOURCE = BikeDataSource(
    name="서울특별시 공공자전거 대여소 정보",
    url="https://data.seoul.go.kr/dataList/OA-13252/F/1/datasetView.do",
    license="공공누리 제1유형",
    published_at="2026-07-15",
)


def station(station_id: str, lon: float, lat: float) -> BikeStation:
    return BikeStation(
        station_id=station_id,
        name=f"Station {station_id}",
        district="테스트구",
        address=None,
        coordinate=Coordinate(lon=lon, lat=lat),
        rack_count=None,
    )


class BikeDomainTests(SimpleTestCase):
    def test_same_nearest_station_uses_next_distinct_return_station(self) -> None:
        catalog = BikeCatalog(
            station_data_month="2026-06",
            source=SOURCE,
            stations=(
                station("A", 127.0, 37.0),
                station("B", 127.0005, 37.0),
            ),
        )

        result = build_bike_options(
            catalog,
            Coordinate(lon=127.0, lat=37.0),
            Coordinate(lon=127.0, lat=37.0),
        )

        self.assertEqual(result["pickupStations"][0]["stationId"], "A")
        self.assertEqual(result["returnStations"][0]["stationId"], "A")
        self.assertEqual(result["rideEstimate"]["pickupStationId"], "A")
        self.assertEqual(result["rideEstimate"]["returnStationId"], "B")

    def test_distance_sorting_and_time_calculation_are_deterministic(self) -> None:
        tied_stations = (
            station("20", 127.0, 37.0),
            station("100", 127.0, 37.0),
        )
        ordered = nearest_stations(tied_stations, Coordinate(lon=127.0, lat=37.0))
        self.assertEqual([item.station.station_id for item in ordered], ["100", "20"])

        distance_meters = round(
            haversine_distance_meters(
                Coordinate(lon=127.0, lat=37.0),
                Coordinate(lon=127.0, lat=38.0),
            )
        )
        self.assertEqual(distance_meters, 111_195)
        self.assertEqual(cycling_duration_seconds(distance_meters), 26_687)

    def test_estimate_is_null_when_only_same_station_is_available(self) -> None:
        catalog = BikeCatalog(
            station_data_month="2026-06",
            source=SOURCE,
            stations=(station("A", 127.0, 37.0),),
        )
        result = build_bike_options(
            catalog,
            Coordinate(lon=127.0, lat=37.0),
            Coordinate(lon=127.0, lat=37.0),
        )
        self.assertIsNone(result["rideEstimate"])


class BikeApiTests(SimpleTestCase):
    def setUp(self) -> None:
        reset_rate_limits()

    def test_returns_official_station_snapshot_and_estimate(self) -> None:
        response = self.client.get(
            "/api/v1/bike-options",
            {
                "originLon": "126.91062927",
                "originLat": "37.5556488",
                "destinationLon": "126.91498566",
                "destinationLat": "37.55062866",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pickupStations"][0]["stationId"], "102")
        self.assertEqual(body["returnStations"][0]["stationId"], "104")
        self.assertEqual(body["rideEstimate"]["pickupStationId"], "102")
        self.assertEqual(body["rideEstimate"]["returnStationId"], "104")
        self.assertEqual(body["rideEstimate"]["assumedSpeedKph"], 15)
        self.assertEqual(body["rideEstimate"]["distanceMethod"], "STRAIGHT_LINE")
        self.assertEqual(body["searchRadiusMeters"], 5_000)
        self.assertEqual(body["stationDataMonth"], "2026-06")
        self.assertEqual(body["availabilityStatus"], "NOT_PROVIDED")
        self.assertEqual(body["dataSource"]["publishedAt"], "2026-07-15")
        self.assertNotIn("availableBikeCount", body["pickupStations"][0])
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_rejects_missing_non_finite_and_out_of_range_coordinates(self) -> None:
        base = {
            "originLon": "126.91",
            "originLat": "37.55",
            "destinationLon": "126.92",
            "destinationLat": "37.56",
        }
        for name, value in (("originLon", None), ("originLat", "nan"), ("destinationLon", "133")):
            query = {key: item for key, item in base.items() if key != name}
            if value is not None:
                query[name] = value
            with self.subTest(name=name, value=value):
                response = self.client.get("/api/v1/bike-options", query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "INVALID_COORDINATE")

    def test_coordinates_outside_station_coverage_return_empty_options(self) -> None:
        response = self.client.get(
            "/api/v1/bike-options",
            {
                "originLon": "126.5",
                "originLat": "33.5",
                "destinationLon": "126.5",
                "destinationLat": "33.5",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pickupStations"], [])
        self.assertEqual(response.json()["returnStations"], [])
        self.assertIsNone(response.json()["rideEstimate"])

    @override_settings(PUBLIC_RATE_LIMIT_PER_MINUTE=1)
    def test_rate_limit_uses_problem_response(self) -> None:
        query = {
            "originLon": "126.91",
            "originLat": "37.55",
            "destinationLon": "126.92",
            "destinationLat": "37.56",
        }
        self.assertEqual(self.client.get("/api/v1/bike-options", query).status_code, 200)
        limited = self.client.get("/api/v1/bike-options", query)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["code"], "RATE_LIMITED")
        self.assertEqual(limited["Cache-Control"], "no-store")
