from __future__ import annotations

import os
import subprocess
import sys
from typing import ClassVar

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from journeys.middleware import TrustedProxyHeadersMiddleware
from journeys.proxy import client_ip


SERVICE_JWT_SECRET = "service-routing-test-secret-7Vq!4xP@9mK#2sL%6wN&8cR"


class ProductionSettingsTests(SimpleTestCase):
    _production_keys: ClassVar[set[str]] = {
        "DATABASE_URL",
        "SERVICE_ENVIRONMENT",
        "SERVICE_SECRET_KEY",
        "SERVICE_ROUTING_GATEWAY",
        "SERVICE_ROUTING_JWT_SECRET",
        "SERVICE_ROUTING_JWT_ISSUER",
        "SERVICE_ROUTING_JWT_AUDIENCE",
        "SERVICE_ROUTING_JWT_TTL_SECONDS",
        "SERVICE_PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS",
        "SERVICE_ROUTING_DEADLINE_MILLISECONDS",
        "SERVICE_ROUTING_API_ALLOWED_HOSTS",
        "SERVICE_CSRF_TRUSTED_ORIGINS",
        "SERVICE_TRUST_PROXY_HEADERS",
        "SERVICE_TRUSTED_PROXY_IPS",
        "SERVICE_CONSENT_DOCUMENT_VERSION",
        "SERVICE_CONSENT_SEARCH_HISTORY_DOCUMENT_VERSION",
        "SERVICE_CONSENT_PRECISE_LOCATION_DOCUMENT_VERSION",
        "SERVICE_CONSENT_PRODUCT_ANALYTICS_DOCUMENT_VERSION",
        "SERVICE_CONSENT_ROUTING_FEEDBACK_DOCUMENT_VERSION",
        "SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND",
        "SERVICE_DATA_RIGHTS_ARTIFACT_DIRECTORY",
        "SERVICE_DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY",
        "SERVICE_REDIS_URL",
        "KAKAO_LOCAL_REST_KEY",
        "SERVICE_RATE_LIMIT_PER_MINUTE",
        "SERVICE_GUEST_SESSION_RATE_LIMIT_PER_MINUTE",
        "SERVICE_PLACE_RATE_LIMIT_PER_MINUTE",
        "SERVICE_RATE_LIMIT_CACHE_TTL_SECONDS",
        "SERVICE_IDEMPOTENCY_CACHE_TTL_SECONDS",
        "SERVICE_IDEMPOTENCY_LEASE_SECONDS",
        "SERVICE_REDIS_KEY_DERIVATION_SECRET",
        "SERVICE_ROUTING_MAX_RESPONSE_BYTES",
        "SERVICE_KAKAO_LOCAL_MAX_RESPONSE_BYTES",
    }

    def _import_settings(self, *, code: str | None = None, **values: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        for key in self._production_keys:
            environment.pop(key, None)
        environment.update(
            {
                "SERVICE_ENVIRONMENT": "production",
                "SERVICE_SECRET_KEY": "production-settings-test-secret-abcdefghijklmnopqrstuvwxyz",
                "SERVICE_ROUTING_GATEWAY": "stub",
                "SERVICE_CONSENT_DOCUMENT_VERSION": "privacy-test-current",
                "SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND": "disabled",
                "SERVICE_REDIS_URL": "rediss://redis.internal:6379/0",
                "KAKAO_LOCAL_REST_KEY": "production-kakao-test-key",
                **values,
            }
        )
        return subprocess.run(
            [
                sys.executable,
                "-c",
                code or "import service_api.settings as s; print(s.DATABASES['default']['ENGINE'])",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_production_requires_database_url(self) -> None:
        result = self._import_settings()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL is required in production", result.stderr)

    def test_production_rejects_sqlite_database_url(self) -> None:
        result = self._import_settings(DATABASE_URL="sqlite:///unsafe-production.sqlite3")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must use PostgreSQL", result.stderr)

    def test_production_accepts_postgresql_configuration_without_connecting(self) -> None:
        result = self._import_settings(DATABASE_URL="postgresql://service:secret@db.internal/service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("django.db.backends.postgresql", result.stdout)

    def test_production_requires_tls_redis_coordination(self) -> None:
        missing = self._import_settings(
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_REDIS_URL="",
        )
        insecure = self._import_settings(
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_REDIS_URL="redis://redis.internal:6379/0",
        )

        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("SERVICE_REDIS_URL is required in production", missing.stderr)
        self.assertNotEqual(insecure.returncode, 0)
        self.assertIn("production requires rediss", insecure.stderr)

    def test_production_rejects_redis_tls_verification_query_overrides(self) -> None:
        result = self._import_settings(
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_REDIS_URL="rediss://redis.internal:6379/0?ssl_cert_reqs=none",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("valid private Redis URL", result.stderr)

    def test_production_rejects_weak_secrets_and_invalid_upstream_limits(self) -> None:
        common = {"DATABASE_URL": "postgresql://service:secret@db.internal/service"}
        weak_service = self._import_settings(**common, SERVICE_SECRET_KEY="too-short")
        weak_derivation = self._import_settings(
            **common,
            SERVICE_REDIS_KEY_DERIVATION_SECRET="too-short",
        )
        routing_limit = self._import_settings(**common, SERVICE_ROUTING_MAX_RESPONSE_BYTES="512")
        kakao_limit = self._import_settings(**common, SERVICE_KAKAO_LOCAL_MAX_RESPONSE_BYTES="512")

        self.assertNotEqual(weak_service.returncode, 0)
        self.assertIn("at least 32 characters", weak_service.stderr)
        self.assertNotEqual(weak_derivation.returncode, 0)
        self.assertIn("KEY_DERIVATION_SECRET", weak_derivation.stderr)
        self.assertNotEqual(routing_limit.returncode, 0)
        self.assertIn("ROUTING_MAX_RESPONSE_BYTES", routing_limit.stderr)
        self.assertNotEqual(kakao_limit.returncode, 0)
        self.assertIn("KAKAO_LOCAL_MAX_RESPONSE_BYTES", kakao_limit.stderr)

    def test_production_requires_kakao_local_capability_key(self) -> None:
        result = self._import_settings(
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            KAKAO_LOCAL_REST_KEY="",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("KAKAO_LOCAL_REST_KEY is required in production", result.stderr)

    def test_http_gateway_requires_strong_short_lived_service_jwt_and_deadline_margin(self) -> None:
        common = {
            "DATABASE_URL": "postgresql://service:secret@db.internal/service",
            "SERVICE_ROUTING_GATEWAY": "http",
            "SERVICE_ROUTING_API_ALLOWED_HOSTS": "routing.internal",
            "SERVICE_ROUTING_JWT_ISSUER": "service-api",
            "SERVICE_ROUTING_JWT_AUDIENCE": "routing-api",
        }
        missing = self._import_settings(**common)
        weak = self._import_settings(**common, SERVICE_ROUTING_JWT_SECRET="x" * 32)
        missing_identity = self._import_settings(
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_ROUTING_GATEWAY="http",
            SERVICE_ROUTING_API_ALLOWED_HOSTS="routing.internal",
            SERVICE_ROUTING_JWT_SECRET=SERVICE_JWT_SECRET,
        )
        invalid_ttl = self._import_settings(
            **common,
            SERVICE_ROUTING_JWT_SECRET=SERVICE_JWT_SECRET,
            SERVICE_ROUTING_JWT_TTL_SECONDS="301",
        )
        missing_margin = self._import_settings(
            **common,
            SERVICE_ROUTING_JWT_SECRET=SERVICE_JWT_SECRET,
            SERVICE_PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS="6500",
            SERVICE_ROUTING_DEADLINE_MILLISECONDS="6200",
        )
        oversized_routing_deadline = self._import_settings(
            **common,
            SERVICE_ROUTING_JWT_SECRET=SERVICE_JWT_SECRET,
            SERVICE_PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS="7000",
            SERVICE_ROUTING_DEADLINE_MILLISECONDS="6600",
        )
        oversized_public_budget = self._import_settings(
            **common,
            SERVICE_ROUTING_JWT_SECRET=SERVICE_JWT_SECRET,
            SERVICE_PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS="7001",
            SERVICE_ROUTING_DEADLINE_MILLISECONDS="6500",
        )

        self.assertIn("explicit strong secret", missing.stderr)
        self.assertIn("explicit strong secret", weak.stderr)
        self.assertIn("issuer and audience must be explicit", missing_identity.stderr)
        self.assertIn("TTL_SECONDS", invalid_ttl.stderr)
        self.assertIn("at least 500ms", missing_margin.stderr)
        self.assertIn("between 1 and 6500", oversized_routing_deadline.stderr)
        self.assertIn("between 1 and 7000", oversized_public_budget.stderr)

    def test_production_rejects_disabled_rate_limits_and_short_coordination_ttls(self) -> None:
        common = {"DATABASE_URL": "postgresql://service:secret@db.internal/service"}
        disabled = self._import_settings(**common, SERVICE_RATE_LIMIT_PER_MINUTE="0")
        short_rate = self._import_settings(**common, SERVICE_RATE_LIMIT_CACHE_TTL_SECONDS="59")
        short_idempotency = self._import_settings(
            **common,
            SERVICE_IDEMPOTENCY_LEASE_SECONDS="15",
            SERVICE_IDEMPOTENCY_CACHE_TTL_SECONDS="15",
        )

        self.assertNotEqual(disabled.returncode, 0)
        self.assertIn("rate limits must be positive", disabled.stderr)
        self.assertNotEqual(short_rate.returncode, 0)
        self.assertIn("must cover the one-minute rate window", short_rate.stderr)
        self.assertNotEqual(short_idempotency.returncode, 0)
        self.assertIn("must exceed the lease duration", short_idempotency.stderr)

    def test_production_requires_current_consent_document_versions(self) -> None:
        result = self._import_settings(
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_CONSENT_DOCUMENT_VERSION="",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("current consent document version is required in production", result.stderr)

    def test_per_purpose_consent_version_overrides_common_version(self) -> None:
        result = self._import_settings(
            code=(
                "import service_api.settings as s; "
                "print(s.CONSENT_DOCUMENT_VERSIONS['SEARCH_HISTORY']); "
                "print(s.CONSENT_DOCUMENT_VERSIONS['ROUTING_FEEDBACK'])"
            ),
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_CONSENT_DOCUMENT_VERSION="privacy-common",
            SERVICE_CONSENT_SEARCH_HISTORY_DOCUMENT_VERSION="privacy-search-v2",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["privacy-search-v2", "privacy-common"])

    def test_production_requires_explicit_data_rights_artifact_backend(self) -> None:
        result = self._import_settings(
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND="",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ARTIFACT_BACKEND is required in production", result.stderr)

    def test_encrypted_artifact_backend_requires_private_storage_configuration(self) -> None:
        result = self._import_settings(
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND="encrypted-filesystem",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ARTIFACT_DIRECTORY is required", result.stderr)

    def test_production_rejects_invalid_trusted_proxy_cidr(self) -> None:
        result = self._import_settings(
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_TRUST_PROXY_HEADERS="true",
            SERVICE_TRUSTED_PROXY_IPS="not-a-network",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid IP address or CIDR", result.stderr)

    def test_csrf_trusted_origins_are_normalized_https_origins(self) -> None:
        result = self._import_settings(
            code="import service_api.settings as s; print('|'.join(s.CSRF_TRUSTED_ORIGINS))",
            DATABASE_URL="postgresql://service:secret@db.internal/service",
            SERVICE_CSRF_TRUSTED_ORIGINS="https://APP.example.test/,https://mobile.example.test:8443",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("https://app.example.test|https://mobile.example.test:8443", result.stdout)

    def test_production_rejects_unsafe_csrf_trusted_origins(self) -> None:
        for origin in (
            "http://app.example.test",
            "https://user:password@app.example.test",
            "https://app.example.test/path",
            "https://app.example.test?next=attacker",
        ):
            with self.subTest(origin=origin):
                result = self._import_settings(
                    DATABASE_URL="postgresql://service:secret@db.internal/service",
                    SERVICE_CSRF_TRUSTED_ORIGINS=origin,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("HTTPS origins only", result.stderr)


class TrustedProxyPolicyTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    @override_settings(TRUST_PROXY_HEADERS=False, TRUSTED_PROXY_IPS=())
    def test_forwarded_for_is_ignored_by_default(self) -> None:
        request = self.factory.get(
            "/",
            REMOTE_ADDR="198.51.100.30",
            HTTP_X_FORWARDED_FOR="203.0.113.99",
        )
        self.assertEqual(client_ip(request), "198.51.100.30")

    @override_settings(TRUST_PROXY_HEADERS=True, TRUSTED_PROXY_IPS=("10.0.0.0/24",))
    def test_trusted_proxy_cidr_uses_nearest_untrusted_client_and_ignores_spoof(self) -> None:
        request = self.factory.get(
            "/",
            REMOTE_ADDR="10.0.0.5",
            HTTP_X_FORWARDED_FOR="192.0.2.99, 198.51.100.31",
        )
        self.assertEqual(client_ip(request), "198.51.100.31")

    @override_settings(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_IPS=("10.0.0.0/24", "203.0.113.0/24"),
    )
    def test_alb_cloudfront_chain_ignores_forged_leftmost_value(self) -> None:
        request = self.factory.get(
            "/",
            REMOTE_ADDR="10.0.0.5",
            HTTP_X_FORWARDED_FOR="192.0.2.250, 198.51.100.31, 203.0.113.8",
        )
        self.assertEqual(client_ip(request), "198.51.100.31")

    def test_proxy_resolver_accepts_managed_cloudfront_cidr_set(self) -> None:
        managed_ranges = tuple(f"100.64.{index}.0/24" for index in range(55))
        with override_settings(
            TRUST_PROXY_HEADERS=True,
            TRUSTED_PROXY_IPS=("10.0.0.0/24", *managed_ranges),
        ):
            request = self.factory.get(
                "/",
                REMOTE_ADDR="10.0.0.5",
                HTTP_X_FORWARDED_FOR="198.51.100.32, 100.64.54.7",
            )
            self.assertEqual(client_ip(request), "198.51.100.32")

    @override_settings(TRUST_PROXY_HEADERS=True, TRUSTED_PROXY_IPS=("2001:db8:1::/64",))
    def test_ipv6_trusted_proxy_chain_is_supported(self) -> None:
        request = self.factory.get(
            "/",
            REMOTE_ADDR="2001:db8:1::5",
            HTTP_X_FORWARDED_FOR="2001:db8:ffff::42, 2001:db8:1::8",
        )
        self.assertEqual(client_ip(request), "2001:db8:ffff::42")

    @override_settings(TRUST_PROXY_HEADERS=True, TRUSTED_PROXY_IPS=("10.0.0.0/24",))
    def test_untrusted_peer_cannot_spoof_forwarded_for(self) -> None:
        request = self.factory.get(
            "/",
            REMOTE_ADDR="198.51.100.40",
            HTTP_X_FORWARDED_FOR="203.0.113.40",
        )
        self.assertEqual(client_ip(request), "198.51.100.40")

    @override_settings(TRUST_PROXY_HEADERS=True, TRUSTED_PROXY_IPS=("invalid",))
    def test_invalid_development_proxy_configuration_trusts_nobody(self) -> None:
        request = self.factory.get(
            "/",
            REMOTE_ADDR="198.51.100.41",
            HTTP_X_FORWARDED_FOR="203.0.113.41",
        )
        self.assertEqual(client_ip(request), "198.51.100.41")

    @override_settings(TRUST_PROXY_HEADERS=True, TRUSTED_PROXY_IPS=("10.0.0.0/24",))
    def test_middleware_strips_forwarding_headers_from_untrusted_peer(self) -> None:
        request = self.factory.get(
            "/",
            REMOTE_ADDR="198.51.100.42",
            HTTP_X_FORWARDED_FOR="203.0.113.42",
            HTTP_X_FORWARDED_PROTO="https",
        )
        middleware = TrustedProxyHeadersMiddleware(lambda received: HttpResponse(str(received.META)))
        middleware(request)
        self.assertNotIn("HTTP_X_FORWARDED_FOR", request.META)
        self.assertNotIn("HTTP_X_FORWARDED_PROTO", request.META)

    @override_settings(TRUST_PROXY_HEADERS=True, TRUSTED_PROXY_IPS=("10.0.0.0/24",))
    def test_middleware_preserves_forwarding_headers_from_trusted_peer(self) -> None:
        request = self.factory.get(
            "/",
            REMOTE_ADDR="10.0.0.5",
            HTTP_X_FORWARDED_FOR="198.51.100.43",
            HTTP_X_FORWARDED_PROTO="https",
        )
        middleware = TrustedProxyHeadersMiddleware(lambda received: HttpResponse(str(received.META)))
        middleware(request)
        self.assertEqual(request.META["HTTP_X_FORWARDED_FOR"], "198.51.100.43")
        self.assertEqual(request.META["HTTP_X_FORWARDED_PROTO"], "https")
