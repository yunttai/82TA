from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[3]


def load_yaml(relative: str) -> dict:
    value = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object in {relative}")
    return value


def load_example_validator():
    path = ROOT / "src/scripts/validate_openapi_examples.py"
    spec = importlib.util.spec_from_file_location("contract_example_validator", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load canonical example validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ServiceContract11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.public = load_yaml("src/contracts/openapi/service-public.v1.yaml")
        cls.private = load_yaml("src/contracts/openapi/routing-private.v1.yaml")
        cls.common = load_yaml("src/contracts/openapi/common/components.v1.yaml")
        cls.codes = load_yaml("src/contracts/codes/reason-warning-error-codes.yaml")

    def test_public_completion_operations_are_present(self) -> None:
        paths = self.public["paths"]
        expected_methods = {
            "/api/v1/guest-sessions": {"post"},
            "/api/v1/session": {"get", "delete"},
            "/api/v1/me/saved-places/{savedPlaceId}": {"patch", "delete"},
            "/api/v1/me/favorite-journeys/{favoriteJourneyId}": {"patch", "delete"},
            "/api/v1/me/consents": {"get"},
            "/api/v1/me/consents/{consentType}": {"put"},
            "/api/v1/me/data-exports": {"post"},
            "/api/v1/me/data-exports/{jobId}": {"get"},
            "/api/v1/me/data-deletions": {"post"},
            "/api/v1/me/data-deletions/{jobId}": {"get"},
        }
        for path, methods in expected_methods.items():
            self.assertTrue(methods.issubset(paths[path]), path)
        self.assertTrue(paths["/api/v1/me/data"]["delete"]["deprecated"])

    def test_route_contract_documents_errors_and_owner_security(self) -> None:
        paths = self.public["paths"]
        create_responses = paths["/api/v1/route-searches"]["post"]["responses"]
        self.assertEqual(
            set(create_responses),
            {"200", "400", "403", "409", "422", "429", "502", "503", "504"},
        )
        problem = {"$ref": "#/components/responses/Problem"}
        self.assertEqual(create_responses["422"], problem)
        self.assertEqual(create_responses["504"], problem)
        self.assertEqual(self.codes["errorCodes"]["UNSUPPORTED_REGION"]["httpStatus"], 422)
        self.assertFalse(self.codes["errorCodes"]["UNSUPPORTED_REGION"]["retryable"])
        self.assertEqual(
            self.codes["errorCodes"]["ROUTING_DEADLINE_EXCEEDED"]["httpStatus"],
            504,
        )
        self.assertTrue(
            self.codes["errorCodes"]["ROUTING_DEADLINE_EXCEEDED"]["retryable"]
        )
        detail = paths["/api/v1/route-searches/{searchId}"]["get"]
        self.assertEqual(
            detail["security"],
            [{"sessionCookie": []}, {"guestToken": []}],
        )
        self.assertIn("403", detail["responses"])

    def test_place_suggestion_requires_two_characters(self) -> None:
        parameters = self.public["paths"]["/api/v1/places/suggest"]["get"]["parameters"]
        query = next(parameter for parameter in parameters if parameter["name"] == "query")
        self.assertEqual(query["schema"]["minLength"], 2)
        self.assertEqual(query["schema"]["maxLength"], 100)

    def test_place_operations_document_rate_limit_problem(self) -> None:
        problem_ref = {"$ref": "#/components/responses/Problem"}
        for path in (
            "/api/v1/places/suggest",
            "/api/v1/places/reverse-geocode",
        ):
            self.assertEqual(
                self.public["paths"][path]["get"]["responses"]["429"],
                problem_ref,
                path,
            )
        self.assertEqual(self.codes["errorCodes"]["RATE_LIMITED"]["httpStatus"], 429)

    def test_mapping_fields_are_optional_and_pass_through_capable(self) -> None:
        request = self.public["components"]["schemas"]["PublicRouteSearchRequest"]
        preferences = request["properties"]["preferences"]
        self.assertIn("allowedModes", preferences["properties"])
        self.assertNotIn("allowedModes", preferences["required"])
        private_preference = self.common["components"]["schemas"]["OptimizationPreference"]
        self.assertIn("avoidHighBusSeatRisk", private_preference["properties"])
        self.assertNotIn("avoidHighBusSeatRisk", private_preference["required"])
        capabilities = self.private["components"]["schemas"]["RoutingCapabilities"]
        self.assertIn("busIntelligenceCoverage", capabilities["properties"])
        self.assertNotIn("busIntelligenceCoverage", capabilities["required"])

    def test_existing_request_required_sets_remain_compatible(self) -> None:
        request = self.public["components"]["schemas"]["PublicRouteSearchRequest"]
        self.assertEqual(
            request["required"],
            [
                "origin",
                "destination",
                "departure",
                "taxiBudget",
                "preferences",
                "requestedRecommendations",
            ],
        )
        self.assertEqual(
            self.private["components"]["schemas"]["OptimizeRouteRequest"]
            ["properties"]["contractVersion"]["const"],
            "1.0",
        )
        self.assertEqual(self.public["info"]["version"], "1.3.0")
        self.assertEqual(self.private["info"]["version"], "1.1.0")
        manifest = json.loads(
            (ROOT / "src/contracts/CONTEXT_MANIFEST.json").read_text(encoding="utf-8")
        )
        versions = json.loads(
            (ROOT / "src/contracts/versions/platform-versions.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["contextVersion"], "1.3.0")
        self.assertEqual(manifest["contractVersion"], "1.3.0")
        self.assertEqual(versions["contextVersion"], "1.3.0")
        self.assertEqual(versions["contractVersion"], "1.3.0")
        self.assertEqual(versions["databaseContractVersion"], "1.2.0")
        self.assertEqual(versions["codeRegistryVersion"], "1.3.0")
        self.assertEqual(versions["rankingPolicyVersion"], "rank-0.1.1")

    def test_registration_inline_example_matches_its_schema(self) -> None:
        example = self.public["paths"]["/api/v1/auth/register"]["post"]["requestBody"][
            "content"
        ]["application/json"]["example"]
        schema = self.public["components"]["schemas"]["EmailRegistrationInput"]
        errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(example)
        )
        self.assertEqual(errors, [])

    def test_new_problem_codes_have_expected_status(self) -> None:
        errors = self.codes["errorCodes"]
        self.assertEqual(errors["CONSENT_REQUIRED"]["httpStatus"], 403)
        self.assertEqual(errors["ARRIVE_BY_UNSUPPORTED"]["httpStatus"], 400)
        self.assertEqual(errors["PREFERENCE_VERSION_CONFLICT"]["httpStatus"], 409)

    def test_new_examples_validate_against_canonical_schemas(self) -> None:
        validator = load_example_validator()
        cases = [
            ("GuestSessionCredential", "public-guest-session-response.json"),
            ("ConsentRecord", "public-consent-response.json"),
            ("DataRightsJob", "public-data-rights-job-response.json"),
        ]
        for schema, example in cases:
            self.assertEqual(
                validator.validate("service-public.v1.yaml", schema, example),
                [],
                example,
            )

    def test_saved_place_and_favorite_outputs_are_satisfiable(self) -> None:
        validator = load_example_validator()
        spec_path = ROOT / "src/contracts/openapi/service-public.v1.yaml"
        document = validator.load_yaml(spec_path)
        cases = {
            "SavedPlace": {
                "id": "71ddc751-95ac-45e1-ac93-1e64e6559f4e",
                "label": "학교",
                "place": {
                    "displayName": "명지대학교 자연캠퍼스",
                    "coordinate": {"lon": 127.187456, "lat": 37.222345},
                    "provider": "KAKAO_LOCAL",
                    "providerPlaceId": "example-origin",
                },
                "isSensitive": True,
                "createdAt": "2026-08-23T07:30:00+09:00",
                "updatedAt": "2026-08-23T07:40:00+09:00",
            },
            "FavoriteJourney": {
                "id": "cd9fbe06-1eef-4f2f-9c92-3a2a197a5ac5",
                "nickname": "등교",
                "originSavedPlaceId": "71ddc751-95ac-45e1-ac93-1e64e6559f4e",
                "destinationSavedPlaceId": "548214e9-c4c8-4762-bea6-221e7c9873c0",
                "defaultConstraints": {"maxWalkSeconds": 900},
                "createdAt": "2026-08-23T07:30:00+09:00",
                "updatedAt": "2026-08-23T07:40:00+09:00",
            },
        }
        for schema_name, instance in cases.items():
            schema = validator.dereference(
                document["components"]["schemas"][schema_name],
                document,
                spec_path,
            )
            errors = list(
                Draft202012Validator(
                    schema, format_checker=FormatChecker()
                ).iter_errors(instance)
            )
            self.assertEqual(errors, [], schema_name)

    def test_saved_place_and_favorite_outputs_reject_invalid_shapes(self) -> None:
        validator = load_example_validator()
        spec_path = ROOT / "src/contracts/openapi/service-public.v1.yaml"
        document = validator.load_yaml(spec_path)
        invalid_cases = {
            "SavedPlace": {
                "label": "학교",
                "place": {
                    "displayName": "명지대학교 자연캠퍼스",
                    "coordinate": {"lon": 127.187456, "lat": 37.222345},
                },
                "createdAt": "2026-08-23T07:30:00+09:00",
                "rawProviderPayload": {},
            },
            "FavoriteJourney": {
                "id": "cd9fbe06-1eef-4f2f-9c92-3a2a197a5ac5",
                "nickname": "등교",
                "originSavedPlaceId": "not-a-uuid",
                "destinationSavedPlaceId": "548214e9-c4c8-4762-bea6-221e7c9873c0",
                "defaultConstraints": {},
                "createdAt": "2026-08-23T07:30:00+09:00",
                "unexpected": True,
            },
        }
        for schema_name, instance in invalid_cases.items():
            schema = validator.dereference(
                document["components"]["schemas"][schema_name],
                document,
                spec_path,
            )
            errors = list(
                Draft202012Validator(
                    schema, format_checker=FormatChecker()
                ).iter_errors(instance)
            )
            self.assertTrue(errors, schema_name)

    def test_service_db_expansion_is_owner_local(self) -> None:
        dbml = (ROOT / "src/contracts/database/service-db.dbml").read_text(encoding="utf-8")
        ownership = load_yaml("src/contracts/database/schema-ownership.yaml")
        self.assertIn("Table authenticated_session", dbml)
        self.assertIn("Table data_rights_job", dbml)
        tables = ownership["schemas"]["service"]["tables"]
        self.assertIn("authenticated_session", tables)
        self.assertIn("data_rights_job", tables)
        self.assertNotIn("authenticated_session", ownership["schemas"]["routing"]["tables"])


if __name__ == "__main__":
    unittest.main()
