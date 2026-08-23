"""Secret-safe, fixed-scope verification probes for the Kakao baseline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable, Mapping

from .canonical import Coordinate
from .http import BoundedHttpTransport, HttpRequest, SensitiveValue
from .kakao_mobility import normalize_current_directions
from .kakao_raw import (
    parse_kakao_public_transit,
    parse_kakao_walk,
)
from .named import ENDPOINT_SPECS
from .validation import SchemaValidationError


class ProbeState(StrEnum):
    KEY_VERIFIED = "KEY_VERIFIED"
    FAILED = "FAILED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True)
class ProviderProbeResult:
    provider: str
    operation: str
    schema_version: str
    state: ProbeState
    normalized_count: int
    checked_at: datetime
    artifact_sha256: str
    message_code: str

    def as_sanitized_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "operation": self.operation,
            "documentationState": "DOCUMENTED",
            "keyVerificationState": self.state.value,
            "productionState": "UNAPPROVED",
            "schemaVersion": self.schema_version,
            "normalizedCount": self.normalized_count,
            "checkedAt": self.checked_at.isoformat(),
            "artifactSha256": self.artifact_sha256,
            "messageCode": self.message_code,
        }


_ProbeParser = Callable[[object], tuple[object, ...]]
_PROBE_SCOPES: Mapping[
    str,
    tuple[str, str, tuple[tuple[str, object], ...], _ProbeParser],
] = {
    "transit": (
        "KAKAO_PUBLIC_TRANSIT",
        "search_current",
        (
            ("start_x", 127.11119217), ("start_y", 37.39477123),
            ("end_x", 127.12628814), ("end_y", 37.41993056),
            ("input_coord", "WGS84"), ("output_coord", "WGS84"),
        ),
        lambda body: parse_kakao_public_transit(
            body,
            effective_at=None,
            origin=Coordinate(127.11119217, 37.39477123),
            destination=Coordinate(127.12628814, 37.41993056),
        ),
    ),
    "walk": (
        "KAKAO_WALK",
        "route",
        (
            ("start_x", 127.11119669891646), ("start_y", 37.394776627382875),
            ("end_x", 127.12629039752096), ("end_y", 37.4199323570413),
            ("input_coord", "WGS84"), ("output_coord", "WGS84"),
            ("route_mode", "BROAD_FIRST"),
        ),
        lambda body: parse_kakao_walk(body, effective_at=None),
    ),
    "directions": (
        "KAKAO_DIRECTIONS",
        "route_current",
        (
            ("origin", "127.11119217,37.39477123"),
            ("destination", "127.12628814,37.41993056"),
            ("priority", "TIME"),
            ("car_fuel", "GASOLINE"),
            ("car_hipass", "false"),
            ("alternatives", "false"),
            ("road_details", "false"),
            ("summary", "false"),
        ),
        normalize_current_directions,
    ),
}


def probe_kakao_operation(
    name: str,
    *,
    transport: BoundedHttpTransport,
    credential: SensitiveValue,
    clock: Callable[[], datetime] | None = None,
) -> ProviderProbeResult:
    """Spend one fixed probe call and return metadata with no key or raw payload."""

    if name not in _PROBE_SCOPES:
        raise ValueError("unknown Kakao probe operation")
    provider, operation, query, parser = _PROBE_SCOPES[name]
    spec = next(
        item for item in ENDPOINT_SPECS
        if item.provider == provider and item.operation == operation
    )
    if (
        spec.url is None
        or spec.auth is None
        or not spec.response_schema_verified
        or spec.response_schema_version is None
    ):
        raise ValueError("Kakao probe endpoint is not executable")
    schema_version = spec.response_schema_version
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    request = HttpRequest(
        method=spec.method,
        url=spec.url,
        query=query,
        headers=(("Accept", "application/json"),),
        timeout_ms=spec.timeout_ms,
        maximum_response_bytes=spec.maximum_response_bytes,
    )
    request = spec.auth.apply(request, credential)
    response = transport.send(request)
    state = ProbeState.INDETERMINATE
    count = 0
    message = "PROBE_INDETERMINATE"
    if response.status_code in {401, 403}:
        state = ProbeState.FAILED
        message = "KEY_REJECTED"
    elif 200 <= response.status_code < 300:
        try:
            body = response.json_object(maximum_bytes=spec.maximum_response_bytes)
            payload = parser(body)
        except (SchemaValidationError, ValueError, KeyError, TypeError):
            message = "RESPONSE_SCHEMA_MISMATCH"
        else:
            state = ProbeState.KEY_VERIFIED
            count = len(payload)
            message = "KEY_AND_SCHEMA_VERIFIED"
    elif response.status_code == 429:
        message = "RATE_LIMITED"
    sanitized = {
        "provider": provider,
        "operation": operation,
        "schemaVersion": schema_version,
        "state": state.value,
        "normalizedCount": count,
        "checkedAt": now.isoformat(),
        "messageCode": message,
    }
    digest = hashlib.sha256(
        json.dumps(sanitized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ProviderProbeResult(
        provider=provider,
        operation=operation,
        schema_version=schema_version,
        state=state,
        normalized_count=count,
        checked_at=now,
        artifact_sha256=digest,
        message_code=message,
    )


def probe_scope_names() -> tuple[str, ...]:
    return tuple(_PROBE_SCOPES)


__all__ = [
    "ProbeState",
    "ProviderProbeResult",
    "probe_kakao_operation",
    "probe_scope_names",
]
