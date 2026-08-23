from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.db import transaction

from routing_api import models

from .records import (
    CheckpointRecord,
    DeploymentRecord,
    MappingRecord,
    ModelArtifactRecord,
    OptimizationRunRecord,
    OptimizationResultRecord,
    ProviderOperationRecord,
)


class PersistenceUnavailableError(RuntimeError):
    """Raised before ORM access when Routing PostGIS is not configured."""


def _requires_routing_database(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        if not settings.ROUTING_DB_CONFIGURED:
            raise PersistenceUnavailableError("Routing PostGIS is not configured")
        return function(*args, **kwargs)

    return guarded


class DjangoProviderStateRepository:
    @_requires_routing_database
    @transaction.atomic
    def save(self, record: ProviderOperationRecord) -> None:
        provider, _ = models.Provider.objects.update_or_create(
            code=record.provider_code,
            defaults={
                "category": record.provider_category,
                "enabled": record.enabled,
                "config_without_secret": dict(record.config_without_secret or {}),
                "updated_at": record.checked_at,
            },
        )
        models.ProviderOperationState.objects.update_or_create(
            provider=provider,
            operation=record.operation,
            defaults={
                "documentation_state": record.documentation_state,
                "key_verification_state": record.key_verification_state,
                "production_state": record.production_state,
                "health": record.health,
                "consecutive_failures": record.consecutive_failures,
                "checked_at": record.checked_at,
            },
        )


class DjangoCheckpointRepository:
    @_requires_routing_database
    @transaction.atomic
    def save(self, record: CheckpointRecord) -> None:
        source, _ = models.IngestionSource.objects.update_or_create(
            code=record.source_code,
            defaults={"data_type": record.data_type, "owner": record.owner},
        )
        models.IngestionCheckpoint.objects.update_or_create(
            source=source,
            partition_key=record.partition_key,
            defaults={
                "last_observed_at": record.last_observed_at,
                "last_success_at": record.last_success_at,
                "status": record.status,
                "cursor": dict(record.cursor),
            },
        )


class DjangoMappingRepository:
    @_requires_routing_database
    def save(self, record: MappingRecord) -> str:
        value = models.EntityMapping.objects.create(
            provider_entity_id=record.provider_entity_id,
            transport_route_id=record.transport_route_id,
            transport_stop_id=record.transport_stop_id,
            direction=record.direction,
            score=record.score,
            grade=record.grade,
            signal_breakdown=dict(record.signal_breakdown),
            algorithm_version=record.algorithm_version,
            valid_from=record.valid_from,
            valid_to=record.valid_to,
        )
        return str(value.pk)


class DjangoOptimizationRunRepository:
    @_requires_routing_database
    def save(self, record: OptimizationRunRecord) -> str:
        value, _ = models.RouteOptimizationRun.objects.update_or_create(
            request_id=record.request_id,
            defaults={
                "request_fingerprint": record.request_fingerprint,
                "origin": record.origin_wkt,
                "destination": record.destination_wkt,
                "departure_time": record.departure_time,
                "constraints": dict(record.constraints),
                "status": record.status,
                "ranking_policy_version": record.ranking_policy_version,
                "duration_ms": record.duration_ms,
                "provider_summary": dict(record.provider_summary),
                "created_at": record.created_at,
                "expires_at": record.expires_at,
            },
        )
        return str(value.pk)


class DjangoOptimizationResultRepository:
    """Transactional ORM adapter; canonical application records never expose ORM."""

    @_requires_routing_database
    @transaction.atomic
    def persist(self, record: OptimizationResultRecord) -> None:
        run_id = DjangoOptimizationRunRepository().save(record.run)
        run = models.RouteOptimizationRun.objects.select_for_update().get(pk=run_id)
        # Replaying the same request replaces only its owned candidate subtree.
        models.RouteCandidate.objects.filter(run=run).delete()
        candidates = models.RouteCandidate.objects.bulk_create(
            [
                models.RouteCandidate(
                    run=run,
                    route_key=item.route_key,
                    pattern=item.pattern,
                    p50_seconds=item.p50_seconds,
                    p90_seconds=item.p90_seconds,
                    taxi_cost_expected=item.taxi_cost_expected,
                    taxi_cost_upper=item.taxi_cost_upper,
                    total_fare_expected=item.total_fare_expected,
                    walk_seconds=item.walk_seconds,
                    transfer_count=item.transfer_count,
                    reliability_score=item.reliability_score,
                    pareto=item.pareto,
                    reason_codes=list(item.reason_codes),
                    warning_codes=list(item.warning_codes),
                )
                for item in record.candidates
            ]
        )
        by_key = {
            item.route_key: value
            for item, value in zip(record.candidates, candidates, strict=True)
        }
        legs = models.RouteLeg.objects.bulk_create(
            [
                models.RouteLeg(
                    candidate=by_key[item.route_key],
                    sequence=item.sequence,
                    mode=item.mode,
                    route_id=item.transport_route_id,
                    from_stop_id=item.from_stop_id,
                    to_stop_id=item.to_stop_id,
                    expected_start_at=item.expected_start_at,
                    expected_end_at=item.expected_end_at,
                    p50_seconds=item.p50_seconds,
                    p90_seconds=item.p90_seconds,
                    fare_expected=item.fare_expected,
                    geometry=item.geometry_wkt,
                    provenance=[
                        dict(value) if isinstance(value, Mapping) else value
                        for value in item.provenance
                    ],
                )
                for item in record.legs
            ]
        )
        by_leg = {
            (item.route_key, item.sequence): value
            for item, value in zip(record.legs, legs, strict=True)
        }
        models.BusLegEnrichment.objects.bulk_create(
            [
                models.BusLegEnrichment(
                    route_leg=by_leg[(item.route_key, item.leg_sequence)],
                    entity_mapping_id=item.entity_mapping_id,
                    expected_wait_seconds=item.expected_wait_seconds,
                    p90_wait_seconds=item.p90_wait_seconds,
                    boardability_proxy=item.boardability_proxy,
                    no_seat_probability=item.no_seat_probability,
                    coverage=item.coverage,
                    eta_model_version=item.eta_model_version,
                    seat_model_version=item.seat_model_version,
                    candidate_vehicles=[dict(value) for value in item.candidate_vehicles],
                )
                for item in record.bus_enrichments
            ]
        )
        models.TransferEvaluation.objects.bulk_create(
            [
                models.TransferEvaluation(
                    route_leg=by_leg[(item.route_key, item.leg_sequence)],
                    available_seconds=item.available_seconds,
                    required_seconds=item.required_seconds,
                    margin_p50_seconds=item.margin_p50_seconds,
                    margin_p90_seconds=item.margin_p90_seconds,
                    success_proxy=item.success_proxy,
                    reason_codes=list(item.reason_codes),
                )
                for item in record.transfer_evaluations
            ]
        )


def _artifact_record(value: models.ModelVersion) -> ModelArtifactRecord:
    return ModelArtifactRecord(
        id=value.id,
        purpose=value.family.purpose,
        version=value.version,
        status=value.status,
        artifact_uri=value.artifact_uri,
        artifact_sha256=value.artifact_sha256,
        feature_schema_version=value.feature_schema_version,
    )


def _deployment_record(value: models.ModelDeployment) -> DeploymentRecord:
    return DeploymentRecord(
        id=value.id,
        purpose=value.model_version.family.purpose,
        version=value.model_version.version,
        environment=value.environment,
        state=value.deployment_state,
        traffic_fraction=value.traffic_fraction,
        activated_at=value.activated_at,
        deactivated_at=value.deactivated_at,
    )


class DjangoModelRegistryRepository:
    @_requires_routing_database
    def get_artifact(self, purpose: str, version: str) -> ModelArtifactRecord | None:
        value = (
            models.ModelVersion.objects.select_related("family")
            .filter(family__purpose=purpose, version=version)
            .first()
        )
        return None if value is None else _artifact_record(value)

    @_requires_routing_database
    def get_deployment(
        self, purpose: str, version: str, environment: str
    ) -> DeploymentRecord | None:
        value = (
            models.ModelDeployment.objects.select_related("model_version__family")
            .filter(
                model_version__family__purpose=purpose,
                model_version__version=version,
                environment=environment,
                deactivated_at__isnull=True,
            )
            .order_by("-activated_at")
            .first()
        )
        return None if value is None else _deployment_record(value)

    @_requires_routing_database
    @transaction.atomic
    def transition(
        self,
        *,
        purpose: str,
        version: str,
        environment: str,
        expected_status: str,
        target_status: str,
        traffic_fraction: float,
        occurred_at,
    ) -> DeploymentRecord:
        artifact = models.ModelVersion.objects.select_for_update().select_related("family").get(
            family__purpose=purpose,
            version=version,
        )
        models.ModelFamily.objects.select_for_update().get(pk=artifact.family_id)
        current = (
            models.ModelDeployment.objects.select_for_update()
            .filter(
                model_version=artifact,
                environment=environment,
                deactivated_at__isnull=True,
            )
            .order_by("-activated_at")
            .first()
        )
        current_status = "VALIDATED" if current is None else current.deployment_state
        allowed_transition = {
            "VALIDATED": ("SHADOW", Decimal("0")),
            "SHADOW": ("CANARY", None),
            "CANARY": ("ACTIVE", Decimal("1")),
        }.get(expected_status)
        requested_fraction = Decimal(str(traffic_fraction))
        if (
            current_status != expected_status
            or artifact.status != expected_status
            or allowed_transition is None
            or allowed_transition[0] != target_status
            or (target_status == "CANARY" and not Decimal("0") < requested_fraction < Decimal("1"))
            or (allowed_transition[1] is not None and requested_fraction != allowed_transition[1])
        ):
            raise ValueError("model lifecycle changed concurrently")
        if current is not None:
            current.deactivated_at = occurred_at
            current.save(update_fields=("deactivated_at",))
        if target_status == "ACTIVE":
            superseded = tuple(
                models.ModelDeployment.objects.select_for_update()
                .select_related("model_version")
                .filter(
                    model_version__family=artifact.family,
                    environment=environment,
                    deployment_state="ACTIVE",
                    deactivated_at__isnull=True,
                )
                .exclude(model_version=artifact)
            )
            for previous in superseded:
                previous.deactivated_at = occurred_at
                previous.deployment_state = "RETIRED"
                previous.save(update_fields=("deactivated_at", "deployment_state"))
                previous.model_version.status = "RETIRED"
                previous.model_version.save(update_fields=("status",))
        artifact.status = target_status
        artifact.save(update_fields=("status",))
        deployment = models.ModelDeployment.objects.create(
            model_version=artifact,
            environment=environment,
            deployment_state=target_status,
            traffic_fraction=requested_fraction,
            activated_at=occurred_at,
        )
        return _deployment_record(
            models.ModelDeployment.objects.select_related("model_version__family").get(pk=deployment.pk)
        )

    @_requires_routing_database
    @transaction.atomic
    def rollback(
        self,
        *,
        purpose: str,
        target_version: str,
        environment: str,
        occurred_at,
    ) -> DeploymentRecord:
        target = models.ModelVersion.objects.select_for_update().select_related("family").get(
            family__purpose=purpose,
            version=target_version,
        )
        models.ModelFamily.objects.select_for_update().get(pk=target.family_id)
        if target.status not in {"ACTIVE", "RETIRED"}:
            raise ValueError("rollback target has not passed activation lifecycle")
        target_history = (
            models.ModelDeployment.objects.select_for_update()
            .filter(
                model_version=target,
                environment=environment,
                deployment_state__in=("ACTIVE", "RETIRED"),
                activated_at__isnull=False,
            )
            .order_by("-activated_at")
            .first()
        )
        current = (
            models.ModelDeployment.objects.select_for_update()
            .select_related("model_version")
            .filter(
                model_version__family=target.family,
                environment=environment,
                deployment_state="ACTIVE",
                deactivated_at__isnull=True,
            )
            .exclude(model_version=target)
            .first()
        )
        if target_history is None or current is None:
            raise ValueError("rollback target has not been previously promoted")
        current.deactivated_at = occurred_at
        current.deployment_state = "RETIRED"
        current.save(update_fields=("deactivated_at", "deployment_state"))
        current.model_version.status = "RETIRED"
        current.model_version.save(update_fields=("status",))
        target.status = "ACTIVE"
        target.save(update_fields=("status",))
        deployment = models.ModelDeployment.objects.create(
            model_version=target,
            environment=environment,
            deployment_state="ACTIVE",
            traffic_fraction=Decimal("1"),
            activated_at=occurred_at,
        )
        return _deployment_record(
            models.ModelDeployment.objects.select_related("model_version__family").get(pk=deployment.pk)
        )
