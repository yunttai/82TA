from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


SRC_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_ROOT = SRC_ROOT / "contracts"
OPENAPI_ROOT = CONTRACTS_ROOT / "openapi"


class ContractError(RuntimeError):
    pass


def _canonical_text_bytes(raw: bytes) -> bytes:
    """Normalize checkout line endings before comparing canonical text hashes."""

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("locked fixture is not valid UTF-8") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _json_pointer(document: Any, pointer: str) -> Any:
    value = document
    if pointer:
        for raw_part in pointer.lstrip("/").split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
    return value


class CanonicalContracts:
    """Reads canonical schemas in place; it does not define local DTO copies."""

    def __init__(self) -> None:
        self._documents: dict[Path, Any] = {}
        self.public_path = OPENAPI_ROOT / "service-public.v1.yaml"
        self.private_path = OPENAPI_ROOT / "routing-private.v1.yaml"

    def _load_yaml(self, path: Path) -> Any:
        resolved = path.resolve()
        if resolved not in self._documents:
            self._documents[resolved] = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        return self._documents[resolved]

    def _dereference(self, value: Any, source: Path) -> Any:
        if isinstance(value, list):
            return [self._dereference(item, source) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            ref = value["$ref"]
            file_part, _, fragment = ref.partition("#")
            target_path = (source.parent / file_part).resolve() if file_part else source.resolve()
            target = _json_pointer(self._load_yaml(target_path), fragment)
            merged = copy.deepcopy(target)
            merged.update({key: item for key, item in value.items() if key != "$ref"})
            return self._dereference(merged, target_path)
        return {key: self._dereference(item, source) for key, item in value.items()}

    def schema(self, api: str, schema_name: str) -> dict[str, Any]:
        source = self.public_path if api == "public" else self.private_path
        document = self._load_yaml(source)
        schema = document["components"]["schemas"][schema_name]
        return self._dereference(copy.deepcopy(schema), source)

    def validate(self, api: str, schema_name: str, value: Any) -> list[Any]:
        validator = Draft202012Validator(
            self.schema(api, schema_name), format_checker=FormatChecker()
        )
        return sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))


class LockedFixtures:
    FIXTURES = {
        "public_request": "src/contracts/openapi/examples/public-route-search-request.json",
        "public_response": "src/contracts/openapi/examples/public-route-search-response.json",
        "routing_request": "src/contracts/openapi/examples/routing-optimize-request.json",
        "routing_response": "src/contracts/openapi/examples/routing-optimize-response.json",
    }

    def __init__(self) -> None:
        repository_root = SRC_ROOT.parent
        lock = json.loads((CONTRACTS_ROOT / "CONTRACT_LOCK.json").read_text(encoding="utf-8"))
        expected_hashes = lock["files"]
        self._values: dict[str, Any] = {}
        for name, relative_path in self.FIXTURES.items():
            path = repository_root / relative_path
            raw = _canonical_text_bytes(path.read_bytes())
            if hashlib.sha256(raw).hexdigest() != expected_hashes.get(relative_path):
                raise ContractError(f"locked fixture hash mismatch: {relative_path}")
            self._values[name] = json.loads(raw)

    def get(self, name: str) -> Any:
        return copy.deepcopy(self._values[name])
