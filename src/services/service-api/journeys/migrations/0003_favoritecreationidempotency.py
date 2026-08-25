import datetime
import uuid

import django.db.models.deletion
import django.db.models.expressions
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("journeys", "0002_userprofile_nickname")]

    operations = [
        migrations.CreateModel(
            name="FavoriteCreationIdempotency",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("key_digest", models.CharField(max_length=64)),
                ("request_fingerprint", models.CharField(max_length=64)),
                ("digest_key_version", models.PositiveIntegerField()),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("expires_at", models.DateTimeField()),
                (
                    "destination_saved_place",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="favorite_destination_creation_receipts",
                        to="journeys.savedplace",
                    ),
                ),
                (
                    "favorite_journey",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="creation_receipts",
                        to="journeys.favoritejourney",
                    ),
                ),
                (
                    "origin_saved_place",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="favorite_origin_creation_receipts",
                        to="journeys.savedplace",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="favorite_creation_receipts",
                        to="journeys.serviceuser",
                    ),
                ),
            ],
            options={
                "db_table": "favorite_creation_idempotency",
                "indexes": [
                    models.Index(
                        fields=["expires_at"],
                        name="ix_fav_create_idemp_expiry",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "key_digest"),
                        name="uq_favorite_create_owner_key_digest",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("origin_saved_place", models.F("destination_saved_place")),
                            _negated=True,
                        ),
                        name="ck_favorite_create_distinct_places",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("digest_key_version__gt", 0)),
                        name="ck_favorite_create_digest_key_version",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "expires_at",
                                django.db.models.expressions.CombinedExpression(
                                    models.F("created_at"),
                                    "+",
                                    models.Value(datetime.timedelta(days=1)),
                                ),
                            )
                        ),
                        name="ck_favorite_create_24h_expiry",
                    ),
                ],
            },
        )
    ]
