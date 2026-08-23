"""Real HTTP integration of Service Product and Routing & Intelligence."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SERVICE_ROOT = REPOSITORY_ROOT / "src/services/service-api"
ROUTING_SERVER = Path(__file__).with_name("_loopback_routing_server.py")
PUBLIC_FIXTURE = REPOSITORY_ROOT / "src/contracts/openapi/examples/public-route-search-request.json"
PUBLIC_RESPONSE_FIXTURE = REPOSITORY_ROOT / "src/contracts/openapi/examples/public-route-search-response.json"
PRIVATE_REQUEST_FIXTURE = REPOSITORY_ROOT / "src/contracts/openapi/examples/routing-optimize-request.json"
PRIVATE_RESPONSE_FIXTURE = REPOSITORY_ROOT / "src/contracts/openapi/examples/routing-optimize-response.json"
JWT_SECRET = "iq-130-loopback-service-jwt-secret-9D!v2Q@x7P#s4L"
JWT_ISSUER = "service-api"
JWT_AUDIENCE = "routing-api"


def _b64(value: dict[str, Any] | bytes) -> str:
    raw = (
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if isinstance(value, dict)
        else value
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _token(**claim_overrides: Any) -> str:
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, Any] = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "nbf": now - 1,
        "exp": now + 600,
        "jti": f"iq-130-{uuid.uuid4()}",
    }
    claims.update(claim_overrides)
    header = _b64({"alg": "HS256", "typ": "JWT"})
    payload = _b64(claims)
    signature = _b64(
        hmac.new(
            JWT_SECRET.encode("utf-8"),
            f"{header}.{payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    return f"{header}.{payload}.{signature}"


def _claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"server exited early with {process.returncode}")
        try:
            response = httpx.get(url, timeout=0.5)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.05)
    raise AssertionError(f"server did not become ready: {last_error}")


class RealHttpCrossWorkstreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="82ta-iq130-",
            ignore_cleanup_errors=True,
        )
        temporary = Path(cls.temporary.name)
        cls.record_path = temporary / "routing-requests.jsonl"
        cls.routing_port = _available_port()
        cls.service_port = _available_port()
        cls.routing_url = f"http://127.0.0.1:{cls.routing_port}"
        cls.service_url = f"http://127.0.0.1:{cls.service_port}"
        cls.misconfigured_service_port = _available_port()
        cls.misconfigured_service_url = (
            f"http://127.0.0.1:{cls.misconfigured_service_port}"
        )
        cls.direct_service_token = _token()

        routing_environment = os.environ.copy()
        routing_environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                "ROUTING_RUNTIME_ENVIRONMENT": "TEST",
                "ROUTING_SERVICE_JWT_SECRET": JWT_SECRET,
                "ROUTING_SERVICE_JWT_ISSUER": JWT_ISSUER,
                "ROUTING_SERVICE_JWT_AUDIENCE": JWT_AUDIENCE,
            }
        )
        cls.routing_process = subprocess.Popen(
            [
                sys.executable,
                str(ROUTING_SERVER),
                "--port",
                str(cls.routing_port),
                "--record",
                str(cls.record_path),
            ],
            cwd=REPOSITORY_ROOT,
            env=routing_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for(f"{cls.routing_url}/v1/health/live", cls.routing_process)

        database = (temporary / "service.sqlite3").as_posix()
        cls.service_environment = os.environ.copy()
        cls.service_environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                "SERVICE_ENVIRONMENT": "development",
                "SERVICE_ROUTING_GATEWAY": "http",
                "SERVICE_ROUTING_API_BASE_URL": cls.routing_url,
                # Set both the request-scoped issuer configuration and the legacy
                # static token variable so this integration test stays compatible
                # while IQ-120 lands atomically in the shared worktree.
                "SERVICE_ROUTING_JWT_SECRET": JWT_SECRET,
                "SERVICE_ROUTING_JWT_ISSUER": JWT_ISSUER,
                "SERVICE_ROUTING_JWT_AUDIENCE": JWT_AUDIENCE,
                "SERVICE_ROUTING_JWT_TTL_SECONDS": "60",
                "SERVICE_ROUTING_SERVICE_TOKEN": cls.direct_service_token,
                "SERVICE_ROUTING_VERIFY_SSL": "false",
                "SERVICE_ROUTING_API_ALLOWED_HOSTS": "127.0.0.1",
                "SERVICE_ROUTING_DEADLINE_MILLISECONDS": "6500",
                "DATABASE_URL": f"sqlite:///{database}",
            }
        )
        migration = subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            cwd=SERVICE_ROOT,
            env=cls.service_environment,
            capture_output=True,
            timeout=60,
        )
        if migration.returncode:
            raise AssertionError(migration.stderr.decode("utf-8", errors="replace"))
        cls.service_process = subprocess.Popen(
            [
                sys.executable,
                "manage.py",
                "runserver",
                f"127.0.0.1:{cls.service_port}",
                "--noreload",
            ],
            cwd=SERVICE_ROOT,
            env=cls.service_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for(f"{cls.service_url}/api/v1/health", cls.service_process)

        misconfigured_environment = cls.service_environment.copy()
        misconfigured_environment.update(
            {
                "SERVICE_ROUTING_JWT_SECRET": f"wrong-{JWT_SECRET}",
                "DATABASE_URL": f"sqlite:///{(temporary / 'service-wrong-jwt.sqlite3').as_posix()}",
            }
        )
        migration = subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            cwd=SERVICE_ROOT,
            env=misconfigured_environment,
            capture_output=True,
            timeout=60,
        )
        if migration.returncode:
            raise AssertionError(migration.stderr.decode("utf-8", errors="replace"))
        cls.misconfigured_service_process = subprocess.Popen(
            [
                sys.executable,
                "manage.py",
                "runserver",
                f"127.0.0.1:{cls.misconfigured_service_port}",
                "--noreload",
            ],
            cwd=SERVICE_ROOT,
            env=misconfigured_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for(
            f"{cls.misconfigured_service_url}/api/v1/health",
            cls.misconfigured_service_process,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        for process_name in (
            "service_process",
            "misconfigured_service_process",
            "routing_process",
        ):
            process = getattr(cls, process_name, None)
            if process is None:
                continue
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        # Windows can retain the SQLite file handle for a short interval after
        # runserver exits. TemporaryDirectory retries are not built in, so allow
        # the kernel a bounded grace period before the ignore-errors cleanup.
        time.sleep(0.2)
        cls.temporary.cleanup()

    def setUp(self) -> None:
        self.client = httpx.Client(base_url=self.service_url, timeout=10)
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.csrf_token = self.client.cookies["csrftoken"]

    def tearDown(self) -> None:
        self.client.close()

    @staticmethod
    def _public_payload(selector: float) -> dict[str, Any]:
        payload = json.loads(PUBLIC_FIXTURE.read_text(encoding="utf-8"))
        payload["origin"]["coordinate"]["lon"] = selector
        payload["departure"]["time"] = "2026-08-24T07:40:00+09:00"
        payload["preferences"]["maxWalkSeconds"] = 3600
        payload["saveToHistory"] = False
        return payload

    def _public_post(self, selector: float, key: str) -> httpx.Response:
        return self.client.post(
            "/api/v1/route-searches",
            json=self._public_payload(selector),
            headers={
                "Idempotency-Key": key,
                "X-Correlation-Id": f"public-{key}",
                "X-CSRFToken": self.csrf_token,
            },
        )

    def _canonical_public_post(self) -> httpx.Response:
        payload = json.loads(PUBLIC_FIXTURE.read_text(encoding="utf-8"))
        return self.client.post(
            "/api/v1/route-searches",
            json=payload,
            headers={
                "Idempotency-Key": "canonical-r1-http-public-key",
                "X-Correlation-Id": "canonical-r1-http-public",
                "X-CSRFToken": self.csrf_token,
            },
        )

    @classmethod
    def _records(cls) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in cls.record_path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def test_public_service_to_private_routing_statuses_and_forwarded_context(self) -> None:
        initial_record_count = len(self._records())
        cases = (
            (127.187456, "COMPLETE", 200, "complete-key-0001"),
            (127.187457, "PARTIAL", 200, "partial-key-0001"),
            (127.187458, "NO_FEASIBLE_ROUTE", 200, "no-route-key-0001"),
            (127.187459, "TRANSIT_PROVIDER_UNAVAILABLE", 503, "unavailable-key-0001"),
            (127.187460, "ROUTING_DEADLINE_EXCEEDED", 504, "deadline-key-0001"),
            (127.187461, "UNSUPPORTED_REGION", 422, "unsupported-key-0001"),
        )
        responses: dict[float, httpx.Response] = {}
        for selector, expected, status, key in cases:
            response = self._public_post(selector, key)
            responses[selector] = response
            self.assertEqual(response.status_code, status, response.text)
            body = response.json()
            self.assertEqual(body["status"] if status == 200 else body["code"], expected)
            self.assertEqual(response.headers["X-Correlation-Id"], f"public-{key}")

        for selector in (127.187456, 127.187457, 127.187458):
            serialized = json.dumps(responses[selector].json(), sort_keys=True)
            for forbidden in ("providerStatus", "modelVersions", "computation", "userId", "email"):
                self.assertNotIn(forbidden, serialized)

        records = self._records()[initial_record_count:]
        service_records = [
            item
            for item in records
            if item.get("body", {}).get("origin", {}).get("coordinate", {}).get("lon")
            in {case[0] for case in cases}
        ]
        self.assertEqual(len(service_records), len(cases))
        for record, (_, _, _, public_key) in zip(service_records, cases, strict=True):
            self.assertRegex(record["authorization"], r"^Bearer [^.]+\.[^.]+\.[^.]+$")
            self.assertEqual(record["contentType"], "application/json")
            self.assertEqual(record["correlationId"], f"public-{public_key}")
            self.assertGreaterEqual(len(record["idempotencyKey"]), 8)
            deadline = datetime.fromisoformat(record["deadline"])
            self.assertIsNotNone(deadline.tzinfo)
            self.assertGreater(deadline, datetime.now(UTC) - timedelta(seconds=10))

        for record in service_records:
            token_claims = _claims(record["authorization"].removeprefix("Bearer "))
            self.assertEqual(token_claims["iss"], JWT_ISSUER)
            self.assertEqual(token_claims["aud"], JWT_AUDIENCE)
            self.assertGreater(token_claims["exp"], int(datetime.now(UTC).timestamp()))
            self.assertTrue(token_claims["jti"])

        before = len(self._records())
        first = self._public_post(127.187456, "public-idempotent-0001")
        second = self._public_post(127.187456, "public-idempotent-0001")
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(first.json(), second.json())
        self.assertEqual(len(self._records()) - before, 1)

    def _private_post(
        self,
        *,
        token: str,
        correlation: str,
        deadline: str,
        idempotency: str,
        selector: float = 127.187456,
    ) -> httpx.Response:
        payload = json.loads(PRIVATE_REQUEST_FIXTURE.read_text(encoding="utf-8"))
        payload["requestId"] = f"iq130-{uuid.uuid4()}"
        payload["origin"]["coordinate"]["lon"] = selector
        payload["departureTime"] = "2026-08-24T07:40:00+09:00"
        payload["constraints"]["maxWalkSeconds"] = 3600
        return httpx.post(
            f"{self.routing_url}/v1/routes/optimize",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Correlation-Id": correlation,
                "X-Request-Deadline": deadline,
                "Idempotency-Key": idempotency,
            },
            timeout=10,
        )

    def _canonical_private_post(self) -> httpx.Response:
        payload = json.loads(PRIVATE_REQUEST_FIXTURE.read_text(encoding="utf-8"))
        return httpx.post(
            f"{self.routing_url}/v1/routes/optimize",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.direct_service_token}",
                "X-Correlation-Id": "canonical-r1-http-private",
                "X-Request-Deadline": (
                    datetime.now(UTC) + timedelta(seconds=6)
                ).isoformat(),
                "Idempotency-Key": "canonical-r1-http-private-key",
            },
            timeout=10,
        )

    def test_private_api_rejects_invalid_service_jwt_claims(self) -> None:
        now = int(datetime.now(UTC).timestamp())
        invalid = (
            _token(iss="wrong-service"),
            _token(aud="wrong-routing"),
            _token(exp=now - 1),
            _token(jti=""),
        )
        for index, token in enumerate(invalid):
            response = self._private_post(
                token=token,
                correlation=f"auth-negative-{index}",
                deadline=(datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
                idempotency=f"auth-negative-key-{index}",
            )
            self.assertEqual(response.status_code, 401, response.text)
            self.assertEqual(response.json()["code"], "SERVICE_AUTH_REQUIRED")

    def test_private_api_expired_deadline_is_504_and_echoes_correlation(self) -> None:
        response = self._private_post(
            token=self.direct_service_token,
            correlation="private-expired-deadline",
            deadline=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            idempotency="private-expired-key-0001",
        )
        self.assertEqual(response.status_code, 504, response.text)
        self.assertEqual(response.json()["code"], "ROUTING_DEADLINE_EXCEEDED")
        self.assertEqual(response.headers["X-Correlation-Id"], "private-expired-deadline")

    def test_canonical_replay_and_actual_http_response_have_wire_shape_compatibility(self) -> None:
        response = self._private_post(
            token=self.direct_service_token,
            correlation="private-parity",
            deadline=(datetime.now(UTC) + timedelta(seconds=5)).isoformat(),
            idempotency="private-parity-key-0001",
            selector=127.187457,
        )
        self.assertEqual(response.status_code, 200, response.text)
        actual = response.json()
        canonical = json.loads(PRIVATE_RESPONSE_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(set(actual), set(canonical))
        self.assertEqual(set(actual["recommendations"]), set(canonical["recommendations"]))
        self.assertEqual(set(actual["computation"]), set(canonical["computation"]))
        self.assertEqual(
            set(actual["computation"]["candidateCounts"]),
            set(canonical["computation"]["candidateCounts"]),
        )
        self.assertEqual(
            set(actual["providerStatus"][0]),
            set(canonical["providerStatus"][0]),
        )
        self.assertIsInstance(actual["routes"], list)
        self.assertIsInstance(canonical["routes"], list)

        public_actual = self._public_post(127.187456, "public-parity-key-0001").json()
        public_canonical = json.loads(PUBLIC_RESPONSE_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(set(public_actual), set(public_canonical))
        self.assertEqual(
            set(public_actual["recommendations"]),
            set(public_canonical["recommendations"]),
        )

    def test_canonical_replay_and_actual_http_response_have_semantic_parity(self) -> None:
        response = self._canonical_private_post()
        self.assertEqual(response.status_code, 200, response.text)
        actual = response.json()
        canonical = json.loads(PRIVATE_RESPONSE_FIXTURE.read_text(encoding="utf-8"))
        actual["computation"]["durationMs"] = canonical["computation"]["durationMs"]
        self.assertEqual(actual, canonical)

        public_actual_response = self._canonical_public_post()
        self.assertEqual(public_actual_response.status_code, 200, public_actual_response.text)
        public_actual = public_actual_response.json()
        public_canonical = json.loads(PUBLIC_RESPONSE_FIXTURE.read_text(encoding="utf-8"))
        public_actual["searchId"] = public_canonical["searchId"]
        self.assertEqual(public_actual, public_canonical)
        self.assertEqual(
            public_actual_response.headers["X-Correlation-Id"],
            "canonical-r1-http-public",
        )

        record = next(
            item
            for item in reversed(self._records())
            if item["correlationId"] == "canonical-r1-http-public"
        )
        forwarded = record["body"]
        forwarded["requestId"] = canonical["requestId"]
        canonical_request = json.loads(PRIVATE_REQUEST_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(forwarded, canonical_request)
        routed = record["responseBody"]
        routed["requestId"] = canonical["requestId"]
        routed["computation"]["durationMs"] = canonical["computation"]["durationMs"]
        self.assertEqual(record["responseStatus"], 200)
        self.assertEqual(routed, canonical)

    def test_private_401_is_redacted_by_service_across_real_processes(self) -> None:
        with httpx.Client(base_url=self.misconfigured_service_url, timeout=10) as client:
            health = client.get("/api/v1/health")
            self.assertEqual(health.status_code, 200)
            csrf = client.cookies["csrftoken"]
            payload = json.loads(PUBLIC_FIXTURE.read_text(encoding="utf-8"))
            response = client.post(
                "/api/v1/route-searches",
                json=payload,
                headers={
                    "Idempotency-Key": "wrong-service-jwt-public-key",
                    "X-Correlation-Id": "wrong-service-jwt-public",
                    "X-CSRFToken": csrf,
                },
            )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["code"], "TRANSIT_PROVIDER_UNAVAILABLE")
        serialized = json.dumps(response.json())
        self.assertNotIn("SERVICE_AUTH_REQUIRED", serialized)
        self.assertNotIn(f"wrong-{JWT_SECRET}", serialized)
        self.assertEqual(response.json()["correlationId"], "wrong-service-jwt-public")
        self.assertEqual(
            response.headers["X-Correlation-Id"],
            "wrong-service-jwt-public",
        )
        record = next(
            item
            for item in reversed(self._records())
            if item["correlationId"] == "wrong-service-jwt-public"
        )
        self.assertEqual(record["responseStatus"], 401)
        self.assertEqual(record["responseBody"]["code"], "SERVICE_AUTH_REQUIRED")


if __name__ == "__main__":
    unittest.main()
