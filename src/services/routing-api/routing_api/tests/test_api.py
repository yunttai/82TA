from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import Client, SimpleTestCase

from routing_api.application import (
    BoundedUseCaseRunner,
    FixtureOptimizeRouteUseCase,
    InMemoryIdempotencyStore,
    OptimizeCommand,
    RequestContext,
    RoutingCapacityExceeded,
    RoutingApiApplication,
    RoutingDeadlineExceeded,
    UnsupportedRegionError,
    UnavailableOptimizeRouteUseCase,
    UseCaseResult,
)
from routing_api.auth import Hs256ServiceBearerVerifier
from routing_api.capabilities import foundation_capability_projection
from routing_api.contract import CanonicalContractValidator


NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
SECRET = b"routing-api-local-test-secret-that-is-long-enough"


@dataclass
class FakeClock:
    wall: datetime = NOW
    ticks: float = 100.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.ticks


def _segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _token(
    clock: FakeClock,
    *,
    secret: bytes = SECRET,
    jti: object = "service-token-test-1",
    claims_overrides: dict[str, object] | None = None,
) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    claims: dict[str, object] = {
            "iss": "service-api",
            "aud": "routing-api",
            "sub": "service-api-local-test",
            "jti": jti,
            "exp": int((clock.now() + timedelta(minutes=5)).timestamp()),
        }
    claims.update(claims_overrides or {})
    payload = _segment(claims)
    signature = hmac.new(secret, f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{header}.{payload}.{encoded_signature}"


def _request_payload() -> dict[str, object]:
    return {
        "contractVersion": "1.0",
        "requestId": "01JTESTROUTING",
        "origin": {"coordinate": {"lon": 127.1, "lat": 37.2}, "regionHint": None},
        "destination": {"coordinate": {"lon": 127.2, "lat": 37.4}, "regionHint": None},
        "departureTime": "2026-08-23T09:00:00+09:00",
        "arrivalDeadline": None,
        "constraints": {
            "taxiBudget": {"currency": "KRW", "maxAmount": 10000, "strict": True},
            "maxWalkSeconds": 900,
            "maxTransfers": 3,
            "maxTaxiLegs": 2,
            "allowTaxiBridge": False,
            "allowedModes": ["WALK", "TAXI", "BUS", "SUBWAY"],
        },
        "preference": {"profile": "BALANCED"},
        "requestedRecommendations": ["FASTEST", "STABLE", "EFFICIENT", "PUBLIC_TRANSIT_ONLY"],
        "clientContext": {"locale": "ko-KR", "timezone": "Asia/Seoul"},
    }


class RoutingApiTests(SimpleTestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.contract = CanonicalContractValidator()
        self.fixture_use_case = FixtureOptimizeRouteUseCase(self.clock, optional_complete=True)
        self.app = self._application(self.fixture_use_case)
        self.client = Client()
        self.app_patch = patch("routing_api.views.get_application", side_effect=lambda: self.app)
        self.app_patch.start()
        self.addCleanup(self.app_patch.stop)

    def _application(self, use_case: object, *, runner=None) -> RoutingApiApplication:
        return RoutingApiApplication(
            verifier=Hs256ServiceBearerVerifier(
                secret=SECRET,
                issuer="service-api",
                audience="routing-api",
                now=self.clock.now,
            ),
            contract=self.contract,
            use_case=use_case,  # type: ignore[arg-type]
            clock=self.clock,
            idempotency=InMemoryIdempotencyStore(),
            build_version="test-build",
            runner=runner,
            capability_projection=foundation_capability_projection(),
        )

    def _headers(self, deadline_seconds: float = 10) -> dict[str, str]:
        return {
            "HTTP_AUTHORIZATION": f"Bearer {_token(self.clock)}",
            "HTTP_X_CORRELATION_ID": "corr-test-1",
            "HTTP_X_REQUEST_DEADLINE": (self.clock.now() + timedelta(seconds=deadline_seconds)).isoformat(),
            "HTTP_IDEMPOTENCY_KEY": "idem-test-0001",
        }

    def _post(self, payload: object, *, deadline_seconds: float = 10):
        return self.client.post(
            "/v1/routes/optimize",
            data=json.dumps(payload),
            content_type="application/json",
            **self._headers(deadline_seconds),
        )

    def test_liveness_is_public_but_other_status_endpoints_require_service_bearer(self) -> None:
        self.assertEqual(self.client.get("/v1/health/live").json(), {"status": "ok"})
        for path in ("/v1/capabilities", "/v1/health/ready", "/v1/version"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["code"], "SERVICE_AUTH_REQUIRED")

    def test_capabilities_are_false_for_every_unverified_provider_feature(self) -> None:
        response = self.client.get(
            "/v1/capabilities", HTTP_AUTHORIZATION=f"Bearer {_token(self.clock)}"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(any(body["features"].values()))
        self.assertTrue(all(item["keyVerificationState"] == "UNVERIFIED" for item in body["providers"]))
        self.assertTrue(all(item["productionState"] == "UNAPPROVED" for item in body["providers"]))
        self.assertTrue(all(item["health"] == "DISABLED" for item in body["providers"]))

    def test_optimize_returns_contract_valid_response_and_caps_deadline(self) -> None:
        recorded = []
        delegate = self.fixture_use_case

        class RecordingUseCase:
            def execute(inner_self, command, context):
                recorded.append(context)
                return delegate.execute(command, context)

        self.app = self._application(RecordingUseCase())
        response = self._post(_request_payload(), deadline_seconds=30)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["contractVersion"], "1.0")
        self.assertEqual(response.json()["status"], "COMPLETE")
        self.assertEqual(
            set(response.json()["recommendations"]),
            {"fastest", "stable", "efficient", "publicTransitOnly"},
        )
        self.assertIsNone(response.json()["routes"][0]["legs"][0]["busIntelligence"])
        self.assertEqual(
            recorded[0].effective_deadline,
            self.clock.now() + timedelta(seconds=6.5),
        )
        self.assertEqual(self.contract.validate_optimize_response(response.json()), ())
        self.assertEqual(response.headers["X-Correlation-Id"], "corr-test-1")

    def test_earlier_client_deadline_disables_optional_enrichment_and_returns_partial(self) -> None:
        recorded = []
        fixture = FixtureOptimizeRouteUseCase(self.clock, optional_complete=False)

        class RecordingUseCase:
            def execute(inner_self, command, context):
                recorded.append(context)
                return fixture.execute(command, context)

        self.app = self._application(RecordingUseCase())
        response = self._post(_request_payload(), deadline_seconds=0.1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "PARTIAL")
        self.assertFalse(recorded[0].optional_enrichment_allowed)
        self.assertIn("PROVIDER_PARTIAL_FAILURE", response.json()["warningCodes"])
        self.assertEqual(self.contract.validate_optimize_response(response.json()), ())

    def test_missing_headers_and_expired_deadline_fail_before_use_case(self) -> None:
        missing = self.client.post(
            "/v1/routes/optimize",
            data=json.dumps(_request_payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {_token(self.clock)}",
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["code"], "CONSTRAINT_OUT_OF_RANGE")

        expired = self._post(_request_payload(), deadline_seconds=-1)
        self.assertEqual(expired.status_code, 504)
        self.assertEqual(expired.json()["code"], "ROUTING_DEADLINE_EXCEEDED")

    def test_contract_rejects_identity_and_unknown_fields(self) -> None:
        payload = _request_payload()
        payload["userId"] = "forbidden"
        response = self._post(payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "CONSTRAINT_OUT_OF_RANGE")
        fields = {item["field"] for item in response.json()["violations"]}
        self.assertIn("$", fields)

    def test_contract_version_must_be_exactly_one_dot_zero(self) -> None:
        payload = _request_payload()
        payload["contractVersion"] = "1.0.0"
        response = self._post(payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "CONSTRAINT_OUT_OF_RANGE")

    def test_non_finite_numbers_and_duplicate_keys_are_not_accepted_as_json(self) -> None:
        headers = self._headers()
        non_finite = self.client.post(
            "/v1/routes/optimize",
            data=b'{"contractVersion":"1.0","origin":{"coordinate":{"lon":NaN}}}',
            content_type="application/json",
            **headers,
        )
        self.assertEqual(non_finite.status_code, 400)

        duplicate = self.client.post(
            "/v1/routes/optimize",
            data=b'{"contractVersion":"1.0","contractVersion":"1.0"}',
            content_type="application/json",
            **headers,
        )
        self.assertEqual(duplicate.status_code, 400)

    def test_invalid_service_token_is_rejected_without_detail_leak(self) -> None:
        headers = self._headers()
        headers["HTTP_AUTHORIZATION"] = f"Bearer {_token(self.clock, secret=b'x' * 40)}"
        response = self.client.post(
            "/v1/routes/optimize",
            data=json.dumps(_request_payload()),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "SERVICE_AUTH_REQUIRED")
        self.assertIsNone(response.json()["detail"])

    def test_service_token_requires_jti(self) -> None:
        header = _segment({"alg": "HS256", "typ": "JWT"})
        payload = _segment(
            {
                "iss": "service-api",
                "aud": "routing-api",
                "exp": int((self.clock.now() + timedelta(minutes=5)).timestamp()),
            }
        )
        signature = hmac.new(
            SECRET, f"{header}.{payload}".encode("ascii"), hashlib.sha256
        ).digest()
        token = f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"
        response = self.client.get(
            "/v1/version", HTTP_AUTHORIZATION=f"Bearer {token}"
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "SERVICE_AUTH_REQUIRED")

    def test_service_token_jti_must_be_a_nonblank_string(self) -> None:
        for invalid_jti in ("", "   ", True, 1, 1.5, {}, []):
            with self.subTest(jti=invalid_jti):
                response = self.client.get(
                    "/v1/version",
                    HTTP_AUTHORIZATION=f"Bearer {_token(self.clock, jti=invalid_jti)}",
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["code"], "SERVICE_AUTH_REQUIRED")

    def test_registered_jwt_claims_reject_malformed_types_and_nonfinite_dates(self) -> None:
        invalid_claims = (
            {"nbf": "future"},
            {"nbf": True},
            {"nbf": float("inf")},
            {"exp": True},
            {"exp": float("nan")},
            {"iat": {}},
            {"aud": ["routing-api", 1]},
            {"aud": []},
            {"aud": ["routing-api", ""]},
        )
        for overrides in invalid_claims:
            with self.subTest(overrides=overrides):
                response = self.client.get(
                    "/v1/version",
                    HTTP_AUTHORIZATION=(
                        f"Bearer {_token(self.clock, claims_overrides=overrides)}"
                    ),
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["code"], "SERVICE_AUTH_REQUIRED")

    def test_idempotency_replays_same_body_and_conflicts_on_different_body(self) -> None:
        calls = []
        delegate = self.fixture_use_case

        class CountingUseCase:
            def execute(inner_self, command, context):
                calls.append(command)
                return delegate.execute(command, context)

        self.app = self._application(CountingUseCase())
        first = self._post(_request_payload())
        second = self._post(_request_payload())
        self.assertEqual(first.json(), second.json())
        self.assertEqual(len(calls), 1)

        changed = _request_payload()
        changed["requestId"] = "01JDIFFERENT"
        conflict = self._post(changed)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "IDEMPOTENCY_CONFLICT")

    def test_required_provider_failure_returns_registered_503_problem(self) -> None:
        self.app = self._application(UnavailableOptimizeRouteUseCase())
        response = self._post(_request_payload())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "TRANSIT_PROVIDER_UNAVAILABLE")
        self.assertTrue(response.json()["retryable"])

    def test_unsupported_region_returns_registered_nonretryable_422(self) -> None:
        class UnsupportedUseCase:
            def execute(inner_self, command, context):
                raise UnsupportedRegionError("outside approved corridor")

        self.app = self._application(UnsupportedUseCase())
        response = self._post(_request_payload())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "UNSUPPORTED_REGION")
        self.assertFalse(response.json()["retryable"])

    def test_optional_incomplete_does_not_overwrite_no_feasible_route(self) -> None:
        fixture = self.fixture_use_case

        class NoFeasibleUseCase:
            def execute(inner_self, command, context):
                base = fixture.execute(command, context)
                response = dict(base.response)
                response["status"] = "NO_FEASIBLE_ROUTE"
                response["recommendations"] = {
                    "fastest": None,
                    "stable": None,
                    "efficient": None,
                    "publicTransitOnly": None,
                }
                response["routes"] = []
                response["paretoRouteIds"] = []
                response["warningCodes"] = []
                return UseCaseResult(
                    response=response,
                    optional_enrichment_complete=False,
                    warning_codes=("BUS_DATA_UNAVAILABLE",),
                )

        self.app = self._application(NoFeasibleUseCase())
        response = self._post(_request_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "NO_FEASIBLE_ROUTE")
        self.assertEqual(response.json()["warningCodes"], [])

    def test_use_case_is_bounded_by_earlier_client_deadline_and_signals_cancellation(self) -> None:
        contexts = []

        class SlowUseCase:
            def execute(inner_self, command, context):
                contexts.append(context)
                context.cancellation.wait(timeout=0.2)
                return self.fixture_use_case.execute(command, context)

        self.app = self._application(SlowUseCase())
        started = time.monotonic()
        response = self._post(_request_payload(), deadline_seconds=0.02)
        elapsed = time.monotonic() - started
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["code"], "ROUTING_DEADLINE_EXCEEDED")
        self.assertLess(elapsed, 0.15)
        self.assertTrue(contexts[0].cancellation.is_set())

    def test_admission_saturation_returns_registered_retryable_429(self) -> None:
        class RejectingRunner:
            def run(inner_self, use_case, command, context, timeout_seconds):
                raise RoutingCapacityExceeded

        self.app = self._application(self.fixture_use_case, runner=RejectingRunner())
        response = self._post(_request_payload())
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "RATE_LIMITED")
        self.assertTrue(response.json()["retryable"])

    def test_bounded_runner_releases_permit_after_success_error_and_timeout(self) -> None:
        runner = BoundedUseCaseRunner(maximum_inflight=1)
        self.addCleanup(runner.shutdown)

        def context() -> RequestContext:
            return RequestContext(
                correlation_id="runner-test",
                idempotency_key="runner-test-key",
                client_deadline=self.clock.now() + timedelta(seconds=1),
                effective_deadline=self.clock.now() + timedelta(seconds=1),
                optional_enrichment_allowed=True,
                cancellation=threading.Event(),
            )

        command = OptimizeCommand(_request_payload())
        runner.run(self.fixture_use_case, command, context(), 1.0)

        with self.assertRaises(RuntimeError):
            runner.run(UnavailableOptimizeRouteUseCase(), command, context(), 1.0)

        class CooperativeSlowUseCase:
            def execute(inner_self, inner_command, inner_context):
                inner_context.cancellation.wait(timeout=0.2)
                return self.fixture_use_case.execute(inner_command, inner_context)

        timeout_context = context()
        with self.assertRaises(RoutingDeadlineExceeded):
            runner.run(CooperativeSlowUseCase(), command, timeout_context, 0.01)
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            try:
                runner.run(self.fixture_use_case, command, context(), 1.0)
                break
            except RoutingCapacityExceeded:
                time.sleep(0.005)
        else:
            self.fail("timeout path leaked its admission permit")

    def test_version_and_ready_expose_no_active_model_claims(self) -> None:
        auth = {"HTTP_AUTHORIZATION": f"Bearer {_token(self.clock)}"}
        version = self.client.get("/v1/version", **auth)
        ready = self.client.get("/v1/health/ready", **auth)
        self.assertEqual(version.status_code, 200)
        self.assertEqual(version.json()["models"], [])
        self.assertEqual(version.json()["contractVersion"], "1.2.0")
        self.assertEqual(version.json()["contractVersion"], self.contract.contract_version)
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "degraded")

    def test_disconnected_route_endpoints_are_rejected_before_cache_or_return(self) -> None:
        fixture = self.fixture_use_case

        class DisconnectedUseCase:
            def execute(inner_self, command, context):
                base = fixture.execute(command, context)
                response = json.loads(json.dumps(base.response))
                response["routes"][0]["legs"][0]["from"]["coordinate"] = {
                    "lon": 126.0,
                    "lat": 36.0,
                }
                return UseCaseResult(
                    response=response,
                    optional_enrichment_complete=True,
                )

        self.app = self._application(DisconnectedUseCase())
        response = self._post(_request_payload())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "TRANSIT_PROVIDER_UNAVAILABLE")
