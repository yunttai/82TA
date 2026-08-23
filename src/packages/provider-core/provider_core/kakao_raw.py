"""Strict normalization for the documented Kakao route response shapes.

Provider dictionaries are accepted only in this infrastructure module and are
immediately converted to provider-neutral immutable values.  The schema versions
name the official documentation snapshot implemented here; they are not evidence
that a credential works or that commercial production use is approved.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Any, Mapping

from .canonical import (
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
from .validation import SchemaValidationError


KAKAO_PUBLIC_TRANSIT_SCHEMA_VERSION = "kakao.public-transit.rest.v2.2026-08-24"
KAKAO_WALK_SCHEMA_VERSION = "kakao.walk.rest.v2.2026-08-24"
KAKAO_DIRECTIONS_SCHEMA_VERSION = "kakao-mobility.directions.v1.2026-08-24"

_TRANSIT_EMPTY_STATUSES = {
    "STARTNODES_NULL",
    "ENDNODES_NULL",
    "EQUAL_POINTS",
    "INVALID_REQUEST",
    "NO_RESULTS",
}
_WALK_EMPTY_STATUSES = {
    "SAME_POINT",
    "START_LINK_NOT_FOUND",
    "END_LINK_NOT_FOUND",
    "TOO_MANY_SEARCH_LINK",
    "TOO_FAR_AWAY",
    "ROUTE_RESULT_NOT_FOUND",
}
_TRANSIT_MODES = {
    "BUS": TravelMode.BUS,
    "SUBWAY": TravelMode.SUBWAY,
    "WALKING": TravelMode.WALK,
}
_MAX_ROUTES = 32
_MAX_STEPS = 256
_MAX_POINTS = 50_000


def parse_kakao_public_transit(
    body: Any,
    *,
    effective_at: datetime | None,
    origin: Coordinate | None = None,
    destination: Coordinate | None = None,
    maximum_itineraries: int | None = None,
) -> tuple[CanonicalItinerary, ...]:
    if (origin is None) != (destination is None):
        raise SchemaValidationError("Kakao public transit endpoints must be paired")
    if maximum_itineraries is not None and (
        not isinstance(maximum_itineraries, int)
        or isinstance(maximum_itineraries, bool)
        or not 1 <= maximum_itineraries <= 10
    ):
        raise SchemaValidationError("Kakao public transit result bound is invalid")
    root = _object(body, "Kakao public transit body")
    status = _text(root.get("status"), "Kakao public transit status")
    if status in _TRANSIT_EMPTY_STATUSES:
        _exact(root, {"status"}, "Kakao public transit empty body")
        return ()
    if status != "OK":
        raise SchemaValidationError("Kakao public transit status is undocumented")
    _exact(root, {"status", "properties", "routes"}, "Kakao public transit body")
    properties = _exact_object(
        root["properties"],
        {"total", "bus", "subway", "busAndSubway", "landingURL"},
        "Kakao public transit properties",
    )
    for key in ("total", "bus", "subway", "busAndSubway"):
        _integer(properties[key], f"Kakao public transit properties.{key}")
    _text(properties["landingURL"], "Kakao public transit landingURL")
    routes = _array(root["routes"], "Kakao public transit routes", maximum=_MAX_ROUTES)
    if properties["total"] < len(routes):
        raise SchemaValidationError("Kakao public transit total is below returned routes")
    selected = routes if maximum_itineraries is None else routes[:maximum_itineraries]
    return tuple(
        _transit_route(
            route,
            index=index,
            effective_at=effective_at,
            origin=origin,
            destination=destination,
        )
        for index, route in enumerate(selected)
    )


def parse_kakao_walk(
    body: Any, *, effective_at: datetime | None
) -> tuple[CanonicalItinerary, ...]:
    root = _object(body, "Kakao walk body")
    status_value = root.get("status")
    if status_value is not None:
        status = _text(status_value, "Kakao walk status")
        if status in _WALK_EMPTY_STATUSES:
            _exact(root, {"status"}, "Kakao walk empty body")
            return ()
        if status != "OK":
            raise SchemaValidationError("Kakao walk status is undocumented")
        _exact(root, {"status", "route"}, "Kakao walk body")
    else:
        # The official successful-response example omits status even though the
        # response table documents it.  Accept exactly that published variant.
        _exact(root, {"route"}, "Kakao walk body")
    route = _exact_object(root["route"], {"properties", "legs"}, "Kakao walk route")
    properties = _exact_object(
        route["properties"],
        {"totalDistance", "totalTime", "landingUrl"},
        "Kakao walk route properties",
    )
    distance = _integer(properties["totalDistance"], "Kakao walk totalDistance")
    duration = _integer(properties["totalTime"], "Kakao walk totalTime")
    _text(properties["landingUrl"], "Kakao walk landingUrl")
    legs = _array(route["legs"], "Kakao walk legs", maximum=_MAX_STEPS)
    points: list[Coordinate] = []
    for leg_index, raw_leg in enumerate(legs):
        leg = _exact_object(raw_leg, {"properties", "steps"}, "Kakao walk leg")
        leg_properties = _exact_object(
            leg["properties"], {"distance", "time"}, "Kakao walk leg properties"
        )
        _integer(leg_properties["distance"], "Kakao walk leg distance")
        _integer(leg_properties["time"], "Kakao walk leg time")
        steps = _array(leg["steps"], "Kakao walk steps", maximum=_MAX_STEPS)
        for step_index, raw_step in enumerate(steps):
            step = _exact_object(raw_step, {"properties", "path"}, "Kakao walk step")
            step_properties = _exact_object(
                step["properties"],
                {"distance", "guidance", "time", "x", "y"},
                "Kakao walk step properties",
            )
            _integer(step_properties["distance"], "Kakao walk step distance")
            _integer(step_properties["time"], "Kakao walk step time")
            _text(step_properties["guidance"], "Kakao walk guidance")
            Coordinate(
                _number(step_properties["x"], "Kakao walk step x"),
                _number(step_properties["y"], "Kakao walk step y"),
            )
            path = _exact_object(step["path"], {"points"}, "Kakao walk path")
            step_points = _points(path["points"], "Kakao walk path points")
            if points and step_points[0] != points[-1]:
                raise SchemaValidationError("Kakao walk step geometry is disconnected")
            _extend_geometry(points, step_points)
    if len(points) < 2:
        raise SchemaValidationError("Kakao walk route requires at least two path points")
    start_at = effective_at
    end_at = None if start_at is None else start_at + timedelta(seconds=duration)
    identifier = _identifier("kakao-walk", distance, duration, points)
    leg = CanonicalLeg(
        leg_id=f"{identifier}-leg-0",
        sequence=0,
        mode=TravelMode.WALK,
        from_stop=CanonicalStop("Kakao walk origin", points[0]),
        to_stop=CanonicalStop("Kakao walk destination", points[-1]),
        duration=_point_estimate(duration),
        distance_meters=distance,
        fare=_money(0),
        expected_start_at=start_at,
        expected_end_at=end_at,
        geometry=tuple(points),
    )
    return (CanonicalItinerary(identifier, (leg,)),)


def parse_kakao_directions(
    body: Any, *, effective_at: datetime | None
) -> tuple[CanonicalItinerary, ...]:
    root = _exact_object(body, {"trans_id", "routes"}, "Kakao directions body")
    _text(root["trans_id"], "Kakao directions trans_id")
    routes = _array(root["routes"], "Kakao directions routes", maximum=_MAX_ROUTES)
    result: list[CanonicalItinerary] = []
    for index, raw_route in enumerate(routes):
        route = _object(raw_route, "Kakao directions route")
        code = _integer(route.get("result_code"), "Kakao directions result_code")
        _text(route.get("result_msg"), "Kakao directions result_msg")
        if code != 0:
            _allowed(
                route,
                required={"result_code", "result_msg"},
                optional={"summary", "sections"},
                path="Kakao directions failed route",
            )
            continue
        _exact(
            route,
            {"result_code", "result_msg", "summary", "sections"},
            "Kakao directions route",
        )
        summary = _allowed_object(
            route["summary"],
            required={"origin", "destination", "waypoints", "priority", "fare", "distance", "duration"},
            optional={"bound"},
            path="Kakao directions summary",
        )
        origin = _xy(summary["origin"], "Kakao directions origin")
        destination = _xy(summary["destination"], "Kakao directions destination")
        _array(summary["waypoints"], "Kakao directions waypoints", maximum=5)
        _text(summary["priority"], "Kakao directions priority")
        fare = _exact_object(summary["fare"], {"taxi", "toll"}, "Kakao directions fare")
        taxi_fare = _integer(fare["taxi"], "Kakao directions taxi fare")
        _integer(fare["toll"], "Kakao directions toll fare")
        distance = _integer(summary["distance"], "Kakao directions distance")
        duration = _integer(summary["duration"], "Kakao directions duration")
        sections = _array(route["sections"], "Kakao directions sections", maximum=_MAX_STEPS)
        geometry = [origin]
        for raw_section in sections:
            section = _allowed_object(
                raw_section,
                required={"distance", "duration", "roads", "guides"},
                optional={"bound"},
                path="Kakao directions section",
            )
            _integer(section["distance"], "Kakao directions section distance")
            _integer(section["duration"], "Kakao directions section duration")
            roads = _array(section["roads"], "Kakao directions roads", maximum=_MAX_STEPS)
            _array(section["guides"], "Kakao directions guides", maximum=_MAX_STEPS)
            for raw_road in roads:
                road = _allowed_object(
                    raw_road,
                    required={"name", "distance", "duration", "traffic_speed", "traffic_state", "vertexes"},
                    optional={},
                    path="Kakao directions road",
                )
                if not isinstance(road["name"], str):
                    raise SchemaValidationError("Kakao directions road name must be a string")
                _integer(road["distance"], "Kakao directions road distance")
                _integer(road["duration"], "Kakao directions road duration")
                _number(road["traffic_speed"], "Kakao directions traffic_speed")
                _integer(road["traffic_state"], "Kakao directions traffic_state")
                vertices = _flat_points(road["vertexes"], "Kakao directions vertexes")
                _extend_geometry(geometry, vertices)
        _extend_geometry(geometry, (destination,))
        start_at = effective_at
        end_at = None if start_at is None else start_at + timedelta(seconds=duration)
        identifier = _identifier("kakao-directions", index, origin, destination, distance, duration)
        leg = CanonicalLeg(
            leg_id=f"{identifier}-leg-0",
            sequence=0,
            mode=TravelMode.TAXI,
            from_stop=CanonicalStop("Kakao directions origin", origin),
            to_stop=CanonicalStop("Kakao directions destination", destination),
            duration=_point_estimate(duration),
            distance_meters=distance,
            fare=_money(taxi_fare),
            expected_start_at=start_at,
            expected_end_at=end_at,
            geometry=tuple(geometry),
        )
        result.append(CanonicalItinerary(identifier, (leg,)))
    return tuple(result)


def _transit_route(
    raw_route: Any,
    *,
    index: int,
    effective_at: datetime | None,
    origin: Coordinate | None,
    destination: Coordinate | None,
) -> CanonicalItinerary:
    route = _exact_object(raw_route, {"properties", "steps"}, "Kakao public transit route")
    properties = _exact_object(
        route["properties"],
        {"type", "totalDistance", "totalTime", "transfers", "fare"},
        "Kakao public transit route properties",
    )
    if _text(properties["type"], "Kakao public transit route type") not in {
        "BUS", "SUBWAY", "BUS_AND_SUBWAY"
    }:
        raise SchemaValidationError("Kakao public transit route type is undocumented")
    total_distance = _integer(properties["totalDistance"], "Kakao public transit totalDistance")
    total_time = _integer(properties["totalTime"], "Kakao public transit totalTime")
    _integer(properties["transfers"], "Kakao public transit transfers")
    fare = _object(properties["fare"], "Kakao public transit fare")
    if set(fare) == {"value"}:
        fare_value = _integer(fare["value"], "Kakao public transit fare value")
        fare_minimum = fare_value
        fare_maximum = fare_value
    elif set(fare) in ({"min", "max"}, {"value", "min", "max"}):
        fare_minimum = _integer(fare["min"], "Kakao public transit fare min")
        fare_maximum = _integer(fare["max"], "Kakao public transit fare max")
        # Some successful Kakao routes publish only a bounded fare range.  The
        # canonical DTO requires one expected value, so use the Provider's upper
        # bound rather than inventing an unsupported midpoint or understating cost.
        fare_value = (
            _integer(fare["value"], "Kakao public transit fare value")
            if "value" in fare
            else fare_maximum
        )
    else:
        raise SchemaValidationError("Kakao public transit fare schema mismatch")
    if not fare_minimum <= fare_value <= fare_maximum:
        raise SchemaValidationError("Kakao public transit fare range is invalid")
    steps = _array(route["steps"], "Kakao public transit steps", maximum=_MAX_STEPS)
    if not steps:
        raise SchemaValidationError("Kakao public transit route has no steps")
    parsed: list[tuple[TravelMode, int, int, tuple[Coordinate, ...], tuple[str, ...], tuple[tuple[str, str], ...]]] = []
    for raw_step in steps:
        step = _exact_object(raw_step, {"properties", "path"}, "Kakao public transit step")
        step_properties = _allowed_object(
            step["properties"],
            required={"guidance", "type", "distance", "time", "stops"},
            optional={"vehicles"},
            path="Kakao public transit step properties",
        )
        _text(step_properties["guidance"], "Kakao public transit guidance")
        raw_mode = _text(step_properties["type"], "Kakao public transit step type")
        if raw_mode not in _TRANSIT_MODES:
            raise SchemaValidationError("Kakao public transit step type is undocumented")
        distance = _integer(step_properties["distance"], "Kakao public transit step distance")
        duration = _integer(step_properties["time"], "Kakao public transit step time")
        stops = tuple(
            _text(
                _exact_object(item, {"name"}, "Kakao public transit stop")["name"],
                "Kakao public transit stop name",
            )
            for item in _array(step_properties["stops"], "Kakao public transit stops", maximum=_MAX_STEPS)
        )
        vehicles = tuple(
            (
                _text(vehicle["name"], "Kakao public transit vehicle name"),
                _text(vehicle["type"], "Kakao public transit vehicle type"),
            )
            for vehicle in (
                _exact_object(item, {"name", "type"}, "Kakao public transit vehicle")
                for item in _array(
                    step_properties.get("vehicles", []),
                    "Kakao public transit vehicles",
                    maximum=32,
                )
            )
        )
        mode = _TRANSIT_MODES[raw_mode]
        if mode is not TravelMode.WALK and (len(stops) < 2 or not vehicles):
            raise SchemaValidationError("Kakao transit step lacks documented stop or vehicle evidence")
        path = _exact_object(step["path"], {"points"}, "Kakao public transit path")
        points = _points(path["points"], "Kakao public transit path points")
        parsed.append((mode, distance, duration, points, stops, vehicles))
    step_duration = sum(item[2] for item in parsed)
    step_distance = sum(item[1] for item in parsed)
    residual_time = total_time - step_duration
    residual_distance = total_distance - step_distance
    if residual_time < 0 or residual_distance < 0:
        raise SchemaValidationError("Kakao public transit steps exceed route total")
    if len(parsed) * 2 + 1 > _MAX_STEPS:
        raise SchemaValidationError("Kakao public transit normalized leg bound exceeded")

    if origin is None or destination is None:
        if residual_time or residual_distance:
            raise SchemaValidationError("Kakao public transit route total requires request endpoints")
        if any(
            previous[3][-1] != current[3][0]
            for previous, current in zip(parsed, parsed[1:])
        ):
            raise SchemaValidationError("Kakao public transit step geometry is disconnected")
        route_origin = parsed[0][3][0]
        route_destination = parsed[-1][3][-1]
    else:
        route_origin = origin
        route_destination = destination

    connector_pairs = [
        (route_origin, parsed[0][3][0]),
        *(
            (previous[3][-1], current[3][0])
            for previous, current in zip(parsed, parsed[1:])
        ),
        (parsed[-1][3][-1], route_destination),
    ]
    connector_weights = tuple(
        _coordinate_distance_weight(start, end) for start, end in connector_pairs
    )
    connector_distances = _allocate_integer(residual_distance, connector_weights)
    connector_times = _allocate_integer(
        residual_time,
        tuple(float(value) for value in connector_distances)
        if any(connector_distances)
        else connector_weights,
    )
    start_at = effective_at
    current_at = start_at
    legs: list[CanonicalLeg] = []
    fare_assigned = False
    route_identity = _identifier(
        "kakao-public-transit",
        index,
        route_origin,
        route_destination,
        total_distance,
        total_time,
        parsed,
        connector_distances,
        connector_times,
    )

    def stop_names(item_index: int) -> tuple[str, str]:
        stops = parsed[item_index][4]
        if stops:
            return stops[0], stops[-1]
        return (
            f"Kakao walking point {item_index}",
            f"Kakao walking point {item_index + 1}",
        )

    def append_connector(connector_index: int, from_name: str, to_name: str) -> None:
        nonlocal current_at
        start, end = connector_pairs[connector_index]
        duration = connector_times[connector_index]
        distance = connector_distances[connector_index]
        if start == end and duration == 0 and distance == 0:
            return
        end_at = None if current_at is None else current_at + timedelta(seconds=duration)
        legs.append(
            CanonicalLeg(
                leg_id=f"{route_identity}-connector-{connector_index}",
                sequence=len(legs),
                mode=TravelMode.WALK,
                from_stop=CanonicalStop(from_name, start),
                to_stop=CanonicalStop(to_name, end),
                duration=_point_estimate(duration),
                distance_meters=distance,
                fare=_money(0),
                expected_start_at=current_at,
                expected_end_at=end_at,
                geometry=(start, end) if start != end else (start,),
            )
        )
        current_at = end_at

    first_from, _ = stop_names(0)
    append_connector(0, "Kakao transit origin", first_from)
    for item_index, (mode, distance, duration, points, stops, vehicles) in enumerate(parsed):
        from_name, to_name = stop_names(item_index)
        end_at = None if current_at is None else current_at + timedelta(seconds=duration)
        transit = None
        leg_fare = 0
        if mode is not TravelMode.WALK:
            route_names = tuple(dict.fromkeys(name for name, _ in vehicles))
            route_types = tuple(dict.fromkeys(kind for _, kind in vehicles))
            transit = TransitDescriptor(
                route_label=" / ".join(route_names),
                route_type=" / ".join(route_types),
                boarding_sequence=0,
                alighting_sequence=len(stops) - 1,
                terminal_names=(stops[0], stops[-1]),
            )
            if not fare_assigned:
                leg_fare = fare_value
                fare_assigned = True
        legs.append(CanonicalLeg(
            leg_id=f"{route_identity}-step-{item_index}",
            sequence=len(legs),
            mode=mode,
            from_stop=CanonicalStop(from_name, points[0], sequence=0 if stops else None),
            to_stop=CanonicalStop(to_name, points[-1], sequence=len(stops) - 1 if stops else None),
            duration=_point_estimate(duration),
            distance_meters=distance,
            fare=(
                MoneyRange(
                    fare_value,
                    fare_minimum,
                    fare_maximum,
                    DataOrigin.PROVIDER_ESTIMATE,
                )
                if leg_fare
                else _money(0)
            ),
            expected_start_at=current_at,
            expected_end_at=end_at,
            transit=transit,
            geometry=points,
        ))
        current_at = end_at
        if item_index + 1 < len(parsed):
            next_from, _ = stop_names(item_index + 1)
            append_connector(item_index + 1, to_name, next_from)
    _, last_to = stop_names(len(parsed) - 1)
    append_connector(
        len(connector_pairs) - 1,
        last_to,
        "Kakao transit destination",
    )
    if (
        sum(leg.duration.p50_seconds for leg in legs) != total_time
        or sum(leg.distance_meters for leg in legs) != total_distance
    ):
        raise SchemaValidationError("Kakao public transit normalized total mismatches route")
    return CanonicalItinerary(route_identity, tuple(legs))


def _coordinate_distance_weight(start: Coordinate, end: Coordinate) -> float:
    latitude_1 = math.radians(start.lat)
    latitude_2 = math.radians(end.lat)
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = math.radians(end.lon - start.lon)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_1)
        * math.cos(latitude_2)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 6_371_000 * 2 * math.asin(math.sqrt(haversine))


def _allocate_integer(total: int, weights: tuple[float, ...]) -> tuple[int, ...]:
    if total < 0 or not weights or any(value < 0 or not math.isfinite(value) for value in weights):
        raise SchemaValidationError("Kakao public transit residual allocation is invalid")
    if total == 0:
        return (0,) * len(weights)
    denominator = sum(weights)
    effective = weights if denominator > 0 else (1.0,) * len(weights)
    denominator = sum(effective)
    exact = tuple(total * value / denominator for value in effective)
    allocated = [math.floor(value) for value in exact]
    remainder = total - sum(allocated)
    order = sorted(
        range(len(exact)),
        key=lambda item: (-(exact[item] - allocated[item]), item),
    )
    for item in order[:remainder]:
        allocated[item] += 1
    return tuple(allocated)


def _point_estimate(seconds: int) -> TimeEstimate:
    # Kakao publishes one duration estimate, not percentile bounds.  The canonical
    # interval is deliberately collapsed rather than inventing an uncertainty uplift.
    return TimeEstimate(seconds, seconds, DataOrigin.PROVIDER_ESTIMATE)


def _money(value: int) -> MoneyRange:
    return MoneyRange(value, value, value, DataOrigin.PROVIDER_ESTIMATE)


def _identifier(prefix: str, *values: Any) -> str:
    encoded = json.dumps(values, default=_json_default, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _json_default(value: Any) -> Any:
    if isinstance(value, Coordinate):
        return [value.lon, value.lat]
    if isinstance(value, TravelMode):
        return value.value
    raise TypeError("unsupported identifier input")


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{path} must be an object")
    return value


def _exact(value: Mapping[str, Any], keys: set[str], path: str) -> None:
    if set(value) != keys:
        raise SchemaValidationError(f"{path} schema mismatch")


def _exact_object(value: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    result = _object(value, path)
    _exact(result, keys, path)
    return result


def _allowed(
    value: Mapping[str, Any], *, required: set[str], optional: set[str], path: str
) -> None:
    optional_fields = set(optional)
    if required - set(value) or set(value) - required - optional_fields:
        raise SchemaValidationError(f"{path} schema mismatch")


def _allowed_object(
    value: Any, *, required: set[str], optional: set[str], path: str
) -> Mapping[str, Any]:
    result = _object(value, path)
    _allowed(result, required=required, optional=optional, path=path)
    return result


def _array(value: Any, path: str, *, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise SchemaValidationError(f"{path} must be a bounded array")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2_048:
        raise SchemaValidationError(f"{path} must be non-empty text")
    return value


def _integer(value: Any, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SchemaValidationError(f"{path} must be a non-negative integer")
    return value


def _number(value: Any, path: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise SchemaValidationError(f"{path} must be a finite number")
    return float(value)


def _xy(value: Any, path: str) -> Coordinate:
    item = _allowed_object(
        value, required={"name", "x", "y"}, optional={}, path=path
    )
    if not isinstance(item["name"], str):
        raise SchemaValidationError(f"{path}.name must be a string")
    return Coordinate(_number(item["x"], f"{path}.x"), _number(item["y"], f"{path}.y"))


def _points(value: Any, path: str) -> tuple[Coordinate, ...]:
    raw = _array(value, path, maximum=_MAX_POINTS)
    if not raw:
        raise SchemaValidationError(f"{path} cannot be empty")
    points: list[Coordinate] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise SchemaValidationError(f"{path} point must be [x, y]")
        points.append(Coordinate(_number(item[0], path), _number(item[1], path)))
    return tuple(points)


def _flat_points(value: Any, path: str) -> tuple[Coordinate, ...]:
    raw = _array(value, path, maximum=_MAX_POINTS * 2)
    if len(raw) % 2:
        raise SchemaValidationError(f"{path} must contain x/y pairs")
    return tuple(
        Coordinate(_number(raw[index], path), _number(raw[index + 1], path))
        for index in range(0, len(raw), 2)
    )


def _extend_geometry(target: list[Coordinate], values: tuple[Coordinate, ...]) -> None:
    for value in values:
        if not target or target[-1] != value:
            target.append(value)


__all__ = [
    "KAKAO_DIRECTIONS_SCHEMA_VERSION",
    "KAKAO_PUBLIC_TRANSIT_SCHEMA_VERSION",
    "KAKAO_WALK_SCHEMA_VERSION",
    "parse_kakao_directions",
    "parse_kakao_public_transit",
    "parse_kakao_walk",
]
