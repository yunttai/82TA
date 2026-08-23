from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest

from bus_intelligence_core import (
    ETA_CONTEXT_FEATURE_NAMES,
    ETA_CONTEXT_SERVING_SCHEMA_VERSION,
    SEAT_RISK_CONTEXT_FEATURE_NAMES,
    SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
)
from model_foundation import (
    ArtifactIntegrityError,
    ArtifactMetadata,
    ModelFoundationError,
    eta_feature_target_metadata,
    seat_risk_feature_target_metadata,
    verify_artifact,
)
from routing_worker.feature_encoding import FEATURE_ENCODING_VERSION


class ModelFoundationTest(unittest.TestCase):
    def test_feature_metadata_matches_shared_train_serve_builder(self) -> None:
        data_quality = Path(__file__).parents[1] / "data-quality"
        sys.path.insert(0, str(data_quality))
        try:
            from feature_builder import (
                ETA_SCHEMA_VERSION,
                SEAT_SCHEMA_VERSION,
                NormalizedFeatureObservation,
                build_eta_features,
                build_seat_features,
            )
            from datetime import datetime, timezone

            observed = datetime(2026, 8, 23, tzinfo=timezone.utc)
            source = NormalizedFeatureObservation(
                "trip", "route", "UP", observed, observed, observed, 1, 2
            )
            eta = eta_feature_target_metadata()
            seat = seat_risk_feature_target_metadata()
            eta_vector = build_eta_features(source)
            seat_vector = build_seat_features(source)
            self.assertEqual((eta.feature_schema_version, eta.feature_names), (ETA_SCHEMA_VERSION, eta_vector.feature_names))
            self.assertEqual((seat.feature_schema_version, seat.feature_names), (SEAT_SCHEMA_VERSION, seat_vector.feature_names))
            self.assertEqual(
                (eta.context_schema_version, eta.context_feature_names),
                (ETA_CONTEXT_SERVING_SCHEMA_VERSION, ETA_CONTEXT_FEATURE_NAMES),
            )
            self.assertEqual(
                (seat.context_schema_version, seat.context_feature_names),
                (
                    SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
                    SEAT_RISK_CONTEXT_FEATURE_NAMES,
                ),
            )
            self.assertEqual(eta.feature_encoding_version, FEATURE_ENCODING_VERSION)
            self.assertEqual(seat.feature_encoding_version, FEATURE_ENCODING_VERSION)
        finally:
            sys.path.remove(str(data_quality))

    def test_eta_and_seat_metadata_are_separate_and_leakage_safe(self) -> None:
        eta = eta_feature_target_metadata()
        seat = seat_risk_feature_target_metadata()
        self.assertNotEqual(eta.model_family, seat.model_family)
        self.assertNotEqual(eta.feature_schema_version, seat.feature_schema_version)
        self.assertEqual(eta.target_names, ("eta_seconds",))
        self.assertIn("no_seat_at_target", seat.target_names)
        self.assertEqual(eta.training_label_names, ("eta_seconds",))
        self.assertEqual(seat.training_label_names, ("seat_ordinal_class",))
        self.assertTrue(set(eta.feature_names).isdisjoint(eta.target_names))
        self.assertTrue(set(seat.feature_names).isdisjoint(seat.target_names))
        self.assertNotEqual(eta.context_schema_version, seat.context_schema_version)

    def test_metadata_rejects_cross_family_context_schema(self) -> None:
        eta = eta_feature_target_metadata()
        with self.assertRaisesRegex(ModelFoundationError, "match the model family"):
            replace(
                eta,
                context_schema_version=SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
            )
        with self.assertRaisesRegex(ModelFoundationError, "schema version"):
            replace(eta, feature_encoding_version="worker-feature-encoding-v0")

    def test_old_or_cross_family_context_schema_fails_artifact_verification(self) -> None:
        artifact_bytes = b"tree\nversion=v2\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eta-model.txt").write_bytes(artifact_bytes)
            old = ArtifactMetadata(
                model_family="ETA",
                model_version="fixture-only-v1",
                artifact_filename="eta-model.txt",
                artifact_format="LIGHTGBM_TEXT",
                artifact_sha256=sha256(artifact_bytes).hexdigest(),
                feature_schema_version="eta-feature-foundation-v1",
                feature_names=("remaining_stops",),
            )
            eta = eta_feature_target_metadata()
            seat = seat_risk_feature_target_metadata()
            with self.assertRaisesRegex(ArtifactIntegrityError, "schema version"):
                verify_artifact(
                    root,
                    old,
                    runtime_feature_schema_version=eta.feature_schema_version,
                    runtime_feature_names=eta.feature_names,
                )

            eta_artifact = ArtifactMetadata(
                model_family="ETA",
                model_version="fixture-only-v2",
                artifact_filename="eta-model.txt",
                artifact_format="LIGHTGBM_TEXT",
                artifact_sha256=sha256(artifact_bytes).hexdigest(),
                feature_schema_version=eta.feature_schema_version,
                feature_names=eta.feature_names,
            )
            with self.assertRaisesRegex(ArtifactIntegrityError, "schema version"):
                verify_artifact(
                    root,
                    eta_artifact,
                    runtime_feature_schema_version=seat.feature_schema_version,
                    runtime_feature_names=seat.feature_names,
                )

    def test_artifact_is_verified_without_deserialization(self) -> None:
        artifact_bytes = b"tree\nversion=v1\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eta-model.txt").write_bytes(artifact_bytes)
            metadata = ArtifactMetadata(
                model_family="ETA",
                model_version="fixture-only-v1",
                artifact_filename="eta-model.txt",
                artifact_format="LIGHTGBM_TEXT",
                artifact_sha256=sha256(artifact_bytes).hexdigest(),
                feature_schema_version="eta-feature-foundation-v1",
                feature_names=("remaining_stops", "freshness_seconds"),
            )
            result = verify_artifact(
                root,
                metadata,
                runtime_feature_schema_version="eta-feature-foundation-v1",
                runtime_feature_names=("remaining_stops", "freshness_seconds"),
            )
            self.assertTrue(result.verified)
            self.assertEqual(result.byte_size, len(artifact_bytes))

    def test_hash_and_schema_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "seat-model.txt").write_bytes(b"model")
            metadata = ArtifactMetadata(
                model_family="SEAT_RISK",
                model_version="fixture-only-v1",
                artifact_filename="seat-model.txt",
                artifact_format="LIGHTGBM_TEXT",
                artifact_sha256="0" * 64,
                feature_schema_version="seat-risk-feature-foundation-v1",
                feature_names=("remaining_stops",),
            )
            with self.assertRaisesRegex(ArtifactIntegrityError, "schema version"):
                verify_artifact(
                    root,
                    metadata,
                    runtime_feature_schema_version="wrong",
                    runtime_feature_names=("remaining_stops",),
                )
            with self.assertRaisesRegex(ArtifactIntegrityError, "SHA-256"):
                verify_artifact(
                    root,
                    metadata,
                    runtime_feature_schema_version="seat-risk-feature-foundation-v1",
                    runtime_feature_names=("remaining_stops",),
                )

    def test_pickle_and_path_traversal_are_not_allowlisted(self) -> None:
        common = dict(
            model_family="ETA",
            model_version="fixture-only-v1",
            artifact_format="LIGHTGBM_TEXT",
            artifact_sha256="0" * 64,
            feature_schema_version="eta-feature-foundation-v1",
            feature_names=("remaining_stops",),
        )
        with self.assertRaises(ArtifactIntegrityError):
            ArtifactMetadata(artifact_filename="model.pkl", **common)
        with self.assertRaises(ArtifactIntegrityError):
            ArtifactMetadata(artifact_filename="../model.txt", **common)


if __name__ == "__main__":
    unittest.main()
