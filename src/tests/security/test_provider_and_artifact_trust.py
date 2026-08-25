from __future__ import annotations

import json
import re
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from model_foundation import (
    ArtifactIntegrityError,
    ArtifactMetadata,
    eta_feature_target_metadata,
    verify_artifact,
)
from provider_core.adapters import FixtureScenario, FixtureTransitAdapter
from provider_core.canonical import Coordinate
from provider_core.capabilities import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
    foundation_capability_registry,
)
from provider_core.envelope import ProviderStatus, QualityFlag
from provider_core.http import HttpRequest, SensitiveValue
from provider_core.named import (
    ENDPOINT_SPECS,
    ProviderAdapterSuite,
    ProviderCall,
    ProviderFixtureScenario,
)
from provider_core.requests import TransitSearchRequest
from provider_core.resilience import Deadline
from provider_core.validation import (
    EndpointRule,
    FixedEndpointAllowlist,
    InputValidationError,
    ObjectSchema,
    SchemaValidationError,
    is_non_negative_int,
    is_string,
    validate_limit,
)
from routing_api.persistence.admin_services import (
    AdminValidationError,
    ArtifactDescriptor,
    Sha256ArtifactVerifier,
)


KST = timezone(timedelta(hours=9))
FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "provider-core"
    / "provider_core"
    / "fixtures"
)


def _request() -> TransitSearchRequest:
    return TransitSearchRequest(
        origin=Coordinate(127.1, 37.4),
        destination=Coordinate(127.2, 37.5),
        departure_time=datetime(2026, 8, 23, 9, 0, tzinfo=KST),
    )


def _artifact_metadata(filename: str, content: bytes) -> ArtifactMetadata:
    schema = eta_feature_target_metadata()
    return ArtifactMetadata(
        model_family="ETA",
        model_version="fixture-only",
        artifact_filename=filename,
        artifact_format="LIGHTGBM_TEXT",
        artifact_sha256=sha256(content).hexdigest(),
        feature_schema_version=schema.feature_schema_version,
        feature_names=schema.feature_names,
    )


def test_fixed_provider_allowlist_rejects_ssrf_and_embedded_credentials() -> None:
    expected = "https://api.example.invalid/v1/route"
    allowlist = FixedEndpointAllowlist(EndpointRule("provider", "route", expected))
    assert allowlist.resolve("provider", "route") == expected

    for supplied in (
        "http://api.example.invalid/v1/route",
        "https://attacker.invalid/v1/route",
        "https://api.example.invalid/v1/route?url=https://attacker.invalid",
        "https://api.example.invalid/v1/route#https://attacker.invalid",
    ):
        with pytest.raises(InputValidationError):
            allowlist.assert_exact("provider", "route", supplied)

    with pytest.raises(InputValidationError):
        allowlist.resolve("provider", "request-selected-operation")
    with pytest.raises(ValueError):
        EndpointRule("provider", "route", "https://secret@example.invalid/v1/route")
    with pytest.raises(ValueError):
        EndpointRule("provider", "route", "http://example.invalid/v1/route")


def test_named_endpoint_inventory_is_exact_https_or_deliberately_unpinned() -> None:
    assert len(ENDPOINT_SPECS) == 14
    for spec in ENDPOINT_SPECS:
        if spec.url is None:
            assert (spec.provider, spec.operation) in {
                ("GBIS_V2", "locations"),
                ("GBIS_V2", "stations"),
                ("GITS", "traffic_context"),
            }
            continue
        parsed = urlsplit(spec.url)
        assert parsed.scheme == "https"
        assert parsed.hostname
        assert parsed.username is parsed.password is None
        assert parsed.query == parsed.fragment == ""


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[HttpRequest] = []

    def send(self, request: HttpRequest):
        self.calls.append(request)
        raise AssertionError("live network seam must remain unreachable")


def _promoted_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        Capability(
            provider=spec.provider,
            operation=spec.operation,
            documentation_state=DocumentationState.DOCUMENTED,
            key_verification_state=KeyVerificationState.KEY_VERIFIED,
            production_state=ProductionState.PRODUCTION_APPROVED,
            fixture_only=False,
        )
        for spec in ENDPOINT_SPECS
    )


def test_fixture_and_unverified_named_adapters_never_call_network_or_promote_capability() -> None:
    transport = RecordingTransport()
    suite = ProviderAdapterSuite(transport)
    registry = foundation_capability_registry()

    for adapter in (
        suite.kakao_transit,
        suite.kakao_walk,
        suite.kakao_mobility,
        suite.gbis,
        suite.kma,
        suite.gits,
        suite.tmap,
        suite.odsay,
    ):
        for operation in adapter.operations:
            disabled = adapter.invoke(
                operation,
                ProviderCall(f"disabled:{adapter.provider}:{operation}"),
                deadline=Deadline.after_ms(100),
            )
            assert disabled.status is ProviderStatus.DISABLED
            fixture = adapter.fixture(operation, ProviderFixtureScenario.SUCCESS)
            assert QualityFlag.SANITIZED_FIXTURE in fixture.quality_flags

    assert transport.calls == []
    assert all(not capability.enabled for capability in registry.all())
    assert all(capability.fixture_only for capability in registry.all())


def test_key_and_approval_promotion_alone_cannot_execute_unverified_schema_or_unpinned_url() -> None:
    transport = RecordingTransport()
    suite = ProviderAdapterSuite(
        transport,
        capabilities=_promoted_registry(),
        credential=SensitiveValue("provider-key-must-never-be-sent"),
    )
    for adapter in (
        suite.kakao_transit,
        suite.kakao_walk,
        suite.kakao_mobility,
        suite.gbis,
        suite.kma,
        suite.gits,
        suite.tmap,
        suite.odsay,
    ):
        for operation in adapter.operations:
            result = adapter.invoke(
                operation,
                ProviderCall(f"promoted:{adapter.provider}:{operation}"),
                deadline=Deadline.after_ms(100),
            )
            assert result.status is ProviderStatus.DISABLED
            assert result.latency_ms == 0
            assert result.cache_hit is False
            assert result.payload is None
    assert transport.calls == []


def test_secret_values_and_http_summaries_never_render_credentials_or_raw_body() -> None:
    secret = "super-secret-provider-key"
    request = HttpRequest(
        "POST",
        "https://api.example.invalid/v1/route",
        headers=(("Authorization", SensitiveValue(secret)),),
        query=(("apiKey", SensitiveValue(secret)),),
        json_body={"coordinate": {"lon": 127.1, "lat": 37.2}},
    )
    rendered = repr(request)
    summary = json.dumps(request.safe_summary(), sort_keys=True)
    assert secret not in rendered
    assert secret not in summary
    assert "127.1" not in summary
    assert summary.count("***") == 2


def test_provider_input_and_response_schema_fail_closed() -> None:
    schema = ObjectSchema(required={"id": is_string, "count": is_non_negative_int})
    for untrusted in (
        {"id": "ok"},
        {"id": "ok", "count": True},
        {"id": "ok", "count": "0"},
        {"id": "ok", "count": 0, "rawPayload": {"secret": "x"}},
    ):
        with pytest.raises(SchemaValidationError):
            schema.validate(untrusted)

    for value in (0, 101, True, "10"):
        with pytest.raises(InputValidationError):
            validate_limit(value, minimum=1, maximum=100)  # type: ignore[arg-type]
    for lon, lat in ((float("nan"), 37.4), (127.1, float("inf")), (181.0, 37.4), (127.1, 91.0)):
        with pytest.raises(ValueError):
            Coordinate(lon, lat)


def test_adapter_schema_drift_never_surfaces_untrusted_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = FixtureTransitAdapter(FixtureScenario.SUCCESS)
    malicious = {
        "fixtureVersion": "1",
        "scenario": "success",
        "provider": adapter.provider,
        "operation": adapter.operation,
        "fetchedAt": "2026-08-23T09:00:00+09:00",
        "receivedAt": "2026-08-23T09:00:00+09:00",
        "observedAt": None,
        "schemaVersion": "fixture-v1",
        "status": "OK",
        "results": [],
        "apiKey": "must-not-cross",
    }
    monkeypatch.setattr(adapter, "_read_fixture", lambda _: json.dumps(malicious).encode())

    result = adapter.search(_request(), deadline=Deadline.after_ms(1000))
    assert result.status is ProviderStatus.BAD_RESPONSE
    assert result.payload is None
    assert result.normalized_count == 0
    assert QualityFlag.SCHEMA_DRIFT in result.quality_flags
    assert "must-not-cross" not in repr(result)


def test_sanitized_fixtures_and_envelopes_contain_no_secret_plate_or_raw_field() -> None:
    forbidden_keys = {
        "authorization",
        "apikey",
        "api_key",
        "access_token",
        "secret",
        "rawpayload",
        "raw_payload",
        "plate",
        "vehicleplate",
    }
    korean_plate = re.compile(r"\d{2,3}[가-힣]\d{4}")
    for path in FIXTURE_ROOT.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        document = json.loads(text)
        stack = [document]
        keys: set[str] = set()
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                keys.update(str(key).lower() for key in value)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
        assert keys.isdisjoint(forbidden_keys), path
        assert korean_plate.search(text) is None, path

    result = FixtureTransitAdapter(FixtureScenario.SUCCESS).search(
        _request(), deadline=Deadline.after_ms(1000)
    )
    envelope_fields = {item.name.lower() for item in fields(result)}
    assert envelope_fields.isdisjoint(forbidden_keys)
    assert not isinstance(result.payload, (dict, str, bytes))


def test_artifact_rejects_traversal_pickle_and_hash_mismatch(tmp_path: Path) -> None:
    content = b"tree\nfixture-only\n"
    artifact = tmp_path / "model.txt"
    artifact.write_bytes(content)

    with pytest.raises(ArtifactIntegrityError):
        _artifact_metadata("../model.txt", content)
    with pytest.raises(ArtifactIntegrityError):
        ArtifactMetadata(
            model_family="ETA",
            model_version="fixture-only",
            artifact_filename="model.pkl",
            artifact_format="PICKLE",
            artifact_sha256=sha256(content).hexdigest(),
            feature_schema_version="eta-feature-foundation-v1",
            feature_names=("route_id",),
        )

    metadata = _artifact_metadata("model.txt", b"different bytes")
    schema = eta_feature_target_metadata()
    with pytest.raises(ArtifactIntegrityError, match="SHA-256"):
        verify_artifact(
            tmp_path,
            metadata,
            runtime_feature_schema_version=schema.feature_schema_version,
            runtime_feature_names=schema.feature_names,
        )


def test_artifact_rejects_symlink_and_schema_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"tree\nfixture-only\n"
    artifact = tmp_path / "model.txt"
    artifact.write_bytes(content)

    metadata = _artifact_metadata("model.txt", content)
    schema = eta_feature_target_metadata()
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "model.txt")
    with pytest.raises(ArtifactIntegrityError, match="symbolic-link"):
        verify_artifact(
            tmp_path,
            metadata,
            runtime_feature_schema_version=schema.feature_schema_version,
            runtime_feature_names=schema.feature_names,
        )

    monkeypatch.setattr(Path, "is_symlink", original_is_symlink)
    with pytest.raises(ArtifactIntegrityError, match="schema version"):
        verify_artifact(
            tmp_path,
            metadata,
            runtime_feature_schema_version="wrong-schema",
            runtime_feature_names=schema.feature_names,
        )


def test_admin_artifact_verifier_rejects_pickle_ambiguous_uri_and_path_traversal() -> None:
    content = b"deterministic-safe-artifact"
    digest = sha256(content).hexdigest()
    verifier = Sha256ArtifactVerifier(
        loader=lambda _: content,
        allowed_buckets=frozenset({"routing-model-registry"}),
        allowed_feature_schemas=frozenset({"bus-features-v1"}),
    )
    verifier.verify(
        ArtifactDescriptor(
            "gs://routing-model-registry/models/eta.onnx",
            digest,
            "bus-features-v1",
        )
    )
    for uri in (
        "gs://routing-model-registry/models/eta.pkl",
        "gs://routing-model-registry/models/../eta.onnx",
        "gs://routing-model-registry/models/%2e%2e/eta.onnx",
        "gs://routing-model-registry/models\\eta.onnx",
        "gs://user@routing-model-registry/models/eta.onnx",
        "gs://routing-model-registry:443/models/eta.onnx",
        "gs://routing-model-registry/models/eta.onnx?versionId=mutable",
        "gs://routing-model-registry/models/eta.onnx#fragment",
    ):
        with pytest.raises(AdminValidationError):
            verifier.verify(ArtifactDescriptor(uri, digest, "bus-features-v1"))
