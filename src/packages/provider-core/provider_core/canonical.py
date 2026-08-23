"""Immutable provider-neutral transport values.

Only normalized values belong here. Provider response dictionaries, response field
names, credentials, and URLs must not cross this module boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TravelMode(StrEnum):
    WALK = "WALK"
    WAIT = "WAIT"
    TRANSFER = "TRANSFER"
    TAXI = "TAXI"
    BUS = "BUS"
    SUBWAY = "SUBWAY"
    GTX = "GTX"
    TRAIN = "TRAIN"


class DataOrigin(StrEnum):
    OBSERVED = "OBSERVED"
    PROVIDER_ESTIMATE = "PROVIDER_ESTIMATE"
    MODEL_PREDICTED = "MODEL_PREDICTED"
    HISTORICAL_PROXY = "HISTORICAL_PROXY"
    USER_INPUT = "USER_INPUT"
    UNKNOWN = "UNKNOWN"


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True, slots=True)
class Coordinate:
    lon: float
    lat: float

    def __post_init__(self) -> None:
        if not 124.0 <= self.lon <= 132.0:
            raise ValueError("lon must be within the canonical Korea bounds")
        if not 33.0 <= self.lat <= 39.5:
            raise ValueError("lat must be within the canonical Korea bounds")


@dataclass(frozen=True, slots=True)
class CanonicalStop:
    name: str
    coordinate: Coordinate
    external_id: str | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "stop name")
        if self.external_id is not None:
            _require_text(self.external_id, "external stop id")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("stop sequence must be non-negative")


@dataclass(frozen=True, slots=True)
class TimeEstimate:
    p50_seconds: int
    p90_seconds: int
    origin: DataOrigin
    lower_seconds: int | None = None
    upper_seconds: int | None = None

    def __post_init__(self) -> None:
        values = (self.p50_seconds, self.p90_seconds, self.lower_seconds, self.upper_seconds)
        if any(value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0) for value in values):
            raise ValueError("time estimates must be non-negative integer seconds")
        if self.p90_seconds < self.p50_seconds:
            raise ValueError("p90_seconds must be greater than or equal to p50_seconds")
        if self.lower_seconds is not None and self.lower_seconds > self.p50_seconds:
            raise ValueError("lower_seconds cannot exceed p50_seconds")
        if self.upper_seconds is not None and self.upper_seconds < self.p90_seconds:
            raise ValueError("upper_seconds cannot be below p90_seconds")


@dataclass(frozen=True, slots=True)
class MoneyRange:
    expected_krw: int
    lower_krw: int
    upper_krw: int
    origin: DataOrigin

    def __post_init__(self) -> None:
        values = (self.expected_krw, self.lower_krw, self.upper_krw)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("money values must be non-negative integer KRW")
        if not self.lower_krw <= self.expected_krw <= self.upper_krw:
            raise ValueError("money range must satisfy lower <= expected <= upper")


@dataclass(frozen=True, slots=True)
class TransitDescriptor:
    """Optional provider evidence used by entity mapping.

    Absence is meaningful. Callers must not invent route type, direction, sequence,
    branch, terminal, geometry, or live-vehicle evidence.
    """

    route_label: str | None = None
    external_route_id: str | None = None
    route_type: str | None = None
    direction: str | None = None
    branch_id: str | None = None
    boarding_sequence: int | None = None
    alighting_sequence: int | None = None
    terminal_names: tuple[str, ...] = ()
    live_vehicle_observed: bool | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.route_label, "route_label"),
            (self.external_route_id, "external_route_id"),
            (self.route_type, "route_type"),
            (self.direction, "direction"),
            (self.branch_id, "branch_id"),
        ):
            if value is not None:
                _require_text(value, name)
        for value in (self.boarding_sequence, self.alighting_sequence):
            if value is not None and value < 0:
                raise ValueError("transit stop sequence must be non-negative")
        if (
            self.boarding_sequence is not None
            and self.alighting_sequence is not None
            and self.alighting_sequence <= self.boarding_sequence
        ):
            raise ValueError("alighting sequence must follow boarding sequence")
        if any(not name.strip() for name in self.terminal_names):
            raise ValueError("terminal names must be non-empty")


@dataclass(frozen=True, slots=True)
class CanonicalLeg:
    leg_id: str
    sequence: int
    mode: TravelMode
    from_stop: CanonicalStop
    to_stop: CanonicalStop
    duration: TimeEstimate
    distance_meters: int
    fare: MoneyRange
    expected_start_at: datetime | None = None
    expected_end_at: datetime | None = None
    transit: TransitDescriptor | None = None
    geometry: tuple[Coordinate, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.leg_id, "leg_id")
        if self.sequence < 0:
            raise ValueError("leg sequence must be non-negative")
        if not isinstance(self.distance_meters, int) or isinstance(self.distance_meters, bool) or self.distance_meters < 0:
            raise ValueError("distance_meters must be a non-negative integer")
        if self.expected_start_at is not None:
            require_aware(self.expected_start_at, "expected_start_at")
        if self.expected_end_at is not None:
            require_aware(self.expected_end_at, "expected_end_at")
        if self.expected_start_at is not None and self.expected_end_at is not None:
            if self.expected_end_at < self.expected_start_at:
                raise ValueError("expected_end_at cannot precede expected_start_at")
        if self.mode in {TravelMode.BUS, TravelMode.SUBWAY, TravelMode.GTX, TravelMode.TRAIN}:
            if self.transit is None:
                raise ValueError("transit modes require a TransitDescriptor")
        elif self.transit is not None:
            raise ValueError("non-transit modes cannot carry a TransitDescriptor")


@dataclass(frozen=True, slots=True)
class CanonicalItinerary:
    itinerary_id: str
    legs: tuple[CanonicalLeg, ...]

    def __post_init__(self) -> None:
        _require_text(self.itinerary_id, "itinerary_id")
        if not self.legs:
            raise ValueError("itinerary must contain at least one leg")
        expected_sequences = tuple(range(len(self.legs)))
        if tuple(leg.sequence for leg in self.legs) != expected_sequences:
            raise ValueError("leg sequences must be contiguous and start at zero")
        for previous, current in zip(self.legs, self.legs[1:]):
            if previous.to_stop.coordinate != current.from_stop.coordinate:
                raise ValueError("adjacent legs must connect at the same coordinate")
            if previous.expected_end_at is not None and current.expected_start_at is not None:
                if current.expected_start_at < previous.expected_end_at:
                    raise ValueError("itinerary legs must be chronological")
