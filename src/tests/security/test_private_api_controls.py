from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from django.test import Client

from routing_api.application import (
    FixtureOptimizeRouteUseCase,
    InMemoryIdempotencyStore,
    RoutingApiApplication,
)
from routing_api.auth import AuthenticationError, Hs256ServiceBearerVerifier
from routing_api.contract import CanonicalContractValidator


NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
SECRET = b"routing-api-local-security-test-secret-long-enough"
REQUEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "openapi"
    / "examples"
    / "routing-optimize-request.json"
)
_MISSING = object()


@dataclass
class FixedClock:
    wall: datetime = NOW

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return time.monotonic()


def _segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(
    clock: FixedClock,
    *,
    secret: bytes = SECRET,
    issuer: str = "service-api",
    audience: object = "routing-api",
    expires_in: float = 300,
    not_before: float | None = None,
    jti: object = "jti-security-001",
) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    claims: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "sub": "service-api-security-test",
        "exp": int((clock.now() + timedelta(seconds=expires_in)).timestamp()),
    }
    if not_before is not None:
        claims["nbf"] = int((clock.now() + timedelta(seconds=not_before)).timestamp())
    if jti is not _MISSING:
        claims["jti"] = jti
    payload = _segment(claims)
    signature = hmac.new(secret, f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _signed_claims(claims: dict[str, object]) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload = _segment(claims)
    signature = hmac.new(
        SECRET, f"{header}.{payload}".encode("ascii"), hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _request_payload() -> dict[str, object]:
    return json.loads(REQUEST_PATH.read_text(encoding="utf-8"))


def _application(clock: FixedClock, *, optional_complete: bool = True) -> RoutingApiApplication:
    return RoutingApiApplication(
        verifier=Hs256ServiceBearerVerifier(
            secret=SECRET,
            issuer="service-api",
            audience="routing-api",
            now=clock.now,
        ),
        contract=CanonicalContractValidator(),
        use_case=FixtureOptimizeRouteUseCase(clock, optional_complete=optional_complete),
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version="security-test",
    )


def _optimize(app: RoutingApiApplication, clock: FixedClock, payload: object, key: str):
    token = _token(clock)
    result = app.optimize(
        authorization=f"Bearer {token}",
        correlation_id="security-correlation",
        deadline_header=(clock.now() + timedelta(seconds=10)).isoformat(),
        idempotency_key=key,
        content_type="application/json",
        raw_body=json.dumps(payload).encode(),
    )
    return result, token


def test_service_bearer_validates_signature_issuer_audience_expiry_and_nbf() -> None:
    clock = FixedClock()
    verifier = Hs256ServiceBearerVerifier(SECRET, "service-api", "routing-api", clock.now)
    assert verifier.verify(f"Bearer {_token(clock)}")["jti"] == "jti-security-001"
    assert verifier.verify(f"Bearer {_token(clock, audience=['other', 'routing-api'])}")["aud"] == [
        "other",
        "routing-api",
    ]

    invalid = (
        _token(clock, secret=b"x" * 48),
        _token(clock, issuer="attacker"),
        _token(clock, audience="other"),
        _token(clock, expires_in=-1),
        _token(clock, not_before=30),
    )
    for token in invalid:
        with pytest.raises(AuthenticationError):
            verifier.verify(f"Bearer {token}")
    with pytest.raises(AuthenticationError):
        verifier.verify(None)


def test_service_bearer_secret_is_redacted_from_repr_and_errors() -> None:
    clock = FixedClock()
    verifier = Hs256ServiceBearerVerifier(SECRET, "service-api", "routing-api", clock.now)
    assert SECRET.decode("utf-8") not in repr(verifier)
    with pytest.raises(AuthenticationError) as captured:
        verifier.verify("Bearer malformed")
    assert SECRET.decode("utf-8") not in str(captured.value)


def test_service_bearer_requires_nonblank_string_jti() -> None:
    clock = FixedClock()
    verifier = Hs256ServiceBearerVerifier(SECRET, "service-api", "routing-api", clock.now)
    invalid_jti_values = (_MISSING, None, "", "   ", True, 1, 1.5, {}, [])
    for invalid_jti in invalid_jti_values:
        with pytest.raises(AuthenticationError):
            verifier.verify(f"Bearer {_token(clock, jti=invalid_jti)}")


@pytest.mark.parametrize(
    "claims",
    (
        {
            "iss": "service-api",
            "aud": "routing-api",
            "exp": 9_999_999_999,
            "nbf": "later",
            "jti": "malformed-nbf",
        },
        {
            "iss": "service-api",
            "aud": "routing-api",
            "exp": float("inf"),
            "jti": "non-finite-exp",
        },
        {
            "iss": "service-api",
            "aud": ["routing-api", 7],
            "exp": 9_999_999_999,
            "jti": "mixed-audience",
        },
    ),
)
def test_service_bearer_rejects_malformed_numeric_dates_and_audience(
    claims: dict[str, object],
) -> None:
    verifier = Hs256ServiceBearerVerifier(
        SECRET, "service-api", "routing-api", FixedClock().now
    )
    with pytest.raises(AuthenticationError):
        verifier.verify(f"Bearer {_signed_claims(claims)}")


def test_private_routes_require_auth_and_unimplemented_admin_routes_fail_closed() -> None:
    clock = FixedClock()
    app = _application(clock)
    client = Client()
    with patch("routing_api.views.get_application", return_value=app):
        assert client.get("/v1/health/live").status_code == 200
        for path in ("/v1/capabilities", "/v1/health/ready", "/v1/version"):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["code"] == "SERVICE_AUTH_REQUIRED"
        response = client.post(
            "/v1/routes/optimize",
            data=json.dumps(_request_payload()),
            content_type="application/json",
        )
        assert response.status_code == 401

        for path in (
            "/internal/admin/cache/invalidate",
            "/internal/admin/models/fixture-only/activate",
        ):
            assert client.post(path, data="{}", content_type="application/json").status_code == 404


def test_identity_rejection_idempotency_and_problem_response_do_not_leak_secret(caplog) -> None:
    clock = FixedClock()
    app = _application(clock)
    payload = _request_payload()
    payload["userId"] = "forbidden-user"
    rejected, token = _optimize(app, clock, payload, "security-idem-0001")
    serialized = json.dumps(rejected.body)
    assert rejected.status_code == 400
    assert rejected.body["code"] == "CONSTRAINT_OUT_OF_RANGE"
    assert token not in serialized
    assert SECRET.decode() not in serialized
    assert rejected.body["detail"] is None
    assert rejected.body["safeContext"] == {}

    valid = _request_payload()
    first, _ = _optimize(app, clock, valid, "security-idem-0002")
    replay, _ = _optimize(app, clock, valid, "security-idem-0002")
    assert first.status_code == replay.status_code == 200
    assert first.body == replay.body

    changed = copy.deepcopy(valid)
    changed["requestId"] = "01JSECURITYDIFFERENT"
    conflict, _ = _optimize(app, clock, changed, "security-idem-0002")
    assert conflict.status_code == 409
    assert conflict.body["code"] == "IDEMPOTENCY_CONFLICT"

    logs = caplog.text
    assert token not in logs
    assert "127.1" not in logs
    assert "127.2" not in logs




def test_optimize_rejects_header_content_type_and_body_size_abuse_before_spend() -> None:
    clock = FixedClock()
    app = _application(clock)
    token = _token(clock)
    valid_body = json.dumps(_request_payload()).encode()

    def call(**overrides: object):
        values: dict[str, object] = {
            "authorization": f"Bearer {token}",
            "correlation_id": "security-bounds",
            "deadline_header": (clock.now() + timedelta(seconds=10)).isoformat(),
            "idempotency_key": "security-bounds-0001",
            "content_type": "application/json",
            "raw_body": valid_body,
        }
        values.update(overrides)
        return app.optimize(**values)  # type: ignore[arg-type]

    for key in ("short", "x" * 129):
        result = call(idempotency_key=key)
        assert result.status_code == 400
        assert result.body["code"] == "CONSTRAINT_OUT_OF_RANGE"

    wrong_media = call(content_type="text/plain")
    assert wrong_media.status_code == 400
    assert wrong_media.body["code"] == "CONSTRAINT_OUT_OF_RANGE"

    oversized = call(raw_body=b"{" + b" " * 65_536 + b"}")
    assert oversized.status_code == 400
    assert oversized.body["code"] == "CONSTRAINT_OUT_OF_RANGE"

    duplicate = call(raw_body=b'{"contractVersion":"1.0","contractVersion":"1.0"}')
    non_finite = call(raw_body=b'{"contractVersion":"1.0","value":NaN}')
    assert duplicate.status_code == non_finite.status_code == 400
    assert duplicate.body["code"] == non_finite.body["code"] == "CONSTRAINT_OUT_OF_RANGE"
