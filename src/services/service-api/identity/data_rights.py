from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from journeys.models import AccountAuditEvent, DataRightsJob, ServiceUser


class DataRightsJobConflict(RuntimeError):
    pass


class DataRightsRepository:
    @staticmethod
    @transaction.atomic
    def create(*, user_id: UUID | str, job_type: str, requested_at=None) -> DataRightsJob:
        user = ServiceUser.objects.select_for_update().get(
            id=user_id,
            is_active=True,
            deleted_at__isnull=True,
        )
        if job_type not in DataRightsJob.JobType.values:
            raise ValueError("Unsupported data-rights job type.")
        if DataRightsJob.objects.filter(
            user=user,
            job_type=job_type,
            status__in=[DataRightsJob.Status.PENDING, DataRightsJob.Status.RUNNING],
        ).exists():
            raise DataRightsJobConflict("An active job of this type already exists.")
        job = DataRightsJob.objects.create(
            user=user,
            job_type=job_type,
            status=DataRightsJob.Status.PENDING,
            requested_at=requested_at or timezone.now(),
        )
        AccountAuditEvent.objects.create(
            user=user,
            event_type=f"DATA_{job_type}_REQUESTED",
            safe_metadata={"jobId": str(job.id)},
        )
        return job

    @staticmethod
    def get_owned(*, user_id: UUID | str, job_id: UUID | str) -> DataRightsJob:
        return DataRightsJob.objects.get(id=job_id, user_id=user_id)

    @staticmethod
    @transaction.atomic
    def mark_running(*, job_id: UUID | str, started_at=None) -> DataRightsJob:
        job = DataRightsJob.objects.select_for_update().get(
            id=job_id,
            status=DataRightsJob.Status.PENDING,
        )
        job.status = DataRightsJob.Status.RUNNING
        job.started_at = started_at or timezone.now()
        job.save(update_fields=["status", "started_at"])
        return job

    @staticmethod
    @transaction.atomic
    def complete_export(
        *,
        job_id: UUID | str,
        artifact_ref: str,
        download_expires_at,
        completed_at=None,
    ) -> DataRightsJob:
        if not artifact_ref or artifact_ref.startswith(("http://", "https://")):
            raise ValueError("artifact_ref must be an internal object reference, not a public URL.")
        job = DataRightsJob.objects.select_for_update().get(
            id=job_id,
            job_type=DataRightsJob.JobType.EXPORT,
            status=DataRightsJob.Status.RUNNING,
        )
        job.status = DataRightsJob.Status.COMPLETE
        job.artifact_ref = artifact_ref
        job.download_expires_at = download_expires_at
        job.completed_at = completed_at or timezone.now()
        job.failure_code = None
        job.save(
            update_fields=[
                "status",
                "artifact_ref",
                "download_expires_at",
                "completed_at",
                "failure_code",
            ]
        )
        AccountAuditEvent.objects.create(
            user=job.user,
            event_type="DATA_EXPORT_COMPLETED",
            safe_metadata={"jobId": str(job.id)},
        )
        return job

    @staticmethod
    @transaction.atomic
    def fail(*, job_id: UUID | str, failure_code: str, completed_at=None) -> DataRightsJob:
        job = DataRightsJob.objects.select_for_update().get(id=job_id)
        if job.status not in {DataRightsJob.Status.PENDING, DataRightsJob.Status.RUNNING}:
            raise DataRightsJobConflict("Only an active job may fail.")
        job.status = DataRightsJob.Status.FAILED
        job.failure_code = failure_code
        job.completed_at = completed_at or timezone.now()
        job.artifact_ref = None
        job.download_expires_at = None
        job.save(
            update_fields=[
                "status",
                "failure_code",
                "completed_at",
                "artifact_ref",
                "download_expires_at",
            ]
        )
        AccountAuditEvent.objects.create(
            user=job.user,
            event_type=f"DATA_{job.job_type}_FAILED",
            safe_metadata={"jobId": str(job.id), "failureCode": failure_code},
        )
        return job
