"""Local Service gateway -> Routing WSGI HTTP load evidence.

This deliberately uses sanitized fixture work and a loopback process boundary. It
does not claim deployed Public API, Provider, database, model, AWS, or production
capacity evidence.
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
from threading import Barrier, Lock, Thread
from typing import Iterator
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import pytest
from django.core.wsgi import get_wsgi_application
from django.test import override_settings


SRC_ROOT = Path(__file__).resolve().parents[3]
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
from routing_api.application import (  # noqa: E402
    BoundedUseCaseRunner,
    FixtureOptimizeRouteUseCase,
    InMemoryIdempotencyStore,
    RoutingApiApplication,
    SystemClock,
)
from routing_api.auth import Hs256ServiceBearerVerifier  # noqa: E402
from routing_api.contract import CanonicalContractValidator  # noqa: E402


SECRET = "cross-workstream-load-secret-7Vq!4xP@9mK#2sL%6wN&8cR"


class ThreadingWsgiServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


class CountingApplication:
    def __init__(self, delegate: RoutingApiApplication) -> None:
        self.delegate = delegate
        self._lock = Lock()
        self.optimize_calls = 0

    def optimize(self, **kwargs: object):
        with self._lock:
            self.optimize_calls += 1
        return self.delegate.optimize(**kwargs)  # type: ignore[arg-type]

    def authenticate(self, *args: object, **kwargs: object):
        return self.delegate.authenticate(*args, **kwargs)  # type: ignore[arg-type]

    def capabilities(self):
        return self.delegate.capabilities()

    def readiness(self):
        return self.delegate.readiness()

    def version(self):
        return self.delegate.version()


@contextmanager
def _routing_server(application: CountingApplication) -> Iterator[str]:
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
    print("IQ160_METRIC " + json.dumps(values, sort_keys=True))


def _routing_application(runner: BoundedUseCaseRunner) -> CountingApplication:
    clock = SystemClock()
    return CountingApplication(
        RoutingApiApplication(
            verifier=Hs256ServiceBearerVerifier(
                SECRET.encode("utf-8"),
                "service-api",
                "routing-api",
                clock.now,
            ),
            contract=CanonicalContractValidator(),
            use_case=FixtureOptimizeRouteUseCase(clock),
            clock=clock,
            idempotency=InMemoryIdempotencyStore(),
            build_version="cross-workstream-loopback-load",
            runner=runner,
        )
    )


@pytest.mark.parametrize("concurrency", (10, 50, 100))
def test_service_http_gateway_to_private_routing_loopback_is_bounded(
    concurrency: int,
) -> None:
    runner = BoundedUseCaseRunner(maximum_inflight=8)
    application = _routing_application(runner)
    fixtures = LockedFixtures()
    public_request = fixtures.get("public_request")
    start_gate = Barrier(concurrency)

    try:
        with _routing_server(application) as base_url, override_settings(
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

            def invoke(index: int) -> tuple[int, float, dict[str, object] | None]:
                start_gate.wait(timeout=10)
                started = time.perf_counter()
                try:
                    response = gateway.optimize(
                        public_request,
                        RoutingEnvelope(
                            correlation_id=f"iq160-load-{concurrency}-{index}",
                            idempotency_key=f"iq160-load-idempotency-{concurrency}-{index:04d}",
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

    assert len(results) == concurrency
    assert application.optimize_calls == concurrency
    assert set(statuses) <= {200, 429}
    assert successful
    assert all(
        response is not None and response["status"] in {"COMPLETE", "PARTIAL"}
        for _, _, response in successful
    )
    assert all(latency < 7_000 for latency in latencies)
    success_p95_ms = _percentile([latency for _, latency, _ in successful], 0.95)
    assert success_p95_ms < 6_500

    _metric(
        scenario="service_gateway_to_routing_loopback_http",
        concurrency=concurrency,
        offered=concurrency,
        routing_http_calls=application.optimize_calls,
        success_count=len(successful),
        admission_rejected=len(rejected),
        p50_ms=round(_percentile(latencies, 0.50), 4),
        p95_ms=round(_percentile(latencies, 0.95), 4),
        success_p95_ms=round(success_p95_ms, 4),
        max_ms=round(max(latencies), 4),
        external_provider_calls=0,
        evidence_scope=(
            "local_loopback_service_gateway_and_sanitized_fixture;"
            "not_full_public_path_not_deployed_not_production_slo"
        ),
    )
