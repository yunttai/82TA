"""Fail-closed environment assembly for reviewed live Provider scopes.

The factory is deployment-owned input parsing, not an approval authority.  A key's
presence never changes capability state.  All approval and runtime evidence must be
supplied as an exact, non-secret external bundle and remains subject to the adapter's
normal runtime gate.
"""

from __future__ import annotations

import hashlib
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
from .context import OpaqueVehicleTokenIssuer
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
GBIS_LIVE_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("GBIS_V2", "arrivals"),
    ("GBIS_V2", "locations"),
)
KAKAO_GBIS_OPERATIONS: tuple[tuple[str, str], ...] = (
    KAKAO_BASELINE_OPERATIONS + GBIS_LIVE_OPERATIONS
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
KAKAO_GBIS_KEY_ENV: Mapping[tuple[str, str], str] = {
    operation: PROVIDER_OPERATION_KEY_ENV[operation]
    for operation in KAKAO_GBIS_OPERATIONS
}
KAKAO_BASELINE_SCHEMA_VERSIONS: Mapping[tuple[str, str], str] = {
    (spec.provider, spec.operation): spec.response_schema_version
    for spec in ENDPOINT_SPECS
    if (spec.provider, spec.operation) in KAKAO_BASELINE_OPERATIONS
    and spec.response_schema_version is not None
}
if set(KAKAO_BASELINE_SCHEMA_VERSIONS) != set(KAKAO_BASELINE_OPERATIONS):
    raise RuntimeError("Kakao baseline response schema mapping is incomplete")
KAKAO_GBIS_SCHEMA_VERSIONS: Mapping[tuple[str, str], str] = {
    (spec.provider, spec.operation): spec.response_schema_version
    for spec in ENDPOINT_SPECS
    if (spec.provider, spec.operation) in KAKAO_GBIS_OPERATIONS
    and spec.response_schema_version is not None
}
if set(KAKAO_GBIS_SCHEMA_VERSIONS) != set(KAKAO_GBIS_OPERATIONS):
    raise RuntimeError("Kakao and GBIS response schema mapping is incomplete")
EVIDENCE_ENV = "ROUTING_PROVIDER_EVIDENCE_JSON"
PROVIDER_HTTPS_PROXY_ENV = "ROUTING_PROVIDER_HTTPS_PROXY_URL"


def build_kakao_baseline_config() -> ProviderAdapterSuiteConfig:
    """Build exact operation bindings from environment, without inferring approval."""

    return _build_provider_config(
        KAKAO_BASELINE_OPERATIONS,
        KAKAO_BASELINE_SCHEMA_VERSIONS,
        scope_name="Kakao baseline",
        include_gbis_token_issuer=False,
    )


def build_kakao_gbis_config() -> ProviderAdapterSuiteConfig:
    """Build the Kakao baseline plus reviewed GBIS arrival/location bindings."""

    return _build_provider_config(
        KAKAO_GBIS_OPERATIONS,
        KAKAO_GBIS_SCHEMA_VERSIONS,
        scope_name="Kakao and GBIS scope",
        include_gbis_token_issuer=True,
    )


def _build_provider_config(
    operations: tuple[tuple[str, str], ...],
    schema_versions: Mapping[tuple[str, str], str],
    *,
    scope_name: str,
    include_gbis_token_issuer: bool,
) -> ProviderAdapterSuiteConfig:
    document = _evidence_document(os.environ.get(EVIDENCE_ENV))
    capabilities = _capabilities(
        document["capabilities"], operations=operations, scope_name=scope_name
    )
    runtime_evidence = _runtime_evidence(
        document["runtimeEvidence"],
        operations=operations,
        schema_versions=schema_versions,
    )
    attestation = _egress_attestation(document["egressAttestation"])
    specs = {
        (spec.provider, spec.operation): spec
        for spec in ENDPOINT_SPECS
        if (spec.provider, spec.operation) in operations
    }
    if set(specs) != set(operations):
        raise ValueError(f"{scope_name} endpoint specification is incomplete")
    urls = tuple(specs[key].url for key in operations)
    if any(url is None for url in urls):
        raise ValueError(f"{scope_name} endpoint is not pinned")
    transport = build_strict_https_transport(
        tuple(url for url in urls if url is not None),
        attestation=attestation,
    )
    bindings = []
    secrets: dict[str, str] = {}
    for provider, operation in operations:
        env_name = PROVIDER_OPERATION_KEY_ENV[(provider, operation)]
        secret = _secret(os.environ.get(env_name), env_name)
        secrets[env_name] = secret
        bindings.append(ProviderOperationBinding(
            transport=ScopedProviderTransport(provider, operation, transport),
            credential=ScopedProviderCredential(
                provider, operation, SensitiveValue(secret)
            ),
        ))
    token_issuer = None
    if include_gbis_token_issuer:
        token_issuer = _gbis_vehicle_token_issuer(secrets["GBIS_SERVICE_KEY"])
    return ProviderAdapterSuiteConfig(
        bindings=tuple(bindings),
        capabilities=CapabilityRegistry(capabilities),
        runtime_evidence=ProviderRuntimeEvidenceConfig(runtime_evidence),
        gbis_vehicle_token_issuer=token_issuer,
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


def _capabilities(
    raw: Any,
    *,
    operations: tuple[tuple[str, str], ...] = KAKAO_BASELINE_OPERATIONS,
    scope_name: str = "Kakao baseline",
) -> tuple[Capability, ...]:
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
        if key not in operations or key in keys:
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
    if keys != set(operations):
        raise ValueError(
            f"provider capability bundle must cover the exact {scope_name}"
        )
    return tuple(result)


def _runtime_evidence(
    raw: Any,
    *,
    operations: tuple[tuple[str, str], ...] = KAKAO_BASELINE_OPERATIONS,
    schema_versions: Mapping[
        tuple[str, str], str
    ] = KAKAO_BASELINE_SCHEMA_VERSIONS,
) -> tuple[RuntimeEvidence, ...]:
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
        if (provider, operation) not in operations:
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
            and version != schema_versions[(provider, operation)]
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
        for provider, operation in operations
        for kind in RuntimeEvidenceKind
    }
    if keys != expected:
        raise ValueError("runtime evidence must cover every configured operation and kind")
    return tuple(result)


def _gbis_vehicle_token_issuer(service_key: str) -> OpaqueVehicleTokenIssuer:
    key = hashlib.sha256(
        b"82TA GBIS vehicle token v1\x00" + service_key.encode("ascii")
    ).digest()
    return OpaqueVehicleTokenIssuer(key)


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
    "GBIS_LIVE_OPERATIONS",
    "KAKAO_BASELINE_KEY_ENV",
    "KAKAO_BASELINE_OPERATIONS",
    "KAKAO_BASELINE_SCHEMA_VERSIONS",
    "KAKAO_GBIS_KEY_ENV",
    "KAKAO_GBIS_OPERATIONS",
    "KAKAO_GBIS_SCHEMA_VERSIONS",
    "PROVIDER_OPERATION_KEY_ENV",
    "PROVIDER_HTTPS_PROXY_ENV",
    "build_kakao_baseline_config",
    "build_kakao_gbis_config",
    "build_strict_https_transport",
]
