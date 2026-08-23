"""RI-382 adversarial controls for the Routing model data plane.

These tests deliberately use only injected DB-API/native seams.  They prove the
security boundary without claiming that PostgreSQL, S3, or LightGBM exists here.
"""

from __future__ import annotations

import builtins
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from time import sleep
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from django.test.utils import override_settings

from bus_intelligence_core import EtaPredictorInput, SeatRiskPredictorInput
from provider_core.named import ProviderAdapterSuite
from routing_api.container import (
    _reset_application_composition_for_tests,
    get_application,
    register_production_dependencies,
)
from routing_api.production_composition import ProductionCompositionDependencies
from routing_worker import model_deployment as deployment_module
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
)
from routing_worker.postgres_serving import (
    ETA_POINT_IN_TIME_SQL,
    SEAT_RISK_POINT_IN_TIME_SQL,
    PostgresEtaServingFeatureSource,
    PostgresSeatRiskServingFeatureSource,
    PostgresServingFeatureSourceError,
    ServingSnapshotTimeouts,
)


UTC = timezone.utc
AS_OF = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
OBSERVED_AT = AS_OF - timedelta(seconds=10)
TRIP_ID = UUID("00000000-0000-0000-0000-000000000011")
ROUTE_ID = UUID("00000000-0000-0000-0000-000000000012")
BOARDING_ID = UUID("00000000-0000-0000-0000-000000000013")
TARGET_ID = UUID("00000000-0000-0000-0000-000000000014")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


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
        if operation == self.fail_statement:
            raise TimeoutError("sensitive database detail")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self.fake_cursor = cursor
        self.rollbacks = 0
        self.commits = 0
        self.closed = False

    def cursor(self) -> _Cursor:
        return self.fake_cursor

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
        self.cursor = _Cursor(rows, fail_statement=fail_statement)
        self.connection = _Connection(self.cursor)
        self.calls = 0

    def __call__(self) -> _Connection:
        self.calls += 1
        return self.connection


def _eta_input(**changes: object) -> EtaPredictorInput:
    values: dict[str, object] = {
        "vehicle_ref": "vehicle-token",
        "route_id": str(ROUTE_ID),
        "direction": "UP",
        "boarding_stop_id": str(BOARDING_ID),
        "observed_at": OBSERVED_AT,
        "remain_seat_observed": 0,
        "prediction_at": AS_OF,
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
        "observed_at": 7,
        "ingested_at": 8,
        "recent_1": 9,
        "quality_flags": 14,
    }
    for name, value in changes.items():
        values[indexes[name]] = value
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
    for name, value in changes.items():
        values[indexes[name]] = value
    return tuple(values)


def _assert_snapshot_closed(factory: _Factory, *, statement: str) -> None:
    assert factory.calls == 1
    assert factory.connection.rollbacks == 1
    assert factory.connection.commits == 0
    assert factory.cursor.closed is True
    assert factory.connection.closed is True
    executions = factory.cursor.executions
    assert executions[0] == (
        "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        (),
    )
    assert executions[1][1] == ("120ms",)
    assert executions[2][1] == ("50ms",)
    assert executions[3][1] == ("250ms",)
    assert executions[4][0] is statement


def _serving_evidence(family: str) -> dict[str, object]:
    eta = family == "ETA"
    return {
        "schemaVersion": "worker-serving-evidence-v1",
        "artifactFormat": "LIGHTGBM_TEXT",
        "artifactFilename": "eta-model.txt" if eta else "seat-model.txt",
        "featureNames": list(ETA_FEATURE_NAMES if eta else SEAT_FEATURE_NAMES),
        "modelCardFilename": "eta-card.md" if eta else "seat-card.md",
        "modelCardSha256": SHA_B,
        "calibrationFilename": (
            "eta-calibration.json" if eta else "seat-calibration.json"
        ),
        "calibrationMethod": "CONFORMAL" if eta else "ISOTONIC",
        "calibrationSha256": SHA_C,
        "featureSchemaFilename": "eta-schema.json" if eta else "seat-schema.json",
        "featureSchemaSha256": SHA_D,
        "datasetSha256": SHA_A,
        "metricsSha256": SHA_E,
        "validationEvidenceSha256": SHA_E,
        "registryStateVersion": 5,
        "registryUpdatedAt": (AS_OF - timedelta(days=1)).isoformat(),
    }


def _training_scope(
    family: str,
    *,
    evidence_changes: dict[str, object] | None = None,
    outer_changes: dict[str, object] | None = None,
) -> dict[str, object]:
    evidence = _serving_evidence(family)
    if evidence_changes:
        evidence.update(evidence_changes)
    scope: dict[str, object] = {
        "calibrationSha256": SHA_C,
        "datasetSha256": SHA_A,
        "missingTargetPolicy": "EXCLUDE_UNOBSERVED",
        "modelCardSha256": SHA_B,
        "splitPolicy": "TEMPORAL_TRIP_GROUP_PURGED",
        "servingEvidence": evidence,
    }
    if outer_changes:
        scope.update(outer_changes)
    return scope


def _active_row(family: str, **changes: object) -> tuple[Any, ...]:
    eta = family == "ETA"
    values: list[Any] = [
        "BUS_ETA" if eta else "SEAT_RISK",
        UUID("00000000-0000-0000-0000-000000000021" if eta else "00000000-0000-0000-0000-000000000022"),
        "eta-prod-v1" if eta else "seat-prod-v1",
        "ACTIVE",
        "s3://routing-models/eta/prod/v1" if eta else "s3://routing-models/seat/prod/v1",
        SHA_A,
        ETA_SCHEMA_VERSION if eta else SEAT_SCHEMA_VERSION,
        _training_scope(family),
        AS_OF - timedelta(days=2),
        UUID("00000000-0000-0000-0000-000000000031" if eta else "00000000-0000-0000-0000-000000000032"),
        "prod",
        "ACTIVE",
        Decimal("1"),
        AS_OF - timedelta(hours=1),
        None,
    ]
    indexes = {
        "purpose": 0,
        "version": 2,
        "version_state": 3,
        "artifact_uri": 4,
        "artifact_sha256": 5,
        "feature_schema_version": 6,
        "training_scope": 7,
        "created_at": 8,
        "environment": 10,
        "deployment_state": 11,
        "traffic_fraction": 12,
        "activated_at": 13,
        "deactivated_at": 14,
    }
    for name, value in changes.items():
        values[indexes[name]] = value
    return tuple(values)


def test_fixed_sql_and_parameter_binding_exclude_dynamic_or_service_identifiers() -> None:
    forbidden = (
        "auth_user",
        "service_db",
        "saved_place",
        "route_search",
        "email",
        "phone",
        "raw_payload",
        "provider_payload",
    )
    for statement, placeholders in (
        (ETA_POINT_IN_TIME_SQL, 6),
        (SEAT_RISK_POINT_IN_TIME_SQL, 7),
        (deployment_module._MODEL_PAIR_SNAPSHOT_SQL, 2),
    ):
        lowered = statement.casefold()
        assert statement.count("%s") == placeholders
        assert "{" not in statement and "}" not in statement
        assert not any(token in lowered for token in forbidden)

    injection = "UP' OR TRUE --"
    factory = _Factory([])
    assert PostgresEtaServingFeatureSource(factory).load(
        _eta_input(direction=injection)
    ) is None
    statement, parameters = factory.cursor.executions[-1]
    assert statement is ETA_POINT_IN_TIME_SQL
    assert injection not in statement
    assert parameters[1] == injection


def test_exact_route_stop_vehicle_identity_and_family_queries_fail_closed() -> None:
    eta_cases = (
        _eta_row(route_id=UUID("00000000-0000-0000-0000-000000000099")),
        _eta_row(boarding_stop_id=UUID("00000000-0000-0000-0000-000000000099")),
        _eta_row(vehicle_ref="other-vehicle"),
        _eta_row(direction="DOWN"),
    )
    for row in eta_cases:
        factory = _Factory([row])
        assert PostgresEtaServingFeatureSource(factory).load(_eta_input()) is None
        assert SEAT_RISK_POINT_IN_TIME_SQL not in {
            statement for statement, _ in factory.cursor.executions
        }

    seat_cases = (
        _seat_row(route_id=UUID("00000000-0000-0000-0000-000000000099")),
        _seat_row(boarding_stop_id=UUID("00000000-0000-0000-0000-000000000099")),
        _seat_row(target_stop_id=UUID("00000000-0000-0000-0000-000000000099")),
        _seat_row(vehicle_ref="other-vehicle"),
        _seat_row(direction="DOWN"),
    )
    for row in seat_cases:
        factory = _Factory([row])
        assert PostgresSeatRiskServingFeatureSource(factory).load(_seat_input()) is None
        assert ETA_POINT_IN_TIME_SQL not in {
            statement for statement, _ in factory.cursor.executions
        }


def test_snapshot_timeout_zero_missing_future_ambiguous_and_malformed_are_closed() -> None:
    eta_timeout = _Factory([], fail_statement=ETA_POINT_IN_TIME_SQL)
    seat_timeout = _Factory([], fail_statement=SEAT_RISK_POINT_IN_TIME_SQL)
    assert PostgresEtaServingFeatureSource(eta_timeout).load(_eta_input()) is None
    assert PostgresSeatRiskServingFeatureSource(seat_timeout).load(_seat_input()) is None
    _assert_snapshot_closed(eta_timeout, statement=ETA_POINT_IN_TIME_SQL)
    _assert_snapshot_closed(seat_timeout, statement=SEAT_RISK_POINT_IN_TIME_SQL)

    cases = (
        (PostgresEtaServingFeatureSource(_Factory([])), _eta_input()),
        (PostgresEtaServingFeatureSource(_Factory([_eta_row(), _eta_row()])), _eta_input()),
        (PostgresEtaServingFeatureSource(_Factory([_eta_row()[:-1]])), _eta_input()),
        (PostgresEtaServingFeatureSource(_Factory([_eta_row(recent_1=None)])), _eta_input()),
        (
            PostgresEtaServingFeatureSource(
                _Factory([_eta_row(ingested_at=AS_OF + timedelta(microseconds=1))])
            ),
            _eta_input(),
        ),
        (PostgresSeatRiskServingFeatureSource(_Factory([])), _seat_input()),
        (
            PostgresSeatRiskServingFeatureSource(_Factory([_seat_row(), _seat_row()])),
            _seat_input(),
        ),
        (PostgresSeatRiskServingFeatureSource(_Factory([_seat_row()[:-1]])), _seat_input()),
        (
            PostgresSeatRiskServingFeatureSource(_Factory([_seat_row(remaining=None)])),
            _seat_input(),
        ),
        (
            PostgresSeatRiskServingFeatureSource(
                _Factory([_seat_row(observed_at=AS_OF + timedelta(microseconds=1))])
            ),
            _seat_input(),
        ),
    )
    for source, value in cases:
        assert source.load(value) is None

    eta_zero = PostgresEtaServingFeatureSource(_Factory([_eta_row()])).load(_eta_input())
    seat_zero = PostgresSeatRiskServingFeatureSource(_Factory([_seat_row()])).load(
        _seat_input()
    )
    assert eta_zero is not None and eta_zero.observation.recent_segment_seconds_1 == 0
    assert eta_zero.observation.headway_seconds == 0
    assert seat_zero is not None and seat_zero.observation.current_remaining_seats == 0
    assert seat_zero.observation.capacity_confidence == 0


@pytest.mark.parametrize(
    "values",
    (
        {"statement_ms": True},
        {"statement_ms": 0},
        {"statement_ms": 121},
        {"lock_ms": 51},
        {"idle_in_transaction_ms": 251},
    ),
)
def test_snapshot_timeouts_cannot_expand_frozen_online_caps(values: dict[str, object]) -> None:
    with pytest.raises(PostgresServingFeatureSourceError):
        ServingSnapshotTimeouts(**values)  # type: ignore[arg-type]
    assert ServingSnapshotTimeouts(1, 1, 1) == ServingSnapshotTimeouts(1, 1, 1)


def test_active_pair_is_one_read_only_snapshot_with_exact_environment_and_fraction() -> None:
    factory = _Factory([_active_row("ETA"), _active_row("SEAT_RISK")])
    pair = PostgresActiveModelPairSource(factory, as_of=AS_OF).load("prod")
    assert pair.environment == "prod"
    assert pair.eta.lifecycle.deployment.traffic_fraction == 1
    assert pair.seat_risk.lifecycle.deployment.traffic_fraction == 1
    assert pair.eta.lifecycle.calibration_method == "CONFORMAL"
    assert pair.seat_risk.lifecycle.calibration_method == "ISOTONIC"
    _assert_snapshot_closed(factory, statement=deployment_module._MODEL_PAIR_SNAPSHOT_SQL)
    statement, parameters = factory.cursor.executions[-1]
    assert statement is deployment_module._MODEL_PAIR_SNAPSHOT_SQL
    assert parameters == ("prod", AS_OF)
    assert "prod" not in statement
    assert AS_OF.isoformat() not in statement


@pytest.mark.parametrize(
    "as_of",
    (
        datetime(2026, 8, 23, 12, 0),
        "2026-08-23T12:00:00+00:00",
        None,
        True,
    ),
)
def test_active_pair_rejects_naive_or_invalid_startup_as_of(as_of: object) -> None:
    factory = _Factory([_active_row("ETA"), _active_row("SEAT_RISK")])
    with pytest.raises(ModelDeploymentAssemblyError, match="timezone-aware"):
        PostgresActiveModelPairSource(factory, as_of=as_of)  # type: ignore[arg-type]
    assert factory.calls == 0


@pytest.mark.parametrize(
    ("family", "changes"),
    (
        ("ETA", {"version_state": "CANARY"}),
        ("ETA", {"deployment_state": "CANARY"}),
        ("ETA", {"traffic_fraction": Decimal("0.999999")}),
        ("ETA", {"environment": "staging"}),
        ("ETA", {"deactivated_at": AS_OF}),
        ("ETA", {"created_at": AS_OF + timedelta(microseconds=1)}),
        ("ETA", {"activated_at": AS_OF + timedelta(microseconds=1)}),
        (
            "ETA",
            {
                "training_scope": _training_scope(
                    "ETA",
                    evidence_changes={
                        "registryUpdatedAt": (
                            AS_OF + timedelta(microseconds=1)
                        ).isoformat()
                    },
                )
            },
        ),
        ("ETA", {"artifact_uri": "file:///tmp/model.txt"}),
        ("ETA", {"artifact_uri": "s3://bucket/model.txt?version=request"}),
        ("ETA", {"artifact_sha256": "A" * 64}),
        ("ETA", {"feature_schema_version": SEAT_SCHEMA_VERSION}),
        (
            "ETA",
            {
                "training_scope": _training_scope(
                    "ETA", evidence_changes={"requestPath": "../../attacker"}
                )
            },
        ),
        (
            "ETA",
            {
                "training_scope": _training_scope(
                    "ETA", evidence_changes={"calibrationMethod": "ISOTONIC"}
                )
            },
        ),
        (
            "ETA",
            {
                "training_scope": _training_scope(
                    "ETA", evidence_changes={"artifactFilename": "model.pkl"}
                )
            },
        ),
    ),
)
def test_active_pair_lifecycle_uri_schema_calibration_and_pickle_fail_closed(
    family: str, changes: dict[str, object]
) -> None:
    rows = [_active_row("ETA"), _active_row("SEAT_RISK")]
    rows[0 if family == "ETA" else 1] = _active_row(family, **changes)
    factory = _Factory(rows)
    with pytest.raises((ModelDeploymentAssemblyError, ValueError)):
        PostgresActiveModelPairSource(factory, as_of=AS_OF).load("prod")
    assert factory.connection.rollbacks == 1
    assert factory.cursor.closed and factory.connection.closed


@pytest.mark.parametrize(
    "training_scope",
    (
        _training_scope(
            "ETA", outer_changes={"missingTargetPolicy": "MISSING_IS_ZERO"}
        ),
        _training_scope("ETA", outer_changes={"splitPolicy": "RANDOM_ROW"}),
        _training_scope("ETA", outer_changes={"calibrationSha256": SHA_D}),
        _training_scope("ETA", outer_changes={"datasetSha256": SHA_D}),
        _training_scope("ETA", outer_changes={"modelCardSha256": SHA_D}),
        {
            key: value
            for key, value in _training_scope("ETA").items()
            if key != "missingTargetPolicy"
        },
    ),
)
def test_serving_evidence_must_match_registration_safety_evidence_exactly(
    training_scope: dict[str, object],
) -> None:
    factory = _Factory(
        [
            _active_row("ETA", training_scope=training_scope),
            _active_row("SEAT_RISK"),
        ]
    )
    with pytest.raises(ModelDeploymentAssemblyError):
        PostgresActiveModelPairSource(factory, as_of=AS_OF).load("prod")
    assert factory.connection.rollbacks == 1
    assert factory.cursor.closed and factory.connection.closed


def test_fixed_artifact_materialization_confines_path_and_binds_full_identity(
    tmp_path: Path,
) -> None:
    pair = PostgresActiveModelPairSource(
        _Factory([_active_row("ETA"), _active_row("SEAT_RISK")]),
        as_of=AS_OF,
    ).load("prod")
    root = tmp_path / "approved"
    eta = root / "eta"
    seat = root / "seat"
    outside = tmp_path / "outside"
    for directory in (eta, seat, outside):
        directory.mkdir(parents=True)

    eta_materialization = ApprovedBundleMaterialization(
        "ETA",
        pair.eta.manifest.artifact.model_version,
        pair.eta.artifact_uri,
        pair.eta.manifest.artifact.artifact_sha256,
        eta,
    )
    seat_materialization = ApprovedBundleMaterialization(
        "SEAT_RISK",
        pair.seat_risk.manifest.artifact.model_version,
        pair.seat_risk.artifact_uri,
        pair.seat_risk.manifest.artifact.artifact_sha256,
        seat,
    )
    resolver = FixedArtifactBundleResolver(
        bundle_root=root,
        materializations=(eta_materialization, seat_materialization),
    )
    assert resolver.resolve(pair.eta) == eta.resolve()
    assert resolver.resolve(pair.seat_risk) == seat.resolve()

    with pytest.raises(ModelDeploymentAssemblyError, match="escaped"):
        FixedArtifactBundleResolver(
            bundle_root=root,
            materializations=(replace(eta_materialization, bundle_directory=outside),),
        )
    with pytest.raises(ModelDeploymentAssemblyError, match="duplicate"):
        FixedArtifactBundleResolver(
            bundle_root=root,
            materializations=(eta_materialization, eta_materialization),
        )
    with pytest.raises(ModelDeploymentAssemblyError, match="no approved"):
        resolver.resolve(replace(pair.eta, artifact_uri="s3://other/eta/prod/v1"))


@pytest.fixture
def _isolated_api_composition() -> None:
    _reset_application_composition_for_tests()
    yield
    _reset_application_composition_for_tests()


def test_api_registration_exact_type_replacement_late_and_no_hot_swap(
    _isolated_api_composition: None,
) -> None:
    class Derived(ProductionCompositionDependencies):
        pass

    with pytest.raises(TypeError, match="exact ProductionCompositionDependencies"):
        register_production_dependencies(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact ProductionCompositionDependencies"):
        register_production_dependencies(Derived())

    first = ProductionCompositionDependencies()
    second = ProductionCompositionDependencies()
    register_production_dependencies(first)
    register_production_dependencies(first)
    with pytest.raises(RuntimeError, match="already registered"):
        register_production_dependencies(second)

    marker = object()
    with patch("routing_api.container.build_application", return_value=marker) as build:
        assert get_application() is marker
        assert get_application() is marker
    build.assert_called_once_with(production_dependencies=first)
    with pytest.raises(RuntimeError, match="before application startup"):
        register_production_dependencies(first)

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        with pytest.raises(RuntimeError, match="test-only"):
            get_application.cache_clear()


def test_api_registration_and_cached_build_races_have_exactly_one_winner(
    _isolated_api_composition: None,
) -> None:
    values = (ProductionCompositionDependencies(), ProductionCompositionDependencies())
    gate = threading.Barrier(2)
    outcomes: list[tuple[str, object]] = []
    lock = threading.Lock()

    def register(value: ProductionCompositionDependencies) -> None:
        gate.wait(timeout=2)
        try:
            register_production_dependencies(value)
        except RuntimeError as exc:
            outcome: tuple[str, object] = ("rejected", exc)
        else:
            outcome = ("accepted", value)
        with lock:
            outcomes.append(outcome)

    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(executor.map(register, values))
    accepted = [value for state, value in outcomes if state == "accepted"]
    assert len(accepted) == 1
    assert sum(state == "rejected" for state, _ in outcomes) == 1

    marker = object()
    build_calls = 0

    def slow_build(*, production_dependencies=None):
        nonlocal build_calls
        build_calls += 1
        assert production_dependencies is accepted[0]
        sleep(0.02)
        return marker

    with patch("routing_api.container.build_application", side_effect=slow_build):
        with ThreadPoolExecutor(max_workers=32) as executor:
            applications = tuple(executor.map(lambda _: get_application(), range(64)))
    assert build_calls == 1
    assert all(application is marker for application in applications)


def test_api_same_thread_reentrant_build_fails_closed_and_caches_error(
    _isolated_api_composition: None,
) -> None:
    dependencies = ProductionCompositionDependencies()
    register_production_dependencies(dependencies)
    build_calls = 0

    def reentrant_build(*, production_dependencies=None):
        nonlocal build_calls
        build_calls += 1
        assert production_dependencies is dependencies
        return get_application()

    with patch(
        "routing_api.container.build_application", side_effect=reentrant_build
    ):
        with pytest.raises(RuntimeError, match="already in progress") as first:
            get_application()
        with pytest.raises(RuntimeError, match="previously failed") as cached:
            get_application()

    assert build_calls == 1
    assert cached.value.__cause__ is first.value


def test_api_default_is_zero_call_all_false_and_never_imports_worker(
    _isolated_api_composition: None,
) -> None:
    imported_worker: list[str] = []
    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object):
        if name == "routing_worker" or name.startswith("routing_worker."):
            imported_worker.append(name)
            raise AssertionError("Routing API attempted to import Worker implementation")
        return original_import(name, *args, **kwargs)

    with (
        override_settings(
            ROUTING_FIXTURE_SCENARIO="",
            ROUTING_SERVICE_JWT_SECRET="x" * 32,
        ),
        patch.object(
            ProviderAdapterSuite,
            "from_config",
            side_effect=AssertionError("default startup constructed a Provider suite"),
        ) as provider_suite,
        patch("builtins.__import__", side_effect=guarded_import),
    ):
        application = get_application()

    provider_suite.assert_not_called()
    assert imported_worker == []
    assert application.readiness()["checks"]["backend"] == "unavailable"
    assert not any(application.capabilities()["features"].values())
