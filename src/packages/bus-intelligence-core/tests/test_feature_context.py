from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from bus_intelligence_core import (
    ETA_CONTEXT_FEATURE_NAMES,
    ETA_CONTEXT_SERVING_SCHEMA_VERSION,
    SEAT_RISK_CONTEXT_FEATURE_NAMES,
    SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
    TRAFFIC_CONTEXT_FUTURE_EXCLUDED,
    TRAFFIC_CONTEXT_MISSING,
    TRAFFIC_CONTEXT_SCHEMA_MISMATCH,
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    TRAFFIC_CONTEXT_STALE,
    WEATHER_CONTEXT_FUTURE_EXCLUDED,
    WEATHER_CONTEXT_MISSING,
    WEATHER_CONTEXT_SCHEMA_MISMATCH,
    WEATHER_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_STALE,
    EtaFeatureContext,
    FeatureContextPolicy,
    RuntimeModelSpec,
    SeatRiskFeatureContext,
    TrafficFeatureContext,
    WeatherFeatureContext,
    build_eta_context_features,
    build_seat_risk_context_features,
    resolve_eta_feature_context,
    resolve_seat_risk_feature_context,
)


UTC = timezone.utc
AS_OF = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)


def weather(
    *,
    observed_at: datetime = AS_OF,
    schema_version: str = WEATHER_CONTEXT_SCHEMA_VERSION,
    temperature_c: float | None = 0.0,
    precipitation_mm: float | None = 0.0,
) -> WeatherFeatureContext:
    return WeatherFeatureContext(
        observed_at=observed_at,
        schema_version=schema_version,
        temperature_c=temperature_c,
        precipitation_mm=precipitation_mm,
    )


def traffic(
    *,
    observed_at: datetime = AS_OF,
    schema_version: str = TRAFFIC_CONTEXT_SCHEMA_VERSION,
    speed_kph: float | None = 0.0,
    travel_time_seconds: float | None = 0.0,
    incident_present: bool | None = False,
) -> TrafficFeatureContext:
    return TrafficFeatureContext(
        observed_at=observed_at,
        schema_version=schema_version,
        speed_kph=speed_kph,
        travel_time_seconds=travel_time_seconds,
        incident_present=incident_present,
    )


def test_fresh_zero_values_project_deterministically_without_zero_fill() -> None:
    eta = build_eta_context_features(
        EtaFeatureContext(weather=weather(), traffic=traffic()), AS_OF
    )
    seat = build_seat_risk_context_features(
        SeatRiskFeatureContext(weather=weather(), traffic=traffic()), AS_OF
    )

    assert eta.schema_version == ETA_CONTEXT_SERVING_SCHEMA_VERSION
    assert seat.schema_version == SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION
    assert eta.schema_version != seat.schema_version
    assert eta.feature_names == ETA_CONTEXT_FEATURE_NAMES
    assert seat.feature_names == SEAT_RISK_CONTEXT_FEATURE_NAMES
    assert eta.as_mapping == {
        "weather_temperature_c": 0.0,
        "weather_precipitation_mm": 0.0,
        "weather_age_seconds": 0,
        "traffic_speed_kph": 0.0,
        "traffic_travel_time_seconds": 0.0,
        "traffic_incident_present": False,
        "traffic_age_seconds": 0,
        "context_missing_flags": "",
    }
    assert eta.missing_flags == ()
    assert seat.values == eta.values
    with pytest.raises(TypeError):
        eta.as_mapping["weather_temperature_c"] = 1.0


def test_none_projects_as_typed_missing_not_observed_zero() -> None:
    eta = build_eta_context_features(None, AS_OF)

    assert {WEATHER_CONTEXT_MISSING, TRAFFIC_CONTEXT_MISSING}.issubset(
        eta.missing_flags
    )
    assert eta.as_mapping["weather_temperature_c"] is None
    assert eta.as_mapping["weather_age_seconds"] is None
    assert eta.as_mapping["traffic_speed_kph"] is None
    assert eta.as_mapping["traffic_incident_present"] is None


def test_configurable_freshness_accepts_boundary_and_excludes_stale() -> None:
    policy = FeatureContextPolicy(
        weather_max_age_seconds=10,
        traffic_max_age_seconds=20,
    )
    context = EtaFeatureContext(
        weather=weather(observed_at=AS_OF - timedelta(seconds=10)),
        traffic=traffic(observed_at=AS_OF - timedelta(seconds=21)),
    )

    resolved = resolve_eta_feature_context(context, AS_OF, policy=policy)

    assert resolved.weather is not None
    assert resolved.traffic is None
    assert TRAFFIC_CONTEXT_STALE in resolved.missing_flags
    assert WEATHER_CONTEXT_STALE not in resolved.missing_flags


def test_stale_future_and_schema_mismatch_are_typed_missing_not_errors() -> None:
    policy = FeatureContextPolicy(
        weather_max_age_seconds=10,
        traffic_max_age_seconds=10,
    )
    stale = resolve_eta_feature_context(
        EtaFeatureContext(
            weather=weather(observed_at=AS_OF - timedelta(seconds=11)),
            traffic=traffic(observed_at=AS_OF - timedelta(seconds=11)),
        ),
        AS_OF,
        policy=policy,
    )
    future = resolve_eta_feature_context(
        EtaFeatureContext(
            weather=weather(observed_at=AS_OF + timedelta(microseconds=1)),
            traffic=traffic(observed_at=AS_OF + timedelta(microseconds=1)),
        ),
        AS_OF,
    )
    mismatch = resolve_eta_feature_context(
        EtaFeatureContext(
            weather=weather(schema_version="weather-context-v999"),
            traffic=traffic(schema_version="traffic-context-v999"),
        ),
        AS_OF,
    )

    assert stale.weather is None and stale.traffic is None
    assert {WEATHER_CONTEXT_STALE, TRAFFIC_CONTEXT_STALE}.issubset(
        stale.missing_flags
    )
    assert future.weather is None and future.traffic is None
    assert {
        WEATHER_CONTEXT_FUTURE_EXCLUDED,
        TRAFFIC_CONTEXT_FUTURE_EXCLUDED,
    }.issubset(future.missing_flags)
    assert mismatch.weather is None and mismatch.traffic is None
    assert {
        WEATHER_CONTEXT_SCHEMA_MISMATCH,
        TRAFFIC_CONTEXT_SCHEMA_MISMATCH,
    }.issubset(mismatch.missing_flags)


@pytest.mark.parametrize(
    ("context", "expected_flags"),
    [
        (
            EtaFeatureContext(
                weather=weather(observed_at=AS_OF + timedelta(seconds=1)),
                traffic=traffic(observed_at=AS_OF + timedelta(seconds=1)),
            ),
            {
                WEATHER_CONTEXT_FUTURE_EXCLUDED,
                TRAFFIC_CONTEXT_FUTURE_EXCLUDED,
            },
        ),
        (
            EtaFeatureContext(
                weather=weather(observed_at=AS_OF - timedelta(hours=2)),
                traffic=traffic(observed_at=AS_OF - timedelta(minutes=6)),
            ),
            {WEATHER_CONTEXT_STALE, TRAFFIC_CONTEXT_STALE},
        ),
        (
            EtaFeatureContext(
                weather=weather(schema_version="weather-context-v999"),
                traffic=traffic(schema_version="traffic-context-v999"),
            ),
            {
                WEATHER_CONTEXT_SCHEMA_MISMATCH,
                TRAFFIC_CONTEXT_SCHEMA_MISMATCH,
            },
        ),
    ],
)
def test_repeated_as_of_and_builder_preserve_terminal_missing_reason(
    context: EtaFeatureContext, expected_flags: set[str]
) -> None:
    once = context.as_of(AS_OF)
    twice = once.as_of(AS_OF)
    first_vector = build_eta_context_features(once, AS_OF)
    second_vector = build_eta_context_features(twice, AS_OF)

    assert once == twice
    assert expected_flags.issubset(once.missing_flags)
    assert expected_flags.issubset(twice.missing_flags)
    assert first_vector == second_vector


def test_eta_and_seat_filter_with_independent_policies_and_types() -> None:
    eta_policy = FeatureContextPolicy(
        accepted_weather_schema_versions=frozenset({"eta-weather-v2"}),
        accepted_traffic_schema_versions=frozenset({"eta-traffic-v2"}),
    )
    seat_policy = FeatureContextPolicy()
    eta_context = EtaFeatureContext(
        weather=weather(schema_version="eta-weather-v2"),
        traffic=traffic(schema_version="eta-traffic-v2"),
    )
    seat_context = SeatRiskFeatureContext(
        weather=weather(schema_version="eta-weather-v2"),
        traffic=traffic(schema_version="eta-traffic-v2"),
    )

    resolved_eta = resolve_eta_feature_context(
        eta_context, AS_OF, policy=eta_policy
    )
    resolved_seat = resolve_seat_risk_feature_context(
        seat_context, AS_OF, policy=seat_policy
    )

    assert isinstance(resolved_eta, EtaFeatureContext)
    assert resolved_eta.weather is not None and resolved_eta.traffic is not None
    assert isinstance(resolved_seat, SeatRiskFeatureContext)
    assert resolved_seat.weather is None and resolved_seat.traffic is None
    assert {
        WEATHER_CONTEXT_SCHEMA_MISMATCH,
        TRAFFIC_CONTEXT_SCHEMA_MISMATCH,
    }.issubset(resolved_seat.missing_flags)


def test_context_schema_does_not_replace_full_runtime_model_schema_guard() -> None:
    spec = RuntimeModelSpec(
        purpose="BUS_ETA",
        version="eta-v3",
        readiness="ACTIVE",
        feature_schema_version="eta-full-feature-v3",
    )

    assert spec.can_serve("eta-full-feature-v3") is True
    assert spec.can_serve(ETA_CONTEXT_SERVING_SCHEMA_VERSION) is False


def test_invalid_generation_inputs_fail_fast_and_policy_is_immutable() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        weather(observed_at=AS_OF.replace(tzinfo=None))
    with pytest.raises(ValueError, match="positive integer"):
        FeatureContextPolicy(weather_max_age_seconds=0)
    with pytest.raises(ValueError, match="non-blank versions"):
        FeatureContextPolicy(accepted_weather_schema_versions=frozenset({""}))
    policy = FeatureContextPolicy()
    with pytest.raises(FrozenInstanceError):
        policy.weather_max_age_seconds = 1
