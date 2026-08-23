from __future__ import annotations

from uuid import UUID

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
        user = ServiceUser.objects.get(id=user_id, is_active=True, deleted_at__isnull=True)
        return ConsentRecord.objects.create(
            user=user,
            consent_type=consent_type,
            document_version=document_version,
            accepted=accepted,
            recorded_at=recorded_at or timezone.now(),
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
