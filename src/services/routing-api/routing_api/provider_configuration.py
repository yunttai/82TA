"""Map deployment credentials to exact provider-operation bindings.

Secret presence never implies capability approval or runtime evidence. A deployment
composition must provide both independently.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from provider_core.capabilities import CapabilityRegistry
from provider_core.http import SensitiveValue
from provider_core.named import (
    ProviderAdapterSuiteConfig,
    ProviderOperationBinding,
    ScopedProviderCredential,
    ScopedProviderTransport,
)
from provider_core.runtime import ProviderRuntimeEvidenceConfig


PROVIDER_CREDENTIAL_SETTING_BY_OPERATION = MappingProxyType(
    {
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
)


def build_provider_adapter_config(
    settings_object: object,
    *,
    transports: Mapping[tuple[str, str], object],
    capabilities: CapabilityRegistry,
    runtime_evidence: ProviderRuntimeEvidenceConfig,
) -> ProviderAdapterSuiteConfig:
    """Build secret-safe exact-operation bindings from Django settings."""

    unknown_transports = set(transports) - set(PROVIDER_CREDENTIAL_SETTING_BY_OPERATION)
    if unknown_transports:
        raise ValueError("unknown provider operation transport")

    bindings: list[ProviderOperationBinding] = []
    for scope, setting_name in PROVIDER_CREDENTIAL_SETTING_BY_OPERATION.items():
        credential = getattr(settings_object, setting_name, "")
        transport = transports.get(scope)
        if transport is not None and not credential:
            raise ValueError(f"credential is not configured for {scope!r}")
        if not credential or transport is None:
            continue
        if not isinstance(credential, str):
            raise TypeError(f"{setting_name} must be a string")
        provider, operation = scope
        bindings.append(
            ProviderOperationBinding(
                ScopedProviderTransport(provider, operation, transport),
                ScopedProviderCredential(
                    provider, operation, SensitiveValue(credential)
                ),
            )
        )
    return ProviderAdapterSuiteConfig(
        bindings=tuple(bindings),
        capabilities=capabilities,
        runtime_evidence=runtime_evidence,
    )
