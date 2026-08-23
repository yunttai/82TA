"""Production-shaped Service -> Routing source-path E2E.

This suite proves the deployable composition and vendor-raw normalization path
without claiming live credential, public Internet, TLS, quota, or staging proof.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import httpx


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
TEST_DIRECTORY = Path(__file__).resolve().parent
ROUTING_ROOT = REPOSITORY_ROOT / "src/services/routing-api"
SERVICE_ROOT = REPOSITORY_ROOT / "src/services/service-api"
ROUTING_SERVER = TEST_DIRECTORY / "_production_loopback_server.py"
DEPENDENCY_FACTORY = TEST_DIRECTORY / "_production_dependencies.py"
PUBLIC_REQUEST = (
    REPOSITORY_ROOT
    / "src/contracts/openapi/examples/public-route-search-request.json"
)
JWT_SECRET = "ri405-production-shaped-jwt-secret-9D!v2Q@x7P#s4L"
PROVIDER_SECRET_SENTINEL = "ri405-provider-secret-must-never-cross-boundary"
RAW_SENTINEL = "ri405-sanitized-vendor-raw-must-never-cross-boundary"
KAKAO_OPERATIONS = (
    (
        "KAKAO_PUBLIC_TRANSIT",
        "search_current",
        "kakao.public-transit.rest.v2.2026-08-24",
    ),
    ("KAKAO_WALK", "route", "kakao.walk.rest.v2.2026-08-24"),
    (
        "KAKAO_DIRECTIONS",
        "route_current",
        "kakao-directions.v1.current-route.20260824",
    ),
)


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                "server exited early "
                f"({process.returncode}): "
                f"{stdout.decode(errors='replace')} {stderr.decode(errors='replace')}"
            )
        try:
            if httpx.get(url, timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.05)
    raise AssertionError(f"server did not become ready: {last_error}")


def _json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)


def _provider_values(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "provider" and isinstance(item, str):
                yield item
            yield from _provider_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _provider_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def _public_routes(body: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    routes: dict[str, dict[str, Any]] = {}
    baseline = body.get("baseline")
    if isinstance(baseline, dict):
        routes[baseline["routeId"]] = baseline
    recommendations = body.get("recommendations", {})
    if isinstance(recommendations, dict):
        for route in recommendations.values():
            if isinstance(route, dict):
                routes[route["routeId"]] = route
    return tuple(routes.values())


def _synthetic_provider_evidence() -> str:
    now = datetime.now(timezone.utc)
    capabilities = [
        {
            "provider": provider,
            "operation": operation,
            "documentationState": "DOCUMENTED",
            "keyVerificationState": "KEY_VERIFIED",
            "productionState": "PRODUCTION_APPROVED",
            "fixtureOnly": False,
        }
        for provider, operation, _ in KAKAO_OPERATIONS
    ]
    runtime = []
    for index, (provider, operation, schema_version) in enumerate(KAKAO_OPERATIONS):
        for kind_index, kind in enumerate(
            ("KEY_VERIFICATION", "PRODUCTION_APPROVAL", "RESPONSE_SCHEMA")
        ):
            runtime.append(
                {
                    "provider": provider,
                    "operation": operation,
                    "kind": kind,
                    "evidenceId": f"ri405-{index}-{kind_index}",
                    "artifactSha256": f"{index + kind_index + 1:x}" * 64,
                    "version": schema_version if kind == "RESPONSE_SCHEMA" else "ri405.v1",
                    "issuedAt": (now - timedelta(minutes=5)).isoformat(),
                    "expiresAt": (now + timedelta(hours=1)).isoformat(),
                }
            )
    return json.dumps(
        {
            "version": "1.0",
            "capabilities": capabilities,
            "runtimeEvidence": runtime,
            "egressAttestation": {
                "evidenceId": "ri405-egress",
                "artifactSha256": "e" * 64,
                "version": "ri405.v1",
                "issuedAt": (now - timedelta(minutes=5)).isoformat(),
                "expiresAt": (now + timedelta(hours=1)).isoformat(),
                "enforcement": "EXTERNAL_PROXY_OR_FIREWALL",
            },
        }
    )


class ProductionFactoryAssemblyTests(unittest.TestCase):
    def test_real_deployment_factory_validates_exact_synthetic_evidence_without_io(self) -> None:
        for root in (
            ROUTING_ROOT,
            REPOSITORY_ROOT / "src/packages/provider-core",
            REPOSITORY_ROOT / "src/packages/routing-domain",
            REPOSITORY_ROOT / "src/packages/bus-intelligence-core",
        ):
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
        from routing_deployment.bootstrap import _load_factory

        environment = {
            "KAKAO_REST_API_KEY": "ri405-synthetic-rest-key",
            "ROUTING_PROVIDER_EVIDENCE_JSON": _synthetic_provider_evidence(),
            "ROUTING_PROVIDER_CONFIG_FACTORY": (
                "provider_core.production:build_kakao_baseline_config"
            ),
            "ROUTING_RUNTIME_ENVIRONMENT": "STAGING",
        }
        with patch.dict(os.environ, environment, clear=False):
            factory = _load_factory(
                "routing_deployment.baseline:build_dependencies"
            )
            dependencies = factory()

        self.assertEqual(dependencies.deployment_environment, "staging")
        self.assertEqual(
            set(dependencies.provider_config.binding_map),
            {(provider, operation) for provider, operation, _ in KAKAO_OPERATIONS},
        )
        self.assertEqual(
            len(dependencies.provider_config.runtime_evidence.all()),
            len(KAKAO_OPERATIONS) * 3,
        )


class ProductionProviderHttpE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        for path in (ROUTING_SERVER, DEPENDENCY_FACTORY):
            if not path.exists():
                raise unittest.SkipTest(f"concurrent production seam is not ready: {path}")
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="82ta-ri405-",
            ignore_cleanup_errors=True,
        )
        temporary = Path(cls.temporary.name)
        cls.routing_record = temporary / "routing-wire.jsonl"
        cls.provider_record = temporary / "provider-calls.jsonl"
        cls.routing_port = _available_port()
        cls.service_port = _available_port()
        cls.routing_url = f"http://127.0.0.1:{cls.routing_port}"
        cls.service_url = f"http://127.0.0.1:{cls.service_port}"

        python_paths = (
            TEST_DIRECTORY,
            ROUTING_ROOT,
            REPOSITORY_ROOT / "src/packages/routing-domain",
            REPOSITORY_ROOT / "src/packages/provider-core",
            REPOSITORY_ROOT / "src/packages/bus-intelligence-core",
            REPOSITORY_ROOT / "src/generated/routing-client-python",
        )
        routing_environment = os.environ.copy()
        routing_environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": os.pathsep.join(map(str, python_paths)),
                "DJANGO_SETTINGS_MODULE": "routing_api.settings",
                "ROUTING_RUNTIME_ENVIRONMENT": "TEST",
                "ROUTING_SERVICE_JWT_SECRET": JWT_SECRET,
                "ROUTING_SERVICE_JWT_ISSUER": "service-api",
                "ROUTING_SERVICE_JWT_AUDIENCE": "routing-api",
                "ROUTING_PRODUCTION_DEPENDENCIES_FACTORY": (
                    "_production_dependencies:build_dependencies"
                ),
                "RI405_PROVIDER_RECORD_PATH": str(cls.provider_record),
                "RI405_PROVIDER_SECRET_SENTINEL": PROVIDER_SECRET_SENTINEL,
                "RI405_RAW_SENTINEL": RAW_SENTINEL,
            }
        )
        cls.routing_process = subprocess.Popen(
            [
                sys.executable,
                str(ROUTING_SERVER),
                "--port",
                str(cls.routing_port),
                "--record",
                str(cls.routing_record),
            ],
            cwd=REPOSITORY_ROOT,
            env=routing_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _wait_for(f"{cls.routing_url}/v1/health/live", cls.routing_process)

        database = (temporary / "service.sqlite3").as_posix()
        cls.service_environment = os.environ.copy()
        cls.service_environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": os.pathsep.join(
                    (
                        str(SERVICE_ROOT),
                        str(REPOSITORY_ROOT / "src/generated/routing-client-python"),
                    )
                ),
                "SERVICE_ENVIRONMENT": "development",
                "SERVICE_ROUTING_GATEWAY": "http",
                "SERVICE_ROUTING_API_BASE_URL": cls.routing_url,
                "SERVICE_ROUTING_JWT_SECRET": JWT_SECRET,
                "SERVICE_ROUTING_JWT_ISSUER": "service-api",
                "SERVICE_ROUTING_JWT_AUDIENCE": "routing-api",
                "SERVICE_ROUTING_JWT_TTL_SECONDS": "60",
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
            raise AssertionError(migration.stderr.decode(errors="replace"))
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _wait_for(f"{cls.service_url}/api/v1/health", cls.service_process)

    @classmethod
    def tearDownClass(cls) -> None:
        for name in ("service_process", "routing_process"):
            process = getattr(cls, name, None)
            if process is None:
                continue
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        time.sleep(0.2)
        cls.temporary.cleanup()

    def setUp(self) -> None:
        self.client = httpx.Client(base_url=self.service_url, timeout=12)
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.csrf = self.client.cookies["csrftoken"]

    def tearDown(self) -> None:
        self.client.close()

    @staticmethod
    def _payload(*, fault: bool = False) -> dict[str, Any]:
        payload = json.loads(PUBLIC_REQUEST.read_text(encoding="utf-8"))
        payload["departure"]["time"] = datetime.now().astimezone().replace(
            microsecond=0
        ).isoformat()
        payload["preferences"]["maxWalkSeconds"] = 3600
        payload["saveToHistory"] = False
        if fault:
            payload["origin"]["coordinate"]["lon"] = 127.187459
        return payload

    def _post(self, *, fault: bool = False) -> httpx.Response:
        suffix = "fault" if fault else "success"
        return self.client.post(
            "/api/v1/route-searches",
            json=self._payload(fault=fault),
            headers={
                "Idempotency-Key": f"ri405-{suffix}-key-0001",
                "X-Correlation-Id": f"ri405-{suffix}",
                "X-CSRFToken": self.csrf,
            },
        )

    def test_01_vendor_raw_production_composition_reaches_graph_and_public_projection(self) -> None:
        response = self._post()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "COMPLETE")
        self.assertEqual(body["warnings"], [])

        routes = _public_routes(body)
        self.assertTrue(routes)
        self.assertTrue(any(route["taxiCost"]["upper"] > 0 for route in routes))
        self.assertIsNotNone(body["recommendations"]["publicTransitOnly"])
        budget = self._payload()["taxiBudget"]["maxAmount"]
        for route in routes:
            self.assertGreaterEqual(
                route["totalDuration"]["p90Seconds"],
                route["totalDuration"]["p50Seconds"],
            )
            taxi_upper = sum(
                leg["fare"]["upper"]
                for leg in route["legs"]
                if leg["mode"] == "TAXI"
            )
            self.assertEqual(route["taxiCost"]["upper"], taxi_upper)
            self.assertLessEqual(taxi_upper, budget)
            for leg in route["legs"]:
                self.assertGreaterEqual(
                    leg["waitDuration"]["p90Seconds"],
                    leg["waitDuration"]["p50Seconds"],
                )
                self.assertGreaterEqual(
                    leg["travelDuration"]["p90Seconds"],
                    leg["travelDuration"]["p50Seconds"],
                )
                if leg["mode"] == "TAXI":
                    self.assertGreater(leg["waitDuration"]["p50Seconds"], 0)
                    self.assertGreater(leg["travelDuration"]["p50Seconds"], 0)

        provider_records = _json_lines(self.provider_record)
        self.assertTrue(provider_records)
        operations = {
            (item["provider"], item["operation"]) for item in provider_records
        }
        self.assertTrue(
            {
                ("KAKAO_PUBLIC_TRANSIT", "search_current"),
                ("KAKAO_DIRECTIONS", "route_current"),
            }
            <= operations,
            operations,
        )
        self.assertTrue(
            all(
                item["sourceProof"] == "SANITIZED_VENDOR_RAW"
                for item in provider_records
            )
        )
        self.assertTrue(all(item["credential"] == "***" for item in provider_records))
        serialized_provider_records = json.dumps(provider_records, sort_keys=True)
        self.assertNotIn(PROVIDER_SECRET_SENTINEL, serialized_provider_records)
        self.assertNotIn(RAW_SENTINEL, serialized_provider_records)

        record = next(
            item
            for item in reversed(_json_lines(self.routing_record))
            if item["correlationId"] == "ri405-success"
        )
        self.assertEqual(record["responseStatus"], 200)
        private = record["response"]
        self.assertGreater(private["computation"]["candidateCounts"]["fullyEvaluated"], 0)
        self.assertTrue(private["routes"])
        self.assertIsNone(private["computation"]["mappingVersion"])
        self.assertEqual(private["modelVersions"], [])
        transit_legs = [
            leg
            for route in private["routes"]
            for leg in route["legs"]
            if leg["mode"] == "SUBWAY"
        ]
        self.assertTrue(transit_legs)
        for leg in transit_legs:
            self.assertIsNone(leg["transit"]["externalRouteId"])
            self.assertIsNone(leg["busIntelligence"])
        self.assertTrue(
            any(
                status["provider"] == "KAKAO_PUBLIC_TRANSIT"
                and status["status"] == "OK"
                for status in private["providerStatus"]
            )
        )
        self.assertTrue(
            any(
                status["provider"] == "KAKAO_DIRECTIONS"
                and status["status"] == "OK"
                for status in private["providerStatus"]
            )
        )
        serialized_private = json.dumps(private, sort_keys=True)
        self.assertIs(private["computation"]["cache"]["fixture"], False)
        self.assertTrue(
            all("fixture" not in value.lower() for value in _provider_values(private))
        )
        self.assertNotIn(PROVIDER_SECRET_SENTINEL, serialized_private)
        self.assertNotIn(RAW_SENTINEL, serialized_private)

        private_request_keys = set(_keys(record["request"]))
        self.assertTrue(
            {
                "userId",
                "email",
                "guestToken",
                "providerPlaceId",
                "displayName",
                "savedPlaceLabel",
            }.isdisjoint(private_request_keys)
        )
        public_keys = set(_keys(body))
        self.assertTrue(
            {
                "providerStatus",
                "modelVersions",
                "computation",
                "messageCode",
                "fingerprint",
                "schemaVersion",
                "rawResponse",
                "userId",
                "email",
                "guestToken",
                "providerPlaceId",
            }.isdisjoint(public_keys)
        )
        serialized_public = json.dumps(body, sort_keys=True)
        self.assertNotIn(PROVIDER_SECRET_SENTINEL, serialized_public)
        self.assertNotIn(RAW_SENTINEL, serialized_public)

    def test_02_required_provider_fault_is_public_safe(self) -> None:
        response = self._post(fault=True)
        self.assertEqual(response.status_code, 503, response.text)
        body = response.json()
        self.assertEqual(body["code"], "TRANSIT_PROVIDER_UNAVAILABLE")
        self.assertEqual(body["correlationId"], "ri405-fault")
        serialized = json.dumps(body, sort_keys=True)
        self.assertNotIn(PROVIDER_SECRET_SENTINEL, serialized)
        self.assertNotIn(RAW_SENTINEL, serialized)
        self.assertNotIn("providerStatus", serialized)

    def test_03_harness_cannot_regress_to_fixture_or_scenario_use_cases(self) -> None:
        source = ROUTING_SERVER.read_text(encoding="utf-8") + DEPENDENCY_FACTORY.read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "IntegratedFixtureOptimizeRouteUseCase",
            "FixtureOptimizeRouteUseCase",
            "ScenarioUseCase",
            "fixture_scenario",
            "fixture_fan_in_dependencies",
        ):
            self.assertNotIn(forbidden, source)

if __name__ == "__main__":
    unittest.main()
