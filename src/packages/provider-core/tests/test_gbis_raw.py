from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from provider_core import (
    GBIS_ARRIVALS_SCHEMA_VERSION,
    GBIS_LIVE_OPERATIONS,
    GBIS_LOCATIONS_SCHEMA_VERSION,
    KAKAO_GBIS_OPERATIONS,
    KAKAO_GBIS_SCHEMA_VERSIONS,
    BusArrivalObservation,
    BusLocationObservation,
    Capability,
    CapabilityRegistry,
    DocumentationState,
    GbisAdapter,
    KeyVerificationState,
    OpaqueVehicleTokenIssuer,
    ProductionState,
    ProviderAdapterSuite,
    ProviderRuntimeEvidenceConfig,
    ProviderStatus,
    RuntimeEvidence,
    RuntimeEvidenceKind,
    SensitiveValue,
    build_kakao_gbis_config,
    parse_gbis_arrivals,
    parse_gbis_locations,
)
from provider_core.http import HttpResponse
from provider_core.resilience import Deadline
from provider_core.transport import HttpsConnectProxyConnectionFactory
from provider_core.validation import SchemaValidationError


NOW = datetime(2026, 8, 25, 8, 30, tzinfo=timezone.utc)
DIGEST = "d" * 64
ISSUER = OpaqueVehicleTokenIssuer(b"sanitized-gbis-test-key-material" * 2)


def response(item_name: str, items: object) -> dict[str, object]:
    return {
        "response": {
            "msgHeader": {"resultCode": "00", "resultMessage": "정상"},
            "msgBody": {item_name: items},
        }
    }


def approved_capability(operation: str) -> Capability:
    return Capability(
        provider="GBIS_V2",
        operation=operation,
        documentation_state=DocumentationState.DOCUMENTED,
        key_verification_state=KeyVerificationState.KEY_VERIFIED,
        production_state=ProductionState.PRODUCTION_APPROVED,
        fixture_only=False,
    )


def runtime_evidence(operation: str, schema_version: str) -> tuple[RuntimeEvidence, ...]:
    return tuple(
        RuntimeEvidence(
            provider="GBIS_V2",
            operation=operation,
            kind=kind,
            evidence_id=f"gbis-{operation}-{kind.value.lower()}",
            artifact_sha256=DIGEST,
            version=(
                schema_version
                if kind is RuntimeEvidenceKind.RESPONSE_SCHEMA
                else "evidence-v1"
            ),
            issued_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=1),
        )
        for kind in RuntimeEvidenceKind
    )


def evidence_document(
    operations: tuple[tuple[str, str], ...] = KAKAO_GBIS_OPERATIONS,
) -> dict[str, object]:
    capabilities = [
        {
            "provider": provider,
            "operation": operation,
            "documentationState": "DOCUMENTED",
            "keyVerificationState": "KEY_VERIFIED",
            "productionState": "PRODUCTION_APPROVED",
            "fixtureOnly": False,
        }
        for provider, operation in operations
    ]
    runtime = []
    for provider, operation in operations:
        for kind in RuntimeEvidenceKind:
            runtime.append({
                "provider": provider,
                "operation": operation,
                "kind": kind.value,
                "evidenceId": f"{provider.lower()}-{operation}-{kind.value.lower()}",
                "artifactSha256": DIGEST,
                "version": (
                    KAKAO_GBIS_SCHEMA_VERSIONS[(provider, operation)]
                    if kind is RuntimeEvidenceKind.RESPONSE_SCHEMA
                    else "evidence-v1"
                ),
                "issuedAt": "2026-08-24T00:00:00Z",
                "expiresAt": "2026-08-26T00:00:00Z",
            })
    return {
        "version": "1.0",
        "capabilities": capabilities,
        "runtimeEvidence": runtime,
        "egressAttestation": {
            "evidenceId": "routing-egress-review",
            "artifactSha256": DIGEST,
            "version": "egress-v1",
            "issuedAt": "2026-08-24T00:00:00Z",
            "expiresAt": "2026-08-26T00:00:00Z",
            "enforcement": "EXTERNAL_PROXY_OR_FIREWALL",
        },
    }


class FakeTransport:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = body
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return HttpResponse(
            200,
            "application/json",
            json.dumps(self.body, ensure_ascii=False).encode("utf-8"),
        )


class GbisRawParserTests(unittest.TestCase):
    def test_arrival_list_prefers_seconds_and_preserves_slot_two_zero_seats(self) -> None:
        plate = "경기70바1234"
        raw = response("busArrivalList", [{
            "routeId": 5001,
            "stationId": "228000101",
            "predictTimeSec1": "61",
            "predictTime1": "9",
            "remainSeatCnt1": "-1",
            "vehId1": 7001,
            "plateNo1": plate,
            "crowded1": 4,
            "predictTimeSec2": "",
            "predictTime2": "3",
            "remainSeatCnt2": "0",
            "vehId2": "",
            "plateNo2": "경기70바9999",
        }])

        arrivals = parse_gbis_arrivals(
            raw, observed_at=NOW, token_issuer=ISSUER
        )

        self.assertEqual(len(arrivals), 2)
        self.assertTrue(all(isinstance(item, BusArrivalObservation) for item in arrivals))
        self.assertEqual(arrivals[0].eta_seconds, 61)
        self.assertIsNone(arrivals[0].remaining_seats)
        self.assertEqual(arrivals[0].vehicle_token, ISSUER.issue("GBIS_V2", "7001"))
        self.assertEqual(arrivals[1].eta_seconds, 180)
        self.assertEqual(arrivals[1].remaining_seats, 0)
        self.assertIsNone(arrivals[1].vehicle_token)
        self.assertNotIn(plate, repr(arrivals))

    def test_arrival_singleton_and_empty_shapes_are_supported(self) -> None:
        singleton = response("busArrivalList", {
            "routeId": "route-a",
            "stationId": "station-a",
            "predictTime1": 2,
            "remainSeatCnt1": " ",
        })
        self.assertEqual(
            parse_gbis_arrivals(
                singleton, observed_at=NOW, token_issuer=ISSUER
            )[0].eta_seconds,
            120,
        )
        for empty in (
            response("busArrivalList", []),
            response("busArrivalList", ""),
            {
                "response": {
                    "msgHeader": {"resultCode": 0},
                    "msgBody": {},
                }
            },
            {
                "response": {
                    "msgHeader": {"resultCode": "00"},
                    "msgBody": None,
                }
            },
        ):
            with self.subTest(empty=empty):
                self.assertEqual(
                    parse_gbis_arrivals(
                        empty, observed_at=NOW, token_issuer=ISSUER
                    ),
                    (),
                )

    def test_official_no_result_is_empty_but_other_errors_are_sanitized(self) -> None:
        no_result = {
            "response": {
                "msgHeader": {
                    "resultCode": "4",
                    "resultMessage": "결과가 존재하지 않습니다.",
                }
            }
        }
        self.assertEqual(
            parse_gbis_arrivals(
                no_result, observed_at=NOW, token_issuer=ISSUER
            ),
            (),
        )

        secret_message = "rejected service key SECRET-KEY"
        error = {
            "response": {
                "msgHeader": {
                    "resultCode": "30",
                    "resultMsg": secret_message,
                },
                "msgBody": {},
            }
        }
        with self.assertRaises(SchemaValidationError) as caught:
            parse_gbis_arrivals(error, observed_at=NOW, token_issuer=ISSUER)
        self.assertNotIn(secret_message, str(caught.exception))
        self.assertNotIn("SECRET-KEY", str(caught.exception))

    def test_locations_support_list_and_singleton_and_share_vehicle_join_token(self) -> None:
        item = {
            "routeId": 5001,
            "vehId": 7001,
            "stationSeq": "12",
            "x": "127.10",
            "y": "37.39",
            "plateNo": "경기70바1234",
            "crowded": 4,
        }
        singleton = parse_gbis_locations(
            response("busLocationList", item),
            observed_at=NOW,
            token_issuer=ISSUER,
        )
        listed = parse_gbis_locations(
            response("busLocationList", [item]),
            observed_at=NOW,
            token_issuer=ISSUER,
        )

        self.assertEqual(singleton, listed)
        self.assertIsInstance(singleton[0], BusLocationObservation)
        self.assertEqual(singleton[0].route_external_id, "5001")
        self.assertEqual(singleton[0].stop_sequence, 12)
        self.assertEqual(
            singleton[0].vehicle_token, ISSUER.issue("GBIS_V2", "7001")
        )
        self.assertEqual(
            parse_gbis_locations(
                response("busLocationList", []),
                observed_at=NOW,
                token_issuer=ISSUER,
            ),
            (),
        )

    def test_malformed_items_and_unaware_observation_fail_closed(self) -> None:
        malformed = response("busLocationList", ["not-an-object"])
        with self.assertRaises(SchemaValidationError):
            parse_gbis_locations(
                malformed, observed_at=NOW, token_issuer=ISSUER
            )
        with self.assertRaises(SchemaValidationError):
            parse_gbis_locations(
                response("busLocationList", []),
                observed_at=NOW.replace(tzinfo=None),
                token_issuer=ISSUER,
            )


class GbisAdapterIntegrationTests(unittest.TestCase):
    def test_live_arrival_uses_clock_observation_and_official_raw_parser(self) -> None:
        raw = response("busArrivalList", {
            "routeId": "5001",
            "stationId": "228000101",
            "predictTimeSec1": 45,
            "remainSeatCnt1": 0,
            "vehId1": "7001",
        })
        transport = FakeTransport(raw)
        adapter = GbisAdapter(
            transport,
            capabilities=CapabilityRegistry((approved_capability("arrivals"),)),
            credential=SensitiveValue("gbis-secret"),
            runtime_evidence=ProviderRuntimeEvidenceConfig(
                runtime_evidence("arrivals", GBIS_ARRIVALS_SCHEMA_VERSION)
            ),
            vehicle_token_issuer=ISSUER,
            clock=lambda: NOW,
        )

        result = adapter.arrivals(
            "228000101", deadline=Deadline.after_ms(1000, clock=lambda: 10.0)
        )

        self.assertIs(result.status, ProviderStatus.OK)
        self.assertEqual(result.schema_version, GBIS_ARRIVALS_SCHEMA_VERSION)
        self.assertEqual(result.observed_at, NOW)
        self.assertEqual(result.payload[0].observed_at, NOW)
        request = transport.requests[0]
        self.assertEqual(dict(request.query)["stationId"], "228000101")
        self.assertEqual(dict(request.query)["format"], "json")
        self.assertEqual(request.safe_summary()["query"]["serviceKey"], "***")

    def test_arrival_and_location_calls_always_receive_aware_clock_hint(self) -> None:
        class CaptureAdapter(GbisAdapter):
            def invoke(self, operation, call, *, deadline):
                return operation, call

        adapter = CaptureAdapter(None, clock=lambda: NOW)
        deadline = Deadline.after_ms(1000, clock=lambda: 10.0)
        for operation, call in (
            adapter.arrivals("station-a", deadline=deadline),
            adapter.locations("route-a", deadline=deadline),
        ):
            with self.subTest(operation=operation):
                self.assertEqual(call.observed_hint, NOW)
                self.assertIsNotNone(call.observed_hint.utcoffset())


class GbisProductionFactoryTests(unittest.TestCase):
    def test_factory_uses_only_existing_key_names_and_optional_proxy(self) -> None:
        kakao_secret = "kakao-secret-that-must-not-render"
        gbis_secret = "gbis-secret-that-must-not-render"
        environment = {
            "KAKAO_REST_API_KEY": kakao_secret,
            "GBIS_SERVICE_KEY": gbis_secret,
            "ROUTING_PROVIDER_EVIDENCE_JSON": json.dumps(evidence_document()),
            "ROUTING_PROVIDER_HTTPS_PROXY_URL": "http://proxy.example.test:3128",
        }
        with patch.dict(os.environ, environment, clear=True):
            config = build_kakao_gbis_config()

        self.assertEqual(set(config.binding_map), set(KAKAO_GBIS_OPERATIONS))
        self.assertEqual(
            {key for key in config.binding_map if key[0] == "GBIS_V2"},
            set(GBIS_LIVE_OPERATIONS),
        )
        self.assertIsInstance(config.gbis_vehicle_token_issuer, OpaqueVehicleTokenIssuer)
        rendered = repr(config) + repr(tuple(config.binding_map.values()))
        self.assertNotIn(kakao_secret, rendered)
        self.assertNotIn(gbis_secret, rendered)

        for key, binding in config.binding_map.items():
            expected = gbis_secret if key in GBIS_LIVE_OPERATIONS else kakao_secret
            self.assertEqual(
                binding.credential.value.reveal_for_transport(), expected
            )
            self.assertIsInstance(
                binding.transport.value._connection_factory,
                HttpsConnectProxyConnectionFactory,
            )

        suite = ProviderAdapterSuite.from_config(config)
        self.assertIs(
            suite.gbis.vehicle_token_issuer, config.gbis_vehicle_token_issuer
        )

    def test_factory_requires_exact_five_operation_evidence(self) -> None:
        document = evidence_document()
        document["capabilities"] = document["capabilities"][:-1]  # type: ignore[index]
        environment = {
            "KAKAO_REST_API_KEY": "kakao-secret",
            "GBIS_SERVICE_KEY": "gbis-secret",
            "ROUTING_PROVIDER_EVIDENCE_JSON": json.dumps(document),
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "exact Kakao and GBIS scope"):
                build_kakao_gbis_config()

    def test_factory_pins_both_verified_gbis_schema_versions(self) -> None:
        self.assertEqual(
            KAKAO_GBIS_SCHEMA_VERSIONS[("GBIS_V2", "arrivals")],
            GBIS_ARRIVALS_SCHEMA_VERSION,
        )
        self.assertEqual(
            KAKAO_GBIS_SCHEMA_VERSIONS[("GBIS_V2", "locations")],
            GBIS_LOCATIONS_SCHEMA_VERSION,
        )


if __name__ == "__main__":
    unittest.main()
