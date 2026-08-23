from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import inspect
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bus_intelligence_core import VerifiedEtaPredictor, VerifiedSeatRiskPredictor

from routing_worker.feature_encoding import feature_schema_document
from routing_worker.feature_schema import (
    ETA_FEATURE_NAMES,
    ETA_SCHEMA_VERSION,
    SEAT_FEATURE_NAMES,
    SEAT_SCHEMA_VERSION,
)
from routing_worker.model_deployment import (
    ApprovedBundleMaterialization,
    FixedArtifactBundleResolver,
    ModelDeploymentAssemblyError,
    PostgresActiveModelPairSource,
    VerifiedModelPairAssembler,
)
from routing_worker.native_lightgbm import (
    LightGbmEtaRuntimeLoader,
    LightGbmSeatRiskRuntimeLoader,
)
from routing_worker.postgres_serving import (
    PostgresEtaServingFeatureSource,
    PostgresSeatRiskServingFeatureSource,
)


UTC = timezone.utc
CREATED_AT = datetime(2026, 8, 22, 8, tzinfo=UTC)
UPDATED_AT = CREATED_AT + timedelta(hours=1)
ACTIVATED_AT = UPDATED_AT + timedelta(hours=1)
STARTUP_AS_OF = ACTIVATED_AT + timedelta(hours=1)


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]], *, fail: bool = False) -> None:
        self.rows = rows
        self.fail = fail
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False
        self.rowcount = 0

    def execute(
        self, operation: str, parameters: tuple[Any, ...] = ()
    ) -> None:
        self.executions.append((operation, parameters))
        if self.fail and "FROM model_family" in operation:
            raise TimeoutError("statement timeout")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor, *, fail_on_rollback: bool = False) -> None:
        self.fake_cursor = cursor
        self.autocommit = True
        self.fail_on_rollback = fail_on_rollback
        self.rollbacks = 0
        self.commits = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.fail_on_rollback:
            raise RuntimeError("rollback failed")

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


class Factory:
    def __init__(
        self,
        rows: list[tuple[Any, ...]],
        *,
        fail: bool = False,
        fail_on_rollback: bool = False,
    ) -> None:
        self.cursor = FakeCursor(rows, fail=fail)
        self.connection = FakeConnection(
            self.cursor,
            fail_on_rollback=fail_on_rollback,
        )
        self.calls = 0

    def __call__(self) -> FakeConnection:
        self.calls += 1
        return self.connection


class FakeBooster:
    def __init__(self, module: "FakeLightGbm", model_file: str) -> None:
        self.module = module
        self.model_file = model_file
        self.params = module.parameters

    def feature_name(self) -> list[str]:
        return list(self.module.names)

    def predict(self, matrix: list[list[float]]) -> list[object]:
        return [self.module.output]


class FakeLightGbm:
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

    def Booster(self, *, model_file: str) -> FakeBooster:  # noqa: N802
        self.loaded_paths.append(model_file)
        return FakeBooster(self, model_file)


def digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def write_bundle(root: Path, family: str) -> dict[str, object]:
    root.mkdir(parents=True)
    model = b"safe native fixture\n"
    schema = json.dumps(
        feature_schema_document(family=family), separators=(",", ":")
    ).encode("utf-8")
    if family == "ETA":
        calibration_method = "CONFORMAL"
        calibration_document: dict[str, object] = {
            "schemaVersion": "eta-calibration-v1",
            "family": "ETA",
            "method": calibration_method,
            "confidence": 0.8,
            "p90OffsetSeconds": 60,
        }
        names = ETA_FEATURE_NAMES
    else:
        calibration_method = "PLATT"
        calibration_document = {
            "schemaVersion": "seat-risk-calibration-v1",
            "family": "SEAT_RISK",
            "method": calibration_method,
            "confidence": 0.75,
            "parameters": [
                {"slope": 1.0, "intercept": 0.0},
                {"slope": 1.0, "intercept": 0.0},
                {"slope": 1.0, "intercept": 0.0},
            ],
        }
        names = SEAT_FEATURE_NAMES
    calibration = json.dumps(calibration_document, separators=(",", ":")).encode(
        "utf-8"
    )
    card = f"# {family} reviewed model card\n".encode("utf-8")
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
        "modelCardSha256": digest(card),
        "calibrationFilename": "calibration.json",
        "calibrationMethod": calibration_method,
        "calibrationSha256": digest(calibration),
        "featureSchemaFilename": "feature-schema.json",
        "featureSchemaSha256": digest(schema),
        "datasetSha256": "d" * 64,
        "metricsSha256": "e" * 64,
        "validationEvidenceSha256": "f" * 64,
        "registryStateVersion": 5,
        "registryUpdatedAt": UPDATED_AT.isoformat(),
        "artifactSha256": digest(model),
    }


def lifecycle_row(
    *,
    purpose: str,
    model_version: str,
    artifact_uri: str,
    evidence: dict[str, object],
    model_id: str,
    deployment_id: str,
    **changes: object,
) -> tuple[Any, ...]:
    family = "ETA" if purpose == "BUS_ETA" else "SEAT_RISK"
    schema = ETA_SCHEMA_VERSION if family == "ETA" else SEAT_SCHEMA_VERSION
    artifact_sha = evidence.pop("artifactSha256")
    training_scope = {
        "calibrationSha256": evidence["calibrationSha256"],
        "datasetSha256": evidence["datasetSha256"],
        "missingTargetPolicy": "EXCLUDE_UNOBSERVED",
        "modelCardSha256": evidence["modelCardSha256"],
        "splitPolicy": "TEMPORAL_TRIP_GROUP_PURGED",
        # Unknown outer registration metadata remains backward compatible.
        "trainingWindow": "2026-07",
        "servingEvidence": evidence,
    }
    values: list[Any] = [
        purpose,
        UUID(model_id),
        model_version,
        "ACTIVE",
        artifact_uri,
        artifact_sha,
        schema,
        training_scope,
        CREATED_AT,
        UUID(deployment_id),
        "staging",
        "ACTIVE",
        Decimal("1"),
        ACTIVATED_AT,
        None,
    ]
    indexes = {
        "purpose": 0,
        "version": 2,
        "status": 3,
        "artifact_uri": 4,
        "artifact_sha256": 5,
        "feature_schema": 6,
        "training_scope": 7,
        "created_at": 8,
        "environment": 10,
        "deployment_state": 11,
        "traffic_fraction": 12,
        "activated_at": 13,
        "deactivated_at": 14,
    }
    for key, value in changes.items():
        values[indexes[key]] = value
    return tuple(values)


def build_fixture(tmp_path: Path) -> tuple[
    list[tuple[Any, ...]],
    tuple[ApprovedBundleMaterialization, ...],
    FakeLightGbm,
    FakeLightGbm,
]:
    eta_root = tmp_path / "eta"
    seat_root = tmp_path / "seat"
    eta_evidence = write_bundle(eta_root, "ETA")
    seat_evidence = write_bundle(seat_root, "SEAT_RISK")
    eta_uri = "s3://approved-models/eta/model.txt"
    seat_uri = "s3://approved-models/seat/model.txt"
    eta_sha = str(eta_evidence["artifactSha256"])
    seat_sha = str(seat_evidence["artifactSha256"])
    rows = [
        lifecycle_row(
            purpose="BUS_ETA",
            model_version="eta-v1",
            artifact_uri=eta_uri,
            evidence=dict(eta_evidence),
            model_id="00000000-0000-0000-0000-000000000101",
            deployment_id="00000000-0000-0000-0000-000000000102",
        ),
        lifecycle_row(
            purpose="SEAT_RISK",
            model_version="seat-v1",
            artifact_uri=seat_uri,
            evidence=dict(seat_evidence),
            model_id="00000000-0000-0000-0000-000000000103",
            deployment_id="00000000-0000-0000-0000-000000000104",
        ),
    ]
    materializations = (
        ApprovedBundleMaterialization("ETA", "eta-v1", eta_uri, eta_sha, eta_root),
        ApprovedBundleMaterialization(
            "SEAT_RISK", "seat-v1", seat_uri, seat_sha, seat_root
        ),
    )
    eta_module = FakeLightGbm(
        ETA_FEATURE_NAMES,
        120.0,
        {"objective": "regression"},
    )
    seat_module = FakeLightGbm(
        SEAT_FEATURE_NAMES,
        [0.1, 0.2, 0.3, 0.4],
        {"objective": "multiclass", "num_class": 4},
    )
    return rows, materializations, eta_module, seat_module


def test_active_pair_is_one_strict_read_only_snapshot(tmp_path: Path) -> None:
    rows, _, _, _ = build_fixture(tmp_path)
    factory = Factory(rows)

    pair = PostgresActiveModelPairSource(
        factory,
        as_of=STARTUP_AS_OF,
    ).load("staging")

    assert pair.eta.family == "ETA"
    assert pair.seat_risk.family == "SEAT_RISK"
    assert pair.eta.lifecycle.deployment.traffic_fraction == 1
    assert factory.calls == 1
    assert factory.connection.rollbacks == 1
    assert factory.connection.commits == 0
    assert factory.cursor.closed and factory.connection.closed
    assert factory.cursor.executions[0][0] == (
        "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    query, parameters = factory.cursor.executions[-1]
    assert "FROM model_family" in query
    assert "version.created_at <= request.as_of" in query
    assert "deployment.activated_at <= request.as_of" in query
    assert parameters == ("staging", STARTUP_AS_OF)


def test_verified_assembler_returns_only_bus_owned_wrappers(tmp_path: Path) -> None:
    rows, materializations, eta_module, seat_module = build_fixture(tmp_path)
    lifecycle_factory = Factory(rows)
    resolver = FixedArtifactBundleResolver(
        bundle_root=tmp_path,
        materializations=materializations,
    )
    unused_eta_db = Factory([])
    unused_seat_db = Factory([])
    assembler = VerifiedModelPairAssembler(
        lifecycle_source=PostgresActiveModelPairSource(
            lifecycle_factory,
            as_of=STARTUP_AS_OF,
        ),
        bundle_resolver=resolver,
        eta_feature_source=PostgresEtaServingFeatureSource(unused_eta_db),
        seat_risk_feature_source=PostgresSeatRiskServingFeatureSource(unused_seat_db),
        eta_runtime_loader=LightGbmEtaRuntimeLoader(eta_module),
        seat_risk_runtime_loader=LightGbmSeatRiskRuntimeLoader(seat_module),
        environment="staging",
    )

    pair = assembler.assemble()

    assert type(pair.eta) is VerifiedEtaPredictor
    assert type(pair.seat_risk) is VerifiedSeatRiskPredictor
    assert pair.eta.attestation.model_version == "eta-v1"
    assert pair.seat_risk.attestation.model_version == "seat-v1"
    assert pair.environment == "staging"
    assert unused_eta_db.calls == 0 and unused_seat_db.calls == 0
    assert tuple(inspect.signature(assembler.assemble).parameters) == ()


def test_lifecycle_ambiguity_timeout_and_malformed_evidence_block_startup(
    tmp_path: Path,
) -> None:
    rows, _, _, _ = build_fixture(tmp_path)
    with pytest.raises(ModelDeploymentAssemblyError, match="exactly one"):
        PostgresActiveModelPairSource(
            Factory([*rows, rows[0]]),
            as_of=STARTUP_AS_OF,
        ).load("staging")
    with pytest.raises(ModelDeploymentAssemblyError, match="read failed"):
        PostgresActiveModelPairSource(
            Factory([], fail=True),
            as_of=STARTUP_AS_OF,
        ).load("staging")
    cleanup_failure = Factory(rows, fail_on_rollback=True)
    with pytest.raises(ModelDeploymentAssemblyError, match="read failed"):
        PostgresActiveModelPairSource(
            cleanup_failure,
            as_of=STARTUP_AS_OF,
        ).load("staging")
    assert cleanup_failure.cursor.closed and cleanup_failure.connection.closed

    bad_scope = dict(rows[0][7])
    evidence = dict(bad_scope["servingEvidence"])
    evidence["unexpected"] = True
    bad_scope["servingEvidence"] = evidence
    malformed = list(rows[0])
    malformed[7] = bad_scope
    with pytest.raises(ModelDeploymentAssemblyError, match="schema is not exact"):
        PostgresActiveModelPairSource(
            Factory([tuple(malformed), rows[1]]),
            as_of=STARTUP_AS_OF,
        ).load(
            "staging"
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("missingTargetPolicy", "ZERO_FILL", "missing-target policy"),
        ("splitPolicy", "RANDOM_ROW", "split policy"),
        ("calibrationSha256", "a" * 64, "calibrationSha256 differ"),
        ("datasetSha256", "a" * 64, "datasetSha256 differ"),
        ("modelCardSha256", "a" * 64, "modelCardSha256 differ"),
    ),
)
def test_outer_registration_evidence_must_match_closed_serving_manifest(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    rows, _, _, _ = build_fixture(tmp_path)
    malformed = list(rows[0])
    scope = dict(malformed[7])
    scope[field] = value
    malformed[7] = scope

    with pytest.raises(ModelDeploymentAssemblyError, match=message):
        PostgresActiveModelPairSource(
            Factory([tuple(malformed), rows[1]]),
            as_of=STARTUP_AS_OF,
        ).load(
            "staging"
        )


def test_missing_outer_registration_evidence_blocks_startup(tmp_path: Path) -> None:
    rows, _, _, _ = build_fixture(tmp_path)
    malformed = list(rows[0])
    scope = dict(malformed[7])
    del scope["datasetSha256"]
    malformed[7] = scope

    with pytest.raises(ModelDeploymentAssemblyError, match="registration evidence"):
        PostgresActiveModelPairSource(
            Factory([tuple(malformed), rows[1]]),
            as_of=STARTUP_AS_OF,
        ).load(
            "staging"
        )


def test_family_schema_and_full_traffic_drift_are_not_promoted(tmp_path: Path) -> None:
    rows, _, _, _ = build_fixture(tmp_path)
    bad_schema = list(rows[0])
    bad_schema[6] = SEAT_SCHEMA_VERSION
    with pytest.raises(ModelDeploymentAssemblyError, match="schema version"):
        PostgresActiveModelPairSource(
            Factory([tuple(bad_schema), rows[1]]),
            as_of=STARTUP_AS_OF,
        ).load(
            "staging"
        )
    canary = list(rows[1])
    canary[11] = "CANARY"
    canary[12] = Decimal("0.5")
    with pytest.raises(ModelDeploymentAssemblyError, match="exactly ACTIVE"):
        PostgresActiveModelPairSource(
            Factory([rows[0], tuple(canary)]),
            as_of=STARTUP_AS_OF,
        ).load(
            "staging"
        )


def test_startup_as_of_is_explicit_aware_and_validated_before_database_io(
    tmp_path: Path,
) -> None:
    rows, _, _, _ = build_fixture(tmp_path)
    factory = Factory(rows)
    with pytest.raises(TypeError, match="as_of"):
        PostgresActiveModelPairSource(factory)  # type: ignore[call-arg]
    with pytest.raises(ModelDeploymentAssemblyError, match="timezone-aware"):
        PostgresActiveModelPairSource(
            factory,
            as_of=STARTUP_AS_OF.replace(tzinfo=None),
        )
    with pytest.raises(ModelDeploymentAssemblyError, match="timezone-aware"):
        PostgresActiveModelPairSource(
            factory,
            as_of="2026-08-22T11:00:00+00:00",  # type: ignore[arg-type]
        )
    assert factory.calls == 0


@pytest.mark.parametrize(
    ("row_index", "message"),
    (
        (8, "model created_at is after startup as_of"),
        (13, "deployment activated_at is after startup as_of"),
    ),
)
def test_future_database_lifecycle_timestamps_block_startup(
    tmp_path: Path,
    row_index: int,
    message: str,
) -> None:
    rows, _, _, _ = build_fixture(tmp_path)
    malformed = list(rows[0])
    malformed[row_index] = STARTUP_AS_OF + timedelta(seconds=1)

    with pytest.raises(ModelDeploymentAssemblyError, match=message):
        PostgresActiveModelPairSource(
            Factory([tuple(malformed), rows[1]]),
            as_of=STARTUP_AS_OF,
        ).load("staging")


def test_future_registry_readiness_and_pre_ready_activation_block_startup(
    tmp_path: Path,
) -> None:
    rows, _, _, _ = build_fixture(tmp_path)
    future_registry = list(rows[0])
    future_scope = dict(future_registry[7])
    future_evidence = dict(future_scope["servingEvidence"])
    future_evidence["registryUpdatedAt"] = (
        STARTUP_AS_OF + timedelta(seconds=1)
    ).isoformat()
    future_scope["servingEvidence"] = future_evidence
    future_registry[7] = future_scope
    with pytest.raises(
        ModelDeploymentAssemblyError,
        match="registry updated_at is after startup as_of",
    ):
        PostgresActiveModelPairSource(
            Factory([tuple(future_registry), rows[1]]),
            as_of=STARTUP_AS_OF,
        ).load("staging")

    pre_ready = list(rows[0])
    pre_ready[13] = UPDATED_AT - timedelta(seconds=1)
    with pytest.raises(
        ModelDeploymentAssemblyError,
        match="deployment activation predates registry readiness",
    ):
        PostgresActiveModelPairSource(
            Factory([tuple(pre_ready), rows[1]]),
            as_of=STARTUP_AS_OF,
        ).load("staging")


def test_lifecycle_timestamps_equal_to_startup_as_of_are_accepted(tmp_path: Path) -> None:
    rows, _, _, _ = build_fixture(tmp_path)
    boundary = list(rows[0])
    boundary[8] = STARTUP_AS_OF
    scope = dict(boundary[7])
    evidence = dict(scope["servingEvidence"])
    evidence["registryUpdatedAt"] = STARTUP_AS_OF.isoformat()
    scope["servingEvidence"] = evidence
    boundary[7] = scope
    boundary[13] = STARTUP_AS_OF

    pair = PostgresActiveModelPairSource(
        Factory([tuple(boundary), rows[1]]),
        as_of=STARTUP_AS_OF,
    ).load("staging")

    assert pair.eta.lifecycle.registry_entry.registered_at == STARTUP_AS_OF
    assert pair.eta.lifecycle.registry_entry.updated_at == STARTUP_AS_OF
    assert pair.eta.lifecycle.deployment.activated_at == STARTUP_AS_OF


def test_fixed_bundle_root_rejects_escape_and_unknown_active_identity(
    tmp_path: Path,
) -> None:
    rows, materializations, _, _ = build_fixture(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    escaped = replace(materializations[0], bundle_directory=outside)
    with pytest.raises(ModelDeploymentAssemblyError, match="escaped"):
        FixedArtifactBundleResolver(
            bundle_root=tmp_path,
            materializations=(escaped,),
        )

    resolver = FixedArtifactBundleResolver(
        bundle_root=tmp_path,
        materializations=materializations,
    )
    pair = PostgresActiveModelPairSource(
        Factory(rows),
        as_of=STARTUP_AS_OF,
    ).load("staging")
    unknown = replace(pair.eta, artifact_uri="s3://approved-models/eta/other.txt")
    with pytest.raises(ModelDeploymentAssemblyError, match="no approved"):
        resolver.resolve(unknown)


def test_artifact_hash_tamper_fails_before_pair_exposure(tmp_path: Path) -> None:
    rows, materializations, eta_module, seat_module = build_fixture(tmp_path)
    (tmp_path / "eta" / "model.txt").write_text("tampered", encoding="utf-8")
    assembler = VerifiedModelPairAssembler(
        lifecycle_source=PostgresActiveModelPairSource(
            Factory(rows),
            as_of=STARTUP_AS_OF,
        ),
        bundle_resolver=FixedArtifactBundleResolver(
            bundle_root=tmp_path,
            materializations=materializations,
        ),
        eta_feature_source=PostgresEtaServingFeatureSource(Factory([])),
        seat_risk_feature_source=PostgresSeatRiskServingFeatureSource(Factory([])),
        eta_runtime_loader=LightGbmEtaRuntimeLoader(eta_module),
        seat_risk_runtime_loader=LightGbmSeatRiskRuntimeLoader(seat_module),
        environment="staging",
    )
    with pytest.raises(ModelDeploymentAssemblyError, match="pair assembly"):
        assembler.assemble()


def test_worker_modules_do_not_import_routing_api() -> None:
    source = (
        Path(__file__).parents[1] / "routing_worker" / "model_deployment.py"
    ).read_text(encoding="utf-8")
    serving = (
        Path(__file__).parents[1] / "routing_worker" / "postgres_serving.py"
    ).read_text(encoding="utf-8")
    assert "routing_api" not in source
    assert "routing_api" not in serving
    assert "pickle" not in source and "joblib" not in source
