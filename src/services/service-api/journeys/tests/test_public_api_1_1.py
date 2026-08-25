from __future__ import annotations

import copy
import json
from datetime import timedelta

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import resolve
from django.utils import timezone

from consent.repository import ConsentRepository
from identity.repository import IdentityRepository
from identity.sessions import SessionRepository
from journeys import views
from journeys.abuse import reset_rate_limits
from journeys.api_common import token_digest
from journeys.contracts import CanonicalContracts, LockedFixtures
from journeys.models import (
    AnonymousSession,
    DataRightsJob,
    RouteSearch,
    RouteSearchResult,
    SavedPlace,
)


class PublicApi11Tests(TestCase):
    def setUp(self) -> None:
        views._fixtures = None
        views._gateway = None
        views._idempotency.clear()
        views._rate_buckets.clear()
        reset_rate_limits()
        self.client = Client()
        self.user = IdentityRepository.create_user(email="owner@example.com")
        self.contracts = CanonicalContracts()

    def login(self, client: Client | None = None, user=None) -> Client:
        client = client or self.client
        user = user or self.user
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

    def test_guest_session_is_opaque_hashed_and_revocable(self) -> None:
        created = self.client.post("/api/v1/guest-sessions")
        token = created.json()["guestToken"]
        row = AnonymousSession.objects.get()

        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.contracts.validate("public", "GuestSessionCredential", created.json()), [])
        self.assertGreaterEqual(len(token), 32)
        self.assertNotEqual(row.token_hash, token)
        current = self.client.get("/api/v1/session", HTTP_X_GUEST_TOKEN=token)
        self.assertEqual(current.json()["subjectType"], "GUEST")
        self.assertEqual(self.client.delete("/api/v1/session", HTTP_X_GUEST_TOKEN=token).status_code, 204)
        self.assertEqual(self.client.get("/api/v1/session", HTTP_X_GUEST_TOKEN=token).status_code, 401)

    @override_settings(GUEST_SESSION_RATE_LIMIT_PER_MINUTE=1)
    def test_guest_session_issuance_is_rate_limited_without_leaking_tokens(self) -> None:
        first = self.client.post("/api/v1/guest-sessions", REMOTE_ADDR="198.51.100.10")
        second = self.client.post("/api/v1/guest-sessions", REMOTE_ADDR="198.51.100.10")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "RATE_LIMITED")
        self.assertNotIn("guestToken", second.json())
        self.assertEqual(second["Retry-After"], "60")
        self.assertEqual(AnonymousSession.objects.count(), 1)

    def test_preferences_etag_and_conflict(self) -> None:
        self.login()
        initial = self.client.get("/api/v1/me/preferences")
        payload = initial.json()
        payload["maxWalkSeconds"] = 1200
        updated = self.client.put(
            "/api/v1/me/preferences",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IF_MATCH=initial["ETag"],
        )
        stale = self.client.put(
            "/api/v1/me/preferences",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IF_MATCH=initial["ETag"],
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.contracts.validate("public", "UserPreferences", updated.json()), [])
        self.assertEqual(updated.json()["version"], 2)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["code"], "PREFERENCE_VERSION_CONFLICT")

    def test_saved_places_and_favorites_are_owner_bound_and_soft_deleted(self) -> None:
        self.login()
        ConsentRepository.record(
            user_id=self.user.id,
            consent_type="PRECISE_LOCATION",
            document_version=settings.CONSENT_DOCUMENT_VERSIONS["PRECISE_LOCATION"],
            accepted=True,
        )
        place_payload = {
            "label": "집",
            "place": {
                "displayName": "광교",
                "coordinate": {"lon": 127.05, "lat": 37.29},
                "provider": None,
                "providerPlaceId": None,
                "regionCode": None,
            },
            "isSensitive": True,
        }
        origin = self.client.post(
            "/api/v1/me/saved-places", data=json.dumps(place_payload), content_type="application/json"
        ).json()
        place_payload["label"] = "회사"
        destination = self.client.post(
            "/api/v1/me/saved-places", data=json.dumps(place_payload), content_type="application/json"
        ).json()
        favorite_payload = {
            "nickname": "출근",
            "originSavedPlaceId": origin["id"],
            "destinationSavedPlaceId": destination["id"],
            "defaultConstraints": {"maxWalkSeconds": 900},
        }
        favorite = self.client.post(
            "/api/v1/me/favorite-journeys",
            data=json.dumps(favorite_payload),
            content_type="application/json",
        )
        self.assertEqual(favorite.status_code, 201)
        self.assertEqual(self.contracts.validate("public", "SavedPlace", origin), [])
        self.assertEqual(self.contracts.validate("public", "FavoriteJourney", favorite.json()), [])
        self.assertEqual(origin["id"], str(SavedPlace.objects.get(id=origin["id"]).id))
        self.assertEqual(favorite.json()["originSavedPlaceId"], origin["id"])

        other = IdentityRepository.create_user(email="other@example.com")
        other_client = self.login(Client(), other)
        self.assertEqual(
            other_client.patch(
                f"/api/v1/me/saved-places/{origin['id']}",
                data=json.dumps({"label": "침입"}),
                content_type="application/json",
            ).status_code,
            404,
        )
        self.assertEqual(
            other_client.delete(f"/api/v1/me/favorite-journeys/{favorite.json()['id']}").status_code,
            404,
        )
        self.assertEqual(self.client.delete(f"/api/v1/me/saved-places/{origin['id']}").status_code, 204)
        self.assertIsNotNone(SavedPlace.objects.get(id=origin["id"]).deleted_at)
        self.assertEqual(self.client.get("/api/v1/me/favorite-journeys").json(), [])

    def test_consent_and_data_rights_jobs_are_owner_bound(self) -> None:
        self.login()
        consent = self.client.put(
            "/api/v1/me/consents/SEARCH_HISTORY",
            data=json.dumps(
                {
                    "documentVersion": settings.CONSENT_DOCUMENT_VERSIONS["SEARCH_HISTORY"],
                    "accepted": True,
                }
            ),
            content_type="application/json",
        )
        first = self.client.post("/api/v1/me/data-exports")
        conflict = self.client.post("/api/v1/me/data-exports")

        self.assertEqual(consent.status_code, 200)
        self.assertEqual(self.contracts.validate("public", "ConsentRecord", consent.json()), [])
        self.assertEqual(self.client.get("/api/v1/me/consents").json()["items"][0]["accepted"], True)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(self.contracts.validate("public", "DataRightsJob", first.json()), [])
        self.assertEqual(conflict.status_code, 409)
        self.assertIsNone(first.json()["downloadUrl"])

        other = IdentityRepository.create_user(email="jobs-other@example.com")
        other_client = self.login(Client(), other)
        self.assertEqual(
            other_client.get(f"/api/v1/me/data-exports/{first.json()['jobId']}").status_code,
            404,
        )
        self.assertEqual(DataRightsJob.objects.count(), 1)

    def test_consent_rejects_stale_and_unknown_document_versions(self) -> None:
        self.login()
        stale = self.client.put(
            "/api/v1/me/consents/SEARCH_HISTORY",
            data=json.dumps({"documentVersion": "stale-version", "accepted": True}),
            content_type="application/json",
        )
        unknown = self.client.put(
            "/api/v1/me/consents/UNKNOWN_PURPOSE",
            data=json.dumps({"documentVersion": "stale-version", "accepted": True}),
            content_type="application/json",
        )

        self.assertEqual(stale.status_code, 400)
        self.assertEqual(stale.json()["code"], "CONSTRAINT_OUT_OF_RANGE")
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(ConsentRepository.latest(user_id=self.user.id, consent_type="SEARCH_HISTORY"), None)

    @override_settings(ROUTING_GATEWAY_MODE="stub")
    def test_saved_search_history_and_detail_require_owner_and_consent(self) -> None:
        self.login()
        ConsentRepository.record(
            user_id=self.user.id,
            consent_type="SEARCH_HISTORY",
            document_version=settings.CONSENT_DOCUMENT_VERSIONS["SEARCH_HISTORY"],
            accepted=True,
        )
        payload = LockedFixtures().get("public_request")
        payload["saveToHistory"] = True
        response = self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="history-key-0001",
        )
        search_id = response.json()["searchId"]

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["history"]["saved"])
        self.assertEqual(self.client.get("/api/v1/route-searches").json()["items"][0]["searchId"], search_id)
        detail = self.client.get(f"/api/v1/route-searches/{search_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["warnings"], response.json()["warnings"])
        self.assertEqual(detail.json()["support"], response.json()["support"])

        other = IdentityRepository.create_user(email="search-other@example.com")
        other_client = self.login(Client(), other)
        self.assertEqual(other_client.get(f"/api/v1/route-searches/{search_id}").status_code, 404)

    @override_settings(ROUTING_GATEWAY_MODE="stub")
    def test_stale_history_consent_is_not_authorization(self) -> None:
        self.login()
        ConsentRepository.record(
            user_id=self.user.id,
            consent_type="SEARCH_HISTORY",
            document_version="stale-version",
            accepted=True,
        )
        payload = LockedFixtures().get("public_request")
        payload["saveToHistory"] = True
        response = self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="stale-history-key",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "CONSENT_REQUIRED")
        self.assertIsNone(views._gateway)

    def test_guest_save_to_history_is_rejected_without_forwarding(self) -> None:
        payload = LockedFixtures().get("public_request")
        payload["saveToHistory"] = True
        response = self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="guest-history-key",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "CONSENT_REQUIRED")
        self.assertIsNone(views._gateway)

    def test_session_cookie_does_not_forward_identity_or_saved_labels(self) -> None:
        self.login()
        payload = copy.deepcopy(LockedFixtures().get("public_request"))
        payload["saveToHistory"] = False
        response = self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="identity-safe-key",
        )
        forwarded = json.dumps(views._gateway.last_forwarded_request)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(self.user.id), forwarded)
        self.assertNotIn(payload["origin"]["displayName"], forwarded)
        self.assertNotIn(payload["origin"]["providerPlaceId"], forwarded)

    def test_feedback_is_owner_bound_consent_gated_and_single_submission(self) -> None:
        self.login()
        now = timezone.now()
        search = RouteSearch.objects.create(
            user=self.user,
            origin_coordinate={"lon": 127.05, "lat": 37.29},
            destination_coordinate={"lon": 127.11, "lat": 37.39},
            departure_time=now,
            taxi_budget_max=10000,
            strict_budget=True,
            constraints={},
            status="COMPLETE",
            routing_request_id="feedback-routing-request",
            contract_version="1.0",
            retention_until=now + timedelta(days=1),
            expires_at=now + timedelta(minutes=10),
        )
        RouteSearchResult.objects.create(
            route_search=search,
            recommendation_type="FASTEST",
            routing_route_id="route-feedback",
            p50_seconds=100,
            p90_seconds=120,
            taxi_cost_expected=5000,
            taxi_cost_upper=6000,
            reliability_score=0.8,
            public_result={},
        )
        payload = {"selectedRouteId": "route-feedback", "rating": 5}
        denied = self.client.post(
            f"/api/v1/route-searches/{search.id}/feedback",
            data=json.dumps(payload),
            content_type="application/json",
        )
        ConsentRepository.record(
            user_id=self.user.id,
            consent_type="ROUTING_FEEDBACK",
            document_version=settings.CONSENT_DOCUMENT_VERSIONS["ROUTING_FEEDBACK"],
            accepted=True,
        )
        accepted = self.client.post(
            f"/api/v1/route-searches/{search.id}/feedback",
            data=json.dumps(payload),
            content_type="application/json",
        )
        duplicate = self.client.post(
            f"/api/v1/route-searches/{search.id}/feedback",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(accepted.status_code, 204)
        self.assertEqual(duplicate.status_code, 409)

    def test_every_public_1_1_path_resolves(self) -> None:
        identifier = "00000000-0000-0000-0000-000000000001"
        paths = [
            "/api/v1/guest-sessions",
            "/api/v1/session",
            "/api/v1/places/suggest",
            "/api/v1/places/reverse-geocode",
            "/api/v1/route-searches",
            f"/api/v1/route-searches/{identifier}",
            f"/api/v1/route-searches/{identifier}/feedback",
            "/api/v1/me/preferences",
            "/api/v1/me/saved-places",
            f"/api/v1/me/saved-places/{identifier}",
            "/api/v1/me/favorite-journeys",
            f"/api/v1/me/favorite-journeys/{identifier}",
            "/api/v1/me/consents",
            "/api/v1/me/consents/SEARCH_HISTORY",
            "/api/v1/me/data-exports",
            f"/api/v1/me/data-exports/{identifier}",
            "/api/v1/me/data-deletions",
            f"/api/v1/me/data-deletions/{identifier}",
            "/api/v1/me/data",
            "/api/v1/support/capabilities",
            "/api/v1/health",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertIsNotNone(resolve(path).func)

    def test_public_capabilities_are_contract_safe(self) -> None:
        response = self.client.get("/api/v1/support/capabilities")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.contracts.validate("public", "PublicCapabilities", response.json()), [])
        self.assertNotIn("providers", response.json())
        self.assertNotIn("models", response.json())
