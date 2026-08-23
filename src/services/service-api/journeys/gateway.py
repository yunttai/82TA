from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from routing_client.api.default import get_routing_capabilities, optimize_routes
from routing_client.client import AuthenticatedClient
from routing_client.errors import UnexpectedStatus
from routing_client.models.optimize_route_request import OptimizeRouteRequest
from routing_client.models.optimize_route_response import OptimizeRouteResponse
from routing_client.models.problem_details import ProblemDetails

from .contracts import CanonicalContracts, ContractError, LockedFixtures
from .http_safety import buffer_bounded_response


class ReplayMiss(Exception):
    pass


@dataclass(frozen=True)
class RoutingGatewayError(Exception):
    status: int
    code: str
    retryable: bool = False


@dataclass(frozen=True)
class RoutingEnvelope:
    correlation_id: str
    idempotency_key: str
    request_deadline: str


class RoutingGateway(Protocol):
    def optimize(self, public_request: dict[str, Any], envelope: RoutingEnvelope) -> dict[str, Any]: ...

    def capabilities(self, *, allow_network: bool = True) -> dict[str, Any]: ...


ALL_MODES = ["WALK", "WAIT", "TRANSFER", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"]
SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")


def _bounded_generated_call(
    operation: Any,
    *,
    client: AuthenticatedClient,
    max_bytes: int,
    **operation_kwargs: Any,
) -> Any:
    request_kwargs = operation._get_kwargs(**operation_kwargs)
    request_kwargs.setdefault("headers", {})["Accept-Encoding"] = "identity"
    with client.get_httpx_client().stream(**request_kwargs) as streamed:
        response = buffer_bounded_response(streamed, max_bytes=max_bytes)
    return operation._build_response(client=client, response=response)


def public_to_private(public_request: dict[str, Any], envelope: RoutingEnvelope) -> dict[str, Any]:
    """Apply only the canonical 1.1 Public-to-Private pass-through policy."""

    preference = public_request["preferences"]
    value: dict[str, Any] = {
        "contractVersion": "1.0",
        "requestId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"82ta:{envelope.idempotency_key}")),
        "origin": {
            "coordinate": public_request["origin"]["coordinate"],
            "regionHint": public_request["origin"].get("regionCode"),
        },
        "destination": {
            "coordinate": public_request["destination"]["coordinate"],
            "regionHint": public_request["destination"].get("regionCode"),
        },
        "departureTime": public_request["departure"]["time"],
        "constraints": {
            "taxiBudget": public_request["taxiBudget"],
            "maxWalkSeconds": preference["maxWalkSeconds"],
            "maxTransfers": preference["maxTransfers"],
            "maxTaxiLegs": preference["maxTaxiLegs"],
            "allowTaxiBridge": preference.get("allowTaxiBridge", False),
            "allowedModes": preference.get("allowedModes", ALL_MODES),
            "accessibility": preference.get("accessibility", {}),
        },
        "preference": {
            "profile": preference["optimization"],
            "avoidHighBusSeatRisk": preference.get("avoidHighBusSeatRisk", False),
            "accessibility": preference.get("accessibility", {}),
        },
        "requestedRecommendations": public_request["requestedRecommendations"],
        "clientContext": {"locale": "ko-KR", "timezone": "Asia/Seoul"},
    }
    if "arrivalDeadline" in public_request:
        value["arrivalDeadline"] = public_request["arrivalDeadline"]
    return value


def project_capabilities(private: dict[str, Any] | None) -> dict[str, Any]:
    if not private:
        return {
            "features": {},
            "busIntelligenceCoverage": "UNKNOWN",
            "degraded": ["ROUTING_CAPABILITIES_UNAVAILABLE"],
        }
    return {
        "region": {
            "originSupported": bool(private.get("region", {}).get("originSupported", False)),
            "destinationSupported": bool(private.get("region", {}).get("destinationSupported", False)),
        },
        "features": {
            key: bool(value)
            for key, value in private.get("features", {}).items()
            if key
            in {
                "currentTransit",
                "futureTransit",
                "currentTaxi",
                "futureTaxi",
                "multiDestinationTaxi",
                "busSeatRisk",
                "busEtaModel",
                "taxiBridge",
                "realtimeRerouting",
            }
        },
        "busIntelligenceCoverage": private.get("busIntelligenceCoverage", "UNKNOWN"),
        "degraded": [str(code) for code in private.get("degraded", [])],
    }


class ReplayRoutingGateway:
    """Exact deterministic replay of the contract-locked Foundation fixture."""

    def __init__(self, fixtures: LockedFixtures | None = None) -> None:
        self.fixtures = fixtures or LockedFixtures()
        self.last_forwarded_request: dict[str, Any] | None = None
        self.last_envelope: RoutingEnvelope | None = None

    def optimize(self, public_request: dict[str, Any], envelope: RoutingEnvelope) -> dict[str, Any]:
        canonical_public = self.fixtures.get("public_request")
        replay_input = dict(public_request)
        canonical_public = dict(canonical_public)
        replay_input.pop("saveToHistory", None)
        canonical_public.pop("saveToHistory", None)
        if json.dumps(replay_input, sort_keys=True) != json.dumps(canonical_public, sort_keys=True):
            raise ReplayMiss("request has no canonical replay")

        self.last_envelope = envelope
        self.last_forwarded_request = public_to_private(public_request, envelope)
        return self.fixtures.get("routing_response")

    def capabilities(self, *, allow_network: bool = True) -> dict[str, Any]:
        return self.fixtures.get("public_response")["support"]


class StubRoutingGateway:
    """Contract-shaped stub for focused tests; never performs routing work."""

    def __init__(self, fixtures: LockedFixtures | None = None) -> None:
        self.fixtures = fixtures or LockedFixtures()
        self.last_forwarded_request: dict[str, Any] | None = None
        self.last_envelope: RoutingEnvelope | None = None

    def optimize(self, public_request: dict[str, Any], envelope: RoutingEnvelope) -> dict[str, Any]:
        self.last_envelope = envelope
        self.last_forwarded_request = public_to_private(public_request, envelope)
        return self.fixtures.get("routing_response")

    def capabilities(self, *, allow_network: bool = True) -> dict[str, Any]:
        return self.fixtures.get("public_response")["support"]


class HttpRoutingGateway:
    """Generated-client adapter for the private Routing boundary."""

    def __init__(self, contracts: CanonicalContracts | None = None) -> None:
        self.contracts = contracts or CanonicalContracts()
        self.last_forwarded_request: dict[str, Any] | None = None
        self._capabilities_lock = threading.Lock()
        self._capabilities_value: dict[str, Any] | None = None
        self._capabilities_expires_at = 0.0
        base_url = self._validated_base_url()
        self.client = AuthenticatedClient(
            base_url=base_url,
            token=settings.ROUTING_SERVICE_TOKEN,
            timeout=httpx.Timeout(settings.ROUTING_DEADLINE_MILLISECONDS / 1000),
            verify_ssl=settings.ROUTING_VERIFY_SSL,
            follow_redirects=False,
            raise_on_unexpected_status=True,
        )

    @staticmethod
    def _validated_base_url() -> str:
        raw = settings.ROUTING_API_BASE_URL.strip()
        try:
            parsed = urlsplit(raw)
            host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
            port = parsed.port
        except (UnicodeError, ValueError) as exc:
            raise ContractError("invalid Routing API base URL") from exc
        if not host or parsed.username is not None or parsed.password is not None:
            raise ContractError("Routing API base URL must not contain user information")
        if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ContractError("Routing API base URL must be an origin without path, query, or fragment")
        if parsed.scheme not in {"http", "https"}:
            raise ContractError("Routing API base URL has an unsupported scheme")
        if settings.ENVIRONMENT == "production" and parsed.scheme != "https":
            raise ContractError("Routing API base URL must use HTTPS in production")
        allowed = {value.encode("idna").decode("ascii").lower().rstrip(".") for value in settings.ROUTING_API_ALLOWED_HOSTS}
        if settings.ENVIRONMENT == "production" and not allowed:
            raise ContractError("Routing API allowed hosts are required in production")
        if allowed and host not in allowed:
            raise ContractError("Routing API host is not allowed")
        default_port = 443 if parsed.scheme == "https" else 80
        authority = f"[{host}]" if ":" in host else host
        if port is not None and port != default_port:
            authority = f"{authority}:{port}"
        return f"{parsed.scheme}://{authority}"

    def optimize(self, public_request: dict[str, Any], envelope: RoutingEnvelope) -> dict[str, Any]:
        private = public_to_private(public_request, envelope)
        self.last_forwarded_request = private
        if self.contracts.validate("private", "OptimizeRouteRequest", private):
            raise ContractError("translated Routing request failed private schema validation")
        try:
            response = _bounded_generated_call(
                optimize_routes,
                client=self.client,
                max_bytes=settings.ROUTING_MAX_RESPONSE_BYTES,
                body=OptimizeRouteRequest.from_dict(private),
                x_correlation_id=envelope.correlation_id,
                x_request_deadline=envelope.request_deadline,
                idempotency_key=envelope.idempotency_key,
            )
        except httpx.TimeoutException as exc:
            raise RoutingGatewayError(504, "ROUTING_DEADLINE_EXCEEDED", True) from exc
        except httpx.HTTPError as exc:
            raise RoutingGatewayError(503, "TRANSIT_PROVIDER_UNAVAILABLE", True) from exc
        except (UnexpectedStatus, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RoutingGatewayError(502, "PROVIDER_BAD_RESPONSE", True) from exc
        if isinstance(response.parsed, OptimizeRouteResponse):
            try:
                value = response.parsed.to_dict()
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise RoutingGatewayError(502, "PROVIDER_BAD_RESPONSE", True) from exc
            if self.contracts.validate("private", "OptimizeRouteResponse", value):
                raise RoutingGatewayError(502, "PROVIDER_BAD_RESPONSE", True)
            if value.get("requestId") != private["requestId"]:
                raise RoutingGatewayError(502, "PROVIDER_BAD_RESPONSE", True)
            route_ids = [route.get("routeId") for route in value.get("routes", [])]
            if len(route_ids) != len(set(route_ids)):
                raise RoutingGatewayError(502, "PROVIDER_BAD_RESPONSE", True)
            return value
        if isinstance(response.parsed, ProblemDetails):
            try:
                value = response.parsed.to_dict()
                status = value.get("status")
                code = value.get("code")
                retryable = value.get("retryable")
                if (
                    not isinstance(status, int)
                    or isinstance(status, bool)
                    or status != response.status_code
                    or status not in {400, 401, 409, 422, 429, 503, 504}
                    or not isinstance(code, str)
                    or SAFE_ERROR_CODE.fullmatch(code) is None
                    or not isinstance(retryable, bool)
                ):
                    raise RoutingGatewayError(502, "PROVIDER_BAD_RESPONSE", True)
                raise RoutingGatewayError(
                    status,
                    code,
                    retryable,
                )
            except RoutingGatewayError:
                raise
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise RoutingGatewayError(502, "PROVIDER_BAD_RESPONSE", True) from exc
        raise RoutingGatewayError(502, "PROVIDER_BAD_RESPONSE", True)

    def capabilities(self, *, allow_network: bool = True) -> dict[str, Any]:
        with self._capabilities_lock:
            if self._capabilities_value is not None and self._capabilities_expires_at > time.monotonic():
                return dict(self._capabilities_value)
            if not allow_network:
                return project_capabilities(None)
            try:
                response = _bounded_generated_call(
                    get_routing_capabilities,
                    client=self.client,
                    max_bytes=settings.ROUTING_MAX_RESPONSE_BYTES,
                )
                if response.parsed is None:
                    value = project_capabilities(None)
                else:
                    private = response.parsed.to_dict()
                    value = (
                        project_capabilities(None)
                        if self.contracts.validate("private", "RoutingCapabilities", private)
                        else project_capabilities(private)
                    )
            except (
                httpx.HTTPError,
                UnexpectedStatus,
                json.JSONDecodeError,
                UnicodeDecodeError,
                KeyError,
                TypeError,
                ValueError,
                AttributeError,
            ):
                value = project_capabilities(None)
            self._capabilities_value = value
            self._capabilities_expires_at = (
                time.monotonic() + settings.ROUTING_CAPABILITIES_CACHE_TTL_SECONDS
            )
            return dict(value)
