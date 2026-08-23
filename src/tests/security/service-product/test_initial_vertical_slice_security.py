from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SERVICE_ROOT = REPOSITORY_ROOT / "src/services/service-api"
WEB_SOURCE_ROOT = REPOSITORY_ROOT / "src/apps/web/src"
GENERATED_CLIENT_ROOT = REPOSITORY_ROOT / "src/generated/service-client-ts"

sys.path.insert(0, str(SERVICE_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_api.settings")

import django  # noqa: E402

django.setup()

from django.test import Client, TestCase  # noqa: E402

from journeys import views  # noqa: E402
from journeys.contracts import LockedFixtures  # noqa: E402


def _read_sources(root: Path, suffixes: tuple[str, ...]) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in suffixes and ".test." not in path.name
    )


class InitialVerticalSliceSecurityTests(TestCase):
    def setUp(self) -> None:
        views._fixtures = None
        views._gateway = None
        views._idempotency.clear()
        views._rate_buckets.clear()
        self.payload = LockedFixtures().get("public_request")
        self.payload["saveToHistory"] = False

    def test_unsafe_route_search_requires_csrf_and_returns_safe_problem(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.get("/api/v1/health")
        response = client.post(
            "/api/v1/route-searches",
            data=json.dumps(self.payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="security-csrf-0001",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/problem+json")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response.json()["code"], "FORBIDDEN")
        self.assertNotIn("coordinate", response.content.decode("utf-8"))

    def test_csrf_bootstrap_cookie_and_matching_header_complete_the_request(self) -> None:
        client = Client(enforce_csrf_checks=True)
        health = client.get("/api/v1/health")
        csrf_token = client.cookies["csrftoken"].value

        response = client.post(
            "/api/v1/route-searches",
            data=json.dumps(self.payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="security-csrf-0002",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(health.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_oversized_body_is_rejected_without_echoing_sensitive_marker(self) -> None:
        sensitive_marker = "home-exact-location-marker"
        response = Client(enforce_csrf_checks=False).post(
            "/api/v1/route-searches",
            data=json.dumps({"padding": sensitive_marker + ("x" * 70_000)}),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="security-size-0001",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn(sensitive_marker, response.content.decode("utf-8"))

    def test_browser_source_avoids_private_boundaries_and_dangerous_sinks(self) -> None:
        source = _read_sources(WEB_SOURCE_ROOT, (".ts", ".tsx"))

        for forbidden in (
            "dangerouslySetInnerHTML",
            ".innerHTML",
            "localStorage.setItem",
            "sessionStorage.setItem",
            "/v1/routes/optimize",
            "routing.internal",
            "GBIS",
            "KAKAO_MOBILITY",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn('POST("/api/v1/route-searches"', source)

    def test_generated_client_is_same_origin_and_browser_has_no_embedded_secret(self) -> None:
        generated = _read_sources(GENERATED_CLIENT_ROOT, (".ts",))
        web = _read_sources(WEB_SOURCE_ROOT, (".ts", ".tsx"))
        combined = generated + "\n" + web

        self.assertIn('credentials: "same-origin"', generated)
        secret_assignment = re.compile(
            r"(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|private[_-]?key)"
            r"\s*[:=]\s*['\"][^'\"]+['\"]"
        )
        self.assertIsNone(secret_assignment.search(combined))

    def test_web_client_bootstraps_and_forwards_csrf_without_persistence(self) -> None:
        public_client = (WEB_SOURCE_ROOT / "shared/api/publicService.ts").read_text(encoding="utf-8")

        self.assertIn('GET("/api/v1/health"', public_client)
        self.assertIn('return { "X-CSRFToken": token }', public_client)
        self.assertIn('credentials: "same-origin"', public_client)
        self.assertNotIn("localStorage", public_client)
        self.assertNotIn("sessionStorage", public_client)

    def test_runtime_abuse_caches_have_finite_bounds_and_ttls(self) -> None:
        for cache in (views._idempotency, views._rate_buckets):
            self.assertGreater(cache.max_entries, 0)
            self.assertGreater(cache.ttl_seconds, 0)
            self.assertLessEqual(len(cache), cache.max_entries)

    def test_production_cookie_and_transport_defaults_are_declared(self) -> None:
        settings_source = (SERVICE_ROOT / "service_api/settings.py").read_text(encoding="utf-8")

        for expected in (
            "SESSION_COOKIE_HTTPONLY = True",
            'SESSION_COOKIE_SAMESITE = "Lax"',
            'SESSION_COOKIE_SECURE = ENVIRONMENT == "production"',
            'CSRF_COOKIE_SAMESITE = "Lax"',
            'CSRF_COOKIE_SECURE = ENVIRONMENT == "production"',
            'SECURE_SSL_REDIRECT = ENVIRONMENT == "production"',
            'X_FRAME_OPTIONS = "DENY"',
        ):
            self.assertIn(expected, settings_source)


if __name__ == "__main__":
    unittest.main()
