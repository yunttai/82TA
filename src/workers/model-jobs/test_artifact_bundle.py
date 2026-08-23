from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from artifact_bundle import ArtifactBundleManifest, BundleFile, verify_bundle
from model_foundation import ArtifactIntegrityError, ArtifactMetadata


class ArtifactBundleTest(unittest.TestCase):
    def test_model_calibration_schema_and_card_are_all_hash_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "model.txt": b"tree\n",
                "calibration.json": b'{"method":"platt"}',
                "feature_schema.json": b'{"version":"v1"}',
                "model_card.md": b"# limitations\nfixture only\n",
            }
            for name, value in files.items():
                (root / name).write_bytes(value)
            artifact = ArtifactMetadata(
                "ETA", "eta-v1", "model.txt", "LIGHTGBM_TEXT",
                sha256(files["model.txt"]).hexdigest(), "v1", ("x",),
            )
            manifest = ArtifactBundleManifest(
                artifact=artifact,
                calibration=BundleFile("calibration.json", sha256(files["calibration.json"]).hexdigest()),
                model_card=BundleFile("model_card.md", sha256(files["model_card.md"]).hexdigest()),
                feature_schema=BundleFile("feature_schema.json", sha256(files["feature_schema.json"]).hexdigest()),
                dataset_sha256="a" * 64, metrics_sha256="b" * 64,
            )
            result = verify_bundle(
                root, manifest, runtime_feature_schema_version="v1", runtime_feature_names=("x",),
            )
            self.assertEqual(len(result.verified_files), 4)
            (root / "calibration.json").write_text("tampered", encoding="utf-8")
            with self.assertRaises(ArtifactIntegrityError):
                verify_bundle(root, manifest, runtime_feature_schema_version="v1", runtime_feature_names=("x",))


if __name__ == "__main__":
    unittest.main()
