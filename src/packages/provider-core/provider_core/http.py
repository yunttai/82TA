"""Bounded HTTP transport port and secret-safe request values.

This module contains no concrete network client. The composition root must inject a
transport that enforces the supplied timeout and response byte ceiling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from .validation import SchemaValidationError


@dataclass(frozen=True, slots=True, repr=False)
class SensitiveValue:
    """A credential value whose repr/str never exposes the secret."""

    _value: str

    def __post_init__(self) -> None:
        if not self._value:
            raise ValueError("sensitive value cannot be empty")

    def __repr__(self) -> str:
        return "SensitiveValue(***)"

    def __str__(self) -> str:
        return "***"

    def reveal_for_transport(self) -> str:
        return self._value


HttpValue = str | int | float | bool | SensitiveValue


@dataclass(frozen=True, slots=True, repr=False)
class HttpRequest:
    method: str
    url: str
    headers: tuple[tuple[str, HttpValue], ...] = ()
    query: tuple[tuple[str, HttpValue], ...] = ()
    json_body: dict[str, Any] | None = None
    timeout_ms: int = 1000
    maximum_response_bytes: int = 512_000

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST"}:
            raise ValueError("provider HTTP method must be GET or POST")
        if self.timeout_ms <= 0 or self.maximum_response_bytes <= 0:
            raise ValueError("provider HTTP bounds must be positive")

    def safe_summary(self) -> dict[str, Any]:
        def safe_headers(values: tuple[tuple[str, HttpValue], ...]) -> dict[str, Any]:
            return {key: "***" if isinstance(value, SensitiveValue) else value for key, value in values}

        def safe_query(values: tuple[tuple[str, HttpValue], ...]) -> dict[str, str]:
            # Query values commonly contain exact coordinates or provider IDs. They
            # are never appropriate in a general request summary.
            return {
                key: "***" if isinstance(value, SensitiveValue) else "<redacted>"
                for key, value in values
            }

        return {
            "method": self.method,
            "url": self.url,
            "headers": safe_headers(self.headers),
            "query": safe_query(self.query),
            "hasJsonBody": self.json_body is not None,
            "timeoutMs": self.timeout_ms,
            "maximumResponseBytes": self.maximum_response_bytes,
        }

    def __repr__(self) -> str:
        return f"HttpRequest({self.safe_summary()!r})"


@dataclass(frozen=True, slots=True, repr=False)
class HttpResponse:
    status_code: int
    content_type: str
    body: bytes

    def json_object(self, *, maximum_bytes: int) -> dict[str, Any]:
        media_type = self.content_type.split(";", 1)[0].strip().lower()
        if media_type not in {"application/json", "application/problem+json"}:
            raise SchemaValidationError(f"unsupported provider content type: {media_type}")
        if len(self.body) > maximum_bytes:
            raise SchemaValidationError("provider response exceeds byte limit")
        try:
            value = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SchemaValidationError("provider response is not valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise SchemaValidationError("provider response root must be an object")
        return value

    def __repr__(self) -> str:
        return (
            "HttpResponse("
            f"status_code={self.status_code!r}, content_type={self.content_type!r}, "
            f"body_bytes={len(self.body)!r})"
        )


class BoundedHttpTransport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class AuthInjection:
    location: str
    name: str
    prefix: str = ""

    def __post_init__(self) -> None:
        if self.location not in {"header", "query"}:
            raise ValueError("auth location must be header or query")
        if not self.name.strip():
            raise ValueError("auth field name is required")

    def apply(self, request: HttpRequest, credential: SensitiveValue) -> HttpRequest:
        value = SensitiveValue(self.prefix + credential.reveal_for_transport())
        if self.location == "header":
            return HttpRequest(
                request.method, request.url, request.headers + ((self.name, value),), request.query,
                request.json_body, request.timeout_ms, request.maximum_response_bytes,
            )
        return HttpRequest(
            request.method, request.url, request.headers, request.query + ((self.name, value),),
            request.json_body, request.timeout_ms, request.maximum_response_bytes,
        )
