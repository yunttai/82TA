from __future__ import annotations

import math

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from journeys.abuse import enforce_rate_limit
from journeys.api_common import ApiProblem, no_store, problem_response, validate_schema

from .catalog import Coordinate, build_bike_options, get_catalog


def _required_number(
    request: HttpRequest,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = request.GET.get(name)
    if raw in (None, ""):
        raise ApiProblem(400, "INVALID_COORDINATE", f"{name} is required")
    try:
        value = float(raw)
    except ValueError:
        raise ApiProblem(400, "INVALID_COORDINATE", f"{name} must be numeric") from None
    if not math.isfinite(value):
        raise ApiProblem(400, "INVALID_COORDINATE", f"{name} must be finite")
    if not minimum <= value <= maximum:
        raise ApiProblem(
            400,
            "INVALID_COORDINATE",
            f"{name} is outside the supported WGS84 range",
        )
    return value


def _coordinate(request: HttpRequest, prefix: str) -> Coordinate:
    return Coordinate(
        lon=_required_number(request, f"{prefix}Lon", minimum=124, maximum=132),
        lat=_required_number(request, f"{prefix}Lat", minimum=33, maximum=39.5),
    )


@require_GET
def bike_options(request: HttpRequest) -> JsonResponse:
    try:
        enforce_rate_limit(
            request,
            scope="bike-options",
            limit=settings.PUBLIC_RATE_LIMIT_PER_MINUTE,
            title="Too many bike option requests",
        )
        origin = _coordinate(request, "origin")
        destination = _coordinate(request, "destination")
        payload = build_bike_options(get_catalog(), origin, destination)
        validate_schema("public", "BikeOptionsResponse", payload)
        return no_store(JsonResponse(payload))
    except ApiProblem as problem:
        return problem_response(problem, request)
