from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from django.test import Client


SRC_ROOT = Path(__file__).resolve().parents[3]
for relative in ("services/service-api", "generated/routing-client-python"):
    path = str(SRC_ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from journeys.service_auth import Hs256ServiceJwtIssuer  # noqa: E402
from routing_api.application import (  # noqa: E402
    BoundedUseCaseRunner,
    FixtureOptimizeRouteUseCase,
    InMemoryIdempotencyStore,
    OptimizeCommand,
    RequestContext,
    RoutingApiApplication,
    UseCaseResult,
)
from routing_api.auth import Hs256ServiceBearerVerifier  # noqa: E402
from routing_api.contract import CanonicalContractValidator  # noqa: E402


NOW = datetime(2026, 8, 23, 4, 0, tzinfo=timezone.utc)
SECRET = b"cross-workstream-service-jwt-secret-7Vq!4xP@9mK#2sL"
REQUEST_PATH = (
    SRC_ROOT / "contracts" / "openapi" / "examples" / "routing-optimize-request.json"
)


@dataclass
class FixedClock:
    wall: datetime = NOW

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return time.monotonic()


def _payload() -> dict[str, object]:
    return json.loads(REQUEST_PATH.read_text(encoding="utf-8"))


def _issuer(
    *,
    now: datetime = NOW,
    issuer: str = "service-api",
    audience: str = "routing-api",
    ttl_seconds: int = 60,
) -> Hs256ServiceJwtIssuer:
    return Hs256ServiceJwtIssuer(
        secret=SECRET,
        issuer=issuer,
        audience=audience,
        ttl_seconds=ttl_seconds,
        now=lambda: now,
    )


def _application(
    clock: FixedClock,
    *,
    use_case: object | None = None,
    runner: BoundedUseCaseRunner | None = None,
) -> RoutingApiApplication:
    return RoutingApiApplication(
        verifier=Hs256ServiceBearerVerifier(
            secret=SECRET,
            issuer="service-api",
            audience="routing-api",
            now=clock.now,
        ),
        contract=CanonicalContractValidator(),
        use_case=use_case or FixtureOptimizeRouteUseCase(clock),  # type: ignore[arg-type]
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version="cross-workstream-security",
        runner=runner,
    )


def _post(
    client: Client,
    payload: dict[str, object],
    *,
    authorization: str | None,
    correlation_id: str | None = "cross-security-correlation",
    deadline: str | None = None,
    idempotency_key: str | None = "cross-security-idempotency-0001",
):
    headers: dict[str, str] = {}
    if authorization is not None:
        headers["HTTP_AUTHORIZATION"] = authorization
    if correlation_id is not None:
        headers["HTTP_X_CORRELATION_ID"] = correlation_id
    if deadline is not None:
        headers["HTTP_X_REQUEST_DEADLINE"] = deadline
    if idempotency_key is not None:
        headers["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
    return client.post(
        "/v1/routes/optimize",
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )


def _without_jti(authorization: str) -> str:
    token = authorization.removeprefix("Bearer ")
    encoded_header, encoded_payload, _ = token.split(".")
    claims = json.loads(
        base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
    )
    claims.pop("jti")
    replacement = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        SECRET,
        f"{encoded_header}.{replacement}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return (
        "Bearer "
        + f"{encoded_header}.{replacement}."
        + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    )


def test_service_issuer_and_private_http_authentication_are_compatible_and_fail_closed(
    caplog,
) -> None:
    clock = FixedClock()
    app = _application(clock)
    client = Client()
    valid = _issuer().authorization_header()

    invalid = (
        None,
        "Bearer malformed",
        _issuer(issuer="wrong-service").authorization_header(),
        _issuer(audience="wrong-routing").authorization_header(),
        _issuer(now=NOW - timedelta(minutes=2), ttl_seconds=15).authorization_header(),
        _without_jti(valid),
    )
    with patch("routing_api.views.get_application", return_value=app):
        accepted = _post(
            client,
            _payload(),
            authorization=valid,
            deadline=(NOW + timedelta(seconds=5)).isoformat(),
        )
        assert accepted.status_code == 200
        assert accepted["X-Correlation-Id"] == "cross-security-correlation"

        for index, authorization in enumerate(invalid):
            response = _post(
                client,
                _payload(),
                authorization=authorization,
                deadline=(NOW + timedelta(seconds=5)).isoformat(),
                idempotency_key=f"cross-security-auth-{index:04d}",
            )
            assert response.status_code == 401
            assert response.json()["code"] == "SERVICE_AUTH_REQUIRED"

    secret = SECRET.decode("utf-8")
    assert secret not in repr(_issuer())
    assert secret not in caplog.text
    assert valid not in caplog.text
    assert secret not in accepted.content.decode("utf-8")
    assert valid not in accepted.content.decode("utf-8")


def test_private_http_headers_idempotency_conflict_and_correlation_are_enforced() -> None:
    clock = FixedClock()
    app = _application(clock)
    client = Client()
    authorization = _issuer().authorization_header()
    valid_deadline = (NOW + timedelta(seconds=5)).isoformat()

    with patch("routing_api.views.get_application", return_value=app):
        missing_cases = (
            {"correlation_id": None},
            {"deadline": None},
            {"idempotency_key": None},
            {"idempotency_key": "short"},
        )
        for index, overrides in enumerate(missing_cases):
            values = {
                "correlation_id": f"cross-header-{index}",
                "deadline": valid_deadline,
                "idempotency_key": f"cross-header-idempotency-{index:04d}",
            }
            values.update(overrides)
            response = _post(
                client,
                _payload(),
                authorization=authorization,
                **values,
            )
            assert response.status_code == 400
            assert response.json()["code"] == "CONSTRAINT_OUT_OF_RANGE"

        malformed_deadline = _post(
            client,
            _payload(),
            authorization=authorization,
            deadline="2026-08-23T04:00:01",
            idempotency_key="cross-malformed-deadline",
        )
        assert malformed_deadline.status_code == 400
        assert malformed_deadline.json()["code"] == "UNSUPPORTED_TIME"

        expired_deadline = _post(
            client,
            _payload(),
            authorization=authorization,
            deadline=(NOW - timedelta(milliseconds=1)).isoformat(),
            idempotency_key="cross-expired-deadline",
        )
        assert expired_deadline.status_code == 504
        assert expired_deadline.json()["code"] == "ROUTING_DEADLINE_EXCEEDED"

        key = "cross-idempotency-conflict-0001"
        first = _post(
            client,
            _payload(),
            authorization=authorization,
            correlation_id="cross-correlation-first",
            deadline=valid_deadline,
            idempotency_key=key,
        )
        replay = _post(
            client,
            _payload(),
            authorization=authorization,
            correlation_id="cross-correlation-replay",
            deadline=valid_deadline,
            idempotency_key=key,
        )
        changed = copy.deepcopy(_payload())
        changed["requestId"] = "cross-workstream-different-request"
        conflict = _post(
            client,
            changed,
            authorization=authorization,
            correlation_id="cross-correlation-conflict",
            deadline=valid_deadline,
            idempotency_key=key,
        )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert replay["X-Correlation-Id"] == "cross-correlation-replay"
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert conflict.json()["correlationId"] == "cross-correlation-conflict"
    assert conflict["X-Correlation-Id"] == "cross-correlation-conflict"


def test_effective_deadline_is_capped_and_actual_http_timeout_returns_504() -> None:
    clock = FixedClock()
    captured: list[RequestContext] = []
    delegate = FixtureOptimizeRouteUseCase(clock)

    class CapturingUseCase:
        def execute(self, command: OptimizeCommand, context: RequestContext) -> UseCaseResult:
            captured.append(context)
            return delegate.execute(command, context)

    app = _application(clock, use_case=CapturingUseCase())
    authorization = _issuer().authorization_header()
    client = Client()
    with patch("routing_api.views.get_application", return_value=app):
        response = _post(
            client,
            _payload(),
            authorization=authorization,
            deadline=(NOW + timedelta(seconds=30)).isoformat(),
            idempotency_key="cross-effective-deadline",
        )
    assert response.status_code == 200
    assert len(captured) == 1
    assert captured[0].effective_deadline == NOW + timedelta(seconds=6.5)
    assert captured[0].client_deadline == NOW + timedelta(seconds=30)

    class SlowUseCase:
        def execute(self, command: OptimizeCommand, context: RequestContext) -> UseCaseResult:
            time.sleep(0.10)
            return delegate.execute(command, context)

    runner = BoundedUseCaseRunner(maximum_inflight=1)
    slow_app = _application(clock, use_case=SlowUseCase(), runner=runner)
    started = time.perf_counter()
    try:
        with patch("routing_api.views.get_application", return_value=slow_app):
            timed_out = _post(
                client,
                _payload(),
                authorization=authorization,
                correlation_id="cross-deadline-timeout",
                deadline=(NOW + timedelta(milliseconds=20)).isoformat(),
                idempotency_key="cross-deadline-timeout-idempotency",
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
    finally:
        runner.shutdown()

    assert timed_out.status_code == 504
    assert timed_out.json()["code"] == "ROUTING_DEADLINE_EXCEEDED"
    assert timed_out.json()["correlationId"] == "cross-deadline-timeout"
    assert timed_out["X-Correlation-Id"] == "cross-deadline-timeout"
    assert elapsed_ms < 500


def test_deployment_wires_service_jwt_contract_instead_of_a_static_bearer() -> None:
    terraform = (
        SRC_ROOT / "infra" / "terraform" / "modules" / "service-platform" / "main.tf"
    ).read_text(encoding="utf-8")
    required = {
        "SERVICE_ROUTING_JWT_SECRET",
        "SERVICE_ROUTING_JWT_ISSUER",
        "SERVICE_ROUTING_JWT_AUDIENCE",
    }
    missing = sorted(name for name in required if f'name = "{name}"' not in terraform)
    assert not missing, f"Service task is missing Routing JWT configuration: {missing}"
    assert 'name = "SERVICE_ROUTING_SERVICE_TOKEN"' not in terraform
