from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from journeys.models import AnonymousSession, AuthenticatedSession, ServiceUser


class SessionRepository:
    @staticmethod
    def create_guest(*, token_hash: str, expires_at) -> AnonymousSession:
        return AnonymousSession.objects.create(token_hash=token_hash, expires_at=expires_at)

    @staticmethod
    def resolve_guest(*, token_hash: str, now=None) -> AnonymousSession:
        now = now or timezone.now()
        return AnonymousSession.objects.get(
            token_hash=token_hash,
            expires_at__gt=now,
            revoked_at__isnull=True,
        )

    @staticmethod
    def create_authenticated(
        *, user_id: UUID | str, token_hash: str, expires_at
    ) -> AuthenticatedSession:
        user = ServiceUser.objects.get(id=user_id, is_active=True, deleted_at__isnull=True)
        return AuthenticatedSession.objects.create(
            user=user,
            token_hash=token_hash,
            expires_at=expires_at,
        )

    @staticmethod
    @transaction.atomic
    def resolve_authenticated(*, token_hash: str, now=None) -> AuthenticatedSession:
        now = now or timezone.now()
        session = AuthenticatedSession.objects.select_for_update().get(
            token_hash=token_hash,
            expires_at__gt=now,
            revoked_at__isnull=True,
            user__is_active=True,
            user__deleted_at__isnull=True,
        )
        session.last_seen_at = now
        session.save(update_fields=["last_seen_at"])
        return session

    @staticmethod
    def revoke_guest(*, session_id: UUID | str, now=None) -> bool:
        return bool(
            AnonymousSession.objects.filter(id=session_id, revoked_at__isnull=True).update(
                revoked_at=now or timezone.now()
            )
        )

    @staticmethod
    def revoke_authenticated(
        *, user_id: UUID | str, session_id: UUID | str, now=None
    ) -> bool:
        return bool(
            AuthenticatedSession.objects.filter(
                id=session_id,
                user_id=user_id,
                revoked_at__isnull=True,
            ).update(revoked_at=now or timezone.now())
        )
