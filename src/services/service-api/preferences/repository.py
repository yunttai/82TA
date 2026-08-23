from __future__ import annotations

from uuid import UUID

from django.db import transaction

from journeys.models import ServiceUser, UserPreference


class PreferenceVersionConflict(RuntimeError):
    pass


class PreferenceRepository:
    MUTABLE_FIELDS = frozenset(
        {
            "default_taxi_budget",
            "max_walk_seconds",
            "max_transfers",
            "max_taxi_legs",
            "optimization_profile",
            "accessibility",
            "privacy",
        }
    )

    @staticmethod
    def get_or_create(*, user_id: UUID | str) -> UserPreference:
        user = ServiceUser.objects.get(id=user_id, is_active=True, deleted_at__isnull=True)
        preference, _ = UserPreference.objects.get_or_create(user=user)
        return preference

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        user_id: UUID | str,
        expected_version: int,
        changes: dict[str, object],
    ) -> UserPreference:
        unknown = set(changes) - cls.MUTABLE_FIELDS
        if unknown:
            raise ValueError("Unsupported preference fields: " + ", ".join(sorted(unknown)))
        preference = UserPreference.objects.select_for_update().get(
            user_id=user_id,
            user__is_active=True,
            user__deleted_at__isnull=True,
        )
        if preference.version != expected_version:
            raise PreferenceVersionConflict("Preference version is stale.")
        for name, value in changes.items():
            setattr(preference, name, value)
        preference.version += 1
        preference.full_clean()
        preference.save(update_fields=[*sorted(changes), "version", "updated_at"])
        return preference
