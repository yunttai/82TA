"""Reproducible canonical Service -> Routing -> Service R1 example chain."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
for import_root in reversed(
    (
        REPOSITORY_ROOT / "src/services/service-api",
        REPOSITORY_ROOT / "src/services/routing-api",
        REPOSITORY_ROOT / "src/packages/routing-domain",
        REPOSITORY_ROOT / "src/packages/provider-core",
        REPOSITORY_ROOT / "src/packages/bus-intelligence-core",
        REPOSITORY_ROOT / "src/generated/routing-client-python",
    )
):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)

from journeys.contracts import CanonicalContracts  # noqa: E402
from journeys.gateway import (  # noqa: E402
    RoutingEnvelope,
    project_capabilities,
    public_to_private,
)
from journeys.projection import project_public_response  # noqa: E402
from routing_api.application import (  # noqa: E402
    InMemoryIdempotencyStore,
    RoutingApiApplication,
)
from routing_api.auth import Hs256ServiceBearerVerifier  # noqa: E402
from routing_api.capabilities import foundation_capability_projection  # noqa: E402
from routing_api.contract import CanonicalContractValidator  # noqa: E402
from routing_api.fixture_integration import IntegratedFixtureOptimizeRouteUseCase  # noqa: E402
from routing_api.fixture_scenarios import fixture_scenario  # noqa: E402
from routing_domain import RankingPolicy  # noqa: E402


EXAMPLES = REPOSITORY_ROOT / "src/contracts/openapi/examples"
PUBLIC_REQUEST_PATH = EXAMPLES / "public-route-search-request.json"
PRIVATE_REQUEST_PATH = EXAMPLES / "routing-optimize-request.json"
PRIVATE_RESPONSE_PATH = EXAMPLES / "routing-optimize-response.json"
PUBLIC_RESPONSE_PATH = EXAMPLES / "public-route-search-response.json"
CANONICAL_IDEMPOTENCY_KEY = "canonical-r1-replay-0001"
CANONICAL_CORRELATION_ID = "canonical-r1"
CANONICAL_SEARCH_ID = "00000000-0000-4000-8000-000000000006"
CANONICAL_NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
JWT_SECRET = b"canonical-route-chain-service-jwt-secret-v1"


@dataclass(frozen=True)
class FixedClock:
    instant: datetime = CANONICAL_NOW
    tick: float = 100.0

    def now(self) -> datetime:
        return self.instant

    def monotonic(self) -> float:
        return self.tick


def _segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _service_token(clock: FixedClock) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload = _segment(
        {
            "iss": "service-api",
            "aud": "routing-api",
            "iat": int(clock.now().timestamp()),
            "nbf": int(clock.now().timestamp()) - 1,
            "exp": int((clock.now() + timedelta(minutes=5)).timestamp()),
            "jti": "canonical-route-chain-r1",
        }
    )
    signature = hmac.new(
        JWT_SECRET,
        f"{header}.{payload}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def canonical_public_request() -> dict[str, Any]:
    return json.loads(PUBLIC_REQUEST_PATH.read_text(encoding="utf-8"))


def canonical_private_request() -> dict[str, Any]:
    return public_to_private(
        canonical_public_request(),
        RoutingEnvelope(
            correlation_id=CANONICAL_CORRELATION_ID,
            idempotency_key=CANONICAL_IDEMPOTENCY_KEY,
            request_deadline=(CANONICAL_NOW + timedelta(seconds=6)).isoformat(),
        ),
    )


def canonical_application(clock: FixedClock | None = None) -> RoutingApiApplication:
    clock = clock or FixedClock()
    policy_version = RankingPolicy().version
    return RoutingApiApplication(
        verifier=Hs256ServiceBearerVerifier(
            JWT_SECRET,
            "service-api",
            "routing-api",
            now=clock.now,
        ),
        contract=CanonicalContractValidator(),
        use_case=IntegratedFixtureOptimizeRouteUseCase(fixture_scenario("R1"), clock),
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version="canonical-r1-sanitized",
        capability_projection=foundation_capability_projection(),
        backend_state="fixture-only:R1",
        ranking_policy_version=policy_version,
    )


def canonical_private_response(
    private_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clock = FixedClock()
    application = canonical_application(clock)
    request = private_request or canonical_private_request()
    result = application.optimize(
        authorization=f"Bearer {_service_token(clock)}",
        correlation_id=CANONICAL_CORRELATION_ID,
        deadline_header=(clock.now() + timedelta(seconds=6)).isoformat(),
        idempotency_key=CANONICAL_IDEMPOTENCY_KEY,
        content_type="application/json",
        raw_body=json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        ),
    )
    if result.status_code != 200:
        raise RuntimeError(f"canonical Routing producer returned {result.status_code}: {result.body}")
    return json.loads(json.dumps(result.body, ensure_ascii=False))


def canonical_public_response(
    private_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    routing_response = private_response or canonical_private_response()
    contracts = CanonicalContracts()
    response = project_public_response(
        routing_response,
        contracts,
        None,  # type: ignore[arg-type] -- support is explicit, so fixtures are unused.
        support=project_capabilities(None),
        public_request=canonical_public_request(),
    )
    response["searchId"] = CANONICAL_SEARCH_ID
    response["history"] = {
        "saved": False,
        "ownerKind": "GUEST",
        "retainedUntil": response["expiresAt"],
    }
    errors = contracts.validate("public", "PublicRouteSearchResponse", response)
    if errors:
        raise RuntimeError(f"canonical Service projection is invalid: {errors}")
    return response


def public_projection_for_fixture_comparison(
    response: dict[str, Any],
) -> dict[str, Any]:
    """Remove request-derived presentation fields from a Public fixture comparison.

    The canonical response example deliberately uses sanitized placeholder labels,
    while the live Service projection replaces those placeholders with the user's
    Public request labels and removes internal-looking transit directions. Public
    1.5 also adds a persisted, privacy-safe request summary. Those additive or
    request-derived fields are asserted separately by the integration tests; the
    remaining response must retain exact semantic parity with the canonical fixture.
    """

    comparable = copy.deepcopy(response)
    comparable.pop("requestSummary", None)
    routes = [comparable.get("baseline")]
    recommendations = comparable.get("recommendations")
    if isinstance(recommendations, dict):
        routes.extend(recommendations.values())
    for route in routes:
        if not isinstance(route, dict):
            continue
        for leg in route.get("legs", []):
            if not isinstance(leg, dict):
                continue
            for endpoint in ("from", "to"):
                stop = leg.get(endpoint)
                if isinstance(stop, dict):
                    stop.pop("name", None)
            transit = leg.get("transit")
            if isinstance(transit, dict):
                transit.pop("direction", None)
    return comparable


def build_chain() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    public_request = canonical_public_request()
    private_request = canonical_private_request()
    private_response = canonical_private_response(private_request)
    public_response = canonical_public_response(private_response)
    return public_request, private_request, private_response, public_response


def _write_json(path: Path, value: object) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(encoded)


def write_derived_examples() -> None:
    _, private_request, private_response, public_response = build_chain()
    _write_json(PRIVATE_REQUEST_PATH, private_request)
    _write_json(PRIVATE_RESPONSE_PATH, private_response)
    _write_json(PUBLIC_RESPONSE_PATH, public_response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-derived",
        action="store_true",
        help="Regenerate the three derived canonical examples from the Public request.",
    )
    arguments = parser.parse_args()
    if not arguments.write_derived:
        parser.error("--write-derived is required")
    write_derived_examples()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
