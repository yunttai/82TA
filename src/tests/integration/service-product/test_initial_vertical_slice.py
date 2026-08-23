from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SERVICE_ROOT = REPOSITORY_ROOT / "src/services/service-api"
sys.path.insert(0, str(SERVICE_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_api.settings")

import django  # noqa: E402


django.setup()

from django.test import Client, TestCase, override_settings  # noqa: E402

from journeys import views  # noqa: E402
from journeys.contracts import CanonicalContracts, LockedFixtures  # noqa: E402
from journeys.gateway import ReplayRoutingGateway, StubRoutingGateway  # noqa: E402


class InitialVerticalSliceIntegrationTests(TestCase):
    def setUp(self) -> None:
        views._fixtures = None
        views._gateway = None
        views._idempotency.clear()
        views._rate_buckets.clear()
        self.fixtures = LockedFixtures()

    def csrf_client(self) -> tuple[Client, str]:
        client = Client(enforce_csrf_checks=True)
        health = client.get("/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertIn("csrftoken", client.cookies)
        return client, client.cookies["csrftoken"].value

    def post(self, client: Client, csrf_token: str, payload: dict, key: str):
        return client.post(
            "/api/v1/route-searches",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            HTTP_X_CORRELATION_ID=f"qa-{key}",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

    @override_settings(ROUTING_GATEWAY_MODE="stub")
    def test_browser_shaped_request_reaches_canonical_stub_and_returns_partial(self) -> None:
        payload = {
            "origin": {
                "displayName": "명지대학교 자연캠퍼스",
                "coordinate": {"lon": 127.187456, "lat": 37.222345},
            },
            "destination": {
                "displayName": "판교역",
                "coordinate": {"lon": 127.111159, "lat": 37.394761},
            },
            "departure": {
                "type": "DEPART_AT",
                "time": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            },
            "arrivalDeadline": None,
            "taxiBudget": {"currency": "KRW", "maxAmount": 10000, "strict": True},
            "preferences": {
                "maxWalkSeconds": 900,
                "maxTransfers": 3,
                "maxTaxiLegs": 2,
                "allowTaxiBridge": True,
                "avoidHighBusSeatRisk": False,
                "optimization": "BALANCED",
                "accessibility": {"avoidStairs": False, "wheelchair": False},
            },
            "requestedRecommendations": [
                "FASTEST",
                "STABLE",
                "EFFICIENT",
                "PUBLIC_TRANSIT_ONLY",
            ],
            "saveToHistory": False,
        }

        client, csrf_token = self.csrf_client()
        response = self.post(client, csrf_token, payload, "stub-key-0001")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(views._gateway, StubRoutingGateway)
        self.assertEqual(body["status"], "PARTIAL")
        self.assertEqual(body["recommendations"], {
            "fastest": None,
            "stable": None,
            "efficient": None,
            "publicTransitOnly": None,
        })
        self.assertEqual(body["warnings"], ["PROVIDER_PARTIAL_FAILURE"])
        self.assertEqual(
            CanonicalContracts().validate("public", "PublicRouteSearchResponse", body),
            [],
        )

    @override_settings(ROUTING_GATEWAY_MODE="replay")
    def test_locked_public_request_replays_private_fixture_and_safe_projection(self) -> None:
        client, csrf_token = self.csrf_client()
        payload = self.fixtures.get("public_request")
        # The canonical request demonstrates the authenticated history opt-in.
        # This guest replay verifies the same Routing payload without attempting
        # to persist account history, which is a Service-local concern.
        payload["saveToHistory"] = False
        response = self.post(
            client,
            csrf_token,
            payload,
            "replay-key-0001",
        )
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(views._gateway, ReplayRoutingGateway)
        forwarded_request = views._gateway.last_forwarded_request
        self.assertEqual(
            CanonicalContracts().validate("private", "OptimizeRouteRequest", forwarded_request),
            [],
        )
        self.assertEqual(
            forwarded_request["origin"]["coordinate"],
            payload["origin"]["coordinate"],
        )
        self.assertEqual(
            forwarded_request["destination"]["coordinate"],
            payload["destination"]["coordinate"],
        )
        self.assertEqual(forwarded_request["departureTime"], payload["departure"]["time"])
        self.assertRegex(body["searchId"], r"^[0-9a-f-]{36}$")
        self.assertEqual(body["status"], "PARTIAL")
        self.assertNotIn("providerStatus", body)
        self.assertNotIn("modelVersions", body)
        self.assertNotIn("computation", body)

        forwarded = json.dumps(views._gateway.last_forwarded_request)
        for forbidden in (
            "displayName",
            "providerPlaceId",
            "saveToHistory",
            "userId",
            "email",
            "guestToken",
        ):
            self.assertNotIn(forbidden, forwarded)

    def test_react_uses_generated_public_client_and_never_private_routing(self) -> None:
        web_source = REPOSITORY_ROOT / "src/apps/web/src"
        api_source = (web_source / "shared/api/publicService.ts").read_text(encoding="utf-8")
        all_web_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(web_source.rglob("*"))
            if path.suffix in {".ts", ".tsx"}
        )

        self.assertIn('from "@82ta/service-client"', api_source)
        self.assertIn('GET("/api/v1/health"', api_source)
        self.assertIn('POST("/api/v1/route-searches"', api_source)
        self.assertIn('"X-CSRFToken"', api_source)
        self.assertNotIn("/v1/routes/optimize", all_web_source)
        self.assertNotIn("routing.internal", all_web_source)
        self.assertNotIn("GBIS", all_web_source)
        self.assertNotIn("KAKAO_MOBILITY", all_web_source)

    def test_generated_statuses_have_reachable_react_render_branches(self) -> None:
        generated_schema = (
            REPOSITORY_ROOT / "src/generated/service-client-ts/schema.gen.ts"
        ).read_text(encoding="utf-8")
        hook = (
            REPOSITORY_ROOT
            / "src/apps/web/src/features/route-search/useRouteSearch.ts"
        ).read_text(encoding="utf-8")
        panel = (
            REPOSITORY_ROOT
            / "src/apps/web/src/features/route-results/ResultPanel.tsx"
        ).read_text(encoding="utf-8")

        statuses = (
            "COMPLETE",
            "PARTIAL",
            "NO_FEASIBLE_ROUTE",
            "PROVIDER_UNAVAILABLE",
            "FAILED",
            "EXPIRED",
        )
        for status in statuses:
            self.assertIn(f'"{status}"', generated_schema)

        # COMPLETE is the normal typed response branch; the other states have
        # explicit banners or terminal branches.
        self.assertIn("phase: ResponsePhase", hook)
        self.assertIn("phase: responsePhase(data)", hook)
        for explicit_status in statuses[1:]:
            self.assertIn(explicit_status, hook + panel)


if __name__ == "__main__":
    import unittest

    unittest.main()
