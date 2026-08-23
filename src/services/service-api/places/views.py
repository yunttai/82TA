from __future__ import annotations

import copy
import math

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from journeys.abuse import enforce_rate_limit
from journeys.api_common import ApiProblem, no_store, problem_response, validate_schema
from journeys.cache import BoundedTTLCache

from .adapter import PlaceProviderError, configured_adapter

_place_cache = BoundedTTLCache[str, object](
    max_entries=settings.PLACE_CACHE_MAX_ENTRIES,
    ttl_seconds=settings.PLACE_CACHE_TTL_SECONDS,
)


def _number(raw: str | None, name: str) -> float | None:
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ApiProblem(400, "INVALID_COORDINATE", f"{name} must be numeric") from None
    if not math.isfinite(value):
        raise ApiProblem(400, "INVALID_COORDINATE", f"{name} must be finite")
    return value


def _coordinate(lon_raw: str | None, lat_raw: str | None, *, required: bool) -> tuple[float | None, float | None]:
    lon, lat = _number(lon_raw, "lon"), _number(lat_raw, "lat")
    if required and (lon is None or lat is None):
        raise ApiProblem(400, "INVALID_COORDINATE", "lon and lat are required")
    if (lon is None) != (lat is None):
        raise ApiProblem(400, "INVALID_COORDINATE", "lon and lat must be supplied together")
    if lon is not None and not 124 <= lon <= 132:
        raise ApiProblem(400, "INVALID_COORDINATE", "lon is outside the supported WGS84 range")
    if lat is not None and not 33 <= lat <= 39.5:
        raise ApiProblem(400, "INVALID_COORDINATE", "lat is outside the supported WGS84 range")
    return lon, lat


@require_GET
def suggest_places(request: HttpRequest) -> JsonResponse:
    try:
        enforce_rate_limit(
            request,
            scope="places",
            limit=settings.PLACE_RATE_LIMIT_PER_MINUTE,
            title="Too many place requests",
        )
        query = request.GET.get("query", "").strip()
        if not 2 <= len(query) <= 100:
            raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "query must contain 2-100 characters")
        lon, lat = _coordinate(request.GET.get("lon"), request.GET.get("lat"), required=False)
        cache_key = f"suggest:{query.casefold()}:{lon}:{lat}"
        cached = _place_cache.get(cache_key)
        items = copy.deepcopy(cached) if isinstance(cached, list) else None
        if items is None:
            items = configured_adapter().suggest(query, lon=lon, lat=lat)
            _place_cache.set(cache_key, copy.deepcopy(items))
        for item in items:
            validate_schema("public", "SavedPlaceInput", {"label": "result", "place": item})
        return no_store(JsonResponse({"items": items}))
    except ApiProblem as problem:
        return problem_response(problem, request)
    except PlaceProviderError:
        return problem_response(
            ApiProblem(502, "PROVIDER_BAD_RESPONSE", "Place provider is temporarily unavailable", retryable=True),
            request,
        )


@require_GET
def reverse_geocode(request: HttpRequest) -> JsonResponse:
    try:
        enforce_rate_limit(
            request,
            scope="places",
            limit=settings.PLACE_RATE_LIMIT_PER_MINUTE,
            title="Too many place requests",
        )
        lon, lat = _coordinate(request.GET.get("lon"), request.GET.get("lat"), required=True)
        assert lon is not None and lat is not None
        cache_key = f"reverse:{lon:.6f}:{lat:.6f}"
        cached = _place_cache.get(cache_key)
        item = copy.deepcopy(cached) if isinstance(cached, dict) else None
        if item is None:
            item = configured_adapter().reverse(lon, lat)
            _place_cache.set(cache_key, copy.deepcopy(item))
        validate_schema("public", "SavedPlaceInput", {"label": "result", "place": item})
        return no_store(JsonResponse(item))
    except ApiProblem as problem:
        return problem_response(problem, request)
    except PlaceProviderError:
        return problem_response(
            ApiProblem(502, "PROVIDER_BAD_RESPONSE", "Place provider is temporarily unavailable", retryable=True),
            request,
        )
