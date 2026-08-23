from __future__ import annotations

import uuid

from django.db import models
from django.db.models import F, Q


MODEL_DEPLOYMENT_STATES = (
    "REGISTERED",
    "VALIDATED",
    "SHADOW",
    "CANARY",
    "ACTIVE",
    "RETIRED",
    "REJECTED",
)
MODEL_DEPLOYMENT_CHOICES = tuple((value, value) for value in MODEL_DEPLOYMENT_STATES)
DEPLOYED_MODEL_STATES = ("SHADOW", "CANARY", "ACTIVE", "RETIRED")


class GeographyField(models.Field):
    """Migration-safe PostGIS geography field without importing native GDAL locally."""

    description = "PostGIS geography"

    def __init__(self, *args, geometry_type: str = "GEOMETRY", srid: int = 4326, **kwargs):
        self.geometry_type = geometry_type.upper()
        self.srid = srid
        super().__init__(*args, **kwargs)

    def db_type(self, connection):
        return f"geography({self.geometry_type},{self.srid})"

    def get_internal_type(self):
        return "TextField"

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["geometry_type"] = self.geometry_type
        kwargs["srid"] = self.srid
        return name, path, args, kwargs


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class Provider(UUIDModel):
    code = models.CharField(max_length=128, unique=True)
    category = models.CharField(max_length=64)
    enabled = models.BooleanField(default=True)
    config_without_secret = models.JSONField(default=dict)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "provider"


class ProviderOperationState(UUIDModel):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE)
    operation = models.CharField(max_length=128)
    documentation_state = models.CharField(max_length=32)
    key_verification_state = models.CharField(max_length=32)
    production_state = models.CharField(max_length=32)
    health = models.CharField(max_length=32)
    consecutive_failures = models.IntegerField(default=0)
    checked_at = models.DateTimeField()

    class Meta:
        db_table = "provider_operation_state"
        constraints = [
            models.UniqueConstraint(fields=("provider", "operation"), name="uq_provider_operation"),
            models.CheckConstraint(condition=Q(consecutive_failures__gte=0), name="ck_provider_failures_nonnegative"),
        ]


class TransportRoute(UUIDModel):
    canonical_name = models.CharField(max_length=255)
    mode = models.CharField(max_length=32)
    route_type = models.CharField(max_length=64, null=True, blank=True)
    region = models.CharField(max_length=128, null=True, blank=True)
    geometry = GeographyField(null=True, blank=True)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "transport_route"
        constraints = [models.CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")), name="ck_route_valid_window")]


class TransportStop(UUIDModel):
    canonical_name = models.CharField(max_length=255)
    region = models.CharField(max_length=128, null=True, blank=True)
    coordinate = GeographyField(geometry_type="POINT")
    attributes = models.JSONField(default=dict)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "transport_stop"
        constraints = [models.CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")), name="ck_stop_valid_window")]


class RouteStop(models.Model):
    pk = models.CompositePrimaryKey("route", "sequence", "direction")
    route = models.ForeignKey(TransportRoute, on_delete=models.CASCADE)
    stop = models.ForeignKey(TransportStop, on_delete=models.PROTECT)
    sequence = models.IntegerField()
    direction = models.CharField(max_length=128)
    cumulative_distance = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)

    class Meta:
        db_table = "route_stop"
        constraints = [
            models.CheckConstraint(condition=Q(sequence__gte=0), name="ck_route_stop_sequence"),
            models.CheckConstraint(condition=Q(cumulative_distance__isnull=True) | Q(cumulative_distance__gte=0), name="ck_route_stop_distance"),
        ]


class ProviderEntity(UUIDModel):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE)
    entity_type = models.CharField(max_length=64)
    external_id = models.CharField(max_length=255)
    fingerprint = models.CharField(max_length=128)
    normalized_identity = models.JSONField()
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "provider_entity"
        constraints = [
            models.UniqueConstraint(fields=("provider", "entity_type", "external_id", "valid_from"), name="uq_provider_entity_valid_from"),
            models.CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")), name="ck_provider_entity_window"),
        ]


class EntityMapping(UUIDModel):
    provider_entity = models.ForeignKey(ProviderEntity, on_delete=models.CASCADE)
    transport_route = models.ForeignKey(TransportRoute, on_delete=models.PROTECT, null=True, blank=True)
    transport_stop = models.ForeignKey(TransportStop, on_delete=models.PROTECT, null=True, blank=True)
    direction = models.CharField(max_length=128, null=True, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=6)
    grade = models.CharField(max_length=16)
    signal_breakdown = models.JSONField()
    algorithm_version = models.CharField(max_length=128)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "entity_mapping"
        indexes = [models.Index(fields=("provider_entity", "grade", "valid_from"), name="ix_mapping_lookup")]
        constraints = [
            models.CheckConstraint(condition=Q(score__gte=0) & Q(score__lte=1), name="ck_mapping_score_probability"),
            models.CheckConstraint(condition=(Q(transport_route__isnull=False) & Q(transport_stop__isnull=True)) | (Q(transport_route__isnull=True) & Q(transport_stop__isnull=False)), name="ck_mapping_one_target"),
            models.CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")), name="ck_mapping_valid_window"),
        ]


class MappingReview(UUIDModel):
    entity_mapping = models.ForeignKey(EntityMapping, on_delete=models.CASCADE)
    status = models.CharField(max_length=32)
    reviewer = models.CharField(max_length=255, null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mapping_review"


class BusVehicle(UUIDModel):
    provider_vehicle_token = models.CharField(max_length=255, unique=True)
    vehicle_type = models.CharField(max_length=64, null=True, blank=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()

    class Meta:
        db_table = "bus_vehicle"
        constraints = [models.CheckConstraint(condition=Q(last_seen_at__gte=F("first_seen_at")), name="ck_vehicle_seen_order")]


class BusVehicleTrip(UUIDModel):
    route = models.ForeignKey(TransportRoute, on_delete=models.PROTECT)
    vehicle = models.ForeignKey(BusVehicle, on_delete=models.PROTECT)
    service_date = models.DateField()
    direction = models.CharField(max_length=128)
    inferred_start_at = models.DateTimeField()
    inferred_end_at = models.DateTimeField(null=True, blank=True)
    identity_version = models.CharField(max_length=128)

    class Meta:
        db_table = "bus_vehicle_trip"
        indexes = [models.Index(fields=("route", "service_date", "direction"), name="ix_trip_identity")]
        constraints = [models.CheckConstraint(condition=Q(inferred_end_at__isnull=True) | Q(inferred_end_at__gte=F("inferred_start_at")), name="ck_trip_time_order")]


class BusLocationObservation(models.Model):
    id = models.BigAutoField(primary_key=True)
    trip = models.ForeignKey(BusVehicleTrip, on_delete=models.CASCADE)
    stop = models.ForeignKey(TransportStop, on_delete=models.PROTECT, null=True, blank=True)
    station_sequence = models.IntegerField(null=True, blank=True)
    remaining_seats = models.IntegerField(null=True, blank=True)
    crowded_code = models.IntegerField(null=True, blank=True)
    coordinate = GeographyField(geometry_type="POINT", null=True, blank=True)
    observed_at = models.DateTimeField()
    ingested_at = models.DateTimeField()
    source = models.CharField(max_length=128)
    quality_flags = models.JSONField(default=list)

    class Meta:
        db_table = "bus_location_observation"
        indexes = [models.Index(fields=("trip", "observed_at"), name="ix_location_trip_observed")]
        constraints = [
            models.CheckConstraint(condition=Q(station_sequence__isnull=True) | Q(station_sequence__gte=0), name="ck_location_sequence"),
            models.CheckConstraint(condition=Q(remaining_seats__isnull=True) | Q(remaining_seats__gte=0), name="ck_location_seats"),
            models.CheckConstraint(condition=Q(ingested_at__gte=F("observed_at")), name="ck_location_ingested_order"),
        ]


class BusArrivalObservation(models.Model):
    id = models.BigAutoField(primary_key=True)
    trip = models.ForeignKey(BusVehicleTrip, on_delete=models.CASCADE)
    stop = models.ForeignKey(TransportStop, on_delete=models.PROTECT)
    provider_eta_seconds = models.IntegerField(null=True, blank=True)
    remaining_seats = models.IntegerField(null=True, blank=True)
    observed_at = models.DateTimeField()
    predicted_arrival_at = models.DateTimeField(null=True, blank=True)
    ingested_at = models.DateTimeField()
    source = models.CharField(max_length=128)
    quality_flags = models.JSONField(default=list)

    class Meta:
        db_table = "bus_arrival_observation"
        indexes = [models.Index(fields=("stop", "observed_at"), name="ix_arrival_stop_observed")]
        constraints = [
            models.CheckConstraint(condition=Q(provider_eta_seconds__isnull=True) | Q(provider_eta_seconds__gte=0), name="ck_arrival_eta"),
            models.CheckConstraint(condition=Q(remaining_seats__isnull=True) | Q(remaining_seats__gte=0), name="ck_arrival_seats"),
            models.CheckConstraint(condition=Q(ingested_at__gte=F("observed_at")), name="ck_arrival_ingested_order"),
        ]


class VehicleCapacityAssertion(UUIDModel):
    vehicle = models.ForeignKey(BusVehicle, on_delete=models.CASCADE)
    capacity = models.IntegerField()
    source = models.CharField(max_length=128)
    confidence = models.DecimalField(max_digits=7, decimal_places=6)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "vehicle_capacity_assertion"
        constraints = [
            models.CheckConstraint(condition=Q(capacity__gt=0), name="ck_capacity_positive"),
            models.CheckConstraint(condition=Q(confidence__gte=0) & Q(confidence__lte=1), name="ck_capacity_confidence"),
            models.CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")), name="ck_capacity_window"),
        ]


class RouteOptimizationRun(UUIDModel):
    request_id = models.CharField(max_length=255, unique=True)
    request_fingerprint = models.CharField(max_length=128)
    origin = GeographyField(geometry_type="POINT")
    destination = GeographyField(geometry_type="POINT")
    departure_time = models.DateTimeField()
    constraints = models.JSONField()
    status = models.CharField(max_length=32)
    ranking_policy_version = models.CharField(max_length=128)
    duration_ms = models.IntegerField(null=True, blank=True)
    provider_summary = models.JSONField(default=dict)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "route_optimization_run"
        constraints = [
            models.CheckConstraint(condition=Q(duration_ms__isnull=True) | Q(duration_ms__gte=0), name="ck_run_duration"),
            models.CheckConstraint(condition=Q(expires_at__gt=F("created_at")), name="ck_run_expiry"),
        ]


class RouteCandidate(UUIDModel):
    run = models.ForeignKey(RouteOptimizationRun, on_delete=models.CASCADE)
    route_key = models.CharField(max_length=255)
    pattern = models.CharField(max_length=64)
    p50_seconds = models.IntegerField()
    p90_seconds = models.IntegerField()
    taxi_cost_expected = models.IntegerField()
    taxi_cost_upper = models.IntegerField()
    total_fare_expected = models.IntegerField()
    walk_seconds = models.IntegerField()
    transfer_count = models.IntegerField()
    reliability_score = models.DecimalField(max_digits=7, decimal_places=6)
    pareto = models.BooleanField()
    reason_codes = models.JSONField()
    warning_codes = models.JSONField()

    class Meta:
        db_table = "route_candidate"
        constraints = [
            models.UniqueConstraint(fields=("run", "route_key"), name="uq_candidate_run_key"),
            models.CheckConstraint(condition=Q(p50_seconds__gte=0) & Q(p90_seconds__gte=F("p50_seconds")), name="ck_candidate_duration"),
            models.CheckConstraint(condition=Q(taxi_cost_expected__gte=0) & Q(taxi_cost_upper__gte=F("taxi_cost_expected")), name="ck_candidate_taxi_cost"),
            models.CheckConstraint(condition=Q(total_fare_expected__gte=0) & Q(walk_seconds__gte=0) & Q(transfer_count__gte=0), name="ck_candidate_nonnegative"),
            models.CheckConstraint(condition=Q(reliability_score__gte=0) & Q(reliability_score__lte=1), name="ck_candidate_reliability"),
        ]


class RouteLeg(UUIDModel):
    candidate = models.ForeignKey(RouteCandidate, on_delete=models.CASCADE)
    sequence = models.IntegerField()
    mode = models.CharField(max_length=32)
    route = models.ForeignKey(TransportRoute, on_delete=models.PROTECT, null=True, blank=True)
    from_stop = models.ForeignKey(TransportStop, on_delete=models.PROTECT, null=True, blank=True, related_name="departing_route_legs")
    to_stop = models.ForeignKey(TransportStop, on_delete=models.PROTECT, null=True, blank=True, related_name="arriving_route_legs")
    expected_start_at = models.DateTimeField(null=True, blank=True)
    expected_end_at = models.DateTimeField(null=True, blank=True)
    p50_seconds = models.IntegerField()
    p90_seconds = models.IntegerField()
    fare_expected = models.IntegerField()
    geometry = GeographyField(null=True, blank=True)
    provenance = models.JSONField()

    class Meta:
        db_table = "route_leg"
        constraints = [
            models.UniqueConstraint(fields=("candidate", "sequence"), name="uq_leg_candidate_sequence"),
            models.CheckConstraint(condition=Q(sequence__gte=0), name="ck_leg_sequence"),
            models.CheckConstraint(condition=Q(p50_seconds__gte=0) & Q(p90_seconds__gte=F("p50_seconds")), name="ck_leg_duration"),
            models.CheckConstraint(condition=Q(fare_expected__gte=0), name="ck_leg_fare"),
            models.CheckConstraint(condition=Q(expected_start_at__isnull=True) | Q(expected_end_at__isnull=True) | Q(expected_end_at__gte=F("expected_start_at")), name="ck_leg_time_order"),
        ]


class BusLegEnrichment(models.Model):
    route_leg = models.OneToOneField(RouteLeg, primary_key=True, on_delete=models.CASCADE)
    entity_mapping = models.ForeignKey(EntityMapping, on_delete=models.PROTECT, null=True, blank=True)
    expected_wait_seconds = models.IntegerField()
    p90_wait_seconds = models.IntegerField()
    boardability_proxy = models.DecimalField(max_digits=7, decimal_places=6, null=True, blank=True)
    no_seat_probability = models.DecimalField(max_digits=7, decimal_places=6, null=True, blank=True)
    coverage = models.CharField(max_length=32)
    eta_model_version = models.CharField(max_length=128, null=True, blank=True)
    seat_model_version = models.CharField(max_length=128, null=True, blank=True)
    candidate_vehicles = models.JSONField()

    class Meta:
        db_table = "bus_leg_enrichment"
        constraints = [
            models.CheckConstraint(condition=Q(expected_wait_seconds__gte=0) & Q(p90_wait_seconds__gte=F("expected_wait_seconds")), name="ck_bus_wait_order"),
            models.CheckConstraint(condition=Q(boardability_proxy__isnull=True) | (Q(boardability_proxy__gte=0) & Q(boardability_proxy__lte=1)), name="ck_boardability_probability"),
            models.CheckConstraint(condition=Q(no_seat_probability__isnull=True) | (Q(no_seat_probability__gte=0) & Q(no_seat_probability__lte=1)), name="ck_no_seat_probability"),
        ]


class TransferEvaluation(UUIDModel):
    route_leg = models.ForeignKey(RouteLeg, on_delete=models.CASCADE)
    available_seconds = models.IntegerField()
    required_seconds = models.IntegerField()
    margin_p50_seconds = models.IntegerField()
    margin_p90_seconds = models.IntegerField()
    success_proxy = models.DecimalField(max_digits=7, decimal_places=6, null=True, blank=True)
    reason_codes = models.JSONField()

    class Meta:
        db_table = "transfer_evaluation"
        constraints = [
            models.CheckConstraint(condition=Q(available_seconds__gte=0) & Q(required_seconds__gte=0), name="ck_transfer_nonnegative"),
            models.CheckConstraint(condition=Q(success_proxy__isnull=True) | (Q(success_proxy__gte=0) & Q(success_proxy__lte=1)), name="ck_transfer_probability"),
        ]


class ModelFamily(UUIDModel):
    purpose = models.CharField(max_length=64, unique=True)
    target_definition = models.TextField()
    owner = models.CharField(max_length=255)

    class Meta:
        db_table = "model_family"


class ModelVersion(UUIDModel):
    family = models.ForeignKey(ModelFamily, on_delete=models.PROTECT)
    version = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=32, choices=MODEL_DEPLOYMENT_CHOICES)
    artifact_uri = models.CharField(max_length=1024)
    artifact_sha256 = models.CharField(max_length=64)
    feature_schema_version = models.CharField(max_length=128)
    training_scope = models.JSONField()
    created_at = models.DateTimeField()

    class Meta:
        db_table = "model_version"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=MODEL_DEPLOYMENT_STATES),
                name="ck_model_version_state",
            )
        ]


class ModelMetric(UUIDModel):
    model_version = models.ForeignKey(ModelVersion, on_delete=models.CASCADE)
    split_name = models.CharField(max_length=64)
    slice_key = models.CharField(max_length=255)
    metrics = models.JSONField()
    evaluated_at = models.DateTimeField()

    class Meta:
        db_table = "model_metric"
        indexes = [models.Index(fields=("model_version", "split_name", "slice_key"), name="ix_model_metric_slice")]


class ModelDeployment(UUIDModel):
    model_version = models.ForeignKey(ModelVersion, on_delete=models.PROTECT)
    environment = models.CharField(max_length=32)
    deployment_state = models.CharField(
        max_length=32, choices=MODEL_DEPLOYMENT_CHOICES
    )
    traffic_fraction = models.DecimalField(max_digits=7, decimal_places=6)
    activated_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "model_deployment"
        indexes = [models.Index(fields=("environment", "deployment_state"), name="ix_deployment_active")]
        constraints = [
            models.UniqueConstraint(fields=("model_version", "environment"), condition=Q(deactivated_at__isnull=True), name="uq_deployment_current"),
            models.CheckConstraint(condition=Q(traffic_fraction__gte=0) & Q(traffic_fraction__lte=1), name="ck_deployment_traffic"),
            models.CheckConstraint(condition=Q(deployment_state__in=DEPLOYED_MODEL_STATES), name="ck_deployment_state"),
            models.CheckConstraint(
                condition=~Q(deployment_state="RETIRED")
                | Q(deactivated_at__isnull=False),
                name="ck_retired_deactivated",
            ),
            models.CheckConstraint(
                condition=(
                    Q(deployment_state="SHADOW", traffic_fraction=0)
                    | Q(
                        deployment_state="CANARY",
                        traffic_fraction__gt=0,
                        traffic_fraction__lt=1,
                    )
                    | Q(deployment_state="ACTIVE", traffic_fraction=1)
                    | Q(deployment_state="RETIRED")
                ),
                name="ck_deployment_state_traffic",
            ),
            models.CheckConstraint(
                condition=Q(deactivated_at__isnull=True)
                | (
                    Q(activated_at__isnull=False)
                    & Q(deactivated_at__gte=F("activated_at"))
                ),
                name="ck_deployment_activation_order",
            ),
        ]


class PredictionAudit(models.Model):
    id = models.BigAutoField(primary_key=True)
    model_version = models.ForeignKey(ModelVersion, on_delete=models.PROTECT)
    request_id = models.CharField(max_length=255)
    entity_key = models.CharField(max_length=255)
    input_summary = models.JSONField()
    prediction = models.JSONField()
    created_at = models.DateTimeField()

    class Meta:
        db_table = "prediction_audit"
        indexes = [models.Index(fields=("model_version", "created_at"), name="ix_prediction_model_time")]


class IngestionSource(UUIDModel):
    code = models.CharField(max_length=128, unique=True)
    data_type = models.CharField(max_length=64)
    owner = models.CharField(max_length=255)

    class Meta:
        db_table = "ingestion_source"


class IngestionCheckpoint(UUIDModel):
    source = models.ForeignKey(IngestionSource, on_delete=models.CASCADE)
    partition_key = models.CharField(max_length=255)
    last_observed_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32)
    cursor = models.JSONField(default=dict)

    class Meta:
        db_table = "ingestion_checkpoint"
        constraints = [models.UniqueConstraint(fields=("source", "partition_key"), name="uq_checkpoint_partition")]


class DataQualityRun(UUIDModel):
    source = models.ForeignKey(IngestionSource, on_delete=models.PROTECT)
    dataset_version = models.CharField(max_length=128)
    status = models.CharField(max_length=32)
    metrics = models.JSONField()
    violations = models.JSONField()
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "data_quality_run"
        constraints = [models.CheckConstraint(condition=Q(finished_at__isnull=True) | Q(finished_at__gte=F("started_at")), name="ck_quality_run_order")]
