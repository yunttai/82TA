"""Request-scoped GBIS arrival estimates for the local live Docker profile.

The journey planner returns Bus stop names and coordinates but does not expose
GBIS identifiers.  This adapter resolves those identifiers from the official
GBIS v2 station endpoints, refreshes arrivals once for each Routing request,
and converts the first usable vehicle prediction into a wait at the candidate's
actual Bus-leg entry time.

All endpoint hosts are fixed in source.  The service key is added only at the
HTTP boundary and is never included in cache keys, exceptions, or object reprs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from threading import Lock
from time import monotonic
from typing import TypeVar, cast
import unicodedata
from urllib.parse import urlencode, urlsplit
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

from provider_core.canonical import CanonicalLeg, require_aware
from routing_domain import TimeEstimate

from routing_api.fanin_integration import BusWaitEstimate, BusWaitEstimator


GBIS_SERVICE_KEY_ENV = "GBIS_SERVICE_KEY"
PROVIDER_HTTPS_PROXY_ENV = "ROUTING_PROVIDER_HTTPS_PROXY_URL"

_STATIONS_AROUND_URL = (
    "https://apis.data.go.kr/6410000/busstationservice/v2/"
    "getBusStationAroundListv2"
)
_STATION_ROUTES_URL = (
    "https://apis.data.go.kr/6410000/busstationservice/v2/"
    "getBusStationViaRouteListv2"
)
_ARRIVALS_URL = (
    "https://apis.data.go.kr/6410000/busarrivalservice/v2/"
    "getBusArrivalListv2"
)
_MAXIMUM_RESPONSE_BYTES = 512_000
_MAXIMUM_ITEMS = 256
_MAPPING_TTL_SECONDS = 30 * 60.0
_REQUEST_ARRIVAL_TTL_SECONDS = 15.0
_MAXIMUM_CACHE_ENTRIES = 256
_HTTP_TIMEOUT_SECONDS = 0.7

_JsonFetcher = Callable[
    [str, tuple[tuple[str, str], ...]], Mapping[str, object]
]
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class _GbisRouteMapping:
    station_id: str
    route_ids: frozenset[str]


def _provider_id(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    if not normalized or len(normalized) > 64 or not normalized.isascii():
        return None
    return normalized


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


def _nonnegative_int(value: object) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 24 * 60 else None


def _identity_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().upper()
    for separator in ("(", "[", "{"):
        value = value.partition(separator)[0]
    normalized = "".join(character for character in value if character.isalnum())
    return normalized[:-1] if normalized.endswith("번") else normalized


def _route_labels(leg: CanonicalLeg) -> tuple[str, ...]:
    transit = leg.transit
    if transit is None or transit.route_label is None:
        return ()
    values = tuple(
        _identity_text(item)
        for item in transit.route_label.split("/")
        if _identity_text(item)
    )
    return tuple(dict.fromkeys(values))


def _distance_meters(
    origin_lon: float,
    origin_lat: float,
    destination_lon: float,
    destination_lat: float,
) -> float:
    # A bounded local station lookup does not need a full geodesic.  Longitude
    # scaling at Gyeonggi/Seoul latitudes is approximately 88 km per degree.
    east = (destination_lon - origin_lon) * 88_000.0
    north = (destination_lat - origin_lat) * 111_000.0
    return (east * east + north * north) ** 0.5


def _response_items(
    document: Mapping[str, object], collection_name: str
) -> tuple[Mapping[str, object], ...]:
    response = document.get("response")
    if not isinstance(response, Mapping):
        raise ValueError("GBIS response wrapper is invalid")
    header = response.get("msgHeader")
    if not isinstance(header, Mapping):
        raise ValueError("GBIS response header is invalid")
    result_code = str(header.get("resultCode", "")).strip()
    if result_code not in {"0", "00"}:
        raise ValueError("GBIS request was not successful")
    body = response.get("msgBody")
    if body is None or body == "":
        return ()
    if not isinstance(body, Mapping):
        raise ValueError("GBIS response body is invalid")
    raw = body.get(collection_name)
    if raw is None or raw == "":
        return ()
    if isinstance(raw, Mapping):
        values: tuple[object, ...] = (raw,)
    elif isinstance(raw, list):
        values = tuple(raw)
    else:
        raise ValueError("GBIS response collection is invalid")
    if len(values) > _MAXIMUM_ITEMS or any(
        not isinstance(item, Mapping) for item in values
    ):
        raise ValueError("GBIS response collection exceeds its schema bound")
    return cast(tuple[Mapping[str, object], ...], values)


class GbisLiveBusWaitEstimator:
    """Resolve a canonical Bus leg and refresh GBIS arrivals per request.

    Static stop/route identity is cached briefly.  Arrival payloads include the
    exact ``evaluated_at`` instant in their cache key, so separate route requests
    do not inherit one another's real-time snapshot.
    """

    def __init__(
        self,
        service_key: str,
        fallback: BusWaitEstimator,
        *,
        proxy_url: str = "",
        fetch_json: _JsonFetcher | None = None,
    ) -> None:
        if (
            not service_key.strip()
            or len(service_key) > 512
            or any(ord(character) < 33 or ord(character) > 126 for character in service_key)
        ):
            raise ValueError("GBIS_SERVICE_KEY is missing or invalid")
        if not callable(getattr(fallback, "estimate", None)):
            raise ValueError("GBIS live estimator requires a fallback")
        self._service_key = service_key
        self._fallback = fallback
        self._opener = self._build_opener(proxy_url)
        self._fetch_json = fetch_json or self._http_json
        self._cache: dict[tuple[object, ...], tuple[float, object]] = {}
        self._inflight: dict[tuple[object, ...], Future[object]] = {}
        self._lock = Lock()

    def estimate(
        self,
        leg: CanonicalLeg,
        *,
        arrival_at: datetime,
        evaluated_at: datetime,
    ) -> BusWaitEstimate | None:
        require_aware(arrival_at, "arrival_at")
        require_aware(evaluated_at, "evaluated_at")
        try:
            mapping = self._mapping(leg)
            if mapping is not None:
                rows = self._arrivals(mapping.station_id, evaluated_at)
                wait = self._wait_from_arrivals(
                    rows,
                    mapping.route_ids,
                    arrival_at=arrival_at,
                    evaluated_at=evaluated_at,
                )
                if wait is not None:
                    return BusWaitEstimate(
                        wait=wait,
                        source="GBIS_V2_LIVE_ARRIVAL",
                        version="gbis-live-arrival-v2.0",
                        origin="PROVIDER_ESTIMATE",
                    )
        # The route request must remain usable during a Provider timeout, schema
        # drift, key rejection, or an unmapped stop.  No exception text is logged
        # because urllib errors can contain a URL with the credential query.
        except Exception:
            pass
        return self._fallback.estimate(
            leg,
            arrival_at=arrival_at,
            evaluated_at=evaluated_at,
        )

    def _mapping(self, leg: CanonicalLeg) -> _GbisRouteMapping | None:
        labels = _route_labels(leg)
        if not labels:
            return None
        stop = leg.from_stop
        external_route_id = (
            leg.transit.external_route_id
            if leg.transit is not None
            else None
        )
        key = (
            "mapping",
            round(stop.coordinate.lon, 5),
            round(stop.coordinate.lat, 5),
            _identity_text(stop.name),
            labels,
            external_route_id,
        )

        def load() -> _GbisRouteMapping | None:
            station_rows = _response_items(
                self._fetch_json(
                    _STATIONS_AROUND_URL,
                    (
                        ("x", f"{stop.coordinate.lon:.7f}"),
                        ("y", f"{stop.coordinate.lat:.7f}"),
                        ("format", "json"),
                    ),
                ),
                "busStationAroundList",
            )
            station_id = self._nearest_station_id(leg, station_rows)
            if station_id is None:
                return None
            route_rows = _response_items(
                self._fetch_json(
                    _STATION_ROUTES_URL,
                    (("stationId", station_id), ("format", "json")),
                ),
                "busRouteList",
            )
            wanted_external = _provider_id(external_route_id)
            route_ids = frozenset(
                route_id
                for row in route_rows
                if (route_id := _provider_id(row.get("routeId"))) is not None
                and (
                    route_id == wanted_external
                    or _identity_text(str(row.get("routeName", ""))) in labels
                )
            )
            if not route_ids:
                return None
            return _GbisRouteMapping(station_id, route_ids)

        return self._cached(key, _MAPPING_TTL_SECONDS, load)

    @staticmethod
    def _nearest_station_id(
        leg: CanonicalLeg, rows: tuple[Mapping[str, object], ...]
    ) -> str | None:
        target_name = _identity_text(leg.from_stop.name)
        target = leg.from_stop.coordinate
        ranked: list[tuple[int, float, str]] = []
        for row in rows:
            station_id = _provider_id(row.get("stationId"))
            candidate_name = _identity_text(str(row.get("stationName", "")))
            lon = _finite_float(row.get("x"))
            lat = _finite_float(row.get("y"))
            if station_id is None or lon is None or lat is None:
                continue
            distance = _finite_float(row.get("distance"))
            if distance is None:
                distance = _distance_meters(target.lon, target.lat, lon, lat)
            if distance > 300.0:
                continue
            name_matches = bool(
                target_name
                and candidate_name
                and (
                    target_name == candidate_name
                    or (
                        min(len(target_name), len(candidate_name)) >= 3
                        and (
                            target_name in candidate_name
                            or candidate_name in target_name
                        )
                    )
                )
            )
            # A name mismatch is acceptable only for a very close Provider snap.
            if not name_matches and distance > 80.0:
                continue
            ranked.append((0 if name_matches else 1, distance, station_id))
        return min(ranked)[2] if ranked else None

    def _arrivals(
        self, station_id: str, evaluated_at: datetime
    ) -> tuple[Mapping[str, object], ...]:
        key = ("arrivals", station_id, evaluated_at.isoformat())

        def load() -> tuple[Mapping[str, object], ...]:
            return _response_items(
                self._fetch_json(
                    _ARRIVALS_URL,
                    (("stationId", station_id), ("format", "json")),
                ),
                "busArrivalList",
            )

        return self._cached(key, _REQUEST_ARRIVAL_TTL_SECONDS, load)

    @staticmethod
    def _wait_from_arrivals(
        rows: tuple[Mapping[str, object], ...],
        route_ids: frozenset[str],
        *,
        arrival_at: datetime,
        evaluated_at: datetime,
    ) -> TimeEstimate | None:
        waits: list[int] = []
        for row in rows:
            if _provider_id(row.get("routeId")) not in route_ids:
                continue
            for field in ("predictTime1", "predictTime2"):
                minutes = _nonnegative_int(row.get(field))
                if minutes is None:
                    continue
                # GBIS exposes minute precision.  Zero means imminent, not an
                # unknown/missing wait, so keep it distinct with a 30s midpoint.
                eta_seconds = 30 if minutes == 0 else minutes * 60
                predicted_at = evaluated_at + timedelta(seconds=eta_seconds)
                remaining = int((predicted_at - arrival_at).total_seconds())
                if remaining >= 0:
                    waits.append(max(30, remaining))
        if not waits:
            return None
        p50 = min(waits)
        # The upstream value is minute-rounded and has no percentile interval.
        # Preserve that uncertainty explicitly instead of claiming p50 == p90.
        uncertainty = max(120, min(300, p50 // 3))
        return TimeEstimate(p50, p50 + uncertainty)

    def _cached(
        self,
        key: tuple[object, ...],
        ttl_seconds: float,
        loader: Callable[[], _T],
    ) -> _T:
        now = monotonic()
        owner = False
        with self._lock:
            self._drop_expired(now)
            cached = self._cache.get(key)
            if cached is not None:
                return cast(_T, cached[1])
            future = self._inflight.get(key)
            if future is None:
                future = Future()
                self._inflight[key] = future
                owner = True
        if not owner:
            return cast(_T, future.result())
        try:
            value = loader()
        except Exception as exc:
            with self._lock:
                self._inflight.pop(key, None)
            future.set_exception(exc)
            raise
        with self._lock:
            while len(self._cache) >= _MAXIMUM_CACHE_ENTRIES:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (monotonic() + ttl_seconds, value)
            self._inflight.pop(key, None)
        future.set_result(value)
        return value

    def _drop_expired(self, now: float) -> None:
        for key in tuple(
            key for key, (expires_at, _) in self._cache.items() if expires_at <= now
        ):
            self._cache.pop(key, None)

    @staticmethod
    def _build_opener(proxy_url: str) -> OpenerDirector:
        normalized = proxy_url.strip()
        if not normalized:
            return build_opener(ProxyHandler({}))
        parsed = urlsplit(normalized)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Routing Provider HTTPS proxy URL is invalid")
        return build_opener(ProxyHandler({"https": normalized}))

    def _http_json(
        self, endpoint: str, query: tuple[tuple[str, str], ...]
    ) -> Mapping[str, object]:
        encoded = urlencode(
            (("serviceKey", self._service_key), *query),
            safe="%",
        )
        request = Request(
            f"{endpoint}?{encoded}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with self._opener.open(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", 200)
            if not 200 <= status < 300:
                raise OSError("GBIS HTTP request failed")
            raw = response.read(_MAXIMUM_RESPONSE_BYTES + 1)
        if len(raw) > _MAXIMUM_RESPONSE_BYTES:
            raise ValueError("GBIS response exceeds the byte limit")
        document = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(document, Mapping):
            raise ValueError("GBIS response root is invalid")
        return document


__all__ = [
    "GBIS_SERVICE_KEY_ENV",
    "PROVIDER_HTTPS_PROXY_ENV",
    "GbisLiveBusWaitEstimator",
]
