from __future__ import annotations

from uuid import UUID

from django.db import transaction

from journeys.models import ServiceUser, UserProfile


class IdentityRepository:
    @staticmethod
    @transaction.atomic
    def create_user(
        *, email: str, password_hash: str | None = None, nickname: str = "82TA 사용자"
    ) -> ServiceUser:
        user = ServiceUser.objects.create(email=email.strip().casefold(), password_hash=password_hash)
        UserProfile.objects.create(user=user, nickname=nickname.strip())
        return user

    @staticmethod
    def get_active(user_id: UUID | str) -> ServiceUser:
        return ServiceUser.objects.get(id=user_id, is_active=True, deleted_at__isnull=True)

    @staticmethod
    def update_profile(
        *, user_id: UUID | str, locale: str, timezone: str
    ) -> UserProfile:
        user = IdentityRepository.get_active(user_id)
        profile, _ = UserProfile.objects.update_or_create(
            user=user,
            defaults={"locale": locale, "timezone": timezone},
        )
        return profile
