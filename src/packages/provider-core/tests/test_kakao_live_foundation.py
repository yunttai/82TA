from __future__ import annotations

from datetime import datetime, timezone
from importlib import resources
import json
import os
import unittest
from unittest.mock import patch

from provider_core import (
    Coordinate,
    ENDPOINT_SPECS,
    KAKAO_BASELINE_OPERATIONS,
    KAKAO_BASELINE_SCHEMA_VERSIONS,
    KAKAO_GBIS_OPERATIONS,
    PROVIDER_OPERATION_KEY_ENV,
    ProviderAdapterSuite,
    ProviderFixtureScenario,
    ProviderStatus,
    SensitiveValue,
    TransitSearchRequest,
    build_kakao_baseline_config,
)
from provider_core.http import HttpResponse
from provider_core.capabilities import FOUNDATION_DOCUMENTED_OPERATIONS
from provider_core.kakao_mobility import KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION
from provider_core.kakao_raw import parse_kakao_public_transit
from provider_core.named import (
    KakaoMobilityDirectionsAdapter,
    KakaoTransitAdapter,
    KakaoWalkAdapter,
)
from provider_core.probe import ProbeState, probe_kakao_operation
from provider_core.resilience import Deadline
from provider_core.runtime import RuntimeEvidenceKind


NOW = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64


def evidence_document(*, approved: bool = True) -> dict[str, object]:
    versions = KAKAO_BASELINE_SCHEMA_VERSIONS
    capabilities = [
        {
            "provider": provider,
            "operation": operation,
            "documentationState": "DOCUMENTED",
            "keyVerificationState": "KEY_VERIFIED" if approved else "UNVERIFIED",
            "productionState": "PRODUCTION_APPROVED" if approved else "UNAPPROVED",
            "fixtureOnly": not approved,
        }
        for provider, operation in KAKAO_BASELINE_OPERATIONS
    ]
    runtime = []
    for provider, operation in KAKAO_BASELINE_OPERATIONS:
        for kind in RuntimeEvidenceKind:
            runtime.append({
                "provider": provider,
                "operation": operation,
                "kind": kind.value,
                "evidenceId": f"{provider.lower()}-{operation}-{kind.value.lower()}",
                "artifactSha256": DIGEST,
                "version": versions[(provider, operation)] if kind is RuntimeEvidenceKind.RESPONSE_SCHEMA else "evidence-v1",
                "issuedAt": "2026-08-23T00:00:00Z",
                "expiresAt": "2026-08-25T00:00:00Z",
            })
    return {
        "version": "1.0",
        "capabilities": capabilities,
        "runtimeEvidence": runtime,
        "egressAttestation": {
            "evidenceId": "routing-egress-review",
            "artifactSha256": DIGEST,
            "version": "egress-v1",
            "issuedAt": "2026-08-23T00:00:00Z",
            "expiresAt": "2026-08-25T00:00:00Z",
            "enforcement": "EXTERNAL_PROXY_OR_FIREWALL",
        },
    }


class FakeTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return self.response


def success_body(filename: str, operation: str) -> dict[str, object]:
    document = json.loads(
        resources.files("provider_core").joinpath("fixtures", filename).read_text(encoding="utf-8")
    )
    return document["operations"][operation]["success"]["body"]


class KakaoVendorRawTests(unittest.TestCase):
    def test_live_adapters_build_only_official_fixed_query_names(self) -> None:
        class CaptureTransit(KakaoTransitAdapter):
            def invoke(self, operation, call, *, deadline):
                return operation, call

        class CaptureWalk(KakaoWalkAdapter):
            def invoke(self, operation, call, *, deadline):
                return operation, call

        class CaptureDirections(KakaoMobilityDirectionsAdapter):
            def invoke(self, operation, call, *, deadline):
                return operation, call

        request = TransitSearchRequest(
            Coordinate(127.1, 37.39), Coordinate(127.11, 37.4), NOW
        )
        deadline = Deadline.after_ms(1000, clock=lambda: 10.0)
        _, transit = CaptureTransit().search(request, deadline=deadline)
        _, walk = CaptureWalk().route(request, deadline=deadline)
        _, directions = CaptureDirections().route(request, deadline=deadline)
        route_names = {"start_x", "start_y", "end_x", "end_y", "input_coord", "output_coord"}
        self.assertEqual(set(dict(transit.query)), route_names)
        self.assertEqual(set(dict(walk.query)), route_names | {"route_mode"})
        self.assertEqual(
            set(dict(directions.query)),
            {
                "origin",
                "destination",
                "priority",
                "car_fuel",
                "car_hipass",
                "alternatives",
                "road_details",
                "summary",
            },
        )
        for call in (transit, walk, directions):
            self.assertEqual(call.effective_at, NOW)
            self.assertIsNone(call.observed_hint)

    def test_sanitized_vendor_raw_fixtures_normalize_without_raw_dicts(self) -> None:
        cases = (
            (KakaoTransitAdapter(None), "search_current"),
            (KakaoWalkAdapter(None), "route"),
            (KakaoMobilityDirectionsAdapter(None), "route_current"),
        )
        for adapter, operation in cases:
            with self.subTest(operation=operation):
                result = adapter.fixture(operation, ProviderFixtureScenario.SUCCESS)
                self.assertIs(result.status, ProviderStatus.OK)
                self.assertGreater(result.normalized_count, 0)
                self.assertTrue(all(not isinstance(item, dict) for item in result.payload))
                self.assertEqual(
                    result.schema_version,
                    adapter.endpoint_spec(operation).response_schema_version,
                )

    def test_live_transit_residual_becomes_bounded_access_egress_connectors(self) -> None:
        raw = success_body("named_kakao_transit.json", "search_current")
        route = raw["routes"][0]
        route["properties"]["totalDistance"] += 421
        route["properties"]["totalTime"] += 387
        route["properties"]["fare"] = {"min": 1_450, "max": 2_900}
        for step in route["steps"]:
            if step["properties"]["type"] == "WALKING":
                step["properties"].pop("vehicles", None)
        raw["routes"].append(json.loads(json.dumps(route)))
        raw["properties"]["total"] = len(raw["routes"])
        origin = Coordinate(127.09, 37.38)
        destination = Coordinate(127.12, 37.41)

        itineraries = parse_kakao_public_transit(
            raw,
            effective_at=NOW,
            origin=origin,
            destination=destination,
            maximum_itineraries=1,
        )

        self.assertEqual(len(itineraries), 1)
        itinerary = itineraries[0]
        self.assertEqual(itinerary.legs[0].from_stop.coordinate, origin)
        self.assertEqual(itinerary.legs[-1].to_stop.coordinate, destination)
        self.assertEqual(
            sum(item.distance_meters for item in itinerary.legs),
            route["properties"]["totalDistance"],
        )
        self.assertEqual(
            sum(item.duration.p50_seconds for item in itinerary.legs),
            route["properties"]["totalTime"],
        )
        self.assertTrue(
            any(item.mode.value == "WALK" for item in itinerary.legs)
        )
        transit_fares = [
            item.fare
            for item in itinerary.legs
            if item.mode.value in {"BUS", "SUBWAY"}
            and item.fare.upper_krw > 0
        ]
        self.assertEqual(len(transit_fares), 1)
        self.assertEqual(
            (
                transit_fares[0].expected_krw,
                transit_fares[0].lower_krw,
                transit_fares[0].upper_krw,
            ),
            (2_900, 1_450, 2_900),
        )
        self.assertTrue(
            all(
                previous.to_stop.coordinate == current.from_stop.coordinate
                for previous, current in zip(itinerary.legs, itinerary.legs[1:])
            )
        )

    def test_probe_is_fixed_scope_and_never_returns_key_or_raw_payload(self) -> None:
        raw = success_body("named_kakao_transit.json", "search_current")
        transport = FakeTransport(HttpResponse(200, "application/json", json.dumps(raw).encode()))
        secret = "secret-that-must-never-render"
        result = probe_kakao_operation(
            "transit",
            transport=transport,
            credential=SensitiveValue(secret),
            clock=lambda: NOW,
        )
        self.assertIs(result.state, ProbeState.KEY_VERIFIED)
        self.assertGreater(result.normalized_count, 0)
        rendered = json.dumps(result.as_sanitized_dict(), sort_keys=True)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("routes", rendered)
        request = transport.requests[0]
        self.assertEqual(dict(request.query)["start_x"], 127.11119217)
        self.assertEqual(request.safe_summary()["headers"]["Authorization"], "***")

    def test_probe_distinguishes_key_rejection_and_schema_drift(self) -> None:
        rejected = probe_kakao_operation(
            "walk",
            transport=FakeTransport(HttpResponse(401, "application/json", b"{}")),
            credential=SensitiveValue("secret"),
            clock=lambda: NOW,
        )
        self.assertIs(rejected.state, ProbeState.FAILED)
        drift = probe_kakao_operation(
            "directions",
            transport=FakeTransport(HttpResponse(200, "application/json", b'{"routes":[]}')),
            credential=SensitiveValue("secret"),
            clock=lambda: NOW,
        )
        self.assertIs(drift.state, ProbeState.INDETERMINATE)
        self.assertEqual(drift.message_code, "RESPONSE_SCHEMA_MISMATCH")

    def test_directions_probe_matches_the_executable_current_route_contract(self) -> None:
        raw = success_body("named_kakao_mobility.json", "route_current")
        transport = FakeTransport(
            HttpResponse(200, "application/json", json.dumps(raw).encode())
        )

        result = probe_kakao_operation(
            "directions",
            transport=transport,
            credential=SensitiveValue("secret"),
            clock=lambda: NOW,
        )

        self.assertIs(result.state, ProbeState.KEY_VERIFIED)
        self.assertEqual(
            result.schema_version, KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION
        )
        spec = next(
            item
            for item in ENDPOINT_SPECS
            if (item.provider, item.operation)
            == ("KAKAO_DIRECTIONS", "route_current")
        )
        self.assertEqual(result.schema_version, spec.response_schema_version)
        self.assertEqual(
            dict(transport.requests[0].query),
            {
                "origin": "127.11119217,37.39477123",
                "destination": "127.12628814,37.41993056",
                "priority": "TIME",
                "car_fuel": "GASOLINE",
                "car_hipass": "false",
                "alternatives": "false",
                "road_details": "false",
                "summary": "false",
            },
        )


class KakaoProductionFactoryTests(unittest.TestCase):
    def environment(self, document: dict[str, object]) -> dict[str, str]:
        return {
            "KAKAO_REST_API_KEY": "rest-secret",
            "ROUTING_PROVIDER_EVIDENCE_JSON": json.dumps(document),
        }

    def test_canonical_key_mapping_covers_every_documented_operation(self) -> None:
        self.assertEqual(
            set(PROVIDER_OPERATION_KEY_ENV),
            set(FOUNDATION_DOCUMENTED_OPERATIONS),
        )
        self.assertEqual(
            set(PROVIDER_OPERATION_KEY_ENV.values()),
            {
                "KAKAO_REST_API_KEY",
                "GBIS_SERVICE_KEY",
                "GITS_API_KEY",
                "TMAP_APP_KEY",
                "ODSAY_API_KEY",
            },
        )
        self.assertEqual(
            {PROVIDER_OPERATION_KEY_ENV[operation] for operation in KAKAO_BASELINE_OPERATIONS},
            {"KAKAO_REST_API_KEY"},
        )

    def test_exact_external_evidence_builds_operation_scoped_config(self) -> None:
        with patch.dict(os.environ, self.environment(evidence_document()), clear=True):
            config = build_kakao_baseline_config()
        self.assertEqual(set(config.binding_map), set(KAKAO_BASELINE_OPERATIONS))
        self.assertNotIn("rest-secret", repr(config))
        suite = ProviderAdapterSuite.from_config(config)
        self.assertFalse(suite.shared_configuration_quarantined)
        verified_specs = {
            (spec.provider, spec.operation): spec.response_schema_version
            for spec in ENDPOINT_SPECS if spec.response_schema_verified
        }
        self.assertEqual(set(verified_specs), set(KAKAO_GBIS_OPERATIONS))

    def test_key_presence_does_not_infer_approval(self) -> None:
        with patch.dict(os.environ, self.environment(evidence_document(approved=False)), clear=True):
            config = build_kakao_baseline_config()
        self.assertTrue(all(not item.enabled for item in config.capabilities.all()))

    def test_schema_evidence_mismatch_and_unknown_fields_fail_closed(self) -> None:
        document = evidence_document()
        document["runtimeEvidence"][2]["version"] = "wrong-schema"  # type: ignore[index]
        with patch.dict(os.environ, self.environment(document), clear=True):
            with self.assertRaisesRegex(ValueError, "schema evidence version mismatches"):
                build_kakao_baseline_config()
        document = evidence_document()
        document["unexpected"] = True
        with patch.dict(os.environ, self.environment(document), clear=True):
            with self.assertRaisesRegex(ValueError, "schema mismatch"):
                build_kakao_baseline_config()


if __name__ == "__main__":
    unittest.main()
