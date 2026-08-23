"""Production-shaped local load for Provider -> Routing -> Service gateway.

The transport emits sanitized documented vendor response shapes and performs no
external I/O.  Results are source-regression evidence only, never deployed/live
Provider SLO or quota evidence.
"""

from __future__ import annotations

import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from socketserver import ThreadingMixIn
from threading import Barrier, Thread
from typing import Iterator
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import pytest
from django.core.wsgi import get_wsgi_application
from django.test import override_settings

pytest.importorskip("httpx", reason="Service HTTP gateway dependency is not installed")


SRC_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_HELPERS = SRC_ROOT / "tests" / "integration" / "cross-workstream"
for relative in (
    "services/service-api",
    "generated/routing-client-python",
    str(INTEGRATION_HELPERS.relative_to(SRC_ROOT)),
):
    path = str(SRC_ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from _production_dependencies import build_dependencies  # noqa: E402
from journeys.contracts import CanonicalContracts, LockedFixtures  # noqa: E402
from journeys.gateway import HttpRoutingGateway, RoutingEnvelope, RoutingGatewayError  # noqa: E402
from routing_api.application import (  # noqa: E402
    BoundedUseCaseRunner,
    InMemoryIdempotencyStore,
    RoutingApiApplication,
    SystemClock,
)
from routing_api.auth import Hs256ServiceBearerVerifier  # noqa: E402
from routing_api.contract import CanonicalContractValidator  # noqa: E402
from routing_api.production_composition import build_injected_production_use_case  # noqa: E402
from routing_domain import BoundedStrategyGenerator  # noqa: E402


JWT_SECRET = "ri406-production-shaped-load-jwt-7Vq!4xP@9mK#2sL"
PROVIDER_SECRET = "ri406-production-shaped-provider-secret"


class ThreadingWsgiServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return None


@contextmanager
def _routing_server(application: RoutingApiApplication) -> Iterator[str]:
    django_wsgi = get_wsgi_application()
    with patch("routing_api.views.get_application", return_value=application):
        server = make_server(
            "127.0.0.1",
            0,
            django_wsgi,
            server_class=ThreadingWsgiServer,
            handler_class=QuietHandler,
        )
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _metric(**values: object) -> None:
    print("RI406_METRIC " + json.dumps(values, sort_keys=True))


def _application(runner: BoundedUseCaseRunner) -> RoutingApiApplication:
    clock = SystemClock()
    dependencies = build_dependencies()
    use_case = build_injected_production_use_case(clock, dependencies)
    return RoutingApiApplication(
        verifier=Hs256ServiceBearerVerifier(
            JWT_SECRET.encode("utf-8"),
            "service-api",
            "routing-api",
            clock.now,
        ),
        contract=CanonicalContractValidator(),
        use_case=use_case,
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version="ri406-production-shaped-load",
        runner=runner,
    )


@pytest.mark.parametrize("concurrency", (10, 50, 100))
def test_production_shaped_provider_routing_service_gateway_load_is_bounded(
    concurrency: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider_record = tmp_path / f"provider-{concurrency}.jsonl"
    monkeypatch.setenv("RI405_PROVIDER_RECORD_PATH", str(provider_record))
    monkeypatch.setenv("RI405_PROVIDER_SECRET_SENTINEL", PROVIDER_SECRET)
    monkeypatch.setenv("RI405_RAW_SENTINEL", "ri406-raw-sentinel")

    runner = BoundedUseCaseRunner(maximum_inflight=8)
    optimizer_caps = BoundedStrategyGenerator().caps
    application = _application(runner)
    public_request = LockedFixtures().get("public_request")
    public_request["departure"]["time"] = datetime.now().astimezone().replace(
        microsecond=0
    ).isoformat()
    start_gate = Barrier(concurrency)

    try:
        with _routing_server(application) as base_url, override_settings(
            ENVIRONMENT="development",
            ROUTING_API_BASE_URL=base_url,
            ROUTING_API_ALLOWED_HOSTS=("127.0.0.1",),
            ROUTING_SERVICE_JWT_SECRET=JWT_SECRET,
            ROUTING_SERVICE_JWT_ISSUER="service-api",
            ROUTING_SERVICE_JWT_AUDIENCE="routing-api",
            ROUTING_SERVICE_JWT_TTL_SECONDS=60,
            ROUTING_DEADLINE_MILLISECONDS=6_500,
            ROUTING_VERIFY_SSL=False,
            ROUTING_MAX_RESPONSE_BYTES=2 * 1024 * 1024,
            ROUTING_CAPABILITIES_CACHE_TTL_SECONDS=60,
        ):
            gateway = HttpRoutingGateway(CanonicalContracts())

            def invoke(index: int) -> tuple[int, float, dict[str, object] | None]:
                start_gate.wait(timeout=10)
                started = time.perf_counter()
                try:
                    response = gateway.optimize(
                        public_request,
                        RoutingEnvelope(
                            correlation_id=f"ri406-load-{concurrency}-{index}",
                            idempotency_key=(
                                f"ri406-production-load-{concurrency}-{index:04d}"
                            ),
                            request_deadline=(
                                datetime.now(timezone.utc) + timedelta(seconds=6)
                            ).isoformat(),
                        ),
                    )
                    return 200, (time.perf_counter() - started) * 1000, response
                except RoutingGatewayError as exc:
                    return exc.status, (time.perf_counter() - started) * 1000, None

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                results = list(executor.map(invoke, range(concurrency)))
            gateway.client.get_httpx_client().close()
    finally:
        runner.shutdown()

    statuses = [status for status, _, _ in results]
    latencies = [latency for _, latency, _ in results]
    successful = [item for item in results if item[0] == 200]
    rejected = [item for item in results if item[0] == 429]
    timed_out = [item for item in results if item[0] == 504]

    assert len(results) == concurrency
    assert set(statuses) <= {200, 429, 504}
    assert successful
    assert all(latency < 7_000 for latency in latencies)
    success_p95_ms = _percentile([latency for _, latency, _ in successful], 0.95)
    assert success_p95_ms < 6_500

    max_generated = 0
    max_evaluated = 0
    max_routes = 0
    for _, _, response in successful:
        assert response is not None
        assert response["status"] == "PARTIAL"
        counts = response["computation"]["candidateCounts"]
        max_generated = max(max_generated, int(counts["generated"]))
        max_evaluated = max(max_evaluated, int(counts["fullyEvaluated"]))
        max_routes = max(max_routes, len(response["routes"]))
        assert counts["generated"] <= optimizer_caps.coarse_combinations
        assert counts["fullyEvaluated"] <= optimizer_caps.coarse_combinations
        assert len(response["routes"]) <= optimizer_caps.user_results
        budget = public_request["taxiBudget"]["maxAmount"]
        for route in response["routes"]:
            assert route["taxiCost"]["upper"] <= budget
            assert route["totalDuration"]["p90Seconds"] >= route["totalDuration"]["p50Seconds"]

    records = [
        json.loads(line)
        for line in provider_record.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert records
    admitted = len(successful) + len(timed_out)
    assert len(records) <= optimizer_caps.provider_calls * admitted
    assert all(item["credential"] == "***" for item in records)
    assert all(PROVIDER_SECRET not in json.dumps(item, sort_keys=True) for item in records)
    assert all(item["sourceProof"] == "SANITIZED_VENDOR_RAW" for item in records)

    _metric(
        scenario="production_shaped_provider_routing_service_gateway",
        concurrency=concurrency,
        offered=concurrency,
        success_count=len(successful),
        admission_rejected=len(rejected),
        deadline_timeouts=len(timed_out),
        provider_calls=len(records),
        provider_operation_cap_per_admitted_request=optimizer_caps.provider_calls,
        candidate_generated_max=max_generated,
        candidate_fully_evaluated_max=max_evaluated,
        returned_routes_max=max_routes,
        p50_ms=round(_percentile(latencies, 0.50), 4),
        p95_ms=round(_percentile(latencies, 0.95), 4),
        success_p95_ms=round(success_p95_ms, 4),
        max_ms=round(max(latencies), 4),
        external_provider_calls=0,
        evidence_scope=(
            "local_loopback_sanitized_vendor_raw_and_service_gateway;"
            "not_live_provider_not_tls_not_aws_not_deployed_slo"
        ),
    )
