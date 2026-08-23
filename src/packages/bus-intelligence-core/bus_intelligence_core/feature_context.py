"""Provider-neutral, versioned optional context for ETA and Seat Risk serving.

The module performs no provider I/O. It accepts already-normalized observations,
filters them against one request ``evaluated_at``, and projects deterministic
context-only feature vectors. A context schema version is deliberately distinct
from the full model feature schema guarded by :class:`RuntimeModelSpec`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import Mapping


WEATHER_CONTEXT_SCHEMA_VERSION = "weather-context-v1"
TRAFFIC_CONTEXT_SCHEMA_VERSION = "traffic-context-v1"

ETA_CONTEXT_SERVING_SCHEMA_VERSION = "eta-context-serving-v1"
SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION = "seat-risk-context-serving-v1"

DEFAULT_WEATHER_MAX_AGE_SECONDS = 3_600
DEFAULT_TRAFFIC_MAX_AGE_SECONDS = 300

WEATHER_CONTEXT_MISSING = "WEATHER_CONTEXT_MISSING"
WEATHER_CONTEXT_FUTURE_EXCLUDED = "WEATHER_CONTEXT_FUTURE_EXCLUDED"
WEATHER_CONTEXT_STALE = "WEATHER_CONTEXT_STALE"
WEATHER_CONTEXT_SCHEMA_MISMATCH = "WEATHER_CONTEXT_SCHEMA_MISMATCH"
TRAFFIC_CONTEXT_MISSING = "TRAFFIC_CONTEXT_MISSING"
TRAFFIC_CONTEXT_FUTURE_EXCLUDED = "TRAFFIC_CONTEXT_FUTURE_EXCLUDED"
TRAFFIC_CONTEXT_STALE = "TRAFFIC_CONTEXT_STALE"
TRAFFIC_CONTEXT_SCHEMA_MISMATCH = "TRAFFIC_CONTEXT_SCHEMA_MISMATCH"

FEATURE_CONTEXT_MISSING_FLAGS = frozenset(
    {
        WEATHER_CONTEXT_MISSING,
        WEATHER_CONTEXT_FUTURE_EXCLUDED,
        WEATHER_CONTEXT_STALE,
        WEATHER_CONTEXT_SCHEMA_MISMATCH,
        TRAFFIC_CONTEXT_MISSING,
        TRAFFIC_CONTEXT_FUTURE_EXCLUDED,
        TRAFFIC_CONTEXT_STALE,
        TRAFFIC_CONTEXT_SCHEMA_MISMATCH,
    }
)
_WEATHER_TERMINAL_FLAGS = frozenset(
    {
        WEATHER_CONTEXT_MISSING,
        WEATHER_CONTEXT_FUTURE_EXCLUDED,
        WEATHER_CONTEXT_STALE,
        WEATHER_CONTEXT_SCHEMA_MISMATCH,
    }
)
_TRAFFIC_TERMINAL_FLAGS = frozenset(
    {
        TRAFFIC_CONTEXT_MISSING,
        TRAFFIC_CONTEXT_FUTURE_EXCLUDED,
        TRAFFIC_CONTEXT_STALE,
        TRAFFIC_CONTEXT_SCHEMA_MISMATCH,
    }
)

_CONTEXT_FEATURE_NAMES = (
    "weather_temperature_c",
    "weather_precipitation_mm",
    "weather_age_seconds",
    "traffic_speed_kph",
    "traffic_travel_time_seconds",
    "traffic_incident_present",
    "traffic_age_seconds",
    "context_missing_flags",
)
ETA_CONTEXT_FEATURE_NAMES = _CONTEXT_FEATURE_NAMES
SEAT_RISK_CONTEXT_FEATURE_NAMES = _CONTEXT_FEATURE_NAMES


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _schema(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("context schema_version must be non-blank")


def _optional_finite(value: float | None, field_name: str, *, nonnegative: bool) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isfinite(value):
        raise ValueError(f"{field_name} must be finite when observed")
    if nonnegative and value < 0:
        raise ValueError(f"{field_name} must be non-negative when observed")


def _flags(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted(set(values)))
    if any(not isinstance(value, str) or not value.strip() for value in normalized):
        raise ValueError("context missing flags must be non-blank")
    return normalized


@dataclass(frozen=True, slots=True)
class FeatureContextPolicy:
    """Pure acceptance/freshness policy, independently assignable per model family."""

    weather_max_age_seconds: int = DEFAULT_WEATHER_MAX_AGE_SECONDS
    traffic_max_age_seconds: int = DEFAULT_TRAFFIC_MAX_AGE_SECONDS
    accepted_weather_schema_versions: frozenset[str] = frozenset(
        {WEATHER_CONTEXT_SCHEMA_VERSION}
    )
    accepted_traffic_schema_versions: frozenset[str] = frozenset(
        {TRAFFIC_CONTEXT_SCHEMA_VERSION}
    )

    def __post_init__(self) -> None:
        for name in ("weather_max_age_seconds", "traffic_max_age_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "accepted_weather_schema_versions",
            "accepted_traffic_schema_versions",
        ):
            raw_versions = getattr(self, name)
            if isinstance(raw_versions, (str, bytes)):
                raise ValueError(f"{name} must contain non-blank versions")
            versions = frozenset(raw_versions)
            if not versions or any(
                not isinstance(value, str) or not value.strip() for value in versions
            ):
                raise ValueError(f"{name} must contain non-blank versions")
            object.__setattr__(self, name, versions)


# Separate immutable instances let ETA and Seat acceptance evolve independently.
DEFAULT_ETA_FEATURE_CONTEXT_POLICY = FeatureContextPolicy()
DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY = FeatureContextPolicy()


@dataclass(frozen=True, slots=True)
class WeatherFeatureContext:
    """Normalized weather values; absence is represented by ``None``, never zero."""

    observed_at: datetime
    schema_version: str
    temperature_c: float | None = None
    precipitation_mm: float | None = None

    def __post_init__(self) -> None:
        _aware(self.observed_at, "weather observed_at")
        _schema(self.schema_version)
        _optional_finite(self.temperature_c, "temperature_c", nonnegative=False)
        _optional_finite(self.precipitation_mm, "precipitation_mm", nonnegative=True)
        if self.temperature_c is None and self.precipitation_mm is None:
            raise ValueError("weather context requires at least one observed value")


@dataclass(frozen=True, slots=True)
class TrafficFeatureContext:
    """Normalized relevant-corridor traffic summary selected above Bus core."""

    observed_at: datetime
    schema_version: str
    speed_kph: float | None = None
    travel_time_seconds: float | None = None
    incident_present: bool | None = None

    def __post_init__(self) -> None:
        _aware(self.observed_at, "traffic observed_at")
        _schema(self.schema_version)
        _optional_finite(self.speed_kph, "speed_kph", nonnegative=True)
        _optional_finite(
            self.travel_time_seconds, "travel_time_seconds", nonnegative=True
        )
        if self.incident_present is not None and not isinstance(
            self.incident_present, bool
        ):
            raise ValueError("incident_present must be boolean when observed")
        if (
            self.speed_kph is None
            and self.travel_time_seconds is None
            and self.incident_present is None
        ):
            raise ValueError("traffic context requires at least one observed value")


def _filter_as_of(
    weather: WeatherFeatureContext | None,
    traffic: TrafficFeatureContext | None,
    missing_flags: tuple[str, ...],
    evaluated_at: datetime,
    policy: FeatureContextPolicy,
) -> tuple[
    WeatherFeatureContext | None,
    TrafficFeatureContext | None,
    tuple[str, ...],
]:
    _aware(evaluated_at, "context evaluated_at")
    if not isinstance(policy, FeatureContextPolicy):
        raise ValueError("context policy must be FeatureContextPolicy")
    # Re-derive a reserved reason whenever a value is present. Once a value has
    # already been excluded, preserve its terminal reason so repeated filtering is
    # idempotent rather than degrading FUTURE/STALE/SCHEMA_MISMATCH into MISSING.
    weather_terminal_flags = set(missing_flags) & _WEATHER_TERMINAL_FLAGS
    traffic_terminal_flags = set(missing_flags) & _TRAFFIC_TERMINAL_FLAGS
    flags = set(missing_flags) - FEATURE_CONTEXT_MISSING_FLAGS

    if weather is None:
        flags.update(weather_terminal_flags or {WEATHER_CONTEXT_MISSING})
    elif weather.observed_at > evaluated_at:
        weather = None
        flags.add(WEATHER_CONTEXT_FUTURE_EXCLUDED)
    elif weather.schema_version not in policy.accepted_weather_schema_versions:
        weather = None
        flags.add(WEATHER_CONTEXT_SCHEMA_MISMATCH)
    elif (
        evaluated_at - weather.observed_at
    ).total_seconds() > policy.weather_max_age_seconds:
        weather = None
        flags.add(WEATHER_CONTEXT_STALE)

    if traffic is None:
        flags.update(traffic_terminal_flags or {TRAFFIC_CONTEXT_MISSING})
    elif traffic.observed_at > evaluated_at:
        traffic = None
        flags.add(TRAFFIC_CONTEXT_FUTURE_EXCLUDED)
    elif traffic.schema_version not in policy.accepted_traffic_schema_versions:
        traffic = None
        flags.add(TRAFFIC_CONTEXT_SCHEMA_MISMATCH)
    elif (
        evaluated_at - traffic.observed_at
    ).total_seconds() > policy.traffic_max_age_seconds:
        traffic = None
        flags.add(TRAFFIC_CONTEXT_STALE)

    return weather, traffic, tuple(sorted(flags))


@dataclass(frozen=True, slots=True)
class EtaFeatureContext:
    weather: WeatherFeatureContext | None = None
    traffic: TrafficFeatureContext | None = None
    missing_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "missing_flags", _flags(tuple(self.missing_flags)))
        if self.weather is None and self.traffic is None and not self.missing_flags:
            raise ValueError("empty ETA feature context must be represented by None")

    def as_of(
        self,
        evaluated_at: datetime,
        *,
        policy: FeatureContextPolicy = DEFAULT_ETA_FEATURE_CONTEXT_POLICY,
    ) -> "EtaFeatureContext":
        weather, traffic, flags = _filter_as_of(
            self.weather, self.traffic, self.missing_flags, evaluated_at, policy
        )
        if (weather, traffic, flags) == (
            self.weather,
            self.traffic,
            self.missing_flags,
        ):
            return self
        return replace(self, weather=weather, traffic=traffic, missing_flags=flags)


@dataclass(frozen=True, slots=True)
class SeatRiskFeatureContext:
    weather: WeatherFeatureContext | None = None
    traffic: TrafficFeatureContext | None = None
    missing_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "missing_flags", _flags(tuple(self.missing_flags)))
        if self.weather is None and self.traffic is None and not self.missing_flags:
            raise ValueError("empty Seat Risk feature context must be represented by None")

    def as_of(
        self,
        evaluated_at: datetime,
        *,
        policy: FeatureContextPolicy = DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY,
    ) -> "SeatRiskFeatureContext":
        weather, traffic, flags = _filter_as_of(
            self.weather, self.traffic, self.missing_flags, evaluated_at, policy
        )
        if (weather, traffic, flags) == (
            self.weather,
            self.traffic,
            self.missing_flags,
        ):
            return self
        return replace(self, weather=weather, traffic=traffic, missing_flags=flags)


def resolve_eta_feature_context(
    context: EtaFeatureContext | None,
    evaluated_at: datetime,
    *,
    policy: FeatureContextPolicy = DEFAULT_ETA_FEATURE_CONTEXT_POLICY,
) -> EtaFeatureContext:
    """Return an ETA-typed context, including explicit flags for total absence."""

    if context is None:
        context = EtaFeatureContext(
            missing_flags=(WEATHER_CONTEXT_MISSING, TRAFFIC_CONTEXT_MISSING)
        )
    return context.as_of(evaluated_at, policy=policy)


def resolve_seat_risk_feature_context(
    context: SeatRiskFeatureContext | None,
    evaluated_at: datetime,
    *,
    policy: FeatureContextPolicy = DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY,
) -> SeatRiskFeatureContext:
    """Return a Seat-typed context, including explicit flags for total absence."""

    if context is None:
        context = SeatRiskFeatureContext(
            missing_flags=(WEATHER_CONTEXT_MISSING, TRAFFIC_CONTEXT_MISSING)
        )
    return context.as_of(evaluated_at, policy=policy)


@dataclass(frozen=True, slots=True)
class ContextFeatureVector:
    """Deterministic context extension; not a complete model feature vector."""

    family: str
    schema_version: str
    feature_names: tuple[str, ...]
    values: tuple[object, ...]
    missing_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.family not in {"ETA", "SEAT_RISK"}:
            raise ValueError("unsupported context feature family")
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise ValueError("context serving schema_version must be non-blank")
        if len(self.feature_names) != len(self.values):
            raise ValueError("context feature names and values must have equal length")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise ValueError("context feature names must be unique")
        object.__setattr__(self, "missing_flags", _flags(tuple(self.missing_flags)))

    @property
    def as_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(dict(zip(self.feature_names, self.values, strict=True)))


def _project(
    *,
    family: str,
    schema_version: str,
    feature_names: tuple[str, ...],
    weather: WeatherFeatureContext | None,
    traffic: TrafficFeatureContext | None,
    missing_flags: tuple[str, ...],
    evaluated_at: datetime,
) -> ContextFeatureVector:
    values: dict[str, object] = {
        "weather_temperature_c": None if weather is None else weather.temperature_c,
        "weather_precipitation_mm": None
        if weather is None
        else weather.precipitation_mm,
        "weather_age_seconds": None
        if weather is None
        else int((evaluated_at - weather.observed_at).total_seconds()),
        "traffic_speed_kph": None if traffic is None else traffic.speed_kph,
        "traffic_travel_time_seconds": None
        if traffic is None
        else traffic.travel_time_seconds,
        "traffic_incident_present": None
        if traffic is None
        else traffic.incident_present,
        "traffic_age_seconds": None
        if traffic is None
        else int((evaluated_at - traffic.observed_at).total_seconds()),
    }
    all_missing = tuple(
        sorted(
            set(missing_flags)
            | {name for name, value in values.items() if value is None}
        )
    )
    values["context_missing_flags"] = "|".join(all_missing)
    return ContextFeatureVector(
        family=family,
        schema_version=schema_version,
        feature_names=feature_names,
        values=tuple(values[name] for name in feature_names),
        missing_flags=all_missing,
    )


def build_eta_context_features(
    context: EtaFeatureContext | None,
    evaluated_at: datetime,
    *,
    policy: FeatureContextPolicy = DEFAULT_ETA_FEATURE_CONTEXT_POLICY,
) -> ContextFeatureVector:
    """Filter and project ETA-only optional context in one pure operation."""

    resolved = resolve_eta_feature_context(context, evaluated_at, policy=policy)
    return _project(
        family="ETA",
        schema_version=ETA_CONTEXT_SERVING_SCHEMA_VERSION,
        feature_names=ETA_CONTEXT_FEATURE_NAMES,
        weather=resolved.weather,
        traffic=resolved.traffic,
        missing_flags=resolved.missing_flags,
        evaluated_at=evaluated_at,
    )


def build_seat_risk_context_features(
    context: SeatRiskFeatureContext | None,
    evaluated_at: datetime,
    *,
    policy: FeatureContextPolicy = DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY,
) -> ContextFeatureVector:
    """Filter and project Seat-only optional context in one pure operation."""

    resolved = resolve_seat_risk_feature_context(context, evaluated_at, policy=policy)
    return _project(
        family="SEAT_RISK",
        schema_version=SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
        feature_names=SEAT_RISK_CONTEXT_FEATURE_NAMES,
        weather=resolved.weather,
        traffic=resolved.traffic,
        missing_flags=resolved.missing_flags,
        evaluated_at=evaluated_at,
    )
