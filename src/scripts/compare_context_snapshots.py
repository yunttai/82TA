#!/usr/bin/env python3
"""Compare the latest Service and Routing context snapshots before integration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _contract_utils import project_root


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve() if args.root else project_root()
    paths = {
        "service-product": root / "_workspace/service-product/00_context_snapshot_latest.json",
        "routing-intelligence": root / "_workspace/routing-intelligence/00_context_snapshot_latest.json",
    }
    for name, path in paths.items():
        if not path.is_file():
            print(f"ERROR: {name} snapshot is missing: {path.relative_to(root)}")
            return 2
    left = load(paths["service-product"])
    right = load(paths["routing-intelligence"])
    keys = ("project", "contextVersion", "contractVersion", "aggregateSha256")
    differences = [key for key in keys if left.get(key) != right.get(key)]
    if left.get("canonicalFiles") != right.get("canonicalFiles"):
        differences.append("canonicalFiles")
    if differences:
        print("CONTEXT PARITY FAILED")
        for key in differences:
            print(f"- {key}: service={left.get(key)!r}, routing={right.get(key)!r}")
        return 1
    print(
        "CONTEXT PARITY OK: "
        f"context={left['contextVersion']} contract={left['contractVersion']} "
        f"aggregate={left['aggregateSha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
