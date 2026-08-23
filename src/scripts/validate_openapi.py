#!/usr/bin/env python3
"""Parse OpenAPI YAML and verify every repository-local $ref target exists."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

import yaml

from _contract_utils import project_root


def walk_refs(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                yield item
            yield from walk_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_refs(item)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve() if args.root else project_root()
    openapi_dir = root / "src/contracts/openapi"
    errors: list[str] = []
    for path in sorted(openapi_dir.rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - CLI validator
            errors.append(f"{path.relative_to(root)}: YAML parse failed: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{path.relative_to(root)}: root must be an object")
            continue
        if path.parent == openapi_dir and path.name != "components.v1.yaml" and "openapi" not in data:
            errors.append(f"{path.relative_to(root)}: missing openapi version")
        for ref in walk_refs(data):
            if ref.startswith("#") or ref.startswith("http://") or ref.startswith("https://"):
                continue
            file_part = ref.split("#", 1)[0]
            target = (path.parent / file_part).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{path.relative_to(root)}: $ref escapes repository: {ref}")
                continue
            if not target.is_file():
                errors.append(f"{path.relative_to(root)}: missing $ref target: {ref}")
    if errors:
        print("OPENAPI VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("OpenAPI YAML and local $ref targets OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
