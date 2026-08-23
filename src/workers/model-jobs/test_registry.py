from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import unittest

from model_foundation import ArtifactMetadata
from registry import (
    DEPLOYMENT_ENVIRONMENTS,
    Deployment,
    ModelCard,
    ModelState,
    RegistryError,
    plan_rollback,
    prediction_audit,
    register,
    transition,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 23, tzinfo=UTC)


def artifact(version="eta-v1"):
    return ArtifactMetadata(
        model_family="ETA", model_version=version, artifact_filename="model.txt",
        artifact_format="LIGHTGBM_TEXT", artifact_sha256="a" * 64,
        feature_schema_version="eta-feature-foundation-v1", feature_names=("x",),
    )


def card(version="eta-v1"):
    return ModelCard(
        "ETA", version, "target-stop ETA only", (("scope", "fixture"),),
        ("not production trained",), "a" * 64, "b" * 64, NOW,
    )


def advance_to(entry, target, offset=1):
    order = (ModelState.VALIDATED, ModelState.SHADOW, ModelState.CANARY, ModelState.ACTIVE)
    for index, state in enumerate(order, start=offset):
        entry, _ = transition(
            entry, state, actor="release-bot", reason="offline evidence",
            occurred_at=NOW + timedelta(minutes=index), validation_evidence_sha256="b" * 64,
        )
        if state is target:
            return entry
    return entry


class RegistryTest(unittest.TestCase):
    def test_deployment_environment_vocabulary_is_canonical(self):
        self.assertEqual(DEPLOYMENT_ENVIRONMENTS, frozenset({"dev", "staging", "prod"}))

    def test_model_card_is_immutable_and_discloses_limitations(self):
        card = ModelCard(
            "ETA", "eta-v1", "target-stop ETA only", (("dates", "3 weeks"),),
            ("fixture evaluation only",), "a" * 64, "b" * 64, NOW,
        )
        rendered = card.render_markdown()
        self.assertIn("fixture evaluation only", rendered)
        self.assertIn("3 weeks", rendered)

    def test_full_lifecycle_requires_order_and_validation_hash(self):
        entry = register(artifact(), model_card=card(), registered_at=NOW)
        with self.assertRaises(RegistryError):
            register(artifact("eta-other"), model_card=card(), registered_at=NOW)
        with self.assertRaises(RegistryError):
            transition(entry, ModelState.ACTIVE, actor="x", reason="skip", occurred_at=NOW)
        with self.assertRaises(RegistryError):
            transition(entry, ModelState.VALIDATED, actor="x", reason="no hash", occurred_at=NOW)
        active = advance_to(entry, ModelState.ACTIVE)
        retired, event = transition(
            active, ModelState.RETIRED, actor="operator", reason="rollback",
            occurred_at=NOW + timedelta(minutes=5),
        )
        self.assertEqual(retired.state, ModelState.RETIRED)
        self.assertEqual(event.from_state, ModelState.ACTIVE)

    def test_deployment_fraction_and_rollback_plan(self):
        old = advance_to(register(artifact("eta-old"), model_card=card("eta-old"), registered_at=NOW), ModelState.ACTIVE)
        old, _ = transition(
            old, ModelState.RETIRED, actor="operator", reason="superseded",
            occurred_at=NOW + timedelta(minutes=5),
        )
        current = advance_to(register(artifact("eta-current"), model_card=card("eta-current"), registered_at=NOW), ModelState.ACTIVE)
        deployment = Deployment("eta-current", "prod", ModelState.ACTIVE, 1.0, NOW)
        plan = plan_rollback(deployment, (old, current), reason="drift", planned_at=NOW)
        self.assertEqual(plan.restore_model_version, "eta-old")
        with self.assertRaises(RegistryError):
            Deployment("bad", "prod", ModelState.CANARY, 1.0, NOW)
        with self.assertRaises(RegistryError):
            Deployment("legacy", "PRODUCTION", ModelState.ACTIVE, 1.0, NOW)

    def test_prediction_audit_hashes_entity_and_input_instead_of_storing_them(self):
        audit = prediction_audit(
            model_version="eta-v1", request_id="opaque-request", entity_key="vehicle-token",
            feature_schema_version="eta-feature-foundation-v1", input_summary={"route": "R1"},
            prediction={"p50": 10}, created_at=NOW,
        )
        self.assertNotEqual(audit.entity_key_hash, "vehicle-token")
        self.assertNotIn("R1", audit.input_summary_sha256)


if __name__ == "__main__":
    unittest.main()
