from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from bus_intelligence_core import (
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_SCHEMA_VERSION,
    EtaFeatureContext,
    EtaNativePrediction,
    EtaPredictorInput,
    SeatRiskNativePrediction,
    SeatRiskPredictorInput,
    SeatRiskFeatureContext,
    TrafficFeatureContext,
    WeatherFeatureContext,
)
from routing_worker.feature_builder import NormalizedFeatureObservation
from routing_worker.feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)
from routing_worker.feature_encoding import encode_feature_values
from routing_worker.model_jobs.artifact_bundle import (
    ArtifactBundleManifest,
    BundleFile,
)
from routing_worker.model_jobs.model_foundation import (
    ArtifactIntegrityError,
    ArtifactMetadata,
)
from routing_worker.model_jobs.registry import Deployment, ModelState, RegistryEntry
from routing_worker.model_serving import (
    ModelServingConfigurationError,
    VerifiedServingLifecycle,
    build_verified_eta_predictor,
    build_verified_seat_risk_predictor,
)
from routing_worker.serving_features import (
    EtaServingFeatureRecord,
    SeatRiskServingFeatureRecord,
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


class EtaSource:
    def __init__(self, record: EtaServingFeatureRecord) -> None:
        self.record = record

    def load(self, value: EtaPredictorInput) -> EtaServingFeatureRecord:
        return self.record


class SeatSource:
    def __init__(self, record: SeatRiskServingFeatureRecord) -> None:
        self.record = record

    def load(self, value: SeatRiskPredictorInput) -> SeatRiskServingFeatureRecord:
        return self.record


def contexts() -> tuple[EtaFeatureContext, SeatRiskFeatureContext]:
    weather = WeatherFeatureContext(
        OBSERVED_AT,
        WEATHER_CONTEXT_SCHEMA_VERSION,
        temperature_c=0.0,
        precipitation_mm=0.0,
    )
    traffic = TrafficFeatureContext(
        OBSERVED_AT,
        TRAFFIC_CONTEXT_SCHEMA_VERSION,
        speed_kph=0.0,
        travel_time_seconds=0,
        incident_present=False,
    )
    return EtaFeatureContext(weather, traffic), SeatRiskFeatureContext(weather, traffic)


def eta_input(context: EtaFeatureContext | None = None) -> EtaPredictorInput:
    return EtaPredictorInput(
        "vehicle-token",
        "route-1",
        "UP",
        "stop-4",
        OBSERVED_AT,
        0,
        QUERY_AT,
        context,
    )


def seat_input(context: SeatRiskFeatureContext | None = None) -> SeatRiskPredictorInput:
    return SeatRiskPredictorInput(
        "vehicle-token",
        "route-1",
        "UP",
        "stop-4",
        "stop-8",
        OBSERVED_AT,
        QUERY_AT,
        0,
        context,
    )


def digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def bundle(
    root: Path,
    *,
    family: str,
    schema_version: str,
    feature_names: tuple[str, ...],
) -> ArtifactBundleManifest:
    artifact = b"tree\nversion=v2\n"
    calibration = b'{"method":"fixture"}\n'
    card = b"# Offline fixture model card\n"
    schema = b'{"version":"v2"}\n'
    suffix = "eta" if family == "ETA" else "seat"
    files = {
        f"{suffix}-model.txt": artifact,
        f"{suffix}-calibration.json": calibration,
        f"{suffix}-model-card.md": card,
        f"{suffix}-feature-schema.json": schema,
    }
    for name, value in files.items():
        (root / name).write_bytes(value)
    return ArtifactBundleManifest(
        artifact=ArtifactMetadata(
            model_family=family,
            model_version=f"{suffix}-fixture-v2",
            artifact_filename=f"{suffix}-model.txt",
            artifact_format="LIGHTGBM_TEXT",
            artifact_sha256=digest(artifact),
            feature_schema_version=schema_version,
            feature_names=feature_names,
        ),
        calibration=BundleFile(
            f"{suffix}-calibration.json", digest(calibration)
        ),
        model_card=BundleFile(f"{suffix}-model-card.md", digest(card)),
        feature_schema=BundleFile(
            f"{suffix}-feature-schema.json", digest(schema)
        ),
        dataset_sha256="d" * 64,
        metrics_sha256="e" * 64,
    )


def lifecycle(
    manifest: ArtifactBundleManifest,
    *,
    calibration_method: str = "CONFORMAL",
) -> VerifiedServingLifecycle:
    validation_digest = "f" * 64
    entry = RegistryEntry(
        artifact=manifest.artifact,
        model_card_sha256=manifest.model_card.sha256,
        state=ModelState.ACTIVE,
        state_version=5,
        registered_at=QUERY_AT - timedelta(days=1),
        updated_at=QUERY_AT - timedelta(hours=1),
        validation_evidence_sha256=validation_digest,
    )
    active = Deployment(
        model_version=manifest.artifact.model_version,
        environment="staging",
        state=ModelState.ACTIVE,
        traffic_fraction=1,
        activated_at=QUERY_AT - timedelta(minutes=30),
    )
    assert manifest.calibration is not None
    return VerifiedServingLifecycle(
        registry_entry=entry,
        deployment=active,
        deployment_id="deployment-fixed-by-composition",
        calibration_method=calibration_method,
        calibration_sha256=manifest.calibration.sha256,
        feature_schema_sha256=manifest.feature_schema.sha256,
        validation_evidence_sha256=validation_digest,
    )


class EtaSession:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, values: tuple[object, ...]) -> EtaNativePrediction:
        self.calls += 1
        encode_feature_values(
            family="ETA",
            feature_schema_version=ETA_SCHEMA_VERSION,
            feature_names=ETA_FEATURE_NAMES,
            values=values,
        )
        return EtaNativePrediction(120, 180, 0.8)


class SeatSession:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, values: tuple[object, ...]) -> SeatRiskNativePrediction:
        self.calls += 1
        encode_feature_values(
            family="SEAT_RISK",
            feature_schema_version=SEAT_SCHEMA_VERSION,
            feature_names=SEAT_FEATURE_NAMES,
            values=values,
        )
        return SeatRiskNativePrediction(0.1, 0.2, 0.3, 0.75)


class Loader:
    def __init__(self, session: EtaSession | SeatSession) -> None:
        self.session = session
        self.calls: list[dict[str, object]] = []

    def load(self, **values: object) -> EtaSession | SeatSession:
        self.calls.append(values)
        return self.session


def test_verified_factories_bind_fixed_bundle_source_runtime_and_family(tmp_path: Path) -> None:
    eta_context, seat_context = contexts()
    eta_observation = complete_observation(eta_feature_context=eta_context)
    eta_session = EtaSession()
    eta_loader = Loader(eta_session)
    eta_manifest = bundle(
        tmp_path,
        family="ETA",
        schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    eta = build_verified_eta_predictor(
        bundle_directory=tmp_path,
        manifest=eta_manifest,
        lifecycle=lifecycle(eta_manifest),
        feature_source=EtaSource(
            EtaServingFeatureRecord("vehicle-token", "stop-4", eta_observation)
        ),
        runtime_loader=eta_loader,
    )
    result = eta.predict(eta_input(eta_context))
    assert result is not None
    assert result.model_version == "eta-fixture-v2"
    assert result.source == "POSITION_MODEL"
    assert result.model_readiness == "ACTIVE"
    assert result.p50_arrival_at == QUERY_AT + timedelta(seconds=120)
    assert result.p90_arrival_at == QUERY_AT + timedelta(seconds=180)
    assert eta_session.calls == 1
    assert len(eta_loader.calls) == 1
    assert eta_loader.calls[0]["feature_names"] == ETA_FEATURE_NAMES
    assert eta_loader.calls[0]["artifact_path"] == (
        tmp_path / "eta-model.txt"
    ).resolve()

    seat_root = tmp_path / "seat"
    seat_root.mkdir()
    seat_session = SeatSession()
    seat_loader = Loader(seat_session)
    seat_manifest = bundle(
        seat_root,
        family="SEAT_RISK",
        schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
    )
    seat = build_verified_seat_risk_predictor(
        bundle_directory=seat_root,
        manifest=seat_manifest,
        lifecycle=lifecycle(seat_manifest, calibration_method="ISOTONIC"),
        feature_source=SeatSource(
            SeatRiskServingFeatureRecord(
                "vehicle-token",
                "stop-4",
                "stop-8",
                complete_observation(seat_risk_feature_context=seat_context),
            )
        ),
        runtime_loader=seat_loader,
    )
    seat_result = seat.predict(seat_input(seat_context))
    assert seat_result is not None
    assert seat_result.model_version == "seat-fixture-v2"
    assert seat_result.origin == "MODEL_PREDICTED"
    assert seat_session.calls == 1
    assert seat_loader.calls[0]["feature_names"] == SEAT_FEATURE_NAMES


def test_missing_core_fails_before_native_runtime_call(tmp_path: Path) -> None:
    manifest = bundle(
        tmp_path,
        family="ETA",
        schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    session = EtaSession()
    predictor = build_verified_eta_predictor(
        bundle_directory=tmp_path,
        manifest=manifest,
        lifecycle=lifecycle(manifest),
        feature_source=EtaSource(
            EtaServingFeatureRecord(
                "vehicle-token",
                "stop-4",
                complete_observation(headway_seconds=None),
            )
        ),
        runtime_loader=Loader(session),
    )
    assert predictor.predict(eta_input()) is None
    assert session.calls == 0


def test_lifecycle_rejects_arbitrary_active_strings_retired_canary_and_dev(
    tmp_path: Path,
) -> None:
    manifest = bundle(
        tmp_path,
        family="ETA",
        schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    source = EtaSource(
        EtaServingFeatureRecord("vehicle-token", "stop-4", complete_observation())
    )
    loader = Loader(EtaSession())
    with pytest.raises(ModelServingConfigurationError, match="lifecycle object"):
        build_verified_eta_predictor(
            bundle_directory=tmp_path,
            manifest=manifest,
            lifecycle="ACTIVE",  # type: ignore[arg-type]
            feature_source=source,
            runtime_loader=loader,
        )
    assert loader.calls == []

    valid = lifecycle(manifest)
    with pytest.raises(ModelServingConfigurationError, match="both be ACTIVE"):
        replace(
            valid,
            registry_entry=replace(
                valid.registry_entry, state=ModelState.RETIRED
            ),
        )
    with pytest.raises(ModelServingConfigurationError, match="both be ACTIVE"):
        replace(
            valid,
            deployment=replace(
                valid.deployment,
                state=ModelState.CANARY,
                traffic_fraction=0.5,
            ),
        )
    with pytest.raises(ModelServingConfigurationError, match="staging or prod"):
        replace(valid, deployment=replace(valid.deployment, environment="dev"))
    with pytest.raises(ValueError, match="traffic"):
        replace(valid.deployment, traffic_fraction=0.5)


def test_lifecycle_rejects_version_validation_and_calibration_drift(
    tmp_path: Path,
) -> None:
    manifest = bundle(
        tmp_path,
        family="ETA",
        schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    valid = lifecycle(manifest)
    with pytest.raises(ModelServingConfigurationError, match="model versions differ"):
        replace(
            valid,
            deployment=replace(valid.deployment, model_version="different-version"),
        )
    with pytest.raises(ModelServingConfigurationError, match="validation evidence"):
        replace(valid, validation_evidence_sha256="a" * 64)
    with pytest.raises(ValueError, match="calibration method"):
        replace(valid, calibration_method="UNKNOWN")


def test_family_schema_hash_and_calibration_bundle_fail_closed(tmp_path: Path) -> None:
    seat_manifest = bundle(
        tmp_path,
        family="SEAT_RISK",
        schema_version=SEAT_SCHEMA_VERSION,
        feature_names=SEAT_FEATURE_NAMES,
    )
    source = EtaSource(
        EtaServingFeatureRecord("vehicle-token", "stop-4", complete_observation())
    )
    with pytest.raises(ModelServingConfigurationError, match="family mismatch"):
        build_verified_eta_predictor(
            bundle_directory=tmp_path,
            manifest=seat_manifest,
            lifecycle=lifecycle(seat_manifest, calibration_method="ISOTONIC"),
            feature_source=source,
            runtime_loader=Loader(EtaSession()),
        )

    eta_root = tmp_path / "eta"
    eta_root.mkdir()
    eta_manifest = bundle(
        eta_root,
        family="ETA",
        schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    (eta_root / "eta-model.txt").write_bytes(b"tampered")
    with pytest.raises(ModelServingConfigurationError, match="bundle verification"):
        build_verified_eta_predictor(
            bundle_directory=eta_root,
            manifest=eta_manifest,
            lifecycle=lifecycle(eta_manifest),
            feature_source=source,
            runtime_loader=Loader(EtaSession()),
        )

    wrong_schema = replace(
        eta_manifest,
        artifact=replace(
            eta_manifest.artifact,
            feature_schema_version="eta-feature-foundation-v1",
        ),
    )
    with pytest.raises(ModelServingConfigurationError, match="schema version"):
        build_verified_eta_predictor(
            bundle_directory=eta_root,
            manifest=wrong_schema,
            lifecycle=lifecycle(wrong_schema),
            feature_source=source,
            runtime_loader=Loader(EtaSession()),
        )

    no_calibration = replace(eta_manifest, calibration=None)
    with pytest.raises(ModelServingConfigurationError, match="calibration artifact"):
        build_verified_eta_predictor(
            bundle_directory=eta_root,
            manifest=no_calibration,
            lifecycle=lifecycle(eta_manifest),
            feature_source=source,
            runtime_loader=Loader(EtaSession()),
        )


@pytest.mark.parametrize(
    "drift, match",
    [
        ("artifact", "artifact metadata"),
        ("model_card", "model-card digest"),
        ("calibration", "calibration digest"),
        ("feature_schema", "feature-schema digest"),
    ],
)
def test_registry_manifest_digest_drift_fails_before_loader(
    tmp_path: Path, drift: str, match: str
) -> None:
    manifest = bundle(
        tmp_path,
        family="ETA",
        schema_version=ETA_SCHEMA_VERSION,
        feature_names=ETA_FEATURE_NAMES,
    )
    evidence = lifecycle(manifest)
    if drift == "artifact":
        evidence = replace(
            evidence,
            registry_entry=replace(
                evidence.registry_entry,
                artifact=replace(
                    evidence.registry_entry.artifact,
                    artifact_sha256="0" * 64,
                ),
            ),
        )
    elif drift == "model_card":
        evidence = replace(
            evidence,
            registry_entry=replace(
                evidence.registry_entry, model_card_sha256="0" * 64
            ),
        )
    elif drift == "calibration":
        evidence = replace(evidence, calibration_sha256="0" * 64)
    else:
        evidence = replace(evidence, feature_schema_sha256="0" * 64)
    loader = Loader(EtaSession())
    with pytest.raises(ModelServingConfigurationError, match=match):
        build_verified_eta_predictor(
            bundle_directory=tmp_path,
            manifest=manifest,
            lifecycle=evidence,
            feature_source=EtaSource(
                EtaServingFeatureRecord(
                    "vehicle-token", "stop-4", complete_observation()
                )
            ),
            runtime_loader=loader,
        )
    assert loader.calls == []


def test_pickle_and_request_selected_artifact_paths_are_not_available(tmp_path: Path) -> None:
    with pytest.raises(ArtifactIntegrityError):
        ArtifactMetadata(
            model_family="ETA",
            model_version="bad",
            artifact_filename="model.pkl",
            artifact_format="PICKLE",
            artifact_sha256="a" * 64,
            feature_schema_version=ETA_SCHEMA_VERSION,
            feature_names=ETA_FEATURE_NAMES,
        )
    assert "artifact_path" not in eta_input().__dataclass_fields__
    assert "artifact_uri" not in seat_input().__dataclass_fields__
