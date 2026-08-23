"""Fail-closed environment assembly for the three-operation Kakao baseline.

The factory is deployment-owned input parsing, not an approval authority.  A key's
presence never changes capability state.  All approval and runtime evidence must be
supplied as an exact, non-secret external bundle and remains subject to the adapter's
normal runtime gate.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Mapping

from .canonical import require_aware
from .capabilities import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    FOUNDATION_DOCUMENTED_OPERATIONS,
    KeyVerificationState,
    ProductionState,
)
from .http import SensitiveValue
from .kakao_raw import (
    KAKAO_DIRECTIONS_SCHEMA_VERSION,
    KAKAO_PUBLIC_TRANSIT_SCHEMA_VERSION,
    KAKAO_WALK_SCHEMA_VERSION,
)
from .named import (
    ENDPOINT_SPECS,
    ProviderAdapterSuiteConfig,
    ProviderOperationBinding,
    ScopedProviderCredential,
    ScopedProviderTransport,
)
from .runtime import ProviderRuntimeEvidenceConfig, RuntimeEvidence, RuntimeEvidenceKind
from .transport import EgressEnforcement, NetworkEgressAttestation, StrictHttpsTransport
from .transport import HttpsConnectProxyConnectionFactory


KAKAO_BASELINE_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("KAKAO_PUBLIC_TRANSIT", "search_current"),
    ("KAKAO_WALK", "route"),
    ("KAKAO_DIRECTIONS", "route_current"),
)
PROVIDER_OPERATION_KEY_ENV: Mapping[tuple[str, str], str] = {
    ("KAKAO_PUBLIC_TRANSIT", "search_current"): "KAKAO_REST_API_KEY",
    ("KAKAO_WALK", "route"): "KAKAO_REST_API_KEY",
    ("KAKAO_DIRECTIONS", "route_current"): "KAKAO_REST_API_KEY",
    ("KAKAO_MULTI_DESTINATION", "many_destinations"): "KAKAO_REST_API_KEY",
    ("KAKAO_MULTI_ORIGIN", "many_origins"): "KAKAO_REST_API_KEY",
    ("KAKAO_FUTURE_DIRECTIONS", "route_future"): "KAKAO_REST_API_KEY",
    ("GBIS_V2", "arrivals"): "GBIS_SERVICE_KEY",
    ("GBIS_V2", "locations"): "GBIS_SERVICE_KEY",
    ("GBIS_V2", "routes"): "GBIS_SERVICE_KEY",
    ("GBIS_V2", "stations"): "GBIS_SERVICE_KEY",
    ("KMA", "weather_context"): "GBIS_SERVICE_KEY",
    ("GITS", "traffic_context"): "GITS_API_KEY",
    ("TMAP_TRANSIT", "search"): "TMAP_APP_KEY",
    ("ODSAY", "search"): "ODSAY_API_KEY",
}
if set(PROVIDER_OPERATION_KEY_ENV) != set(FOUNDATION_DOCUMENTED_OPERATIONS):
    raise RuntimeError("provider credential environment mapping is incomplete")

KAKAO_BASELINE_KEY_ENV: Mapping[tuple[str, str], str] = {
    operation: PROVIDER_OPERATION_KEY_ENV[operation]
    for operation in KAKAO_BASELINE_OPERATIONS
}
KAKAO_BASELINE_SCHEMA_VERSIONS = {
    ("KAKAO_PUBLIC_TRANSIT", "search_current"): KAKAO_PUBLIC_TRANSIT_SCHEMA_VERSION,
    ("KAKAO_WALK", "route"): KAKAO_WALK_SCHEMA_VERSION,
    ("KAKAO_DIRECTIONS", "route_current"): KAKAO_DIRECTIONS_SCHEMA_VERSION,
}
EVIDENCE_ENV = "ROUTING_PROVIDER_EVIDENCE_JSON"
PROVIDER_HTTPS_PROXY_ENV = "ROUTING_PROVIDER_HTTPS_PROXY_URL"


def build_kakao_baseline_config() -> ProviderAdapterSuiteConfig:
    """Build exact operation bindings from environment, without inferring approval."""

    document = _evidence_document(os.environ.get(EVIDENCE_ENV))
    capabilities = _capabilities(document["capabilities"])
    runtime_evidence = _runtime_evidence(document["runtimeEvidence"])
    attestation = _egress_attestation(document["egressAttestation"])
    specs = {
        (spec.provider, spec.operation): spec
        for spec in ENDPOINT_SPECS
        if (spec.provider, spec.operation) in KAKAO_BASELINE_OPERATIONS
    }
    if set(specs) != set(KAKAO_BASELINE_OPERATIONS):
        raise ValueError("Kakao baseline endpoint specification is incomplete")
    urls = tuple(specs[key].url for key in KAKAO_BASELINE_OPERATIONS)
    if any(url is None for url in urls):
        raise ValueError("Kakao baseline endpoint is not pinned")
    transport = build_strict_https_transport(
        tuple(url for url in urls if url is not None),
        attestation=attestation,
    )
    bindings = []
    for provider, operation in KAKAO_BASELINE_OPERATIONS:
        env_name = KAKAO_BASELINE_KEY_ENV[(provider, operation)]
        secret = _secret(os.environ.get(env_name), env_name)
        bindings.append(ProviderOperationBinding(
            transport=ScopedProviderTransport(provider, operation, transport),
            credential=ScopedProviderCredential(
                provider, operation, SensitiveValue(secret)
            ),
        ))
    return ProviderAdapterSuiteConfig(
        bindings=tuple(bindings),
        capabilities=CapabilityRegistry(capabilities),
        runtime_evidence=ProviderRuntimeEvidenceConfig(runtime_evidence),
    )


def build_strict_https_transport(
    exact_endpoint_urls: tuple[str, ...],
    *,
    attestation: NetworkEgressAttestation,
    environment: Mapping[str, str] | None = None,
) -> StrictHttpsTransport:
    """Assemble the strict transport with an optional fixed deployment proxy."""

    values = os.environ if environment is None else environment
    proxy_url = values.get(PROVIDER_HTTPS_PROXY_ENV, "").strip()
    connection_factory = (
        HttpsConnectProxyConnectionFactory(proxy_url) if proxy_url else None
    )
    return StrictHttpsTransport(
        exact_endpoint_urls,
        egress_attestation=attestation,
        connection_factory=connection_factory,
    )


def _evidence_document(raw: str | None) -> Mapping[str, Any]:
    if raw is None or not raw.strip():
        raise ValueError(f"{EVIDENCE_ENV} is required")
    if len(raw.encode("utf-8")) > 64_000:
        raise ValueError("provider evidence bundle exceeds the size limit")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError("provider evidence bundle is invalid JSON") from None
    document = _exact_object(
        value,
        {"version", "capabilities", "runtimeEvidence", "egressAttestation"},
        "provider evidence bundle",
    )
    if document["version"] != "1.0":
        raise ValueError("provider evidence bundle version is unsupported")
    return document


def _capabilities(raw: Any) -> tuple[Capability, ...]:
    items = _bounded_array(raw, "capabilities", 16)
    result = []
    keys: set[tuple[str, str]] = set()
    for raw_item in items:
        item = _exact_object(
            raw_item,
            {
                "provider", "operation", "documentationState",
                "keyVerificationState", "productionState", "fixtureOnly",
            },
            "provider capability",
        )
        key = (_text(item["provider"]), _text(item["operation"]))
        if key not in KAKAO_BASELINE_OPERATIONS or key in keys:
            raise ValueError("provider capability scope is unknown or duplicated")
        if not isinstance(item["fixtureOnly"], bool):
            raise ValueError("provider capability fixtureOnly must be boolean")
        try:
            capability = Capability(
                provider=key[0],
                operation=key[1],
                documentation_state=DocumentationState(item["documentationState"]),
                key_verification_state=KeyVerificationState(item["keyVerificationState"]),
                production_state=ProductionState(item["productionState"]),
                fixture_only=item["fixtureOnly"],
            )
        except (TypeError, ValueError):
            raise ValueError("provider capability state is invalid") from None
        result.append(capability)
        keys.add(key)
    if keys != set(KAKAO_BASELINE_OPERATIONS):
        raise ValueError("provider capability bundle must cover the exact Kakao baseline")
    return tuple(result)


def _runtime_evidence(raw: Any) -> tuple[RuntimeEvidence, ...]:
    items = _bounded_array(raw, "runtimeEvidence", 32)
    result = []
    keys: set[tuple[str, str, RuntimeEvidenceKind]] = set()
    for raw_item in items:
        item = _exact_object(
            raw_item,
            {
                "provider", "operation", "kind", "evidenceId", "artifactSha256",
                "version", "issuedAt", "expiresAt",
            },
            "provider runtime evidence",
        )
        provider = _text(item["provider"])
        operation = _text(item["operation"])
        if (provider, operation) not in KAKAO_BASELINE_OPERATIONS:
            raise ValueError("provider runtime evidence scope is unknown")
        try:
            kind = RuntimeEvidenceKind(item["kind"])
        except (TypeError, ValueError):
            raise ValueError("provider runtime evidence kind is invalid") from None
        key = (provider, operation, kind)
        if key in keys:
            raise ValueError("provider runtime evidence scope is duplicated")
        version = _text(item["version"])
        if (
            kind is RuntimeEvidenceKind.RESPONSE_SCHEMA
            and version != KAKAO_BASELINE_SCHEMA_VERSIONS[(provider, operation)]
        ):
            raise ValueError("provider response schema evidence version mismatches source")
        try:
            evidence = RuntimeEvidence(
                provider=provider,
                operation=operation,
                kind=kind,
                evidence_id=_text(item["evidenceId"]),
                artifact_sha256=_text(item["artifactSha256"]),
                version=version,
                issued_at=_aware_time(item["issuedAt"]),
                expires_at=_aware_time(item["expiresAt"]),
            )
        except (TypeError, ValueError):
            raise ValueError("provider runtime evidence is invalid") from None
        result.append(evidence)
        keys.add(key)
    expected = {
        (provider, operation, kind)
        for provider, operation in KAKAO_BASELINE_OPERATIONS
        for kind in RuntimeEvidenceKind
    }
    if keys != expected:
        raise ValueError("runtime evidence must cover every Kakao operation and kind")
    return tuple(result)


def _egress_attestation(raw: Any) -> NetworkEgressAttestation:
    item = _exact_object(
        raw,
        {"evidenceId", "artifactSha256", "version", "issuedAt", "expiresAt", "enforcement"},
        "provider egress attestation",
    )
    try:
        enforcement = EgressEnforcement(item["enforcement"])
        return NetworkEgressAttestation(
            evidence_id=_text(item["evidenceId"]),
            artifact_sha256=_text(item["artifactSha256"]),
            version=_text(item["version"]),
            issued_at=_aware_time(item["issuedAt"]),
            expires_at=_aware_time(item["expiresAt"]),
            enforcement=enforcement,
        )
    except (TypeError, ValueError):
        raise ValueError("provider egress attestation is invalid") from None


def _secret(raw: str | None, name: str) -> str:
    if (
        raw is None
        or not raw.strip()
        or len(raw) > 512
        or any(ord(character) < 33 or ord(character) > 126 for character in raw)
    ):
        raise ValueError(f"{name} is missing or invalid")
    return raw


def _aware_time(raw: Any) -> datetime:
    if not isinstance(raw, str) or len(raw) > 64:
        raise ValueError("evidence timestamp is invalid")
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    require_aware(value, "evidence timestamp")
    return value


def _exact_object(raw: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ValueError(f"{path} schema mismatch")
    return raw


def _bounded_array(raw: Any, path: str, maximum: int) -> list[Any]:
    if not isinstance(raw, list) or len(raw) > maximum:
        raise ValueError(f"{path} must be a bounded array")
    return raw


def _text(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 256:
        raise ValueError("provider evidence text is invalid")
    return raw


__all__ = [
    "EVIDENCE_ENV",
    "KAKAO_BASELINE_KEY_ENV",
    "KAKAO_BASELINE_OPERATIONS",
    "KAKAO_BASELINE_SCHEMA_VERSIONS",
    "PROVIDER_OPERATION_KEY_ENV",
    "PROVIDER_HTTPS_PROXY_ENV",
    "build_kakao_baseline_config",
    "build_strict_https_transport",
]
