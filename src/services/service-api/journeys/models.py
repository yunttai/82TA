from __future__ import annotations

import json
import math
import re
import struct
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


def _normalized_coordinate(value: Any) -> dict[str, float]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValidationError("Coordinate must be valid JSON.") from exc
    if not isinstance(value, dict) or set(value) != {"lon", "lat"}:
        raise ValidationError("Coordinate must contain only lon and lat.")
    lon = value.get("lon")
    lat = value.get("lat")
    if isinstance(lon, bool) or isinstance(lat, bool):
        raise ValidationError("Coordinate values must be numbers.")
    try:
        normalized = {"lon": float(lon), "lat": float(lat)}
    except (TypeError, ValueError) as exc:
        raise ValidationError("Coordinate values must be numbers.") from exc
    if not math.isfinite(normalized["lon"]) or not math.isfinite(normalized["lat"]):
        raise ValidationError("Coordinate values must be finite.")
    if not -180 <= normalized["lon"] <= 180 or not -90 <= normalized["lat"] <= 90:
        raise ValidationError("Coordinate is outside WGS84 bounds.")
    return normalized


_EWKT_POINT = re.compile(
    r"^(?:SRID=(?P<srid>[0-9]+);)?POINT\s*\(\s*(?P<lon>[-+0-9.eE]+)\s+(?P<lat>[-+0-9.eE]+)\s*\)$",
    re.IGNORECASE,
)


def _coordinate_from_wkb(raw: bytes) -> dict[str, float]:
    if len(raw) < 21 or raw[0] not in (0, 1):
        raise ValidationError("Coordinate database value is not a WKB point.")
    byte_order = "<" if raw[0] == 1 else ">"
    geometry_type = struct.unpack_from(f"{byte_order}I", raw, 1)[0]
    if geometry_type & 0xC0000000:
        raise ValidationError("Coordinate database value must be a two-dimensional point.")
    has_srid = bool(geometry_type & 0x20000000)
    if geometry_type & 0x0FFFFFFF != 1:
        raise ValidationError("Coordinate database value is not a point.")
    offset = 5
    if has_srid:
        if len(raw) < 25:
            raise ValidationError("Coordinate database value is truncated.")
        srid = struct.unpack_from(f"{byte_order}I", raw, offset)[0]
        if srid != 4326:
            raise ValidationError("Coordinate database value must use SRID 4326.")
        offset += 4
    if len(raw) != offset + 16:
        raise ValidationError("Coordinate database point has an invalid size.")
    lon, lat = struct.unpack_from(f"{byte_order}dd", raw, offset)
    return _normalized_coordinate({"lon": lon, "lat": lat})


def _coordinate_from_database(value: Any) -> dict[str, float]:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        if len(value) >= 21 and value[0] in (0, 1):
            return _coordinate_from_wkb(value)
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return _coordinate_from_wkb(value)
    if isinstance(value, str):
        stripped = value.strip()
        ewkt = _EWKT_POINT.fullmatch(stripped)
        if ewkt:
            srid = ewkt.group("srid")
            if srid is not None and int(srid) != 4326:
                raise ValidationError("Coordinate database value must use SRID 4326.")
            return _normalized_coordinate(
                {"lon": ewkt.group("lon"), "lat": ewkt.group("lat")}
            )
        hex_value = stripped.removeprefix("\\x")
        try:
            return _coordinate_from_wkb(bytes.fromhex(hex_value))
        except ValueError:
            return _normalized_coordinate(value)
    if hasattr(value, "x") and hasattr(value, "y"):
        srid = getattr(value, "srid", 4326)
        if srid not in (None, 4326):
            raise ValidationError("Coordinate database value must use SRID 4326.")
        return _normalized_coordinate({"lon": value.x, "lat": value.y})
    raise ValidationError("Coordinate database value has an unsupported representation.")


class WGS84PointField(models.Field):
    """Portable WGS84 point with a PostGIS geography production representation."""

    description = "WGS84 geography point"

    def db_type(self, connection: Any) -> str:
        if connection.vendor == "postgresql":
            return "geography(Point,4326)"
        return "text"

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Any:
        if value is None or isinstance(value, dict):
            return value
        if connection.vendor == "postgresql":
            return _coordinate_from_database(value)
        return _normalized_coordinate(value)

    def to_python(self, value: Any) -> Any:
        if value is None or (isinstance(value, dict) and set(value) == {"lon", "lat"}):
            return value
        return _normalized_coordinate(value)

    def get_prep_value(self, value: Any) -> Any:
        if value is None:
            return None
        coordinate = _normalized_coordinate(value)
        return json.dumps(coordinate, sort_keys=True, separators=(",", ":"))

    def get_db_prep_value(self, value: Any, connection: Any, prepared: bool = False) -> Any:
        if value is None:
            return None
        coordinate = _normalized_coordinate(value)
        if connection.vendor == "postgresql":
            return f"SRID=4326;POINT({coordinate['lon']} {coordinate['lat']})"
        return json.dumps(coordinate, sort_keys=True, separators=(",", ":"))


_FORBIDDEN_PUBLIC_RESULT_KEYS = frozenset(
    {
        "rawPayload",
        "raw_payload",
        "plate",
        "plateNumber",
        "vehiclePlate",
        "internalDbId",
        "modelArtifactUri",
        "featureVector",
        "providerCredential",
        "provider_credential",
        "providerQuota",
        "provider_quota",
    }
)


def validate_public_result_snapshot(value: Any) -> None:
    """Reject fields forbidden by the public-safe projection boundary."""

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            forbidden = _FORBIDDEN_PUBLIC_RESULT_KEYS.intersection(node)
            if forbidden:
                raise ValidationError(
                    "Public result contains forbidden fields: " + ", ".join(sorted(forbidden))
                )
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)


class ServiceUser(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "auth_user"
        constraints = [
            models.CheckConstraint(
                condition=Q(is_active=False) | Q(deleted_at__isnull=True),
                name="auth_user_active_not_deleted",
            )
        ]


class UserProfile(models.Model):
    user = models.OneToOneField(
        ServiceUser,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    nickname = models.CharField(max_length=20, default="82TA 사용자")
    locale = models.CharField(max_length=35, default="ko-KR")
    timezone = models.CharField(max_length=63, default="Asia/Seoul")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_profile"


class UserPreference(models.Model):
    user = models.OneToOneField(
        ServiceUser,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="preference",
    )
    default_taxi_budget = models.IntegerField(default=10_000)
    max_walk_seconds = models.IntegerField(default=900)
    max_transfers = models.IntegerField(default=3)
    max_taxi_legs = models.IntegerField(default=2)
    optimization_profile = models.CharField(max_length=32, default="BALANCED")
    accessibility = models.JSONField(default=dict, blank=True)
    privacy = models.JSONField(default=dict, blank=True)
    version = models.IntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_preference"
        constraints = [
            models.CheckConstraint(condition=Q(default_taxi_budget__gte=0), name="pref_budget_gte_0"),
            models.CheckConstraint(condition=Q(max_walk_seconds__gte=0), name="pref_walk_gte_0"),
            models.CheckConstraint(condition=Q(max_transfers__gte=0), name="pref_transfer_gte_0"),
            models.CheckConstraint(condition=Q(max_taxi_legs__gte=0), name="pref_taxi_legs_gte_0"),
            models.CheckConstraint(condition=Q(version__gte=1), name="pref_version_gte_1"),
        ]


class SavedPlace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(ServiceUser, on_delete=models.CASCADE, related_name="saved_places")
    label = models.CharField(max_length=50)
    display_name = models.CharField(max_length=255)
    coordinate = WGS84PointField()
    provider = models.CharField(max_length=64, null=True, blank=True)
    provider_place_id = models.CharField(max_length=255, null=True, blank=True)
    is_sensitive = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "saved_place"
        indexes = [models.Index(fields=["user", "deleted_at"], name="saved_place_owner_live")]


class FavoriteJourney(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(ServiceUser, on_delete=models.CASCADE, related_name="favorite_journeys")
    origin_saved_place = models.ForeignKey(
        SavedPlace,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="favorite_origins",
    )
    destination_saved_place = models.ForeignKey(
        SavedPlace,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="favorite_destinations",
    )
    default_constraints = models.JSONField(blank=True)
    nickname = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "favorite_journey"
        indexes = [models.Index(fields=["user", "deleted_at"], name="favorite_owner_live")]

    def clean(self) -> None:
        super().clean()
        for field_name in ("origin_saved_place", "destination_saved_place"):
            place = getattr(self, field_name, None)
            if place is not None and (place.user_id != self.user_id or place.deleted_at is not None):
                raise ValidationError(
                    {field_name: "Favorite journeys may use only active saved places owned by the user."}
                )


class AnonymousSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "anonymous_session"
        indexes = [models.Index(fields=["expires_at"], name="anonymous_expires")]


class AuthenticatedSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        ServiceUser,
        on_delete=models.CASCADE,
        related_name="authenticated_sessions",
    )
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "authenticated_session"
        indexes = [
            models.Index(fields=["user", "expires_at"], name="auth_session_owner_exp"),
            models.Index(fields=["expires_at"], name="auth_session_expires"),
        ]


class RouteSearchManager(models.Manager):
    def create_owned(
        self,
        *,
        user: ServiceUser | None,
        anonymous_session: AnonymousSession | None,
        save_to_history: bool,
        now=None,
        **values: Any,
    ):
        now = now or timezone.now()
        if (user is None) == (anonymous_session is None):
            raise ValidationError("A route search requires exactly one user or guest owner.")
        if save_to_history:
            if user is None:
                raise ValidationError("Guest searches cannot be saved to history.")
            latest = (
                ConsentRecord.objects.filter(user=user, consent_type="SEARCH_HISTORY")
                .order_by("-recorded_at", "-id")
                .first()
            )
            if latest is None or not latest.accepted:
                raise ValidationError("Current SEARCH_HISTORY consent is required.")
            maximum_retention = now + timedelta(days=90)
        else:
            maximum_retention = now + timedelta(hours=24)
        requested_retention = values.pop("retention_until", maximum_retention)
        if requested_retention > maximum_retention:
            raise ValidationError("Route search retention exceeds the allowed owner policy.")
        return self.create(
            user=user,
            anonymous_session=anonymous_session,
            save_to_history=save_to_history,
            retention_until=requested_retention,
            **values,
        )


class RouteSearch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        ServiceUser,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="route_searches",
    )
    anonymous_session = models.ForeignKey(
        AnonymousSession,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="route_searches",
    )
    origin_coordinate = WGS84PointField()
    destination_coordinate = WGS84PointField()
    origin_display_name = models.CharField(max_length=255, null=True, blank=True)
    destination_display_name = models.CharField(max_length=255, null=True, blank=True)
    departure_time = models.DateTimeField()
    arrival_deadline = models.DateTimeField(null=True, blank=True)
    taxi_budget_max = models.IntegerField()
    strict_budget = models.BooleanField()
    constraints = models.JSONField(blank=True)
    status = models.CharField(max_length=32)
    routing_request_id = models.CharField(max_length=128, unique=True)
    contract_version = models.CharField(max_length=32)
    save_to_history = models.BooleanField(default=False)
    retention_until = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    objects = RouteSearchManager()

    class Meta:
        db_table = "route_search"
        indexes = [
            models.Index(fields=["user", "created_at"], name="route_user_created"),
            models.Index(fields=["anonymous_session", "created_at"], name="route_guest_created"),
            models.Index(fields=["expires_at"], name="route_search_expires"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(user__isnull=False) & Q(anonymous_session__isnull=True))
                | (Q(user__isnull=True) & Q(anonymous_session__isnull=False)),
                name="route_search_one_owner",
            ),
            models.CheckConstraint(condition=Q(taxi_budget_max__gte=0), name="route_budget_gte_0"),
            models.CheckConstraint(
                condition=Q(save_to_history=False) | Q(user__isnull=False),
                name="route_history_user_only",
            ),
        ]


class RouteSearchResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route_search = models.ForeignKey(RouteSearch, on_delete=models.CASCADE, related_name="results")
    recommendation_type = models.CharField(max_length=32)
    routing_route_id = models.CharField(max_length=128)
    p50_seconds = models.IntegerField()
    p90_seconds = models.IntegerField()
    taxi_cost_expected = models.IntegerField()
    taxi_cost_upper = models.IntegerField()
    reliability_score = models.DecimalField(max_digits=7, decimal_places=6)
    public_result = models.JSONField(blank=True, validators=[validate_public_result_snapshot])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "route_search_result"
        indexes = [models.Index(fields=["route_search", "recommendation_type"], name="result_search_type")]
        constraints = [
            models.CheckConstraint(condition=Q(p50_seconds__gte=0), name="result_p50_gte_0"),
            models.CheckConstraint(condition=Q(p90_seconds__gte=models.F("p50_seconds")), name="result_p90_gte_p50"),
            models.CheckConstraint(condition=Q(taxi_cost_expected__gte=0), name="result_cost_expected_gte_0"),
            models.CheckConstraint(condition=Q(taxi_cost_upper__gte=0), name="result_cost_upper_gte_0"),
            models.CheckConstraint(
                condition=Q(reliability_score__gte=Decimal("0"))
                & Q(reliability_score__lte=Decimal("1")),
                name="result_reliability_0_1",
            ),
        ]


class RouteFeedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route_search = models.OneToOneField(RouteSearch, on_delete=models.CASCADE, related_name="feedback")
    user = models.ForeignKey(
        ServiceUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="route_feedback",
    )
    selected_route_id = models.CharField(max_length=128)
    actual_duration_seconds = models.IntegerField(null=True, blank=True)
    actual_taxi_cost = models.IntegerField(null=True, blank=True)
    arrived_on_time = models.BooleanField(null=True, blank=True)
    bus_outcome = models.JSONField(null=True, blank=True)
    rating = models.IntegerField(null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "route_feedback"
        constraints = [
            models.CheckConstraint(
                condition=Q(actual_duration_seconds__isnull=True) | Q(actual_duration_seconds__gte=0),
                name="feedback_duration_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(actual_taxi_cost__isnull=True) | Q(actual_taxi_cost__gte=0),
                name="feedback_cost_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(rating__isnull=True) | (Q(rating__gte=1) & Q(rating__lte=5)),
                name="feedback_rating_1_5",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.user_id is not None and self.route_search.user_id != self.user_id:
            raise ValidationError({"user": "Feedback user must own the route search."})


class ConsentRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(ServiceUser, on_delete=models.CASCADE, related_name="consent_records")
    consent_type = models.CharField(max_length=64)
    document_version = models.CharField(max_length=64)
    accepted = models.BooleanField()
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = "consent_record"
        indexes = [models.Index(fields=["user", "consent_type", "recorded_at"], name="consent_owner_type_time")]


class DataRightsJob(models.Model):
    class JobType(models.TextChoices):
        EXPORT = "EXPORT"
        DELETE = "DELETE"

    class Status(models.TextChoices):
        PENDING = "PENDING"
        RUNNING = "RUNNING"
        COMPLETE = "COMPLETE"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(ServiceUser, on_delete=models.CASCADE, related_name="data_rights_jobs")
    job_type = models.CharField(max_length=16, choices=JobType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    artifact_ref = models.CharField(max_length=512, null=True, blank=True)
    download_expires_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=64, null=True, blank=True)
    requested_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "data_rights_job"
        indexes = [models.Index(fields=["user", "job_type", "requested_at"], name="rights_owner_type_time")]
        constraints = [
            models.CheckConstraint(
                condition=Q(job_type__in=["EXPORT", "DELETE"]),
                name="rights_job_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["PENDING", "RUNNING", "COMPLETE", "FAILED"]),
                name="rights_job_status_valid",
            ),
        ]


class AccountAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        ServiceUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=64)
    safe_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "account_audit_event"
        indexes = [models.Index(fields=["user", "created_at"], name="audit_owner_created")]
