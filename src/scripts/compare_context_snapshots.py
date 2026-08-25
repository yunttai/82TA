#!/usr/bin/env python3
"""Verify and compare live Service and Routing contract locks."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _contract_utils import load_json, project_root


def verify(root: Path, label: str) -> bool:
    result = subprocess.run(
        [
            sys.executable,
            str(root / "src/scripts/verify_contract_lock.py"),
            "--root",
            str(root),
        ],
        cwd=root,
        check=False,
    )
    if result.returncode:
        print(f"ERROR: {label} live contract lock verification failed: {root}")
        return False
    return True


def context(root: Path) -> dict:
    manifest = load_json(root / "src/contracts/CONTEXT_MANIFEST.json")
    lock = load_json(root / "src/contracts/CONTRACT_LOCK.json")
    return {
        "project": manifest.get("project"),
        "contextVersion": lock.get("contextVersion"),
        "contractVersion": lock.get("contractVersion"),
        "aggregateSha256": lock.get("aggregateSha256"),
        "canonicalFiles": lock.get("files"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare verified live contract locks; historical snapshots are ignored."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="backward-compatible shorthand that sets both roots",
    )
    parser.add_argument("--service-root", type=Path, default=None)
    parser.add_argument("--routing-root", type=Path, default=None)
    args = parser.parse_args()

    default_root = args.root.resolve() if args.root else project_root()
    service_root = (
        args.service_root.resolve() if args.service_root else default_root
    )
    routing_root = (
        args.routing_root.resolve() if args.routing_root else default_root
    )

    roots = [("service-product", service_root)]
    if routing_root != service_root:
        roots.append(("routing-intelligence", routing_root))
    if not all(verify(root, label) for label, root in roots):
        return 2

    left = context(service_root)
    right = context(routing_root)
    keys = (
        "project",
        "contextVersion",
        "contractVersion",
        "aggregateSha256",
        "canonicalFiles",
    )
    differences = [key for key in keys if left.get(key) != right.get(key)]
    if differences:
        print("CONTEXT PARITY FAILED")
        for key in differences:
            print(f"- {key}: service={left.get(key)!r}, routing={right.get(key)!r}")
        return 1

    print(
        "LIVE CONTEXT PARITY OK: "
        f"context={left['contextVersion']} contract={left['contractVersion']} "
        f"aggregate={left['aggregateSha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
