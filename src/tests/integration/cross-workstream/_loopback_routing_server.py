"""Test-only loopback host for the real Routing Django HTTP boundary.

The server keeps Django views, authentication, contract validation, idempotency,
deadline handling, and response serialization real.  Only the use case behind the
application is deterministic so cross-workstream tests can exercise every public
terminal state without live Provider credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, make_server


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ROUTING_ROOT = REPOSITORY_ROOT / "src/services/routing-api"
sys.path.insert(0, str(ROUTING_ROOT))
os.environ.setdefault("ROUTING_RUNTIME_ENVIRONMENT", "TEST")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "routing_api.settings")

import django  # noqa: E402

from routing_api.workspace_packages import activate_workspace_packages  # noqa: E402


activate_workspace_packages()
django.setup()

from django.core.wsgi import get_wsgi_application  # noqa: E402
from routing_api import views  # noqa: E402
from routing_api.application import (  # noqa: E402
    FixtureOptimizeRouteUseCase,
    InMemoryIdempotencyStore,
    OptimizeCommand,
    RequestContext,
    RoutingApiApplication,
    RoutingDeadlineExceeded,
    RoutingUnavailableError,
    UnsupportedRegionError,
    SystemClock,
    UseCaseResult,
)
from routing_api.auth import Hs256ServiceBearerVerifier  # noqa: E402
from routing_api.capabilities import foundation_capability_projection  # noqa: E402
from routing_api.contract import CanonicalContractValidator  # noqa: E402
from routing_api.fixture_integration import IntegratedFixtureOptimizeRouteUseCase  # noqa: E402
from routing_api.fixture_scenarios import fixture_scenario  # noqa: E402
from routing_api import settings  # noqa: E402


@dataclass(frozen=True)
class CanonicalClock:
    instant: datetime = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
    tick: float = 100.0

    def now(self) -> datetime:
        return self.instant

    def monotonic(self) -> float:
        return self.tick


@dataclass(frozen=True)
class ScenarioUseCase:
    clock: SystemClock

    def execute(self, command: OptimizeCommand, context: RequestContext) -> UseCaseResult:
        if context.correlation_id.startswith("canonical-r1-http"):
            fixed_clock = CanonicalClock()
            return IntegratedFixtureOptimizeRouteUseCase(
                fixture_scenario("R1"),
                fixed_clock,
            ).execute(command, context)
        coordinate = command.payload["origin"]["coordinate"]  # type: ignore[index]
        selector = round(float(coordinate["lon"]), 6)  # type: ignore[index]
        if selector == 127.187459:
            raise RoutingUnavailableError("deterministic required-provider outage")
        if selector == 127.187460:
            raise RoutingDeadlineExceeded("deterministic internal deadline")
        if selector == 127.187461:
            raise UnsupportedRegionError("deterministic unsupported corridor")

        complete = selector == 127.187456
        outcome = FixtureOptimizeRouteUseCase(
            self.clock,
            optional_complete=complete,
        ).execute(command, context)
        if selector != 127.187458:
            return outcome

        response = dict(outcome.response)
        response.update(
            {
                "status": "NO_FEASIBLE_ROUTE",
                "recommendations": {
                    "fastest": None,
                    "stable": None,
                    "efficient": None,
                    "publicTransitOnly": None,
                },
                "routes": [],
                "paretoRouteIds": [],
                "warningCodes": [],
            }
        )
        computation = dict(response["computation"])  # type: ignore[arg-type]
        counts = dict(computation["candidateCounts"])  # type: ignore[arg-type]
        counts.update({"fullyEvaluated": 0, "pareto": 0})
        computation["candidateCounts"] = counts
        response["computation"] = computation
        return UseCaseResult(response=response, optional_enrichment_complete=True)


class RecordingApplication:
    def __init__(self, application: RoutingApiApplication, record_path: Path) -> None:
        self._application = application
        self._record_path = record_path
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._application, name)

    def optimize(self, **kwargs: Any):
        try:
            body = json.loads(kwargs["raw_body"])
        except (KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
            body = None
        result = self._application.optimize(**kwargs)
        record = {
            "authorization": kwargs.get("authorization"),
            "correlationId": kwargs.get("correlation_id"),
            "deadline": kwargs.get("deadline_header"),
            "idempotencyKey": kwargs.get("idempotency_key"),
            "contentType": kwargs.get("content_type"),
            "body": body,
            "responseStatus": result.status_code,
            "responseBody": result.body,
        }
        with self._lock:
            with self._record_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
        return result


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--record", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.record.parent.mkdir(parents=True, exist_ok=True)
    arguments.record.write_text("", encoding="utf-8")

    clock = SystemClock()
    application = RoutingApiApplication(
        verifier=Hs256ServiceBearerVerifier(
            secret=settings.ROUTING_SERVICE_JWT_SECRET.encode("utf-8"),
            issuer=settings.ROUTING_SERVICE_JWT_ISSUER,
            audience=settings.ROUTING_SERVICE_JWT_AUDIENCE,
        ),
        contract=CanonicalContractValidator(),
        use_case=ScenarioUseCase(clock),
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version="iq-130-loopback",
        capability_projection=foundation_capability_projection(),
        backend_state="test-only:iq-130",
    )
    views.get_application = lambda: RecordingApplication(application, arguments.record)
    wsgi_application = get_wsgi_application()
    with make_server(
        "127.0.0.1",
        arguments.port,
        wsgi_application,
        handler_class=QuietHandler,
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
