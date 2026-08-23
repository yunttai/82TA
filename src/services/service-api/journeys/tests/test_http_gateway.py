from __future__ import annotations

import base64
import hashlib
import hmac
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
from journeys.service_auth import Hs256ServiceJwtIssuer


SERVICE_JWT_SECRET = "service-routing-test-secret-7Vq!4xP@9mK#2sL%6wN&8cR"


class HttpRoutingGatewayTests(SimpleTestCase):
    def test_service_jwt_is_bounded_cached_rotated_and_redacted_from_repr(self) -> None:
        current = [datetime(2026, 8, 23, 0, 0, tzinfo=UTC)]
        issuer = Hs256ServiceJwtIssuer(
            SERVICE_JWT_SECRET.encode("utf-8"),
            "service-api",
            "routing-api",
            ttl_seconds=30,
            now=lambda: current[0],
        )

        first = issuer.authorization_header()
        current[0] += timedelta(seconds=19)
        self.assertEqual(issuer.authorization_header(), first)
        current[0] += timedelta(seconds=1)
        rotated = issuer.authorization_header()

        self.assertNotEqual(rotated, first)
        self.assertNotIn(SERVICE_JWT_SECRET, repr(issuer))
        self.assertNotIn(first.removeprefix("Bearer "), repr(issuer))

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
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
        ROUTING_SERVICE_JWT_ISSUER="service-api",
        ROUTING_SERVICE_JWT_AUDIENCE="routing-api",
        ROUTING_SERVICE_JWT_TTL_SECONDS=60,
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
        authorization = seen["headers"]["authorization"]
        self.assertTrue(authorization.startswith("Bearer "))
        encoded_header, encoded_payload, encoded_signature = (
            authorization.removeprefix("Bearer ").split(".")
        )
        payload = json.loads(
            base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        )
        supplied = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        expected = hmac.new(
            SERVICE_JWT_SECRET.encode("utf-8"),
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        self.assertTrue(hmac.compare_digest(expected, supplied))
        self.assertEqual((payload["iss"], payload["aud"]), ("service-api", "routing-api"))
        self.assertGreater(payload["exp"], payload["iat"])
        self.assertEqual(payload["nbf"], payload["iat"] - 5)
        self.assertTrue(payload["jti"])
        self.assertEqual(seen["headers"]["x-correlation-id"], "corr-http")
        self.assertEqual(seen["headers"]["x-request-deadline"], deadline)
        self.assertEqual(seen["headers"]["idempotency-key"], "idempotency-http")
        self.assertEqual(seen["headers"]["accept-encoding"], "identity")

    @override_settings(
        ENVIRONMENT="production",
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
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
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
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
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
    )
    def test_internal_service_auth_failure_is_redacted_as_public_safe_503(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                headers={"Content-Type": "application/problem+json"},
                json={
                    "type": "https://api.example.invalid/problems/service-auth-required",
                    "title": "Service authentication required",
                    "status": 401,
                    "code": "SERVICE_AUTH_REQUIRED",
                    "detail": None,
                    "retryable": False,
                    "correlationId": "private-correlation",
                    "violations": [],
                    "safeContext": {},
                },
            )

        gateway = HttpRoutingGateway()
        gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
        with self.assertRaises(RoutingGatewayError) as raised:
            gateway.optimize(
                LockedFixtures().get("public_request"),
                RoutingEnvelope(
                    "corr-auth",
                    "idempotency-auth",
                    (datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
                ),
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.code, raised.exception.retryable),
            (503, "TRANSIT_PROVIDER_UNAVAILABLE", True),
        )

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
    )
    def test_registered_422_and_504_problems_are_preserved(self) -> None:
        fixtures = LockedFixtures()
        envelope = RoutingEnvelope(
            "corr-problem",
            "idempotency-problem",
            (datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
        )
        cases = (
            (422, "UNSUPPORTED_REGION", False),
            (504, "ROUTING_DEADLINE_EXCEEDED", True),
        )
        for status, code, retryable in cases:
            with self.subTest(status=status, code=code):
                def handler(
                    request: httpx.Request,
                    status: int = status,
                    code: str = code,
                    retryable: bool = retryable,
                ) -> httpx.Response:
                    return httpx.Response(
                        status,
                        headers={"Content-Type": "application/problem+json"},
                        json={
                            "type": f"https://api.example.invalid/problems/{code.lower()}",
                            "title": "Routing request failed",
                            "status": status,
                            "code": code,
                            "detail": None,
                            "retryable": retryable,
                            "correlationId": "corr-problem",
                            "violations": [],
                            "safeContext": {},
                        },
                    )

                gateway = HttpRoutingGateway()
                gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
                with self.assertRaises(RoutingGatewayError) as raised:
                    gateway.optimize(fixtures.get("public_request"), envelope)
                self.assertEqual(
                    (
                        raised.exception.status,
                        raised.exception.code,
                        raised.exception.retryable,
                    ),
                    (status, code, retryable),
                )

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
        ROUTING_VERIFY_SSL=True,
        ROUTING_API_ALLOWED_HOSTS=("routing.internal",),
    )
    def test_unapproved_private_problem_code_is_redacted_as_safe_502(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                503,
                headers={"Content-Type": "application/problem+json"},
                json={
                    "type": "https://routing.internal/problems/provider-secret",
                    "title": "provider credential rejected",
                    "status": 503,
                    "code": "PROVIDER_CREDENTIAL_DETAIL",
                    "detail": "upstream secret detail",
                    "retryable": True,
                    "correlationId": "private-correlation",
                    "violations": [],
                    "safeContext": {"upstream": "private-provider"},
                },
            )

        gateway = HttpRoutingGateway()
        gateway.client._httpx_args["transport"] = httpx.MockTransport(handler)
        with self.assertRaises(RoutingGatewayError) as raised:
            gateway.optimize(
                LockedFixtures().get("public_request"),
                RoutingEnvelope(
                    "corr-unapproved",
                    "idempotency-unapproved",
                    (datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
                ),
            )
        self.assertEqual(
            (
                raised.exception.status,
                raised.exception.code,
                raised.exception.retryable,
            ),
            (502, "PROVIDER_BAD_RESPONSE", True),
        )

    @override_settings(
        ROUTING_API_BASE_URL="https://routing.internal",
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
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
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
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
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
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
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
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
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
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
        ROUTING_SERVICE_JWT_SECRET=SERVICE_JWT_SECRET,
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
