from __future__ import annotations

import hashlib
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
from provider_core.envelope import ProviderStatus
from provider_core.http import HttpResponse, SensitiveValue
from provider_core.named import (
    ENDPOINT_SPECS,
    KakaoTransitAdapter,
    OdsayTransitAdapter,
    ProviderAdapterSuite,
    ProviderAdapterSuiteConfig,
    ProviderOperationBinding,
    ScopedProviderCredential,
    ScopedProviderTransport,
)
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from provider_core.runtime import (
    ProviderRuntimeEvidenceConfig,
    RuntimeEvidence,
    RuntimeEvidenceKind,
)


KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 24, 7, 40, tzinfo=KST)
SCHEMA_VERSION = "sanitized-live-contract-v1"
DIGEST = "c" * 64


class RecordingTransport:
    def __init__(self) -> None:
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        body = {
            "routes": [
                {
                    "id": "sanitized-production-route",
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


class NoCallTransport:
    def __init__(self) -> None:
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        raise AssertionError("fail-closed assembly attempted network I/O")


def approved_capability(provider: str, operation: str) -> Capability:
    return Capability(
        provider=provider,
        operation=operation,
        documentation_state=DocumentationState.DOCUMENTED,
        key_verification_state=KeyVerificationState.KEY_VERIFIED,
        production_state=ProductionState.PRODUCTION_APPROVED,
        fixture_only=False,
    )


def evidence(provider: str, operation: str) -> tuple[RuntimeEvidence, ...]:
    return tuple(
        RuntimeEvidence(
            provider=provider,
            operation=operation,
            kind=kind,
            evidence_id=f"{provider.lower()}-{operation}-{kind.value.lower()}",
            artifact_sha256=DIGEST,
            version=(SCHEMA_VERSION if kind is RuntimeEvidenceKind.RESPONSE_SCHEMA else "evidence-v1"),
            issued_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=1),
        )
        for kind in RuntimeEvidenceKind
    )


def binding(
    provider: str,
    operation: str,
    transport,
    secret: str,
) -> ProviderOperationBinding:
    return ProviderOperationBinding(
        transport=ScopedProviderTransport(provider, operation, transport),
        credential=ScopedProviderCredential(
            provider, operation, SensitiveValue(secret),
        ),
    )


class VerifiedKakaoTransitAdapter(KakaoTransitAdapter):
    def endpoint_spec(self, operation):
        spec = next(
            item
            for item in ENDPOINT_SPECS
            if item.provider == "KAKAO_PUBLIC_TRANSIT"
            and item.operation == operation
        )
        return replace(
            spec,
            response_schema_verified=True,
            response_schema_version=SCHEMA_VERSION,
        )


class VerifiedOdsayTransitAdapter(OdsayTransitAdapter):
    def endpoint_spec(self, operation):
        spec = next(
            item
            for item in ENDPOINT_SPECS
            if item.provider == "ODSAY" and item.operation == operation
        )
        return replace(
            spec,
            response_schema_verified=True,
            response_schema_version=SCHEMA_VERSION,
        )


class ProductionAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = TransitSearchRequest(
            Coordinate(127.1, 37.3), Coordinate(127.2, 37.4), NOW,
        )
        self.deadline = Deadline.after_ms(1000, clock=lambda: 10.0)

    def test_entry_time_fingerprint_preserves_exact_aware_iso_timestamp(self) -> None:
        departure = datetime.fromisoformat("2026-08-24T07:40:00.123456+09:00")
        request = TransitSearchRequest(
            self.request.origin,
            self.request.destination,
            departure,
            max_itineraries=7,
        )
        canonical = json.dumps(
            {
                "departureTime": departure.isoformat(),
                "destination": {"lat": 37.4, "lon": 127.2},
                "maxItineraries": 7,
                "origin": {"lat": 37.3, "lon": 127.1},
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertEqual(request.fingerprint(), hashlib.sha256(canonical).hexdigest())
        one_microsecond_later = replace(
            request,
            departure_time=departure + timedelta(microseconds=1),
        )
        self.assertNotEqual(request.fingerprint(), one_microsecond_later.fingerprint())
        with self.assertRaises(ValueError):
            replace(request, departure_time=departure.replace(tzinfo=None))

    def test_scopes_must_match_and_unknown_or_duplicate_bindings_are_rejected(self) -> None:
        transport = NoCallTransport()
        with self.assertRaisesRegex(ValueError, "scopes must match"):
            ProviderOperationBinding(
                ScopedProviderTransport(
                    "KAKAO_PUBLIC_TRANSIT", "search_current", transport,
                ),
                ScopedProviderCredential(
                    "ODSAY", "search", SensitiveValue("wrong-scope-secret"),
                ),
            )
        unknown = binding("UNKNOWN", "search", transport, "unknown-secret")
        with self.assertRaisesRegex(ValueError, "unknown provider operation"):
            ProviderAdapterSuiteConfig((unknown,))
        exact = binding(
            "KAKAO_PUBLIC_TRANSIT", "search_current", transport, "exact-secret",
        )
        with self.assertRaisesRegex(ValueError, "duplicate provider operation"):
            ProviderAdapterSuiteConfig((exact, exact))

    def test_config_and_binding_repr_are_secret_and_transport_safe(self) -> None:
        secret = "credential-must-never-render"
        exact = binding(
            "KAKAO_PUBLIC_TRANSIT", "search_current", NoCallTransport(), secret,
        )
        config = ProviderAdapterSuiteConfig((exact,))
        rendered = repr((exact, exact.transport, exact.credential, config))
        self.assertNotIn(secret, rendered)
        self.assertNotIn("NoCallTransport", rendered)
        self.assertIn("KAKAO_PUBLIC_TRANSIT", rendered)
        with self.assertRaises(TypeError):
            config.binding_map[("ODSAY", "search")] = exact  # type: ignore[index]

    def test_legacy_shared_configuration_is_quarantined_and_never_forwarded(self) -> None:
        transport = NoCallTransport()
        secret = "must-be-quarantined"
        suite = ProviderAdapterSuite(
            transport,
            capabilities=CapabilityRegistry(
                (
                    approved_capability(
                        "KAKAO_PUBLIC_TRANSIT", "search_current",
                    ),
                )
            ),
            credential=SensitiveValue(secret),
        )
        result = suite.kakao_transit.search(self.request, deadline=self.deadline)
        self.assertTrue(suite.shared_configuration_quarantined)
        self.assertEqual(result.status, ProviderStatus.DISABLED)
        self.assertEqual(transport.calls, [])
        self.assertIsNone(suite.kakao_transit.credential)
        self.assertFalse(
            suite.kakao_transit.capabilities.enabled(
                "KAKAO_PUBLIC_TRANSIT", "search_current",
            )
        )
        self.assertNotIn(secret, repr(suite.__dict__))

    def test_binding_and_fixture_presence_cannot_enable_foundation_capability(self) -> None:
        transport = NoCallTransport()
        config = ProviderAdapterSuiteConfig(
            (
                binding(
                    "KAKAO_PUBLIC_TRANSIT",
                    "search_current",
                    transport,
                    "configured-but-unverified",
                ),
            )
        )
        suite = ProviderAdapterSuite.from_config(config)
        result = suite.kakao_transit.search(self.request, deadline=self.deadline)
        self.assertEqual(result.status, ProviderStatus.DISABLED)
        self.assertEqual(transport.calls, [])
        self.assertTrue(
            suite.kakao_transit.fixture_file.startswith("named_kakao_transit")
        )
        self.assertFalse(
            config.capabilities.enabled("KAKAO_PUBLIC_TRANSIT", "search_current")
        )

    def test_promoted_state_and_evidence_still_cannot_bypass_live_schema_gate(self) -> None:
        transport = NoCallTransport()
        key = ("KAKAO_PUBLIC_TRANSIT", "search_current")
        config = ProviderAdapterSuiteConfig(
            (binding(*key, transport, "configured-promoted-secret"),),
            capabilities=CapabilityRegistry((approved_capability(*key),)),
            runtime_evidence=ProviderRuntimeEvidenceConfig(evidence(*key)),
            clock=lambda: NOW,
        )
        suite = ProviderAdapterSuite.from_config(config)
        result = suite.kakao_transit.search(self.request, deadline=self.deadline)
        self.assertEqual(result.status, ProviderStatus.DISABLED)
        self.assertEqual(transport.calls, [])

    def test_exact_header_and_query_auth_use_only_their_scoped_transport_and_secret(self) -> None:
        kakao_transport = RecordingTransport()
        odsay_transport = RecordingTransport()
        kakao_key = ("KAKAO_PUBLIC_TRANSIT", "search_current")
        odsay_key = ("ODSAY", "search")
        config = ProviderAdapterSuiteConfig(
            (
                binding(*kakao_key, kakao_transport, "kakao-only-secret"),
                binding(*odsay_key, odsay_transport, "odsay-only-secret"),
            ),
            capabilities=CapabilityRegistry(
                (
                    approved_capability(*kakao_key),
                    approved_capability(*odsay_key),
                )
            ),
            runtime_evidence=ProviderRuntimeEvidenceConfig(
                evidence(*kakao_key) + evidence(*odsay_key)
            ),
            clock=lambda: NOW,
        )
        kakao = VerifiedKakaoTransitAdapter(
            capabilities=config.capabilities,
            runtime_evidence=config.runtime_evidence,
            operation_bindings=config.binding_map,
            clock=lambda: NOW,
        )
        odsay = VerifiedOdsayTransitAdapter(
            capabilities=config.capabilities,
            runtime_evidence=config.runtime_evidence,
            operation_bindings=config.binding_map,
            clock=lambda: NOW,
        )

        self.assertEqual(
            kakao.search(self.request, deadline=self.deadline).status,
            ProviderStatus.OK,
        )
        self.assertEqual(
            odsay.search(self.request, deadline=self.deadline).status,
            ProviderStatus.OK,
        )
        self.assertEqual(len(kakao_transport.calls), 1)
        self.assertEqual(len(odsay_transport.calls), 1)

        kakao_request = kakao_transport.calls[0]
        odsay_request = odsay_transport.calls[0]
        self.assertEqual(
            dict(kakao_request.headers)["Authorization"].reveal_for_transport(),
            "KakaoAK kakao-only-secret",
        )
        self.assertNotIn("apiKey", dict(kakao_request.query))
        self.assertEqual(
            dict(odsay_request.query)["apiKey"].reveal_for_transport(),
            "odsay-only-secret",
        )
        self.assertNotIn("Authorization", dict(odsay_request.headers))
        self.assertIn("dapi.kakao.com", kakao_request.url)
        self.assertIn("api.odsay.com", odsay_request.url)
        rendered = repr((kakao_request, odsay_request, config))
        self.assertNotIn("kakao-only-secret", rendered)
        self.assertNotIn("odsay-only-secret", rendered)

    def test_missing_exact_binding_is_disabled_even_with_promoted_evidence(self) -> None:
        kakao_transport = NoCallTransport()
        kakao_key = ("KAKAO_PUBLIC_TRANSIT", "search_current")
        odsay_key = ("ODSAY", "search")
        config = ProviderAdapterSuiteConfig(
            (binding(*kakao_key, kakao_transport, "kakao-only-secret"),),
            capabilities=CapabilityRegistry((approved_capability(*odsay_key),)),
            runtime_evidence=ProviderRuntimeEvidenceConfig(evidence(*odsay_key)),
            clock=lambda: NOW,
        )
        odsay = VerifiedOdsayTransitAdapter(
            capabilities=config.capabilities,
            runtime_evidence=config.runtime_evidence,
            operation_bindings=config.binding_map,
            clock=lambda: NOW,
        )
        result = odsay.search(self.request, deadline=self.deadline)
        self.assertEqual(result.status, ProviderStatus.DISABLED)
        self.assertEqual(kakao_transport.calls, [])


if __name__ == "__main__":
    unittest.main()
