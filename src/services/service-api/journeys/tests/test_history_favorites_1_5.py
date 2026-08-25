from __future__ import annotations

import copy
import json
import sys
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone
from django.views.debug import ExceptionReporter

from consent.repository import ConsentRepository
from identity.repository import IdentityRepository
from identity.sessions import SessionRepository
from journeys import account_views, views
from journeys.abuse import rate_limit_cache, reset_rate_limits
from journeys.api_common import token_digest
from journeys.contracts import CanonicalContracts, LockedFixtures
from journeys.favorite_payload import idempotency_key_digest, request_fingerprint
from journeys.models import (
    FavoriteCreationIdempotency,
    FavoriteJourney,
    RouteSearch,
    SavedPlace,
    ServiceUser,
)


class HistoryAndFavoritePublic15Tests(TestCase):
    def setUp(self) -> None:
        views._fixtures = None
        views._gateway = None
        views._idempotency.clear()
        reset_rate_limits()
        self.client = Client()
        self.user = IdentityRepository.create_user(email="favorite-owner@example.com")
        self.contracts = CanonicalContracts()
        self.login(self.client, self.user)

    @staticmethod
    def login(client: Client, user) -> Client:
        session = client.session
        session["service_user_id"] = str(user.id)
        session.save()
        authenticated = SessionRepository.create_authenticated(
            user_id=user.id,
            token_hash=token_digest(session.session_key),
            expires_at=timezone.now() + timedelta(seconds=settings.AUTH_SESSION_TTL_SECONDS),
        )
        session["service_authenticated_session_id"] = str(authenticated.id)
        session.save()
        return client

    def accept(self, consent_type: str) -> None:
        ConsentRepository.record(
            user_id=self.user.id,
            consent_type=consent_type,
            document_version=settings.CONSENT_DOCUMENT_VERSIONS[consent_type],
            accepted=True,
        )

    @staticmethod
    def conditions() -> dict:
        return {
            "schemaVersion": 1,
            "departurePolicy": "DEPART_AT_CLICK",
            "taxiBudget": {"currency": "KRW", "maxAmount": 7000, "strict": True},
            "preferences": {
                "maxWalkSeconds": 7200,
                "maxTransfers": 8,
                "maxTaxiLegs": 3,
                "allowTaxiBridge": True,
                "avoidHighBusSeatRisk": False,
                "allowedModes": ["WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"],
                "optimization": "BALANCED",
                "accessibility": {
                    "wheelchair": False,
                    "avoidStairs": False,
                },
            },
            "requestedRecommendations": [
                "FASTEST",
                "STABLE",
                "EFFICIENT",
                "PUBLIC_TRANSIT_ONLY",
            ],
        }

    @staticmethod
    def place(label: str, display_name: str, lon: float) -> dict:
        return {
            "label": label,
            "place": {
                "displayName": display_name,
                "coordinate": {"lon": lon, "lat": 37.4},
                "provider": "KAKAO_LOCAL",
                "providerPlaceId": f"provider-{label}",
                "regionCode": None,
            },
            "isSensitive": True,
        }

    def from_places_payload(self) -> dict:
        return {
            "nickname": "매일 출근",
            "originPlace": self.place("집", "광교중앙역", 127.05),
            "destinationPlace": self.place("회사", "세종대학교", 127.08),
            "searchConditions": self.conditions(),
        }

    def test_coordinate_persistence_requires_current_precise_location_consent(self) -> None:
        direct = self.client.post(
            "/api/v1/me/saved-places",
            data=json.dumps(self.place("집", "광교중앙역", 127.05)),
            content_type="application/json",
        )
        atomic = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(self.from_places_payload()),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-consent-0001",
        )

        self.assertEqual(direct.status_code, 403)
        self.assertEqual(atomic.status_code, 403)
        self.assertEqual(direct.json()["code"], "CONSENT_REQUIRED")
        self.assertEqual(atomic.json()["code"], "CONSENT_REQUIRED")
        self.assertEqual(SavedPlace.objects.count(), 0)
        self.assertEqual(FavoriteJourney.objects.count(), 0)

        place = SavedPlace.objects.create(
            user=self.user,
            label="기존",
            display_name="기존 위치",
            coordinate={"lon": 127.0, "lat": 37.0},
        )
        renamed = self.client.patch(
            f"/api/v1/me/saved-places/{place.id}",
            data=json.dumps({"label": "새 이름"}),
            content_type="application/json",
        )
        moved = self.client.patch(
            f"/api/v1/me/saved-places/{place.id}",
            data=json.dumps({"place": self.place("무시", "새 위치", 127.1)["place"]}),
            content_type="application/json",
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(moved.status_code, 403)

    def test_saved_place_mutations_lock_owner_before_place(self) -> None:
        self.accept("PRECISE_LOCATION")
        place = SavedPlace.objects.create(
            user=self.user,
            label="집",
            display_name="기존 위치",
            coordinate={"lon": 127.0, "lat": 37.0},
        )
        events: list[str] = []
        user_select_for_update = ServiceUser.objects.select_for_update
        place_select_for_update = SavedPlace.objects.select_for_update

        def lock_user(*args, **kwargs):
            events.append("user")
            return user_select_for_update(*args, **kwargs)

        def lock_place(*args, **kwargs):
            events.append("place")
            return place_select_for_update(*args, **kwargs)

        with (
            patch.object(ServiceUser.objects, "select_for_update", side_effect=lock_user),
            patch.object(SavedPlace.objects, "select_for_update", side_effect=lock_place),
        ):
            updated = self.client.patch(
                f"/api/v1/me/saved-places/{place.id}",
                data=json.dumps({"place": self.place("집", "새 위치", 127.1)["place"]}),
                content_type="application/json",
            )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(events, ["user", "place"])

    def test_atomic_favorite_creation_is_typed_owner_scoped_and_idempotent(self) -> None:
        self.accept("PRECISE_LOCATION")
        payload = self.from_places_payload()
        first = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-create-0001",
        )
        replay = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-create-0001",
        )
        changed = copy.deepcopy(payload)
        changed["nickname"] = "다른 이름"
        conflict = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(changed),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-create-0001",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(first["Cache-Control"], "no-store")
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(SavedPlace.objects.count(), 2)
        self.assertEqual(FavoriteJourney.objects.count(), 1)
        self.assertEqual(
            self.contracts.validate("public", "FavoriteJourneyFromPlacesResult", first.json()),
            [],
        )
        self.assertEqual(first.json()["favoriteJourneyId"], str(FavoriteJourney.objects.get().id))
        self.assertIn("createdAt", first.json())
        self.assertIn("idempotencyExpiresAt", first.json())
        self.assertEqual(FavoriteCreationIdempotency.objects.count(), 1)
        favorite = FavoriteJourney.objects.get()
        self.assertEqual(favorite.default_constraints, payload["searchConditions"])
        encoded_storage = json.dumps(favorite.default_constraints, ensure_ascii=False)
        self.assertNotIn("favorite-create-0001", encoded_storage)
        self.assertNotIn("creationIdempotency", encoded_storage)

        other = IdentityRepository.create_user(email="favorite-other@example.com")
        other_client = self.login(Client(), other)
        ConsentRepository.record(
            user_id=other.id,
            consent_type="PRECISE_LOCATION",
            document_version=settings.CONSENT_DOCUMENT_VERSIONS["PRECISE_LOCATION"],
            accepted=True,
        )
        other_result = other_client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-create-0001",
            REMOTE_ADDR="198.51.100.42",
        )
        self.assertEqual(other_result.status_code, 201)
        self.assertNotEqual(
            other_result.json()["favoriteJourneyId"],
            first.json()["favoriteJourneyId"],
        )

    def test_durable_replay_precedes_redis_quota_and_current_consent(self) -> None:
        self.accept("PRECISE_LOCATION")
        payload = self.from_places_payload()
        first = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-durable-0001",
        )
        ConsentRepository.record(
            user_id=self.user.id,
            consent_type="PRECISE_LOCATION",
            document_version=settings.CONSENT_DOCUMENT_VERSIONS["PRECISE_LOCATION"],
            accepted=False,
        )

        with patch.object(
            account_views,
            "_enforce_favorite_write_rate_limit",
            side_effect=AssertionError("replay must not touch Redis-backed quota"),
        ):
            replay = self.client.post(
                "/api/v1/me/favorite-journeys/from-places",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="favorite-durable-0001",
            )
            new_claim = self.client.post(
                "/api/v1/me/favorite-journeys/from-places",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="favorite-durable-0002",
            )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(new_claim.status_code, 403)
        self.assertEqual(new_claim.json()["code"], "CONSENT_REQUIRED")
        self.assertEqual(SavedPlace.objects.count(), 2)
        self.assertEqual(FavoriteJourney.objects.count(), 1)
        self.assertEqual(FavoriteCreationIdempotency.objects.count(), 1)

    def test_fingerprint_canonicalizes_json_order_and_saved_place_default(self) -> None:
        self.accept("PRECISE_LOCATION")
        payload = self.from_places_payload()
        payload["originPlace"].pop("isSensitive")
        payload["destinationPlace"].pop("isSensitive")
        first = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-canonical-0001",
        )
        equivalent = copy.deepcopy(payload)
        equivalent["originPlace"]["isSensitive"] = True
        equivalent["destinationPlace"]["isSensitive"] = True
        equivalent = dict(reversed(list(equivalent.items())))
        replay = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(equivalent),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-canonical-0001",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(FavoriteCreationIdempotency.objects.count(), 1)

    def test_soft_deleted_receipt_replays_without_resurrecting_resources(self) -> None:
        self.accept("PRECISE_LOCATION")
        payload = self.from_places_payload()
        first = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-soft-delete-0001",
        )
        origin_id = first.json()["originSavedPlaceId"]
        deleted = self.client.delete(f"/api/v1/me/saved-places/{origin_id}")
        replay = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-soft-delete-0001",
        )

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), first.json())
        self.assertIsNotNone(SavedPlace.objects.get(id=origin_id).deleted_at)
        self.assertIsNotNone(
            FavoriteJourney.objects.get(id=first.json()["favoriteJourneyId"]).deleted_at
        )
        self.assertEqual(self.client.get("/api/v1/me/favorite-journeys").json(), [])

    def test_expired_key_can_create_a_new_immutable_receipt(self) -> None:
        self.accept("PRECISE_LOCATION")
        payload = self.from_places_payload()
        first = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-expiry-0001",
        )
        old_created_at = timezone.now() - timedelta(hours=25)
        FavoriteCreationIdempotency.objects.update(
            created_at=old_created_at,
            expires_at=old_created_at + timedelta(hours=24),
        )
        reused = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-expiry-0001",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(reused.status_code, 201)
        self.assertNotEqual(reused.json()["favoriteJourneyId"], first.json()["favoriteJourneyId"])
        self.assertNotEqual(reused.json()["originSavedPlaceId"], first.json()["originSavedPlaceId"])
        self.assertEqual(SavedPlace.objects.count(), 4)
        self.assertEqual(FavoriteJourney.objects.count(), 2)
        self.assertEqual(FavoriteCreationIdempotency.objects.count(), 1)

    def test_receipt_and_response_do_not_expose_key_payload_or_coordinates(self) -> None:
        self.accept("PRECISE_LOCATION")
        raw_key = "favorite-never-persist-this-0001"
        payload = self.from_places_payload()
        result = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=raw_key,
        )
        ledger = FavoriteCreationIdempotency.objects.get()
        stored = " ".join(
            str(getattr(ledger, field.name))
            for field in FavoriteCreationIdempotency._meta.concrete_fields
        )
        encoded_response = json.dumps(result.json(), ensure_ascii=False)

        self.assertEqual(result.status_code, 201)
        self.assertNotIn(raw_key, stored)
        self.assertNotIn(payload["originPlace"]["place"]["displayName"], stored)
        self.assertNotIn(str(payload["originPlace"]["place"]["coordinate"]["lon"]), stored)
        self.assertNotIn("coordinate", encoded_response)
        self.assertNotIn("keyDigest", encoded_response)
        self.assertNotIn("requestFingerprint", encoded_response)

    def test_legacy_favorites_fail_closed_until_typed_conditions_are_saved(self) -> None:
        origin = SavedPlace.objects.create(
            user=self.user,
            label="집",
            display_name="광교",
            coordinate={"lon": 127.05, "lat": 37.4},
        )
        destination = SavedPlace.objects.create(
            user=self.user,
            label="회사",
            display_name="서울",
            coordinate={"lon": 127.08, "lat": 37.5},
        )
        legacy = FavoriteJourney.objects.create(
            user=self.user,
            origin_saved_place=origin,
            destination_saved_place=destination,
            nickname="예전 즐겨찾기",
            default_constraints={"maxWalkSeconds": 900},
        )

        listed = self.client.get("/api/v1/me/favorite-journeys")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["defaultConstraints"], {"maxWalkSeconds": 900})
        self.assertIsNone(listed.json()[0]["searchConditions"])

        updated = self.client.patch(
            f"/api/v1/me/favorite-journeys/{legacy.id}",
            data=json.dumps({"searchConditions": self.conditions()}),
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["defaultConstraints"], {})
        self.assertEqual(updated.json()["searchConditions"], self.conditions())
        legacy.refresh_from_db()
        self.assertEqual(legacy.default_constraints, self.conditions())

    def test_deleted_or_null_place_references_never_serialize(self) -> None:
        origin = SavedPlace.objects.create(
            user=self.user,
            label="집",
            display_name="광교",
            coordinate={"lon": 127.05, "lat": 37.4},
        )
        destination = SavedPlace.objects.create(
            user=self.user,
            label="회사",
            display_name="서울",
            coordinate={"lon": 127.08, "lat": 37.5},
        )
        favorite = FavoriteJourney.objects.create(
            user=self.user,
            origin_saved_place=origin,
            destination_saved_place=destination,
            nickname="출근",
            default_constraints=self.conditions(),
        )
        FavoriteJourney.objects.create(
            user=self.user,
            origin_saved_place=None,
            destination_saved_place=destination,
            nickname="깨진 레거시",
            default_constraints={},
        )

        deleted = self.client.delete(f"/api/v1/me/saved-places/{origin.id}")
        self.assertEqual(deleted.status_code, 204)
        favorite.refresh_from_db()
        self.assertIsNotNone(favorite.deleted_at)
        self.assertEqual(self.client.get("/api/v1/me/favorite-journeys").json(), [])

    def test_atomic_creation_requires_csrf(self) -> None:
        self.accept("PRECISE_LOCATION")
        csrf_client = Client(enforce_csrf_checks=True)
        self.login(csrf_client, self.user)
        denied = csrf_client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(self.from_places_payload()),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-csrf-0001",
        )
        csrf_client.get("/api/v1/health")
        accepted = csrf_client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(self.from_places_payload()),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-csrf-0001",
            HTTP_X_CSRFTOKEN=csrf_client.cookies["csrftoken"].value,
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "FORBIDDEN")
        self.assertEqual(accepted.status_code, 201)

    @override_settings(FAVORITE_WRITE_RATE_LIMIT_PER_MINUTE=1)
    def test_completed_replay_bypasses_write_quota_but_new_claim_does_not(self) -> None:
        self.accept("PRECISE_LOCATION")
        first = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(self.from_places_payload()),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-rate-0001",
            REMOTE_ADDR="198.51.100.41",
        )
        replay = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(self.from_places_payload()),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-rate-0001",
            REMOTE_ADDR="198.51.100.41",
        )
        new_claim = self.client.post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(self.from_places_payload()),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="favorite-rate-0002",
            REMOTE_ADDR="198.51.100.41",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(new_claim.status_code, 429)
        self.assertEqual(new_claim.json()["code"], "RATE_LIMITED")
        self.assertEqual(SavedPlace.objects.count(), 2)
        self.assertEqual(FavoriteJourney.objects.count(), 1)
        self.assertEqual(FavoriteCreationIdempotency.objects.count(), 1)

    @override_settings(FAVORITE_WRITE_RATE_LIMIT_PER_MINUTE=1)
    def test_direct_post_endpoints_share_the_location_favorite_write_quota(self) -> None:
        self.accept("PRECISE_LOCATION")
        origin = self.client.post(
            "/api/v1/me/saved-places",
            data=json.dumps(self.place("집", "광교중앙역", 127.05)),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.51",
        )
        destination = SavedPlace.objects.create(
            user=self.user,
            label="회사",
            display_name="세종대학교",
            coordinate={"lon": 127.08, "lat": 37.4},
        )
        bypass = self.client.post(
            "/api/v1/me/favorite-journeys",
            data=json.dumps(
                {
                    "nickname": "우회 시도",
                    "originSavedPlaceId": origin.json()["id"],
                    "destinationSavedPlaceId": str(destination.id),
                    "defaultConstraints": {},
                    "searchConditions": self.conditions(),
                }
            ),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.51",
        )
        self.assertEqual(origin.status_code, 201)
        self.assertEqual(bypass.status_code, 429)
        self.assertEqual(bypass.json()["code"], "RATE_LIMITED")
        self.assertEqual(FavoriteJourney.objects.count(), 0)

    @override_settings(FAVORITE_WRITE_RATE_LIMIT_PER_MINUTE=1)
    def test_favorite_write_quota_isolated_for_users_behind_same_ip(self) -> None:
        self.accept("PRECISE_LOCATION")
        other = IdentityRepository.create_user(email="favorite-nat-peer@example.com")
        other_client = self.login(Client(), other)
        ConsentRepository.record(
            user_id=other.id,
            consent_type="PRECISE_LOCATION",
            document_version=settings.CONSENT_DOCUMENT_VERSIONS["PRECISE_LOCATION"],
            accepted=True,
        )
        shared_ip = "198.51.100.81"

        first = self.client.post(
            "/api/v1/me/saved-places",
            data=json.dumps(self.place("집", "광교중앙역", 127.05)),
            content_type="application/json",
            REMOTE_ADDR=shared_ip,
        )
        peer = other_client.post(
            "/api/v1/me/saved-places",
            data=json.dumps(self.place("회사", "세종대학교", 127.08)),
            content_type="application/json",
            REMOTE_ADDR=shared_ip,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(peer.status_code, 201)
        self.assertEqual(SavedPlace.objects.filter(user=self.user).count(), 1)
        self.assertEqual(SavedPlace.objects.filter(user=other).count(), 1)

    @override_settings(FAVORITE_WRITE_RATE_LIMIT_PER_MINUTE=1)
    def test_favorite_write_quota_follows_owner_across_ip_changes(self) -> None:
        self.accept("PRECISE_LOCATION")
        first = self.client.post(
            "/api/v1/me/saved-places",
            data=json.dumps(self.place("집", "광교중앙역", 127.05)),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.82",
        )
        changed_ip = self.client.post(
            "/api/v1/me/saved-places",
            data=json.dumps(self.place("회사", "세종대학교", 127.08)),
            content_type="application/json",
            REMOTE_ADDR="203.0.113.82",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(changed_ip.status_code, 429)
        self.assertEqual(changed_ip.json()["code"], "RATE_LIMITED")
        self.assertEqual(SavedPlace.objects.filter(user=self.user).count(), 1)

    def test_owner_rate_limit_storage_and_exception_locals_hide_user_id(self) -> None:
        request = RequestFactory().post(
            "/api/v1/me/saved-places",
            REMOTE_ADDR="198.51.100.83",
        )
        user_id = str(self.user.id)
        account_views._enforce_favorite_write_rate_limit(request, user_id=user_id)
        cache_keys = list(rate_limit_cache()._entries)

        self.assertEqual(len(cache_keys), 1)
        self.assertTrue(cache_keys[0].startswith("favorite-location-write:"))
        self.assertNotIn(user_id, cache_keys[0])

        try:
            with patch("journeys.abuse.hmac.new", side_effect=RuntimeError("digest failure")):
                account_views._enforce_favorite_write_rate_limit(request, user_id=user_id)
        except RuntimeError:
            report = ExceptionReporter(request, *sys.exc_info()).get_traceback_text()
        else:  # pragma: no cover - the injected failure is the test precondition.
            self.fail("Expected injected owner digest failure")

        self.assertNotIn(user_id, report)

    @override_settings(FAVORITE_WRITE_RATE_LIMIT_PER_MINUTE=1)
    def test_patch_and_delete_are_rate_limited_as_database_writes(self) -> None:
        origin = SavedPlace.objects.create(
            user=self.user,
            label="집",
            display_name="광교",
            coordinate={"lon": 127.05, "lat": 37.4},
        )
        destination = SavedPlace.objects.create(
            user=self.user,
            label="회사",
            display_name="서울",
            coordinate={"lon": 127.08, "lat": 37.5},
        )
        favorite = FavoriteJourney.objects.create(
            user=self.user,
            origin_saved_place=origin,
            destination_saved_place=destination,
            nickname="출근",
            default_constraints=self.conditions(),
        )
        renamed = self.client.patch(
            f"/api/v1/me/favorite-journeys/{favorite.id}",
            data=json.dumps({"nickname": "새 이름"}),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.61",
        )
        limited_delete = self.client.delete(
            f"/api/v1/me/favorite-journeys/{favorite.id}",
            REMOTE_ADDR="198.51.100.61",
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(limited_delete.status_code, 429)
        favorite.refresh_from_db()
        self.assertIsNone(favorite.deleted_at)

    def test_atomic_creation_rolls_back_both_places_when_a_save_fails(self) -> None:
        self.accept("PRECISE_LOCATION")
        original_saved_place_save = SavedPlace.save
        save_calls = 0

        def fail_second_place(instance, *args, **kwargs):
            nonlocal save_calls
            save_calls += 1
            if save_calls == 2:
                raise RuntimeError("injected saved-place failure")
            return original_saved_place_save(instance, *args, **kwargs)

        with patch.object(SavedPlace, "save", new=fail_second_place):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/api/v1/me/favorite-journeys/from-places",
                    data=json.dumps(self.from_places_payload()),
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY="favorite-rollback-place",
                    REMOTE_ADDR="198.51.100.71",
                )
        self.assertEqual(SavedPlace.objects.count(), 0)
        self.assertEqual(FavoriteJourney.objects.count(), 0)
        self.assertEqual(FavoriteCreationIdempotency.objects.count(), 0)

        with patch.object(FavoriteJourney, "save", side_effect=RuntimeError("injected favorite failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/api/v1/me/favorite-journeys/from-places",
                    data=json.dumps(self.from_places_payload()),
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY="favorite-rollback-journey",
                    REMOTE_ADDR="198.51.100.72",
                )
        self.assertEqual(SavedPlace.objects.count(), 0)
        self.assertEqual(FavoriteJourney.objects.count(), 0)
        self.assertEqual(FavoriteCreationIdempotency.objects.count(), 0)

    def test_exception_report_redacts_json_payload_and_idempotency_key(self) -> None:
        secret_place_name = "민감한 집 위치 예외보고서 금지"
        secret_idempotency_key = "raw-idempotency-secret-0001"
        payload = self.from_places_payload()
        payload["originPlace"]["place"]["displayName"] = secret_place_name
        request = RequestFactory().post(
            "/api/v1/me/favorite-journeys/from-places",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=secret_idempotency_key,
        )
        try:
            with patch.object(
                account_views.canonical_contracts,
                "validate",
                side_effect=RuntimeError("injected schema validator failure"),
            ):
                account_views._validate_favorite_from_places(payload)
        except RuntimeError:
            report = ExceptionReporter(request, *sys.exc_info()).get_traceback_text()
        else:  # pragma: no cover - the injected failure is the test precondition.
            self.fail("Expected injected validation failure")

        self.assertNotIn(secret_place_name, report)
        self.assertNotIn(secret_idempotency_key, report)

        try:
            with patch("journeys.favorite_payload.hmac.new", side_effect=RuntimeError("digest failure")):
                idempotency_key_digest(user_id=str(self.user.id), raw_key=secret_idempotency_key)
        except RuntimeError:
            key_report = ExceptionReporter(request, *sys.exc_info()).get_traceback_text()
        else:  # pragma: no cover - the injected failure is the test precondition.
            self.fail("Expected injected digest failure")

        try:
            with patch("journeys.favorite_payload.hmac.new", side_effect=RuntimeError("digest failure")):
                request_fingerprint(user_id=str(self.user.id), payload=payload)
        except RuntimeError:
            payload_report = ExceptionReporter(request, *sys.exc_info()).get_traceback_text()
        else:  # pragma: no cover - the injected failure is the test precondition.
            self.fail("Expected injected digest failure")

        self.assertNotIn(secret_idempotency_key, key_report)
        self.assertNotIn(secret_place_name, payload_report)

    @override_settings(ROUTING_GATEWAY_MODE="stub")
    def test_history_summary_is_safe_and_route_retry_creates_one_record(self) -> None:
        self.accept("SEARCH_HISTORY")
        payload = LockedFixtures().get("public_request")
        payload["saveToHistory"] = True
        first = self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="history-1-5-0001",
        )
        replay = self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="history-1-5-0001",
        )
        history = self.client.get("/api/v1/route-searches")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.json()["searchId"], replay.json()["searchId"])
        self.assertEqual(RouteSearch.objects.filter(user=self.user, save_to_history=True).count(), 1)
        summary = history.json()["items"][0]["requestSummary"]
        self.assertEqual(summary["originDisplayName"], payload["origin"]["displayName"])
        self.assertEqual(summary["destinationDisplayName"], payload["destination"]["displayName"])
        self.assertEqual(summary["taxiBudget"], payload["taxiBudget"])
        encoded = json.dumps(summary, ensure_ascii=False)
        self.assertNotIn("coordinate", encoded)
        self.assertNotIn("provider", encoded.lower())
        forwarded = json.dumps(views._gateway.last_forwarded_request, ensure_ascii=False)
        self.assertNotIn("saveToHistory", forwarded)
        self.assertNotIn(str(self.user.id), forwarded)
        self.assertNotIn(payload["origin"]["displayName"], forwarded)
