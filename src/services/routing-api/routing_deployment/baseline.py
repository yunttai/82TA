"""Concrete live-Provider / no-Bus-model baseline dependency factory.

Provider-core owns credentials, endpoint bindings and runtime evidence.  This
module consumes one exact operation-scoped Provider config without inspecting or
copying any of its secrets, then supplies Routing-owned result persistence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import ceil
import os
from statistics import median
from threading import Lock
from time import monotonic

from provider_core.canonical import CanonicalLeg
from provider_core.named import ProviderAdapterSuiteConfig
from provider_core.requests import TransitSearchRequest
from routing_domain import TimeEstimate

from routing_api.fanin_integration import BusWaitEstimate, TaxiDispatchEstimate
from routing_api.production_composition import ProductionCompositionDependencies
from routing_deployment.bootstrap import ProductionBootstrapError, _load_factory
from routing_deployment.gbis_live import (
    GBIS_SERVICE_KEY_ENV,
    PROVIDER_HTTPS_PROXY_ENV,
    GbisLiveBusWaitEstimator,
)


PROVIDER_CONFIG_FACTORY_ENV = "ROUTING_PROVIDER_CONFIG_FACTORY"
RUNTIME_ENVIRONMENT_ENV = "ROUTING_RUNTIME_ENVIRONMENT"
LOCAL_LIVE_E2E_ENV = "ROUTING_LOCAL_LIVE_E2E"
DEFAULT_PROVIDER_CONFIG_FACTORY = (
    "provider_core.production:build_kakao_baseline_config"
)
SEOUL_TIMEZONE = timezone(timedelta(hours=9))


class LazyDjangoOptimizationResultRepository:
    """Defer ORM import until Django has completed application setup."""

    def persist(self, record) -> None:
        from routing_api.persistence.repositories import (
            DjangoOptimizationResultRepository,
        )

        DjangoOptimizationResultRepository().persist(record)


class ConservativeTaxiDispatchEstimator:
    """Time-dependent Taxi dispatch prior for the live baseline.

    Kakao directions supplies drive time and fare, not pickup time.  Until a
    verified supply model is deployed, keep that missing component explicit as
    a bounded 2--8 minute historical proxy.  The candidate entry time selects
    the bucket, so Taxi access after a preceding leg is not evaluated with a
    request-start constant.
    """

    def estimate(
        self,
        request: TransitSearchRequest,
        *,
        evaluated_at: datetime,
    ) -> TaxiDispatchEstimate:
        del request
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        local = evaluated_at.astimezone(SEOUL_TIMEZONE)
        hour = local.hour
        if 0 <= hour < 5:
            wait = TimeEstimate(240, 480)
        elif local.weekday() < 5 and (7 <= hour < 10 or 17 <= hour < 21):
            wait = TimeEstimate(180, 360)
        elif local.weekday() >= 5 and 20 <= hour < 24:
            wait = TimeEstimate(180, 360)
        else:
            wait = TimeEstimate(120, 240)
        return TaxiDispatchEstimate(
            wait=wait,
            source="TIME_BUCKET_HISTORICAL_PROXY",
            version="taxi-dispatch-historical-proxy-1.1.0",
            origin="HISTORICAL_PROXY",
        )


def _percentile(values: tuple[int, ...], probability: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, ceil(len(ordered) * probability) - 1))]


def _historical_wait(
    arrivals: Iterable[datetime], arrival_at: datetime
) -> TimeEstimate | None:
    """Estimate the next wait from prior service days at the same local time."""

    local_zone = arrival_at.tzinfo
    if local_zone is None or arrival_at.utcoffset() is None:
        raise ValueError("arrival_at must be timezone-aware")
    target_weekend = arrival_at.weekday() >= 5
    target_second = arrival_at.hour * 3600 + arrival_at.minute * 60 + arrival_at.second
    by_day: dict[object, list[int]] = {}
    for value in arrivals:
        if value.tzinfo is None or value.utcoffset() is None:
            continue
        local = value.astimezone(local_zone)
        if (local.weekday() >= 5) != target_weekend:
            continue
        second = local.hour * 3600 + local.minute * 60 + local.second
        by_day.setdefault(local.date(), []).append(second)

    waits: list[int] = []
    for seconds in by_day.values():
        # Provider polling yields several predictions for one physical arrival.
        # Collapse observations within three minutes before estimating headway.
        events: list[int] = []
        for second in sorted(seconds):
            if not events or second - events[-1] >= 180:
                events.append(second)
        if not events:
            continue
        following = next((second for second in events if second > target_second), None)
        waits.append(
            (following - target_second)
            if following is not None
            else (86_400 - target_second + events[0])
        )
    if not waits:
        return None
    values = tuple(max(1, value) for value in waits)
    p50 = max(1, ceil(median(values)))
    return TimeEstimate(p50, max(p50, _percentile(values, 0.9)))


def _conservative_headway_wait(leg: CanonicalLeg, arrival_at: datetime) -> TimeEstimate:
    """Time-dependent fallback used only until this route has arrival history."""

    hour = arrival_at.hour
    if 7 <= hour < 9:
        headway = 420
    elif 17 <= hour < 20:
        headway = 480
    elif 9 <= hour < 17:
        headway = 600
    elif 5 <= hour < 23:
        headway = 720
    else:
        headway = 1_200
    route_label = leg.transit.route_label if leg.transit is not None else "UNKNOWN"
    identity = f"{route_label}|{leg.from_stop.name}".encode("utf-8")
    phase = int.from_bytes(sha256(identity).digest()[:4], "big") % headway
    second = arrival_at.hour * 3600 + arrival_at.minute * 60 + arrival_at.second
    wait = (phase - second) % headway
    # Missing data must never silently become a zero-second wait.
    if wait < 45:
        wait += headway
    return TimeEstimate(wait, wait + max(120, headway // 2))


class DjangoHistoricalBusWaitEstimator:
    """Live-miss fallback backed by prior canonical Bus arrival observations.

    The lookup is deliberately lazy so Django can finish application setup. It
    matches the normalized route/boarding-stop identity, considers only rows
    observed by ``evaluated_at``, and estimates the next service separately for
    weekday and weekend service. Empty/new databases use an explicit
    route-specific headway proxy, never a zero wait.
    """

    _MAX_ROWS = 4_096
    _MAX_AGE = timedelta(days=56)
    _CACHE_TTL_SECONDS = 60.0

    def __init__(self) -> None:
        self._cache: dict[
            tuple[str, str, object], tuple[float, tuple[datetime, ...]]
        ] = {}
        self._lock = Lock()

    def estimate(
        self,
        leg: CanonicalLeg,
        *,
        arrival_at: datetime,
        evaluated_at: datetime,
    ) -> BusWaitEstimate:
        if arrival_at.tzinfo is None or arrival_at.utcoffset() is None:
            raise ValueError("arrival_at must be timezone-aware")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        history = self._arrival_history(leg, evaluated_at)
        wait = _historical_wait(history, arrival_at)
        if wait is not None:
            return BusWaitEstimate(
                wait=wait,
                source="BUS_ARRIVAL_OBSERVATION_HISTORY",
                version="bus-wait-history-1.0.0",
            )
        return BusWaitEstimate(
            wait=_conservative_headway_wait(leg, arrival_at),
            source="ROUTE_TIME_BUCKET_HEADWAY_PROXY",
            version="bus-wait-headway-proxy-1.0.0",
        )

    def _arrival_history(
        self, leg: CanonicalLeg, evaluated_at: datetime
    ) -> tuple[datetime, ...]:
        transit = leg.transit
        if transit is None:
            return ()
        labels = tuple(
            value.strip() for value in transit.route_label.split("/") if value.strip()
        )
        if not labels:
            return ()
        cache_key = (
            "|".join(value.casefold() for value in labels),
            leg.from_stop.name.casefold(),
            evaluated_at.date(),
        )
        now = monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and now - cached[0] < self._CACHE_TTL_SECONDS:
                return cached[1]

        values: tuple[datetime, ...] = ()
        try:
            from django.db import DatabaseError
            from django.db.models import Q

            from routing_api.models import BusArrivalObservation

            route_filter = Q()
            for label in labels:
                route_filter |= Q(trip__route__canonical_name__iexact=label)
            rows = (
                BusArrivalObservation.objects.filter(
                    route_filter,
                    stop__canonical_name__iexact=leg.from_stop.name,
                    observed_at__gte=evaluated_at - self._MAX_AGE,
                    observed_at__lte=evaluated_at,
                )
                .order_by("-observed_at")
                .values_list(
                    "observed_at", "provider_eta_seconds", "predicted_arrival_at"
                )[: self._MAX_ROWS]
            )
            projected = []
            for observed_at, eta_seconds, predicted_at in rows:
                if predicted_at is not None:
                    projected.append(predicted_at)
                elif eta_seconds is not None:
                    projected.append(observed_at + timedelta(seconds=eta_seconds))
            values = tuple(projected)
        except (DatabaseError, LookupError):
            values = ()
        with self._lock:
            self._cache[cache_key] = (now, values)
        return values


def build_dependencies(
    environment: Mapping[str, str] | None = None,
) -> ProductionCompositionDependencies:
    """Build the exact Internal-Alpha production baseline boundary object.

    Expected deployment configuration::

        ROUTING_PROVIDER_CONFIG_FACTORY=package.module:build_provider_config  # optional
        ROUTING_RUNTIME_ENVIRONMENT=STAGING|PRODUCTION

    Local Docker E2E may use ``DEVELOPMENT`` only with the exact
    ``ROUTING_LOCAL_LIVE_E2E=true`` opt-in.  It remains ``dev`` provenance,
    requires the same Provider evidence gates, and does not enable fixtures.

    The provider factory must return an exact ``ProviderAdapterSuiteConfig`` with
    its own credential handles, capability registry and runtime evidence.  This
    factory neither reads Provider key variables nor activates capabilities.  The
    default is the reviewed Kakao baseline factory in provider-core.
    """

    values = os.environ if environment is None else environment
    provider_factory_path = values.get(
        PROVIDER_CONFIG_FACTORY_ENV, DEFAULT_PROVIDER_CONFIG_FACTORY
    ).strip()
    if not provider_factory_path:
        raise ProductionBootstrapError("provider config factory is required")
    runtime = values.get(RUNTIME_ENVIRONMENT_ENV, "").strip().upper()
    deployment_environment = {
        "STAGING": "staging",
        "PRODUCTION": "prod",
    }.get(runtime)
    if (
        runtime == "DEVELOPMENT"
        and values.get(LOCAL_LIVE_E2E_ENV, "").strip().lower() == "true"
    ):
        deployment_environment = "dev"
    if deployment_environment is None:
        raise ProductionBootstrapError(
            "baseline runtime must be STAGING/PRODUCTION or explicit local live E2E"
        )
    provider_factory = _load_factory(provider_factory_path)
    try:
        provider_config = provider_factory()
    except Exception:
        raise ProductionBootstrapError("provider config factory failed") from None
    if type(provider_config) is not ProviderAdapterSuiteConfig:
        raise ProductionBootstrapError(
            "provider config factory returned an invalid boundary object"
        )
    historical_bus_wait = DjangoHistoricalBusWaitEstimator()
    bus_wait = historical_bus_wait
    gbis_key = values.get(GBIS_SERVICE_KEY_ENV, "")
    if deployment_environment == "dev" and gbis_key.strip():
        bus_wait = GbisLiveBusWaitEstimator(
            gbis_key,
            historical_bus_wait,
            proxy_url=values.get(PROVIDER_HTTPS_PROXY_ENV, ""),
        )
    return ProductionCompositionDependencies(
        provider_config=provider_config,
        persistence=LazyDjangoOptimizationResultRepository(),
        taxi_dispatch=ConservativeTaxiDispatchEstimator(),
        bus_wait=bus_wait,
        capability_registry=provider_config.capabilities,
        deployment_environment=deployment_environment,
    )
