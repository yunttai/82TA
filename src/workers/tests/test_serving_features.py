from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bus_intelligence_core import (
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_SCHEMA_VERSION,
    EtaFeatureContext,
    EtaPredictorInput,
    SeatRiskFeatureContext,
    SeatRiskPredictorInput,
    TrafficFeatureContext,
    WeatherFeatureContext,
)
from routing_worker.feature_builder import (
    NormalizedFeatureObservation,
    build_eta_features,
    build_seat_features,
)
from routing_worker.serving_features import (
    DurableEtaCompleteVectorBuilder,
    DurableSeatRiskCompleteVectorBuilder,
    EtaServingFeatureRecord,
    SeatRiskServingFeatureRecord,
    ServingFeaturePolicy,
    ServingFeatureSourceError,
)


UTC = timezone.utc
QUERY_AT = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
OBSERVED_AT = QUERY_AT - timedelta(seconds=10)


def complete_observation(**changes: object) -> NormalizedFeatureObservation:
    value = NormalizedFeatureObservation(
        trip_id="trip-token",
        route_id="route-1",
        direction="UP",
        observed_at=OBSERVED_AT,
        ingested_at=OBSERVED_AT + timedelta(seconds=2),
        valid_at=OBSERVED_AT,
        current_station_sequence=4,
        target_station_sequence=8,
        recent_segment_seconds_1=61.0,
        recent_segment_seconds_3=180.0,
        recent_segment_seconds_5=300.0,
        historical_segment_seconds=64.0,
        headway_seconds=420.0,
        current_remaining_seats=0,
        current_crowded_code=0,
        capacity_confidence=0.0,
        recent_seat_delta=0.0,
        query_at=QUERY_AT,
    )
    return replace(value, **changes)


def contexts() -> tuple[EtaFeatureContext, SeatRiskFeatureContext]:
    weather = WeatherFeatureContext(
        observed_at=OBSERVED_AT,
        schema_version=WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=0.0,
        precipitation_mm=0.0,
    )
    traffic = TrafficFeatureContext(
        observed_at=OBSERVED_AT,
        schema_version=TRAFFIC_CONTEXT_SCHEMA_VERSION,
        speed_kph=0.0,
        travel_time_seconds=0,
        incident_present=False,
    )
    return EtaFeatureContext(weather, traffic), SeatRiskFeatureContext(weather, traffic)


class EtaSource:
    def __init__(self, record: EtaServingFeatureRecord | None) -> None:
        self.record = record

    def load(self, value: EtaPredictorInput) -> EtaServingFeatureRecord | None:
        return self.record


class SeatSource:
    def __init__(self, record: SeatRiskServingFeatureRecord | None) -> None:
        self.record = record

    def load(
        self, value: SeatRiskPredictorInput
    ) -> SeatRiskServingFeatureRecord | None:
        return self.record


def eta_input(context: EtaFeatureContext | None = None) -> EtaPredictorInput:
    return EtaPredictorInput(
        vehicle_ref="vehicle-token",
        route_id="route-1",
        direction="UP",
        boarding_stop_id="stop-4",
        observed_at=OBSERVED_AT,
        remain_seat_observed=0,
        prediction_at=QUERY_AT,
        feature_context=context,
    )


def seat_input(context: SeatRiskFeatureContext | None = None) -> SeatRiskPredictorInput:
    return SeatRiskPredictorInput(
        vehicle_ref="vehicle-token",
        route_id="route-1",
        direction="UP",
        boarding_stop_id="stop-4",
        target_stop_id="stop-8",
        observed_at=OBSERVED_AT,
        prediction_at=QUERY_AT,
        remain_seat_observed=0,
        feature_context=context,
    )


def test_same_normalized_observation_is_exact_train_serve_parity() -> None:
    eta_context, seat_context = contexts()
    base = complete_observation()
    eta_train = build_eta_features(replace(base, eta_feature_context=eta_context))
    eta_serve = DurableEtaCompleteVectorBuilder(
        EtaSource(EtaServingFeatureRecord("vehicle-token", "stop-4", base))
    ).build(eta_input(eta_context))
    seat_train = build_seat_features(
        replace(base, seat_risk_feature_context=seat_context)
    )
    seat_serve = DurableSeatRiskCompleteVectorBuilder(
        SeatSource(
            SeatRiskServingFeatureRecord(
                "vehicle-token", "stop-4", "stop-8", base
            )
        )
    ).build(seat_input(seat_context))

    assert eta_serve is not None and seat_serve is not None
    assert len(eta_serve.feature_names) == len(seat_serve.feature_names) == 22
    assert (
        eta_train.family,
        eta_train.schema_version,
        eta_train.feature_names,
        eta_train.values,
        eta_train.missing_flags,
    ) == (
        "ETA",
        eta_serve.schema_version,
        eta_serve.feature_names,
        eta_serve.values,
        eta_serve.missing_flags,
    )
    assert (
        seat_train.family,
        seat_train.schema_version,
        seat_train.feature_names,
        seat_train.values,
        seat_train.missing_flags,
    ) == (
        "SEAT_RISK",
        seat_serve.schema_version,
        seat_serve.feature_names,
        seat_serve.values,
        seat_serve.missing_flags,
    )
    eta_values = dict(zip(eta_serve.feature_names, eta_serve.values, strict=True))
    assert eta_values["freshness_seconds"] == 10
    assert eta_values["weather_temperature_c"] == 0.0
    assert eta_values["traffic_incident_present"] is False
    assert "weather_temperature_c" not in eta_serve.missing_flags


def test_optional_context_missing_stays_null_with_flags() -> None:
    base = complete_observation()
    vector = DurableEtaCompleteVectorBuilder(
        EtaSource(EtaServingFeatureRecord("vehicle-token", "stop-4", base))
    ).build(eta_input())
    assert vector is not None
    values = dict(zip(vector.feature_names, vector.values, strict=True))
    assert values["weather_temperature_c"] is None
    assert "weather_temperature_c" in vector.missing_flags


@pytest.mark.parametrize(
    "observation, policy, match",
    [
        (
            complete_observation(recent_segment_seconds_3=None),
            ServingFeaturePolicy(),
            "required core",
        ),
        (
            complete_observation(
                observed_at=QUERY_AT - timedelta(seconds=400),
                ingested_at=QUERY_AT - timedelta(seconds=399),
                valid_at=QUERY_AT - timedelta(seconds=400),
            ),
            ServingFeaturePolicy(maximum_core_age_seconds=180),
            "stale core",
        ),
        (
            complete_observation(
                observed_at=QUERY_AT + timedelta(seconds=1),
                ingested_at=QUERY_AT + timedelta(seconds=1),
                valid_at=QUERY_AT + timedelta(seconds=1),
                query_at=QUERY_AT + timedelta(seconds=2),
            ),
            ServingFeaturePolicy(),
            "as-of|available",
        ),
    ],
)
def test_required_missing_stale_or_future_core_fails_closed(
    observation: NormalizedFeatureObservation,
    policy: ServingFeaturePolicy,
    match: str,
) -> None:
    builder = DurableEtaCompleteVectorBuilder(
        EtaSource(EtaServingFeatureRecord("vehicle-token", "stop-4", observation)),
        policy=policy,
    )
    with pytest.raises((ServingFeatureSourceError, ValueError), match=match):
        builder.build(replace(eta_input(), observed_at=observation.observed_at))


def test_sources_and_contexts_are_family_isolated() -> None:
    eta_context, seat_context = contexts()
    base = complete_observation()
    eta_builder = DurableEtaCompleteVectorBuilder(
        EtaSource(
            EtaServingFeatureRecord(
                "vehicle-token",
                "stop-4",
                replace(base, seat_risk_feature_context=seat_context),
            )
        )
    )
    with pytest.raises(ServingFeatureSourceError, match="Seat Risk context"):
        eta_builder.build(eta_input(eta_context))

    seat_builder = DurableSeatRiskCompleteVectorBuilder(
        SeatSource(
            SeatRiskServingFeatureRecord(
                "vehicle-token",
                "stop-4",
                "wrong-target",
                base,
            )
        )
    )
    with pytest.raises(ServingFeatureSourceError, match="identity mismatch"):
        seat_builder.build(seat_input(seat_context))


def test_absent_durable_record_returns_none() -> None:
    assert DurableEtaCompleteVectorBuilder(EtaSource(None)).build(eta_input()) is None
    assert (
        DurableSeatRiskCompleteVectorBuilder(SeatSource(None)).build(seat_input())
        is None
    )
