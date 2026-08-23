from __future__ import annotations

from types import SimpleNamespace

import pytest

from provider_core.capabilities import foundation_capability_registry
from provider_core.runtime import ProviderRuntimeEvidenceConfig
from routing_api.provider_configuration import build_provider_adapter_config


class RecordingTransport:
    def send(self, request):
        raise AssertionError("configuration test must not perform network I/O")


def _settings(**overrides):
    values = {
        "KAKAO_REST_API_KEY": "",
        "GBIS_SERVICE_KEY": "",
        "GITS_API_KEY": "",
        "TMAP_APP_KEY": "",
        "ODSAY_API_KEY": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_mobility_key_is_bound_only_to_the_exact_requested_operation() -> None:
    secret = "mobility-secret-must-not-render"
    transport = RecordingTransport()
    config = build_provider_adapter_config(
        _settings(KAKAO_REST_API_KEY=secret),
        transports={("KAKAO_DIRECTIONS", "route_current"): transport},
        capabilities=foundation_capability_registry(),
        runtime_evidence=ProviderRuntimeEvidenceConfig(),
    )

    assert tuple(config.binding_map) == (("KAKAO_DIRECTIONS", "route_current"),)
    binding = config.binding_map[("KAKAO_DIRECTIONS", "route_current")]
    assert binding.transport.value is transport
    assert secret not in repr(config)
    assert secret not in repr(binding)


def test_secret_presence_does_not_promote_capability_or_evidence() -> None:
    config = build_provider_adapter_config(
        _settings(KAKAO_REST_API_KEY="configured-not-approved"),
        transports={("KAKAO_DIRECTIONS", "route_current"): RecordingTransport()},
        capabilities=foundation_capability_registry(),
        runtime_evidence=ProviderRuntimeEvidenceConfig(),
    )

    assert not config.capabilities.enabled("KAKAO_DIRECTIONS", "route_current")
    assert config.runtime_evidence.all() == ()


def test_transport_without_credential_and_unknown_scope_fail_closed() -> None:
    with pytest.raises(ValueError, match="credential is not configured"):
        build_provider_adapter_config(
            _settings(),
            transports={("KAKAO_DIRECTIONS", "route_current"): RecordingTransport()},
            capabilities=foundation_capability_registry(),
            runtime_evidence=ProviderRuntimeEvidenceConfig(),
        )
    with pytest.raises(ValueError, match="unknown provider operation"):
        build_provider_adapter_config(
            _settings(),
            transports={("UNKNOWN", "route"): RecordingTransport()},
            capabilities=foundation_capability_registry(),
            runtime_evidence=ProviderRuntimeEvidenceConfig(),
        )
