#!/usr/bin/env python3
"""Rebuild the shared contract SHA-256 lock after an approved joint change."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from _contract_utils import calculate_lock, project_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--approved-change",
        action="store_true",
        help="Assert that shared-contract-governance and both workstream QA reviews are complete.",
    )
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    if not args.approved_change:
        print("Refusing to update contract lock without --approved-change")
        return 2

    root = args.root.resolve() if args.root else project_root()
    payload = calculate_lock(root)
    payload["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Keep a stable human-readable order.
    ordered = {
        "project": payload["project"],
        "contextVersion": payload["contextVersion"],
        "contractVersion": payload["contractVersion"],
        "generatedAt": payload["generatedAt"],
        "algorithm": payload["algorithm"],
        "aggregateSha256": payload["aggregateSha256"],
        "files": payload["files"],
    }
    lock = root / "src/contracts/CONTRACT_LOCK.json"
    lock.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Updated {lock.relative_to(root)} with {len(ordered['files'])} files "
        f"(aggregate {ordered['aggregateSha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
