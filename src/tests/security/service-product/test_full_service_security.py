from __future__ import annotations

import json
import os
import re
import ssl
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SERVICE_ROOT = REPOSITORY_ROOT / "src/services/service-api"
WEB_ROOT = REPOSITORY_ROOT / "src/apps/web"

sys.path.insert(0, str(SERVICE_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_api.settings")

import django  # noqa: E402

django.setup()

from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from cryptography.fernet import Fernet  # noqa: E402
from identity.artifacts import (  # noqa: E402
    ArtifactIntegrityError,
    EncryptedFilesystemArtifactStore,
)
from identity.data_rights import DataRightsRepository  # noqa: E402
from identity.data_rights_worker import process_data_rights_jobs  # noqa: E402
from identity.lifecycle import export_user_data, hard_delete_user_data, purge_service_data  # noqa: E402
from journeys import views  # noqa: E402
from journeys.abuse import reset_rate_limits  # noqa: E402
from journeys.api_common import token_digest  # noqa: E402
from journeys.contracts import ContractError, LockedFixtures  # noqa: E402
from journeys.coordination import RedisCoordination  # noqa: E402
from journeys.gateway import HttpRoutingGateway, RoutingEnvelope, public_to_private  # noqa: E402
from journeys.http_safety import UpstreamResponseTooLarge, read_bounded_response  # noqa: E402
from journeys.models import (  # noqa: E402
    AnonymousSession,
    DataRightsJob,
    RouteSearch,
    SavedPlace,
    ServiceUser,
)
from journeys.proxy import client_ip  # noqa: E402


def _production_web_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((WEB_ROOT / "src").rglob("*"))
        if path.is_file() and path.suffix in {".ts", ".tsx"} and ".test." not in path.name
    )


def _as_user(client: Client, user: ServiceUser) -> None:
    session = client.session
    session["service_user_id"] = str(user.id)
    session.save()


class FullServiceSecurityTests(TestCase):
    def setUp(self) -> None:
        reset_rate_limits()

    def tearDown(self) -> None:
        reset_rate_limits()

    def test_guest_credential_is_high_entropy_hash_only_and_never_cacheable(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.get("/api/v1/health")
        csrf_token = client.cookies["csrftoken"].value

        response = client.post(
            "/api/v1/guest-sessions",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "no-store")
        token = response.json()["guestToken"]
        self.assertGreaterEqual(len(token), 64)
        stored = AnonymousSession.objects.get()
        self.assertEqual(stored.token_hash, token_digest(token))
        self.assertNotEqual(stored.token_hash, token)
        self.assertNotIn(token, json.dumps(stored.__dict__, default=str))

    def test_authenticated_mutation_rejects_missing_csrf(self) -> None:
        user = ServiceUser.objects.create(email="csrf-owner@example.test")
        client = Client(enforce_csrf_checks=True)
        _as_user(client, user)

        response = client.post(
            "/api/v1/me/saved-places",
            data=json.dumps(
                {
                    "label": "집",
                    "place": {
                        "displayName": "민감 위치",
                        "coordinate": {"lon": 127.1, "lat": 37.4},
                    },
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "FORBIDDEN")
        self.assertEqual(SavedPlace.objects.count(), 0)

    @override_settings(
        CONSENT_DOCUMENT_VERSIONS={
            "SEARCH_HISTORY": "privacy-current",
            "PRECISE_LOCATION": "privacy-current",
            "PRODUCT_ANALYTICS": "privacy-current",
            "ROUTING_FEEDBACK": "privacy-current",
        }
    )
    def test_consent_rejects_client_selected_document_version(self) -> None:
        user = ServiceUser.objects.create(email="consent-security@example.test")
        client = Client(enforce_csrf_checks=False)
        _as_user(client, user)

        stale = client.put(
            "/api/v1/me/consents/SEARCH_HISTORY",
            data=json.dumps({"documentVersion": "client-chosen", "accepted": True}),
            content_type="application/json",
        )
        current = client.put(
            "/api/v1/me/consents/SEARCH_HISTORY",
            data=json.dumps({"documentVersion": "privacy-current", "accepted": True}),
            content_type="application/json",
        )

        self.assertEqual(stale.status_code, 400)
        self.assertEqual(stale.json()["code"], "CONSTRAINT_OUT_OF_RANGE")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["documentVersion"], "privacy-current")

    def test_other_owner_resources_are_hidden_as_not_found(self) -> None:
        owner = ServiceUser.objects.create(email="owner@example.test")
        attacker = ServiceUser.objects.create(email="attacker@example.test")
        place = SavedPlace.objects.create(
            user=owner,
            label="집",
            display_name="민감 위치",
            coordinate={"lon": 127.1, "lat": 37.4},
        )
        now = timezone.now()
        search = RouteSearch.objects.create(
            user=owner,
            origin_coordinate={"lon": 127.1, "lat": 37.4},
            destination_coordinate={"lon": 127.2, "lat": 37.5},
            departure_time=now,
            taxi_budget_max=10_000,
            strict_budget=True,
            constraints={},
            status="PARTIAL",
            routing_request_id="security-owner-search",
            contract_version="1.0",
            save_to_history=False,
            retention_until=now + timedelta(minutes=10),
            expires_at=now + timedelta(minutes=10),
        )
        job = DataRightsJob.objects.create(
            user=owner,
            job_type="EXPORT",
            status="PENDING",
            requested_at=now,
        )
        client = Client(enforce_csrf_checks=False)
        _as_user(client, attacker)

        responses = (
            client.delete(f"/api/v1/me/saved-places/{place.id}"),
            client.get(f"/api/v1/route-searches/{search.id}"),
            client.get(f"/api/v1/me/data-exports/{job.id}"),
        )

        self.assertEqual([response.status_code for response in responses], [404, 404, 404])
        self.assertTrue(SavedPlace.objects.filter(id=place.id, deleted_at__isnull=True).exists())

    def test_routing_request_strips_identity_labels_provider_ids_and_history(self) -> None:
        public = LockedFixtures().get("public_request")
        public["saveToHistory"] = True
        public["origin"]["displayName"] = "집"
        public["origin"]["providerPlaceId"] = "provider-secret-id"
        public["destination"]["displayName"] = "직장"
        public["destination"]["providerPlaceId"] = "provider-secret-id-2"

        private = public_to_private(
            public,
            RoutingEnvelope(
                correlation_id="security-correlation",
                idempotency_key="security-idempotency",
                request_deadline="2026-08-23T05:00:00+00:00",
            ),
        )
        serialized = json.dumps(private, ensure_ascii=False, sort_keys=True)

        for forbidden in (
            "집",
            "직장",
            "displayName",
            "providerPlaceId",
            "saveToHistory",
            "userId",
            "email",
            "guestToken",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(private["origin"]["coordinate"], public["origin"]["coordinate"])

    def test_export_primitive_excludes_auth_secrets_and_uses_internal_artifact_reference(self) -> None:
        user = ServiceUser.objects.create(
            email="export-security@example.test",
            password_hash="must-never-leave-service",
        )
        SavedPlace.objects.create(
            user=user,
            label="집",
            display_name="민감 위치",
            coordinate={"lon": 127.1, "lat": 37.4},
        )
        now = timezone.now()
        job = DataRightsRepository.create(user_id=user.id, job_type="EXPORT", requested_at=now)
        DataRightsRepository.mark_running(job_id=job.id, started_at=now)

        exported = export_user_data(user_id=user.id)
        encoded = json.dumps(exported, ensure_ascii=False, sort_keys=True)
        DataRightsRepository.complete_export(
            job_id=job.id,
            artifact_ref="exports/encrypted/security-object",
            download_expires_at=now + timedelta(minutes=5),
            completed_at=now,
        )
        job.refresh_from_db()

        self.assertIn("민감 위치", encoded)
        self.assertNotIn("must-never-leave-service", encoded)
        self.assertNotIn("password_hash", encoded)
        self.assertNotIn("token_hash", encoded)
        self.assertEqual(job.status, "COMPLETE")
        self.assertFalse(job.artifact_ref.startswith(("http://", "https://")))

    def test_export_worker_encrypts_location_payload_and_rejects_artifact_path_escape(self) -> None:
        user = ServiceUser.objects.create(
            email="encrypted-export@example.test",
            password_hash="never-export-this-password-hash",
        )
        SavedPlace.objects.create(
            user=user,
            label="집",
            display_name="암호화할 민감 위치",
            coordinate={"lon": 127.123456, "lat": 37.456789},
        )
        job = DataRightsRepository.create(user_id=user.id, job_type="EXPORT")

        with tempfile.TemporaryDirectory() as directory:
            store = EncryptedFilesystemArtifactStore(
                directory=directory,
                encryption_key=Fernet.generate_key().decode("ascii"),
            )
            report = process_data_rights_jobs(limit=1, artifact_store=store)
            job.refresh_from_db()
            artifact_path = Path(directory) / job.artifact_ref.removeprefix("fernet-file:")
            ciphertext = artifact_path.read_bytes()

            self.assertEqual(report.exports_completed, 1)
            self.assertEqual(job.status, "COMPLETE")
            self.assertNotIn("암호화할 민감 위치".encode(), ciphertext)
            self.assertNotIn(b"127.123456", ciphertext)
            self.assertNotIn(b"never-export-this-password-hash", ciphertext)
            self.assertEqual(store.read(artifact_ref=job.artifact_ref)["savedPlaces"][0]["label"], "집")
            with self.assertRaises(ArtifactIntegrityError):
                store.read(artifact_ref="fernet-file:../../etc/passwd")

            purge = purge_service_data(
                now=job.download_expires_at,
                artifact_store=store,
            )
            job.refresh_from_db()
            self.assertEqual(purge.expired_export_artifacts, 1)
            self.assertFalse(artifact_path.exists())
            self.assertIsNone(job.artifact_ref)
            self.assertIsNone(job.download_expires_at)

    def test_hard_delete_primitive_cascades_exact_location_data(self) -> None:
        user = ServiceUser.objects.create(email="delete-security@example.test")
        place = SavedPlace.objects.create(
            user=user,
            label="집",
            display_name="삭제할 민감 위치",
            coordinate={"lon": 127.1, "lat": 37.4},
        )

        deleted = hard_delete_user_data(user_id=user.id)

        self.assertTrue(deleted)
        self.assertFalse(ServiceUser.objects.filter(id=user.id).exists())
        self.assertFalse(SavedPlace.objects.filter(id=place.id).exists())

    def test_pwa_cache_is_same_origin_get_only_and_never_handles_api(self) -> None:
        worker = (WEB_ROOT / "public/sw.js").read_text(encoding="utf-8")

        self.assertIn('request.method !== "GET"', worker)
        self.assertIn("url.origin !== self.location.origin", worker)
        self.assertIn('url.pathname.startsWith("/api/")', worker)
        self.assertNotRegex(worker, re.compile(r"cache\.(?:put|add)\([^\n]*\/api\/"))
        for sensitive_store in ("indexedDB", "localStorage", "sessionStorage"):
            self.assertNotIn(sensitive_store, worker)

    def test_map_geometry_decoders_bound_work_and_validate_coordinates(self) -> None:
        decoder = (WEB_ROOT / "src/features/route-map/polyline.ts").read_text(encoding="utf-8")

        self.assertIn("MAX_ENCODED_LENGTH = 100_000", decoder)
        self.assertIn("MAX_GEOMETRY_POINTS = 10_000", decoder)
        self.assertIn("MAX_GEOJSON_DEPTH", decoder)
        self.assertIn("value.coordinates.length > MAX_GEOMETRY_POINTS", decoder)
        self.assertIn("points.length >= MAX_GEOMETRY_POINTS", decoder)
        self.assertIn("Number.isFinite", decoder)
        self.assertIn("lon < -180", decoder)
        self.assertIn("lat < -90", decoder)

    def test_frontend_has_no_unescaped_html_or_credential_persistence_sink(self) -> None:
        source = _production_web_source()

        for forbidden in (
            "dangerouslySetInnerHTML",
            ".innerHTML",
            "localStorage.setItem",
            "sessionStorage.setItem",
            "indexedDB.open",
            "document.write",
            "eval(",
            "new Function",
            "/v1/routes/optimize",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotRegex(source, re.compile(r"console\.(?:log|info|warn|error)\s*\("))

    def test_frontend_guest_session_and_retry_key_remain_memory_only(self) -> None:
        session_source = (
            WEB_ROOT / "src/shared/session/sessionMemory.ts"
        ).read_text(encoding="utf-8")
        api_source = (
            WEB_ROOT / "src/shared/api/publicService.ts"
        ).read_text(encoding="utf-8")
        search_source = (
            WEB_ROOT / "src/features/route-search/useRouteSearch.ts"
        ).read_text(encoding="utf-8")

        self.assertIn("let guestToken: string | undefined", session_source)
        self.assertIn("crypto.getRandomValues", api_source)
        self.assertIn("lastAttempt.current = { request, idempotencyKey }", search_source)
        self.assertIn(
            "execute(lastAttempt.current.request, lastAttempt.current.idempotencyKey)",
            search_source,
        )
        for source in (session_source, api_source, search_source):
            self.assertNotIn("localStorage", source)
            self.assertNotIn("sessionStorage", source)
            self.assertNotIn("indexedDB", source)

    def test_routing_idempotency_hmac_does_not_disclose_service_owner(self) -> None:
        owner_key = "USER:00000000-0000-0000-0000-000000000001:public-retry-key"

        opaque = views._routing_idempotency_key(owner_key)

        self.assertRegex(opaque, re.compile(r"^[0-9a-f]{64}$"))
        self.assertNotIn("USER", opaque)
        self.assertNotIn("public-retry-key", opaque)
        self.assertEqual(opaque, views._routing_idempotency_key(owner_key))

    def test_encoded_upstream_body_is_rejected_before_decompression(self) -> None:
        class NeverRead(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError("encoded upstream body must never be consumed")

        request = httpx.Request("GET", "https://provider.example.test/result")
        response = httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=NeverRead(),
            request=request,
        )

        with self.assertRaises(UpstreamResponseTooLarge):
            read_bounded_response(response, max_bytes=1024)

    @override_settings(GUEST_SESSION_RATE_LIMIT_PER_MINUTE=1)
    def test_guest_session_creation_has_scoped_rate_limit(self) -> None:
        client = Client(enforce_csrf_checks=False)

        first = client.post("/api/v1/guest-sessions", REMOTE_ADDR="192.0.2.10")
        second = client.post("/api/v1/guest-sessions", REMOTE_ADDR="192.0.2.10")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "RATE_LIMITED")
        self.assertEqual(second["Retry-After"], "60")

    @override_settings(PLACE_RATE_LIMIT_PER_MINUTE=1)
    def test_place_lookup_has_scoped_rate_limit_and_no_store(self) -> None:
        client = Client(enforce_csrf_checks=False)

        first = client.get("/api/v1/places/suggest", {"query": "판교"}, REMOTE_ADDR="192.0.2.11")
        second = client.get("/api/v1/places/suggest", {"query": "판교"}, REMOTE_ADDR="192.0.2.11")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first["Cache-Control"], "no-store")
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "RATE_LIMITED")
        self.assertEqual(second["Retry-After"], "60")

    @override_settings(PUBLIC_RATE_LIMIT_PER_MINUTE=1)
    def test_route_search_has_scoped_rate_limit(self) -> None:
        views._fixtures = None
        views._gateway = None
        views._idempotency.clear()
        client = Client(enforce_csrf_checks=False)
        payload = LockedFixtures().get("public_request")
        payload["saveToHistory"] = False

        first = client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="security-rate-0001",
            REMOTE_ADDR="192.0.2.12",
        )
        second = client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="security-rate-0002",
            REMOTE_ADDR="192.0.2.12",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "RATE_LIMITED")


class ServiceBoundarySecurityTests(SimpleTestCase):
    @override_settings(
        REDIS_URL="rediss://redis.internal:6379/0",
        REDIS_KEY_PREFIX="security:service",
        REDIS_SOCKET_TIMEOUT_SECONDS=0.1,
    )
    def test_redis_coordination_uses_certificate_and_hostname_verification(self) -> None:
        backend = RedisCoordination.from_settings()
        connection = backend._client.connection_pool.make_connection()

        self.assertEqual(connection.cert_reqs, ssl.CERT_REQUIRED)
        self.assertTrue(connection.check_hostname)

    @override_settings(TRUST_PROXY_HEADERS=False, TRUSTED_PROXY_IPS=())
    def test_untrusted_forwarded_address_cannot_spoof_rate_limit_identity(self) -> None:
        request = RequestFactory().get(
            "/api/v1/places/suggest",
            REMOTE_ADDR="198.51.100.10",
            HTTP_X_FORWARDED_FOR="203.0.113.99",
        )

        self.assertEqual(client_ip(request), "198.51.100.10")

    @override_settings(TRUST_PROXY_HEADERS=True, TRUSTED_PROXY_IPS=("10.82.0.0/16",))
    def test_trusted_proxy_cidr_uses_nearest_untrusted_address(self) -> None:
        request = RequestFactory().get(
            "/api/v1/places/suggest",
            REMOTE_ADDR="10.82.1.10",
            HTTP_X_FORWARDED_FOR="192.0.2.44, 10.82.2.20",
        )

        self.assertEqual(client_ip(request), "192.0.2.44")

    @override_settings(ENVIRONMENT="production", ROUTING_API_ALLOWED_HOSTS=("routing.internal",))
    def test_http_routing_gateway_rejects_ssrf_capable_origins(self) -> None:
        rejected = (
            "http://routing.internal",
            "https://routing.internal.evil.example",
            "https://user:secret@routing.internal",
            "https://routing.internal/v1",
            "https://routing.internal?target=evil",
            "file:///etc/passwd",
        )

        for base_url in rejected:
            with self.subTest(base_url=base_url), self.settings(ROUTING_API_BASE_URL=base_url):
                with self.assertRaises(ContractError):
                    HttpRoutingGateway._validated_base_url()

        with self.settings(ROUTING_API_BASE_URL="https://Routing.Internal./"):
            self.assertEqual(HttpRoutingGateway._validated_base_url(), "https://routing.internal")

    def test_provider_adapters_do_not_follow_redirects_or_accept_dynamic_origins(self) -> None:
        routing_gateway = (SERVICE_ROOT / "journeys/gateway.py").read_text(encoding="utf-8")
        place_adapter = (SERVICE_ROOT / "places/adapter.py").read_text(encoding="utf-8")
        settings_source = (SERVICE_ROOT / "service_api/settings.py").read_text(encoding="utf-8")

        self.assertIn("follow_redirects=False", routing_gateway)
        self.assertIn("ROUTING_API_ALLOWED_HOSTS", routing_gateway)
        self.assertIn("follow_redirects=False", place_adapter)
        self.assertIn('KAKAO_LOCAL_BASE_URL = "https://dapi.kakao.com"', settings_source)

    def test_location_bearing_requests_are_excluded_from_access_logs(self) -> None:
        dockerfile = (REPOSITORY_ROOT / "src/infra/docker/service-api/Dockerfile").read_text(encoding="utf-8")
        nginx = (REPOSITORY_ROOT / "src/infra/docker/web/default.conf.template").read_text(encoding="utf-8")
        terraform = (
            REPOSITORY_ROOT / "src/infra/terraform/modules/service-platform/main.tf"
        ).read_text(encoding="utf-8")

        self.assertIn('"--access-logfile", "/dev/null"', dockerfile)
        api_location = nginx.split("location /api/", 1)[1].split("}", 1)[0]
        self.assertIn("access_log off", api_location)
        self.assertNotIn("access_logs {", terraform)
        self.assertIn("query_string {}", terraform)
        self.assertNotIn("sampled_requests_enabled   = true", terraform)

    def test_edge_and_task_defense_in_depth_controls_are_declared(self) -> None:
        terraform = (
            REPOSITORY_ROOT / "src/infra/terraform/modules/service-platform/main.tf"
        ).read_text(encoding="utf-8")

        for expected in (
            '"place-ip-rate-limit"',
            '"guest-session-ip-rate-limit"',
            '"route-search-ip-rate-limit"',
            'name = "SERVICE_ROUTING_API_ALLOWED_HOSTS"',
            'name = "SERVICE_TRUST_PROXY_HEADERS"',
            'name = "SERVICE_TRUSTED_PROXY_IPS"',
            "aws_lb.service.dns_name",
            "storage_encrypted",
            "readonlyRootFilesystem = true",
            'origin_protocol_policy = "https-only"',
            "var.alb_origin_domain_name",
            "var.alb_certificate_arn",
        ):
            self.assertIn(expected, terraform)
