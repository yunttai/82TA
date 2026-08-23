from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bus_intelligence_core import (
    BusIntelligenceEngine,
    BusIntelligenceRequest,
    CalibratedSeatRiskPredictor,
    EnginePolicy,
    EtaFallbackChain,
    EtaPrediction,
    GuardedEtaPredictor,
    IdentityProbabilityCalibrator,
    RawSeatRiskScore,
    RuntimeModelSpec,
    SeatRiskPrediction,
    VehicleObservation,
)
from bus_intelligence_core.ports import SeatRiskPredictorInput


UTC = timezone.utc
ARRIVAL = datetime(2026, 8, 23, 8, 0, tzinfo=UTC)
EVALUATED = ARRIVAL - timedelta(seconds=30)


class RecordingEta:
    def __init__(self, prediction: EtaPrediction | None) -> None:
        self.prediction = prediction
        self.inputs = []

    def predict(self, value):
        self.inputs.append(value)
        return self.prediction


class RecordingSeat:
    def __init__(self, prediction: SeatRiskPrediction | None) -> None:
        self.prediction = prediction
        self.inputs = []

    def predict(self, value):
        self.inputs.append(value)
        return self.prediction


class RecordingScorer:
    def __init__(self, score: RawSeatRiskScore | None) -> None:
        self.value = score
        self.inputs = []

    def score(self, value):
        self.inputs.append(value)
        return self.value


def eta_prediction(seconds: int, source: str, version: str) -> EtaPrediction:
    return EtaPrediction(
        p50_arrival_at=ARRIVAL + timedelta(seconds=seconds),
        p90_arrival_at=ARRIVAL + timedelta(seconds=seconds + 60),
        source=source,
        model_version=version,
        confidence=0.85,
        model_readiness="UNVERIFIED",
    )


def seat_prediction(
    no_seat: float,
    *,
    version: str = "seat-historical-v1",
    origin: str = "HISTORICAL_PROXY",
    readiness: str = "ACTIVE",
) -> SeatRiskPrediction:
    return SeatRiskPrediction(
        no_seat_probability=no_seat,
        low_seat2_probability=min(1.0, no_seat + 0.05),
        low_seat5_probability=min(1.0, no_seat + 0.10),
        model_version=version,
        confidence=0.65,
        origin=origin,
        model_readiness=readiness,
    )


def active_spec(
    purpose: str,
    version: str,
    schema: str,
    *,
    calibrated: bool = False,
) -> RuntimeModelSpec:
    return RuntimeModelSpec(
        purpose=purpose,
        version=version,
        readiness="ACTIVE",
        feature_schema_version=schema,
        calibrated=calibrated,
    )


def request(
    observation: VehicleObservation,
    *,
    service_type: str = "SEATED",
) -> BusIntelligenceRequest:
    return BusIntelligenceRequest(
        mapping_grade="HIGH",
        mapping_allows_bus_intelligence=True,
        mapping_score=0.98,
        mapping_version="0.1.0-planned",
        user_arrival_at=ARRIVAL,
        evaluated_at=EVALUATED,
        target_stop_id="target",
        service_type=service_type,
        observations=(observation,),
    )


def observation(
    *,
    official: EtaPrediction | None,
    observed_at: datetime = EVALUATED,
    future_target_remaining_seats: int | None = None,
) -> VehicleObservation:
    return VehicleObservation(
        vehicle_ref="vehicle-1",
        route_id="route-1",
        direction="OUTBOUND",
        boarding_stop_id="board",
        observed_at=observed_at,
        official_eta=official,
        remain_seat_observed=5,
        future_target_remaining_seats=future_target_remaining_seats,
    )


def guarded_eta(
    predictor: RecordingEta,
    *,
    spec: RuntimeModelSpec,
    source: str,
    max_age: int | None,
    serving_schema: str = "eta-schema-v2",
) -> GuardedEtaPredictor:
    return GuardedEtaPredictor(
        predictor,
        spec,
        serving_feature_schema_version=serving_schema,
        required_source=source,
        max_input_age_seconds=max_age,
    )


def calibrated_seat(
    scorer: RecordingScorer,
    *,
    spec: RuntimeModelSpec | None = None,
    serving_schema: str = "seat-schema-v2",
    fallback: RecordingSeat | None = None,
) -> CalibratedSeatRiskPredictor:
    calibrator = IdentityProbabilityCalibrator()
    return CalibratedSeatRiskPredictor(
        scorer,
        spec
        or active_spec(
            "SEAT_RISK", "seat-active-v2", "seat-schema-v2", calibrated=True
        ),
        serving_feature_schema_version=serving_schema,
        no_seat_calibrator=calibrator,
        low_seat2_calibrator=calibrator,
        low_seat5_calibrator=calibrator,
        fallback=fallback,
    )


def test_eta_runtime_uses_position_model_before_historical() -> None:
    position_raw = RecordingEta(eta_prediction(120, "POSITION_MODEL", "eta-position-v2"))
    historical_raw = RecordingEta(eta_prediction(300, "HISTORICAL", "eta-history-v1"))
    eta_runtime = EtaFallbackChain(
        guarded_eta(
            position_raw,
            spec=active_spec("BUS_ETA", "eta-position-v2", "eta-schema-v2"),
            source="POSITION_MODEL",
            max_age=180,
        ),
        guarded_eta(
            historical_raw,
            spec=active_spec("BUS_ETA", "eta-history-v1", "eta-schema-v2"),
            source="HISTORICAL",
            max_age=None,
        ),
    )
    result = BusIntelligenceEngine(
        eta_runtime, RecordingSeat(seat_prediction(0.2))
    ).enrich(request(observation(official=None)))

    assert result.candidate_vehicles[0].eta.source == "POSITION_MODEL"
    assert len(position_raw.inputs) == 1
    assert historical_raw.inputs == []
    assert "ETA_MODEL_FALLBACK" in result.warnings
    assert {(item.purpose, item.readiness) for item in result.model_provenance} == {
        ("BUS_ETA", "ACTIVE"),
        ("SEAT_RISK", "ACTIVE"),
    }


def test_unready_position_model_falls_back_to_historical() -> None:
    position_raw = RecordingEta(eta_prediction(120, "POSITION_MODEL", "eta-position-v2"))
    historical_raw = RecordingEta(eta_prediction(300, "HISTORICAL", "eta-history-v1"))
    unready = RuntimeModelSpec(
        purpose="BUS_ETA",
        version="eta-position-v2",
        readiness="VALIDATED",
        feature_schema_version="eta-schema-v2",
    )
    runtime = EtaFallbackChain(
        guarded_eta(position_raw, spec=unready, source="POSITION_MODEL", max_age=180),
        guarded_eta(
            historical_raw,
            spec=active_spec("BUS_ETA", "eta-history-v1", "eta-schema-v2"),
            source="HISTORICAL",
            max_age=None,
        ),
    )
    result = BusIntelligenceEngine(runtime, RecordingSeat(seat_prediction(0.2))).enrich(
        request(observation(official=None))
    )

    assert position_raw.inputs == []
    assert len(historical_raw.inputs) == 1
    assert result.candidate_vehicles[0].eta.source == "HISTORICAL"
    assert result.coverage == "HISTORICAL"
    assert "HISTORICAL_PROXY_USED" in result.warnings


def test_ood_position_model_falls_back_to_historical_and_warns() -> None:
    ood_position = eta_prediction(120, "POSITION_MODEL", "eta-position-v2")
    ood_position = EtaPrediction(
        p50_arrival_at=ood_position.p50_arrival_at,
        p90_arrival_at=ood_position.p90_arrival_at,
        source=ood_position.source,
        model_version=ood_position.model_version,
        confidence=ood_position.confidence,
        warnings=("FEATURE_OUT_OF_DISTRIBUTION",),
    )
    position_raw = RecordingEta(ood_position)
    historical_raw = RecordingEta(eta_prediction(300, "HISTORICAL", "eta-history-v1"))
    runtime = EtaFallbackChain(
        guarded_eta(
            position_raw,
            spec=active_spec("BUS_ETA", "eta-position-v2", "eta-schema-v2"),
            source="POSITION_MODEL",
            max_age=180,
        ),
        guarded_eta(
            historical_raw,
            spec=active_spec("BUS_ETA", "eta-history-v1", "eta-schema-v2"),
            source="HISTORICAL",
            max_age=None,
        ),
    )
    result = BusIntelligenceEngine(runtime, RecordingSeat(seat_prediction(0.2))).enrich(
        request(observation(official=None))
    )

    assert result.candidate_vehicles[0].eta.source == "HISTORICAL"
    assert "FEATURE_OUT_OF_DISTRIBUTION" in result.warnings
    assert "HISTORICAL_PROXY_USED" in result.warnings


def test_stale_official_and_position_input_fall_back_to_historical() -> None:
    position_raw = RecordingEta(eta_prediction(120, "POSITION_MODEL", "eta-position-v2"))
    historical_raw = RecordingEta(eta_prediction(300, "HISTORICAL", "eta-history-v1"))
    runtime = EtaFallbackChain(
        guarded_eta(
            position_raw,
            spec=active_spec("BUS_ETA", "eta-position-v2", "eta-schema-v2"),
            source="POSITION_MODEL",
            max_age=180,
        ),
        guarded_eta(
            historical_raw,
            spec=active_spec("BUS_ETA", "eta-history-v1", "eta-schema-v2"),
            source="HISTORICAL",
            max_age=None,
        ),
    )
    stale_observed_at = EVALUATED - timedelta(seconds=181)
    result = BusIntelligenceEngine(
        runtime,
        RecordingSeat(seat_prediction(0.2)),
        EnginePolicy(stale_after_seconds=180),
    ).enrich(request(observation(official=EtaPrediction(ARRIVAL + timedelta(seconds=60), ARRIVAL + timedelta(seconds=120), "OFFICIAL"), observed_at=stale_observed_at)))

    assert position_raw.inputs == []
    assert len(historical_raw.inputs) == 1
    assert result.candidate_vehicles[0].eta.source == "HISTORICAL"
    assert result.coverage == "HISTORICAL"
    assert {"DATA_STALE", "HISTORICAL_PROXY_USED"}.issubset(result.warnings)


def test_fresh_official_eta_short_circuits_runtime_models() -> None:
    position_raw = RecordingEta(eta_prediction(120, "POSITION_MODEL", "eta-position-v2"))
    historical_raw = RecordingEta(eta_prediction(300, "HISTORICAL", "eta-history-v1"))
    runtime = EtaFallbackChain(
        guarded_eta(
            position_raw,
            spec=active_spec("BUS_ETA", "eta-position-v2", "eta-schema-v2"),
            source="POSITION_MODEL",
            max_age=180,
        ),
        guarded_eta(
            historical_raw,
            spec=active_spec("BUS_ETA", "eta-history-v1", "eta-schema-v2"),
            source="HISTORICAL",
            max_age=None,
        ),
    )
    official = EtaPrediction(
        ARRIVAL + timedelta(seconds=60), ARRIVAL + timedelta(seconds=120), "OFFICIAL"
    )
    result = BusIntelligenceEngine(runtime, RecordingSeat(seat_prediction(0.2))).enrich(
        request(observation(official=official))
    )

    assert result.candidate_vehicles[0].eta.source == "OFFICIAL"
    assert position_raw.inputs == []
    assert historical_raw.inputs == []
    assert all(item.purpose != "BUS_ETA" for item in result.model_provenance)


def test_eta_chain_reaches_unknown_when_no_fallback_can_serve() -> None:
    position_raw = RecordingEta(None)
    historical_raw = RecordingEta(None)
    runtime = EtaFallbackChain(
        guarded_eta(
            position_raw,
            spec=active_spec("BUS_ETA", "eta-position-v2", "eta-schema-v2"),
            source="POSITION_MODEL",
            max_age=180,
        ),
        guarded_eta(
            historical_raw,
            spec=active_spec("BUS_ETA", "eta-history-v1", "eta-schema-v2"),
            source="HISTORICAL",
            max_age=None,
        ),
    )
    result = BusIntelligenceEngine(runtime, RecordingSeat(seat_prediction(0.2))).enrich(
        request(observation(official=None))
    )

    assert result.enrichment_applied is False
    assert result.expected_wait_seconds is None
    assert result.p90_wait_seconds is None
    assert result.coverage == "UNKNOWN"
    assert result.warnings == ("BUS_DATA_UNAVAILABLE",)


def test_calibrated_seat_runtime_enforces_ordered_probabilities() -> None:
    scorer = RecordingScorer(
        RawSeatRiskScore(
            no_seat_score=0.7,
            low_seat2_score=0.3,
            low_seat5_score=0.2,
            confidence=0.8,
        )
    )
    prediction = calibrated_seat(scorer).predict(
        # Constructed by engine in production; direct use verifies wrapper output.
        SeatRiskPredictorInput(
            vehicle_ref="v",
            route_id="r",
            direction="OUTBOUND",
            boarding_stop_id="b",
            target_stop_id="t",
            observed_at=EVALUATED,
            prediction_at=EVALUATED,
            remain_seat_observed=5,
        )
    )

    assert prediction is not None
    assert prediction.no_seat_probability == pytest.approx(0.7)
    assert prediction.low_seat2_probability == pytest.approx(0.7)
    assert prediction.low_seat5_probability == pytest.approx(0.7)
    assert prediction.model_readiness == "ACTIVE"


def test_seat_schema_mismatch_uses_historical_fallback_without_scoring() -> None:
    scorer = RecordingScorer(RawSeatRiskScore(0.2, 0.3, 0.4, 0.9))
    fallback = RecordingSeat(seat_prediction(0.4))
    runtime = calibrated_seat(scorer, serving_schema="seat-schema-v3", fallback=fallback)
    engine = BusIntelligenceEngine(RecordingEta(None), runtime)
    result = engine.enrich(
        request(
            observation(
                official=EtaPrediction(
                    ARRIVAL + timedelta(seconds=100),
                    ARRIVAL + timedelta(seconds=160),
                    "OFFICIAL",
                )
            )
        )
    )

    assert scorer.inputs == []
    assert len(fallback.inputs) == 1
    seat = result.candidate_vehicles[0].seat_risk_at_boarding
    assert seat is not None and seat.origin == "HISTORICAL_PROXY"
    assert "HISTORICAL_PROXY_USED" in result.warnings


def test_seat_ood_uses_fallback_and_preserves_warning() -> None:
    scorer = RecordingScorer(RawSeatRiskScore(0.2, 0.3, 0.4, 0.9, True))
    fallback = RecordingSeat(seat_prediction(0.45))
    runtime = calibrated_seat(scorer, fallback=fallback)
    result = BusIntelligenceEngine(RecordingEta(None), runtime).enrich(
        request(
            observation(
                official=EtaPrediction(
                    ARRIVAL + timedelta(seconds=100),
                    ARRIVAL + timedelta(seconds=160),
                    "OFFICIAL",
                )
            )
        )
    )

    assert len(scorer.inputs) == 1
    assert len(fallback.inputs) == 1
    assert "FEATURE_OUT_OF_DISTRIBUTION" in result.warnings
    assert "HISTORICAL_PROXY_USED" in result.warnings


def test_unready_seat_model_without_fallback_is_unavailable() -> None:
    scorer = RecordingScorer(RawSeatRiskScore(0.2, 0.3, 0.4, 0.9))
    unready = RuntimeModelSpec(
        purpose="SEAT_RISK",
        version="seat-v2",
        readiness="SHADOW",
        feature_schema_version="seat-schema-v2",
        calibrated=True,
    )
    runtime = calibrated_seat(scorer, spec=unready)
    result = BusIntelligenceEngine(RecordingEta(None), runtime).enrich(
        request(
            observation(
                official=EtaPrediction(
                    ARRIVAL + timedelta(seconds=100),
                    ARRIVAL + timedelta(seconds=160),
                    "OFFICIAL",
                )
            )
        )
    )

    assert scorer.inputs == []
    assert result.enrichment_applied is False
    assert result.expected_wait_seconds is None
    assert result.p90_wait_seconds is None
    assert "BUS_DATA_UNAVAILABLE" in result.warnings


def test_fixture_runtime_requires_explicit_opt_in() -> None:
    disabled = RuntimeModelSpec(
        purpose="BUS_ETA",
        version="fixture-v1",
        readiness="FIXTURE_ONLY",
        feature_schema_version="eta-schema-v2",
    )
    enabled = RuntimeModelSpec(
        purpose="BUS_ETA",
        version="fixture-v1",
        readiness="FIXTURE_ONLY",
        feature_schema_version="eta-schema-v2",
        allow_fixture_only=True,
    )
    assert disabled.can_serve("eta-schema-v2") is False
    assert enabled.can_serve("eta-schema-v2") is True


def test_future_target_outcome_never_enters_online_seat_features() -> None:
    scorer = RecordingScorer(RawSeatRiskScore(0.2, 0.3, 0.4, 0.9))
    runtime = calibrated_seat(scorer)
    result = BusIntelligenceEngine(RecordingEta(None), runtime).enrich(
        request(
            observation(
                official=EtaPrediction(
                    ARRIVAL + timedelta(seconds=100),
                    ARRIVAL + timedelta(seconds=160),
                    "OFFICIAL",
                ),
                future_target_remaining_seats=0,
            )
        )
    )

    assert result.candidate_vehicles[0].future_target_remaining_seats == 0
    assert result.candidate_vehicles[0].future_target_observed is True
    assert not hasattr(scorer.inputs[0], "future_target_remaining_seats")
