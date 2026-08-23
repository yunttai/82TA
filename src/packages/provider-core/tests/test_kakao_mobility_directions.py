from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib import resources
import json
import unittest

from provider_core.capabilities import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
)
from provider_core.canonical import Coordinate, DataOrigin, TravelMode
from provider_core.envelope import Freshness, ProviderStatus, QualityFlag
from provider_core.http import HttpResponse, SensitiveValue
from provider_core.kakao_mobility import KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION
from provider_core.named import (
    KakaoMobilityDirectionsAdapter,
    ProviderOperationBinding,
    ProviderFixtureScenario,
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
from provider_core.validation import SchemaValidationError


KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 24, 8, 10, 1, tzinfo=KST)
PROVIDER = "KAKAO_DIRECTIONS"
OPERATION = "route_current"


class RecordingTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        return self.response


def fixture_body(case: str = "success") -> dict:
    document = json.loads(
        resources.files("provider_core")
        .joinpath("fixtures/named_kakao_mobility.json")
        .read_text(encoding="utf-8")
    )
    return document["operations"][OPERATION][case]["body"]


def executable_adapter(response: HttpResponse, *, secret: str = "test-only-secret"):
    transport = RecordingTransport(response)
    capability = Capability(
        PROVIDER,
        OPERATION,
        documentation_state=DocumentationState.DOCUMENTED,
        key_verification_state=KeyVerificationState.KEY_VERIFIED,
        production_state=ProductionState.PRODUCTION_APPROVED,
        fixture_only=False,
    )
    evidence = tuple(
        RuntimeEvidence(
            PROVIDER,
            OPERATION,
            kind,
            f"test-kakao-{kind.value.lower()}",
            "a" * 64,
            (
                KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION
                if kind is RuntimeEvidenceKind.RESPONSE_SCHEMA
                else "test-evidence-v1"
            ),
            NOW - timedelta(minutes=5),
            NOW + timedelta(minutes=5),
        )
        for kind in RuntimeEvidenceKind
    )
    binding = ProviderOperationBinding(
        ScopedProviderTransport(PROVIDER, OPERATION, transport),
        ScopedProviderCredential(PROVIDER, OPERATION, SensitiveValue(secret)),
    )
    return (
        KakaoMobilityDirectionsAdapter(
            capabilities=CapabilityRegistry((capability,)),
            runtime_evidence=ProviderRuntimeEvidenceConfig(evidence),
            operation_bindings={(PROVIDER, OPERATION): binding},
            clock=lambda: NOW,
        ),
        transport,
    )


class KakaoMobilityDirectionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = TransitSearchRequest(
            Coordinate(127.1, 37.39),
            Coordinate(127.12, 37.41),
            NOW + timedelta(hours=1),
        )
        self.deadline = Deadline.after_ms(1_000, clock=lambda: 10.0)

    def test_current_request_and_official_response_normalize_without_raw_leakage(self) -> None:
        raw = fixture_body()
        response = HttpResponse(
            200,
            "application/json; charset=utf-8",
            json.dumps(raw, separators=(",", ":")).encode("utf-8"),
        )
        secret = "must-never-render-kakao-secret"
        adapter, transport = executable_adapter(response, secret=secret)

        result = adapter.route(self.request, deadline=self.deadline)

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.provider, PROVIDER)
        self.assertEqual(result.schema_version, KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION)
        self.assertEqual(result.freshness, Freshness.UNKNOWN)
        self.assertIn(QualityFlag.SCHEMA_VALIDATED, result.quality_flags)
        self.assertIn(QualityFlag.OBSERVED_AT_MISSING, result.quality_flags)
        self.assertIsNone(result.observed_at)
        self.assertEqual(result.normalized_count, 1)

        itinerary = result.payload[0]
        leg = itinerary.legs[0]
        self.assertEqual(leg.mode, TravelMode.TAXI)
        self.assertEqual(leg.duration.p50_seconds, 720)
        self.assertEqual(leg.duration.p90_seconds, 720)
        self.assertEqual(leg.duration.origin, DataOrigin.PROVIDER_ESTIMATE)
        self.assertEqual(leg.distance_meters, 5100)
        self.assertEqual(leg.fare.expected_krw, 7800)
        self.assertEqual(leg.fare.upper_krw, 7800)
        self.assertEqual(
            leg.geometry,
            (
                Coordinate(127.1, 37.39),
                Coordinate(127.11, 37.4),
                Coordinate(127.12, 37.41),
            ),
        )
        self.assertIsNone(leg.transit)

        self.assertEqual(len(transport.calls), 1)
        request = transport.calls[0]
        self.assertEqual(
            dict(request.query),
            {
                "origin": "127.1,37.39",
                "destination": "127.12,37.41",
                "priority": "TIME",
                "car_fuel": "GASOLINE",
                "car_hipass": "false",
                "alternatives": "false",
                "road_details": "false",
                "summary": "false",
            },
        )
        self.assertEqual(request.safe_summary()["query"]["origin"], "<redacted>")
        self.assertEqual(request.safe_summary()["headers"]["Authorization"], "***")
        rendered = repr((request, result))
        self.assertNotIn(secret, rendered)
        self.assertNotIn(raw["trans_id"], rendered)
        self.assertNotIn("sanitized success", rendered)

    def test_normalization_seam_is_pure_and_known_no_route_is_empty(self) -> None:
        body = {
            "trans_id": "sanitized-kakao-no-route-001",
            "routes": [{"result_code": 104, "result_msg": "sanitized no route"}],
        }
        self.assertEqual(
            KakaoMobilityDirectionsAdapter.normalize_current_response(body), ()
        )

    def test_documented_terminal_guide_road_index_minus_one_is_accepted(self) -> None:
        body = fixture_body()
        terminal_guide = body["routes"][0]["sections"][0]["guides"][-1]
        self.assertEqual(terminal_guide["road_index"], -1)
        itinerary = KakaoMobilityDirectionsAdapter.normalize_current_response(body)[0]
        self.assertEqual(itinerary.legs[0].distance_meters, 5100)

    def test_unknown_fields_codes_and_malformed_geometry_fail_closed(self) -> None:
        unknown_field = fixture_body()
        unknown_field["routes"][0]["summary"]["raw_vendor_extension"] = True
        with self.assertRaises(SchemaValidationError):
            KakaoMobilityDirectionsAdapter.normalize_current_response(unknown_field)

        unknown_code = {
            "trans_id": "sanitized-kakao-unknown-code-001",
            "routes": [{"result_code": 999, "result_msg": "sanitized unknown"}],
        }
        with self.assertRaises(SchemaValidationError):
            KakaoMobilityDirectionsAdapter.normalize_current_response(unknown_code)

        malformed_geometry = fixture_body()
        malformed_geometry["routes"][0]["sections"][0]["roads"][0][
            "vertexes"
        ] = [127.1, 37.39, 127.11]
        with self.assertRaises(SchemaValidationError):
            KakaoMobilityDirectionsAdapter.normalize_current_response(
                malformed_geometry
            )

    def test_live_malformed_and_http_auth_error_return_sanitized_statuses(self) -> None:
        malformed = fixture_body()
        del malformed["routes"][0]["summary"]["fare"]
        adapter, _ = executable_adapter(
            HttpResponse(200, "application/json", json.dumps(malformed).encode())
        )
        bad = adapter.route(self.request, deadline=self.deadline)
        self.assertEqual(bad.status, ProviderStatus.BAD_RESPONSE)
        self.assertEqual(bad.quality_flags, (QualityFlag.SCHEMA_DRIFT,))
        self.assertIsNone(bad.payload)
        self.assertEqual(bad.message_code, "PROVIDER_BAD_RESPONSE")

        auth_adapter, auth_transport = executable_adapter(
            HttpResponse(401, "application/json", b'{"message":"sanitized"}')
        )
        rejected = auth_adapter.route(self.request, deadline=self.deadline)
        self.assertEqual(rejected.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(rejected.quality_flags, ())
        self.assertIsNone(rejected.payload)
        self.assertEqual(len(auth_transport.calls), 1)

    def test_checked_in_capability_remains_disabled_without_approval_evidence(self) -> None:
        transport = RecordingTransport(
            HttpResponse(200, "application/json", json.dumps(fixture_body()).encode())
        )
        adapter = KakaoMobilityDirectionsAdapter(transport)
        result = adapter.route(self.request, deadline=self.deadline)
        self.assertEqual(result.status, ProviderStatus.DISABLED)
        self.assertEqual(transport.calls, [])

    def test_fixture_uses_the_current_schema_and_sanitized_normalization(self) -> None:
        envelope = KakaoMobilityDirectionsAdapter().fixture(
            OPERATION, scenario=ProviderFixtureScenario.SUCCESS
        )
        self.assertEqual(envelope.status, ProviderStatus.OK)
        self.assertEqual(envelope.schema_version, KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION)
        self.assertIn(QualityFlag.SANITIZED_FIXTURE, envelope.quality_flags)


if __name__ == "__main__":
    unittest.main()
