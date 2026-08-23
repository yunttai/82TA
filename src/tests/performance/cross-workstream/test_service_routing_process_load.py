"""Separate-process HTTP load evidence for Service's real generated gateway."""

from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from typing import Iterator

import httpx
import pytest
from django.test import override_settings


SRC_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = SRC_ROOT.parent
for relative in ("services/service-api", "generated/routing-client-python"):
    path = str(SRC_ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from journeys.contracts import CanonicalContracts, LockedFixtures  # noqa: E402
from journeys.gateway import (  # noqa: E402
    HttpRoutingGateway,
    RoutingEnvelope,
    RoutingGatewayError,
)


SECRET = "cross-workstream-process-secret-7Vq!4xP@9mK#2sL%6wN"
SERVER_SCRIPT = (
    SRC_ROOT
    / "tests"
    / "integration"
    / "cross-workstream"
    / "_loopback_routing_server.py"
)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _routing_process(record_path: Path) -> Iterator[str]:
    port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update(
        {
            "ROUTING_RUNTIME_ENVIRONMENT": "TEST",
            "ROUTING_SERVICE_JWT_SECRET": SECRET,
            "ROUTING_SERVICE_JWT_ISSUER": "service-api",
            "ROUTING_SERVICE_JWT_AUDIENCE": "routing-api",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(SERVER_SCRIPT),
            "--port",
            str(port),
            "--record",
            str(record_path),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("loopback Routing process exited during startup")
            try:
                response = httpx.get(f"{base_url}/v1/health/live", timeout=0.25)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise RuntimeError("loopback Routing process did not become ready")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _metric(**values: object) -> None:
    print("IQ160_METRIC " + json.dumps(values, sort_keys=True))


@pytest.mark.parametrize("concurrency", (10, 50, 100))
def test_separate_process_gateway_load_and_wire_headers(
    concurrency: int,
    tmp_path: Path,
) -> None:
    record_path = tmp_path / f"routing-{concurrency}.jsonl"
    fixtures = LockedFixtures()
    public_request = fixtures.get("public_request")
    start_gate = Barrier(concurrency)

    with _routing_process(record_path) as base_url, override_settings(
        ENVIRONMENT="development",
        ROUTING_API_BASE_URL=base_url,
        ROUTING_API_ALLOWED_HOSTS=("127.0.0.1",),
        ROUTING_SERVICE_JWT_SECRET=SECRET,
        ROUTING_SERVICE_JWT_ISSUER="service-api",
        ROUTING_SERVICE_JWT_AUDIENCE="routing-api",
        ROUTING_SERVICE_JWT_TTL_SECONDS=60,
        ROUTING_DEADLINE_MILLISECONDS=6500,
        ROUTING_VERIFY_SSL=False,
        ROUTING_MAX_RESPONSE_BYTES=2 * 1024 * 1024,
        ROUTING_CAPABILITIES_CACHE_TTL_SECONDS=60,
    ):
        gateway = HttpRoutingGateway(CanonicalContracts())

        def invoke(index: int) -> tuple[int, float]:
            start_gate.wait(timeout=10)
            started = time.perf_counter()
            try:
                response = gateway.optimize(
                    public_request,
                    RoutingEnvelope(
                        correlation_id=f"iq160-process-{concurrency}-{index}",
                        idempotency_key=(
                            f"iq160-process-idempotency-{concurrency}-{index:04d}"
                        ),
                        request_deadline=(
                            datetime.now(timezone.utc) + timedelta(seconds=6)
                        ).isoformat(),
                    ),
                )
                assert response["status"] == "COMPLETE"
                return 200, (time.perf_counter() - started) * 1000
            except RoutingGatewayError as exc:
                return exc.status, (time.perf_counter() - started) * 1000

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(executor.map(invoke, range(concurrency)))
        gateway.client.get_httpx_client().close()

    records = [
        json.loads(line)
        for line in record_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    statuses = [status for status, _ in results]
    latencies = [latency for _, latency in results]
    successful_latencies = [latency for status, latency in results if status == 200]

    assert len(records) == concurrency
    assert set(statuses) <= {200, 504}
    assert successful_latencies
    assert all(latency < 7_000 for latency in latencies)
    success_p95_ms = _percentile(successful_latencies, 0.95)
    assert success_p95_ms < 6_500
    assert all(record["authorization"].startswith("Bearer ") for record in records)
    assert all(record["correlationId"] for record in records)
    assert all(record["deadline"] for record in records)
    assert all(record["idempotencyKey"] for record in records)
    serialized_bodies = json.dumps([record["body"] for record in records])
    for forbidden in ("userId", "email", "savedPlaceLabel", "saveToHistory"):
        assert forbidden not in serialized_bodies

    _metric(
        scenario="service_gateway_to_routing_separate_process_http",
        concurrency=concurrency,
        offered=concurrency,
        recorded_http_calls=len(records),
        success_count=len(successful_latencies),
        deadline_504=statuses.count(504),
        p50_ms=round(_percentile(latencies, 0.50), 4),
        p95_ms=round(_percentile(latencies, 0.95), 4),
        success_p95_ms=round(success_p95_ms, 4),
        max_ms=round(max(latencies), 4),
        external_provider_calls=0,
        evidence_scope=(
            "local_separate_process_service_gateway_to_routing_fixture;"
            "not_full_public_path_not_deployed_not_production_slo"
        ),
    )
