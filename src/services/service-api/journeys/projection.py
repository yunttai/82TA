from __future__ import annotations

import copy
from typing import Any

from .contracts import CanonicalContracts, ContractError, LockedFixtures


_PUBLIC_TRANSIT_FIELDS = ("routeLabel", "routeType", "direction")
_MAX_GEOMETRY_POINTS = 10_000
_MAX_POLYLINE_CHARACTERS = 100_000


def _public_transit(value: object) -> dict[str, str | None] | None:
    if not isinstance(value, dict):
        return None
    return {
        key: item
        for key in _PUBLIC_TRANSIT_FIELDS
        if isinstance((item := value.get(key)), str) or item is None
    }


def _decode_public_polyline(raw: str) -> list[list[float]] | None:
    """Decode a standard polyline into bounded Korea-area WGS84 coordinates.

    Returning numeric GeoJSON rather than the provider-supplied string prevents
    an open private geometry field from becoming an arbitrary text channel in
    the Public API.
    """

    if not raw or len(raw) > _MAX_POLYLINE_CHARACTERS:
        return None
    index = 0
    latitude = 0
    longitude = 0
    coordinates: list[list[float]] = []

    def read_delta() -> int | None:
        nonlocal index
        result = 0
        shift = 0
        while index < len(raw):
            byte = ord(raw[index]) - 63
            index += 1
            if byte < 0 or byte > 63 or shift > 30:
                return None
            result += (byte & 0x1F) << shift
            if byte < 0x20:
                return -(result // 2 + 1) if result % 2 else result // 2
            shift += 5
        return None

    while index < len(raw):
        if len(coordinates) >= _MAX_GEOMETRY_POINTS:
            return None
        latitude_delta = read_delta()
        longitude_delta = read_delta()
        if latitude_delta is None or longitude_delta is None:
            return None
        latitude += latitude_delta
        longitude += longitude_delta
        lat = latitude / 100_000
        lon = longitude / 100_000
        if not 124 <= lon <= 132 or not 33 <= lat <= 39.5:
            return None
        coordinates.append([lon, lat])
    return coordinates if len(coordinates) >= 2 else None


def _public_geometry(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"encoding": "NONE"}
    encoding = value.get("encoding")
    raw = value.get("value")
    if encoding == "POLYLINE" and isinstance(raw, str):
        coordinates = _decode_public_polyline(raw)
        if coordinates is not None:
            return {
                "encoding": "GEOJSON",
                "value": {"type": "LineString", "coordinates": coordinates},
            }
    if encoding == "GEOJSON" and isinstance(raw, dict):
        coordinates = raw.get("coordinates")
        if (
            raw.get("type") == "LineString"
            and set(raw) == {"type", "coordinates"}
            and isinstance(coordinates, list)
            and 2 <= len(coordinates) <= _MAX_GEOMETRY_POINTS
        ):
            safe_coordinates: list[list[float | int]] = []
            for point in coordinates:
                if not isinstance(point, list) or len(point) != 2:
                    break
                lon, lat = point
                if (
                    isinstance(lon, bool)
                    or not isinstance(lon, (int, float))
                    or isinstance(lat, bool)
                    or not isinstance(lat, (int, float))
                    or not 124 <= lon <= 132
                    or not 33 <= lat <= 39.5
                ):
                    break
                safe_coordinates.append([lon, lat])
            else:
                return {
                    "encoding": "GEOJSON",
                    "value": {"type": "LineString", "coordinates": safe_coordinates},
                }
    return {"encoding": "NONE"}


def _public_route(value: dict[str, Any]) -> dict[str, Any]:
    route = copy.deepcopy(value)
    if "arrivalAt" in route:
        arrival = route.get("arrivalAt")
        route["arrivalAt"] = (
            {
                key: item
                for key in ("p50", "p90")
                if key in arrival
                and (isinstance((item := arrival[key]), str) or item is None)
            }
            if isinstance(arrival, dict)
            else {}
        )
    if "dominance" in route:
        dominance = route.get("dominance")
        route["dominance"] = (
            {"onParetoFrontier": dominance["onParetoFrontier"]}
            if isinstance(dominance, dict)
            and isinstance(dominance.get("onParetoFrontier"), bool)
            else {}
        )
    for leg in route.get("legs", []):
        if not isinstance(leg, dict):
            continue
        leg["geometry"] = _public_geometry(leg.get("geometry"))
        if "transit" in leg:
            leg["transit"] = _public_transit(leg.get("transit"))
    return route


def project_public_response(
    routing_response: dict[str, Any],
    contracts: CanonicalContracts,
    fixtures: LockedFixtures,
    support: dict[str, Any] | None = None,
    public_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    private_errors = contracts.validate("private", "OptimizeRouteResponse", routing_response)
    if private_errors:
        raise ContractError("canonical Routing response failed private schema validation")

    routes = {
        route["routeId"]: _public_route(route)
        for route in routing_response["routes"]
    }
    recommendation_ids = routing_response["recommendations"]
    strict_budget = bool(public_request and public_request["taxiBudget"]["strict"])
    budget_max = public_request["taxiBudget"]["maxAmount"] if public_request else None
    for route in routes.values():
        duration = route["totalDuration"]
        if duration["p90Seconds"] < duration["p50Seconds"]:
            raise ContractError("Routing response violates P90 >= P50")
        if strict_budget and route["taxiCost"]["upper"] > budget_max:
            raise ContractError("Routing response violates the strict taxi budget")
    if routing_response["status"] == "COMPLETE":
        missing = [
            identifier
            for identifier in recommendation_ids.values()
            if identifier is not None and identifier not in routes
        ]
        if missing:
            raise ContractError("COMPLETE Routing response references a missing route")
    canonical_support = support or fixtures.get("public_response")["support"]
    baseline = routes.get(recommendation_ids.get("publicTransitOnly"))

    response = {
        "contractVersion": routing_response["contractVersion"],
        "searchId": routing_response["requestId"],
        "status": routing_response["status"],
        "generatedAt": routing_response["generatedAt"],
        "expiresAt": routing_response["expiresAt"],
        "baseline": baseline,
        "recommendations": {
            "fastest": routes.get(recommendation_ids.get("fastest")),
            "stable": routes.get(recommendation_ids.get("stable")),
            "efficient": routes.get(recommendation_ids.get("efficient")),
            "publicTransitOnly": routes.get(recommendation_ids.get("publicTransitOnly")),
        },
        "paretoFrontier": [
            {
                "routeId": route_id,
                "taxiCostUpper": routes[route_id]["taxiCost"]["upper"],
                "p50Seconds": routes[route_id]["totalDuration"]["p50Seconds"],
                "p90Seconds": routes[route_id]["totalDuration"]["p90Seconds"],
            }
            for route_id in routing_response["paretoRouteIds"]
            if route_id in routes
        ],
        "warnings": list(routing_response["warningCodes"]),
        "support": canonical_support,
    }
    public_errors = contracts.validate("public", "PublicRouteSearchResponse", response)
    if public_errors:
        raise ContractError("projected response failed public schema validation")
    return response
