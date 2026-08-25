from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.conf import settings
from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from identity.lifecycle import (
    ACCOUNT_DELETION_GRACE,
    export_user_data,
    purge_service_data,
    schedule_user_deletion,
)
from identity.repository import IdentityRepository
from journeys.models import (
    AccountAuditEvent,
    AnonymousSession,
    ConsentRecord,
    FavoriteCreationIdempotency,
    FavoriteJourney,
    RouteFeedback,
    RouteSearch,
    RouteSearchResult,
    SavedPlace,
    ServiceUser,
    UserPreference,
)


class ServiceDataModelTests(TestCase):
    def setUp(self) -> None:
        self.user = IdentityRepository.create_user(
            email="User@Example.com",
            password_hash="opaque-password-hash",
        )

    def make_search(self, *, user=None, anonymous_session=None) -> RouteSearch:
        now = timezone.now()
        return RouteSearch.objects.create(
            user=user,
            anonymous_session=anonymous_session,
            origin_coordinate={"lon": 127.1, "lat": 37.2},
            destination_coordinate={"lon": 127.2, "lat": 37.3},
            origin_display_name="출발",
            destination_display_name="도착",
            departure_time=now,
            taxi_budget_max=10_000,
            strict_budget=True,
            constraints={},
            status="COMPLETE",
            routing_request_id=f"routing-{RouteSearch.objects.count()}",
            contract_version="1.0.0",
            retention_until=now + timedelta(days=1),
            expires_at=now + timedelta(days=1),
        )

    def test_dbml_table_names_are_materialized(self) -> None:
        expected = {
            "auth_user",
            "user_profile",
            "user_preference",
            "saved_place",
            "favorite_journey",
            "favorite_creation_idempotency",
            "anonymous_session",
            "authenticated_session",
            "route_search",
            "route_search_result",
            "route_feedback",
            "consent_record",
            "data_rights_job",
            "account_audit_event",
        }
        actual = {model._meta.db_table for model in apps.get_app_config("journeys").get_models()}
        self.assertEqual(actual, expected)
        self.assertTrue(expected.issubset(set(connection.introspection.table_names())))

    def test_identity_creation_normalizes_email_and_creates_profile(self) -> None:
        self.assertEqual(self.user.email, "user@example.com")
        self.assertEqual(self.user.profile.locale, "ko-KR")
        self.assertEqual(self.user.profile.timezone, "Asia/Seoul")

    def test_route_search_requires_exactly_one_owner(self) -> None:
        session = AnonymousSession.objects.create(
            token_hash="session-hash",
            expires_at=timezone.now() + timedelta(days=1),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_search(user=self.user, anonymous_session=session)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_search()

    def test_coordinate_round_trip_is_wgs84_mapping(self) -> None:
        search = self.make_search(user=self.user)
        search.refresh_from_db()
        self.assertEqual(search.origin_coordinate, {"lon": 127.1, "lat": 37.2})
        search.origin_coordinate = {"lon": 181, "lat": 37.2}
        with self.assertRaises(ValidationError):
            search.save(update_fields=["origin_coordinate"])

    def test_result_enforces_p90_and_public_snapshot_safety(self) -> None:
        search = self.make_search(user=self.user)
        unsafe = RouteSearchResult(
            route_search=search,
            recommendation_type="FASTEST",
            routing_route_id="opaque-route",
            p50_seconds=100,
            p90_seconds=120,
            taxi_cost_expected=5000,
            taxi_cost_upper=6000,
            reliability_score=Decimal("0.8"),
            public_result={"rawPayload": {"secret": True}},
        )
        with self.assertRaises(ValidationError):
            unsafe.full_clean()

        with self.assertRaises(IntegrityError), transaction.atomic():
            RouteSearchResult.objects.create(
                route_search=search,
                recommendation_type="FASTEST",
                routing_route_id="opaque-route",
                p50_seconds=120,
                p90_seconds=100,
                taxi_cost_expected=5000,
                taxi_cost_upper=6000,
                reliability_score=Decimal("0.8"),
                public_result={},
            )

    def test_saved_history_requires_user_and_current_consent(self) -> None:
        now = timezone.now()
        values = {
            "origin_coordinate": {"lon": 127.1, "lat": 37.2},
            "destination_coordinate": {"lon": 127.2, "lat": 37.3},
            "departure_time": now,
            "taxi_budget_max": 0,
            "strict_budget": True,
            "constraints": {},
            "status": "COMPLETE",
            "routing_request_id": "history-consent-search",
            "contract_version": "1.1.0",
            "expires_at": now + timedelta(hours=1),
        }
        with self.assertRaises(ValidationError):
            RouteSearch.objects.create_owned(
                user=self.user,
                anonymous_session=None,
                save_to_history=True,
                now=now,
                **values,
            )
        ConsentRecord.objects.create(
            user=self.user,
            consent_type="SEARCH_HISTORY",
            document_version=settings.CONSENT_DOCUMENT_VERSIONS["SEARCH_HISTORY"],
            accepted=True,
            recorded_at=now,
        )
        search = RouteSearch.objects.create_owned(
            user=self.user,
            anonymous_session=None,
            save_to_history=True,
            now=now,
            **values,
        )
        self.assertTrue(search.save_to_history)
        self.assertEqual(search.retention_until, now + timedelta(days=90))

    def test_favorite_creation_receipt_enforces_dbml_constraints(self) -> None:
        origin = SavedPlace.objects.create(
            user=self.user,
            label="집",
            display_name="집",
            coordinate={"lon": 127.0, "lat": 37.0},
        )
        destination = SavedPlace.objects.create(
            user=self.user,
            label="회사",
            display_name="회사",
            coordinate={"lon": 127.1, "lat": 37.1},
        )
        favorite = FavoriteJourney.objects.create(
            user=self.user,
            origin_saved_place=origin,
            destination_saved_place=destination,
            nickname="출근",
            default_constraints={},
        )
        created_at = timezone.now()
        values = {
            "user": self.user,
            "key_digest": "1" * 64,
            "request_fingerprint": "2" * 64,
            "digest_key_version": 1,
            "favorite_journey": favorite,
            "origin_saved_place": origin,
            "destination_saved_place": destination,
            "created_at": created_at,
            "expires_at": created_at + timedelta(hours=24),
        }
        FavoriteCreationIdempotency.objects.create(**values)

        with self.assertRaises(IntegrityError), transaction.atomic():
            FavoriteCreationIdempotency.objects.create(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FavoriteCreationIdempotency.objects.create(
                **{
                    **values,
                    "key_digest": "3" * 64,
                    "origin_saved_place": origin,
                    "destination_saved_place": origin,
                }
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            FavoriteCreationIdempotency.objects.create(
                **{
                    **values,
                    "key_digest": "4" * 64,
                    "digest_key_version": 0,
                }
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            FavoriteCreationIdempotency.objects.create(
                **{
                    **values,
                    "key_digest": "5" * 64,
                    "expires_at": created_at + timedelta(hours=23),
                }
            )


class DataLifecycleTests(TestCase):
    def setUp(self) -> None:
        self.user = IdentityRepository.create_user(
            email="owner@example.com",
            password_hash="must-never-export",
        )
        self.preference = UserPreference.objects.create(user=self.user)
        self.place = SavedPlace.objects.create(
            user=self.user,
            label="집",
            display_name="민감 장소",
            coordinate={"lon": 127.1, "lat": 37.2},
            provider="KAKAO_LOCAL",
            provider_place_id="provider-place-id",
        )
        self.favorite = FavoriteJourney.objects.create(
            user=self.user,
            origin_saved_place=self.place,
            destination_saved_place=self.place,
            default_constraints={},
            nickname="통근",
        )
        now = timezone.now()
        self.search = RouteSearch.objects.create(
            user=self.user,
            origin_coordinate={"lon": 127.1, "lat": 37.2},
            destination_coordinate={"lon": 127.2, "lat": 37.3},
            departure_time=now,
            taxi_budget_max=0,
            strict_budget=True,
            constraints={},
            status="PARTIAL",
            routing_request_id="opaque-routing-request",
            contract_version="1.0.0",
            save_to_history=True,
            retention_until=now + timedelta(days=90),
            expires_at=now + timedelta(days=1),
        )
        RouteSearchResult.objects.create(
            route_search=self.search,
            recommendation_type="PUBLIC_TRANSIT_ONLY",
            routing_route_id="opaque-route",
            p50_seconds=100,
            p90_seconds=120,
            taxi_cost_expected=0,
            taxi_cost_upper=0,
            reliability_score=Decimal("0.75"),
            public_result={"routeId": "opaque-route"},
        )
        RouteFeedback.objects.create(
            route_search=self.search,
            user=self.user,
            selected_route_id="opaque-route",
            rating=4,
        )
        ConsentRecord.objects.create(
            user=self.user,
            consent_type="LOCATION",
            document_version="2026-08",
            accepted=True,
            recorded_at=now,
        )

    def make_favorite_creation_receipt(self, *, created_at=None):
        created_at = created_at or timezone.now()
        destination = SavedPlace.objects.create(
            user=self.user,
            label="회사",
            display_name="다른 민감 장소",
            coordinate={"lon": 127.2, "lat": 37.3},
        )
        favorite = FavoriteJourney.objects.create(
            user=self.user,
            origin_saved_place=self.place,
            destination_saved_place=destination,
            default_constraints={},
            nickname="원자 생성 통근",
        )
        return FavoriteCreationIdempotency.objects.create(
            user=self.user,
            key_digest="a" * 64,
            request_fingerprint="b" * 64,
            digest_key_version=1,
            favorite_journey=favorite,
            origin_saved_place=self.place,
            destination_saved_place=destination,
            created_at=created_at,
            expires_at=created_at + timedelta(hours=24),
        )

    def test_export_contains_subject_data_but_no_auth_or_routing_secrets(self) -> None:
        self.make_favorite_creation_receipt()
        exported = export_user_data(user_id=self.user.id)
        encoded = json.dumps(exported, ensure_ascii=False)
        self.assertIn("민감 장소", encoded)
        self.assertNotIn("must-never-export", encoded)
        self.assertNotIn("password_hash", encoded)
        self.assertNotIn("token_hash", encoded)
        self.assertNotIn("opaque-routing-request", encoded)
        self.assertNotIn("a" * 64, encoded)
        self.assertNotIn("request_fingerprint", encoded)
        self.assertNotIn("favorite_creation_idempotency", encoded)
        self.assertEqual(exported["routeSearches"][0]["results"], [{"routeId": "opaque-route"}])

    def test_deletion_schedule_is_idempotent_and_soft_deletes_places(self) -> None:
        requested_at = timezone.now()
        schedule_user_deletion(user_id=self.user.id, requested_at=requested_at)
        schedule_user_deletion(user_id=self.user.id, requested_at=requested_at + timedelta(hours=1))
        self.user.refresh_from_db()
        self.place.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual(self.user.deleted_at, requested_at)
        self.assertEqual(self.place.deleted_at, requested_at)
        self.assertEqual(
            AccountAuditEvent.objects.filter(event_type="DATA_DELETION_SCHEDULED").count(),
            1,
        )

    def test_retention_hard_deletes_account_and_preserves_safe_audit(self) -> None:
        now = timezone.now()
        self.make_favorite_creation_receipt(created_at=now)
        schedule_user_deletion(
            user_id=self.user.id,
            requested_at=now - ACCOUNT_DELETION_GRACE - timedelta(seconds=1),
        )
        report = purge_service_data(now=now)
        self.assertEqual(report.hard_deleted_accounts, 1)
        self.assertFalse(ServiceUser.objects.filter(id=self.user.id).exists())
        self.assertFalse(RouteSearch.objects.filter(id=self.search.id).exists())
        self.assertFalse(FavoriteCreationIdempotency.objects.filter(user_id=self.user.id).exists())
        completion = AccountAuditEvent.objects.get(event_type="DATA_DELETION_COMPLETED")
        self.assertIsNone(completion.user_id)
        self.assertEqual(completion.safe_metadata, {})

    def test_expired_favorite_creation_receipts_are_purged(self) -> None:
        now = timezone.now()
        receipt = self.make_favorite_creation_receipt(
            created_at=now - timedelta(hours=25)
        )

        report = purge_service_data(now=now)

        self.assertEqual(report.expired_favorite_creation_idempotency, 1)
        self.assertFalse(FavoriteCreationIdempotency.objects.filter(id=receipt.id).exists())
        self.assertTrue(FavoriteJourney.objects.filter(id=receipt.favorite_journey_id).exists())

    def test_expired_anonymous_session_cascades_guest_search(self) -> None:
        now = timezone.now()
        session = AnonymousSession.objects.create(
            token_hash="guest-token-hash",
            expires_at=now - timedelta(seconds=1),
        )
        search = RouteSearch.objects.create(
            anonymous_session=session,
            origin_coordinate={"lon": 127.1, "lat": 37.2},
            destination_coordinate={"lon": 127.2, "lat": 37.3},
            departure_time=now,
            taxi_budget_max=0,
            strict_budget=True,
            constraints={},
            status="EXPIRED",
            routing_request_id="expired-guest-routing-request",
            contract_version="1.0.0",
            retention_until=now,
            expires_at=now,
        )
        report = purge_service_data(now=now)
        self.assertEqual(report.expired_anonymous_sessions, 1)
        self.assertFalse(RouteSearch.objects.filter(id=search.id).exists())
