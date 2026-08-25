from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

EARTH_RADIUS_METERS = 6_371_008.8
SEARCH_RADIUS_METERS = 5_000
MAX_NEARBY_STATIONS = 5
ASSUMED_SPEED_KPH = 15

DATA_FILE = Path(__file__).resolve().parent / "data" / "stations.json"


@dataclass(frozen=True)
class Coordinate:
    lon: float
    lat: float


@dataclass(frozen=True)
class BikeStation:
    station_id: str
    name: str
    district: str
    address: str | None
    coordinate: Coordinate
    rack_count: int | None


@dataclass(frozen=True)
class BikeDataSource:
    name: str
    url: str
    license: str
    published_at: str


@dataclass(frozen=True)
class BikeCatalog:
    station_data_month: str
    source: BikeDataSource
    stations: tuple[BikeStation, ...]


@dataclass(frozen=True)
class NearbyStation:
    station: BikeStation
    distance_meters: int


def haversine_distance_meters(start: Coordinate, end: Coordinate) -> float:
    """Return WGS84-coordinate great-circle distance in metres."""

    start_lat = math.radians(start.lat)
    end_lat = math.radians(end.lat)
    latitude_delta = end_lat - start_lat
    longitude_delta = math.radians(end.lon - start.lon)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(start_lat) * math.cos(end_lat) * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(haversine))


def rounded_distance_meters(start: Coordinate, end: Coordinate) -> int:
    return int(round(haversine_distance_meters(start, end)))


def cycling_duration_seconds(distance_meters: int) -> int:
    return math.ceil(distance_meters * 3_600 / (ASSUMED_SPEED_KPH * 1_000))


def nearest_stations(
    stations: tuple[BikeStation, ...],
    point: Coordinate,
    *,
    radius_meters: int = SEARCH_RADIUS_METERS,
    limit: int = MAX_NEARBY_STATIONS,
) -> list[NearbyStation]:
    candidates: list[NearbyStation] = []
    for station in stations:
        exact_distance = haversine_distance_meters(point, station.coordinate)
        if exact_distance <= radius_meters:
            candidates.append(
                NearbyStation(station=station, distance_meters=int(round(exact_distance)))
            )
    candidates.sort(key=lambda candidate: (candidate.distance_meters, candidate.station.station_id))
    return candidates[:limit]


def build_bike_options(
    catalog: BikeCatalog,
    origin: Coordinate,
    destination: Coordinate,
) -> dict[str, Any]:
    pickup_stations = nearest_stations(catalog.stations, origin)
    return_stations = nearest_stations(catalog.stations, destination)

    ride_estimate: dict[str, Any] | None = None
    if pickup_stations:
        pickup = pickup_stations[0].station
        selected_return = next(
            (
                nearby.station
                for nearby in return_stations
                if nearby.station.station_id != pickup.station_id
            ),
            None,
        )
        if selected_return is not None:
            distance_meters = rounded_distance_meters(
                pickup.coordinate,
                selected_return.coordinate,
            )
            ride_estimate = {
                "pickupStationId": pickup.station_id,
                "returnStationId": selected_return.station_id,
                "distanceMeters": distance_meters,
                "durationSeconds": cycling_duration_seconds(distance_meters),
                "assumedSpeedKph": ASSUMED_SPEED_KPH,
                "distanceMethod": "STRAIGHT_LINE",
            }

    return {
        "pickupStations": [_station_option(item) for item in pickup_stations],
        "returnStations": [_station_option(item) for item in return_stations],
        "rideEstimate": ride_estimate,
        "searchRadiusMeters": SEARCH_RADIUS_METERS,
        "stationDataMonth": catalog.station_data_month,
        "availabilityStatus": "NOT_PROVIDED",
        "dataSource": {
            "name": catalog.source.name,
            "url": catalog.source.url,
            "license": catalog.source.license,
            "publishedAt": catalog.source.published_at,
        },
    }


def _station_option(nearby: NearbyStation) -> dict[str, Any]:
    station = nearby.station
    return {
        "stationId": station.station_id,
        "name": station.name,
        "district": station.district,
        "address": station.address,
        "coordinate": {
            "lon": station.coordinate.lon,
            "lat": station.coordinate.lat,
        },
        "rackCount": station.rack_count,
        "distanceFromPointMeters": nearby.distance_meters,
    }


@lru_cache(maxsize=1)
def get_catalog() -> BikeCatalog:
    return load_catalog(DATA_FILE)


def load_catalog(path: Path) -> BikeCatalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    source = raw["source"]
    stations = tuple(_load_station(item) for item in raw["stations"])
    if len({station.station_id for station in stations}) != len(stations):
        raise ValueError("Seoul Bike station IDs must be unique")
    return BikeCatalog(
        station_data_month=str(raw["stationDataMonth"]),
        source=BikeDataSource(
            name=str(source["name"]),
            url=str(source["url"]),
            license=str(source["license"]),
            published_at=str(source["publishedAt"]),
        ),
        stations=stations,
    )


def _load_station(raw: dict[str, Any]) -> BikeStation:
    coordinate = raw["coordinate"]
    rack_count = raw["rackCount"]
    return BikeStation(
        station_id=str(raw["stationId"]),
        name=str(raw["name"]),
        district=str(raw["district"]),
        address=None if raw["address"] is None else str(raw["address"]),
        coordinate=Coordinate(lon=float(coordinate["lon"]), lat=float(coordinate["lat"])),
        rack_count=None if rack_count is None else int(rack_count),
    )
