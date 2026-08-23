#!/usr/bin/env python3
"""Verify exact shared context hashes and their aggregate for both harnesses."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _contract_utils import calculate_lock, project_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve() if args.root else project_root()
    manifest_path = root / "src/contracts/CONTEXT_MANIFEST.json"
    lock_path = root / "src/contracts/CONTRACT_LOCK.json"
    if not manifest_path.is_file() or not lock_path.is_file():
        print("Missing context manifest or contract lock")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for key in ("project", "contextVersion", "contractVersion"):
        if manifest.get(key) != lock.get(key):
            errors.append(f"{key} mismatch: manifest={manifest.get(key)!r}, lock={lock.get(key)!r}")

    try:
        actual = calculate_lock(root)
    except Exception as exc:  # noqa: BLE001 - CLI validator
        print(f"CONTRACT LOCK FAILED\n- cannot calculate canonical hashes: {exc}")
        return 1

    expected_paths = set(manifest.get("canonicalFiles", []))
    locked_paths = set(lock.get("files", {}))
    for relative in sorted(expected_paths - locked_paths):
        errors.append(f"not locked: {relative}")
    for relative in sorted(locked_paths - expected_paths):
        errors.append(f"lock contains non-canonical file: {relative}")
    for relative, actual_hash in actual["files"].items():
        recorded = lock.get("files", {}).get(relative)
        if actual_hash != recorded:
            errors.append(f"hash drift: {relative}\n  expected {recorded}\n  actual   {actual_hash}")

    recorded_aggregate = lock.get("aggregateSha256")
    if recorded_aggregate != actual["aggregateSha256"]:
        errors.append(
            "aggregate hash drift:\n"
            f"  expected {recorded_aggregate}\n"
            f"  actual   {actual['aggregateSha256']}"
        )

    if errors:
        print("CONTRACT LOCK FAILED")
        for error in errors:
            print(f"- {error}")
        print("Run shared-contract-governance. Do not update the lock until both workstreams approve the change.")
        return 1
    print(
        f"CONTRACT LOCK OK: {len(expected_paths)} canonical files, "
        f"contract {lock['contractVersion']}, aggregate {recorded_aggregate}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
