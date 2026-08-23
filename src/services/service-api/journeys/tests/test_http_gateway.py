from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
from django.test import SimpleTestCase, override_settings

from journeys.contracts import CanonicalContracts, ContractError, LockedFixtures
from journeys.gateway import (
    HttpRoutingGateway,
    RoutingEnvelope,
    RoutingGatewayError,
    public_to_private,
)
from journeys.projection import project_public_response


class HttpRoutingGatewayTests(SimpleTestCase):
    def test_translation_is_contract_valid_and_drops_service_only_fields(self) -> None:
        public = LockedFixtures().get("public_request")
        private = public_to_private(
            public,
            RoutingEnvelope("correlation", "idempotency-key", "2026-08-23T00:00:00+00:00"),
        )
        encoded = json.dumps(private)
        self.assertEqual(private["contractVersion"], "1.0")
        self.assertEqual(private["preference"]["avoidHighBusSeatRisk"], False)
        self.assertNotIn("displayName", encoded)
        self.assertNotIn("providerPlaceId", encoded)
        self.assertNotIn("saveToHistory", encoded)

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_TOKEN="service-token",
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
    )
    def test_generated_client_forwards_auth_deadline_idempotency_and_correlation(self) -> None:
        fixtures = LockedFixtures()
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = request.headers
            seen["body"] = json.loads(request.content)
            response = fixtures.get("routing_response")
            response["requestId"] = seen["body"]["requestId"]
            return httpx.Response(200, json=response)

        gateway = HttpRoutingGateway()
        gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
        deadline = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
        response = gateway.optimize(
            fixtures.get("public_request"),
            RoutingEnvelope("corr-http", "idempotency-http", deadline),
        )

        self.assertEqual(response["status"], "PARTIAL")
        self.assertEqual(seen["headers"]["authorization"], "Bearer service-token")
        self.assertEqual(seen["headers"]["x-correlation-id"], "corr-http")
        self.assertEqual(seen["headers"]["x-request-deadline"], deadline)
        self.assertEqual(seen["headers"]["idempotency-key"], "idempotency-http")
        self.assertEqual(seen["headers"]["accept-encoding"], "identity")

    @override_settings(
        ENVIRONMENT="production",
        ROUTING_SERVICE_TOKEN="service-token",
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
    )
    def test_production_base_url_is_fail_closed_before_client_construction(self) -> None:
        rejected = [
            "http://routing.internal",
            "https://attacker.invalid",
            "https://user:password@routing.internal",
            "https://routing.internal/private",
            "https://routing.internal?redirect=https://attacker.invalid",
            "https://routing.internal#fragment",
        ]
        for value in rejected:
            with (
                self.subTest(value=value),
                override_settings(ROUTING_API_BASE_URL=value),
                self.assertRaises(ContractError),
            ):
                HttpRoutingGateway()

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_TOKEN="service-token",
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
    )
    def test_optimize_malformed_json_and_unexpected_status_are_safe_502(self) -> None:
        fixtures = LockedFixtures()
        envelope = RoutingEnvelope("corr-bad", "idempotency-bad", "2026-08-23T00:00:00+00:00")
        for response in (
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, json={"status": "COMPLETE"}),
            httpx.Response(418, json={"detail": "internal secret must not escape"}),
            httpx.Response(302, headers={"Location": "https://attacker.invalid/steal"}),
        ):
            with self.subTest(status=response.status_code):
                gateway = HttpRoutingGateway()
                requests = []

                def handler(
                    request: httpx.Request,
                    response=response,
                    requests=requests,
                ) -> httpx.Response:
                    requests.append(str(request.url))
                    return response

                gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
                with self.assertRaises(RoutingGatewayError) as raised:
                    gateway.optimize(fixtures.get("public_request"), envelope)
                self.assertEqual((raised.exception.status, raised.exception.code), (502, "PROVIDER_BAD_RESPONSE"))
                self.assertEqual(len(requests), 1)
                self.assertTrue(requests[0].startswith("https://routing.internal/"))

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_TOKEN="service-token",
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
        ROUTING_MAX_RESPONSE_BYTES=1024,
    )
    def test_routing_response_declared_over_limit_is_rejected_without_reading(self) -> None:
        class NeverRead(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError("oversized declared response must not be consumed")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"Content-Length": "1025"},
                stream=NeverRead(),
            )

        gateway = HttpRoutingGateway()
        gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
        with self.assertRaises(RoutingGatewayError) as raised:
            gateway.optimize(
                LockedFixtures().get("public_request"),
                RoutingEnvelope("corr-size", "idempotency-size", "2026-08-23T00:00:00+00:00"),
            )
        self.assertEqual((raised.exception.status, raised.exception.code), (502, "PROVIDER_BAD_RESPONSE"))

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_TOKEN="service-token",
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
        ROUTING_MAX_RESPONSE_BYTES=1024,
    )
    def test_chunked_oversized_routing_error_and_capabilities_are_bounded(self) -> None:
        class OversizedChunks(httpx.SyncByteStream):
            def __iter__(self):
                yield b"x" * 800
                yield b"y" * 300

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, stream=OversizedChunks())

        gateway = HttpRoutingGateway()
        gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
        with self.assertRaises(RoutingGatewayError) as raised:
            gateway.optimize(
                LockedFixtures().get("public_request"),
                RoutingEnvelope("corr-chunk", "idempotency-chunk", "2026-08-23T00:00:00+00:00"),
            )
        self.assertEqual((raised.exception.status, raised.exception.code), (502, "PROVIDER_BAD_RESPONSE"))

        capabilities = HttpRoutingGateway()
        capabilities.client._httpx_args["transport"] = httpx.MockTransport(handler)
        degraded = capabilities.capabilities()
        self.assertEqual(degraded["busIntelligenceCoverage"], "UNKNOWN")

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_TOKEN="service-token",
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
        ROUTING_MAX_RESPONSE_BYTES=1024,
    )
    def test_compressed_routing_response_is_rejected_before_body_read(self) -> None:
        class NeverReadCompressed(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError("encoded response must not be decompressed or consumed")

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["Accept-Encoding"], "identity")
            return httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                stream=NeverReadCompressed(),
            )

        gateway = HttpRoutingGateway()
        gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
        with self.assertRaises(RoutingGatewayError) as raised:
            gateway.optimize(
                LockedFixtures().get("public_request"),
                RoutingEnvelope("corr-gzip", "idempotency-gzip", "2026-08-23T00:00:00+00:00"),
            )
        self.assertEqual((raised.exception.status, raised.exception.code), (502, "PROVIDER_BAD_RESPONSE"))

        capabilities = HttpRoutingGateway()
        capabilities.client._httpx_args["transport"] = httpx.MockTransport(handler)
        self.assertEqual(capabilities.capabilities()["busIntelligenceCoverage"], "UNKNOWN")

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_TOKEN="service-token",
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
    )
    def test_optimize_rejects_mismatched_request_and_duplicate_route_ids(self) -> None:
        fixtures = LockedFixtures()
        envelope = RoutingEnvelope("corr-boundary", "idempotency-boundary", "2026-08-23T00:00:00+00:00")

        mismatched = fixtures.get("routing_response")
        mismatched["requestId"] = "wrong-request-id"
        duplicate = fixtures.get("routing_response")
        route = {
            "routeId": "duplicate-route",
            "pattern": "TAXI_ONLY",
            "totalDuration": {
                "p50Seconds": 100,
                "p90Seconds": 120,
                "origin": "PROVIDER_ESTIMATE",
                "confidence": {"grade": "LOW", "score": 0.1},
            },
            "taxiCost": {
                "lower": 1000,
                "expected": 2000,
                "upper": 3000,
                "currency": "KRW",
                "origin": "PROVIDER_ESTIMATE",
            },
            "totalFareExpected": 2000,
            "walkSeconds": 0,
            "transferCount": 0,
            "taxiLegCount": 1,
            "reliabilityScore": 0.1,
            "legs": [],
            "reasonCodes": [],
            "warningCodes": [],
        }
        duplicate["routes"] = [route, dict(route)]

        for kind, body in (("mismatch", mismatched), ("duplicate", duplicate)):
            with self.subTest(kind=kind):
                gateway = HttpRoutingGateway()

                def handler(request: httpx.Request, body=body, kind=kind) -> httpx.Response:
                    response_body = json.loads(json.dumps(body))
                    if kind == "duplicate":
                        response_body["requestId"] = json.loads(request.content)["requestId"]
                    return httpx.Response(200, json=response_body)

                gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
                with self.assertRaises(RoutingGatewayError) as raised:
                    gateway.optimize(fixtures.get("public_request"), envelope)
                self.assertEqual((raised.exception.status, raised.exception.code), (502, "PROVIDER_BAD_RESPONSE"))

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_TOKEN="service-token",
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
    )
    def test_capabilities_malformed_json_and_unexpected_status_degrade(self) -> None:
        for response in (
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, json={"features": {}}),
            httpx.Response(418, json={"detail": "internal secret must not escape"}),
            httpx.Response(302, headers={"Location": "https://attacker.invalid/steal"}),
        ):
            with self.subTest(status=response.status_code):
                gateway = HttpRoutingGateway()
                requests = []

                def handler(
                    request: httpx.Request,
                    response=response,
                    requests=requests,
                ) -> httpx.Response:
                    requests.append(str(request.url))
                    return response

                gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
                projected = gateway.capabilities()
                self.assertEqual(projected["busIntelligenceCoverage"], "UNKNOWN")
                self.assertEqual(projected["degraded"], ["ROUTING_CAPABILITIES_UNAVAILABLE"])
                self.assertEqual(len(requests), 1)

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_TOKEN="service-token",
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
    )
    def test_route_critical_path_never_adds_a_capabilities_network_call(self) -> None:
        fixtures = LockedFixtures()
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            if request.url.path.endswith("/routes/optimize"):
                response = fixtures.get("routing_response")
                response["requestId"] = json.loads(request.content)["requestId"]
                return httpx.Response(200, json=response)
            return httpx.Response(200, content=b"malformed-capabilities")

        gateway = HttpRoutingGateway()
        gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
        gateway.optimize(
            fixtures.get("public_request"),
            RoutingEnvelope("corr-deadline", "idempotency-deadline", "2026-08-23T00:00:00+00:00"),
        )
        degraded = gateway.capabilities(allow_network=False)

        self.assertEqual(len(requests), 1)
        self.assertEqual(degraded["busIntelligenceCoverage"], "UNKNOWN")
        gateway.capabilities()
        gateway.capabilities(allow_network=False)
        self.assertEqual(len(requests), 2)

    def test_projection_rejects_p90_and_strict_budget_invariant_violations(self) -> None:
        fixtures = LockedFixtures()
        private = fixtures.get("routing_response")
        request = fixtures.get("public_request")
        route = {
            "routeId": "bad-route",
            "pattern": "TAXI_ONLY",
            "totalDuration": {
                "p50Seconds": 100,
                "p90Seconds": 99,
                "origin": "PROVIDER_ESTIMATE",
                "confidence": {"grade": "LOW", "score": 0.1},
            },
            "taxiCost": {
                "lower": 9000,
                "expected": 10000,
                "upper": 10001,
                "currency": "KRW",
                "origin": "PROVIDER_ESTIMATE",
            },
            "totalFareExpected": 10000,
            "walkSeconds": 0,
            "transferCount": 0,
            "taxiLegCount": 1,
            "reliabilityScore": 0.1,
            "legs": [],
            "reasonCodes": [],
            "warningCodes": [],
        }
        private["routes"] = [route]
        private["recommendations"]["fastest"] = "bad-route"
        with self.assertRaises(ContractError):
            project_public_response(private, CanonicalContracts(), fixtures, public_request=request)
