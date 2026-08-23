from datetime import datetime
import unittest

from provider_core.capabilities import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
    foundation_capability_registry,
)
from provider_core.validation import (
    EndpointRule,
    FixedEndpointAllowlist,
    InputValidationError,
    ObjectSchema,
    SchemaValidationError,
    is_non_negative_int,
    is_string,
)


class CapabilityTests(unittest.TestCase):
    def test_missing_capability_is_false_and_unverified(self) -> None:
        capability = CapabilityRegistry().get("GBIS", "arrivals")
        self.assertFalse(capability.enabled)
        self.assertEqual(capability.key_verification_state, KeyVerificationState.UNVERIFIED)
        self.assertEqual(capability.production_state, ProductionState.UNAPPROVED)
        self.assertTrue(capability.fixture_only)

    def test_documented_or_key_verified_alone_is_not_enabled(self) -> None:
        registry = CapabilityRegistry((Capability(
            "GBIS", "arrivals",
            DocumentationState.DOCUMENTED,
            KeyVerificationState.KEY_VERIFIED,
            ProductionState.UNAPPROVED,
            fixture_only=False,
        ),))
        self.assertFalse(registry.enabled("GBIS", "arrivals"))

    def test_fixture_only_cannot_claim_runtime_capability(self) -> None:
        capability = Capability(
            "fixture", "search",
            DocumentationState.DOCUMENTED,
            KeyVerificationState.KEY_VERIFIED,
            ProductionState.PRODUCTION_APPROVED,
            fixture_only=True,
        )
        self.assertFalse(capability.enabled)

    def test_foundation_live_operations_are_documented_but_disabled(self) -> None:
        capabilities = foundation_capability_registry().all()
        self.assertGreater(len(capabilities), 0)
        for capability in capabilities:
            self.assertEqual(capability.documentation_state, DocumentationState.DOCUMENTED)
            self.assertEqual(capability.key_verification_state, KeyVerificationState.UNVERIFIED)
            self.assertEqual(capability.production_state, ProductionState.UNAPPROVED)
            self.assertFalse(capability.enabled)


class ValidationTests(unittest.TestCase):
    def test_allowlist_rejects_request_selected_url(self) -> None:
        allowlist = FixedEndpointAllowlist(EndpointRule("provider", "route", "https://api.example.invalid/v1/route"))
        self.assertEqual(allowlist.resolve("provider", "route"), "https://api.example.invalid/v1/route")
        with self.assertRaises(InputValidationError):
            allowlist.assert_exact("provider", "route", "https://attacker.invalid/v1/route")

    def test_endpoint_credentials_and_query_are_forbidden(self) -> None:
        with self.assertRaises(ValueError):
            EndpointRule("provider", "route", "https://secret@example.invalid/path")
        with self.assertRaises(ValueError):
            EndpointRule("provider", "route", "https://example.invalid/path?url=other")

    def test_strict_schema_rejects_missing_unknown_and_wrong_type(self) -> None:
        schema = ObjectSchema(required={"id": is_string, "count": is_non_negative_int})
        with self.assertRaises(SchemaValidationError):
            schema.validate({"id": "x"})
        with self.assertRaises(SchemaValidationError):
            schema.validate({"id": "x", "count": 1, "secret": "leak"})
        with self.assertRaises(SchemaValidationError):
            schema.validate({"id": "x", "count": "1"})


if __name__ == "__main__":
    unittest.main()
