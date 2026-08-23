from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from identity.artifacts import (
    ArtifactStoreUnavailable,
    DataRightsArtifactStore,
    configured_artifact_store,
)
from identity.data_rights import DataRightsJobConflict, DataRightsRepository
from identity.lifecycle import ACCOUNT_DELETION_GRACE, export_user_data, hard_delete_user_data
from identity.lifecycle import schedule_user_deletion
from journeys.models import DataRightsJob


@dataclass(frozen=True)
class DataRightsProcessingReport:
    exports_completed: int = 0
    deletions_scheduled: int = 0
    deletions_completed: int = 0
    jobs_failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _locked_jobs(*, skip_locked: bool = True):
    queryset = DataRightsJob.objects.select_for_update()
    if skip_locked and connection.features.has_select_for_update_skip_locked:
        queryset = queryset.select_for_update(skip_locked=True)
    return queryset


def _claim_next_pending(*, now) -> DataRightsJob | None:
    with transaction.atomic():
        job = (
            _locked_jobs()
            .filter(status=DataRightsJob.Status.PENDING)
            .order_by("requested_at", "id")
            .first()
        )
        if job is None:
            return None
        return DataRightsRepository.mark_running(job_id=job.id, started_at=now)


def _fail_active_job(*, job_id: UUID, failure_code: str, now) -> None:
    try:
        DataRightsRepository.fail(job_id=job_id, failure_code=failure_code, completed_at=now)
    except (DataRightsJob.DoesNotExist, DataRightsJobConflict):
        # A competing worker may already have completed or removed the subject.
        return


def _process_export(
    *,
    job: DataRightsJob,
    now,
    artifact_store: DataRightsArtifactStore | None,
) -> bool:
    store = artifact_store
    artifact_ref: str | None = None
    try:
        if store is None:
            store = configured_artifact_store()
        payload = export_user_data(user_id=job.user_id)
        artifact_ref = store.put(job_id=job.id, payload=payload)
        DataRightsRepository.complete_export(
            job_id=job.id,
            artifact_ref=artifact_ref,
            download_expires_at=now
            + timedelta(seconds=settings.DATA_RIGHTS_EXPORT_TTL_SECONDS),
            completed_at=now,
        )
        return True
    except ArtifactStoreUnavailable:
        failure_code = "EXPORT_STORAGE_UNAVAILABLE"
    except Exception:
        failure_code = "EXPORT_PROCESSING_FAILED"

    if artifact_ref is not None and store is not None:
        try:
            store.delete(artifact_ref=artifact_ref)
        except Exception:
            pass
    _fail_active_job(job_id=job.id, failure_code=failure_code, now=now)
    return False


def _schedule_deletion(*, job: DataRightsJob, now) -> bool:
    try:
        schedule_user_deletion(user_id=job.user_id, requested_at=job.requested_at)
        return True
    except Exception:
        _fail_active_job(
            job_id=job.id,
            failure_code="DELETION_PROCESSING_FAILED",
            now=now,
        )
        return False


def _complete_one_due_deletion(
    *,
    now,
    artifact_store: DataRightsArtifactStore | None,
) -> bool | None:
    """Hard-delete one due account.

    The job remains RUNNING during the canonical grace period. Completion deletes
    the account and its owner-bound job in the same transaction; the existing
    DATA_DELETION_COMPLETED audit row survives with a null user reference.
    """

    job = (
        DataRightsJob.objects.select_related("user")
        .filter(
            job_type=DataRightsJob.JobType.DELETE,
            status=DataRightsJob.Status.RUNNING,
            user__deleted_at__isnull=False,
            user__deleted_at__lte=now - ACCOUNT_DELETION_GRACE,
        )
        .order_by("user__deleted_at", "id")
        .first()
    )
    if job is None:
        return None
    job_id = job.id
    try:
        if not hard_delete_user_data(user_id=job.user_id, artifact_store=artifact_store):
            raise RuntimeError("Deletion subject or its artifact storage was unavailable.")
        if DataRightsJob.objects.filter(id=job_id).exists():
            raise RuntimeError("Deletion job did not cascade with its subject.")
        return True
    except Exception:
        if "job_id" in locals():
            _fail_active_job(
                job_id=job_id,
                failure_code="DELETION_PROCESSING_FAILED",
                now=now,
            )
        return False


def process_data_rights_jobs(
    *,
    limit: int = 100,
    now=None,
    artifact_store: DataRightsArtifactStore | None = None,
) -> DataRightsProcessingReport:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    now = now or timezone.now()
    exports_completed = 0
    deletions_scheduled = 0
    deletions_completed = 0
    jobs_failed = 0
    processed = 0

    while processed < limit:
        completed = _complete_one_due_deletion(now=now, artifact_store=artifact_store)
        if completed is None:
            break
        processed += 1
        if completed:
            deletions_completed += 1
        else:
            jobs_failed += 1

    while processed < limit:
        job = _claim_next_pending(now=now)
        if job is None:
            break
        processed += 1
        if job.job_type == DataRightsJob.JobType.EXPORT:
            if _process_export(job=job, now=now, artifact_store=artifact_store):
                exports_completed += 1
            else:
                jobs_failed += 1
        elif _schedule_deletion(job=job, now=now):
            deletions_scheduled += 1
        else:
            jobs_failed += 1

    return DataRightsProcessingReport(
        exports_completed=exports_completed,
        deletions_scheduled=deletions_scheduled,
        deletions_completed=deletions_completed,
        jobs_failed=jobs_failed,
    )
