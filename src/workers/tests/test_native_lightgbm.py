from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from math import isnan
from pathlib import Path

import pytest

from bus_intelligence_core import (
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_SCHEMA_VERSION,
    EtaFeatureContext,
    SeatRiskFeatureContext,
    TrafficFeatureContext,
    WeatherFeatureContext,
)
from routing_worker.feature_builder import (
    NormalizedFeatureObservation,
    build_eta_features,
    build_seat_features,
)
from routing_worker.feature_encoding import (
    encode_feature_mapping,
    encode_feature_values,
    feature_schema_document,
)
from routing_worker.feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)
from routing_worker.model_jobs.lightgbm_adapter import train_to_native_text
from routing_worker.model_jobs.lightgbm_adapter import (
    select_observed_seat_ordinal_training_rows,
)
from routing_worker.data_quality.dataset_foundation import (
    TargetStopObservation,
    build_target_stop_labels,
)
from routing_worker.model_jobs.evaluation import IsotonicCalibrator, PlattCalibrator
from routing_worker.model_serving import ModelServingConfigurationError
from routing_worker.native_lightgbm import (
    LightGbmEtaRuntimeLoader,
    LightGbmSeatRiskRuntimeLoader,
)


UTC = timezone.utc
QUERY_AT = datetime(2026, 8, 23, 12, tzinfo=UTC)


def observation(**changes: object) -> NormalizedFeatureObservation:
    value = NormalizedFeatureObservation(
        trip_id="trip-token",
        route_id="route-1",
        direction="UP",
        observed_at=QUERY_AT - timedelta(seconds=10),
        ingested_at=QUERY_AT - timedelta(seconds=8),
        valid_at=QUERY_AT - timedelta(seconds=7),
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


def fresh_contexts() -> tuple[EtaFeatureContext, SeatRiskFeatureContext]:
    weather = WeatherFeatureContext(
        observed_at=QUERY_AT - timedelta(seconds=10),
        schema_version=WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=0.0,
        precipitation_mm=0.0,
    )
    traffic = TrafficFeatureContext(
        observed_at=QUERY_AT - timedelta(seconds=10),
        schema_version=TRAFFIC_CONTEXT_SCHEMA_VERSION,
        speed_kph=0.0,
        travel_time_seconds=0,
        incident_present=False,
    )
    return EtaFeatureContext(weather, traffic), SeatRiskFeatureContext(weather, traffic)


class FakeDataset:
    def __init__(self, matrix: list[list[float]], **values: object) -> None:
        self.matrix = matrix
        self.values = values


class FakeBooster:
    def __init__(self, module: "FakeLightGbm", model_file: str | None = None) -> None:
        self.module = module
        self.model_file = model_file
        self.params = module.parameters

    def feature_name(self) -> list[str]:
        return list(self.module.names)

    def predict(self, matrix: list[list[float]]) -> list[object]:
        self.module.prediction_matrices.append(matrix)
        return [self.module.output]

    def save_model(self, path: str) -> None:
        Path(path).write_text("safe native fixture\n", encoding="utf-8")


class FakeLightGbm:
    def __init__(
        self,
        names: tuple[str, ...],
        output: object,
        parameters: dict[str, object] | None = None,
    ) -> None:
        self.names = names
        self.output = output
        self.parameters = parameters or {"objective": "regression"}
        self.datasets: list[FakeDataset] = []
        self.prediction_matrices: list[list[list[float]]] = []
        self.loaded_paths: list[str] = []

    def Booster(self, *, model_file: str) -> FakeBooster:  # noqa: N802
        self.loaded_paths.append(model_file)
        return FakeBooster(self, model_file)

    def Dataset(self, matrix: list[list[float]], **values: object) -> FakeDataset:  # noqa: N802
        dataset = FakeDataset(matrix, **values)
        self.datasets.append(dataset)
        return dataset

    def train(self, parameters: dict[str, object], dataset: FakeDataset) -> FakeBooster:
        assert parameters == self.parameters
        assert dataset in self.datasets
        return FakeBooster(self)


def write_runtime_files(
    root: Path, *, family: str, calibration: dict[str, object]
) -> tuple[Path, Path, Path]:
    model = root / "model.txt"
    schema = root / "feature-schema.json"
    calibration_path = root / "calibration.json"
    model.write_text("safe native fixture\n", encoding="utf-8")
    schema.write_text(
        json.dumps(feature_schema_document(family=family), separators=(",", ":")),
        encoding="utf-8",
    )
    calibration_path.write_text(
        json.dumps(calibration, separators=(",", ":")), encoding="utf-8"
    )
    return model, schema, calibration_path


def test_training_and_eta_serving_share_exact_encoder_and_return_durations(
    tmp_path: Path,
) -> None:
    eta_context, _ = fresh_contexts()
    vector = build_eta_features(observation(eta_feature_context=eta_context))
    assert vector.as_mapping["context_missing_flags"] == ""
    assert vector.as_mapping["missing_flags"] == ""
    expected = encode_feature_values(
        family="ETA",
        feature_schema_version=vector.schema_version,
        feature_names=vector.feature_names,
        values=vector.values,
    )
    module = FakeLightGbm(ETA_FEATURE_NAMES, 120.2)
    trained = tmp_path / "trained.txt"
    train_to_native_text(
        rows=(vector.as_mapping,),
        labels=(120.0,),
        family="ETA",
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
        output_path=trained,
        parameters={"objective": "regression"},
        training_enabled=True,
        lightgbm_module=module,
    )
    assert tuple(module.datasets[0].matrix[0]) == expected
    assert module.datasets[0].matrix[0][1] != 0  # direction is not float-cast.
    assert not any(isnan(value) for value in module.datasets[0].matrix[0])

    model, schema, calibration = write_runtime_files(
        tmp_path,
        family="ETA",
        calibration={
            "schemaVersion": "eta-calibration-v1",
            "family": "ETA",
            "method": "CONFORMAL",
            "confidence": 0.8,
            "p90OffsetSeconds": 59.2,
        },
    )
    session = LightGbmEtaRuntimeLoader(module).load(
        artifact_path=model,
        artifact_format="LIGHTGBM_TEXT",
        calibration_path=calibration,
        calibration_method="CONFORMAL",
        feature_schema_path=schema,
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    prediction = session.predict(vector.values)
    assert prediction is not None
    assert (prediction.p50_seconds, prediction.p90_seconds) == (121, 180)
    assert tuple(module.prediction_matrices[0][0]) == expected


def test_seat_runtime_preserves_zero_false_and_applies_three_calibrators(
    tmp_path: Path,
) -> None:
    _, seat_context = fresh_contexts()
    vector = build_seat_features(observation(seat_risk_feature_context=seat_context))
    assert vector.as_mapping["context_missing_flags"] == ""
    assert vector.as_mapping["missing_flags"] == ""
    module = FakeLightGbm(
        SEAT_FEATURE_NAMES,
        [0.05, 0.20, 0.45, 0.30],
        {"objective": "multiclass", "num_class": 4},
    )
    model, schema, calibration = write_runtime_files(
        tmp_path,
        family="SEAT_RISK",
        calibration={
            "schemaVersion": "seat-risk-calibration-v1",
            "family": "SEAT_RISK",
            "method": "PLATT",
            "confidence": 0.75,
            "parameters": [
                {"slope": 1.0, "intercept": 0.0},
                {"slope": 1.0, "intercept": 0.0},
                {"slope": 1.0, "intercept": 0.0},
            ],
        },
    )
    session = LightGbmSeatRiskRuntimeLoader(module).load(
        artifact_path=model,
        artifact_format="LIGHTGBM_TEXT",
        calibration_path=calibration,
        calibration_method="PLATT",
        feature_schema_path=schema,
        feature_schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
    )
    prediction = session.predict(vector.values)
    assert prediction is not None
    cumulative = (0.05, 0.25, 0.70)
    expected = tuple(PlattCalibrator(1.0, 0.0).transform(v) for v in cumulative)
    assert (
        prediction.no_seat_probability,
        prediction.low_seat2_probability,
        prediction.low_seat5_probability,
    ) == pytest.approx(expected)
    encoded = module.prediction_matrices[0][0]
    assert encoded[5:9] == [0.0, 0.0, 0.0, 0.0]


def test_nullable_ordinal_target_selection_excludes_unobserved_before_training(
    tmp_path: Path,
) -> None:
    vector = build_seat_features(observation())
    observed = build_target_stop_labels(
        trip_id="trip-token",
        target_stop_id="stop-8",
        feature_observed_at=QUERY_AT,
        observations=(
            TargetStopObservation(
                "trip-token", "stop-8", QUERY_AT + timedelta(seconds=20), 3
            ),
        ),
    )
    unobserved = build_target_stop_labels(
        trip_id="trip-token",
        target_stop_id="stop-8",
        feature_observed_at=QUERY_AT,
        observations=(),
    )
    rows, labels = select_observed_seat_ordinal_training_rows(
        rows=(vector.as_mapping, vector.as_mapping),
        targets=(observed.seat_ordinal_class, unobserved.seat_ordinal_class),
    )
    assert len(rows) == 1
    assert labels == (2,)
    module = FakeLightGbm(
        SEAT_FEATURE_NAMES,
        [0.1, 0.2, 0.3, 0.4],
        {"objective": "multiclass", "num_class": 4},
    )
    train_to_native_text(
        rows=rows,
        labels=labels,
        family="SEAT_RISK",
        feature_schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
        output_path=tmp_path / "seat-trained.txt",
        parameters={"objective": "multiclass", "num_class": 4},
        training_enabled=True,
        lightgbm_module=module,
    )
    assert module.datasets[0].values["label"] == [2]


def test_seat_isotonic_serving_reuses_stepwise_evaluation_calibrator(tmp_path: Path) -> None:
    vector = build_seat_features(observation())
    module = FakeLightGbm(
        SEAT_FEATURE_NAMES,
        [0.125, 0.125, 0.25, 0.5],
        {"objective": "multiclass", "num_class": 4},
    )
    parameters = [
        {"x": [0.125, 0.25, 1.0], "y": [0.1, 0.3, 0.8]},
        {"x": [0.125, 0.25, 1.0], "y": [0.1, 0.3, 0.8]},
        {"x": [0.125, 0.25, 1.0], "y": [0.1, 0.3, 0.8]},
    ]
    model, schema, calibration = write_runtime_files(
        tmp_path,
        family="SEAT_RISK",
        calibration={
            "schemaVersion": "seat-risk-calibration-v1",
            "family": "SEAT_RISK",
            "method": "ISOTONIC",
            "confidence": 0.75,
            "parameters": parameters,
        },
    )
    session = LightGbmSeatRiskRuntimeLoader(module).load(
        artifact_path=model,
        artifact_format="LIGHTGBM_TEXT",
        calibration_path=calibration,
        calibration_method="ISOTONIC",
        feature_schema_path=schema,
        feature_schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
    )
    prediction = session.predict(vector.values)
    assert prediction is not None
    canonical = IsotonicCalibrator((0.125, 0.25, 1.0), (0.1, 0.3, 0.8))
    expected = tuple(canonical.transform(v) for v in (0.125, 0.25, 0.5))
    assert (
        prediction.no_seat_probability,
        prediction.low_seat2_probability,
        prediction.low_seat5_probability,
    ) == expected


def test_encoder_rejects_wrong_family_schema_types_and_extra_training_keys() -> None:
    vector = build_eta_features(observation())
    with pytest.raises(ValueError, match="canonical family schema"):
        encode_feature_values(
            family="ETA",
            feature_schema_version=SEAT_SCHEMA_VERSION,
            feature_names=vector.feature_names,
            values=vector.values,
        )
    bad = dict(vector.as_mapping)
    bad["extra"] = 1
    with pytest.raises(ValueError, match="exactly match"):
        encode_feature_mapping(
            family="ETA",
            feature_schema_version=ETA_SCHEMA_VERSION,
            feature_names=ETA_FEATURE_NAMES,
            values=bad,
        )
    values = list(vector.values)
    values[2] = True
    with pytest.raises(ValueError, match="numeric"):
        encode_feature_values(
            family="ETA",
            feature_schema_version=ETA_SCHEMA_VERSION,
            feature_names=ETA_FEATURE_NAMES,
            values=tuple(values),
        )
    for name in ("route_id", "direction"):
        values = list(vector.values)
        values[ETA_FEATURE_NAMES.index(name)] = " "
        with pytest.raises(ValueError, match=f"{name} must be non-blank"):
            encode_feature_values(
                family="ETA",
                feature_schema_version=ETA_SCHEMA_VERSION,
                feature_names=ETA_FEATURE_NAMES,
                values=tuple(values),
            )


@pytest.mark.parametrize("state", ["missing", "future", "stale"])
def test_missing_future_and_stale_context_flags_encode_deterministically(
    state: str,
) -> None:
    if state == "missing":
        context = None
    else:
        offset = -400 if state == "stale" else 1
        at = QUERY_AT + timedelta(seconds=offset)
        context = EtaFeatureContext(
            WeatherFeatureContext(
                at,
                WEATHER_CONTEXT_SCHEMA_VERSION,
                temperature_c=1.0,
                precipitation_mm=0.0,
            ),
            TrafficFeatureContext(
                at,
                TRAFFIC_CONTEXT_SCHEMA_VERSION,
                speed_kph=1.0,
                travel_time_seconds=1,
                incident_present=False,
            ),
        )
    vector = build_eta_features(observation(eta_feature_context=context))
    assert vector.as_mapping["context_missing_flags"] != ""
    tuple_encoding = encode_feature_values(
        family="ETA",
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
        values=vector.values,
    )
    mapping_encoding = encode_feature_mapping(
        family="ETA",
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
        values=vector.as_mapping,
    )
    assert tuple_encoding == mapping_encoding


def test_empty_no_missing_category_is_distinct_from_none_zero_and_false() -> None:
    eta_context, _ = fresh_contexts()
    vector = build_eta_features(observation(eta_feature_context=eta_context))
    encoded = encode_feature_values(
        family="ETA",
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
        values=vector.values,
    )
    context_flag_index = ETA_FEATURE_NAMES.index("context_missing_flags")
    missing_flag_index = ETA_FEATURE_NAMES.index("missing_flags")
    incident_index = ETA_FEATURE_NAMES.index("traffic_incident_present")
    precipitation_index = ETA_FEATURE_NAMES.index("weather_precipitation_mm")
    assert encoded[context_flag_index] != 0.0
    assert encoded[missing_flag_index] != 0.0
    assert encoded[incident_index] == 0.0
    assert encoded[precipitation_index] == 0.0
    missing_values = list(vector.values)
    missing_values[context_flag_index] = None
    missing_encoded = encode_feature_values(
        family="ETA",
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
        values=tuple(missing_values),
    )
    assert isnan(missing_encoded[context_flag_index])


@pytest.mark.parametrize(
    "mutation, match",
    [
        ("schema", "versioned encoder"),
        ("duplicate", "strict UTF-8 JSON"),
        ("method", "identity mismatch"),
        ("shape", None),
        ("nonfinite", None),
        ("json_artifact", "only verified text"),
    ],
)
def test_native_eta_loader_and_session_fail_closed(
    tmp_path: Path, mutation: str, match: str | None
) -> None:
    module = FakeLightGbm(ETA_FEATURE_NAMES, 30.0)
    model, schema, calibration = write_runtime_files(
        tmp_path,
        family="ETA",
        calibration={
            "schemaVersion": "eta-calibration-v1",
            "family": "ETA",
            "method": "CONFORMAL",
            "confidence": 0.8,
            "p90OffsetSeconds": 10,
        },
    )
    if mutation == "schema":
        schema.write_text('{"encodingVersion":"wrong"}', encoding="utf-8")
    elif mutation == "duplicate":
        calibration.write_text(
            '{"schemaVersion":"eta-calibration-v1","schemaVersion":"x"}',
            encoding="utf-8",
        )
    elif mutation == "method":
        value = json.loads(calibration.read_text(encoding="utf-8"))
        value["method"] = "QUANTILE"
        calibration.write_text(json.dumps(value), encoding="utf-8")
    elif mutation == "shape":
        module.output = [1.0, 2.0]
    elif mutation == "nonfinite":
        module.output = float("inf")
    loader = LightGbmEtaRuntimeLoader(module)
    if mutation in {"schema", "duplicate", "method", "json_artifact"}:
        with pytest.raises(ModelServingConfigurationError, match=match):
            loader.load(
                artifact_path=model,
                artifact_format=(
                    "LIGHTGBM_JSON" if mutation == "json_artifact" else "LIGHTGBM_TEXT"
                ),
                calibration_path=calibration,
                calibration_method="CONFORMAL",
                feature_schema_path=schema,
                feature_schema_version=ETA_SCHEMA_VERSION,
                feature_names=ETA_FEATURE_NAMES,
            )
        return
    session = loader.load(
        artifact_path=model,
        artifact_format="LIGHTGBM_TEXT",
        calibration_path=calibration,
        calibration_method="CONFORMAL",
        feature_schema_path=schema,
        feature_schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    assert session.predict(build_eta_features(observation()).values) is None


def test_lightgbm_dependency_and_internal_feature_drift_fail_before_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model, schema, calibration = write_runtime_files(
        tmp_path,
        family="ETA",
        calibration={
            "schemaVersion": "eta-calibration-v1",
            "family": "ETA",
            "method": "CONFORMAL",
            "confidence": 0.8,
            "p90OffsetSeconds": 10,
        },
    )
    drift = FakeLightGbm(tuple(reversed(ETA_FEATURE_NAMES)), 10.0)
    with pytest.raises(ModelServingConfigurationError, match="internal feature names"):
        LightGbmEtaRuntimeLoader(drift).load(
            artifact_path=model,
            artifact_format="LIGHTGBM_TEXT",
            calibration_path=calibration,
            calibration_method="CONFORMAL",
            feature_schema_path=schema,
            feature_schema_version=ETA_SCHEMA_VERSION,
            feature_names=ETA_FEATURE_NAMES,
        )

    objective_drift = FakeLightGbm(
        ETA_FEATURE_NAMES, 10.0, {"objective": "multiclass", "num_class": 4}
    )
    with pytest.raises(ModelServingConfigurationError, match="scalar regression"):
        LightGbmEtaRuntimeLoader(objective_drift).load(
            artifact_path=model,
            artifact_format="LIGHTGBM_TEXT",
            calibration_path=calibration,
            calibration_method="CONFORMAL",
            feature_schema_path=schema,
            feature_schema_version=ETA_SCHEMA_VERSION,
            feature_names=ETA_FEATURE_NAMES,
        )

    def unavailable(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("routing_worker.native_lightgbm.importlib.import_module", unavailable)
    with pytest.raises(ModelServingConfigurationError, match="dependency is unavailable"):
        LightGbmEtaRuntimeLoader().load(
            artifact_path=model,
            artifact_format="LIGHTGBM_TEXT",
            calibration_path=calibration,
            calibration_method="CONFORMAL",
            feature_schema_path=schema,
            feature_schema_version=ETA_SCHEMA_VERSION,
            feature_names=ETA_FEATURE_NAMES,
        )


def test_seat_runtime_rejects_direct_three_output_and_wrong_class_metadata(
    tmp_path: Path,
) -> None:
    model, schema, calibration = write_runtime_files(
        tmp_path,
        family="SEAT_RISK",
        calibration={
            "schemaVersion": "seat-risk-calibration-v1",
            "family": "SEAT_RISK",
            "method": "PLATT",
            "confidence": 0.75,
            "parameters": [
                {"slope": 1.0, "intercept": 0.0},
                {"slope": 1.0, "intercept": 0.0},
                {"slope": 1.0, "intercept": 0.0},
            ],
        },
    )
    drift = FakeLightGbm(
        SEAT_FEATURE_NAMES,
        [0.1, 0.2, 0.7],
        {"objective": "multiclass", "num_class": 3},
    )
    with pytest.raises(ModelServingConfigurationError, match="four-class ordinal"):
        LightGbmSeatRiskRuntimeLoader(drift).load(
            artifact_path=model,
            artifact_format="LIGHTGBM_TEXT",
            calibration_path=calibration,
            calibration_method="PLATT",
            feature_schema_path=schema,
            feature_schema_version=SEAT_SCHEMA_VERSION,
            feature_names=SEAT_FEATURE_NAMES,
        )

    direct = FakeLightGbm(
        SEAT_FEATURE_NAMES,
        [0.1, 0.2, 0.7],
        {"objective": "multiclass", "num_class": 4},
    )
    session = LightGbmSeatRiskRuntimeLoader(direct).load(
        artifact_path=model,
        artifact_format="LIGHTGBM_TEXT",
        calibration_path=calibration,
        calibration_method="PLATT",
        feature_schema_path=schema,
        feature_schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
    )
    assert session.predict(build_seat_features(observation()).values) is None
