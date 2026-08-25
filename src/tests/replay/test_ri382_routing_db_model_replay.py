from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest

from bus_intelligence_core import (
    TRAFFIC_CONTEXT_SCHEMA_VERSION,
    WEATHER_CONTEXT_SCHEMA_VERSION,
    EtaCompleteFeatureVector,
    EtaFeatureContext,
    EtaNativePrediction,
    EtaPredictorInput,
    SeatRiskCompleteFeatureVector,
    SeatRiskFeatureContext,
    SeatRiskNativePrediction,
    SeatRiskPredictorInput,
    TrafficFeatureContext,
    VerifiedEtaPredictor,
    VerifiedEtaPredictorAttestation,
    VerifiedSeatRiskPredictor,
    VerifiedSeatRiskPredictorAttestation,
    WeatherFeatureContext,
)
from provider_core import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
    foundation_capability_registry,
)
from provider_core.named import ProviderAdapterSuite, ProviderAdapterSuiteConfig
from routing_api.container import (
    _reset_application_composition_for_tests,
    get_application,
    register_production_dependencies,
)
from routing_api.fanin_integration import (
    InMemoryOptimizationPersistence,
    fixture_fan_in_dependencies,
)
from routing_api.fixture_scenarios import fixture_scenario
from routing_api.production_composition import ProductionCompositionDependencies
from routing_api.tests.test_api import SECRET, FakeClock
from routing_worker.data_quality.dataset_foundation import (
    TargetStopObservation,
    build_target_stop_labels,
)
from routing_worker.feature_builder import build_eta_features, build_seat_features
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
from routing_worker.postgres_serving import (
    ETA_POINT_IN_TIME_SQL,
    SEAT_RISK_POINT_IN_TIME_SQL,
    PostgresEtaServingFeatureSource,
    PostgresSeatRiskServingFeatureSource,
)
from routing_worker.model_deployment import (
    ApprovedBundleMaterialization,
    FixedArtifactBundleResolver,
    ModelDeploymentAssemblyError,
    PostgresActiveModelPairSource,
    VerifiedModelPairAssembler,
    VerifiedModelPredictorPair,
)
from routing_worker.native_lightgbm import (
    LightGbmEtaRuntimeLoader,
    LightGbmSeatRiskRuntimeLoader,
)
from routing_worker.serving_features import (
    DurableEtaCompleteVectorBuilder,
    DurableSeatRiskCompleteVectorBuilder,
)


UTC = timezone.utc
AS_OF = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
OBSERVED_AT = AS_OF - timedelta(seconds=10)
TRIP_ID = UUID("00000000-0000-0000-0000-000000000021")
ROUTE_ID = UUID("00000000-0000-0000-0000-000000000022")
BOARDING_ID = UUID("00000000-0000-0000-0000-000000000023")
TARGET_ID = UUID("00000000-0000-0000-0000-000000000024")


class _Cursor:
    def __init__(
        self,
        rows: list[tuple[Any, ...]],
        *,
        fail_statement: str | None = None,
    ) -> None:
        self.rows = rows
        self.fail_statement = fail_statement
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False
        self.rowcount = 0

    def execute(
        self, operation: str, parameters: tuple[Any, ...] = ()
    ) -> None:
        self.executions.append((operation, parameters))
        if self.fail_statement == operation:
            raise TimeoutError("sanitized Routing-DB timeout")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self.cursor_value = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> _Cursor:
        return self.cursor_value

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _Factory:
    def __init__(
        self,
        rows: list[tuple[Any, ...]],
        *,
        fail_statement: str | None = None,
    ) -> None:
        self.rows = rows
        self.fail_statement = fail_statement
        self.connections: list[_Connection] = []

    def __call__(self) -> _Connection:
        connection = _Connection(
            _Cursor(list(self.rows), fail_statement=self.fail_statement)
        )
        self.connections.append(connection)
        return connection

    @property
    def calls(self) -> int:
        return len(self.connections)

    @property
    def executions(self) -> list[tuple[str, tuple[Any, ...]]]:
        return [
            execution
            for connection in self.connections
            for execution in connection.cursor_value.executions
        ]


def _eta_input(**changes: object) -> EtaPredictorInput:
    values: dict[str, object] = {
        "vehicle_ref": "vehicle-token",
        "route_id": str(ROUTE_ID),
        "direction": "UP",
        "boarding_stop_id": str(BOARDING_ID),
        "observed_at": OBSERVED_AT,
        "remain_seat_observed": 0,
        "prediction_at": AS_OF,
        "feature_context": _contexts()[0],
    }
    values.update(changes)
    return EtaPredictorInput(**values)  # type: ignore[arg-type]


def _seat_input(**changes: object) -> SeatRiskPredictorInput:
    values: dict[str, object] = {
        "vehicle_ref": "vehicle-token",
        "route_id": str(ROUTE_ID),
        "direction": "UP",
        "boarding_stop_id": str(BOARDING_ID),
        "target_stop_id": str(TARGET_ID),
        "observed_at": OBSERVED_AT,
        "prediction_at": AS_OF,
        "remain_seat_observed": 0,
        "feature_context": _contexts()[1],
    }
    values.update(changes)
    return SeatRiskPredictorInput(**values)  # type: ignore[arg-type]


def _eta_row(**changes: object) -> tuple[Any, ...]:
    values: list[Any] = [
        TRIP_ID,
        ROUTE_ID,
        "UP",
        "vehicle-token",
        BOARDING_ID,
        4,
        8,
        OBSERVED_AT,
        OBSERVED_AT + timedelta(seconds=1),
        Decimal("0"),
        Decimal("180"),
        Decimal("300"),
        Decimal("64"),
        Decimal("0"),
        [],
    ]
    indexes = {
        "trip_id": 0,
        "route_id": 1,
        "direction": 2,
        "vehicle_ref": 3,
        "boarding_stop_id": 4,
        "current_sequence": 5,
        "target_sequence": 6,
        "observed_at": 7,
        "ingested_at": 8,
        "recent_1": 9,
        "recent_3": 10,
        "recent_5": 11,
        "historical": 12,
        "headway": 13,
        "quality_flags": 14,
    }
    for key, value in changes.items():
        values[indexes[key]] = value
    return tuple(values)


def _seat_row(**changes: object) -> tuple[Any, ...]:
    values: list[Any] = [
        TRIP_ID,
        ROUTE_ID,
        "UP",
        "vehicle-token",
        BOARDING_ID,
        TARGET_ID,
        4,
        8,
        OBSERVED_AT,
        OBSERVED_AT + timedelta(seconds=1),
        0,
        0,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        [],
        1,
        2,
    ]
    indexes = {
        "trip_id": 0,
        "route_id": 1,
        "direction": 2,
        "vehicle_ref": 3,
        "boarding_stop_id": 4,
        "target_stop_id": 5,
        "current_sequence": 6,
        "target_sequence": 7,
        "observed_at": 8,
        "ingested_at": 9,
        "remaining": 10,
        "crowded": 11,
        "confidence": 12,
        "delta": 13,
        "headway": 14,
        "quality_flags": 15,
        "assertion_count": 16,
        "evidence_count": 17,
    }
    for key, value in changes.items():
        values[indexes[key]] = value
    return tuple(values)


def _contexts() -> tuple[EtaFeatureContext, SeatRiskFeatureContext]:
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
    return EtaFeatureContext(weather, traffic), SeatRiskFeatureContext(
        weather, traffic
    )


def _enabled_transit_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        (
            Capability(
                "KAKAO_PUBLIC_TRANSIT",
                "search_current",
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )


def _assert_closed_snapshot(factory: _Factory) -> None:
    assert factory.calls == 1
    connection = factory.connections[0]
    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.cursor_value.closed
    assert connection.closed
    statements = [statement for statement, _ in factory.executions]
    assert statements[0] == (
        "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    assert "statement_timeout" in statements[1]
    assert "lock_timeout" in statements[2]
    assert "idle_in_transaction_session_timeout" in statements[3]


def test_db_rows_build_exact_22_field_train_serve_vectors_and_valid_empty_flags() -> None:
    eta_context, seat_context = _contexts()
    eta_factory = _Factory([_eta_row()])
    seat_factory = _Factory([_seat_row()])
    eta_record = PostgresEtaServingFeatureSource(eta_factory).load(_eta_input())
    seat_record = PostgresSeatRiskServingFeatureSource(seat_factory).load(
        _seat_input()
    )
    assert eta_record is not None and seat_record is not None
    assert eta_record.observation.recent_segment_seconds_1 == 0.0
    assert eta_record.observation.headway_seconds == 0.0
    assert seat_record.observation.current_remaining_seats == 0
    assert seat_record.observation.current_crowded_code == 0
    assert seat_record.observation.capacity_confidence == 0.0
    assert seat_record.observation.recent_seat_delta == 0.0
    assert seat_record.observation.headway_seconds == 0.0
    _assert_closed_snapshot(eta_factory)
    _assert_closed_snapshot(seat_factory)

    eta_train = build_eta_features(
        replace(eta_record.observation, eta_feature_context=eta_context)
    )
    seat_train = build_seat_features(
        replace(seat_record.observation, seat_risk_feature_context=seat_context)
    )
    eta_serve = DurableEtaCompleteVectorBuilder(
        PostgresEtaServingFeatureSource(_Factory([_eta_row()]))
    ).build(_eta_input())
    seat_serve = DurableSeatRiskCompleteVectorBuilder(
        PostgresSeatRiskServingFeatureSource(_Factory([_seat_row()]))
    ).build(_seat_input())
    assert eta_serve is not None and seat_serve is not None
    assert len(eta_serve.feature_names) == len(seat_serve.feature_names) == 22
    assert (
        eta_train.schema_version,
        eta_train.feature_names,
        eta_train.values,
        eta_train.missing_flags,
    ) == (
        eta_serve.schema_version,
        eta_serve.feature_names,
        eta_serve.values,
        eta_serve.missing_flags,
    )
    assert (
        seat_train.schema_version,
        seat_train.feature_names,
        seat_train.values,
        seat_train.missing_flags,
    ) == (
        seat_serve.schema_version,
        seat_serve.feature_names,
        seat_serve.values,
        seat_serve.missing_flags,
    )
    for family, trained, served in (
        ("ETA", eta_train, eta_serve),
        ("SEAT_RISK", seat_train, seat_serve),
    ):
        assert trained.missing_flags == served.missing_flags == ()
        assert trained.as_mapping["context_missing_flags"] == ""
        assert trained.as_mapping["missing_flags"] == ""
        assert encode_feature_mapping(
            family=family,
            feature_schema_version=trained.schema_version,
            feature_names=trained.feature_names,
            values=trained.as_mapping,
        ) == encode_feature_values(
            family=family,
            feature_schema_version=served.schema_version,
            feature_names=served.feature_names,
            values=served.values,
        )


@pytest.mark.parametrize(
    ("family", "rows", "input_changes", "failure"),
    (
        ("ETA", [], {}, None),
        ("ETA", [_eta_row(), _eta_row()], {}, None),
        ("ETA", [_eta_row()[:-1]], {}, None),
        ("ETA", [_eta_row(vehicle_ref="different")], {}, None),
        (
            "ETA",
            [_eta_row(ingested_at=AS_OF + timedelta(seconds=1))],
            {},
            None,
        ),
        ("ETA", [], {"route_id": "not-a-uuid"}, None),
        ("ETA", [], {}, ETA_POINT_IN_TIME_SQL),
        ("SEAT_RISK", [], {}, None),
        ("SEAT_RISK", [_seat_row(), _seat_row()], {}, None),
        ("SEAT_RISK", [_seat_row()[:-1]], {}, None),
        ("SEAT_RISK", [_seat_row(target_stop_id=BOARDING_ID)], {}, None),
        (
            "SEAT_RISK",
            [_seat_row(ingested_at=AS_OF + timedelta(seconds=1))],
            {},
            None,
        ),
        ("SEAT_RISK", [_seat_row(assertion_count=2)], {}, None),
        ("SEAT_RISK", [], {"target_stop_id": "not-a-uuid"}, None),
        ("SEAT_RISK", [], {}, SEAT_RISK_POINT_IN_TIME_SQL),
    ),
)
def test_db_source_missing_ambiguous_malformed_future_identity_and_timeout_fail_closed(
    family: str,
    rows: list[tuple[Any, ...]],
    input_changes: dict[str, object],
    failure: str | None,
) -> None:
    factory = _Factory(rows, fail_statement=failure)
    if family == "ETA":
        result = PostgresEtaServingFeatureSource(factory).load(
            _eta_input(**input_changes)
        )
    else:
        result = PostgresSeatRiskServingFeatureSource(factory).load(
            _seat_input(**input_changes)
        )
    assert result is None
    if input_changes:
        assert factory.calls == 0
    else:
        _assert_closed_snapshot(factory)


class _EtaRuntime:
    family = "ETA"
    model_version = "eta-db-replay-v1"
    artifact_sha256 = "a" * 64
    artifact_format = "LIGHTGBM_TEXT"
    calibration_sha256 = "b" * 64

    def __init__(self) -> None:
        self.inputs: list[EtaCompleteFeatureVector] = []

    def predict(self, value: EtaCompleteFeatureVector) -> EtaNativePrediction:
        self.inputs.append(value)
        return EtaNativePrediction(121, 180, 0.81)


class _SeatRuntime:
    family = "SEAT_RISK"
    model_version = "seat-db-replay-v1"
    artifact_sha256 = "c" * 64
    artifact_format = "LIGHTGBM_TEXT"
    calibration_sha256 = "d" * 64

    def __init__(self) -> None:
        self.inputs: list[SeatRiskCompleteFeatureVector] = []

    def predict(
        self, value: SeatRiskCompleteFeatureVector
    ) -> SeatRiskNativePrediction:
        self.inputs.append(value)
        return SeatRiskNativePrediction(0.05, 0.25, 0.70, 0.82)


def _verified_pair() -> tuple[
    VerifiedEtaPredictor,
    VerifiedSeatRiskPredictor,
    _Factory,
    _Factory,
    _EtaRuntime,
    _SeatRuntime,
]:
    eta_factory = _Factory([_eta_row()])
    seat_factory = _Factory([_seat_row()])
    eta_runtime = _EtaRuntime()
    seat_runtime = _SeatRuntime()
    eta_attestation = VerifiedEtaPredictorAttestation(
        family="ETA",
        model_version=eta_runtime.model_version,
        full_feature_schema_version=ETA_SCHEMA_VERSION,
        ordered_feature_names=ETA_FEATURE_NAMES,
        artifact_sha256=eta_runtime.artifact_sha256,
        verified_artifact_sha256=eta_runtime.artifact_sha256,
        artifact_format=eta_runtime.artifact_format,
        deployment_id="eta-db-deployment-v1",
        deployment_environment="staging",
        deployment_state="ACTIVE",
        readiness="ACTIVE",
        calibrated=True,
        calibration_method="CONFORMAL",
        calibration_sha256=eta_runtime.calibration_sha256,
        verified_calibration_sha256=eta_runtime.calibration_sha256,
        source="POSITION_MODEL",
    )
    seat_attestation = VerifiedSeatRiskPredictorAttestation(
        family="SEAT_RISK",
        model_version=seat_runtime.model_version,
        full_feature_schema_version=SEAT_SCHEMA_VERSION,
        ordered_feature_names=SEAT_FEATURE_NAMES,
        artifact_sha256=seat_runtime.artifact_sha256,
        verified_artifact_sha256=seat_runtime.artifact_sha256,
        artifact_format=seat_runtime.artifact_format,
        deployment_id="seat-db-deployment-v1",
        deployment_environment="staging",
        deployment_state="ACTIVE",
        readiness="ACTIVE",
        calibrated=True,
        calibration_method="ISOTONIC",
        calibration_sha256=seat_runtime.calibration_sha256,
        verified_calibration_sha256=seat_runtime.calibration_sha256,
        origin="MODEL_PREDICTED",
    )
    eta = VerifiedEtaPredictor(
        DurableEtaCompleteVectorBuilder(
            PostgresEtaServingFeatureSource(eta_factory)
        ),
        eta_runtime,
        eta_attestation,
        expected_feature_schema_version=ETA_SCHEMA_VERSION,
        expected_feature_names=ETA_FEATURE_NAMES,
        required_environment="staging",
    )
    seat = VerifiedSeatRiskPredictor(
        DurableSeatRiskCompleteVectorBuilder(
            PostgresSeatRiskServingFeatureSource(seat_factory)
        ),
        seat_runtime,
        seat_attestation,
        expected_feature_schema_version=SEAT_SCHEMA_VERSION,
        expected_feature_names=SEAT_FEATURE_NAMES,
        required_environment="staging",
    )
    return eta, seat, eta_factory, seat_factory, eta_runtime, seat_runtime


class _FakeBooster:
    def __init__(self, module: "_FakeLightGbm") -> None:
        self.module = module
        self.params = module.parameters

    def feature_name(self) -> list[str]:
        return list(self.module.names)

    def predict(self, matrix: list[list[float]]) -> list[object]:
        self.module.matrices.append(matrix)
        return [self.module.output]


class _FakeLightGbm:
    def __init__(
        self,
        names: tuple[str, ...],
        output: object,
        parameters: dict[str, object],
    ) -> None:
        self.names = names
        self.output = output
        self.parameters = parameters
        self.loaded_paths: list[str] = []
        self.matrices: list[list[list[float]]] = []

    def Booster(self, *, model_file: str) -> _FakeBooster:  # noqa: N802
        self.loaded_paths.append(model_file)
        return _FakeBooster(self)


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _write_bundle(root: Path, family: str) -> dict[str, object]:
    root.mkdir(parents=True)
    model = f"safe {family} native replay fixture\n".encode()
    schema = json.dumps(
        feature_schema_document(family=family), separators=(",", ":")
    ).encode()
    if family == "ETA":
        names = ETA_FEATURE_NAMES
        calibration_method = "CONFORMAL"
        calibration_value: dict[str, object] = {
            "schemaVersion": "eta-calibration-v1",
            "family": "ETA",
            "method": calibration_method,
            "confidence": 0.81,
            "p90OffsetSeconds": 59,
        }
    else:
        names = SEAT_FEATURE_NAMES
        calibration_method = "PLATT"
        calibration_value = {
            "schemaVersion": "seat-risk-calibration-v1",
            "family": "SEAT_RISK",
            "method": calibration_method,
            "confidence": 0.82,
            "parameters": [
                {"slope": 1.0, "intercept": 0.0},
                {"slope": 1.0, "intercept": 0.0},
                {"slope": 1.0, "intercept": 0.0},
            ],
        }
    calibration = json.dumps(calibration_value, separators=(",", ":")).encode()
    card = f"# {family} RI-382 sanitized replay card\n".encode()
    files = {
        "model.txt": model,
        "calibration.json": calibration,
        "feature-schema.json": schema,
        "model-card.md": card,
    }
    for filename, payload in files.items():
        (root / filename).write_bytes(payload)
    return {
        "schemaVersion": "worker-serving-evidence-v1",
        "artifactFormat": "LIGHTGBM_TEXT",
        "artifactFilename": "model.txt",
        "featureNames": list(names),
        "modelCardFilename": "model-card.md",
        "modelCardSha256": _digest(card),
        "calibrationFilename": "calibration.json",
        "calibrationMethod": calibration_method,
        "calibrationSha256": _digest(calibration),
        "featureSchemaFilename": "feature-schema.json",
        "featureSchemaSha256": _digest(schema),
        "datasetSha256": "d" * 64,
        "metricsSha256": "e" * 64,
        "validationEvidenceSha256": "f" * 64,
        "registryStateVersion": 7,
        "registryUpdatedAt": "2026-08-23T10:00:00+00:00",
        "artifactSha256": _digest(model),
    }


def _active_row(
    *,
    purpose: str,
    model_version: str,
    artifact_uri: str,
    evidence: dict[str, object],
    model_id: str,
    deployment_id: str,
) -> tuple[Any, ...]:
    family = "ETA" if purpose == "BUS_ETA" else "SEAT_RISK"
    schema = ETA_SCHEMA_VERSION if family == "ETA" else SEAT_SCHEMA_VERSION
    serving_evidence = dict(evidence)
    artifact_sha256 = str(serving_evidence.pop("artifactSha256"))
    training_scope = {
        "trainingWindow": "sanitized-ri382",
        "missingTargetPolicy": "EXCLUDE_UNOBSERVED",
        "splitPolicy": "TEMPORAL_TRIP_GROUP_PURGED",
        "calibrationSha256": serving_evidence["calibrationSha256"],
        "datasetSha256": serving_evidence["datasetSha256"],
        "modelCardSha256": serving_evidence["modelCardSha256"],
        "servingEvidence": serving_evidence,
    }
    return (
        purpose,
        UUID(model_id),
        model_version,
        "ACTIVE",
        artifact_uri,
        artifact_sha256,
        schema,
        training_scope,
        datetime(2026, 8, 23, 9, 0, tzinfo=UTC),
        UUID(deployment_id),
        "staging",
        "ACTIVE",
        Decimal("1"),
        datetime(2026, 8, 23, 11, 0, tzinfo=UTC),
        None,
    )


@pytest.mark.parametrize(
    ("outer_field", "replacement", "message"),
    (
        (
            "missingTargetPolicy",
            "IMPUTE_ZERO",
            "missing-target policy is not serving-safe",
        ),
        (
            "splitPolicy",
            "RANDOM_ROW",
            "split policy is not serving-safe",
        ),
        (
            "calibrationSha256",
            "a" * 64,
            "training_scope and servingEvidence calibrationSha256 differ",
        ),
        (
            "datasetSha256",
            "a" * 64,
            "training_scope and servingEvidence datasetSha256 differ",
        ),
        (
            "modelCardSha256",
            "a" * 64,
            "training_scope and servingEvidence modelCardSha256 differ",
        ),
    ),
)
def test_active_lifecycle_rejects_train_serve_policy_or_digest_drift(
    tmp_path: Path,
    outer_field: str,
    replacement: str,
    message: str,
) -> None:
    eta_evidence = _write_bundle(tmp_path / "eta-lifecycle", "ETA")
    seat_evidence = _write_bundle(tmp_path / "seat-lifecycle", "SEAT_RISK")
    eta_row = _active_row(
        purpose="BUS_ETA",
        model_version="eta-active-ri382-lifecycle-v1",
        artifact_uri="gs://approved-models/ri382/lifecycle/eta/model.txt",
        evidence=eta_evidence,
        model_id="00000000-0000-0000-0000-000000000211",
        deployment_id="00000000-0000-0000-0000-000000000212",
    )
    eta_scope = dict(eta_row[7])
    eta_scope[outer_field] = replacement
    eta_row = (*eta_row[:7], eta_scope, *eta_row[8:])
    seat_row = _active_row(
        purpose="SEAT_RISK",
        model_version="seat-active-ri382-lifecycle-v1",
        artifact_uri="gs://approved-models/ri382/lifecycle/seat/model.txt",
        evidence=seat_evidence,
        model_id="00000000-0000-0000-0000-000000000213",
        deployment_id="00000000-0000-0000-0000-000000000214",
    )

    with pytest.raises(ModelDeploymentAssemblyError, match=message):
        PostgresActiveModelPairSource(
            _Factory([eta_row, seat_row]), as_of=AS_OF
        ).load("staging")


def _replace_lifecycle_time(
    row: tuple[Any, ...], field: str, value: datetime
) -> tuple[Any, ...]:
    if field == "created_at":
        return (*row[:8], value, *row[9:])
    if field == "activated_at":
        return (*row[:13], value, *row[14:])
    scope = dict(row[7])
    serving_evidence = dict(scope["servingEvidence"])
    serving_evidence["registryUpdatedAt"] = value.isoformat()
    scope["servingEvidence"] = serving_evidence
    return (*row[:7], scope, *row[8:])


def _lifecycle_replay_rows(tmp_path: Path) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    eta_evidence = _write_bundle(tmp_path / "eta-time", "ETA")
    seat_evidence = _write_bundle(tmp_path / "seat-time", "SEAT_RISK")
    return (
        _active_row(
            purpose="BUS_ETA",
            model_version="eta-active-ri382-time-v1",
            artifact_uri="gs://approved-models/ri382/time/eta/model.txt",
            evidence=eta_evidence,
            model_id="00000000-0000-0000-0000-000000000221",
            deployment_id="00000000-0000-0000-0000-000000000222",
        ),
        _active_row(
            purpose="SEAT_RISK",
            model_version="seat-active-ri382-time-v1",
            artifact_uri="gs://approved-models/ri382/time/seat/model.txt",
            evidence=seat_evidence,
            model_id="00000000-0000-0000-0000-000000000223",
            deployment_id="00000000-0000-0000-0000-000000000224",
        ),
    )


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("created_at", "model created_at is after startup as_of"),
        ("registry_updated_at", "registry updated_at is after startup as_of"),
        ("activated_at", "deployment activated_at is after startup as_of"),
    ),
)
def test_active_lifecycle_rejects_future_timestamp_against_immutable_startup_as_of(
    tmp_path: Path,
    field: str,
    message: str,
) -> None:
    eta_row, seat_row = _lifecycle_replay_rows(tmp_path)
    eta_row = _replace_lifecycle_time(
        eta_row, field, AS_OF + timedelta(microseconds=1)
    )
    factory = _Factory([eta_row, seat_row])

    with pytest.raises(ModelDeploymentAssemblyError, match=message):
        PostgresActiveModelPairSource(factory, as_of=AS_OF).load("staging")

    assert any(parameters == ("staging", AS_OF) for _, parameters in factory.executions)


def test_active_lifecycle_accepts_timestamps_equal_to_immutable_startup_as_of(
    tmp_path: Path,
) -> None:
    eta_row, seat_row = _lifecycle_replay_rows(tmp_path)
    rows = [
        _replace_lifecycle_time(
            _replace_lifecycle_time(
                _replace_lifecycle_time(row, "created_at", AS_OF),
                "registry_updated_at",
                AS_OF,
            ),
            "activated_at",
            AS_OF,
        )
        for row in (eta_row, seat_row)
    ]
    factory = _Factory(rows)

    pair = PostgresActiveModelPairSource(factory, as_of=AS_OF).load("staging")

    assert pair.eta.lifecycle.registry_entry.registered_at == AS_OF
    assert pair.eta.lifecycle.registry_entry.updated_at == AS_OF
    assert pair.eta.lifecycle.deployment.activated_at == AS_OF
    assert any(parameters == ("staging", AS_OF) for _, parameters in factory.executions)


def _assembled_pair(
    tmp_path: Path,
) -> tuple[
    VerifiedModelPredictorPair,
    _Factory,
    _Factory,
    _Factory,
    _FakeLightGbm,
    _FakeLightGbm,
]:
    eta_root = tmp_path / "eta"
    seat_root = tmp_path / "seat"
    eta_evidence = _write_bundle(eta_root, "ETA")
    seat_evidence = _write_bundle(seat_root, "SEAT_RISK")
    eta_uri = "gs://approved-models/ri382/eta/model.txt"
    seat_uri = "gs://approved-models/ri382/seat/model.txt"
    lifecycle_factory = _Factory(
        [
            _active_row(
                purpose="BUS_ETA",
                model_version="eta-active-ri382-v1",
                artifact_uri=eta_uri,
                evidence=eta_evidence,
                model_id="00000000-0000-0000-0000-000000000201",
                deployment_id="00000000-0000-0000-0000-000000000202",
            ),
            _active_row(
                purpose="SEAT_RISK",
                model_version="seat-active-ri382-v1",
                artifact_uri=seat_uri,
                evidence=seat_evidence,
                model_id="00000000-0000-0000-0000-000000000203",
                deployment_id="00000000-0000-0000-0000-000000000204",
            ),
        ]
    )
    eta_factory = _Factory([_eta_row()])
    seat_factory = _Factory([_seat_row()])
    eta_module = _FakeLightGbm(
        ETA_FEATURE_NAMES, 121.0, {"objective": "regression"}
    )
    seat_module = _FakeLightGbm(
        SEAT_FEATURE_NAMES,
        [0.05, 0.20, 0.45, 0.30],
        {"objective": "multiclass", "num_class": 4},
    )
    assembler = VerifiedModelPairAssembler(
        lifecycle_source=PostgresActiveModelPairSource(
            lifecycle_factory, as_of=AS_OF
        ),
        bundle_resolver=FixedArtifactBundleResolver(
            bundle_root=tmp_path,
            materializations=(
                ApprovedBundleMaterialization(
                    "ETA",
                    "eta-active-ri382-v1",
                    eta_uri,
                    str(eta_evidence["artifactSha256"]),
                    eta_root,
                ),
                ApprovedBundleMaterialization(
                    "SEAT_RISK",
                    "seat-active-ri382-v1",
                    seat_uri,
                    str(seat_evidence["artifactSha256"]),
                    seat_root,
                ),
            ),
        ),
        eta_feature_source=PostgresEtaServingFeatureSource(eta_factory),
        seat_risk_feature_source=PostgresSeatRiskServingFeatureSource(
            seat_factory
        ),
        eta_runtime_loader=LightGbmEtaRuntimeLoader(eta_module),
        seat_risk_runtime_loader=LightGbmSeatRiskRuntimeLoader(seat_module),
        environment="staging",
    )
    return (
        assembler.assemble(),
        lifecycle_factory,
        eta_factory,
        seat_factory,
        eta_module,
        seat_module,
    )


def test_verified_wrappers_keep_sql_artifact_calibration_and_provenance_independent() -> None:
    eta, seat, eta_factory, seat_factory, eta_runtime, seat_runtime = (
        _verified_pair()
    )
    eta_prediction = eta.predict(_eta_input())
    seat_prediction = seat.predict(_seat_input())
    assert eta_prediction is not None and seat_prediction is not None
    assert eta_prediction.p50_arrival_at == AS_OF + timedelta(seconds=121)
    assert eta_prediction.p90_arrival_at == AS_OF + timedelta(seconds=180)
    assert eta_prediction.source == "POSITION_MODEL"
    assert eta_prediction.model_version == "eta-db-replay-v1"
    assert seat_prediction.model_version == "seat-db-replay-v1"
    assert seat_prediction.origin == "MODEL_PREDICTED"
    assert (
        seat_prediction.no_seat_probability,
        seat_prediction.low_seat2_probability,
        seat_prediction.low_seat5_probability,
    ) == pytest.approx((0.05, 0.25, 0.70))
    assert eta.attestation.calibration_method == "CONFORMAL"
    assert seat.attestation.calibration_method == "ISOTONIC"
    assert eta.attestation.artifact_sha256 != seat.attestation.artifact_sha256
    assert eta.attestation.calibration_sha256 != (
        seat.attestation.calibration_sha256
    )
    assert eta_factory.executions[-1][0] is ETA_POINT_IN_TIME_SQL
    assert seat_factory.executions[-1][0] is SEAT_RISK_POINT_IN_TIME_SQL
    assert ETA_POINT_IN_TIME_SQL not in [value[0] for value in seat_factory.executions]
    assert SEAT_RISK_POINT_IN_TIME_SQL not in [
        value[0] for value in eta_factory.executions
    ]
    assert eta_runtime.inputs[0].feature_names == ETA_FEATURE_NAMES
    assert seat_runtime.inputs[0].feature_names == SEAT_FEATURE_NAMES


def test_stale_feature_rows_and_missing_future_targets_are_null_not_zero() -> None:
    stale_at = AS_OF - timedelta(seconds=301)
    stale_eta = VerifiedEtaPredictor(
        DurableEtaCompleteVectorBuilder(
            PostgresEtaServingFeatureSource(
                _Factory(
                    [
                        _eta_row(
                            observed_at=stale_at,
                            ingested_at=stale_at + timedelta(seconds=1),
                        )
                    ]
                )
            )
        ),
        _EtaRuntime(),
        _verified_pair()[0].attestation,
        expected_feature_schema_version=ETA_SCHEMA_VERSION,
        expected_feature_names=ETA_FEATURE_NAMES,
        required_environment="staging",
    )
    assert stale_eta.predict(_eta_input(observed_at=stale_at)) is None

    unavailable = build_target_stop_labels(
        trip_id=str(TRIP_ID),
        target_stop_id=str(TARGET_ID),
        feature_observed_at=AS_OF,
        observations=(
            TargetStopObservation(str(TRIP_ID), str(TARGET_ID), AS_OF, 0),
            TargetStopObservation(
                "different-trip",
                str(TARGET_ID),
                AS_OF + timedelta(seconds=30),
                0,
            ),
        ),
    )
    missing_seat = build_target_stop_labels(
        trip_id=str(TRIP_ID),
        target_stop_id=str(TARGET_ID),
        feature_observed_at=AS_OF,
        observations=(
            TargetStopObservation(
                str(TRIP_ID),
                str(TARGET_ID),
                AS_OF + timedelta(seconds=30),
                None,
            ),
        ),
    )
    observed_zero = build_target_stop_labels(
        trip_id=str(TRIP_ID),
        target_stop_id=str(TARGET_ID),
        feature_observed_at=AS_OF,
        observations=(
            TargetStopObservation(
                str(TRIP_ID),
                str(TARGET_ID),
                AS_OF + timedelta(seconds=30),
                0,
            ),
        ),
    )
    assert unavailable.eta_seconds.value is None
    assert not unavailable.eta_seconds.has_target
    assert unavailable.seat_ordinal_class.value is None
    assert not unavailable.seat_ordinal_class.has_target
    assert missing_seat.eta_seconds.value == 30
    assert not missing_seat.seat_ordinal_class.has_target
    assert observed_zero.seat_ordinal_class.has_target
    assert observed_zero.seat_ordinal_class.value == 0
    assert observed_zero.no_seat.value is True


def test_verified_db_pair_reaches_one_shot_api_injection_as_bus_owned_wrappers(
    tmp_path: Path,
) -> None:
    class _NoNetwork:
        def send(self, request):
            raise AssertionError(f"production replay attempted network I/O: {request}")

    (
        pair,
        lifecycle_factory,
        eta_factory,
        seat_factory,
        eta_module,
        seat_module,
    ) = _assembled_pair(tmp_path)
    eta = pair.eta
    seat = pair.seat_risk
    eta_prediction = eta.predict(_eta_input())
    seat_prediction = seat.predict(_seat_input())
    assert eta_prediction is not None and seat_prediction is not None
    assert eta_prediction.p50_arrival_at == AS_OF + timedelta(seconds=121)
    assert eta_prediction.p90_arrival_at == AS_OF + timedelta(seconds=180)
    assert eta_prediction.model_version == "eta-active-ri382-v1"
    assert seat_prediction.model_version == "seat-active-ri382-v1"
    assert (
        seat_prediction.no_seat_probability,
        seat_prediction.low_seat2_probability,
        seat_prediction.low_seat5_probability,
    ) == pytest.approx((0.05, 0.25, 0.70))
    assert lifecycle_factory.calls == eta_factory.calls == seat_factory.calls == 1
    assert eta_factory.executions[-1][0] is ETA_POINT_IN_TIME_SQL
    assert seat_factory.executions[-1][0] is SEAT_RISK_POINT_IN_TIME_SQL
    assert len(eta_module.loaded_paths) == len(seat_module.loaded_paths) == 1
    assert eta_module.loaded_paths[0] != seat_module.loaded_paths[0]
    assert eta.attestation.artifact_sha256 != seat.attestation.artifact_sha256
    assert eta.attestation.calibration_sha256 != seat.attestation.calibration_sha256
    registry = _enabled_transit_registry()
    dependencies = ProductionCompositionDependencies(
        provider_config=ProviderAdapterSuiteConfig(capabilities=registry),
        mapping_database=object(),
        persistence=InMemoryOptimizationPersistence(),
        eta_predictor=eta,
        seat_predictor=seat,
        capability_registry=registry,
        deployment_environment="staging",
    )
    suite = ProviderAdapterSuite(_NoNetwork())
    fixture = fixture_fan_in_dependencies(fixture_scenario("R1"))
    worker_modules_before = {
        name for name in sys.modules if name == "routing_worker" or name.startswith("routing_worker.")
    }

    _reset_application_composition_for_tests()
    try:
        register_production_dependencies(dependencies)
        with (
            patch.object(ProviderAdapterSuite, "from_config", return_value=suite),
            patch(
                "routing_api.production_composition._executable_provider_operations",
                return_value=frozenset(
                    {("KAKAO_PUBLIC_TRANSIT", "search_current")}
                ),
            ),
            patch(
                "routing_api.production_composition.PostgisMappingResolver",
                return_value=fixture.mapping,
            ),
            patch(
                "routing_api.container.settings",
                SimpleNamespace(
                    ROUTING_FIXTURE_SCENARIO="",
                    ROUTING_ALLOW_FIXTURE_BACKEND=False,
                    ROUTING_RUNTIME_ENVIRONMENT="TEST",
                    ROUTING_SERVICE_JWT_SECRET=SECRET.decode("utf-8"),
                    ROUTING_SERVICE_JWT_ISSUER="service-api",
                    ROUTING_SERVICE_JWT_AUDIENCE="routing-api",
                    ROUTING_BUILD_VERSION="ri382-replay",
                ),
            ),
        ):
            application = get_application()

        assert application.readiness()["checks"] == {
            "contract": "ready",
            "backend": "production",
            "providers": "ready",
            "models": "ready",
        }
        assert application.version()["models"] == [
            {"purpose": "BUS_ETA", "version": "eta-active-ri382-v1"},
            {"purpose": "SEAT_RISK", "version": "seat-active-ri382-v1"},
        ]
        use_case = application._use_case  # noqa: SLF001 - cross-package seam replay
        assert use_case._dependencies.eta_predictor is eta  # noqa: SLF001
        assert use_case._dependencies.seat_predictor is seat  # noqa: SLF001
        assert type(eta) is VerifiedEtaPredictor
        assert type(seat) is VerifiedSeatRiskPredictor
        assert {
            name
            for name in sys.modules
            if name == "routing_worker" or name.startswith("routing_worker.")
        } == worker_modules_before
    finally:
        _reset_application_composition_for_tests()

    foundation = foundation_capability_registry()
    assert all(value.fixture_only and not value.enabled for value in foundation.all())


def test_api_package_imports_without_worker_package_on_its_pythonpath() -> None:
    root = Path(__file__).resolve().parents[3]
    paths = (
        root / "src/services/routing-api",
        root / "src/packages/provider-core",
        root / "src/packages/bus-intelligence-core",
        root / "src/packages/routing-domain",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in paths)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    script = (
        "import sys; "
        "import routing_api.container; "
        "import routing_api.production_composition; "
        "assert not any(n == 'routing_worker' or n.startswith('routing_worker.') "
        "for n in sys.modules); "
        "print('API_WITHOUT_WORKER_OK')"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "API_WITHOUT_WORKER_OK"
