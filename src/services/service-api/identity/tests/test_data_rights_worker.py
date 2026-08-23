from __future__ import annotations

import json
import stat
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from identity.artifacts import ArtifactIntegrityError, EncryptedFilesystemArtifactStore
from identity.data_rights import DataRightsRepository
from identity.data_rights_worker import process_data_rights_jobs
from identity.lifecycle import purge_service_data
from identity.repository import IdentityRepository
from journeys.models import AccountAuditEvent, DataRightsJob, ServiceUser


class FailingArtifactStore:
    def put(self, **kwargs):
        raise RuntimeError("simulated private store failure")

    def delete(self, **kwargs):
        return None


class FailingDeleteArtifactStore:
    def put(self, **kwargs):
        return "unused"

    def delete(self, **kwargs):
        raise RuntimeError("simulated artifact delete failure")


class DataRightsWorkerTests(TestCase):
    def setUp(self) -> None:
        self.user = IdentityRepository.create_user(email="portable@example.com")
        self.now = timezone.now()

    def _encrypted_store(self, directory: str):
        return EncryptedFilesystemArtifactStore(
            directory=directory,
            encryption_key=Fernet.generate_key().decode("ascii"),
        )

    def test_export_is_encrypted_private_and_completed_with_internal_reference(self) -> None:
        job = DataRightsRepository.create(
            user_id=self.user.id,
            job_type=DataRightsJob.JobType.EXPORT,
            requested_at=self.now,
        )
        with tempfile.TemporaryDirectory() as directory:
            store = self._encrypted_store(directory)
            report = process_data_rights_jobs(
                limit=1,
                now=self.now,
                artifact_store=store,
            )
            job.refresh_from_db()
            artifact_path = Path(directory) / job.artifact_ref.removeprefix("fernet-file:")

            self.assertEqual(report.exports_completed, 1)
            self.assertEqual(job.status, DataRightsJob.Status.COMPLETE)
            self.assertTrue(job.artifact_ref.startswith("fernet-file:"))
            self.assertNotIn(b"portable@example.com", artifact_path.read_bytes())
            self.assertEqual(stat.S_IMODE(artifact_path.stat().st_mode), 0o600)
            self.assertEqual(store.read(artifact_ref=job.artifact_ref)["account"]["email"], self.user.email)
            self.assertEqual(
                job.download_expires_at,
                self.now + timedelta(seconds=900),
            )

    @override_settings(DATA_RIGHTS_ARTIFACT_BACKEND="disabled")
    def test_disabled_export_storage_fails_closed_without_public_reference(self) -> None:
        job = DataRightsRepository.create(
            user_id=self.user.id,
            job_type=DataRightsJob.JobType.EXPORT,
            requested_at=self.now,
        )
        report = process_data_rights_jobs(limit=1, now=self.now)
        job.refresh_from_db()

        self.assertEqual(report.jobs_failed, 1)
        self.assertEqual(job.status, DataRightsJob.Status.FAILED)
        self.assertEqual(job.failure_code, "EXPORT_STORAGE_UNAVAILABLE")
        self.assertIsNone(job.artifact_ref)

    def test_export_failure_is_safe_and_audited_without_exception_details(self) -> None:
        job = DataRightsRepository.create(
            user_id=self.user.id,
            job_type=DataRightsJob.JobType.EXPORT,
            requested_at=self.now,
        )
        report = process_data_rights_jobs(
            limit=1,
            now=self.now,
            artifact_store=FailingArtifactStore(),
        )
        job.refresh_from_db()
        audit = AccountAuditEvent.objects.get(event_type="DATA_EXPORT_FAILED")

        self.assertEqual(report.jobs_failed, 1)
        self.assertEqual(job.failure_code, "EXPORT_PROCESSING_FAILED")
        self.assertNotIn("simulated", json.dumps(audit.safe_metadata))

    def test_deletion_runs_through_grace_then_removes_subject_and_owner_job(self) -> None:
        job = DataRightsRepository.create(
            user_id=self.user.id,
            job_type=DataRightsJob.JobType.DELETE,
            requested_at=self.now,
        )
        scheduled = process_data_rights_jobs(limit=1, now=self.now)
        job.refresh_from_db()
        self.user.refresh_from_db()

        self.assertEqual(scheduled.deletions_scheduled, 1)
        self.assertEqual(job.status, DataRightsJob.Status.RUNNING)
        self.assertFalse(self.user.is_active)
        self.assertEqual(self.user.deleted_at, self.now)

        completed = process_data_rights_jobs(
            limit=1,
            now=self.now + timedelta(days=31),
        )
        completion_audit = AccountAuditEvent.objects.get(event_type="DATA_DELETION_COMPLETED")

        self.assertEqual(completed.deletions_completed, 1)
        self.assertFalse(ServiceUser.objects.filter(id=self.user.id).exists())
        self.assertFalse(DataRightsJob.objects.filter(id=job.id).exists())
        self.assertIsNone(completion_audit.user_id)

    def test_account_deletion_removes_existing_export_artifact_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._encrypted_store(directory)
            export_job = DataRightsRepository.create(
                user_id=self.user.id,
                job_type=DataRightsJob.JobType.EXPORT,
                requested_at=self.now,
            )
            DataRightsRepository.mark_running(job_id=export_job.id, started_at=self.now)
            artifact_ref = store.put(job_id=export_job.id, payload={"precise": [127.1, 37.4]})
            artifact_path = Path(directory) / artifact_ref.removeprefix("fernet-file:")
            DataRightsRepository.complete_export(
                job_id=export_job.id,
                artifact_ref=artifact_ref,
                download_expires_at=self.now + timedelta(days=60),
                completed_at=self.now,
            )
            deletion_job = DataRightsRepository.create(
                user_id=self.user.id,
                job_type=DataRightsJob.JobType.DELETE,
                requested_at=self.now,
            )

            process_data_rights_jobs(limit=1, now=self.now, artifact_store=store)
            completed = process_data_rights_jobs(
                limit=1,
                now=self.now + timedelta(days=31),
                artifact_store=store,
            )

            self.assertEqual(completed.deletions_completed, 1)
            self.assertFalse(artifact_path.exists())
            self.assertFalse(DataRightsJob.objects.filter(id=deletion_job.id).exists())

    def test_expiry_retains_reference_and_audits_when_physical_delete_fails(self) -> None:
        job = DataRightsRepository.create(
            user_id=self.user.id,
            job_type=DataRightsJob.JobType.EXPORT,
            requested_at=self.now,
        )
        DataRightsRepository.mark_running(job_id=job.id, started_at=self.now)
        DataRightsRepository.complete_export(
            job_id=job.id,
            artifact_ref="fernet-file:00000000-0000-4000-8000-000000000001.json.fernet",
            download_expires_at=self.now,
            completed_at=self.now,
        )

        report = purge_service_data(
            now=self.now,
            artifact_store=FailingDeleteArtifactStore(),
        )
        job.refresh_from_db()
        failure_audit = AccountAuditEvent.objects.get(
            event_type="DATA_EXPORT_ARTIFACT_PURGE_FAILED"
        )

        self.assertEqual(report.expired_export_artifacts, 0)
        self.assertIsNotNone(job.artifact_ref)
        self.assertEqual(failure_audit.safe_metadata["failureCode"], "ARTIFACT_STORE_UNAVAILABLE")

    def test_artifact_reference_cannot_escape_private_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._encrypted_store(directory)
            with self.assertRaises(ArtifactIntegrityError):
                store.read(artifact_ref="fernet-file:../../account.json")

    def test_management_command_processes_a_bounded_batch(self) -> None:
        DataRightsRepository.create(
            user_id=self.user.id,
            job_type=DataRightsJob.JobType.EXPORT,
            requested_at=self.now,
        )
        with tempfile.TemporaryDirectory() as directory:
            key = Fernet.generate_key().decode("ascii")
            output = StringIO()
            with override_settings(
                DATA_RIGHTS_ARTIFACT_BACKEND="encrypted-filesystem",
                DATA_RIGHTS_ARTIFACT_DIRECTORY=directory,
                DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY=key,
            ):
                call_command("process_data_rights_jobs", limit=1, stdout=output)

        self.assertEqual(json.loads(output.getvalue())["exports_completed"], 1)
