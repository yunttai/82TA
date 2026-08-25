from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
import re
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.apps import apps
from django.conf import settings

from routing_api import models
from routing_api.persistence.admin_services import (
    AdminAuthorizationError,
    AdminConflictError,
    AdminValidationError,
    ArtifactDescriptor,
    CacheInvalidationCommand,
    CacheInvalidationService,
    InMemoryImmutableAuditLog,
    ModelActivationCommand,
    ModelActivationService,
    ModelRollbackCommand,
    OperatorClaims,
    Sha256ArtifactVerifier,
)
from routing_api.persistence.records import (
    DeploymentRecord,
    ModelArtifactRecord,
    OptimizationBusLegEnrichmentRecord,
    OptimizationCandidateRecord,
    OptimizationLegRecord,
    OptimizationResultRecord,
    OptimizationRunRecord,
    OptimizationTransferEvaluationRecord,
)
from routing_api.persistence import ports
from routing_api.persistence.repositories import (
    DjangoModelRegistryRepository,
    DjangoOptimizationRunRepository,
    DjangoOptimizationResultRepository,
    PersistenceUnavailableError,
)

NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)


def _optimization_record() -> OptimizationResultRecord:
    route_id = uuid.uuid4()
    from_stop_id = uuid.uuid4()
    to_stop_id = uuid.uuid4()
    mapping_id = uuid.uuid4()
    return OptimizationResultRecord(
        run=OptimizationRunRecord(
            request_id="request-320",
            request_fingerprint="a" * 64,
            origin_wkt="POINT(127.1 37.2)",
            destination_wkt="POINT(127.2 37.3)",
            departure_time=NOW,
            constraints={"taxiBudget": {"maxAmount": 10_000}},
            status="COMPLETE",
            ranking_policy_version="rank-0.2.0",
            duration_ms=120,
            provider_summary={"GBIS_V2": "OK"},
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=2),
        ),
        candidates=(
            OptimizationCandidateRecord(
                "route-1",
                "TRANSIT_ONLY",
                900,
                1100,
                0,
                0,
                2800,
                120,
                1,
                Decimal("0.82"),
                True,
                ("LOW_TRANSFER_RISK",),
                ("BOARDABILITY_IS_PROXY",),
            ),
        ),
        legs=(
            OptimizationLegRecord(
                "route-1",
                0,
                "BUS",
                NOW,
                NOW + timedelta(seconds=900),
                900,
                1100,
                2800,
                ({"provider": "GBIS_V2", "operation": "arrivals"},),
                route_id,
                from_stop_id,
                to_stop_id,
                "LINESTRING(127.1 37.2,127.2 37.3)",
            ),
        ),
        bus_enrichments=(
            OptimizationBusLegEnrichmentRecord(
                "route-1",
                0,
                mapping_id,
                120,
                240,
                Decimal("0.75"),
                None,
                "PARTIAL",
                "eta-1",
                None,
                ({"vehicleToken": "opaque-1", "etaP50Seconds": 120},),
            ),
        ),
        transfer_evaluations=(
            OptimizationTransferEvaluationRecord(
                "route-1",
                0,
                180,
                120,
                60,
                -20,
                Decimal("0.8"),
                ("LOW_TRANSFER_RISK",),
            ),
        ),
    )


def test_routing_models_match_dbml_tables_and_nullable_unknowns_without_sqlite() -> None:
    expected = {
        "provider",
        "provider_operation_state",
        "transport_route",
        "transport_stop",
        "route_stop",
        "provider_entity",
        "entity_mapping",
        "mapping_review",
        "bus_vehicle",
        "bus_vehicle_trip",
        "bus_location_observation",
        "bus_arrival_observation",
        "vehicle_capacity_assertion",
        "route_optimization_run",
        "route_candidate",
        "route_leg",
        "bus_leg_enrichment",
        "transfer_evaluation",
        "model_family",
        "model_version",
        "model_metric",
        "model_deployment",
        "prediction_audit",
        "ingestion_source",
        "ingestion_checkpoint",
        "data_quality_run",
    }
    actual = {
        model._meta.db_table
        for model in apps.get_app_config("routing_api").get_models()
    }
    assert actual == expected
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.dummy"
    assert settings.ROUTING_DB_CONFIGURED is False
    assert models.BusLocationObservation._meta.get_field("remaining_seats").null
    assert models.BusArrivalObservation._meta.get_field("predicted_arrival_at").null
    assert models.BusLegEnrichment._meta.get_field("no_seat_probability").null
    assert models.TransportStop._meta.get_field("coordinate").db_type(None) == "geography(POINT,4326)"


def test_constraints_and_indexes_preserve_high_risk_invariants() -> None:
    constraint_names = {
        item.name
        for model in apps.get_app_config("routing_api").get_models()
        for item in model._meta.constraints
    }
    assert {
        "ck_mapping_one_target",
        "ck_candidate_duration",
        "ck_candidate_taxi_cost",
        "ck_bus_wait_order",
        "ck_no_seat_probability",
        "ck_model_version_state",
        "ck_deployment_state",
        "ck_deployment_state_traffic",
        "ck_retired_deactivated",
        "uq_checkpoint_partition",
    } <= constraint_names
    assert models.RouteStop._meta.pk.__class__.__name__ == "CompositePrimaryKey"


def test_persistence_ports_are_django_independent_and_postgis_config_is_env_driven() -> None:
    assert "django" not in inspect.getsource(ports)
    environment = dict(os.environ)
    service_root = Path(__file__).resolve().parents[2]
    environment.update(
        {
            "ROUTING_DB_NAME": "routing_test",
            "ROUTING_DB_USER": "routing_owner",
            "ROUTING_DB_PASSWORD": "not-logged",
            "ROUTING_DB_HOST": "routing-db.internal",
            "ROUTING_DB_SSLMODE": "verify-full",
        }
    )
    environment["PYTHONPATH"] = str(service_root)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import routing_api.settings as s; d=s.DATABASES['default']; "
                "assert d['ENGINE']=='django.contrib.gis.db.backends.postgis'; "
                "assert d['NAME']=='routing_test' and d['USER']=='routing_owner'; "
                "assert d['OPTIONS']['sslmode']=='verify-full'; "
                "assert s.ROUTING_DB_CONFIGURED is True"
            ),
        ],
        cwd=str(service_root),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_optimization_result_adapter_owns_candidate_and_leg_transaction_without_orm_leak() -> None:
    assert hasattr(ports, "OptimizationResultRepository")
    source = inspect.getsource(DjangoOptimizationResultRepository)
    assert "@transaction.atomic" in source
    assert "DjangoOptimizationRunRepository" in source
    assert "models.RouteCandidate" in source
    assert "models.RouteLeg" in source
    assert "models.BusLegEnrichment" in source
    assert "models.TransferEvaluation" in source
    assert "route_id=item.transport_route_id" in source


def test_optimization_record_preserves_refs_nullable_bus_values_and_strict_budget() -> None:
    record = _optimization_record()
    assert record.legs[0].transport_route_id is not None
    assert record.bus_enrichments[0].no_seat_probability is None
    assert record.bus_enrichments[0].seat_model_version is None
    assert record.legs[0].provenance[0]["provider"] == "GBIS_V2"

    candidate = replace(record.candidates[0], taxi_cost_expected=10_001, taxi_cost_upper=10_001)
    with pytest.raises(ValueError, match="strict taxi upper budget"):
        replace(record, candidates=(candidate,))
    with pytest.raises(ValueError, match="P90"):
        replace(record.bus_enrichments[0], p90_wait_seconds=119)
    with pytest.raises(ValueError, match="reference a persisted leg"):
        replace(
            record,
            transfer_evaluations=(
                replace(record.transfer_evaluations[0], leg_sequence=9),
            ),
        )


def test_unconfigured_postgis_rejects_before_any_orm_or_transaction_call() -> None:
    with patch.object(models.RouteOptimizationRun.objects, "update_or_create") as write:
        with pytest.raises(PersistenceUnavailableError):
            DjangoOptimizationResultRepository().persist(_optimization_record())
    write.assert_not_called()


def test_full_optimization_subtree_is_built_in_one_atomic_adapter() -> None:
    record = _optimization_record()
    run = models.RouteOptimizationRun()
    candidate_bulk = MagicMock(side_effect=lambda values: values)
    leg_bulk = MagicMock(side_effect=lambda values, **_kwargs: values)
    bus_bulk = MagicMock(side_effect=lambda values: values)
    transfer_bulk = MagicMock(side_effect=lambda values: values)
    run_query = MagicMock()
    run_query.get.return_value = run
    original = DjangoOptimizationResultRepository.persist
    while hasattr(original, "__wrapped__"):
        original = original.__wrapped__
    with (
        patch.object(
            DjangoOptimizationRunRepository, "save", return_value=str(run.pk)
        ),
        patch.object(models.RouteOptimizationRun.objects, "select_for_update", return_value=run_query),
        patch.object(models.RouteCandidate.objects, "bulk_create", candidate_bulk),
        patch.object(models.RouteCandidate.objects, "filter", return_value=MagicMock()),
        patch.object(models.RouteLeg.objects, "bulk_create", leg_bulk),
        patch.object(models.BusLegEnrichment.objects, "bulk_create", bus_bulk),
        patch.object(models.TransferEvaluation.objects, "bulk_create", transfer_bulk),
    ):
        original(DjangoOptimizationResultRepository(), record)
    persisted_leg = leg_bulk.call_args.args[0][0]
    persisted_bus = bus_bulk.call_args.args[0][0]
    persisted_transfer = transfer_bulk.call_args.args[0][0]
    assert persisted_leg.route_id == record.legs[0].transport_route_id
    assert persisted_leg.from_stop_id == record.legs[0].from_stop_id
    assert persisted_leg.to_stop_id == record.legs[0].to_stop_id
    assert persisted_leg.geometry == record.legs[0].geometry_wkt
    assert leg_bulk.call_args.kwargs["batch_size"] == 1
    assert persisted_bus.no_seat_probability is None
    assert persisted_bus.entity_mapping_id == record.bus_enrichments[0].entity_mapping_id
    assert persisted_transfer.margin_p90_seconds == -20


def test_model_state_contract_matches_code_registry_and_worker_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src_root = Path(__file__).resolve().parents[4]
    codes = (src_root / "contracts/codes/reason-warning-error-codes.yaml").read_text(
        encoding="utf-8"
    )
    match = re.search(r"ModelDeploymentState:\s*\[([^]]+)]", codes)
    assert match is not None
    canonical = {value.strip() for value in match.group(1).split(",")}

    worker_root = src_root / "workers/model-jobs"
    monkeypatch.syspath_prepend(str(src_root / "workers"))
    monkeypatch.syspath_prepend(str(worker_root))
    module_name = "ri320_worker_registry_contract"
    spec = importlib.util.spec_from_file_location(module_name, worker_root / "registry.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        worker_states = {item.value for item in module.ModelState}
    finally:
        sys.modules.pop(module_name, None)

    model_states = {value for value, _ in models.MODEL_DEPLOYMENT_CHOICES}
    assert canonical == worker_states == model_states
    assert {"INACTIVE", "ROLLED_BACK"}.isdisjoint(model_states)


def test_repository_rollback_promotes_prior_target_and_retires_current_atomically() -> None:
    family = SimpleNamespace(id=uuid.uuid4(), pk=uuid.uuid4(), purpose="BUS_ETA")
    target = SimpleNamespace(
        id=uuid.uuid4(),
        family=family,
        family_id=family.id,
        version="eta-prior",
        status="RETIRED",
        save=MagicMock(),
    )
    current_model = SimpleNamespace(status="ACTIVE", save=MagicMock())
    current = SimpleNamespace(
        model_version=current_model,
        deployment_state="ACTIVE",
        deactivated_at=None,
        save=MagicMock(),
    )
    target_history = SimpleNamespace(deployment_state="RETIRED")
    created = SimpleNamespace(pk=uuid.uuid4())
    final = SimpleNamespace(
        id=created.pk,
        model_version=target,
        environment="staging",
        deployment_state="ACTIVE",
        traffic_fraction=Decimal("1"),
        activated_at=NOW,
        deactivated_at=None,
    )

    version_manager = MagicMock()
    version_manager.select_for_update.return_value.select_related.return_value.get.return_value = target
    family_manager = MagicMock()
    target_query = MagicMock()
    target_query.filter.return_value.order_by.return_value.first.return_value = target_history
    current_query = MagicMock()
    current_query.select_related.return_value.filter.return_value.exclude.return_value.first.return_value = current
    deployment_manager = MagicMock()
    deployment_manager.select_for_update.side_effect = [target_query, current_query]
    deployment_manager.create.return_value = created
    deployment_manager.select_related.return_value.get.return_value = final

    original = DjangoModelRegistryRepository.rollback
    while hasattr(original, "__wrapped__"):
        original = original.__wrapped__
    with (
        patch.object(models.ModelVersion, "objects", version_manager),
        patch.object(models.ModelFamily, "objects", family_manager),
        patch.object(models.ModelDeployment, "objects", deployment_manager),
    ):
        result = original(
            DjangoModelRegistryRepository(),
            purpose="BUS_ETA",
            target_version="eta-prior",
            environment="staging",
            occurred_at=NOW,
        )

    assert result.state == "ACTIVE"
    assert current.deployment_state == "RETIRED"
    assert current.deactivated_at == NOW
    assert current_model.status == "RETIRED"
    assert target.status == "ACTIVE"
    current.save.assert_called_once_with(
        update_fields=("deactivated_at", "deployment_state")
    )
    current_model.save.assert_called_once_with(update_fields=("status",))
    target.save.assert_called_once_with(update_fields=("status",))


class FakeCache:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def invalidate(self, namespace: str, fingerprint: str | None) -> None:
        self.calls.append((namespace, fingerprint))


def claims(*, role: str = "routing-admin", environment: str = "staging") -> OperatorClaims:
    return OperatorClaims("operator-claim-123", frozenset({role}), frozenset({environment}))


def test_cache_invalidation_requires_operator_and_closed_allowlists() -> None:
    cache = FakeCache()
    audit = InMemoryImmutableAuditLog()
    service = CacheInvalidationService(
        invalidator=cache,
        audit=audit,
        allowed_namespaces=frozenset({"provider-routes", "model-runtime"}),
        allowed_environments=frozenset({"staging", "prod"}),
        clock=lambda: NOW,
    )
    digest = "a" * 64
    service.invalidate(
        CacheInvalidationCommand("provider-routes", "staging", digest), claims()
    )
    assert cache.calls == [("provider-routes", digest)]
    assert audit.events[0].action == "CACHE_INVALIDATED"
    assert isinstance(audit.events, tuple)

    with pytest.raises(AdminAuthorizationError):
        service.invalidate(
            CacheInvalidationCommand("provider-routes", "staging"),
            claims(role="service-api"),
        )
    with pytest.raises(AdminValidationError):
        service.invalidate(CacheInvalidationCommand("unknown", "staging"), claims())
    with pytest.raises(AdminValidationError):
        service.invalidate(
            CacheInvalidationCommand("provider-routes", "staging", "not-a-digest"),
            claims(),
        )


def test_artifact_verifier_rejects_paths_buckets_schema_and_digest_mismatch() -> None:
    payload = b"safe-onnx-like-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    verifier = Sha256ArtifactVerifier(
        loader=lambda _: payload,
        allowed_buckets=frozenset({"routing-model-registry"}),
        allowed_feature_schemas=frozenset({"bus-features-v1"}),
    )
    verifier.verify(
        ArtifactDescriptor(
            "gs://routing-model-registry/models/eta.onnx",
            digest,
            "bus-features-v1",
        )
    )
    verifier.verify(
        ArtifactDescriptor(
            "gs://routing-model-registry/models/seat-risk.txt",
            digest,
            "bus-features-v1",
        )
    )
    for descriptor in (
        ArtifactDescriptor("file:///tmp/model.pkl", digest, "bus-features-v1"),
        ArtifactDescriptor("gs://other/model.onnx", digest, "bus-features-v1"),
        ArtifactDescriptor("gs://routing-model-registry/model.onnx", digest, "unknown"),
        ArtifactDescriptor("gs://routing-model-registry/model.onnx", "0" * 64, "bus-features-v1"),
        ArtifactDescriptor("gs://routing-model-registry/model.pkl", digest, "bus-features-v1"),
        ArtifactDescriptor("gs://routing-model-registry/models/../model.onnx", digest, "bus-features-v1"),
        ArtifactDescriptor("gs://routing-model-registry/model.onnx?versionId=caller", digest, "bus-features-v1"),
        ArtifactDescriptor("gs://routing-model-registry/model.onnx#fragment", digest, "bus-features-v1"),
        ArtifactDescriptor("gs://user@routing-model-registry/model.onnx", digest, "bus-features-v1"),
        ArtifactDescriptor("gs://routing-model-registry:443/model.onnx", digest, "bus-features-v1"),
        ArtifactDescriptor("gs://routing-model-registry/models//model.onnx", digest, "bus-features-v1"),
        ArtifactDescriptor("gs://routing-model-registry/models/%2e%2e/model.onnx", digest, "bus-features-v1"),
    ):
        with pytest.raises(AdminValidationError):
            verifier.verify(descriptor)


class FakeRegistry:
    def __init__(self, artifact: ModelArtifactRecord) -> None:
        self.artifact = artifact
        self.transitions: list[tuple[str, str, float]] = []
        self.rollbacks: list[str] = []
        self.deployment: DeploymentRecord | None = None

    def get_artifact(self, purpose: str, version: str):
        if purpose == self.artifact.purpose and version == self.artifact.version:
            return self.artifact
        return None

    def get_deployment(self, purpose: str, version: str, environment: str):
        return self.deployment

    def transition(self, **values):
        current_status = "VALIDATED" if self.deployment is None else self.deployment.state
        if values["expected_status"] != current_status:
            raise ValueError("concurrent")
        self.transitions.append(
            (values["expected_status"], values["target_status"], values["traffic_fraction"])
        )
        self.artifact = replace(self.artifact, status=values["target_status"])
        self.deployment = DeploymentRecord(
            uuid.uuid4(),
            self.artifact.purpose,
            self.artifact.version,
            values["environment"],
            values["target_status"],
            Decimal(str(values["traffic_fraction"])),
            values["occurred_at"],
            None,
        )
        return self.deployment

    def rollback(self, **values):
        self.rollbacks.append(values["target_version"])
        return DeploymentRecord(
            uuid.uuid4(),
            self.artifact.purpose,
            self.artifact.version,
            values["environment"],
            "ACTIVE",
            Decimal("1"),
            values["occurred_at"],
            None,
        )


def test_model_activation_enforces_artifact_and_validated_shadow_canary_active_lifecycle() -> None:
    payload = b"validated-safe-artifact"
    artifact = ModelArtifactRecord(
        uuid.uuid4(),
        "BUS_ETA",
        "eta-1.2.3",
        "VALIDATED",
        "gs://routing-model-registry/eta-1.2.3.onnx",
        hashlib.sha256(payload).hexdigest(),
        "bus-features-v1",
    )
    registry = FakeRegistry(artifact)
    audit = InMemoryImmutableAuditLog()
    service = ModelActivationService(
        registry=registry,
        verifier=Sha256ArtifactVerifier(
            loader=lambda _: payload,
            allowed_buckets=frozenset({"routing-model-registry"}),
            allowed_feature_schemas=frozenset({"bus-features-v1"}),
        ),
        audit=audit,
        allowed_environments=frozenset({"staging"}),
        clock=lambda: NOW,
    )
    service.activate(ModelActivationCommand("BUS_ETA", "eta-1.2.3", "staging", 0), claims())
    service.activate(ModelActivationCommand("BUS_ETA", "eta-1.2.3", "staging", 0.1), claims())
    active = service.activate(
        ModelActivationCommand("BUS_ETA", "eta-1.2.3", "staging", 1), claims()
    )
    assert registry.transitions == [
        ("VALIDATED", "SHADOW", 0),
        ("SHADOW", "CANARY", 0.1),
        ("CANARY", "ACTIVE", 1),
    ]
    assert active.state == "ACTIVE"
    assert len(audit.events) == 3
    with pytest.raises(AdminConflictError):
        service.activate(ModelActivationCommand("BUS_ETA", "eta-1.2.3", "staging", 1), claims())

    registry.artifact = replace(
        registry.artifact, version="eta-1.1.0", status="CANARY"
    )
    with pytest.raises(AdminConflictError):
        service.rollback(
            ModelRollbackCommand("BUS_ETA", "eta-1.1.0", "staging"), claims()
        )
    registry.artifact = replace(registry.artifact, status="RETIRED")
    rolled_back = service.rollback(
        ModelRollbackCommand("BUS_ETA", "eta-1.1.0", "staging"), claims()
    )
    assert rolled_back.state == "ACTIVE"
    assert registry.rollbacks == ["eta-1.1.0"]
    assert audit.events[-1].action == "MODEL_ROLLED_BACK"
