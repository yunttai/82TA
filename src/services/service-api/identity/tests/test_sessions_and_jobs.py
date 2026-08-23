import tempfile
from datetime import timedelta

from cryptography.fernet import Fernet
from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase
from django.utils import timezone

from identity.artifacts import EncryptedFilesystemArtifactStore
from identity.data_rights import DataRightsJobConflict, DataRightsRepository
from identity.lifecycle import purge_service_data
from identity.repository import IdentityRepository
from identity.sessions import SessionRepository
from journeys.models import DataRightsJob


class SessionRepositoryTests(TestCase):
    def setUp(self) -> None:
        self.user = IdentityRepository.create_user(email="session@example.com")

    def test_guest_and_authenticated_sessions_store_only_hashes_and_revoke(self) -> None:
        now = timezone.now()
        guest = SessionRepository.create_guest(
            token_hash="guest-sha256-hash",
            expires_at=now + timedelta(hours=1),
        )
        authenticated = SessionRepository.create_authenticated(
            user_id=self.user.id,
            token_hash="auth-sha256-hash",
            expires_at=now + timedelta(hours=1),
        )
        self.assertEqual(SessionRepository.resolve_guest(token_hash="guest-sha256-hash"), guest)
        self.assertEqual(
            SessionRepository.resolve_authenticated(
                token_hash="auth-sha256-hash",
                now=now,
            ),
            authenticated,
        )
        self.assertTrue(SessionRepository.revoke_guest(session_id=guest.id, now=now))
        self.assertTrue(
            SessionRepository.revoke_authenticated(
                user_id=self.user.id,
                session_id=authenticated.id,
                now=now,
            )
        )
        with self.assertRaises(ObjectDoesNotExist):
            SessionRepository.resolve_guest(token_hash="guest-sha256-hash", now=now)
        report = purge_service_data(now=now)
        self.assertEqual(report.expired_anonymous_sessions, 1)
        self.assertEqual(report.expired_authenticated_sessions, 1)


class DataRightsRepositoryTests(TestCase):
    def setUp(self) -> None:
        self.user = IdentityRepository.create_user(email="rights@example.com")
        self.other = IdentityRepository.create_user(email="other-rights@example.com")

    def test_export_job_state_machine_and_artifact_expiry(self) -> None:
        now = timezone.now()
        job = DataRightsRepository.create(
            user_id=self.user.id,
            job_type=DataRightsJob.JobType.EXPORT,
            requested_at=now,
        )
        with self.assertRaises(DataRightsJobConflict):
            DataRightsRepository.create(
                user_id=self.user.id,
                job_type=DataRightsJob.JobType.EXPORT,
                requested_at=now,
            )
        DataRightsRepository.mark_running(job_id=job.id, started_at=now)
        with tempfile.TemporaryDirectory() as directory:
            store = EncryptedFilesystemArtifactStore(
                directory=directory,
                encryption_key=Fernet.generate_key().decode("ascii"),
            )
            artifact_ref = store.put(
                job_id=job.id,
                payload={"account": {"id": str(self.user.id)}},
            )
            artifact_path = store._directory / artifact_ref.removeprefix("fernet-file:")
            self.assertTrue(artifact_path.exists())
            DataRightsRepository.complete_export(
                job_id=job.id,
                artifact_ref=artifact_ref,
                download_expires_at=now + timedelta(minutes=5),
                completed_at=now,
            )
            job.refresh_from_db()
            self.assertEqual(job.status, DataRightsJob.Status.COMPLETE)
            self.assertEqual(job.artifact_ref, artifact_ref)
            report = purge_service_data(
                now=now + timedelta(minutes=5),
                artifact_store=store,
            )
            job.refresh_from_db()
            self.assertEqual(report.expired_export_artifacts, 1)
            self.assertIsNone(job.artifact_ref)
            self.assertIsNone(job.download_expires_at)
            self.assertFalse(artifact_path.exists())

    def test_job_lookup_is_owner_bound_and_public_urls_are_not_artifact_refs(self) -> None:
        now = timezone.now()
        job = DataRightsRepository.create(
            user_id=self.user.id,
            job_type=DataRightsJob.JobType.EXPORT,
            requested_at=now,
        )
        DataRightsRepository.mark_running(job_id=job.id, started_at=now)
        with self.assertRaises(ValueError):
            DataRightsRepository.complete_export(
                job_id=job.id,
                artifact_ref="https://objects.example/export.zip",
                download_expires_at=now + timedelta(minutes=5),
            )
        with self.assertRaises(ObjectDoesNotExist):
            DataRightsRepository.get_owned(user_id=self.other.id, job_id=job.id)
