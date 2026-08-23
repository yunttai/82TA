from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from journeys import abuse, views
from journeys.cache import BoundedTTLCache
from journeys.contracts import CanonicalContracts, LockedFixtures
from journeys.models import RouteSearch


class RouteSearchApiTests(TestCase):
    def setUp(self) -> None:
        views._fixtures = None
        views._gateway = None
        views._idempotency.clear()
        views._rate_buckets.clear()
        self.client = Client(enforce_csrf_checks=False)
        self.fixtures = LockedFixtures()
        self.payload = self.fixtures.get("public_request")
        self.payload["saveToHistory"] = False

    def post(self, payload=None, *, key="fixture-key-0001", correlation="corr-0001"):
        headers = {"HTTP_IDEMPOTENCY_KEY": key}
        if correlation is not None:
            headers["HTTP_X_CORRELATION_ID"] = correlation
        return self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(self.payload if payload is None else payload),
            content_type="application/json",
            **headers,
        )

    def test_health_is_minimal_and_issues_csrf_cookie(self) -> None:
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})
        self.assertIn("csrftoken", response.cookies)

    @override_settings(ROUTING_GATEWAY_MODE="replay")
    def test_canonical_partial_replay_round_trip(self) -> None:
        response = self.post()
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Correlation-Id"], "corr-0001")
        self.assertEqual(body["status"], "PARTIAL")
        self.assertEqual(body["recommendations"], {
            "fastest": None,
            "stable": None,
            "efficient": None,
            "publicTransitOnly": None,
        })
        self.assertEqual(body["paretoFrontier"], [])
        self.assertNotIn("providerStatus", body)
        self.assertNotIn("modelVersions", body)
        self.assertNotIn("computation", body)
        self.assertEqual(CanonicalContracts().validate("public", "PublicRouteSearchResponse", body), [])

    def test_gateway_forwards_no_identity_or_place_display_metadata(self) -> None:
        response = self.post()
        self.assertEqual(response.status_code, 200)
        forwarded = views._gateway.last_forwarded_request
        encoded = json.dumps(forwarded)

        self.assertNotIn("displayName", encoded)
        self.assertNotIn("providerPlaceId", encoded)
        self.assertNotIn("saveToHistory", encoded)
        self.assertNotIn("userId", encoded)
        self.assertNotIn("email", encoded)
        self.assertNotEqual(views._gateway.last_envelope.correlation_id, "corr-0001")
        self.assertEqual(len(views._gateway.last_envelope.correlation_id), 36)
        self.assertEqual(response["X-Correlation-Id"], "corr-0001")
        self.assertNotEqual(views._gateway.last_envelope.idempotency_key, "fixture-key-0001")
        self.assertEqual(len(views._gateway.last_envelope.idempotency_key), 64)
        self.assertIsNotNone(datetime.fromisoformat(views._gateway.last_envelope.request_deadline).tzinfo)

    def test_transient_coordinate_retention_is_capped_independently_of_routing_expiry(self) -> None:
        initial = self.post(key="retention-source-key")
        self.assertEqual(initial.status_code, 200)
        guest = RouteSearch.objects.get().anonymous_session
        RouteSearch.objects.all().delete()
        public_response = initial.json()
        public_response["expiresAt"] = (timezone.now() + timedelta(days=365)).isoformat()

        persisted = views._persist_search(
            self.payload,
            public_response,
            SimpleNamespace(user=None, guest=guest, kind="GUEST"),
            routing_request_id="retention-cap-request",
        )

        search = RouteSearch.objects.get(id=persisted["searchId"])
        self.assertLessEqual(
            search.retention_until,
            timezone.now() + timedelta(seconds=views.settings.ROUTE_RESULT_TTL_SECONDS + 1),
        )

    def test_detail_replays_exact_persisted_pareto_metadata(self) -> None:
        response = self.post(key="pareto-metadata-key")
        self.assertEqual(response.status_code, 200)
        search = RouteSearch.objects.get(id=response.json()["searchId"])
        metadata = search.constraints["_publicMetadata"]
        metadata["paretoFrontier"] = [
            {
                "routeId": "pareto-only-route",
                "taxiCostUpper": 0,
                "p50Seconds": 1200,
                "p90Seconds": 1500,
            }
        ]
        search.constraints["_publicMetadata"] = metadata
        search.save(update_fields=["constraints"])

        detail = self.client.get(f"/api/v1/route-searches/{search.id}")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["paretoFrontier"], metadata["paretoFrontier"])
        self.assertEqual(list(search.results.values_list("routing_route_id", flat=True)), [])

    def test_missing_idempotency_key_returns_problem_details(self) -> None:
        response = self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["Content-Type"], "application/problem+json")
        self.assertEqual(response.json()["code"], "CONSTRAINT_OUT_OF_RANGE")

    def test_idempotent_replay_and_conflict(self) -> None:
        first = self.post(key="same-key-0001")
        second = self.post(key="same-key-0001", correlation="corr-0002")
        changed = copy.deepcopy(self.payload)
        changed["taxiBudget"]["maxAmount"] = 5000
        conflict = self.post(changed, key="same-key-0001", correlation="corr-0003")

        self.assertEqual(first.json(), second.json())
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "IDEMPOTENCY_CONFLICT")

    def test_arrive_by_is_rejected_before_gateway(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["departure"]["type"] = "ARRIVE_BY"
        response = self.post(payload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "ARRIVE_BY_UNSUPPORTED")
        self.assertIsNone(views._gateway)

    def test_schema_rejects_extra_field_and_does_not_echo_location(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["origin"]["secretLabel"] = "home"
        response = self.post(payload)

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("home", response.content.decode())

    def test_invalid_coordinate_uses_canonical_code(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["origin"]["coordinate"]["lon"] = 200
        response = self.post(payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_COORDINATE")

    @override_settings(ROUTING_GATEWAY_MODE="stub")
    def test_dynamic_valid_depart_at_request_succeeds_in_stub_mode(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["origin"]["displayName"] = "광교중앙역"
        payload["origin"]["coordinate"] = {"lon": 127.0517, "lat": 37.2886}
        payload["origin"]["providerPlaceId"] = "dynamic-origin"
        payload["destination"]["displayName"] = "강남역"
        payload["destination"]["coordinate"] = {"lon": 127.0276, "lat": 37.4979}
        payload["destination"]["providerPlaceId"] = "dynamic-destination"
        payload["departure"]["time"] = "2026-08-23T09:15:00+09:00"
        payload["taxiBudget"]["maxAmount"] = 5000
        payload["saveToHistory"] = False

        response = self.post(payload, key="dynamic-key-0001")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "PARTIAL")
        self.assertEqual(response.json()["recommendations"]["fastest"], None)

    @override_settings(ROUTING_GATEWAY_MODE="replay")
    def test_noncanonical_valid_request_is_an_honest_replay_miss(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["taxiBudget"]["maxAmount"] = 5000
        response = self.post(payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "TRANSIT_PROVIDER_UNAVAILABLE")

    @override_settings(PUBLIC_RATE_LIMIT_PER_MINUTE=1)
    def test_rate_limit_is_problem_details(self) -> None:
        first = self.post(key="rate-key-0001")
        second = self.post(key="rate-key-0002")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "RATE_LIMITED")
        self.assertEqual(second["Retry-After"], "60")

    @override_settings(
        PUBLIC_RATE_LIMIT_PER_MINUTE=1,
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_IPS=("10.0.0.0/24",),
    )
    def test_route_limit_uses_nearest_untrusted_proxy_hop(self) -> None:
        first = self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(self.payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="proxy-rate-key-0001",
            HTTP_X_FORWARDED_FOR="192.0.2.1, 198.51.100.50",
            REMOTE_ADDR="10.0.0.5",
        )
        second = self.client.post(
            "/api/v1/route-searches",
            data=json.dumps(self.payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="proxy-rate-key-0002",
            HTTP_X_FORWARDED_FOR="192.0.2.2, 198.51.100.50",
            REMOTE_ADDR="10.0.0.6",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_invalid_correlation_is_not_reflected(self) -> None:
        response = self.post(correlation="bad\ncorrelation")
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response["X-Correlation-Id"], "bad\ncorrelation")


class CsrfTests(TestCase):
    def test_post_with_csrf_cookie_requires_matching_header(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.get("/api/v1/health")
        payload = LockedFixtures().get("public_request")
        payload["saveToHistory"] = False
        response = client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="csrf-key-0001",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/problem+json")
        self.assertEqual(response.json()["code"], "FORBIDDEN")

    def test_post_with_csrf_cookie_and_header_succeeds(self) -> None:
        views._fixtures = None
        views._gateway = None
        views._idempotency.clear()
        views._rate_buckets.clear()
        client = Client(enforce_csrf_checks=True)
        client.get("/api/v1/health")
        csrf_token = client.cookies["csrftoken"].value
        response = client.post(
            "/api/v1/route-searches",
            data=json.dumps({**LockedFixtures().get("public_request"), "saveToHistory": False}),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="csrf-key-0002",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, 200)


class BoundedCacheTests(SimpleTestCase):
    def test_expiry_uses_injected_monotonic_clock(self) -> None:
        now = [100.0]
        cache = BoundedTTLCache[str, str](max_entries=2, ttl_seconds=10, clock=lambda: now[0])
        cache.set("first", "value")
        now[0] = 109.9
        self.assertEqual(cache.get("first"), "value")
        now[0] = 110.0
        self.assertIsNone(cache.get("first"))
        self.assertEqual(len(cache), 0)

    def test_eviction_is_deterministic_lru(self) -> None:
        cache = BoundedTTLCache[str, str](max_entries=2, ttl_seconds=60)
        cache.set("first", "1")
        cache.set("second", "2")
        self.assertEqual(cache.get("first"), "1")
        cache.set("third", "3")
        self.assertIsNone(cache.get("second"))
        self.assertEqual(cache.get("first"), "1")
        self.assertEqual(cache.get("third"), "3")


class BoundedAbuseTests(TestCase):
    def setUp(self) -> None:
        self.original_idempotency = views._idempotency
        self.original_rate_buckets = abuse._buckets
        views._fixtures = None
        views._gateway = None
        views._idempotency = BoundedTTLCache(max_entries=3, ttl_seconds=60)
        abuse._buckets = BoundedTTLCache(max_entries=2, ttl_seconds=60)
        views._rate_buckets = abuse._buckets
        self.client = Client(enforce_csrf_checks=False)
        self.payload = LockedFixtures().get("public_request")
        self.payload["saveToHistory"] = False
        self.addCleanup(self._restore_caches)

    def _restore_caches(self) -> None:
        views._idempotency = self.original_idempotency
        abuse._buckets = self.original_rate_buckets
        views._rate_buckets = abuse._buckets

    @override_settings(PUBLIC_RATE_LIMIT_PER_MINUTE=100)
    def test_rotating_unique_keys_and_clients_remain_bounded(self) -> None:
        for index in range(6):
            response = self.client.post(
                "/api/v1/route-searches",
                data=json.dumps(self.payload),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=f"abuse-key-{index:04d}",
                HTTP_X_CORRELATION_ID=f"abuse-correlation-{index}",
                REMOTE_ADDR=f"192.0.2.{index + 1}",
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(len(views._idempotency), 3)
        self.assertEqual(len(views._rate_buckets), 2)
