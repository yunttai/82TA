from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

from django.test import Client
from unittest.mock import patch

from routing_api.admin import AdminControlPlane
from routing_api.auth import Hs256ServiceBearerVerifier
from routing_api.persistence.admin_services import (
    CacheInvalidationService,
    InMemoryImmutableAuditLog,
    ModelActivationService,
    Sha256ArtifactVerifier,
)
from routing_api.persistence.records import ModelArtifactRecord
from routing_api.tests.test_persistence import FakeCache, FakeRegistry


NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)
SECRET = b"routing-admin-test-secret-that-is-long-enough"


def _segment(value: object) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(value, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()


def _token(*, roles=("routing-admin",), environments=("staging",)) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    claims = _segment({
        "iss": "service-api",
        "aud": "routing-api",
        "sub": "operator-123",
        "jti": "admin-jti-123",
        "exp": int((NOW + timedelta(minutes=5)).timestamp()),
        "roles": list(roles),
        "environments": list(environments),
    })
    signature = hmac.new(SECRET, f"{header}.{claims}".encode(), hashlib.sha256).digest()
    return f"{header}.{claims}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _control():
    artifact_payload = b"approved-artifact"
    registry = FakeRegistry(ModelArtifactRecord(
        uuid.uuid4(),
        "BUS_ETA",
        "eta-1.0.0",
        "VALIDATED",
        "gs://routing-model-registry/eta-1.0.0.onnx",
        hashlib.sha256(artifact_payload).hexdigest(),
        "bus-features-v1",
    ))
    cache = FakeCache()
    audit = InMemoryImmutableAuditLog()
    control = AdminControlPlane(
        verifier=Hs256ServiceBearerVerifier(
            SECRET, "service-api", "routing-api", now=lambda: NOW
        ),
        cache_service=CacheInvalidationService(
            invalidator=cache,
            audit=audit,
            allowed_namespaces=frozenset({"provider-routes", "model-runtime"}),
            allowed_environments=frozenset({"staging"}),
            clock=lambda: NOW,
        ),
        model_service=ModelActivationService(
            registry=registry,
            verifier=Sha256ArtifactVerifier(
                loader=lambda _: artifact_payload,
                allowed_buckets=frozenset({"routing-model-registry"}),
                allowed_feature_schemas=frozenset({"bus-features-v1"}),
            ),
            audit=audit,
            allowed_environments=frozenset({"staging"}),
            clock=lambda: NOW,
        ),
        cache_environment="staging",
    )
    return control, cache, audit, registry


def test_default_admin_control_plane_remains_fail_closed_404() -> None:
    response = Client().post(
        "/internal/admin/cache/invalidate",
        data=json.dumps({"namespace": "provider-routes"}),
        content_type="application/json",
    )
    assert response.status_code == 404


def test_injected_admin_cache_requires_operator_claim_and_audits() -> None:
    control, cache, audit, _ = _control()
    with patch("routing_api.views.get_admin_control_plane", return_value=control):
        forbidden = Client().post(
            "/internal/admin/cache/invalidate",
            data=json.dumps({"namespace": "provider-routes"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token(roles=('service-api',))}",
        )
        assert forbidden.status_code == 403
        accepted = Client().post(
            "/internal/admin/cache/invalidate",
            data=json.dumps({"namespace": "provider-routes", "fingerprint": "a" * 64}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token()}",
            HTTP_X_CORRELATION_ID="admin-cache-1",
        )
    assert accepted.status_code == 202
    assert cache.calls == [("provider-routes", "a" * 64)]
    assert audit.events[-1].operator_subject == "operator-123"


def test_admin_json_ambiguity_is_rejected_before_cache_side_effect() -> None:
    control, cache, audit, _ = _control()
    with patch("routing_api.views.get_admin_control_plane", return_value=control):
        duplicate = Client().post(
            "/internal/admin/cache/invalidate",
            data=b'{"namespace":"provider-routes","namespace":"model-runtime"}',
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token()}",
        )
        non_finite = Client().post(
            "/internal/admin/cache/invalidate",
            data=b'{"namespace":"provider-routes","fingerprint":NaN}',
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token()}",
        )
    assert duplicate.status_code == 400
    assert non_finite.status_code == 400
    assert cache.calls == []
    assert audit.events == ()


def test_injected_model_activation_validates_artifact_and_lifecycle() -> None:
    control, _, audit, registry = _control()
    with patch("routing_api.views.get_admin_control_plane", return_value=control):
        accepted = Client().post(
            "/internal/admin/models/eta-1.0.0/activate",
            data=json.dumps({"purpose": "BUS_ETA", "environment": "staging", "trafficFraction": 0}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token()}",
        )
        conflict = Client().post(
            "/internal/admin/models/eta-1.0.0/activate",
            data=json.dumps({"purpose": "BUS_ETA", "environment": "staging", "trafficFraction": 0}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token()}",
        )
    assert accepted.status_code == 202
    assert accepted.json()["state"] == "SHADOW"
    assert conflict.status_code == 503
    assert conflict.json()["code"] == "MODEL_NOT_READY"
    assert registry.transitions == [("VALIDATED", "SHADOW", 0.0)]
    assert audit.events[-1].action == "MODEL_TRANSITIONED"


def test_admin_json_ambiguity_is_rejected_before_model_side_effect() -> None:
    control, _, audit, registry = _control()
    with patch("routing_api.views.get_admin_control_plane", return_value=control):
        duplicate = Client().post(
            "/internal/admin/models/eta-1.0.0/activate",
            data=b'{"purpose":"BUS_ETA","purpose":"SEAT_RISK","environment":"staging"}',
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token()}",
        )
        non_finite = Client().post(
            "/internal/admin/models/eta-1.0.0/activate",
            data=b'{"purpose":"BUS_ETA","environment":"staging","trafficFraction":Infinity}',
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token()}",
        )
    assert duplicate.status_code == 400
    assert non_finite.status_code == 400
    assert registry.transitions == []
    assert audit.events == ()
