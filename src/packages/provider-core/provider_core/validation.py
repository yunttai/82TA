"""Endpoint, request, and response schema trust boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


class InputValidationError(ValueError):
    pass


class SchemaValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EndpointRule:
    provider: str
    operation: str
    url: str

    def __post_init__(self) -> None:
        parts = urlsplit(self.url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("provider endpoints must be credential-free HTTPS URLs")
        if parts.fragment or parts.query:
            raise ValueError("provider endpoints cannot contain query strings or fragments")


class FixedEndpointAllowlist:
    """Resolves only composition-root supplied exact endpoints, never request URLs."""

    def __init__(self, *rules: EndpointRule) -> None:
        entries: dict[tuple[str, str], str] = {}
        for rule in rules:
            key = (rule.provider, rule.operation)
            if key in entries:
                raise ValueError(f"duplicate endpoint rule: {key!r}")
            entries[key] = rule.url
        self._entries = MappingProxyType(entries)

    def resolve(self, provider: str, operation: str) -> str:
        try:
            return self._entries[(provider, operation)]
        except KeyError as exc:
            raise InputValidationError("provider operation is not allowlisted") from exc

    def assert_exact(self, provider: str, operation: str, url: str) -> None:
        if url != self.resolve(provider, operation):
            raise InputValidationError("request-selected provider URL is forbidden")


Validator = Callable[[Any], bool]


class ObjectSchema:
    """Small strict schema validator used before provider normalization."""

    def __init__(
        self,
        *,
        required: Mapping[str, Validator],
        optional: Mapping[str, Validator] | None = None,
    ) -> None:
        self.required = MappingProxyType(dict(required))
        self.optional = MappingProxyType(dict(optional or {}))

    def validate(self, value: Any, *, path: str = "$") -> Mapping[str, Any]:
        if not isinstance(value, dict):
            raise SchemaValidationError(f"{path} must be an object")
        allowed = set(self.required) | set(self.optional)
        unknown = set(value) - allowed
        missing = set(self.required) - set(value)
        if unknown:
            raise SchemaValidationError(f"{path} contains unknown fields: {sorted(unknown)}")
        if missing:
            raise SchemaValidationError(f"{path} misses required fields: {sorted(missing)}")
        for field, validator in {**self.required, **self.optional}.items():
            if field in value and not validator(value[field]):
                raise SchemaValidationError(f"{path}.{field} has an invalid type or value")
        return value


def is_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_list(value: Any) -> bool:
    return isinstance(value, list)


def is_optional_string(value: Any) -> bool:
    return value is None or is_string(value)


def is_aware_iso8601(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_limit(value: int, *, minimum: int = 1, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise InputValidationError(f"limit must be an integer between {minimum} and {maximum}")
    return value
