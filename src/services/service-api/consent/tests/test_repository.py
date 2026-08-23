from django.test import TestCase
from django.utils import timezone

from consent.repository import ConsentRepository
from identity.repository import IdentityRepository


class ConsentRepositoryTests(TestCase):
    def test_consent_history_is_append_only_and_latest_is_explicit(self) -> None:
        user = IdentityRepository.create_user(email="consent@example.com")
        recorded_at = timezone.now()
        accepted = ConsentRepository.record(
            user_id=user.id,
            consent_type="LOCATION",
            document_version="1",
            accepted=True,
            recorded_at=recorded_at,
        )
        withdrawn = ConsentRepository.record(
            user_id=user.id,
            consent_type="LOCATION",
            document_version="1",
            accepted=False,
            recorded_at=recorded_at,
        )
        self.assertEqual(user.consent_records.count(), 2)
        self.assertEqual(
            ConsentRepository.latest(user_id=user.id, consent_type="LOCATION"),
            withdrawn,
        )
        self.assertNotEqual(accepted.id, withdrawn.id)
        self.assertGreater(withdrawn.recorded_at, accepted.recorded_at)
