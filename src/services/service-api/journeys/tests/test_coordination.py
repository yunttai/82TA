from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import fakeredis
from django.test import Client, TestCase, override_settings
from redis.exceptions import ConnectionError

from identity.repository import IdentityRepository
from journeys import views
from journeys.contracts import LockedFixtures
from journeys.coordination import (
    RedisCoordination,
    set_redis_coordination_for_tests,
)
from journeys.models import RouteSearch

REDIS_SETTINGS = {
    "COORDINATION_BACKEND": "redis",
    "REDIS_URL": "redis://test.invalid:6379/0",
    "REDIS_KEY_PREFIX": "test:coordination",
    "REDIS_SOCKET_TIMEOUT_SECONDS": 0.1,
    "IDEMPOTENCY_LEASE_SECONDS": 15,
    "IDEMPOTENCY_CACHE_TTL_SECONDS": 600,
    "RATE_LIMIT_CACHE_TTL_SECONDS": 120,
    "PUBLIC_RATE_LIMIT_PER_MINUTE": 60,
}


class BrokenRedis:
    def pipeline(self, *args, **kwargs):
        raise ConnectionError("simulated Redis outage")


@override_settings(**REDIS_SETTINGS)
class RedisCoordinationTests(TestCase):
    def setUp(self) -> None:
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.backend = RedisCoordination(self.redis, prefix="test:coordination")
        set_redis_coordination_for_tests(self.backend)
        views._fixtures = None
        views._gateway = None
        self.addCleanup(set_redis_coordination_for_tests, None)

    def test_rate_limit_is_atomic_across_backend_instances_and_keys_are_opaque(self) -> None:
        other_worker = RedisCoordination(self.redis, prefix="test:coordination")

        self.assertTrue(
            self.backend.enforce_rate_limit(scope="places", subject="198.51.100.50", limit=2)
        )
        self.assertTrue(
            other_worker.enforce_rate_limit(scope="places", subject="198.51.100.50", limit=2)
        )
        self.assertFalse(
            self.backend.enforce_rate_limit(scope="places", subject="198.51.100.50", limit=2)
        )
        keys = [key.decode() if isinstance(key, bytes) else key for key in self.redis.scan_iter()]
        self.assertNotIn("198.51.100.50", json.dumps(keys))
        reversible = hashlib.sha256(b"places:198.51.100.50").hexdigest()
        self.assertNotIn(reversible, json.dumps(keys))

    @override_settings(
        REDIS_URL="rediss://redis.internal:6379/0",
        COORDINATION_HMAC_KEY=b"x" * 32,
    )
    def test_rediss_client_explicitly_requires_certificate_and_hostname_validation(self) -> None:
        with patch("journeys.coordination.redis.Redis.from_url") as from_url:
            RedisCoordination.from_settings()

        _, kwargs = from_url.call_args
        self.assertEqual(kwargs["ssl_cert_reqs"], "required")
        self.assertIs(kwargs["ssl_check_hostname"], True)

    def test_idempotency_claim_is_single_flight_and_replays_completed_response(self) -> None:
        first = self.backend.begin_idempotency(owner_key="USER:secret:key", fingerprint="fingerprint")
        concurrent = RedisCoordination(
            self.redis,
            prefix="test:coordination",
        ).begin_idempotency(owner_key="USER:secret:key", fingerprint="fingerprint")

        self.assertEqual(first.state, "CLAIMED")
        self.assertEqual(concurrent.state, "IN_PROGRESS")
        self.assertTrue(
            self.backend.complete_idempotency(
                owner_key="USER:secret:key",
                fingerprint="fingerprint",
                lease_token=first.lease_token,
                response={"status": "PARTIAL"},
            )
        )
        replay = self.backend.begin_idempotency(
            owner_key="USER:secret:key",
            fingerprint="fingerprint",
        )
        conflict = self.backend.begin_idempotency(
            owner_key="USER:secret:key",
            fingerprint="different",
        )

        self.assertEqual(replay.state, "REPLAY")
        self.assertEqual(replay.response, {"status": "PARTIAL"})
        self.assertEqual(conflict.state, "CONFLICT")
        dump = json.dumps(self.redis.hgetall("unused"), default=str) + json.dumps(
            [
                self.redis.get(key)
                for key in self.redis.scan_iter(match="test:coordination:idempotency:*")
            ]
        )
        self.assertNotIn("USER:secret:key", dump)

    def test_failed_claim_can_be_abandoned_for_immediate_retry(self) -> None:
        claim = self.backend.begin_idempotency(owner_key="GUEST:opaque:key", fingerprint="one")
        self.backend.abandon_idempotency(
            owner_key="GUEST:opaque:key",
            lease_token=claim.lease_token,
        )
        retry = self.backend.begin_idempotency(owner_key="GUEST:opaque:key", fingerprint="one")
        self.assertEqual(retry.state, "CLAIMED")

    @override_settings(GUEST_SESSION_RATE_LIMIT_PER_MINUTE=1)
    def test_redis_outage_fails_closed_with_contract_rate_problem(self) -> None:
        set_redis_coordination_for_tests(
            RedisCoordination(BrokenRedis(), prefix="test:coordination")
        )
        response = Client().post("/api/v1/guest-sessions", REMOTE_ADDR="198.51.100.90")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "RATE_LIMITED")
        self.assertEqual(response["Retry-After"], "60")

    def test_same_public_key_for_two_users_has_distinct_opaque_routing_requests(self) -> None:
        first_user = IdentityRepository.create_user(email="tenant-one@example.test")
        second_user = IdentityRepository.create_user(email="tenant-two@example.test")
        payload = LockedFixtures().get("public_request")
        payload["saveToHistory"] = False

        def authenticated(user):
            client = Client(enforce_csrf_checks=False)
            session = client.session
            session["service_user_id"] = str(user.id)
            session.save()
            return client

        first = authenticated(first_user).post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="shared-public-key",
        )
        second = authenticated(second_user).post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="shared-public-key",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        replay = authenticated(first_user).post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="shared-public-key",
        )
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        request_ids = list(RouteSearch.objects.order_by("created_at").values_list("routing_request_id", flat=True))
        self.assertEqual(len(request_ids), 2)
        self.assertEqual(len(set(request_ids)), 2)
        self.assertNotIn(str(first_user.id), json.dumps(request_ids))
        self.assertNotIn(str(second_user.id), json.dumps(request_ids))
