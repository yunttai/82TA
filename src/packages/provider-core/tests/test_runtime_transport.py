from __future__ import annotations

import ssl
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from provider_core.capabilities import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
)
from provider_core.canonical import Coordinate
from provider_core.context import BusArrivalObservation, OpaqueVehicleTokenIssuer
from provider_core.envelope import ProviderStatus
from provider_core.http import HttpRequest, HttpResponse, SensitiveValue
from provider_core.named import ENDPOINT_SPECS, KakaoTransitAdapter
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from provider_core.runtime import (
    ProviderRuntimeEvidenceConfig,
    RuntimeEvidence,
    RuntimeEvidenceKind,
    RuntimeGateReason,
)
from provider_core.transport import (
    NetworkEgressAttestation,
    PinnedHttpsConnectionFactory,
    StrictHttpsTransport,
    TransportNetworkError,
    TransportSecurityError,
)
from provider_core.validation import InputValidationError, SchemaValidationError


UTC = timezone.utc
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
ENDPOINT = "https://provider.example/api"
DIGEST = "a" * 64


def evidence(
    kind: RuntimeEvidenceKind,
    *,
    provider: str = "KAKAO_PUBLIC_TRANSIT",
    operation: str = "search_current",
    version: str = "schema-v1",
    issued_at: datetime = NOW - timedelta(hours=1),
    expires_at: datetime = NOW + timedelta(hours=1),
) -> RuntimeEvidence:
    return RuntimeEvidence(
        provider=provider,
        operation=operation,
        kind=kind,
        evidence_id=f"evidence-{kind.value.lower()}",
        artifact_sha256=DIGEST,
        version=version,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def approved_capability() -> Capability:
    return Capability(
        provider="KAKAO_PUBLIC_TRANSIT",
        operation="search_current",
        documentation_state=DocumentationState.DOCUMENTED,
        key_verification_state=KeyVerificationState.KEY_VERIFIED,
        production_state=ProductionState.PRODUCTION_APPROVED,
        fixture_only=False,
    )


def egress() -> NetworkEgressAttestation:
    return NetworkEgressAttestation(
        evidence_id="egress-policy-1",
        artifact_sha256="b" * 64,
        version="egress-v1",
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )


class RuntimeEvidenceTests(unittest.TestCase):
    def test_all_independent_exact_evidence_is_required(self) -> None:
        config = ProviderRuntimeEvidenceConfig(evidence(kind) for kind in RuntimeEvidenceKind)
        with self.assertRaises(AttributeError):
            config._entries = {}  # type: ignore[misc]
        decision = config.assess(
            approved_capability(),
            provider="KAKAO_PUBLIC_TRANSIT",
            operation="search_current",
            response_schema_verified=True,
            response_schema_version="schema-v1",
            now=NOW,
        )
        self.assertTrue(decision.executable)
        self.assertEqual(len(decision.evidence_ids), 3)

        missing = ProviderRuntimeEvidenceConfig().assess(
            approved_capability(),
            provider="KAKAO_PUBLIC_TRANSIT",
            operation="search_current",
            response_schema_verified=True,
            response_schema_version="schema-v1",
            now=NOW,
        )
        self.assertFalse(missing.executable)
        self.assertIn(RuntimeGateReason.EVIDENCE_MISSING, missing.reasons)

    def test_expired_and_schema_mismatched_evidence_fail_closed(self) -> None:
        entries = [evidence(kind) for kind in RuntimeEvidenceKind]
        entries[0] = evidence(
            RuntimeEvidenceKind.KEY_VERIFICATION,
            expires_at=NOW,
        )
        entries[2] = evidence(RuntimeEvidenceKind.RESPONSE_SCHEMA, version="schema-v2")
        decision = ProviderRuntimeEvidenceConfig(entries).assess(
            approved_capability(),
            provider="KAKAO_PUBLIC_TRANSIT",
            operation="search_current",
            response_schema_verified=True,
            response_schema_version="schema-v1",
            now=NOW,
        )
        self.assertFalse(decision.executable)
        self.assertIn(RuntimeGateReason.EVIDENCE_EXPIRED, decision.reasons)
        self.assertIn(RuntimeGateReason.RESPONSE_SCHEMA_VERSION_MISMATCH, decision.reasons)

    def test_capability_and_evidence_must_match_exact_operation(self) -> None:
        with self.assertRaises(ValueError):
            ProviderRuntimeEvidenceConfig().assess(
                approved_capability(),
                provider="KAKAO_PUBLIC_TRANSIT",
                operation="different",
                response_schema_verified=True,
                response_schema_version="schema-v1",
                now=NOW,
            )

    def test_current_schema_false_stops_promoted_state_before_transport(self) -> None:
        class NoCallTransport:
            calls = 0

            def send(self, request):
                self.calls += 1
                raise AssertionError("schema-false operation attempted network I/O")

        transport = NoCallTransport()
        adapter = KakaoTransitAdapter(
            transport,
            capabilities=CapabilityRegistry((approved_capability(),)),
            runtime_evidence=ProviderRuntimeEvidenceConfig(
                evidence(kind) for kind in RuntimeEvidenceKind
            ),
            credential=SensitiveValue("not-a-live-secret"),
            clock=lambda: NOW,
        )
        result = adapter.search(
            TransitSearchRequest(
                Coordinate(127.1, 37.3),
                Coordinate(127.2, 37.4),
                NOW,
            ),
            deadline=Deadline.after_ms(1000, clock=lambda: 10.0),
        )
        self.assertEqual(result.status, ProviderStatus.DISABLED)
        self.assertEqual(transport.calls, 0)

    def test_executable_path_preserves_exact_evidence_schema_version(self) -> None:
        schema_version = "kakao-transit-contract-v1"
        foundation_spec = next(
            spec
            for spec in ENDPOINT_SPECS
            if spec.provider == "KAKAO_PUBLIC_TRANSIT"
            and spec.operation == "search_current"
        )
        verified_spec = replace(
            foundation_spec,
            response_schema_verified=True,
            response_schema_version=schema_version,
        )

        class VerifiedTestAdapter(KakaoTransitAdapter):
            def endpoint_spec(self, operation):
                if operation != "search_current":
                    raise AssertionError("unexpected operation")
                return verified_spec

        class RecordingTransport:
            def __init__(self):
                self.calls = []

            def send(self, request):
                self.calls.append(request)
                body = {
                    "routes": [
                        {
                            "id": "verified-schema-route",
                            "origin": {"lon": 127.1, "lat": 37.3},
                            "destination": {"lon": 127.2, "lat": 37.4},
                            "durationSeconds": 600,
                            "p90Seconds": 720,
                            "distanceMeters": 10000,
                            "fareKrw": 2000,
                            "routeId": "sanitized-route",
                            "routeLabel": "SAN-1",
                            "direction": "Sanitized Northbound",
                            "geometry": [
                                {"lon": 127.1, "lat": 37.3},
                                {"lon": 127.2, "lat": 37.4},
                            ],
                        }
                    ]
                }
                return HttpResponse(
                    200,
                    "application/json",
                    json.dumps(body, separators=(",", ":")).encode("utf-8"),
                )

        transport = RecordingTransport()
        runtime = ProviderRuntimeEvidenceConfig(
            evidence(
                kind,
                version=(
                    schema_version
                    if kind is RuntimeEvidenceKind.RESPONSE_SCHEMA
                    else "evidence-v1"
                ),
            )
            for kind in RuntimeEvidenceKind
        )
        adapter = VerifiedTestAdapter(
            transport,
            capabilities=CapabilityRegistry((approved_capability(),)),
            runtime_evidence=runtime,
            credential=SensitiveValue("not-a-live-secret"),
            clock=lambda: NOW,
        )
        result = adapter.search(
            TransitSearchRequest(
                Coordinate(127.1, 37.3),
                Coordinate(127.2, 37.4),
                NOW,
            ),
            deadline=Deadline.after_ms(1000, clock=lambda: 10.0),
        )
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.schema_version, schema_version)
        self.assertEqual(len(transport.calls), 1)

        mismatched = VerifiedTestAdapter(
            RecordingTransport(),
            capabilities=CapabilityRegistry((approved_capability(),)),
            runtime_evidence=ProviderRuntimeEvidenceConfig(
                evidence(kind, version="different-v1")
                for kind in RuntimeEvidenceKind
            ),
            credential=SensitiveValue("not-a-live-secret"),
            clock=lambda: NOW,
        )
        mismatch_result = mismatched.search(
            TransitSearchRequest(
                Coordinate(127.1, 37.3),
                Coordinate(127.2, 37.4),
                NOW,
            ),
            deadline=Deadline.after_ms(1000, clock=lambda: 10.0),
        )
        self.assertEqual(mismatch_result.status, ProviderStatus.DISABLED)
        self.assertEqual(len(mismatched.transport.calls), 0)

        with self.assertRaises(ValueError):
            replace(
                foundation_spec,
                response_schema_verified=True,
                response_schema_version=None,
            )


class FakeResolver:
    def __init__(self, *addresses: str) -> None:
        self.addresses = addresses
        self.calls: list[tuple[str, int]] = []

    def resolve(self, hostname: str, port: int):
        self.calls.append((hostname, port))
        return self.addresses


class FakeResponse:
    def __init__(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        self.status = status
        self._headers = headers
        self._body = body
        self._offset = 0
        self.closed = False

    def getheaders(self):
        return list(self._headers)

    def read(self, amount: int = -1):
        if amount < 0:
            amount = len(self._body) - self._offset
        value = self._body[self._offset : self._offset + amount]
        self._offset += len(value)
        return value

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests = []
        self.read_timeouts = []
        self.closed = False

    def request(self, method, target, body=None, headers=None):
        self.requests.append((method, target, body, headers))

    def getresponse(self):
        return self.response

    def set_read_timeout(self, seconds):
        self.read_timeouts.append(seconds)

    def close(self):
        self.closed = True


class FakeConnectionFactory:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.calls = []

    def open(self, **kwargs):
        self.calls.append(kwargs)
        return self.connection


class StrictHttpsTransportTests(unittest.TestCase):
    def transport(self, response: FakeResponse, *addresses: str):
        connection = FakeConnection(response)
        resolver = FakeResolver(*(addresses or ("93.184.216.34",)))
        factory = FakeConnectionFactory(connection)
        transport = StrictHttpsTransport(
            (ENDPOINT,),
            egress_attestation=egress(),
            resolver=resolver,
            connection_factory=factory,
            clock=lambda: NOW,
            monotonic_clock=lambda: 10.0,
        )
        return transport, resolver, factory, connection

    def test_success_is_exact_bounded_and_secret_safe(self) -> None:
        body = b'{"ok":true}'
        response = FakeResponse(
            200,
            [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))],
            body,
        )
        transport, resolver, factory, connection = self.transport(response)
        request = HttpRequest(
            "GET",
            ENDPOINT,
            headers=(("Authorization", SensitiveValue("secret-value")),),
            query=(("x", 127.123456),),
            timeout_ms=900,
            maximum_response_bytes=100,
        )
        result = transport.send(request)
        self.assertEqual(result.body, body)
        self.assertEqual(resolver.calls, [("provider.example", 443)])
        self.assertEqual(factory.calls[0]["resolved_ip"], "93.184.216.34")
        self.assertAlmostEqual(factory.calls[0]["connect_timeout_seconds"], 0.9)
        self.assertEqual(connection.requests[0][1], "/api?x=127.123456")
        self.assertEqual(connection.requests[0][3]["Authorization"], "secret-value")
        self.assertGreaterEqual(len(connection.read_timeouts), 2)
        self.assertTrue(all(value <= 0.901 for value in connection.read_timeouts))
        self.assertNotIn("secret-value", repr(request))
        self.assertNotIn("127.123456", repr(request))
        self.assertNotIn('{"ok":true}', repr(result))
        self.assertTrue(connection.closed and response.closed)

    def test_missing_egress_evidence_and_private_dns_fail_before_connection(self) -> None:
        response = FakeResponse(200, [("Content-Type", "application/json")], b"{}")
        resolver = FakeResolver("93.184.216.34")
        factory = FakeConnectionFactory(FakeConnection(response))
        transport = StrictHttpsTransport(
            (ENDPOINT,), resolver=resolver, connection_factory=factory, clock=lambda: NOW,
        )
        with self.assertRaises(TransportSecurityError):
            transport.send(HttpRequest("GET", ENDPOINT))
        self.assertEqual(resolver.calls, [])

        private_transport, _, private_factory, _ = self.transport(response, "127.0.0.1")
        with self.assertRaises(TransportSecurityError):
            private_transport.send(HttpRequest("GET", ENDPOINT))
        self.assertEqual(private_factory.calls, [])

    def test_unallowlisted_endpoint_redirect_and_ambiguous_headers_are_rejected(self) -> None:
        ok, _, _, _ = self.transport(
            FakeResponse(200, [("Content-Type", "application/json")], b"{}")
        )
        with self.assertRaises(InputValidationError):
            ok.send(HttpRequest("GET", "https://other.example/api"))

        redirect, _, _, _ = self.transport(
            FakeResponse(302, [("Content-Type", "application/json")], b"{}")
        )
        with self.assertRaises(TransportSecurityError):
            redirect.send(HttpRequest("GET", ENDPOINT))

        ambiguous, _, _, _ = self.transport(
            FakeResponse(
                200,
                [("Content-Type", "application/json"), ("Content-Length", "2"), ("Transfer-Encoding", "chunked")],
                b"{}",
            )
        )
        with self.assertRaises(SchemaValidationError):
            ambiguous.send(HttpRequest("GET", ENDPOINT))

    def test_socket_failure_is_sanitized_as_network_error(self) -> None:
        class FailingFactory:
            def open(self, **kwargs):
                raise OSError("raw socket detail must not cross the boundary")

        transport = StrictHttpsTransport(
            (ENDPOINT,),
            egress_attestation=egress(),
            resolver=FakeResolver("93.184.216.34"),
            connection_factory=FailingFactory(),
            clock=lambda: NOW,
            monotonic_clock=lambda: 10.0,
        )
        with self.assertRaisesRegex(TransportNetworkError, "provider HTTPS transport failed"):
            transport.send(HttpRequest("GET", ENDPOINT))

    def test_response_type_length_and_body_bounds_are_strict(self) -> None:
        invalid_type, _, _, _ = self.transport(
            FakeResponse(200, [("Content-Type", "text/html")], b"{}")
        )
        with self.assertRaises(SchemaValidationError):
            invalid_type.send(HttpRequest("GET", ENDPOINT))

        length_mismatch, _, _, _ = self.transport(
            FakeResponse(200, [("Content-Type", "application/json"), ("Content-Length", "9")], b"{}")
        )
        with self.assertRaises(SchemaValidationError):
            length_mismatch.send(HttpRequest("GET", ENDPOINT))

        oversized, _, _, _ = self.transport(
            FakeResponse(200, [("Content-Type", "application/json")], b"{" + b"a" * 20 + b"}")
        )
        with self.assertRaises(SchemaValidationError):
            oversized.send(HttpRequest("GET", ENDPOINT, maximum_response_bytes=10))


class FakeSocket:
    def __init__(self) -> None:
        self.timeouts = []
        self.closed = False

    def settimeout(self, value):
        self.timeouts.append(value)

    def close(self):
        self.closed = True


class FakeTlsContext:
    check_hostname = True
    verify_mode = ssl.CERT_REQUIRED

    def __init__(self, tls_socket: FakeSocket) -> None:
        self.tls_socket = tls_socket
        self.calls = []

    def wrap_socket(self, raw_socket, *, server_hostname):
        self.calls.append((raw_socket, server_hostname))
        return self.tls_socket


class PinnedConnectionFactoryTests(unittest.TestCase):
    def test_factory_connects_only_to_resolved_ip_with_system_tls_requirements(self) -> None:
        raw = FakeSocket()
        tls_socket = FakeSocket()
        opened = []
        context = FakeTlsContext(tls_socket)
        factory = PinnedHttpsConnectionFactory(
            socket_opener=lambda address, timeout: opened.append((address, timeout)) or raw,
            tls_context_factory=lambda: context,
        )
        connection = factory.open(
            hostname="provider.example",
            port=443,
            resolved_ip="93.184.216.34",
            connect_timeout_seconds=0.7,
        )
        self.assertEqual(opened, [(('93.184.216.34', 443), 0.7)])
        self.assertEqual(context.calls, [(raw, "provider.example")])
        connection.set_read_timeout(0.4)
        self.assertEqual(tls_socket.timeouts[-1], 0.4)


class VehicleTokenTests(unittest.TestCase):
    def test_token_is_stable_provider_scoped_and_missing_is_not_joinable(self) -> None:
        issuer = OpaqueVehicleTokenIssuer(b"k" * 32)
        first = issuer.issue("GBIS_V2", "raw-provider-vehicle-id")
        second = issuer.issue("GBIS_V2", "raw-provider-vehicle-id")
        other = issuer.issue("OTHER", "raw-provider-vehicle-id")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertTrue(first.startswith("veh_") and len(first) == 68)
        self.assertNotIn("raw-provider-vehicle-id", first)
        self.assertNotIn("k" * 16, repr(issuer))

        arrival = BusArrivalObservation("route", "stop", 30, None, NOW)
        self.assertIsNone(arrival.vehicle_join_key)


if __name__ == "__main__":
    unittest.main()
