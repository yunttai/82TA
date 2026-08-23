from django.core.exceptions import ValidationError
from django.test import TestCase

from identity.repository import IdentityRepository
from preferences.repository import PreferenceRepository, PreferenceVersionConflict


class PreferenceRepositoryTests(TestCase):
    def setUp(self) -> None:
        self.user = IdentityRepository.create_user(email="preferences@example.com")
        self.preference = PreferenceRepository.get_or_create(user_id=self.user.id)

    def test_optimistic_version_update(self) -> None:
        updated = PreferenceRepository.update(
            user_id=self.user.id,
            expected_version=1,
            changes={"default_taxi_budget": 20_000, "max_walk_seconds": 600},
        )
        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.default_taxi_budget, 20_000)
        with self.assertRaises(PreferenceVersionConflict):
            PreferenceRepository.update(
                user_id=self.user.id,
                expected_version=1,
                changes={"default_taxi_budget": 0},
            )

    def test_invalid_negative_value_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            PreferenceRepository.update(
                user_id=self.user.id,
                expected_version=1,
                changes={"max_walk_seconds": -1},
            )

    def test_unknown_field_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PreferenceRepository.update(
                user_id=self.user.id,
                expected_version=1,
                changes={"routing_rank_override": True},
            )
