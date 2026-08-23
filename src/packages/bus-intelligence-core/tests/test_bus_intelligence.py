from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from bus_intelligence_core import (
    BusIntelligenceEngine,
    BusIntelligenceRequest,
    EnginePolicy,
    EtaFeatureContext,
    EtaPrediction,
    SeatRiskFeatureContext,
    SeatRiskPrediction,
    TrafficFeatureContext,
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    VehicleObservation,
    WeatherFeatureContext,
    WEATHER_CONTEXT_SCHEMA_VERSION,
    apply_bus_intelligence_wait,
)


UTC = timezone.utc
ARRIVAL = datetime(2026, 8, 23, 8, 0, tzinfo=UTC)
EVALUATED = ARRIVAL - timedelta(seconds=30)


class RecordingEtaPredictor:
    def __init__(self, values: dict[str, EtaPrediction | None] | None = None) -> None:
        self.values = values or {}
        self.inputs = []

    def predict(self, value):
        self.inputs.append(value)
        return self.values.get(value.vehicle_ref)


class RecordingSeatPredictor:
    def __init__(self, values: dict[str, SeatRiskPrediction | None] | None = None) -> None:
        self.values = values or {}
        self.inputs = []

    def predict(self, value):
        self.inputs.append(value)
        return self.values.get(value.vehicle_ref)


def eta(seconds: int, *, p90_extra: int = 60, source: str = "OFFICIAL") -> EtaPrediction:
    return EtaPrediction(
        p50_arrival_at=ARRIVAL + timedelta(seconds=seconds),
        p90_arrival_at=ARRIVAL + timedelta(seconds=seconds + p90_extra),
        source=source,
        model_version=None if source == "OFFICIAL" else f"fixture-{source.lower()}-v1",
        confidence=0.9,
        model_readiness="FIXTURE_ONLY",
    )


def risk(no_seat: float, *, confidence: float = 0.9) -> SeatRiskPrediction:
    return SeatRiskPrediction(
        no_seat_probability=no_seat,
        low_seat2_probability=min(1.0, no_seat + 0.05),
        low_seat5_probability=min(1.0, no_seat + 0.1),
        model_version="fixture-seat-v1",
        confidence=confidence,
        model_readiness="FIXTURE_ONLY",
    )


def observation(
    vehicle_ref: str,
    eta_value: EtaPrediction | None,
    *,
    future_target_remaining_seats: int | None = None,
    observed_at: datetime = EVALUATED,
) -> VehicleObservation:
    return VehicleObservation(
        vehicle_ref=vehicle_ref,
        route_id="R-1",
        direction="OUTBOUND",
        boarding_stop_id="S-BOARD",
        observed_at=observed_at,
        official_eta=eta_value,
        remain_seat_observed=4,
        future_target_remaining_seats=future_target_remaining_seats,
    )


def request(
    *observations: VehicleObservation,
    grade: str = "HIGH",
    mapping_allowed: bool | None = None,
    service_type: str = "SEATED",
    user_arrival_at: datetime = ARRIVAL,
    evaluated_at: datetime = EVALUATED,
    eta_feature_context: EtaFeatureContext | None = None,
    seat_risk_feature_context: SeatRiskFeatureContext | None = None,
) -> BusIntelligenceRequest:
    return BusIntelligenceRequest(
        mapping_grade=grade,
        mapping_allows_bus_intelligence=(grade == "HIGH" if mapping_allowed is None else mapping_allowed),
        mapping_score=0.98,
        mapping_version="0.1.0-planned",
        user_arrival_at=user_arrival_at,
        evaluated_at=evaluated_at,
        target_stop_id="S-TARGET",
        service_type=service_type,
        observations=tuple(observations),
        eta_feature_context=eta_feature_context,
        seat_risk_feature_context=seat_risk_feature_context,
    )


def engine(
    eta_values: dict[str, EtaPrediction | None] | None = None,
    seat_values: dict[str, SeatRiskPrediction | None] | None = None,
    *,
    headway: int = 900,
    max_batch_requests: int = 32,
):
    eta_predictor = RecordingEtaPredictor(eta_values)
    seat_predictor = RecordingSeatPredictor(seat_values)
    instance = BusIntelligenceEngine(
        eta_predictor,
        seat_predictor,
        EnginePolicy(
            conservative_headway_seconds=headway,
            max_batch_requests=max_batch_requests,
        ),
    )
    return instance, eta_predictor, seat_predictor


@pytest.mark.parametrize("grade", ["MEDIUM", "LOW", "UNKNOWN"])
def test_only_high_mapping_can_enrich(grade: str) -> None:
    instance, eta_port, seat_port = engine()
    result = instance.enrich(request(observation("v1", eta(60)), grade=grade))

    assert not result.enrichment_applied
    assert result.expected_wait_seconds is None
    assert result.p90_wait_seconds is None
    assert result.coverage == "UNSUPPORTED"
    assert result.warnings == ("BUS_MAPPING_LOW_CONFIDENCE",)
    assert eta_port.inputs == []
    assert seat_port.inputs == []


def test_candidates_are_strictly_after_timezone_aware_user_arrival() -> None:
    before = EtaPrediction(
        p50_arrival_at=ARRIVAL - timedelta(microseconds=1),
        p90_arrival_at=ARRIVAL + timedelta(seconds=60),
        source="OFFICIAL",
    )
    instance, _, seat_port = engine(seat_values={"equal": risk(0.1), "after": risk(0.1)})
    result = instance.enrich(
        request(
            observation("before", before),
            observation("equal", eta(0)),
            observation("after", eta(60)),
        )
    )

    assert [candidate.vehicle_ref for candidate in result.candidate_vehicles] == ["after"]
    assert [value.vehicle_ref for value in seat_port.inputs] == ["after"]


def test_naive_user_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        BusIntelligenceRequest(
            mapping_grade="HIGH",
            mapping_allows_bus_intelligence=True,
            mapping_score=1.0,
            mapping_version="v1",
            user_arrival_at=datetime(2026, 8, 23, 8, 0),
            evaluated_at=EVALUATED,
            target_stop_id="target",
            service_type="SEATED",
            observations=(),
        )


def test_unknown_service_type_is_rejected_instead_of_defaulting_to_seated() -> None:
    with pytest.raises(ValueError, match="SEATED or GENERAL"):
        request(observation("v1", eta(60)), service_type="UNKNOWN")


def test_future_observation_cannot_shadow_latest_valid_vehicle_snapshot() -> None:
    valid = observation("v1", eta(120), observed_at=EVALUATED)
    future = observation(
        "v1",
        eta(30),
        observed_at=EVALUATED + timedelta(seconds=1),
    )
    instance, eta_port, seat_port = engine(seat_values={"v1": risk(0.1)})

    result = instance.enrich(request(valid, future))

    assert [candidate.wait_p50_seconds for candidate in result.candidate_vehicles] == [120]
    assert eta_port.inputs == []
    assert [value.observed_at for value in seat_port.inputs] == [EVALUATED]


def test_same_bus_movement_is_re_evaluated_for_each_propagated_arrival() -> None:
    values = (observation("v1", eta(120)), observation("v2", eta(300)))
    instance, _, seat_port = engine(
        seat_values={"v1": risk(0.1), "v2": risk(0.2)}
    )

    early = instance.enrich(request(*values, user_arrival_at=ARRIVAL))
    later = instance.enrich(
        request(*values, user_arrival_at=ARRIVAL + timedelta(seconds=180))
    )

    assert [item.vehicle_ref for item in early.candidate_vehicles] == ["v1", "v2"]
    assert [item.vehicle_ref for item in later.candidate_vehicles] == ["v2"]
    assert [item.wait_p50_seconds for item in later.candidate_vehicles] == [120]
    assert [value.vehicle_ref for value in seat_port.inputs] == ["v1", "v2", "v2"]
    assert {value.prediction_at for value in seat_port.inputs} == {EVALUATED}


def test_bounded_batch_preserves_arrival_order_nulls_and_per_result_provenance() -> None:
    valid = (
        observation("v1", None),
        observation("v2", None),
        observation(
            "v2",
            None,
            observed_at=EVALUATED + timedelta(seconds=1),
        ),
    )
    instance, eta_port, seat_port = engine(
        eta_values={
            "v1": eta(120, source="POSITION_MODEL"),
            "v2": eta(300, source="POSITION_MODEL"),
        },
        seat_values={"v1": risk(0.1), "v2": risk(0.2)},
    )

    batch = (
        request(*valid, user_arrival_at=ARRIVAL),
        request(*valid, user_arrival_at=ARRIVAL + timedelta(seconds=180)),
        request(*valid, service_type="GENERAL", user_arrival_at=ARRIVAL),
    )
    results = instance.evaluate_many(batch)
    replayed = instance.evaluate_many(batch)

    assert replayed == results
    assert [
        [candidate.vehicle_ref for candidate in result.candidate_vehicles]
        for result in results
    ] == [["v1", "v2"], ["v2"], ["v1", "v2"]]
    assert all(
        result.p90_wait_seconds is None
        or result.expected_wait_seconds is None
        or result.p90_wait_seconds >= result.expected_wait_seconds
        for result in results
    )
    assert [
        {item.purpose for item in result.model_provenance} for result in results
    ] == [{"BUS_ETA", "SEAT_RISK"}, {"BUS_ETA", "SEAT_RISK"}, {"BUS_ETA"}]
    assert all(
        candidate.future_target_remaining_seats is None
        and candidate.future_target_observed is False
        for result in results
        for candidate in result.candidate_vehicles
    )
    # Two valid vehicle snapshots per request. The future duplicate is excluded
    # before de-duplication/prediction, and GENERAL never invokes Seat Risk.
    assert len(eta_port.inputs) == 12
    assert [value.vehicle_ref for value in seat_port.inputs] == [
        "v1", "v2", "v2", "v1", "v2", "v2"
    ]
    assert {value.prediction_at for value in (*eta_port.inputs, *seat_port.inputs)} == {
        EVALUATED
    }


def test_oversized_batch_is_rejected_before_any_predictor_call() -> None:
    instance, eta_port, seat_port = engine(
        eta_values={"v1": eta(120, source="POSITION_MODEL")},
        seat_values={"v1": risk(0.1)},
        max_batch_requests=2,
    )

    with pytest.raises(ValueError, match="exceeds 2 requests"):
        instance.evaluate_many(
            request(observation("v1", None)) for _ in range(3)
        )

    assert eta_port.inputs == []
    assert seat_port.inputs == []


def test_empty_batch_is_a_noop() -> None:
    instance, eta_port, seat_port = engine()

    assert instance.evaluate_many(()) == ()
    assert eta_port.inputs == []
    assert seat_port.inputs == []


def test_eta_and_seat_receive_independent_optional_context_without_zero_fill() -> None:
    eta_weather = WeatherFeatureContext(
        observed_at=EVALUATED,
        schema_version=WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=-3.5,
        precipitation_mm=None,
    )
    eta_traffic = TrafficFeatureContext(
        observed_at=EVALUATED,
        schema_version=TRAFFIC_CONTEXT_SCHEMA_VERSION,
        speed_kph=0.0,
        travel_time_seconds=None,
        incident_present=None,
    )
    seat_weather = WeatherFeatureContext(
        observed_at=EVALUATED,
        schema_version=WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=None,
        precipitation_mm=0.0,
    )
    instance, eta_port, seat_port = engine(
        eta_values={"v1": eta(120, source="POSITION_MODEL")},
        seat_values={"v1": risk(0.1)},
    )

    result = instance.enrich(
        request(
            observation("v1", None),
            eta_feature_context=EtaFeatureContext(
                weather=eta_weather,
                traffic=eta_traffic,
                missing_flags=("HOLIDAY_CONTEXT_MISSING",),
            ),
            seat_risk_feature_context=SeatRiskFeatureContext(
                weather=seat_weather,
                traffic=None,
                missing_flags=("TRAFFIC_CONTEXT_MISSING",),
            ),
        )
    )

    assert result.enrichment_applied
    assert eta_port.inputs[0].feature_context == EtaFeatureContext(
        weather=eta_weather,
        traffic=eta_traffic,
        missing_flags=("HOLIDAY_CONTEXT_MISSING",),
    )
    assert seat_port.inputs[0].feature_context == SeatRiskFeatureContext(
        weather=seat_weather,
        traffic=None,
        missing_flags=("TRAFFIC_CONTEXT_MISSING",),
    )
    assert eta_port.inputs[0].feature_context is not seat_port.inputs[0].feature_context
    assert eta_port.inputs[0].feature_context.weather.precipitation_mm is None
    assert eta_port.inputs[0].feature_context.traffic.speed_kph == 0.0
    assert seat_port.inputs[0].feature_context.weather.temperature_c is None


def test_future_optional_context_is_excluded_as_unknown_before_prediction() -> None:
    future_weather = WeatherFeatureContext(
        observed_at=EVALUATED + timedelta(seconds=1),
        schema_version=WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=20.0,
    )
    valid_traffic = TrafficFeatureContext(
        observed_at=EVALUATED,
        schema_version=TRAFFIC_CONTEXT_SCHEMA_VERSION,
        travel_time_seconds=120.0,
    )
    instance, eta_port, seat_port = engine(
        eta_values={"v1": eta(120, source="POSITION_MODEL")},
        seat_values={"v1": risk(0.1)},
    )

    instance.enrich(
        request(
            observation("v1", None),
            eta_feature_context=EtaFeatureContext(
                weather=future_weather,
                traffic=valid_traffic,
            ),
            seat_risk_feature_context=SeatRiskFeatureContext(
                weather=future_weather,
                missing_flags=("TRAFFIC_CONTEXT_MISSING",),
            ),
        )
    )

    eta_context = eta_port.inputs[0].feature_context
    seat_context = seat_port.inputs[0].feature_context
    assert eta_context.weather is None
    assert eta_context.traffic == valid_traffic
    assert eta_context.missing_flags == ("WEATHER_CONTEXT_FUTURE_EXCLUDED",)
    assert seat_context.weather is None
    assert seat_context.traffic is None
    assert seat_context.missing_flags == (
        "TRAFFIC_CONTEXT_MISSING",
        "WEATHER_CONTEXT_FUTURE_EXCLUDED",
    )


def test_context_schema_mismatch_reaches_fallback_ports_as_typed_missing() -> None:
    mismatched_weather = WeatherFeatureContext(
        observed_at=EVALUATED,
        schema_version="weather-context-v999",
        temperature_c=0.0,
    )
    mismatched_traffic = TrafficFeatureContext(
        observed_at=EVALUATED,
        schema_version="traffic-context-v999",
        speed_kph=0.0,
    )
    instance, eta_port, seat_port = engine(
        eta_values={"v1": eta(120, source="POSITION_MODEL")},
        seat_values={"v1": risk(0.1)},
    )

    result = instance.enrich(
        request(
            observation("v1", None),
            eta_feature_context=EtaFeatureContext(
                weather=mismatched_weather, traffic=mismatched_traffic
            ),
            seat_risk_feature_context=SeatRiskFeatureContext(
                weather=mismatched_weather, traffic=mismatched_traffic
            ),
        )
    )

    assert result.enrichment_applied
    eta_context = eta_port.inputs[0].feature_context
    seat_context = seat_port.inputs[0].feature_context
    assert eta_context.weather is None and eta_context.traffic is None
    assert seat_context.weather is None and seat_context.traffic is None
    expected = {
        "WEATHER_CONTEXT_SCHEMA_MISMATCH",
        "TRAFFIC_CONTEXT_SCHEMA_MISMATCH",
    }
    assert expected.issubset(eta_context.missing_flags)
    assert expected.issubset(seat_context.missing_flags)


def test_general_service_does_not_consume_seat_feature_context() -> None:
    context = SeatRiskFeatureContext(missing_flags=("ALL_OPTIONAL_CONTEXT_MISSING",))
    instance, _, seat_port = engine()

    result = instance.enrich(
        request(
            observation("v1", eta(120)),
            service_type="GENERAL",
            seat_risk_feature_context=context,
        )
    )

    assert result.enrichment_applied
    assert seat_port.inputs == []
    assert all(item.purpose != "SEAT_RISK" for item in result.model_provenance)


def test_high_grade_with_mapping_blocker_cannot_enrich() -> None:
    instance, eta_port, seat_port = engine()
    result = instance.enrich(
        request(observation("v1", eta(60)), grade="HIGH", mapping_allowed=False)
    )

    assert result.enrichment_applied is False
    assert result.warnings == ("BUS_MAPPING_LOW_CONFIDENCE",)
    assert eta_port.inputs == []
    assert seat_port.inputs == []


def test_official_eta_wins_without_calling_eta_predictor() -> None:
    instance, eta_port, _ = engine(
        eta_values={"v1": eta(999, source="POSITION_MODEL")},
        seat_values={"v1": risk(0.1)},
    )
    result = instance.enrich(request(observation("v1", eta(120))))

    assert result.candidate_vehicles[0].eta.source == "OFFICIAL"
    assert eta_port.inputs == []
    assert "ETA_MODEL_FALLBACK" not in result.warnings


def test_position_model_and_historical_eta_fallbacks_have_separate_provenance() -> None:
    instance, eta_port, _ = engine(
        eta_values={
            "model": eta(120, source="POSITION_MODEL"),
            "history": eta(240, source="HISTORICAL"),
        },
        seat_values={"model": risk(0.1), "history": risk(0.2)},
    )
    result = instance.enrich(
        request(observation("model", None), observation("history", None))
    )

    assert len(eta_port.inputs) == 2
    assert "ETA_MODEL_FALLBACK" in result.warnings
    assert "HISTORICAL_PROXY_USED" in result.warnings
    eta_origins = {
        item.origin for item in result.model_provenance if item.purpose == "BUS_ETA"
    }
    assert eta_origins == {"MODEL_PREDICTED", "HISTORICAL_PROXY"}


def test_future_target_absence_stays_none_unobserved_and_is_not_a_predictor_feature() -> None:
    instance, _, seat_port = engine(seat_values={"v1": risk(0.25)})
    result = instance.enrich(request(observation("v1", eta(120))))

    candidate = result.candidate_vehicles[0]
    assert candidate.future_target_remaining_seats is None
    assert candidate.future_target_observed is False
    predictor_input = seat_port.inputs[0]
    assert not hasattr(predictor_input, "future_target_remaining_seats")


def test_observed_future_zero_is_distinct_from_missing() -> None:
    missing = observation("missing", eta(120))
    zero = observation("zero", eta(240), future_target_remaining_seats=0)
    instance, _, _ = engine(seat_values={"missing": risk(0.2), "zero": risk(0.8)})
    result = instance.enrich(request(missing, zero))

    by_ref = {candidate.vehicle_ref: candidate for candidate in result.candidate_vehicles}
    assert by_ref["missing"].future_target_observed is False
    assert by_ref["missing"].future_target_remaining_seats is None
    assert by_ref["zero"].future_target_observed is True
    assert by_ref["zero"].future_target_remaining_seats == 0


def test_seated_bus_uses_disclosed_boardability_proxy() -> None:
    instance, _, _ = engine(seat_values={"v1": risk(0.8)})
    result = instance.enrich(request(observation("v1", eta(120))))

    assert result.candidate_vehicles[0].boardability_proxy == pytest.approx(0.2)
    assert "BOARDABILITY_IS_PROXY" in result.warnings


def test_general_bus_crowding_is_not_seat_failure() -> None:
    instance, _, seat_port = engine(seat_values={"v1": risk(0.99, confidence=0.0)})
    result = instance.enrich(
        request(observation("v1", eta(120)), service_type="GENERAL")
    )

    candidate = result.candidate_vehicles[0]
    assert candidate.seat_risk_at_boarding is None
    assert candidate.boardability_proxy is None
    assert result.expected_wait_seconds == 120
    assert result.p90_wait_seconds == 180
    assert seat_port.inputs == []
    assert all(item.purpose != "SEAT_RISK" for item in result.model_provenance)
    assert "BOARDABILITY_IS_PROXY" not in result.warnings


def test_first_bus_failure_probability_mass_reaches_second_bus() -> None:
    instance, _, _ = engine(
        seat_values={"v1": risk(0.9), "v2": risk(0.1)}, headway=900
    )
    result = instance.enrich(
        request(observation("v1", eta(120)), observation("v2", eta(900)))
    )

    # success masses: .1 at 120, .81 at 900, conservative tail .09 at 1860
    assert result.expected_wait_seconds == 909
    assert result.p90_wait_seconds == 960


def test_probability_tail_uses_conservative_headway_when_p90_not_reached() -> None:
    instance, _, _ = engine(
        seat_values={"v1": risk(0.95), "v2": risk(0.95)}, headway=1000
    )
    result = instance.enrich(
        request(observation("v1", eta(100)), observation("v2", eta(300)))
    )

    assert result.p90_wait_seconds == 1360


def test_heavy_tail_keeps_optimizer_p90_at_or_above_expected_wait() -> None:
    instance, _, _ = engine(seat_values={"v1": risk(0.09)}, headway=10_000)

    result = instance.enrich(request(observation("v1", eta(100))))

    assert result.expected_wait_seconds == 1006
    assert result.p90_wait_seconds == 1006


def test_all_unknown_seat_risk_makes_seated_enrichment_unavailable() -> None:
    instance, _, _ = engine(seat_values={"v1": None}, headway=900)
    result = instance.enrich(request(observation("v1", eta(100))))

    assert result.candidate_vehicles[0].boardability_proxy is None
    assert result.enrichment_applied is False
    assert result.expected_wait_seconds is None
    assert result.p90_wait_seconds is None
    assert result.coverage == "PARTIAL"
    assert "BUS_DATA_UNAVAILABLE" in result.warnings


def test_partial_seat_coverage_uses_known_mass_then_conservative_tail() -> None:
    instance, _, _ = engine(
        seat_values={"v1": risk(0.5), "v2": None}, headway=900
    )
    result = instance.enrich(
        request(observation("v1", eta(100)), observation("v2", eta(300)))
    )

    assert result.enrichment_applied is True
    assert result.expected_wait_seconds == 680
    assert result.p90_wait_seconds == 1260
    assert result.coverage == "PARTIAL"


def test_stale_data_reduces_coverage_and_warns() -> None:
    stale = EVALUATED - timedelta(seconds=181)
    instance, _, _ = engine(
        eta_values={"v1": eta(100, source="POSITION_MODEL")},
        seat_values={"v1": risk(0.1)},
    )
    result = instance.enrich(request(observation("v1", eta(100), observed_at=stale)))

    assert result.coverage == "PARTIAL"
    assert result.confidence_grade in {"LOW", "MEDIUM"}
    assert "DATA_STALE" in result.warnings


def test_missing_eta_returns_unavailable_not_zero_wait() -> None:
    instance, _, _ = engine(eta_values={"v1": None}, seat_values={"v1": risk(0.1)})
    result = instance.enrich(request(observation("v1", None)))

    assert not result.enrichment_applied
    assert result.expected_wait_seconds is None
    assert result.p90_wait_seconds is None
    assert result.warnings == ("BUS_DATA_UNAVAILABLE",)


def test_wait_changes_bus_leg_duration_and_ranking_input() -> None:
    instance, _, _ = engine(
        seat_values={"v1": risk(0.9), "v2": risk(0.1)}, headway=900
    )
    result = instance.enrich(
        request(observation("v1", eta(120)), observation("v2", eta(900)))
    )

    raw_bus_p50 = 600
    alternative_route_p50 = 1_000
    enriched = apply_bus_intelligence_wait(raw_bus_p50, 700, result)

    assert raw_bus_p50 < alternative_route_p50
    assert enriched.p50_seconds == 1_509
    assert enriched.p50_seconds > alternative_route_p50
    assert enriched.p90_seconds >= enriched.p50_seconds


def test_unavailable_enrichment_cannot_be_applied_as_zero_wait() -> None:
    instance, _, _ = engine()
    unavailable = instance.enrich(
        request(observation("v1", eta(100)), grade="LOW")
    )
    with pytest.raises(ValueError, match="zero wait"):
        apply_bus_intelligence_wait(600, 700, unavailable)


def test_domain_values_are_immutable() -> None:
    value = risk(0.5)
    with pytest.raises(FrozenInstanceError):
        value.confidence = 0.1  # type: ignore[misc]


def test_mutable_warning_input_is_coerced_to_tuple() -> None:
    mutable_warnings = ["FEATURE_OUT_OF_DISTRIBUTION"]
    value = EtaPrediction(
        p50_arrival_at=ARRIVAL,
        p90_arrival_at=ARRIVAL,
        source="OFFICIAL",
        warnings=mutable_warnings,  # type: ignore[arg-type]
    )
    mutable_warnings.append("DATA_STALE")
    assert value.warnings == ("FEATURE_OUT_OF_DISTRIBUTION",)


def test_probability_order_is_validated() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        SeatRiskPrediction(
            no_seat_probability=0.7,
            low_seat2_probability=0.6,
            low_seat5_probability=None,
            model_version="fixture",
            confidence=0.8,
        )
