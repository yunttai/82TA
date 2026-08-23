from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class GeneratedClientTrackingTests(unittest.TestCase):
    def assert_ignored(self, relative: str) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", relative],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, relative)

    def assert_trackable(self, relative: str) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", relative],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 1, relative)

    def test_required_generator_and_client_sources_are_trackable(self) -> None:
        for relative in (
            "src/generated/generate-clients.sh",
            "src/generated/verify-reproducibility.sh",
            "src/generated/config/routing-python.json",
            "src/generated/service-client-ts/schema.gen.ts",
            "src/generated/service-client-ts/client.gen.ts",
            "src/generated/service-client-ts/index.ts",
            "src/generated/service-client-ts/package.json",
            "src/generated/service-client-ts/package-lock.json",
            "src/generated/service-client-ts/tsconfig.json",
            "src/generated/routing-client-python/pyproject.toml",
            "src/generated/routing-client-python/uv.lock",
            "src/generated/routing-client-python/routing_client/client.py",
            "src/generated/routing-client-python/routing_client/py.typed",
        ):
            self.assert_trackable(relative)

    def test_disposable_generated_artifacts_remain_ignored(self) -> None:
        for relative in (
            "src/generated/service-client-ts/node_modules/typescript/package.json",
            "src/generated/service-client-ts/dist/index.js",
            "src/generated/routing-client-python/.venv/pyvenv.cfg",
            "src/generated/routing-client-python/.ruff_cache/CACHEDIR.TAG",
            "src/generated/routing-client-python/routing_client/__pycache__/client.pyc",
            "src/generated/routing-client-python/build/client.whl",
        ):
            self.assert_ignored(relative)

    def test_generator_dependencies_are_exactly_pinned(self) -> None:
        generator = (ROOT / "src/generated/generate-clients.sh").read_text(encoding="utf-8")
        self.assertIn("@redocly/cli@1.34.2", generator)
        self.assertIn("openapi-typescript@7.9.1", generator)
        self.assertIn("openapi-python-client==0.29.0", generator)


if __name__ == "__main__":
    unittest.main()
