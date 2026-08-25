from __future__ import annotations

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from journeys.models import FavoriteJourney, SavedPlace, ServiceUser


class SavedPlaceRepository:
    @staticmethod
    def list_owned(*, user_id: UUID | str):
        return SavedPlace.objects.filter(user_id=user_id, deleted_at__isnull=True).order_by("created_at")

    @staticmethod
    def get_owned(*, user_id: UUID | str, place_id: UUID | str) -> SavedPlace:
        return SavedPlace.objects.get(id=place_id, user_id=user_id, deleted_at__isnull=True)

    @staticmethod
    def create(*, user_id: UUID | str, **values) -> SavedPlace:
        user = ServiceUser.objects.get(id=user_id, is_active=True, deleted_at__isnull=True)
        place = SavedPlace(user=user, **values)
        place.full_clean()
        place.save()
        return place

    @staticmethod
    @transaction.atomic
    def soft_delete(*, user_id: UUID | str, place_id: UUID | str) -> bool:
        now = timezone.now()
        place = (
            SavedPlace.objects.select_for_update().filter(
                id=place_id,
                user_id=user_id,
                deleted_at__isnull=True,
            ).first()
        )
        if place is None:
            return False
        place.deleted_at = now
        place.save(update_fields=["deleted_at", "updated_at"])
        FavoriteJourney.objects.filter(
            Q(origin_saved_place=place) | Q(destination_saved_place=place),
            user_id=user_id,
            deleted_at__isnull=True,
        ).update(deleted_at=now, updated_at=now)
        return True

    @staticmethod
    def update(
        *,
        user_id: UUID | str,
        place_id: UUID | str,
        changes: dict[str, object],
    ) -> SavedPlace:
        allowed = {"label", "display_name", "coordinate", "provider", "provider_place_id", "is_sensitive"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("Unsupported saved-place fields: " + ", ".join(sorted(unknown)))
        place = SavedPlaceRepository.get_owned(user_id=user_id, place_id=place_id)
        for name, value in changes.items():
            setattr(place, name, value)
        place.full_clean()
        place.save(update_fields=[*sorted(changes), "updated_at"])
        return place


class FavoriteRepository:
    @staticmethod
    def list_owned(*, user_id: UUID | str):
        return FavoriteJourney.objects.filter(
            user_id=user_id,
            deleted_at__isnull=True,
            origin_saved_place__isnull=False,
            destination_saved_place__isnull=False,
            origin_saved_place__deleted_at__isnull=True,
            destination_saved_place__deleted_at__isnull=True,
        ).order_by("created_at")

    @staticmethod
    def get_owned(*, user_id: UUID | str, favorite_id: UUID | str) -> FavoriteJourney:
        return FavoriteJourney.objects.get(
            id=favorite_id,
            user_id=user_id,
            deleted_at__isnull=True,
            origin_saved_place__isnull=False,
            destination_saved_place__isnull=False,
            origin_saved_place__deleted_at__isnull=True,
            destination_saved_place__deleted_at__isnull=True,
        )

    @staticmethod
    @transaction.atomic
    def create(
        *,
        user_id: UUID | str,
        origin_saved_place_id: UUID | str | None,
        destination_saved_place_id: UUID | str | None,
        nickname: str,
        default_constraints: dict,
    ) -> FavoriteJourney:
        user = ServiceUser.objects.get(id=user_id, is_active=True, deleted_at__isnull=True)
        if origin_saved_place_id is None or destination_saved_place_id is None:
            raise ValidationError("Favorite journey requires active origin and destination places.")
        place_ids = [origin_saved_place_id, destination_saved_place_id]
        owned = set(
            SavedPlace.objects.filter(
                user=user,
                id__in=place_ids,
                deleted_at__isnull=True,
            ).values_list("id", flat=True)
        )
        if owned != set(place_ids):
            raise ValidationError("Favorite journey may reference only active places owned by the user.")
        return FavoriteJourney.objects.create(
            user=user,
            origin_saved_place_id=origin_saved_place_id,
            destination_saved_place_id=destination_saved_place_id,
            nickname=nickname,
            default_constraints=default_constraints,
        )

    @staticmethod
    def delete(*, user_id: UUID | str, favorite_id: UUID | str) -> bool:
        now = timezone.now()
        return bool(
            FavoriteJourney.objects.filter(
                id=favorite_id,
                user_id=user_id,
                deleted_at__isnull=True,
            ).update(deleted_at=now, updated_at=now)
        )

    @staticmethod
    @transaction.atomic
    def update(
        *,
        user_id: UUID | str,
        favorite_id: UUID | str,
        changes: dict[str, object],
    ) -> FavoriteJourney:
        allowed = {
            "nickname",
            "origin_saved_place_id",
            "destination_saved_place_id",
            "default_constraints",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("Unsupported favorite fields: " + ", ".join(sorted(unknown)))
        favorite = FavoriteRepository.get_owned(user_id=user_id, favorite_id=favorite_id)
        for name, value in changes.items():
            setattr(favorite, name, value)
        if favorite.origin_saved_place_id is None or favorite.destination_saved_place_id is None:
            raise ValidationError("Favorite journey requires active origin and destination places.")
        favorite.full_clean()
        favorite.save(update_fields=[*sorted(changes), "updated_at"])
        return favorite
