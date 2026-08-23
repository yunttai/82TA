from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bus_intelligence_core import (
    CalibratedSeatRiskPredictor,
    EtaCompleteFeatureVector,
    EtaNativePrediction,
    EtaPrediction,
    EtaPredictorInput,
    GuardedEtaPredictor,
    IdentityProbabilityCalibrator,
    RuntimeModelSpec,
    SeatRiskCompleteFeatureVector,
    SeatRiskNativePrediction,
    SeatRiskPrediction,
    SeatRiskPredictorInput,
    VerifiedEtaPredictor,
    VerifiedEtaPredictorAttestation,
    VerifiedPredictorConfigurationError,
    VerifiedSeatRiskPredictor,
    VerifiedSeatRiskPredictorAttestation,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
ETA_SCHEMA = "eta-feature-foundation-v3"
SEAT_SCHEMA = "seat-risk-feature-foundation-v3"
ETA_NAMES = ("route_id", "missing_flags")
SEAT_NAMES = ("current_remaining_seats", "missing_flags")
ARTIFACT_SHA = "a" * 64
CALIBRATION_SHA = "b" * 64


def eta_vector() -> EtaCompleteFeatureVector:
    return EtaCompleteFeatureVector(ETA_SCHEMA, ETA_NAMES, ("route-1", ""), ())


def seat_vector() -> SeatRiskCompleteFeatureVector:
    return SeatRiskCompleteFeatureVector(SEAT_SCHEMA, SEAT_NAMES, (0, ""), ())


class EtaBuilder:
    family = "ETA"
    feature_schema_version = ETA_SCHEMA
    feature_names = ETA_NAMES

    def __init__(self, vector: object = None) -> None:
        self.vector = eta_vector() if vector is None else vector
        self.inputs = []

    def build(self, value):
        self.inputs.append(value)
        return self.vector


class SeatBuilder:
    family = "SEAT_RISK"
    feature_schema_version = SEAT_SCHEMA
    feature_names = SEAT_NAMES

    def __init__(self, vector: object = None) -> None:
        self.vector = seat_vector() if vector is None else vector
        self.inputs = []

    def build(self, value):
        self.inputs.append(value)
        return self.vector


class EtaRuntime:
    family = "ETA"
    model_version = "eta-model-v3"
    artifact_sha256 = ARTIFACT_SHA
    artifact_format = "LIGHTGBM_TEXT"
    calibration_sha256 = CALIBRATION_SHA

    def __init__(self, output: object = None, *, raises: bool = False) -> None:
        self.output = output or EtaNativePrediction(
            120,
            180,
            0.82,
        )
        self.raises = raises
        self.inputs = []

    def predict(self, value):
        self.inputs.append(value)
        if self.raises:
            raise RuntimeError("native runtime failed")
        return self.output


class SeatRuntime:
    family = "SEAT_RISK"
    model_version = "seat-model-v3"
    artifact_sha256 = ARTIFACT_SHA
    artifact_format = "LIGHTGBM_JSON"
    calibration_sha256 = CALIBRATION_SHA

    def __init__(self, output: object = None, *, raises: bool = False) -> None:
        self.output = output or SeatRiskNativePrediction(0.1, 0.2, 0.3, 0.84)
        self.raises = raises
        self.inputs = []

    def predict(self, value):
        self.inputs.append(value)
        if self.raises:
            raise RuntimeError("native runtime failed")
        return self.output


def eta_attestation(**changes) -> VerifiedEtaPredictorAttestation:
    values = {
        "family": "ETA",
        "model_version": "eta-model-v3",
        "full_feature_schema_version": ETA_SCHEMA,
        "ordered_feature_names": ETA_NAMES,
        "artifact_sha256": ARTIFACT_SHA,
        "verified_artifact_sha256": ARTIFACT_SHA,
        "artifact_format": "LIGHTGBM_TEXT",
        "deployment_id": "eta-prod-deployment-v3",
        "deployment_environment": "prod",
        "deployment_state": "ACTIVE",
        "readiness": "ACTIVE",
        "calibrated": True,
        "calibration_method": "CONFORMAL",
        "calibration_sha256": CALIBRATION_SHA,
        "verified_calibration_sha256": CALIBRATION_SHA,
        "source": "POSITION_MODEL",
    }
    values.update(changes)
    return VerifiedEtaPredictorAttestation(**values)


def seat_attestation(**changes) -> VerifiedSeatRiskPredictorAttestation:
    values = {
        "family": "SEAT_RISK",
        "model_version": "seat-model-v3",
        "full_feature_schema_version": SEAT_SCHEMA,
        "ordered_feature_names": SEAT_NAMES,
        "artifact_sha256": ARTIFACT_SHA,
        "verified_artifact_sha256": ARTIFACT_SHA,
        "artifact_format": "LIGHTGBM_JSON",
        "deployment_id": "seat-prod-deployment-v3",
        "deployment_environment": "prod",
        "deployment_state": "ACTIVE",
        "readiness": "ACTIVE",
        "calibrated": True,
        "calibration_method": "ISOTONIC",
        "calibration_sha256": CALIBRATION_SHA,
        "verified_calibration_sha256": CALIBRATION_SHA,
        "origin": "MODEL_PREDICTED",
    }
    values.update(changes)
    return VerifiedSeatRiskPredictorAttestation(**values)


def eta_input() -> EtaPredictorInput:
    return EtaPredictorInput(
        vehicle_ref="vehicle-1",
        route_id="route-1",
        direction="OUTBOUND",
        boarding_stop_id="board",
        observed_at=NOW - timedelta(seconds=30),
        remain_seat_observed=0,
        prediction_at=NOW,
    )


def seat_input() -> SeatRiskPredictorInput:
    return SeatRiskPredictorInput(
        vehicle_ref="vehicle-1",
        route_id="route-1",
        direction="OUTBOUND",
        boarding_stop_id="board",
        target_stop_id="target",
        observed_at=NOW - timedelta(seconds=30),
        prediction_at=NOW,
        remain_seat_observed=0,
    )


def verified_eta(builder=None, runtime=None, attestation=None) -> VerifiedEtaPredictor:
    return VerifiedEtaPredictor(
        builder or EtaBuilder(),
        runtime or EtaRuntime(),
        attestation or eta_attestation(),
        expected_feature_schema_version=ETA_SCHEMA,
        expected_feature_names=ETA_NAMES,
        required_environment="prod",
    )


def verified_seat(
    builder=None, runtime=None, attestation=None
) -> VerifiedSeatRiskPredictor:
    return VerifiedSeatRiskPredictor(
        builder or SeatBuilder(),
        runtime or SeatRuntime(),
        attestation or seat_attestation(),
        expected_feature_schema_version=SEAT_SCHEMA,
        expected_feature_names=SEAT_NAMES,
        required_environment="prod",
    )


def test_verified_eta_rechecks_vector_then_sets_attested_provenance() -> None:
    builder = EtaBuilder()
    runtime = EtaRuntime()
    predictor = verified_eta(builder, runtime)

    prediction = predictor.predict(eta_input())

    assert isinstance(prediction, EtaPrediction)
    assert prediction.source == "POSITION_MODEL"
    assert prediction.model_version == "eta-model-v3"
    assert prediction.model_readiness == "ACTIVE"
    assert prediction.p50_arrival_at == NOW + timedelta(seconds=120)
    assert prediction.p90_arrival_at == NOW + timedelta(seconds=180)
    assert runtime.inputs == [builder.vector]
    assert len(builder.inputs) == 1
    assert len(builder.vector.identity_sha256) == 64


def test_verified_seat_preserves_observed_zero_and_attested_provenance() -> None:
    builder = SeatBuilder()
    runtime = SeatRuntime()
    predictor = verified_seat(builder, runtime)

    prediction = predictor.predict(seat_input())

    assert isinstance(prediction, SeatRiskPrediction)
    assert prediction.model_version == "seat-model-v3"
    assert prediction.origin == "MODEL_PREDICTED"
    assert prediction.model_readiness == "ACTIVE"
    assert runtime.inputs[0].values[0] == 0


def test_family_swap_is_rejected_before_prediction() -> None:
    with pytest.raises(VerifiedPredictorConfigurationError, match="type mismatch"):
        VerifiedEtaPredictor(
            EtaBuilder(),
            EtaRuntime(),
            seat_attestation(),
            expected_feature_schema_version=ETA_SCHEMA,
            expected_feature_names=ETA_NAMES,
            required_environment="prod",
        )


@pytest.mark.parametrize(
    ("predictor", "wrong_input", "builder", "runtime"),
    [
        ("ETA", object(), EtaBuilder(), EtaRuntime()),
        ("ETA", seat_input(), EtaBuilder(), EtaRuntime()),
        ("SEAT_RISK", object(), SeatBuilder(), SeatRuntime()),
        ("SEAT_RISK", eta_input(), SeatBuilder(), SeatRuntime()),
    ],
)
def test_verified_wrapper_rejects_arbitrary_or_wrong_family_input_before_work(
    predictor: str, wrong_input: object, builder: object, runtime: object
) -> None:
    instance = (
        verified_eta(builder, runtime)
        if predictor == "ETA"
        else verified_seat(builder, runtime)
    )

    assert instance.predict(wrong_input) is None
    assert builder.inputs == []
    assert runtime.inputs == []


@pytest.mark.parametrize(
    "changes",
    [
        {"family": "SEAT_RISK"},
        {"artifact_format": "PICKLE"},
        {"verified_artifact_sha256": "c" * 64},
        {"deployment_environment": "dev"},
        {"deployment_state": "CANARY"},
        {"readiness": "SHADOW"},
        {"calibrated": False},
        {"calibration_method": "NONE"},
        {"verified_calibration_sha256": "d" * 64},
    ],
)
def test_eta_attestation_fails_closed_on_unverified_or_inactive_state(changes) -> None:
    with pytest.raises(VerifiedPredictorConfigurationError):
        eta_attestation(**changes)


@pytest.mark.parametrize(
    ("expected_schema", "expected_names"),
    [
        ("eta-feature-foundation-v4", ETA_NAMES),
        (ETA_SCHEMA, ("direction", "missing_flags")),
        (ETA_SCHEMA, tuple(reversed(ETA_NAMES))),
    ],
)
def test_constructor_rejects_expected_version_name_or_order_drift(
    expected_schema, expected_names
) -> None:
    with pytest.raises(VerifiedPredictorConfigurationError):
        VerifiedEtaPredictor(
            EtaBuilder(),
            EtaRuntime(),
            eta_attestation(),
            expected_feature_schema_version=expected_schema,
            expected_feature_names=expected_names,
            required_environment="prod",
        )


def test_constructor_rejects_builder_and_runtime_identity_drift() -> None:
    builder = EtaBuilder()
    builder.feature_schema_version = "eta-feature-foundation-v4"
    with pytest.raises(VerifiedPredictorConfigurationError, match="builder"):
        verified_eta(builder=builder)

    runtime = EtaRuntime()
    runtime.artifact_sha256 = "c" * 64
    with pytest.raises(VerifiedPredictorConfigurationError, match="runtime"):
        verified_eta(runtime=runtime)


@pytest.mark.parametrize(
    ("field_name", "drifted_value"),
    [
        ("family", "SEAT_RISK"),
        ("feature_schema_version", "eta-feature-foundation-v4"),
        ("feature_names", ("direction", "missing_flags")),
    ],
)
def test_prediction_revalidates_mutated_builder_identity_before_build(
    field_name: str, drifted_value: object
) -> None:
    builder = EtaBuilder()
    runtime = EtaRuntime()
    predictor = verified_eta(builder, runtime)
    setattr(builder, field_name, drifted_value)

    assert predictor.predict(eta_input()) is None
    assert builder.inputs == []
    assert runtime.inputs == []


@pytest.mark.parametrize(
    ("field_name", "drifted_value"),
    [
        ("family", "SEAT_RISK"),
        ("model_version", "eta-model-v4"),
        ("artifact_sha256", "c" * 64),
        ("artifact_format", "LIGHTGBM_JSON"),
        ("calibration_sha256", "d" * 64),
    ],
)
def test_prediction_revalidates_mutated_runtime_identity_before_build(
    field_name: str, drifted_value: object
) -> None:
    builder = EtaBuilder()
    runtime = EtaRuntime()
    predictor = verified_eta(builder, runtime)
    setattr(runtime, field_name, drifted_value)

    assert predictor.predict(eta_input()) is None
    assert builder.inputs == []
    assert runtime.inputs == []


def test_verified_seat_also_revalidates_mutable_component_identity_per_call() -> None:
    builder = SeatBuilder()
    runtime = SeatRuntime()
    predictor = verified_seat(builder, runtime)
    runtime.calibration_sha256 = "d" * 64

    assert predictor.predict(seat_input()) is None
    assert builder.inputs == []
    assert runtime.inputs == []


@pytest.mark.parametrize(
    "drift", ["VERSION", "ORDER", "FAMILY", "IDENTITY", "MALFORMED"]
)
def test_prediction_rejects_builder_drift_before_runtime(drift: str) -> None:
    builder = EtaBuilder()
    runtime = EtaRuntime()
    predictor = verified_eta(builder, runtime)
    if drift == "VERSION":
        builder.vector = EtaCompleteFeatureVector(
            "eta-feature-foundation-v4", ETA_NAMES, ("route-1", ""), ()
        )
    elif drift == "ORDER":
        builder.vector = EtaCompleteFeatureVector(
            ETA_SCHEMA, ("direction", "missing_flags"), ("OUTBOUND", ""), ()
        )
    elif drift == "FAMILY":
        builder.vector = seat_vector()
    elif drift == "IDENTITY":
        object.__setattr__(builder.vector, "identity_sha256", "0" * 64)
    else:
        builder.vector = object.__new__(EtaCompleteFeatureVector)

    assert predictor.predict(eta_input()) is None
    assert runtime.inputs == []


@pytest.mark.parametrize(
    "invalid", [object(), "NON_FINITE", "NEGATIVE", "OOD", "MALFORMED"]
)
def test_verified_eta_rejects_invalid_native_output_without_raising(invalid) -> None:
    if invalid == "NON_FINITE":
        output = object.__new__(EtaNativePrediction)
        object.__setattr__(output, "p50_seconds", 60)
        object.__setattr__(output, "p90_seconds", 90)
        object.__setattr__(output, "confidence", float("nan"))
        object.__setattr__(output, "out_of_distribution", False)
    elif invalid == "NEGATIVE":
        output = object.__new__(EtaNativePrediction)
        object.__setattr__(output, "p50_seconds", -1)
        object.__setattr__(output, "p90_seconds", 1)
        object.__setattr__(output, "confidence", 0.8)
        object.__setattr__(output, "out_of_distribution", False)
    elif invalid == "OOD":
        output = EtaNativePrediction(
            60,
            90,
            0.8,
            out_of_distribution=True,
        )
    elif invalid == "MALFORMED":
        output = object.__new__(EtaNativePrediction)
    else:
        output = invalid

    assert verified_eta(runtime=EtaRuntime(output)).predict(eta_input()) is None


def test_verified_wrappers_contain_native_runtime_exceptions() -> None:
    assert verified_eta(runtime=EtaRuntime(raises=True)).predict(eta_input()) is None
    assert verified_seat(runtime=SeatRuntime(raises=True)).predict(seat_input()) is None


def test_verified_seat_rejects_non_finite_runtime_output() -> None:
    output = object.__new__(SeatRiskNativePrediction)
    object.__setattr__(output, "no_seat_probability", float("nan"))
    object.__setattr__(output, "low_seat2_probability", 0.2)
    object.__setattr__(output, "low_seat5_probability", 0.3)
    object.__setattr__(output, "confidence", 0.8)
    object.__setattr__(output, "out_of_distribution", False)

    assert verified_seat(runtime=SeatRuntime(output)).predict(seat_input()) is None


def test_native_runtime_output_rejects_boolean_as_probability() -> None:
    with pytest.raises(ValueError, match="numeric probability"):
        EtaNativePrediction(60, 90, True)
    with pytest.raises(ValueError, match="numeric probability"):
        SeatRiskNativePrediction(False, 0.2, 0.3, 0.8)


@pytest.mark.parametrize(
    ("p50_seconds", "p90_seconds"),
    [(True, 90), (60.0, 90), (-1, 90), (90, 60)],
)
def test_native_eta_duration_rejects_bool_non_integer_negative_and_order(
    p50_seconds: object, p90_seconds: object
) -> None:
    with pytest.raises(ValueError):
        EtaNativePrediction(p50_seconds, p90_seconds, 0.8)


@pytest.mark.parametrize(
    "prediction_at", [None, NOW.replace(tzinfo=None)]
)
def test_verified_eta_requires_aware_prediction_time_before_builder(
    prediction_at: datetime | None,
) -> None:
    builder = EtaBuilder()
    runtime = EtaRuntime()
    predictor = verified_eta(builder, runtime)

    assert predictor.predict(replace(eta_input(), prediction_at=prediction_at)) is None
    assert builder.inputs == []
    assert runtime.inputs == []


def test_verified_seat_requires_aware_prediction_time_before_builder() -> None:
    builder = SeatBuilder()
    runtime = SeatRuntime()
    predictor = verified_seat(builder, runtime)

    assert predictor.predict(
        replace(seat_input(), prediction_at=NOW.replace(tzinfo=None))
    ) is None
    assert builder.inputs == []
    assert runtime.inputs == []


def test_complete_vector_rejects_non_finite_and_missing_flag_value_drift() -> None:
    with pytest.raises(ValueError, match="finite"):
        EtaCompleteFeatureVector(
            ETA_SCHEMA, ETA_NAMES, (float("nan"), ""), ()
        )
    with pytest.raises(ValueError, match="does not match"):
        EtaCompleteFeatureVector(
            ETA_SCHEMA, ETA_NAMES, (None, ""), ("route_id",)
        )


def test_verified_eta_remains_compatible_with_existing_guard() -> None:
    verified = verified_eta()
    guarded = GuardedEtaPredictor(
        verified,
        RuntimeModelSpec(
            purpose="BUS_ETA",
            version="eta-model-v3",
            readiness="ACTIVE",
            feature_schema_version=ETA_SCHEMA,
            calibrated=True,
        ),
        serving_feature_schema_version=ETA_SCHEMA,
        required_source="POSITION_MODEL",
        max_input_age_seconds=180,
    )

    prediction = guarded.predict(eta_input())

    assert prediction is not None
    assert prediction.model_version == "eta-model-v3"
    assert prediction.model_readiness == "ACTIVE"


def test_verified_seat_remains_compatible_as_calibrated_wrapper_fallback() -> None:
    class UnusedScorer:
        def score(self, value):
            raise AssertionError("uncalibrated primary scorer must not run")

    calibrator = IdentityProbabilityCalibrator()
    guarded_primary = CalibratedSeatRiskPredictor(
        UnusedScorer(),
        RuntimeModelSpec(
            purpose="SEAT_RISK",
            version="unready-primary-v1",
            readiness="ACTIVE",
            feature_schema_version="primary-schema-v1",
            calibrated=False,
        ),
        serving_feature_schema_version="primary-schema-v1",
        no_seat_calibrator=calibrator,
        low_seat2_calibrator=calibrator,
        low_seat5_calibrator=calibrator,
        fallback=verified_seat(),
    )

    prediction = guarded_primary.predict(seat_input())

    assert prediction is not None
    assert prediction.model_version == "seat-model-v3"
    assert prediction.model_readiness == "ACTIVE"
