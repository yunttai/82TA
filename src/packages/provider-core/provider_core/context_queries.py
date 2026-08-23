"""Bounded, versioned request identities for optional Provider context.

These values contain only provider-neutral coordinates, timestamps, and opaque link
identifiers.  They deliberately do not assert that KMA or GITS is executable; the
independent capability/runtime gates remain authoritative.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .canonical import Coordinate, require_aware


KMA_GRID_CONVERSION_VERSION = "kma-dfs-grid.v1"
KMA_WEATHER_QUERY_VERSION = "kma-weather-context-query.v1"
GITS_TRAFFIC_QUERY_VERSION = "gits-traffic-corridor-query.v1"

MAX_TRAFFIC_CORRIDOR_POINTS = 64
MAX_TRAFFIC_CORRIDOR_SPAN_METERS = 120_000
MAX_TRAFFIC_PADDING_METERS = 5_000
MAX_TRAFFIC_LINKS = 2_048


def _instant(value: datetime) -> str:
    require_aware(value, "context observed_at")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _coordinate_value(value: Coordinate) -> dict[str, float]:
    return {"lat": value.lat, "lon": value.lon}


@dataclass(frozen=True, slots=True)
class KmaGrid:
    """KMA DFS grid cell derived from WGS84 using the published 5 km projection."""

    nx: int
    ny: int
    conversion_version: str = field(
        default=KMA_GRID_CONVERSION_VERSION, init=False
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.nx, int)
            or isinstance(self.nx, bool)
            or not 1 <= self.nx <= 149
            or not isinstance(self.ny, int)
            or isinstance(self.ny, bool)
            or not 1 <= self.ny <= 253
        ):
            raise ValueError("KMA grid is outside documented bounds")

    @classmethod
    def from_coordinate(cls, coordinate: Coordinate) -> "KmaGrid":
        # KMA DFS Lambert conformal conic constants.  Keeping the constants and
        # version together makes any future projection change an explicit identity
        # migration rather than a silent cache-key change.
        earth_radius_over_grid = 6371.00877 / 5.0
        standard_latitude_1 = math.radians(30.0)
        standard_latitude_2 = math.radians(60.0)
        origin_longitude = math.radians(126.0)
        origin_latitude = math.radians(38.0)
        origin_x = 43.0
        origin_y = 136.0

        cone = math.log(
            math.cos(standard_latitude_1) / math.cos(standard_latitude_2)
        ) / math.log(
            math.tan(math.pi * 0.25 + standard_latitude_2 * 0.5)
            / math.tan(math.pi * 0.25 + standard_latitude_1 * 0.5)
        )
        scale = (
            math.tan(math.pi * 0.25 + standard_latitude_1 * 0.5) ** cone
            * math.cos(standard_latitude_1)
            / cone
        )
        origin_radius = earth_radius_over_grid * scale / (
            math.tan(math.pi * 0.25 + origin_latitude * 0.5) ** cone
        )
        latitude = math.radians(coordinate.lat)
        radius = earth_radius_over_grid * scale / (
            math.tan(math.pi * 0.25 + latitude * 0.5) ** cone
        )
        theta = (math.radians(coordinate.lon) - origin_longitude) * cone
        return cls(
            nx=math.floor(radius * math.sin(theta) + origin_x + 0.5),
            ny=math.floor(origin_radius - radius * math.cos(theta) + origin_y + 0.5),
        )


@dataclass(frozen=True, slots=True)
class KmaWeatherQuery:
    """One exact as-of weather query bound to its derived KMA grid cell."""

    coordinate: Coordinate
    observed_at: datetime
    grid: KmaGrid
    identity_version: str = field(default=KMA_WEATHER_QUERY_VERSION, init=False)

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "weather query observed_at")
        if self.grid != KmaGrid.from_coordinate(self.coordinate):
            raise ValueError("KMA grid does not match the WGS84 coordinate")

    @classmethod
    def from_coordinate(
        cls, coordinate: Coordinate, observed_at: datetime
    ) -> "KmaWeatherQuery":
        return cls(coordinate, observed_at, KmaGrid.from_coordinate(coordinate))

    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "coordinate": _coordinate_value(self.coordinate),
                "grid": {
                    "conversionVersion": self.grid.conversion_version,
                    "nx": self.grid.nx,
                    "ny": self.grid.ny,
                },
                "identityVersion": self.identity_version,
                "observedAt": _instant(self.observed_at),
            }
        )

    @property
    def provider_query(self) -> tuple[tuple[str, str | int], ...]:
        return (
            ("nx", self.grid.nx),
            ("ny", self.grid.ny),
            ("dataType", "JSON"),
        )


def _distance_meters(left: Coordinate, right: Coordinate) -> float:
    radius_meters = 6_371_008.8
    left_lat = math.radians(left.lat)
    right_lat = math.radians(right.lat)
    delta_lat = right_lat - left_lat
    delta_lon = math.radians(right.lon - left.lon)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(left_lat) * math.cos(right_lat) * math.sin(delta_lon / 2.0) ** 2
    )
    return radius_meters * 2.0 * math.asin(min(1.0, math.sqrt(haversine)))


@dataclass(frozen=True, slots=True)
class TrafficBoundingBox:
    minimum: Coordinate
    maximum: Coordinate

    def __post_init__(self) -> None:
        if self.minimum.lon > self.maximum.lon or self.minimum.lat > self.maximum.lat:
            raise ValueError("traffic bounding box is reversed")
        if _distance_meters(self.minimum, self.maximum) > MAX_TRAFFIC_CORRIDOR_SPAN_METERS:
            raise ValueError("traffic bounding box exceeds the corridor span bound")


def _link_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if any(not isinstance(value, str) for value in values):
        raise ValueError("traffic link identifier must be a string")
    normalized = tuple(sorted(set(values)))
    if len(normalized) != len(values):
        raise ValueError("traffic link identifiers must be unique")
    if len(normalized) > MAX_TRAFFIC_LINKS:
        raise ValueError("traffic link identifier count exceeds the response bound")
    for value in normalized:
        if (
            not value
            or len(value) > 128
            or value != value.strip()
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("traffic link identifier is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class GitsTrafficCorridorQuery:
    """A bounded GITS bbox tied to the exact canonical BUS corridor identity."""

    corridor: tuple[Coordinate, ...]
    observed_at: datetime
    bounding_box: TrafficBoundingBox
    relevant_link_external_ids: tuple[str, ...] = ()
    maximum_links: int = 512
    padding_meters: int = 0
    identity_version: str = field(default=GITS_TRAFFIC_QUERY_VERSION, init=False)

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "traffic query observed_at")
        if not 2 <= len(self.corridor) <= MAX_TRAFFIC_CORRIDOR_POINTS:
            raise ValueError("traffic corridor must contain two to sixty-four points")
        if any(
            not (
                self.bounding_box.minimum.lon <= point.lon <= self.bounding_box.maximum.lon
                and self.bounding_box.minimum.lat <= point.lat <= self.bounding_box.maximum.lat
            )
            for point in self.corridor
        ):
            raise ValueError("traffic corridor point is outside its bounding box")
        if (
            not isinstance(self.padding_meters, int)
            or isinstance(self.padding_meters, bool)
            or not 0 <= self.padding_meters <= MAX_TRAFFIC_PADDING_METERS
        ):
            raise ValueError("traffic padding is outside the bounded range")
        if (
            not isinstance(self.maximum_links, int)
            or isinstance(self.maximum_links, bool)
            or not 1 <= self.maximum_links <= MAX_TRAFFIC_LINKS
        ):
            raise ValueError("maximum_links is outside the bounded range")
        object.__setattr__(
            self,
            "relevant_link_external_ids",
            _link_ids(tuple(self.relevant_link_external_ids)),
        )

    @classmethod
    def from_corridor(
        cls,
        corridor: tuple[Coordinate, ...],
        observed_at: datetime,
        *,
        relevant_link_external_ids: tuple[str, ...] = (),
        maximum_links: int = 512,
        padding_meters: int = 0,
    ) -> "GitsTrafficCorridorQuery":
        if not 2 <= len(corridor) <= MAX_TRAFFIC_CORRIDOR_POINTS:
            raise ValueError("traffic corridor must contain two to sixty-four points")
        if (
            not isinstance(padding_meters, int)
            or isinstance(padding_meters, bool)
            or not 0 <= padding_meters <= MAX_TRAFFIC_PADDING_METERS
        ):
            raise ValueError("traffic padding is outside the bounded range")
        minimum_lat = min(point.lat for point in corridor)
        maximum_lat = max(point.lat for point in corridor)
        middle_latitude = math.radians((minimum_lat + maximum_lat) / 2.0)
        latitude_padding = padding_meters / 111_320.0
        longitude_padding = padding_meters / (
            111_320.0 * max(0.1, math.cos(middle_latitude))
        )
        bounding_box = TrafficBoundingBox(
            Coordinate(
                min(point.lon for point in corridor) - longitude_padding,
                minimum_lat - latitude_padding,
            ),
            Coordinate(
                max(point.lon for point in corridor) + longitude_padding,
                maximum_lat + latitude_padding,
            ),
        )
        return cls(
            corridor=tuple(corridor),
            observed_at=observed_at,
            bounding_box=bounding_box,
            relevant_link_external_ids=relevant_link_external_ids,
            maximum_links=maximum_links,
            padding_meters=padding_meters,
        )

    @classmethod
    def from_bounds(
        cls,
        minimum: Coordinate,
        maximum: Coordinate,
        observed_at: datetime,
        *,
        maximum_links: int = 512,
    ) -> "GitsTrafficCorridorQuery":
        return cls(
            corridor=(minimum, maximum),
            observed_at=observed_at,
            bounding_box=TrafficBoundingBox(minimum, maximum),
            maximum_links=maximum_links,
        )

    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "boundingBox": {
                    "maximum": _coordinate_value(self.bounding_box.maximum),
                    "minimum": _coordinate_value(self.bounding_box.minimum),
                },
                "corridor": [_coordinate_value(point) for point in self.corridor],
                "identityVersion": self.identity_version,
                "maximumLinks": self.maximum_links,
                "observedAt": _instant(self.observed_at),
                "paddingMeters": self.padding_meters,
                "relevantLinkExternalIds": list(self.relevant_link_external_ids),
            }
        )

    @property
    def provider_query(self) -> tuple[tuple[str, str | float], ...]:
        return (
            ("minX", self.bounding_box.minimum.lon),
            ("minY", self.bounding_box.minimum.lat),
            ("maxX", self.bounding_box.maximum.lon),
            ("maxY", self.bounding_box.maximum.lat),
            ("getType", "json"),
        )

    def accepts_link(self, external_id: str) -> bool:
        return (
            not self.relevant_link_external_ids
            or external_id in self.relevant_link_external_ids
        )


__all__ = [
    "GITS_TRAFFIC_QUERY_VERSION",
    "GitsTrafficCorridorQuery",
    "KMA_GRID_CONVERSION_VERSION",
    "KMA_WEATHER_QUERY_VERSION",
    "KmaGrid",
    "KmaWeatherQuery",
    "MAX_TRAFFIC_CORRIDOR_POINTS",
    "MAX_TRAFFIC_CORRIDOR_SPAN_METERS",
    "MAX_TRAFFIC_LINKS",
    "MAX_TRAFFIC_PADDING_METERS",
    "TrafficBoundingBox",
]
