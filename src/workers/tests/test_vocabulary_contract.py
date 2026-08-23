from pathlib import Path
import unittest

import yaml

from routing_worker.vocabulary import (
    CANONICAL_DEPLOYMENT_ENVIRONMENTS,
    CANONICAL_MODEL_PURPOSES,
    PROCESS_RUNTIME_ENVIRONMENTS,
    RUNTIME_TO_DEPLOYMENT_ENVIRONMENT,
    TRAINING_FAMILY_TO_PURPOSE,
    WORKER_MODEL_PURPOSES,
    VocabularyError,
    persisted_environment,
    persisted_model_purpose,
    plan_vocabulary_migration,
    require_deployment_environment,
    require_worker_model_purpose,
)


OPENAPI = (
    Path(__file__).parents[2]
    / "contracts"
    / "openapi"
    / "routing-private.v1.yaml"
)


class VocabularyContractTest(unittest.TestCase):
    def test_worker_mapping_ranges_match_locked_private_openapi(self):
        contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
        schema = contract["paths"]["/internal/admin/models/{version}/activate"][
            "post"
        ]["requestBody"]["content"]["application/json"]["schema"]
        purpose_enum = frozenset(schema["properties"]["purpose"]["enum"])
        environment_enum = frozenset(
            schema["properties"]["environment"]["enum"]
        )

        self.assertEqual(purpose_enum, CANONICAL_MODEL_PURPOSES)
        self.assertEqual(environment_enum, CANONICAL_DEPLOYMENT_ENVIRONMENTS)
        self.assertEqual(
            frozenset(TRAINING_FAMILY_TO_PURPOSE),
            frozenset({"ETA", "SEAT_RISK"}),
        )
        self.assertEqual(WORKER_MODEL_PURPOSES, frozenset({"BUS_ETA", "SEAT_RISK"}))
        self.assertLessEqual(WORKER_MODEL_PURPOSES, purpose_enum)
        self.assertEqual(
            frozenset(RUNTIME_TO_DEPLOYMENT_ENVIRONMENT),
            PROCESS_RUNTIME_ENVIRONMENTS,
        )
        self.assertEqual(
            frozenset(RUNTIME_TO_DEPLOYMENT_ENVIRONMENT.values()),
            environment_enum,
        )

    def test_conversion_is_exact_and_persisted_aliases_are_rejected(self):
        self.assertEqual(persisted_model_purpose("ETA"), "BUS_ETA")
        self.assertEqual(persisted_model_purpose("SEAT_RISK"), "SEAT_RISK")
        self.assertEqual(persisted_environment("DEVELOPMENT"), "dev")
        self.assertEqual(persisted_environment("STAGING"), "staging")
        self.assertEqual(persisted_environment("PRODUCTION"), "prod")
        for invalid in ("BUS_ETA", "eta", "CALIBRATION", "TAXI_DISPATCH_WAIT"):
            with self.subTest(training_family=invalid):
                with self.assertRaises(VocabularyError):
                    persisted_model_purpose(invalid)
        for invalid in ("development", "staging", "production", "Prod"):
            with self.subTest(runtime_environment=invalid):
                with self.assertRaises(VocabularyError):
                    persisted_environment(invalid)
        for invalid in ("ETA", "CALIBRATION", "TAXI_DISPATCH_WAIT"):
            with self.subTest(worker_purpose=invalid):
                with self.assertRaises(VocabularyError):
                    require_worker_model_purpose(invalid)
        for invalid in ("DEVELOPMENT", "STAGING", "PRODUCTION", "production"):
            with self.subTest(deployment_environment=invalid):
                with self.assertRaises(VocabularyError):
                    require_deployment_environment(invalid)

    def test_legacy_inventory_plan_is_non_mutating_and_collision_safe(self):
        plan = plan_vocabulary_migration(
            purpose_counts={"ETA": 3, "SEAT_RISK": 2},
            environment_counts={"DEVELOPMENT": 1, "STAGING": 2, "PRODUCTION": 4},
        )
        self.assertTrue(plan.executable)
        self.assertEqual(plan.purpose_updates, (("ETA", "BUS_ETA", 3),))
        self.assertEqual(
            plan.environment_updates,
            (
                ("DEVELOPMENT", "dev", 1),
                ("STAGING", "staging", 2),
                ("PRODUCTION", "prod", 4),
            ),
        )

        blocked = plan_vocabulary_migration(
            purpose_counts={"ETA": 3, "BUS_ETA": 1, "OTHER": 1},
            environment_counts={"STAGING": 2, "staging": 1, "qa": 1},
        )
        self.assertFalse(blocked.executable)
        self.assertEqual(
            blocked.blockers,
            (
                "purpose collision: ETA->BUS_ETA",
                "unknown persisted purpose: OTHER",
                "environment collision: STAGING->staging",
                "unknown persisted environment: qa",
            ),
        )


if __name__ == "__main__":
    unittest.main()
