from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
UTILS_PATH = ROOT / "src/scripts/_contract_utils.py"
SPEC = importlib.util.spec_from_file_location("contract_utils", UTILS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load contract utilities")
CONTRACT_UTILS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT_UTILS)


class ContractLockPortabilityTests(unittest.TestCase):
    def test_text_hash_is_line_ending_independent_but_binary_is_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="82ta-lock-portability-") as directory:
            root = Path(directory)
            lf = root / "lf.json"
            crlf = root / "crlf.json"
            binary_lf = root / "lf.bin"
            binary_crlf = root / "crlf.bin"
            lf.write_bytes(b'{\n  "version": "1.1.0"\n}\n')
            crlf.write_bytes(b'{\r\n  "version": "1.1.0"\r\n}\r\n')
            binary_lf.write_bytes(b"a\nb")
            binary_crlf.write_bytes(b"a\r\nb")

            self.assertEqual(
                CONTRACT_UTILS.sha256_file(lf),
                CONTRACT_UTILS.sha256_file(crlf),
            )
            self.assertNotEqual(
                CONTRACT_UTILS.sha256_file(binary_lf),
                CONTRACT_UTILS.sha256_file(binary_crlf),
            )

    def test_current_checkout_matches_an_explicit_fresh_lf_export(self) -> None:
        current = CONTRACT_UTILS.calculate_lock(ROOT)
        manifest_path = ROOT / "src/contracts/CONTEXT_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="82ta-lock-lf-export-") as directory:
            export_root = Path(directory)
            export_manifest = export_root / "src/contracts/CONTEXT_MANIFEST.json"
            export_manifest.parent.mkdir(parents=True)
            export_manifest.write_bytes(
                manifest_path.read_text(encoding="utf-8")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .encode("utf-8")
            )
            for relative in manifest["canonicalFiles"]:
                source = ROOT / relative
                destination = export_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                raw = source.read_bytes()
                if source.suffix.lower() in CONTRACT_UTILS.CANONICAL_TEXT_SUFFIXES:
                    raw = (
                        raw.decode("utf-8")
                        .replace("\r\n", "\n")
                        .replace("\r", "\n")
                        .encode("utf-8")
                    )
                destination.write_bytes(raw)

            fresh_lf = CONTRACT_UTILS.calculate_lock(export_root)

        self.assertEqual(current["files"], fresh_lf["files"])
        self.assertEqual(current["aggregateSha256"], fresh_lf["aggregateSha256"])
        aggregate_input = "".join(
            f"{path}:{current['files'][path]}\n" for path in sorted(current["files"])
        )
        self.assertEqual(
            current["aggregateSha256"],
            hashlib.sha256(aggregate_input.encode("utf-8")).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
