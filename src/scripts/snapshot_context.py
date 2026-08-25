#!/usr/bin/env python3
"""Write one current context snapshot, with optional explicit archival."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _contract_utils import load_json, project_root

ALLOWED_HARNESSES = {"service-product", "routing-intelligence", "integration"}


def git_value(root: Path, *args: str) -> str | None:
    try:
        value = subprocess.check_output(
            ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        return value or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("harness", choices=sorted(ALLOWED_HARNESSES))
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--archive",
        action="store_true",
        help="also retain a timestamped historical copy; default only updates current",
    )
    args = parser.parse_args()
    root = args.root.resolve() if args.root else project_root()

    verify = subprocess.run(
        [
            sys.executable,
            str(root / "src/scripts/verify_contract_lock.py"),
            "--root",
            str(root),
        ],
        cwd=root,
        check=False,
    )
    if verify.returncode:
        return verify.returncode

    manifest = load_json(root / "src/contracts/CONTEXT_MANIFEST.json")
    lock = load_json(root / "src/contracts/CONTRACT_LOCK.json")
    now = datetime.now(timezone.utc)
    snapshot = {
        "project": manifest["project"],
        "harness": args.harness,
        "snapshotAt": now.isoformat(timespec="seconds"),
        "contextVersion": lock["contextVersion"],
        "contractVersion": lock["contractVersion"],
        "aggregateSha256": lock["aggregateSha256"],
        "canonicalFiles": lock["files"],
        "git": {
            "commit": git_value(root, "rev-parse", "HEAD"),
            "branch": git_value(root, "rev-parse", "--abbrev-ref", "HEAD"),
            "contractLockCommit": git_value(
                root,
                "log",
                "-1",
                "--format=%H",
                "--",
                "src/contracts/CONTRACT_LOCK.json",
            ),
            "dirty": bool(git_value(root, "status", "--porcelain")),
        },
    }

    output_dir = root / "_workspace" / args.harness
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    current = output_dir / "00_context_snapshot_current.json"
    current.write_text(payload, encoding="utf-8")
    print(current.relative_to(root))

    if args.archive:
        archive = output_dir / f"00_context_snapshot_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        archive.write_text(payload, encoding="utf-8")
        print(archive.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
