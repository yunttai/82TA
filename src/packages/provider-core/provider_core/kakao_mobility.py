"""Strict Kakao Mobility current Directions v1 response normalization.

Only the documented ``GET /v1/directions`` response shape belongs here.  The raw
Provider object is validated and discarded; callers receive provider-neutral
``CanonicalItinerary`` values.  This module performs no HTTP, credential, capability,
or approval work, so using the normalizer cannot promote a live operation.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Mapping

from .canonical import (
    CanonicalItinerary,
    CanonicalLeg,
    CanonicalStop,
    Coordinate,
    DataOrigin,
    MoneyRange,
    TimeEstimate,
    TravelMode,
)
from .validation import SchemaValidationError


KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION = (
    "kakao-directions.v1.current-route.20260824"
)

_TRANS_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_SUCCESS_RESULT_CODE = 0
_DOCUMENTED_RESULT_CODES = frozenset({0, 1, 101, 102, 103, 104, 105, 106, 107})
_PRIORITIES = frozenset(
    {"RECOMMEND", "TIME", "DISTANCE", "MAIN_ROAD", "NO_TRAFFIC_INFO"}
)
_TRAFFIC_STATES = frozenset({0, 1, 2, 3, 4, 6})
_MAX_ROADS = 20_000
_MAX_GUIDES = 20_000
_MAX_VERTEX_VALUES = 200_000
_MAX_DISTANCE_METERS = 1_500_000
_MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
_MAX_FARE_KRW = 10_000_000


def normalize_current_directions(body: Any) -> tuple[CanonicalItinerary, ...]:
    """Validate and normalize one non-alternative current Directions response.

    Known Kakao route-result failures are a valid empty result.  Unknown result codes,
    unknown fields, missing fields, invalid units, inconsistent section totals, and
    malformed geometry are schema failures.  Provider messages and transaction IDs
    never cross the adapter boundary; only a hash-derived itinerary identifier does.
    """

    root = _require_exact(body, {"trans_id", "routes"}, "Kakao Directions response")
    trans_id = _identifier(root["trans_id"], "Kakao Directions trans_id")
    routes = root["routes"]
    if not isinstance(routes, list):
        raise SchemaValidationError("Kakao Directions routes must be an array")
    if len(routes) > 1:
        raise SchemaValidationError(
            "Kakao Directions returned alternatives when alternatives=false"
        )
    if not routes:
        return ()

    route = _require_allowed(
        routes[0],
        {"result_code", "result_msg"},
        {"summary", "sections"},
        "Kakao Directions route",
    )
    result_code = _integer(route["result_code"], "result_code", minimum=0)
    if result_code not in _DOCUMENTED_RESULT_CODES:
        raise SchemaValidationError("Kakao Directions result_code is undocumented")
    _text(route["result_msg"], "result_msg", maximum_length=500, allow_empty=False)
    if result_code != _SUCCESS_RESULT_CODE:
        return ()
    if set(route) != {"result_code", "result_msg", "summary", "sections"}:
        raise SchemaValidationError("Kakao Directions success route schema mismatch")

    summary = _require_exact(
        route["summary"],
        {
            "origin",
            "destination",
            "waypoints",
            "priority",
            "bound",
            "fare",
            "distance",
            "duration",
        },
        "Kakao Directions summary",
    )
    origin = _point(summary["origin"], "Kakao Directions summary origin")
    destination = _point(
        summary["destination"], "Kakao Directions summary destination"
    )
    if not isinstance(summary["waypoints"], list) or summary["waypoints"]:
        raise SchemaValidationError(
            "Kakao Directions current route must not contain unrequested waypoints"
        )
    priority = summary["priority"]
    if priority != "TIME" or priority not in _PRIORITIES:
        raise SchemaValidationError(
            "Kakao Directions response priority does not match TIME request"
        )
    _bound(summary["bound"], "Kakao Directions summary bound")

    fare = _require_exact(summary["fare"], {"taxi", "toll"}, "Kakao Directions fare")
    taxi_fare = _integer(
        fare["taxi"], "Kakao Directions taxi fare", minimum=0, maximum=_MAX_FARE_KRW
    )
    toll_fare = _integer(
        fare["toll"], "Kakao Directions toll fare", minimum=0, maximum=_MAX_FARE_KRW
    )
    total_fare = taxi_fare + toll_fare
    if total_fare > _MAX_FARE_KRW:
        raise SchemaValidationError("Kakao Directions total fare exceeds bound")
    distance = _integer(
        summary["distance"],
        "Kakao Directions distance",
        minimum=0,
        maximum=_MAX_DISTANCE_METERS,
    )
    duration = _integer(
        summary["duration"],
        "Kakao Directions duration",
        minimum=0,
        maximum=_MAX_DURATION_SECONDS,
    )

    sections = route["sections"]
    if not isinstance(sections, list) or len(sections) != 1:
        raise SchemaValidationError(
            "Kakao Directions current route must contain exactly one section"
        )
    geometry, section_distance, section_duration = _section(sections[0])
    if section_distance != distance or section_duration != duration:
        raise SchemaValidationError(
            "Kakao Directions section totals do not match summary"
        )

    route_digest = hashlib.sha256(f"{trans_id}:0".encode("ascii")).hexdigest()
    # Kakao supplies one traffic-aware duration and one point fare, not a statistical
    # interval.  The existing canonical DTO requires range slots, so equal endpoints
    # preserve exactly the supplied point values without inventing extra uncertainty.
    leg = CanonicalLeg(
        leg_id=f"kakao-directions-leg-{route_digest[:24]}",
        sequence=0,
        mode=TravelMode.TAXI,
        from_stop=CanonicalStop("Origin", origin),
        to_stop=CanonicalStop("Destination", destination),
        duration=TimeEstimate(
            duration,
            duration,
            DataOrigin.PROVIDER_ESTIMATE,
            lower_seconds=duration,
            upper_seconds=duration,
        ),
        distance_meters=distance,
        fare=MoneyRange(
            total_fare,
            total_fare,
            total_fare,
            DataOrigin.PROVIDER_ESTIMATE,
        ),
        geometry=geometry,
    )
    return (CanonicalItinerary(f"kakao-directions-{route_digest[:32]}", (leg,)),)


def _section(value: Any) -> tuple[tuple[Coordinate, ...], int, int]:
    section = _require_exact(
        value,
        {"distance", "duration", "bound", "roads", "guides"},
        "Kakao Directions section",
    )
    distance = _integer(
        section["distance"],
        "Kakao Directions section distance",
        minimum=0,
        maximum=_MAX_DISTANCE_METERS,
    )
    duration = _integer(
        section["duration"],
        "Kakao Directions section duration",
        minimum=0,
        maximum=_MAX_DURATION_SECONDS,
    )
    _bound(section["bound"], "Kakao Directions section bound")

    roads = section["roads"]
    if not isinstance(roads, list) or not 1 <= len(roads) <= _MAX_ROADS:
        raise SchemaValidationError("Kakao Directions roads count is invalid")
    geometry: list[Coordinate] = []
    for road in roads:
        item = _require_exact(
            road,
            {
                "name",
                "distance",
                "duration",
                "traffic_speed",
                "traffic_state",
                "vertexes",
            },
            "Kakao Directions road",
        )
        _text(item["name"], "Kakao Directions road name", maximum_length=500)
        _integer(
            item["distance"],
            "Kakao Directions road distance",
            minimum=0,
            maximum=_MAX_DISTANCE_METERS,
        )
        _integer(
            item["duration"],
            "Kakao Directions road duration",
            minimum=0,
            maximum=_MAX_DURATION_SECONDS,
        )
        _number(item["traffic_speed"], "Kakao Directions traffic_speed", minimum=0)
        traffic_state = _integer(
            item["traffic_state"], "Kakao Directions traffic_state", minimum=0
        )
        if traffic_state not in _TRAFFIC_STATES:
            raise SchemaValidationError("Kakao Directions traffic_state is undocumented")
        for point in _vertexes(item["vertexes"]):
            if not geometry or point != geometry[-1]:
                geometry.append(point)
    if len(geometry) < 2:
        raise SchemaValidationError("Kakao Directions geometry requires two points")

    guides = section["guides"]
    if not isinstance(guides, list) or len(guides) > _MAX_GUIDES:
        raise SchemaValidationError("Kakao Directions guides count is invalid")
    for guide in guides:
        item = _require_exact(
            guide,
            {
                "name",
                "x",
                "y",
                "distance",
                "duration",
                "type",
                "guidance",
                "road_index",
            },
            "Kakao Directions guide",
        )
        _text(item["name"], "Kakao Directions guide name", maximum_length=500)
        _coordinate(item["x"], item["y"], "Kakao Directions guide coordinate")
        _integer(
            item["distance"],
            "Kakao Directions guide distance",
            minimum=0,
            maximum=_MAX_DISTANCE_METERS,
        )
        _integer(
            item["duration"],
            "Kakao Directions guide duration",
            minimum=0,
            maximum=_MAX_DURATION_SECONDS,
        )
        _integer(item["type"], "Kakao Directions guide type", minimum=0)
        _text(
            item["guidance"],
            "Kakao Directions guide guidance",
            maximum_length=1_000,
        )
        road_index = _integer(
            item["road_index"],
            "Kakao Directions guide road_index",
            minimum=-1,
            maximum=_MAX_ROADS - 1,
        )
        if road_index >= len(roads):
            raise SchemaValidationError(
                "Kakao Directions guide road_index exceeds roads"
            )
    return tuple(geometry), distance, duration


def _point(value: Any, path: str) -> Coordinate:
    point = _require_exact(value, {"name", "x", "y"}, path)
    _text(point["name"], f"{path} name", maximum_length=200)
    return _coordinate(point["x"], point["y"], path)


def _bound(value: Any, path: str) -> None:
    bound = _require_exact(value, {"min_x", "min_y", "max_x", "max_y"}, path)
    minimum = _coordinate(bound["min_x"], bound["min_y"], f"{path} minimum")
    maximum = _coordinate(bound["max_x"], bound["max_y"], f"{path} maximum")
    if minimum.lon > maximum.lon or minimum.lat > maximum.lat:
        raise SchemaValidationError(f"{path} ordering is invalid")


def _vertexes(value: Any) -> tuple[Coordinate, ...]:
    if (
        not isinstance(value, list)
        or len(value) < 4
        or len(value) > _MAX_VERTEX_VALUES
        or len(value) % 2
    ):
        raise SchemaValidationError("Kakao Directions vertexes must be bounded x/y pairs")
    return tuple(
        _coordinate(value[index], value[index + 1], "Kakao Directions vertex")
        for index in range(0, len(value), 2)
    )


def _coordinate(x: Any, y: Any, path: str) -> Coordinate:
    try:
        return Coordinate(
            _number(x, f"{path} x", minimum=None),
            _number(y, f"{path} y", minimum=None),
        )
    except ValueError as exc:
        raise SchemaValidationError(f"{path} is outside canonical bounds") from exc


def _require_exact(value: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SchemaValidationError(f"{path} schema mismatch")
    return value


def _require_allowed(
    value: Any, required: set[str], optional: set[str], path: str
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{path} must be an object")
    if required - set(value) or set(value) - required - optional:
        raise SchemaValidationError(f"{path} schema mismatch")
    return value


def _identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _TRANS_ID.fullmatch(value):
        raise SchemaValidationError(f"{path} is invalid")
    return value


def _text(
    value: Any,
    path: str,
    *,
    maximum_length: int,
    allow_empty: bool = True,
) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum_length
        or (not allow_empty and not value)
        or any(ord(character) < 32 and character not in "\t\n\r" for character in value)
    ):
        raise SchemaValidationError(f"{path} is invalid")
    return value


def _integer(
    value: Any,
    path: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise SchemaValidationError(f"{path} is outside integer bounds")
    return value


def _number(value: Any, path: str, *, minimum: float | None) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or (minimum is not None and value < minimum)
    ):
        raise SchemaValidationError(f"{path} must be a finite number")
    return float(value)
