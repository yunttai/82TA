from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.test import TestCase

from favorites.repository import FavoriteRepository, SavedPlaceRepository
from identity.repository import IdentityRepository


class FavoriteOwnershipTests(TestCase):
    def setUp(self) -> None:
        self.owner = IdentityRepository.create_user(email="owner@example.com")
        self.other = IdentityRepository.create_user(email="other@example.com")
        self.place = SavedPlaceRepository.create(
            user_id=self.owner.id,
            label="집",
            display_name="주소",
            coordinate={"lon": 127.1, "lat": 37.2},
        )

    def test_owner_can_create_and_list_favorite(self) -> None:
        favorite = FavoriteRepository.create(
            user_id=self.owner.id,
            origin_saved_place_id=self.place.id,
            destination_saved_place_id=self.place.id,
            nickname="통근",
            default_constraints={},
        )
        self.assertEqual(list(FavoriteRepository.list_owned(user_id=self.owner.id)), [favorite])
        self.assertEqual(list(FavoriteRepository.list_owned(user_id=self.other.id)), [])

    def test_cross_owner_saved_place_reference_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            FavoriteRepository.create(
                user_id=self.other.id,
                origin_saved_place_id=self.place.id,
                destination_saved_place_id=None,
                nickname="침범",
                default_constraints={},
            )

    def test_cross_owner_read_and_delete_fail_closed(self) -> None:
        favorite = FavoriteRepository.create(
            user_id=self.owner.id,
            origin_saved_place_id=self.place.id,
            destination_saved_place_id=None,
            nickname="통근",
            default_constraints={},
        )
        with self.assertRaises(ObjectDoesNotExist):
            FavoriteRepository.get_owned(user_id=self.other.id, favorite_id=favorite.id)
        self.assertFalse(FavoriteRepository.delete(user_id=self.other.id, favorite_id=favorite.id))
        self.assertTrue(FavoriteRepository.delete(user_id=self.owner.id, favorite_id=favorite.id))

    def test_soft_deleted_place_is_not_visible_or_reusable(self) -> None:
        self.assertTrue(SavedPlaceRepository.soft_delete(user_id=self.owner.id, place_id=self.place.id))
        self.assertEqual(list(SavedPlaceRepository.list_owned(user_id=self.owner.id)), [])
        with self.assertRaises(ValidationError):
            FavoriteRepository.create(
                user_id=self.owner.id,
                origin_saved_place_id=self.place.id,
                destination_saved_place_id=None,
                nickname="삭제 장소",
                default_constraints={},
            )
