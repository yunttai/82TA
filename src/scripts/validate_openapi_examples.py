#!/usr/bin/env python3
"""Validate canonical request/response examples against local OpenAPI schemas.

This validator intentionally resolves repository-local YAML $ref values itself so
it does not rely on network access or a JSON-only file resolver.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "src/contracts/openapi"
_CACHE: dict[Path, dict[str, Any]] = {}


def load_yaml(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if path not in _CACHE:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"OpenAPI document must be an object: {path}")
        _CACHE[path] = value
    return _CACHE[path]


def json_pointer(document: Any, fragment: str) -> Any:
    if not fragment or fragment == "#":
        return document
    if not fragment.startswith("#/"):
        raise ValueError(f"Unsupported JSON pointer: {fragment}")
    current = document
    for token in fragment[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        current = current[token]
    return current


def dereference(node: Any, document: dict[str, Any], path: Path, stack: tuple[tuple[str, str], ...] = ()) -> Any:
    if isinstance(node, list):
        return [dereference(item, document, path, stack) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" not in node:
        return {key: dereference(value, document, path, stack) for key, value in node.items()}

    reference = node["$ref"]
    file_part, separator, fragment = reference.partition("#")
    target_path = (path.parent / file_part).resolve() if file_part else path.resolve()
    target_document = load_yaml(target_path)
    target = json_pointer(target_document, f"#{fragment}" if separator else "")
    cycle_key = (str(target_path), reference)
    if cycle_key in stack:
        raise ValueError(f"Cyclic $ref is not supported by this repository validator: {reference}")
    resolved = dereference(copy.deepcopy(target), target_document, target_path, stack + (cycle_key,))
    siblings = {key: value for key, value in node.items() if key != "$ref"}
    if siblings:
        if not isinstance(resolved, dict):
            raise ValueError(f"Cannot merge sibling keys into non-object ref: {reference}")
        resolved.update(dereference(siblings, document, path, stack))
    return resolved


def validate(spec_name: str, schema_name: str, example_name: str) -> list[str]:
    spec_path = OPENAPI / spec_name
    document = load_yaml(spec_path)
    schema = dereference(document["components"]["schemas"][schema_name], document, spec_path)
    instance = json.loads((OPENAPI / "examples" / example_name).read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance),
        key=lambda error: [str(item) for item in error.path],
    )
    result: list[str] = []
    for error in errors:
        location = "/".join(str(item) for item in error.path) or "<root>"
        result.append(f"{example_name} [{location}]: {error.message}")
    return result


def main() -> int:
    checks = [
        ("service-public.v1.yaml", "PublicRouteSearchRequest", "public-route-search-request.json"),
        ("service-public.v1.yaml", "PublicRouteSearchResponse", "public-route-search-response.json"),
        ("routing-private.v1.yaml", "OptimizeRouteRequest", "routing-optimize-request.json"),
        ("routing-private.v1.yaml", "OptimizeRouteResponse", "routing-optimize-response.json"),
        (
            "service-public.v1.yaml",
            "FavoriteJourneyFromPlacesInput",
            "public-favorite-journey-from-places-request.json",
        ),
        (
            "service-public.v1.yaml",
            "FavoriteJourneyFromPlacesResult",
            "public-favorite-journey-from-places-response.json",
        ),
    ]
    errors: list[str] = []
    for check in checks:
        errors.extend(validate(*check))
    if errors:
        print("OPENAPI EXAMPLE VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"OPENAPI EXAMPLES OK: {len(checks)} canonical examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
