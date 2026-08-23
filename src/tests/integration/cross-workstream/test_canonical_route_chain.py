"""Cross-workstream proof that the four canonical examples form one R1 chain."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import yaml


CURRENT_DIRECTORY = Path(__file__).resolve().parent
if str(CURRENT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIRECTORY))

from _canonical_route_chain import (  # noqa: E402
    CANONICAL_SEARCH_ID,
    PRIVATE_REQUEST_PATH,
    PRIVATE_RESPONSE_PATH,
    PUBLIC_REQUEST_PATH,
    PUBLIC_RESPONSE_PATH,
    REPOSITORY_ROOT,
    build_chain,
    canonical_application,
)
from journeys.gateway import PUBLIC_ROUTING_PROBLEM_ALLOWLIST  # noqa: E402
from routing_api.application import _semantic_response_is_valid  # noqa: E402
from routing_api.contract import CanonicalContractValidator  # noqa: E402
from routing_domain import RankingPolicy  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


class CanonicalRouteChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        (
            cls.actual_public_request,
            cls.actual_private_request,
            cls.actual_private_response,
            cls.actual_public_response,
        ) = build_chain()
        cls.public_request = _load(PUBLIC_REQUEST_PATH)
        cls.private_request = _load(PRIVATE_REQUEST_PATH)
        cls.private_response = _load(PRIVATE_RESPONSE_PATH)
        cls.public_response = _load(PUBLIC_RESPONSE_PATH)
        cls.registry = yaml.safe_load(
            (
                REPOSITORY_ROOT
                / "src/contracts/codes/reason-warning-error-codes.yaml"
            ).read_text(encoding="utf-8")
        )

    def test_examples_are_exact_translator_producer_projection_chain(self) -> None:
        self.assertEqual(self.actual_public_request, self.public_request)
        self.assertEqual(self.actual_private_request, self.private_request)
        self.assertEqual(self.actual_private_response, self.private_response)
        self.assertEqual(self.actual_public_response, self.public_response)
        self.assertNotEqual(
            self.public_response["searchId"],
            self.private_response["requestId"],
        )
        self.assertEqual(self.public_response["searchId"], CANONICAL_SEARCH_ID)
        self.assertEqual(
            self.public_response["history"],
            {
                "saved": False,
                "ownerKind": "GUEST",
                "retainedUntil": self.public_response["expiresAt"],
            },
        )

    def test_private_producer_serialization_is_stable_across_parallel_runs(self) -> None:
        expected = self.actual_private_response
        for _ in range(12):
            self.assertEqual(build_chain()[2], expected)

    def test_private_example_satisfies_producer_semantics_and_budget(self) -> None:
        response = self.private_response
        request = self.private_request
        self.assertTrue(_semantic_response_is_valid(response, request))
        route_ids = {route["routeId"] for route in response["routes"]}
        recommendation_ids = {
            route_id
            for route_id in response["recommendations"].values()
            if route_id is not None
        }
        self.assertTrue(response["routes"])
        self.assertTrue(recommendation_ids <= route_ids)
        self.assertTrue(set(response["paretoRouteIds"]) <= route_ids)

        taxi_budget = request["constraints"]["taxiBudget"]["maxAmount"]
        for route in response["routes"]:
            self.assertGreaterEqual(
                route["totalDuration"]["p90Seconds"],
                route["totalDuration"]["p50Seconds"],
            )
            taxi_upper = sum(
                leg["fare"]["upper"]
                for leg in route["legs"]
                if leg["mode"] == "TAXI"
            )
            self.assertEqual(route["taxiCost"]["upper"], taxi_upper)
            self.assertLessEqual(taxi_upper, taxi_budget)
            previous_end: datetime | None = None
            previous_coordinate: dict[str, float] | None = None
            for leg in route["legs"]:
                start = datetime.fromisoformat(leg["expectedStartAt"])
                end = datetime.fromisoformat(leg["expectedEndAt"])
                self.assertLessEqual(start, end)
                self.assertGreaterEqual(
                    leg["duration"]["p90Seconds"],
                    leg["duration"]["p50Seconds"],
                )
                if previous_end is not None:
                    self.assertGreaterEqual(start, previous_end)
                    self.assertEqual(leg["from"]["coordinate"], previous_coordinate)
                previous_end = end
                previous_coordinate = leg["to"]["coordinate"]

    def test_private_example_provenance_is_causal(self) -> None:
        generated_at = datetime.fromisoformat(self.private_response["generatedAt"])
        provenance = [
            item
            for route in self.private_response["routes"]
            for item in (
                *route["provenance"],
                *(
                    entry
                    for leg in route["legs"]
                    for entry in leg["provenance"]
                ),
            )
        ]
        self.assertTrue(provenance)
        for item in provenance:
            received_at = datetime.fromisoformat(item["receivedAt"])
            self.assertLessEqual(received_at, generated_at)
            if item["observedAt"] is not None:
                observed_at = datetime.fromisoformat(item["observedAt"])
                self.assertLessEqual(observed_at, received_at)
            if item["ageSeconds"] is not None:
                self.assertGreaterEqual(item["ageSeconds"], 0)

    def test_all_emitted_codes_are_registered(self) -> None:
        registered = (
            set(self.registry["reasonCodes"])
            | set(self.registry["warningCodes"])
            | set(self.registry["errorCodes"])
        )
        emitted = set(self.private_response["warningCodes"])
        for route in self.private_response["routes"]:
            emitted.update(route["reasonCodes"])
            emitted.update(route["warningCodes"])
        emitted.update(
            item["messageCode"]
            for item in self.private_response["providerStatus"]
            if item["messageCode"] is not None
        )
        self.assertTrue(emitted <= registered, sorted(emitted - registered))
        self.assertNotIn("NO_SEAT_DATA_FOR_ROUTE", emitted)

    def test_metadata_wire_and_ranking_versions_are_coherent(self) -> None:
        public_spec = yaml.safe_load(
            (REPOSITORY_ROOT / "src/contracts/openapi/service-public.v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        private_spec = yaml.safe_load(
            (REPOSITORY_ROOT / "src/contracts/openapi/routing-private.v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        manifest = _load(REPOSITORY_ROOT / "src/contracts/CONTEXT_MANIFEST.json")
        versions = _load(
            REPOSITORY_ROOT / "src/contracts/versions/platform-versions.json"
        )
        validator = CanonicalContractValidator()
        public_metadata_versions = {
            public_spec["info"]["version"],
            manifest["contextVersion"],
            manifest["contractVersion"],
            versions["contextVersion"],
            versions["contractVersion"],
        }
        self.assertEqual(public_metadata_versions, {"1.3.0"})
        private_metadata_versions = {
            private_spec["info"]["version"],
            validator.contract_version,
            canonical_application().version()["contractVersion"],
        }
        self.assertEqual(private_metadata_versions, {"1.1.0"})
        self.assertEqual(versions["databaseContractVersion"], "1.2.0")
        self.assertEqual(versions["codeRegistryVersion"], "1.3.0")
        self.assertEqual(self.private_request["contractVersion"], "1.0")
        self.assertEqual(self.private_response["contractVersion"], "1.0")
        ranking_versions = {
            versions["rankingPolicyVersion"],
            RankingPolicy().version,
            canonical_application().version()["rankingPolicyVersion"],
            self.private_response["computation"]["rankingPolicyVersion"],
        }
        self.assertEqual(ranking_versions, {"rank-0.1.1"})

    def test_public_contract_documents_complete_safe_error_matrix(self) -> None:
        public_spec = yaml.safe_load(
            (REPOSITORY_ROOT / "src/contracts/openapi/service-public.v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        responses = public_spec["paths"]["/api/v1/route-searches"]["post"][
            "responses"
        ]
        self.assertEqual(
            set(responses),
            {"200", "400", "403", "409", "422", "429", "502", "503", "504"},
        )
        problem = {"$ref": "#/components/responses/Problem"}
        self.assertEqual(responses["422"], problem)
        self.assertEqual(responses["504"], problem)
        self.assertEqual(
            self.registry["errorCodes"]["UNSUPPORTED_REGION"],
            {"httpStatus": 422, "retryable": False},
        )
        self.assertEqual(
            self.registry["errorCodes"]["ROUTING_DEADLINE_EXCEEDED"],
            {"httpStatus": 504, "retryable": True},
        )
        for status, codes in PUBLIC_ROUTING_PROBLEM_ALLOWLIST.items():
            for code in codes:
                self.assertIn(code, self.registry["errorCodes"])
                self.assertEqual(
                    self.registry["errorCodes"][code]["httpStatus"],
                    status,
                )

    def test_public_projection_contains_no_private_or_identity_channels(self) -> None:
        keys = set(_keys(self.public_response))
        self.assertTrue(
            {
                "providerStatus",
                "modelVersions",
                "computation",
                "messageCode",
                "fingerprint",
                "schemaVersion",
                "rawResponse",
                "userId",
                "email",
                "guestToken",
                "providerPlaceId",
            }.isdisjoint(keys)
        )
        private_keys = set(_keys(self.private_request))
        self.assertTrue(
            {"userId", "email", "guestToken", "providerPlaceId", "displayName"}.isdisjoint(
                private_keys
            )
        )


if __name__ == "__main__":
    unittest.main()
