from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from bus_intelligence_core import (
    EtaPredictorInput,
    SeatRiskPredictorInput,
    VerifiedEtaPredictor,
    VerifiedEtaPredictorAttestation,
    VerifiedPredictorConfigurationError,
    VerifiedSeatRiskPredictor,
    VerifiedSeatRiskPredictorAttestation,
)
from provider_core.canonical import Coordinate
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from routing_api.fanin_integration import (
    CanonicalFanInOptimizeRouteUseCase,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.production_composition import _verified_model_projection
from routing_worker.model_jobs.artifact_bundle import BundleFile
from routing_worker.model_jobs.model_foundation import (
    ArtifactIntegrityError,
    ArtifactMetadata,
    ModelFoundationError,
    load_artifact_metadata,
)
from routing_worker.model_serving import ModelServingConfigurationError
from routing_worker.native_lightgbm import _load_json
from transport_mapping import GitsRoadLinkIdentity, ValidityWindow


UTC = timezone.utc
AS_OF = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _artifact(filename: str, artifact_format: str) -> ArtifactMetadata:
    return ArtifactMetadata(
        model_family="ETA",
        model_version="eta-ri373",
        artifact_filename=filename,
        artifact_format=artifact_format,
        artifact_sha256=SHA_A,
        feature_schema_version="eta-ri373-schema",
        feature_names=("route_id", "missing_flags"),
    )


@pytest.mark.parametrize(
    ("filename", "artifact_format"),
    (
        ("../model.txt", "LIGHTGBM_TEXT"),
        ("models/model.txt", "LIGHTGBM_TEXT"),
        ("models\\model.txt", "LIGHTGBM_TEXT"),
        ("C:\\models\\model.txt", "LIGHTGBM_TEXT"),
        ("model.pkl", "PICKLE"),
        ("model.joblib", "JOBLIB"),
        ("model.pkl", "LIGHTGBM_TEXT"),
        ("model.txt", "PICKLE"),
    ),
)
def test_worker_artifact_metadata_rejects_traversal_and_executable_formats(
    filename: str, artifact_format: str
) -> None:
    with pytest.raises(ArtifactIntegrityError):
        _artifact(filename, artifact_format)


def test_bundle_paths_are_plain_relative_unique_inert_files() -> None:
    for filename in (
        "../calibration.json",
        "nested/calibration.json",
        "nested\\calibration.json",
        "C:\\calibration.json",
    ):
        with pytest.raises(ArtifactIntegrityError):
            BundleFile(filename, SHA_A)

    with pytest.raises(ArtifactIntegrityError, match="inert JSON"):
        # BundleFile is valid by itself; the executable calibration suffix is
        # rejected when the full manifest is assembled. Assert the lower-level
        # filename confinement here and the existing Worker suite covers manifest
        # uniqueness/suffix coupling.
        from routing_worker.model_jobs.artifact_bundle import ArtifactBundleManifest

        ArtifactBundleManifest(
            artifact=_artifact("model.txt", "LIGHTGBM_TEXT"),
            calibration=BundleFile("calibration.joblib", SHA_B),
            model_card=BundleFile("card.md", SHA_A),
            feature_schema=BundleFile("schema.json", SHA_B),
            dataset_sha256=SHA_A,
            metrics_sha256=SHA_B,
        )


def test_request_inputs_expose_no_artifact_path_uri_loader_or_format_selection() -> None:
    forbidden = {
        "artifact",
        "artifact_path",
        "artifact_uri",
        "bundle_directory",
        "loader",
        "model_path",
        "path",
        "uri",
        "format",
    }
    for value_type in (EtaPredictorInput, SeatRiskPredictorInput):
        names = {item.name.casefold() for item in fields(value_type)}
        assert names.isdisjoint(forbidden)


@pytest.mark.parametrize(
    "document",
    (
        '{"modelFamily":"ETA","modelFamily":"SEAT_RISK"}',
        '{"modelFamily":"ETA","modelVersion":NaN}',
        '["not-an-object"]',
        '{"unknown":"field"}',
    ),
)
def test_artifact_metadata_json_is_bounded_exact_and_duplicate_safe(
    tmp_path: Path, document: str
) -> None:
    path = tmp_path / "metadata.json"
    path.write_text(document, encoding="utf-8")
    with pytest.raises((ArtifactIntegrityError, ModelFoundationError)):
        load_artifact_metadata(path)

    path.write_text("x" * 33, encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="size limit"):
        load_artifact_metadata(path, max_bytes=32)


@pytest.mark.parametrize(
    "document",
    (
        '{"family":"ETA","family":"SEAT_RISK"}',
        '{"value":NaN}',
        '{"value":Infinity}',
        '["not-an-object"]',
        '{invalid-json}',
    ),
)
def test_native_runtime_json_rejects_duplicate_nonfinite_and_nonobject_values(
    tmp_path: Path, document: str
) -> None:
    path = tmp_path / "native.json"
    path.write_text(document, encoding="utf-8")
    with pytest.raises(ModelServingConfigurationError):
        _load_json(path)


def test_native_runtime_json_rejects_oversize_and_symlink_before_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "native.json"
    path.write_bytes(b"{" + b" " * 1_048_576 + b"}")
    with pytest.raises(ModelServingConfigurationError, match="byte limit"):
        _load_json(path)

    path.write_text("{}", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == path)
    with pytest.raises(ModelServingConfigurationError, match="symlink"):
        _load_json(path)
    monkeypatch.setattr(Path, "is_symlink", original)


def _eta_attestation() -> VerifiedEtaPredictorAttestation:
    return VerifiedEtaPredictorAttestation(
        "ETA",
        "eta-ri373",
        "eta-schema-ri373",
        ("route_id", "missing_flags"),
        SHA_A,
        SHA_A,
        "LIGHTGBM_TEXT",
        "eta-deployment-ri373",
        "prod",
        "ACTIVE",
        "ACTIVE",
        True,
        "CONFORMAL",
        SHA_B,
        SHA_B,
        "POSITION_MODEL",
    )


def _seat_attestation() -> VerifiedSeatRiskPredictorAttestation:
    return VerifiedSeatRiskPredictorAttestation(
        "SEAT_RISK",
        "seat-ri373",
        "seat-schema-ri373",
        ("remaining_seats", "missing_flags"),
        SHA_A,
        SHA_A,
        "LIGHTGBM_TEXT",
        "seat-deployment-ri373",
        "prod",
        "ACTIVE",
        "ACTIVE",
        True,
        "ISOTONIC",
        SHA_B,
        SHA_B,
        "MODEL_PREDICTED",
    )


def test_production_projection_rejects_generic_subclass_and_family_swapped_predictors() -> None:
    class Generic:
        attestation = _eta_attestation()

    class EtaSubclass(VerifiedEtaPredictor):
        pass

    class SeatSubclass(VerifiedSeatRiskPredictor):
        pass

    assert _verified_model_projection(Generic(), Generic(), "prod") is None
    assert (
        _verified_model_projection(
            object.__new__(EtaSubclass), object.__new__(SeatSubclass), "prod"
        )
        is None
    )

    forged_eta = object.__new__(VerifiedEtaPredictor)
    forged_seat = object.__new__(VerifiedSeatRiskPredictor)
    forged_eta._attestation = _seat_attestation()  # type: ignore[attr-defined]
    forged_seat._attestation = _eta_attestation()  # type: ignore[attr-defined]
    assert _verified_model_projection(forged_eta, forged_seat, "prod") is None

    for changes in (
        {"verified_artifact_sha256": "c" * 64},
        {"verified_calibration_sha256": "c" * 64},
        {"deployment_state": "CANARY"},
        {"readiness": "SHADOW"},
        {"calibrated": False},
        {"deployment_environment": "dev"},
    ):
        with pytest.raises(VerifiedPredictorConfigurationError):
            replace(_eta_attestation(), **changes)


def test_gits_traffic_query_requires_current_typed_identity_and_bounds_links() -> None:
    dependencies = fixture_fan_in_dependencies(fixture_scenario("R1"))
    envelope = dependencies.providers.transit(
        TransitSearchRequest(
            Coordinate(127.187456, 37.222345),
            Coordinate(127.111159, 37.394761),
            AS_OF,
        ),
        deadline=Deadline.after_ms(1_000),
    )
    leg = envelope.payload[0].legs[0]
    boarding = SimpleNamespace(lon=127.187456, lat=37.222345)
    alighting = SimpleNamespace(lon=127.111159, lat=37.394761)
    base = {
        "boarding": SimpleNamespace(coordinate=boarding),
        "alighting": SimpleNamespace(coordinate=alighting),
        "geometry": (boarding, alighting),
    }

    caller_only = SimpleNamespace(
        **base,
        traffic_link_external_ids=("caller-selected-link",),
        gits_road_link_identity=None,
    )
    assert (
        CanonicalFanInOptimizeRouteUseCase._traffic_context_query(
            caller_only, leg, AS_OF
        )
        is None
    )

    links = tuple(f"GITS-LINK-{index:03d}" for index in range(512))
    identity = GitsRoadLinkIdentity(
        link_external_ids=links,
        mapping_version="ri373-gits-map-v1",
        validity=ValidityWindow(AS_OF - timedelta(days=1), AS_OF + timedelta(days=1)),
    )
    trusted = SimpleNamespace(**base, gits_road_link_identity=identity)
    query = CanonicalFanInOptimizeRouteUseCase._traffic_context_query(
        trusted, leg, AS_OF
    )
    assert query is not None
    assert query.maximum_links == 512
    assert query.relevant_link_external_ids == links

    stale = SimpleNamespace(
        **base,
        gits_road_link_identity=GitsRoadLinkIdentity(
            link_external_ids=("GITS-LINK-STALE",),
            mapping_version="ri373-gits-map-v1",
            validity=ValidityWindow(
                AS_OF - timedelta(days=2), AS_OF - timedelta(seconds=1)
            ),
        ),
    )
    assert (
        CanonicalFanInOptimizeRouteUseCase._traffic_context_query(stale, leg, AS_OF)
        is None
    )

    with pytest.raises(ValueError):
        GitsRoadLinkIdentity(
            link_external_ids=tuple(f"LINK-{index:04d}" for index in range(513)),
            mapping_version="ri373-gits-map-v1",
            validity=ValidityWindow(AS_OF),
        )
