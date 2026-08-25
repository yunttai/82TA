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
        self.assertEqual(
            request["properties"]["preferences"],
            {"$ref": "#/components/schemas/PublicRouteSearchPreferences"},
        )
        preferences = self.public["components"]["schemas"]["PublicRouteSearchPreferences"]
        self.assertIn("allowedModes", preferences["properties"])
        self.assertNotIn("allowedModes", preferences["required"])
        private_preference = self.common["components"]["schemas"]["OptimizationPreference"]
        self.assertIn("avoidHighBusSeatRisk", private_preference["properties"])
        self.assertNotIn("avoidHighBusSeatRisk", private_preference["required"])
        capabilities = self.private["components"]["schemas"]["RoutingCapabilities"]
        self.assertIn("busIntelligenceCoverage", capabilities["properties"])
        self.assertNotIn("busIntelligenceCoverage", capabilities["required"])

    def test_route_leg_wait_and_travel_components_are_additive_optional_fields(self) -> None:
        route_leg = self.common["components"]["schemas"]["RouteLeg"]
        self.assertEqual(
            route_leg["properties"]["waitDuration"],
            {"$ref": "#/components/schemas/TimeEstimate"},
        )
        self.assertEqual(
            route_leg["properties"]["travelDuration"],
            {"$ref": "#/components/schemas/TimeEstimate"},
        )
        self.assertNotIn("waitDuration", route_leg["required"])
        self.assertNotIn("travelDuration", route_leg["required"])

        for filename, route_path in (
            ("routing-optimize-response.json", ("routes", 0)),
            ("public-route-search-response.json", ("baseline",)),
        ):
            value = json.loads(
                (ROOT / "src/contracts/openapi/examples" / filename).read_text(
                    encoding="utf-8"
                )
            )
            route = value
            for part in route_path:
                route = route[part]
            leg = route["legs"][0]
            self.assertEqual(
                leg["waitDuration"]["p50Seconds"]
                + leg["travelDuration"]["p50Seconds"],
                leg["duration"]["p50Seconds"],
                filename,
            )

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
        self.assertEqual(self.public["info"]["version"], "1.5.0")
        self.assertEqual(self.private["info"]["version"], "1.2.0")
        manifest = json.loads(
            (ROOT / "src/contracts/CONTEXT_MANIFEST.json").read_text(encoding="utf-8")
        )
        versions = json.loads(
            (ROOT / "src/contracts/versions/platform-versions.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["contextVersion"], "1.5.0")
        self.assertEqual(manifest["contractVersion"], "1.5.0")
        self.assertEqual(versions["contextVersion"], "1.5.0")
        self.assertEqual(versions["contractVersion"], "1.5.0")
        self.assertEqual(versions["databaseContractVersion"], "1.3.0")
        self.assertEqual(versions["codeRegistryVersion"], "1.3.0")
        self.assertEqual(versions["rankingPolicyVersion"], "rank-0.2.0")
        self.assertEqual(versions["strategyPolicyVersion"], "strategy-2.0.0")
        place_ref = self.common["components"]["schemas"]["PlaceRef"]
        self.assertIn("address", place_ref["properties"])
        self.assertNotIn("address", place_ref["required"])

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
            (
                "FavoriteJourneyFromPlacesInput",
                "public-favorite-journey-from-places-request.json",
            ),
            (
                "FavoriteJourneyFromPlacesResult",
                "public-favorite-journey-from-places-response.json",
            ),
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

    def test_atomic_favorite_from_places_operation_is_additive_and_idempotent(self) -> None:
        operation = self.public["paths"]["/api/v1/me/favorite-journeys/from-places"]["post"]
        self.assertEqual(operation["operationId"], "createFavoriteJourneyFromPlaces")
        self.assertEqual(operation["security"], [{"sessionCookie": []}])
        idempotency = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        self.assertTrue(idempotency["required"])
        self.assertEqual(idempotency["schema"]["minLength"], 8)
        self.assertEqual(
            set(operation["responses"]),
            {"201", "400", "401", "403", "409", "429"},
        )
        self.assertIn("PRECISE_LOCATION", operation["description"])
        self.assertIn("24 hours", operation["description"])
        self.assertIn("without creating location data", operation["description"])
        self.assertIn("without", operation["description"])
        self.assertIn("IDEMPOTENCY_CONFLICT", operation["description"])
        self.assertEqual(
            operation["responses"]["201"]["headers"]["Cache-Control"]["schema"]["const"],
            "no-store",
        )
        for code in (
            "INVALID_COORDINATE",
            "CONSTRAINT_OUT_OF_RANGE",
            "AUTH_REQUIRED",
            "SESSION_EXPIRED",
            "CONSENT_REQUIRED",
            "RATE_LIMITED",
        ):
            self.assertIn(code, operation["description"])

        receipt = self.public["components"]["schemas"]["FavoriteJourneyFromPlacesResult"]
        self.assertEqual(
            set(receipt["required"]),
            {
                "favoriteJourneyId",
                "originSavedPlaceId",
                "destinationSavedPlaceId",
                "createdAt",
                "idempotencyExpiresAt",
            },
        )
        self.assertEqual(set(receipt["properties"]), set(receipt["required"]))
        self.assertFalse(receipt["additionalProperties"])
        forbidden = {
            "favoriteJourney",
            "originSavedPlace",
            "destinationSavedPlace",
            "place",
            "coordinate",
            "label",
            "request",
            "response",
        }
        self.assertTrue(forbidden.isdisjoint(receipt["properties"]))

    def test_saved_place_location_consent_scope_and_problem_responses_are_explicit(self) -> None:
        paths = self.public["paths"]
        collection = paths["/api/v1/me/saved-places"]
        detail = paths["/api/v1/me/saved-places/{savedPlaceId}"]

        create = collection["post"]
        self.assertEqual(
            set(create["responses"]),
            {"201", "400", "401", "403", "429"},
        )
        for value in (
            "PRECISE_LOCATION",
            "INVALID_COORDINATE",
            "CONSTRAINT_OUT_OF_RANGE",
            "AUTH_REQUIRED",
            "SESSION_EXPIRED",
            "CONSENT_REQUIRED",
        ):
            self.assertIn(value, create["description"])

        update = detail["patch"]
        self.assertEqual(
            set(update["responses"]),
            {"200", "400", "401", "403", "404", "429"},
        )
        self.assertIn("PRECISE_LOCATION", update["description"])
        self.assertIn("only when", update["description"])
        self.assertIn("Label-only", update["description"])
        self.assertIn("isSensitive-only", update["description"])

        delete = detail["delete"]
        self.assertEqual(
            set(delete["responses"]),
            {"204", "401", "403", "404", "429"},
        )
        self.assertIn("PRECISE_LOCATION consent is not required", delete["description"])
        self.assertIn("other-owner resource is returned as 404", delete["description"])

    def test_favorite_location_write_quota_is_declared_only_on_mutations(self) -> None:
        paths = self.public["paths"]
        mutation_operations = (
            paths["/api/v1/me/saved-places"]["post"],
            paths["/api/v1/me/saved-places/{savedPlaceId}"]["patch"],
            paths["/api/v1/me/saved-places/{savedPlaceId}"]["delete"],
            paths["/api/v1/me/favorite-journeys"]["post"],
            paths["/api/v1/me/favorite-journeys/from-places"]["post"],
            paths["/api/v1/me/favorite-journeys/{favoriteJourneyId}"]["patch"],
            paths["/api/v1/me/favorite-journeys/{favoriteJourneyId}"]["delete"],
        )
        problem = {"$ref": "#/components/responses/Problem"}
        for operation in mutation_operations:
            self.assertEqual(operation["responses"]["429"], problem)

        self.assertNotIn(
            "429",
            paths["/api/v1/me/saved-places"]["get"]["responses"],
        )
        self.assertNotIn(
            "429",
            paths["/api/v1/me/favorite-journeys"]["get"]["responses"],
        )

    def test_legacy_favorite_crud_declares_producer_problem_statuses(self) -> None:
        paths = self.public["paths"]
        collection = paths["/api/v1/me/favorite-journeys"]
        detail = paths["/api/v1/me/favorite-journeys/{favoriteJourneyId}"]
        self.assertEqual(
            set(collection["post"]["responses"]),
            {"201", "400", "401", "403", "404", "429"},
        )
        self.assertEqual(
            set(detail["patch"]["responses"]),
            {"200", "400", "401", "403", "404", "429"},
        )
        self.assertEqual(
            set(detail["delete"]["responses"]),
            {"204", "401", "403", "404", "429"},
        )
        problem = {"$ref": "#/components/responses/Problem"}
        for operation, statuses in (
            (collection["post"], ("400", "401", "403", "404", "429")),
            (detail["patch"], ("400", "401", "403", "404", "429")),
            (detail["delete"], ("401", "403", "404", "429")),
        ):
            for status in statuses:
                self.assertEqual(operation["responses"][status], problem)

    def test_legacy_favorite_remains_valid_and_typed_conditions_are_strict(self) -> None:
        validator = load_example_validator()
        spec_path = ROOT / "src/contracts/openapi/service-public.v1.yaml"
        document = validator.load_yaml(spec_path)
        input_schema = validator.dereference(
            document["components"]["schemas"]["FavoriteJourneyInput"],
            document,
            spec_path,
        )
        legacy = {
            "nickname": "등교",
            "originSavedPlaceId": "71ddc751-95ac-45e1-ac93-1e64e6559f4e",
            "destinationSavedPlaceId": "548214e9-c4c8-4762-bea6-221e7c9873c0",
            "defaultConstraints": {"legacyClientField": "preserved"},
        }
        self.assertEqual(
            list(Draft202012Validator(input_schema, format_checker=FormatChecker()).iter_errors(legacy)),
            [],
        )
        output_schema = validator.dereference(
            document["components"]["schemas"]["FavoriteJourney"],
            document,
            spec_path,
        )
        legacy_output = {
            "id": "cd9fbe06-1eef-4f2f-9c92-3a2a197a5ac5",
            **legacy,
            "searchConditions": None,
            "createdAt": "2026-08-25T09:00:00+09:00",
        }
        self.assertEqual(
            list(Draft202012Validator(output_schema, format_checker=FormatChecker()).iter_errors(legacy_output)),
            [],
        )

        conditions_schema = validator.dereference(
            document["components"]["schemas"]["FavoriteJourneySearchConditionsV1"],
            document,
            spec_path,
        )
        valid = json.loads(
            (ROOT / "src/contracts/openapi/examples/public-favorite-journey-from-places-request.json")
            .read_text(encoding="utf-8")
        )["searchConditions"]
        conditions_validator = Draft202012Validator(
            conditions_schema,
            format_checker=FormatChecker(),
        )
        self.assertEqual(list(conditions_validator.iter_errors(valid)), [])
        for invalid in (
            {key: value for key, value in valid.items() if key != "departurePolicy"},
            {**valid, "departurePolicy": "SAVED_TIMESTAMP"},
            {**valid, "unknown": True},
            {**valid, "requestedRecommendations": []},
        ):
            self.assertTrue(list(conditions_validator.iter_errors(invalid)), invalid)

    def test_legacy_default_constraints_generated_type_remains_opaque(self) -> None:
        schemas = self.public["components"]["schemas"]
        for schema_name in (
            "FavoriteJourneyInput",
            "FavoriteJourney",
            "FavoriteJourneyUpdate",
        ):
            default_constraints = schemas[schema_name]["properties"]["defaultConstraints"]
            self.assertEqual(default_constraints["type"], "object")
            self.assertIs(default_constraints["additionalProperties"], True)
        self.assertIs(
            schemas["FavoriteJourneySearchConditionsV1"]["additionalProperties"],
            False,
        )

        generated = (
            ROOT / "src/generated/service-client-ts/schema.gen.ts"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(generated.count("[key: string]: unknown;"), 3)
        self.assertNotIn("defaultConstraints: Record<string, never>;", generated)
        self.assertNotIn("defaultConstraints?: Record<string, never>;", generated)
        self.assertNotIn("[key: string]: never;", generated)

    def test_route_search_request_summary_is_coordinate_and_provider_free(self) -> None:
        validator = load_example_validator()
        spec_path = ROOT / "src/contracts/openapi/service-public.v1.yaml"
        document = validator.load_yaml(spec_path)
        schema = validator.dereference(
            document["components"]["schemas"]["RouteSearchRequestSummary"],
            document,
            spec_path,
        )
        forbidden = {"coordinate", "coordinates", "address", "provider", "providerPlaceId", "regionCode"}
        self.assertTrue(forbidden.isdisjoint(schema["properties"]))
        summary = {
            "originDisplayName": "광교중앙역",
            "destinationDisplayName": "세종대학교",
            "departureTime": "2026-08-25T09:10:00+09:00",
            "arrivalDeadline": None,
            "taxiBudget": {"currency": "KRW", "maxAmount": 7000, "strict": True},
            "preferences": {
                "maxWalkSeconds": 7200,
                "maxTransfers": 8,
                "maxTaxiLegs": 3,
                "optimization": "BALANCED",
            },
        }
        summary_validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.assertEqual(list(summary_validator.iter_errors(summary)), [])
        self.assertTrue(
            list(summary_validator.iter_errors({**summary, "coordinate": {"lon": 127, "lat": 37}}))
        )

    def test_service_db_expansion_is_owner_local(self) -> None:
        dbml = (ROOT / "src/contracts/database/service-db.dbml").read_text(encoding="utf-8")
        ownership = load_yaml("src/contracts/database/schema-ownership.yaml")
        self.assertIn("Table authenticated_session", dbml)
        self.assertIn("Table data_rights_job", dbml)
        self.assertIn("Table favorite_creation_idempotency", dbml)
        self.assertIn("(user_id, key_digest) [unique", dbml)
        self.assertIn("request_fingerprint char(64)", dbml)
        self.assertIn("digest_key_version integer", dbml)
        self.assertIn("ix_fav_create_idemp_expiry", dbml)
        self.assertNotIn("ix_favorite_create_idempotency_expiry", dbml)
        self.assertIn("expires_at = created_at + interval '24 hours'", dbml)
        for forbidden in (
            "raw_idempotency_key",
            "request_body",
            "response_body",
            "coordinate geography",
        ):
            ledger = dbml.split("Table favorite_creation_idempotency", 1)[1].split(
                "\nTable ", 1
            )[0]
            self.assertNotIn(forbidden, ledger)
        tables = ownership["schemas"]["service"]["tables"]
        self.assertIn("authenticated_session", tables)
        self.assertIn("data_rights_job", tables)
        self.assertIn("favorite_creation_idempotency", tables)
        self.assertNotIn("authenticated_session", ownership["schemas"]["routing"]["tables"])
        self.assertNotIn(
            "favorite_creation_idempotency",
            ownership["schemas"]["routing"]["tables"],
        )


if __name__ == "__main__":
    unittest.main()
