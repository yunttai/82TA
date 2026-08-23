import uuid
from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models

import journeys.models


def ensure_postgis(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("CREATE EXTENSION IF NOT EXISTS postgis")


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.RunPython(ensure_postgis, migrations.RunPython.noop),
        migrations.CreateModel(
            name="ServiceUser",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("password_hash", models.CharField(blank=True, max_length=255, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "auth_user"},
        ),
        migrations.CreateModel(
            name="AnonymousSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("token_hash", models.CharField(max_length=128, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "anonymous_session",
                "indexes": [models.Index(fields=["expires_at"], name="anonymous_expires")],
            },
        ),
        migrations.CreateModel(
            name="AuthenticatedSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("token_hash", models.CharField(max_length=128, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="authenticated_sessions",
                        to="journeys.serviceuser",
                    ),
                ),
            ],
            options={
                "db_table": "authenticated_session",
                "indexes": [
                    models.Index(fields=["user", "expires_at"], name="auth_session_owner_exp"),
                    models.Index(fields=["expires_at"], name="auth_session_expires"),
                ],
            },
        ),
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="profile",
                        serialize=False,
                        to="journeys.serviceuser",
                    ),
                ),
                ("locale", models.CharField(default="ko-KR", max_length=35)),
                ("timezone", models.CharField(default="Asia/Seoul", max_length=63)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "user_profile"},
        ),
        migrations.CreateModel(
            name="UserPreference",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="preference",
                        serialize=False,
                        to="journeys.serviceuser",
                    ),
                ),
                ("default_taxi_budget", models.IntegerField(default=10000)),
                ("max_walk_seconds", models.IntegerField(default=900)),
                ("max_transfers", models.IntegerField(default=3)),
                ("max_taxi_legs", models.IntegerField(default=2)),
                ("optimization_profile", models.CharField(default="BALANCED", max_length=32)),
                ("accessibility", models.JSONField(blank=True, default=dict)),
                ("privacy", models.JSONField(blank=True, default=dict)),
                ("version", models.IntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "user_preference"},
        ),
        migrations.CreateModel(
            name="SavedPlace",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("label", models.CharField(max_length=50)),
                ("display_name", models.CharField(max_length=255)),
                ("coordinate", journeys.models.WGS84PointField()),
                ("provider", models.CharField(blank=True, max_length=64, null=True)),
                ("provider_place_id", models.CharField(blank=True, max_length=255, null=True)),
                ("is_sensitive", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saved_places",
                        to="journeys.serviceuser",
                    ),
                ),
            ],
            options={
                "db_table": "saved_place",
                "indexes": [models.Index(fields=["user", "deleted_at"], name="saved_place_owner_live")],
            },
        ),
        migrations.CreateModel(
            name="FavoriteJourney",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("default_constraints", models.JSONField(blank=True)),
                ("nickname", models.CharField(max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "destination_saved_place",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="favorite_destinations",
                        to="journeys.savedplace",
                    ),
                ),
                (
                    "origin_saved_place",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="favorite_origins",
                        to="journeys.savedplace",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="favorite_journeys",
                        to="journeys.serviceuser",
                    ),
                ),
            ],
            options={
                "db_table": "favorite_journey",
                "indexes": [models.Index(fields=["user", "deleted_at"], name="favorite_owner_live")],
            },
        ),
        migrations.CreateModel(
            name="RouteSearch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("origin_coordinate", journeys.models.WGS84PointField()),
                ("destination_coordinate", journeys.models.WGS84PointField()),
                ("origin_display_name", models.CharField(blank=True, max_length=255, null=True)),
                ("destination_display_name", models.CharField(blank=True, max_length=255, null=True)),
                ("departure_time", models.DateTimeField()),
                ("arrival_deadline", models.DateTimeField(blank=True, null=True)),
                ("taxi_budget_max", models.IntegerField()),
                ("strict_budget", models.BooleanField()),
                ("constraints", models.JSONField(blank=True)),
                ("status", models.CharField(max_length=32)),
                ("routing_request_id", models.CharField(max_length=128, unique=True)),
                ("contract_version", models.CharField(max_length=32)),
                ("save_to_history", models.BooleanField(default=False)),
                ("retention_until", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                (
                    "anonymous_session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="route_searches",
                        to="journeys.anonymoussession",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="route_searches",
                        to="journeys.serviceuser",
                    ),
                ),
            ],
            options={
                "db_table": "route_search",
                "indexes": [
                    models.Index(fields=["user", "created_at"], name="route_user_created"),
                    models.Index(fields=["anonymous_session", "created_at"], name="route_guest_created"),
                    models.Index(fields=["expires_at"], name="route_search_expires"),
                ],
            },
        ),
        migrations.CreateModel(
            name="RouteSearchResult",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("recommendation_type", models.CharField(max_length=32)),
                ("routing_route_id", models.CharField(max_length=128)),
                ("p50_seconds", models.IntegerField()),
                ("p90_seconds", models.IntegerField()),
                ("taxi_cost_expected", models.IntegerField()),
                ("taxi_cost_upper", models.IntegerField()),
                ("reliability_score", models.DecimalField(decimal_places=6, max_digits=7)),
                ("public_result", models.JSONField(blank=True, validators=[journeys.models.validate_public_result_snapshot])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "route_search",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="results",
                        to="journeys.routesearch",
                    ),
                ),
            ],
            options={
                "db_table": "route_search_result",
                "indexes": [models.Index(fields=["route_search", "recommendation_type"], name="result_search_type")],
            },
        ),
        migrations.CreateModel(
            name="RouteFeedback",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("selected_route_id", models.CharField(max_length=128)),
                ("actual_duration_seconds", models.IntegerField(blank=True, null=True)),
                ("actual_taxi_cost", models.IntegerField(blank=True, null=True)),
                ("arrived_on_time", models.BooleanField(blank=True, null=True)),
                ("bus_outcome", models.JSONField(blank=True, null=True)),
                ("rating", models.IntegerField(blank=True, null=True)),
                ("comment", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "route_search",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feedback",
                        to="journeys.routesearch",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="route_feedback",
                        to="journeys.serviceuser",
                    ),
                ),
            ],
            options={"db_table": "route_feedback"},
        ),
        migrations.CreateModel(
            name="ConsentRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("consent_type", models.CharField(max_length=64)),
                ("document_version", models.CharField(max_length=64)),
                ("accepted", models.BooleanField()),
                ("recorded_at", models.DateTimeField()),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="consent_records",
                        to="journeys.serviceuser",
                    ),
                ),
            ],
            options={
                "db_table": "consent_record",
                "indexes": [
                    models.Index(
                        fields=["user", "consent_type", "recorded_at"],
                        name="consent_owner_type_time",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="DataRightsJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("job_type", models.CharField(choices=[("EXPORT", "Export"), ("DELETE", "Delete")], max_length=16)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("RUNNING", "Running"),
                            ("COMPLETE", "Complete"),
                            ("FAILED", "Failed"),
                        ],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("artifact_ref", models.CharField(blank=True, max_length=512, null=True)),
                ("download_expires_at", models.DateTimeField(blank=True, null=True)),
                ("failure_code", models.CharField(blank=True, max_length=64, null=True)),
                ("requested_at", models.DateTimeField()),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="data_rights_jobs",
                        to="journeys.serviceuser",
                    ),
                ),
            ],
            options={
                "db_table": "data_rights_job",
                "indexes": [
                    models.Index(
                        fields=["user", "job_type", "requested_at"],
                        name="rights_owner_type_time",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="AccountAuditEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_type", models.CharField(max_length=64)),
                ("safe_metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_events",
                        to="journeys.serviceuser",
                    ),
                ),
            ],
            options={
                "db_table": "account_audit_event",
                "indexes": [models.Index(fields=["user", "created_at"], name="audit_owner_created")],
            },
        ),
        migrations.AddConstraint(
            model_name="serviceuser",
            constraint=models.CheckConstraint(
                condition=models.Q(("is_active", False), ("deleted_at__isnull", True), _connector="OR"),
                name="auth_user_active_not_deleted",
            ),
        ),
        migrations.AddConstraint(
            model_name="userpreference",
            constraint=models.CheckConstraint(condition=models.Q(("default_taxi_budget__gte", 0)), name="pref_budget_gte_0"),
        ),
        migrations.AddConstraint(
            model_name="userpreference",
            constraint=models.CheckConstraint(condition=models.Q(("max_walk_seconds__gte", 0)), name="pref_walk_gte_0"),
        ),
        migrations.AddConstraint(
            model_name="userpreference",
            constraint=models.CheckConstraint(condition=models.Q(("max_transfers__gte", 0)), name="pref_transfer_gte_0"),
        ),
        migrations.AddConstraint(
            model_name="userpreference",
            constraint=models.CheckConstraint(condition=models.Q(("max_taxi_legs__gte", 0)), name="pref_taxi_legs_gte_0"),
        ),
        migrations.AddConstraint(
            model_name="userpreference",
            constraint=models.CheckConstraint(condition=models.Q(("version__gte", 1)), name="pref_version_gte_1"),
        ),
        migrations.AddConstraint(
            model_name="routesearch",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("user__isnull", False), ("anonymous_session__isnull", True)),
                    models.Q(("user__isnull", True), ("anonymous_session__isnull", False)),
                    _connector="OR",
                ),
                name="route_search_one_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="routesearch",
            constraint=models.CheckConstraint(condition=models.Q(("taxi_budget_max__gte", 0)), name="route_budget_gte_0"),
        ),
        migrations.AddConstraint(
            model_name="routesearch",
            constraint=models.CheckConstraint(
                condition=models.Q(("save_to_history", False), ("user__isnull", False), _connector="OR"),
                name="route_history_user_only",
            ),
        ),
        migrations.AddConstraint(
            model_name="routesearchresult",
            constraint=models.CheckConstraint(condition=models.Q(("p50_seconds__gte", 0)), name="result_p50_gte_0"),
        ),
        migrations.AddConstraint(
            model_name="routesearchresult",
            constraint=models.CheckConstraint(
                condition=models.Q(("p90_seconds__gte", models.F("p50_seconds"))),
                name="result_p90_gte_p50",
            ),
        ),
        migrations.AddConstraint(
            model_name="routesearchresult",
            constraint=models.CheckConstraint(
                condition=models.Q(("taxi_cost_expected__gte", 0)),
                name="result_cost_expected_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="routesearchresult",
            constraint=models.CheckConstraint(
                condition=models.Q(("taxi_cost_upper__gte", 0)),
                name="result_cost_upper_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="routesearchresult",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("reliability_score__gte", Decimal("0")),
                    ("reliability_score__lte", Decimal("1")),
                ),
                name="result_reliability_0_1",
            ),
        ),
        migrations.AddConstraint(
            model_name="routefeedback",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("actual_duration_seconds__isnull", True),
                    ("actual_duration_seconds__gte", 0),
                    _connector="OR",
                ),
                name="feedback_duration_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="routefeedback",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("actual_taxi_cost__isnull", True),
                    ("actual_taxi_cost__gte", 0),
                    _connector="OR",
                ),
                name="feedback_cost_gte_0",
            ),
        ),
        migrations.AddConstraint(
            model_name="routefeedback",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("rating__isnull", True),
                    models.Q(("rating__gte", 1), ("rating__lte", 5)),
                    _connector="OR",
                ),
                name="feedback_rating_1_5",
            ),
        ),
        migrations.AddConstraint(
            model_name="datarightsjob",
            constraint=models.CheckConstraint(
                condition=models.Q(("job_type__in", ["EXPORT", "DELETE"])),
                name="rights_job_type_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="datarightsjob",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["PENDING", "RUNNING", "COMPLETE", "FAILED"])),
                name="rights_job_status_valid",
            ),
        ),
    ]
