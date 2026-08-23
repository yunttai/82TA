from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from journeys.models import ConsentRecord, ServiceUser


class ConsentRepository:
    @staticmethod
    def record(
        *,
        user_id: UUID | str,
        consent_type: str,
        document_version: str,
        accepted: bool,
        recorded_at=None,
    ) -> ConsentRecord:
        with transaction.atomic():
            user = ServiceUser.objects.select_for_update().get(
                id=user_id,
                is_active=True,
                deleted_at__isnull=True,
            )
            effective_at = recorded_at if recorded_at is not None else timezone.now()
            previous_at = (
                ConsentRecord.objects.filter(
                    user=user,
                    consent_type=consent_type,
                )
                .order_by("-recorded_at")
                .values_list("recorded_at", flat=True)
                .first()
            )
            if previous_at is not None and effective_at <= previous_at:
                effective_at = previous_at + timedelta(microseconds=1)
            return ConsentRecord.objects.create(
                user=user,
                consent_type=consent_type,
                document_version=document_version,
                accepted=accepted,
                recorded_at=effective_at,
            )

    @staticmethod
    def latest(*, user_id: UUID | str, consent_type: str) -> ConsentRecord | None:
        return (
            ConsentRecord.objects.filter(user_id=user_id, consent_type=consent_type)
            .order_by("-recorded_at", "-id")
            .first()
        )

    @staticmethod
    def latest_by_type(*, user_id: UUID | str) -> list[ConsentRecord]:
        latest: dict[str, ConsentRecord] = {}
        for record in ConsentRecord.objects.filter(user_id=user_id).order_by(
            "consent_type", "-recorded_at", "-id"
        ):
            latest.setdefault(record.consent_type, record)
        return list(latest.values())
