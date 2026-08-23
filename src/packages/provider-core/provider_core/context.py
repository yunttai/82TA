"""Immutable normalized values for non-itinerary provider operations."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from dataclasses import dataclass
from datetime import datetime

from .canonical import Coordinate, require_aware


def _text(value: str, name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} must be non-empty")


_OPAQUE_VEHICLE_TOKEN = re.compile(r"veh_[0-9a-f]{64}\Z")


def _vehicle_token(value: str | None) -> None:
    if value is not None and not _OPAQUE_VEHICLE_TOKEN.fullmatch(value):
        raise ValueError("vehicle_token must be an opaque provider-scoped token")


@dataclass(frozen=True, slots=True, repr=False)
class OpaqueVehicleTokenIssuer:
    """Issues a stable provider-scoped HMAC token without retaining a raw ID."""

    _key: bytes

    def __post_init__(self) -> None:
        if len(self._key) < 32:
            raise ValueError("vehicle tokenization key must contain at least 32 bytes")

    def __repr__(self) -> str:
        return "OpaqueVehicleTokenIssuer(***)"

    def issue(self, provider: str, raw_identifier: str) -> str:
        _text(provider, "provider")
        if (
            not raw_identifier
            or len(raw_identifier) > 256
            or any(ord(char) < 32 for char in raw_identifier)
        ):
            raise ValueError("raw vehicle identifier is invalid")
        digest = hmac.new(
            self._key,
            f"{provider}\x00{raw_identifier}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return "veh_" + digest


@dataclass(frozen=True, slots=True)
class BusArrivalObservation:
    route_external_id: str
    station_external_id: str
    eta_seconds: int
    remaining_seats: int | None
    observed_at: datetime
    vehicle_token: str | None = None

    def __post_init__(self) -> None:
        _text(self.route_external_id, "route_external_id")
        _text(self.station_external_id, "station_external_id")
        if self.eta_seconds < 0 or (self.remaining_seats is not None and self.remaining_seats < 0):
            raise ValueError("arrival values cannot be negative")
        require_aware(self.observed_at, "observed_at")
        _vehicle_token(self.vehicle_token)

    @property
    def vehicle_join_key(self) -> tuple[str, str] | None:
        if self.vehicle_token is None:
            return None
        return self.route_external_id, self.vehicle_token


@dataclass(frozen=True, slots=True)
class BusLocationObservation:
    route_external_id: str
    vehicle_token: str
    stop_sequence: int
    coordinate: Coordinate
    observed_at: datetime

    def __post_init__(self) -> None:
        _text(self.route_external_id, "route_external_id")
        _text(self.vehicle_token, "vehicle_token")
        if self.stop_sequence < 0:
            raise ValueError("stop_sequence cannot be negative")
        require_aware(self.observed_at, "observed_at")
        _vehicle_token(self.vehicle_token)

    @property
    def vehicle_join_key(self) -> tuple[str, str]:
        return self.route_external_id, self.vehicle_token


@dataclass(frozen=True, slots=True)
class BusRouteRecord:
    external_id: str
    name: str
    route_type: str | None

    def __post_init__(self) -> None:
        _text(self.external_id, "external_id")
        _text(self.name, "name")


@dataclass(frozen=True, slots=True)
class BusStationRecord:
    external_id: str
    name: str
    coordinate: Coordinate

    def __post_init__(self) -> None:
        _text(self.external_id, "external_id")
        _text(self.name, "name")


@dataclass(frozen=True, slots=True)
class WeatherContext:
    coordinate: Coordinate
    observed_at: datetime
    temperature_c: float | None
    precipitation_mm: float | None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        for value, name in (
            (self.temperature_c, "temperature_c"),
            (self.precipitation_mm, "precipitation_mm"),
        ):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite when observed")
        if self.temperature_c is None and self.precipitation_mm is None:
            raise ValueError("weather context requires at least one observed value")
        if self.precipitation_mm is not None and self.precipitation_mm < 0:
            raise ValueError("precipitation cannot be negative")


@dataclass(frozen=True, slots=True)
class TrafficLinkContext:
    link_external_id: str
    speed_kph: int
    travel_time_seconds: float
    observed_at: datetime

    def __post_init__(self) -> None:
        _text(self.link_external_id, "link_external_id")
        if (
            not isinstance(self.speed_kph, int)
            or isinstance(self.speed_kph, bool)
            or self.speed_kph < 0
        ):
            raise ValueError("speed_kph must be a non-negative integer")
        if (
            isinstance(self.travel_time_seconds, bool)
            or not isinstance(self.travel_time_seconds, (int, float))
            or not math.isfinite(self.travel_time_seconds)
            or self.travel_time_seconds < 0
        ):
            raise ValueError(
                "travel_time_seconds must be finite and non-negative"
            )
        require_aware(self.observed_at, "observed_at")
