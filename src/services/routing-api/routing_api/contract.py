from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


def default_contract_path() -> Path:
    configured = os.environ.get("ROUTING_PRIVATE_OPENAPI_PATH")
    if configured:
        return Path(configured).resolve()
    src_root = Path(__file__).resolve().parents[3]
    return src_root / "contracts" / "openapi" / "routing-private.v1.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OpenAPI document is not an object: {path}")
    return value


def _pointer(document: Any, fragment: str) -> Any:
    if not fragment or fragment == "#":
        return document
    if not fragment.startswith("#/"):
        raise ValueError("unsupported contract reference")
    current = document
    for token in fragment[2:].split("/"):
        current = current[token.replace("~1", "/").replace("~0", "~")]
    return current


def _dereference(
    node: Any,
    document: dict[str, Any],
    path: Path,
    stack: tuple[tuple[Path, str], ...] = (),
) -> Any:
    if isinstance(node, list):
        return [_dereference(item, document, path, stack) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" not in node:
        return {key: _dereference(value, document, path, stack) for key, value in node.items()}

    reference = str(node["$ref"])
    file_part, separator, fragment = reference.partition("#")
    target_path = (path.parent / file_part).resolve() if file_part else path
    key = (target_path, reference)
    if key in stack:
        raise ValueError("cyclic contract reference")
    target_document = _load_yaml(target_path)
    target = _pointer(target_document, f"#{fragment}" if separator else "")
    resolved = _dereference(copy.deepcopy(target), target_document, target_path, stack + (key,))
    siblings = {key: value for key, value in node.items() if key != "$ref"}
    if siblings:
        if not isinstance(resolved, dict):
            raise ValueError("invalid contract reference siblings")
        resolved.update(_dereference(siblings, document, path, stack))
    return resolved


@dataclass(frozen=True)
class ContractViolation:
    field: str
    message: str


class CanonicalContractValidator:
    """Validator backed by the shared OpenAPI source, never a local DTO copy."""

    def __init__(self, contract_path: Path | None = None) -> None:
        self._path = (contract_path or default_contract_path()).resolve()
        document = _load_yaml(self._path)
        schema = document["components"]["schemas"]["OptimizeRouteRequest"]
        resolved = _dereference(schema, document, self._path)
        self._request_validator = Draft202012Validator(resolved, format_checker=FormatChecker())
        response_schema = document["components"]["schemas"]["OptimizeRouteResponse"]
        resolved_response = _dereference(response_schema, document, self._path)
        self._response_validator = Draft202012Validator(
            resolved_response, format_checker=FormatChecker()
        )

    def validate_optimize_request(self, payload: object) -> tuple[ContractViolation, ...]:
        errors = sorted(
            self._request_validator.iter_errors(payload),
            key=lambda error: [str(item) for item in error.absolute_path],
        )
        return tuple(
            ContractViolation(
                field=".".join(str(item) for item in error.absolute_path) or "$",
                message=error.message,
            )
            for error in errors
        )

    def validate_optimize_response(self, payload: object) -> tuple[ContractViolation, ...]:
        errors = sorted(
            self._response_validator.iter_errors(payload),
            key=lambda error: [str(item) for item in error.absolute_path],
        )
        return tuple(
            ContractViolation(
                field=".".join(str(item) for item in error.absolute_path) or "$",
                message=error.message,
            )
            for error in errors
        )
