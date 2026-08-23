from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Mapping, MutableMapping, Protocol

from routing_api.auth import AuthenticationError, ServiceBearerVerifier
from routing_api.capabilities import CapabilityProjection
from routing_api.contract import CanonicalContractValidator, ContractViolation


INTERNAL_DEADLINE_SECONDS = 6.5
OPTIONAL_ENRICHMENT_RESERVE_SECONDS = 0.25
MAX_REQUEST_BYTES = 65_536
IDENTITY_KEYS = frozenset(
    {"userId", "email", "phone", "phoneNumber", "socialId", "savedPlaceLabel"}
)


@dataclass(frozen=True)
class RequestContext:
    correlation_id: str
    idempotency_key: str
    client_deadline: datetime
    effective_deadline: datetime
    optional_enrichment_allowed: bool
    cancellation: threading.Event


@dataclass(frozen=True)
class OptimizeCommand:
    payload: Mapping[str, object]


@dataclass(frozen=True)
class UseCaseResult:
    response: Mapping[str, object]
    optional_enrichment_complete: bool
    warning_codes: tuple[str, ...] = ()


class OptimizeRouteUseCase(Protocol):
    def execute(self, command: OptimizeCommand, context: RequestContext) -> UseCaseResult: ...


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


@dataclass(frozen=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


class RoutingUnavailableError(RuntimeError):
    """The required baseline providers cannot produce any valid route."""


class UnsupportedRegionError(RuntimeError):
    """The requested origin/destination corridor is outside supported coverage."""


class RoutingDeadlineExceeded(RuntimeError):
    """The injected use case did not complete inside the effective deadline."""


class RoutingCapacityExceeded(RuntimeError):
    """The process-local use-case admission budget is exhausted."""


class UnavailableOptimizeRouteUseCase:
    """Fail-closed production default until provider/domain fan-in is wired."""

    def execute(self, command: OptimizeCommand, context: RequestContext) -> UseCaseResult:
        raise RoutingUnavailableError("no verified baseline provider is configured")


class UseCaseRunner(Protocol):
    def run(
        self,
        use_case: OptimizeRouteUseCase,
        command: OptimizeCommand,
        context: RequestContext,
        timeout_seconds: float,
    ) -> UseCaseResult: ...


class BoundedUseCaseRunner:
    """Fail-fast process-local admission with no request queue wait."""

    def __init__(
        self,
        *,
        maximum_inflight: int = 8,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        if maximum_inflight <= 0:
            raise ValueError("maximum_inflight must be positive")
        self._admission = threading.BoundedSemaphore(maximum_inflight)
        self._executor = executor or ThreadPoolExecutor(
            max_workers=maximum_inflight,
            thread_name_prefix="routing-use-case",
        )

    def run(
        self,
        use_case: OptimizeRouteUseCase,
        command: OptimizeCommand,
        context: RequestContext,
        timeout_seconds: float,
    ) -> UseCaseResult:
        if not self._admission.acquire(blocking=False):
            raise RoutingCapacityExceeded("routing use-case admission is saturated")
        try:
            future: Future[UseCaseResult] = self._executor.submit(
                use_case.execute, command, context
            )
        except BaseException:
            self._admission.release()
            raise

        # The permit follows actual work, not merely the HTTP response. A timed-out
        # cooperative task releases immediately after observing cancellation; a
        # non-cooperative task stays admitted until it really terminates.
        future.add_done_callback(lambda _: self._admission.release())
        try:
            return future.result(timeout=max(0.0, timeout_seconds))
        except FutureTimeoutError as exc:
            context.cancellation.set()
            future.cancel()
            raise RoutingDeadlineExceeded from exc

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)


_DEFAULT_USE_CASE_RUNNER = BoundedUseCaseRunner()


class FixtureOptimizeRouteUseCase:
    """Deterministic local adapter with an explicit UNKNOWN-origin baseline route."""

    def __init__(self, clock: Clock, *, optional_complete: bool = False) -> None:
        self._clock = clock
        self._optional_complete = optional_complete

    def execute(self, command: OptimizeCommand, context: RequestContext) -> UseCaseResult:
        now = self._clock.now().astimezone(timezone.utc)
        request_id = str(command.payload["requestId"])
        route_id = "fixture_public_01"
        coordinate_from = command.payload["origin"]["coordinate"]  # type: ignore[index]
        coordinate_to = command.payload["destination"]["coordinate"]  # type: ignore[index]
        confidence = {"score": 0.0, "grade": "UNKNOWN"}
        time_estimate = {
            "p50Seconds": 3600,
            "p90Seconds": 4200,
            "lowerSeconds": None,
            "upperSeconds": None,
            "confidence": confidence,
            "origin": "UNKNOWN",
        }
        zero_cost = {
            "currency": "KRW",
            "expected": 0,
            "lower": 0,
            "upper": 0,
            "origin": "UNKNOWN",
        }
        provenance = {
            "provider": "FIXTURE",
            "origin": "UNKNOWN",
            "observedAt": None,
            "receivedAt": now.isoformat(),
            "ageSeconds": None,
            "confidence": confidence,
            "fallbackLevel": 0,
        }
        route = {
            "routeId": route_id,
            "pattern": "TRANSIT_ONLY",
            "totalDuration": time_estimate,
            "arrivalAt": {
                "p50": (now + timedelta(seconds=3600)).isoformat(),
                "p90": (now + timedelta(seconds=4200)).isoformat(),
            },
            "taxiCost": zero_cost,
            "totalFareExpected": 0,
            "walkSeconds": 3600,
            "transferCount": 0,
            "taxiLegCount": 0,
            "reliabilityScore": 0.0,
            "dominance": {"onParetoFrontier": True},
            "legs": [
                {
                    "legId": "fixture_leg_01",
                    "sequence": 0,
                    "mode": "WALK",
                    "from": {"name": "origin", "coordinate": coordinate_from},
                    "to": {"name": "destination", "coordinate": coordinate_to},
                    "expectedStartAt": now.isoformat(),
                    "expectedEndAt": (now + timedelta(seconds=3600)).isoformat(),
                    "duration": time_estimate,
                    "distanceMeters": 0,
                    "fare": zero_cost,
                    "geometry": {"encoding": "NONE"},
                    "transit": None,
                    "busIntelligence": None,
                    "provenance": [provenance],
                }
            ],
            "reasonCodes": ["WITHIN_STRICT_TAXI_BUDGET"],
            "warningCodes": ["PROVIDER_PARTIAL_FAILURE"],
            "provenance": [provenance],
        }
        response: dict[str, object] = {
            "contractVersion": "1.0",
            "requestId": request_id,
            "status": "COMPLETE" if self._optional_complete else "PARTIAL",
            "generatedAt": now.isoformat(),
            "expiresAt": (now + timedelta(seconds=120)).isoformat(),
            "computation": {
                "durationMs": 0,
                "rankingPolicyVersion": "rank-0.2.0",
                "mappingVersion": None,
                "candidateCounts": {
                    "generated": 1,
                    "coarsePruned": 0,
                    "fullyEvaluated": 1,
                    "pareto": 1,
                },
                "cache": {"fixture": True},
            },
            "recommendations": {
                "fastest": route_id,
                "stable": route_id,
                "efficient": route_id,
                "publicTransitOnly": route_id,
            },
            "routes": [route],
            "paretoRouteIds": [route_id],
            "providerStatus": [
                {
                    "provider": provider,
                    "operation": None,
                    "status": "DISABLED",
                    "latencyMs": 0,
                    "cache": False,
                    "messageCode": None,
                }
                for provider in ("KAKAO_TRANSIT", "KAKAO_WALK", "KAKAO_MOBILITY", "GBIS")
            ],
            "modelVersions": [],
            "warningCodes": [] if self._optional_complete else ["PROVIDER_PARTIAL_FAILURE"],
        }
        return UseCaseResult(
            response=response,
            optional_enrichment_complete=self._optional_complete,
            warning_codes=() if self._optional_complete else ("PROVIDER_PARTIAL_FAILURE",),
        )


class IdempotencyState(str, Enum):
    NEW = "NEW"
    CACHED = "CACHED"
    CONFLICT = "CONFLICT"
    IN_PROGRESS = "IN_PROGRESS"


@dataclass(frozen=True)
class IdempotencyDecision:
    state: IdempotencyState
    response: Mapping[str, object] | None = None


class InMemoryIdempotencyStore:
    """Deterministic local adapter; production can inject a shared-store adapter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: MutableMapping[str, tuple[str, Mapping[str, object] | None]] = {}

    def reserve(self, key: str, fingerprint: str) -> IdempotencyDecision:
        with self._lock:
            found = self._entries.get(key)
            if found is None:
                self._entries[key] = (fingerprint, None)
                return IdempotencyDecision(IdempotencyState.NEW)
            stored_fingerprint, response = found
            if stored_fingerprint != fingerprint:
                return IdempotencyDecision(IdempotencyState.CONFLICT)
            if response is None:
                return IdempotencyDecision(IdempotencyState.IN_PROGRESS)
            return IdempotencyDecision(IdempotencyState.CACHED, response)

    def complete(self, key: str, fingerprint: str, response: Mapping[str, object]) -> None:
        with self._lock:
            if self._entries.get(key) == (fingerprint, None):
                self._entries[key] = (fingerprint, response)

    def abandon(self, key: str, fingerprint: str) -> None:
        with self._lock:
            if self._entries.get(key) == (fingerprint, None):
                del self._entries[key]


@dataclass(frozen=True)
class ApiResult:
    status_code: int
    body: Mapping[str, object]
    content_type: str = "application/json"
    correlation_id: str | None = None


def _problem(
    status: int,
    code: str,
    title: str,
    correlation_id: str,
    *,
    retryable: bool = False,
    violations: tuple[ContractViolation, ...] = (),
) -> ApiResult:
    return ApiResult(
        status_code=status,
        content_type="application/problem+json",
        correlation_id=correlation_id,
        body={
            "type": f"https://budget-route.invalid/problems/{code.lower()}",
            "title": title,
            "status": status,
            "code": code,
            "detail": None,
            "retryable": retryable,
            "correlationId": correlation_id,
            "violations": [
                {"field": violation.field, "message": violation.message}
                for violation in violations
            ],
            "safeContext": {},
        },
    )


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _contains_identity(value: object) -> bool:
    if isinstance(value, dict):
        return any(key in IDENTITY_KEYS or _contains_identity(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_identity(item) for item in value)
    return False


def _coordinates_match(left: object, right: object, tolerance: float = 1e-6) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    for axis in ("lon", "lat"):
        left_value = left.get(axis)
        right_value = right.get(axis)
        if (
            not isinstance(left_value, (int, float))
            or isinstance(left_value, bool)
            or not isinstance(right_value, (int, float))
            or isinstance(right_value, bool)
            or abs(float(left_value) - float(right_value)) > tolerance
        ):
            return False
    return True


def _semantic_response_is_valid(response: Mapping[str, object], request: Mapping[str, object]) -> bool:
    if response.get("contractVersion") != "1.0" or response.get("requestId") != request.get("requestId"):
        return False
    routes = response.get("routes")
    recommendations = response.get("recommendations")
    pareto_ids = response.get("paretoRouteIds")
    if not isinstance(routes, list) or not isinstance(recommendations, dict) or not isinstance(pareto_ids, list):
        return False
    route_ids = {route.get("routeId") for route in routes if isinstance(route, dict)}
    if response.get("status") in {"COMPLETE", "PARTIAL"} and not routes:
        return False
    if any(value is not None and value not in route_ids for value in recommendations.values()):
        return False
    if any(value not in route_ids for value in pareto_ids):
        return False

    constraints = request.get("constraints")
    if not isinstance(constraints, dict) or not isinstance(constraints.get("taxiBudget"), dict):
        return False
    budget = constraints["taxiBudget"].get("maxAmount")
    if not isinstance(budget, int):
        return False
    request_origin = request.get("origin")
    request_destination = request.get("destination")
    if not isinstance(request_origin, dict) or not isinstance(request_destination, dict):
        return False
    origin_coordinate = request_origin.get("coordinate")
    destination_coordinate = request_destination.get("coordinate")
    for route in routes:
        if not isinstance(route, dict):
            return False
        total_duration = route.get("totalDuration")
        taxi_cost = route.get("taxiCost")
        legs = route.get("legs")
        if not isinstance(total_duration, dict) or not isinstance(taxi_cost, dict) or not isinstance(legs, list):
            return False
        if not legs:
            return False
        first_leg = legs[0]
        last_leg = legs[-1]
        if not isinstance(first_leg, dict) or not isinstance(last_leg, dict):
            return False
        first_from = first_leg.get("from")
        last_to = last_leg.get("to")
        if (
            not isinstance(first_from, dict)
            or not isinstance(last_to, dict)
            or not _coordinates_match(first_from.get("coordinate"), origin_coordinate)
            or not _coordinates_match(last_to.get("coordinate"), destination_coordinate)
        ):
            return False
        for previous, following in zip(legs, legs[1:]):
            if not isinstance(previous, dict) or not isinstance(following, dict):
                return False
            previous_to = previous.get("to")
            following_from = following.get("from")
            if (
                not isinstance(previous_to, dict)
                or not isinstance(following_from, dict)
                or not _coordinates_match(
                    previous_to.get("coordinate"), following_from.get("coordinate")
                )
            ):
                return False
        if total_duration.get("p90Seconds", -1) < total_duration.get("p50Seconds", 0):
            return False
        if taxi_cost.get("upper", budget + 1) > budget:
            return False
        taxi_upper_sum = 0
        for leg in legs:
            if not isinstance(leg, dict) or not isinstance(leg.get("duration"), dict):
                return False
            duration = leg["duration"]
            if duration.get("p90Seconds", -1) < duration.get("p50Seconds", 0):
                return False
            if leg.get("mode") == "TAXI":
                fare = leg.get("fare")
                if not isinstance(fare, dict) or not isinstance(fare.get("upper"), int):
                    return False
                taxi_upper_sum += fare["upper"]
        if taxi_upper_sum > budget or taxi_cost.get("upper") != taxi_upper_sum:
            return False
    return True


class RoutingApiApplication:
    def __init__(
        self,
        *,
        verifier: ServiceBearerVerifier,
        contract: CanonicalContractValidator,
        use_case: OptimizeRouteUseCase,
        clock: Clock,
        idempotency: InMemoryIdempotencyStore,
        build_version: str,
        runner: UseCaseRunner | None = None,
        capability_projection: CapabilityProjection | None = None,
        backend_state: str = "unavailable",
        ranking_policy_version: str = "unavailable",
    ) -> None:
        self._verifier = verifier
        self._contract = contract
        self._use_case = use_case
        self._clock = clock
        self._idempotency = idempotency
        self._build_version = build_version
        self._runner = runner or _DEFAULT_USE_CASE_RUNNER
        self._capability_projection = capability_projection or CapabilityProjection(
            features={
                "currentTransit": False,
                "futureTransit": False,
                "currentTaxi": False,
                "futureTaxi": False,
                "multiDestinationTaxi": False,
                "busSeatRisk": False,
                "busEtaModel": False,
                "taxiBridge": False,
                "realtimeRerouting": False,
            },
            providers=(),
            degraded=("CAPABILITY_REGISTRY_UNAVAILABLE", "NO_MODEL_ACTIVE"),
            models=(),
        )
        self._backend_state = backend_state
        self._ranking_policy_version = ranking_policy_version

    def authenticate(self, authorization: str | None, correlation_id: str = "unavailable") -> ApiResult | None:
        try:
            self._verifier.verify(authorization)
        except AuthenticationError:
            return _problem(401, "SERVICE_AUTH_REQUIRED", "Service authentication required", correlation_id)
        return None

    def optimize(
        self,
        *,
        authorization: str | None,
        correlation_id: str | None,
        deadline_header: str | None,
        idempotency_key: str | None,
        content_type: str,
        raw_body: bytes,
    ) -> ApiResult:
        request_started_at = self._clock.now()
        safe_correlation = correlation_id if correlation_id is not None else "missing"
        auth_failure = self.authenticate(authorization, safe_correlation)
        if auth_failure:
            return auth_failure

        header_violations: list[ContractViolation] = []
        if correlation_id is None:
            header_violations.append(ContractViolation("X-Correlation-Id", "header is required"))
        if deadline_header is None:
            header_violations.append(ContractViolation("X-Request-Deadline", "header is required"))
        if idempotency_key is None:
            header_violations.append(ContractViolation("Idempotency-Key", "header is required"))
        elif not 8 <= len(idempotency_key) <= 128:
            header_violations.append(ContractViolation("Idempotency-Key", "length must be 8..128"))
        if header_violations:
            return _problem(
                400,
                "CONSTRAINT_OUT_OF_RANGE",
                "Invalid routing request headers",
                safe_correlation,
                violations=tuple(header_violations),
            )
        assert deadline_header is not None and idempotency_key is not None and correlation_id is not None

        client_deadline = _parse_timestamp(deadline_header)
        now = request_started_at
        if client_deadline is None:
            return _problem(
                400,
                "UNSUPPORTED_TIME",
                "Request deadline must be timezone-aware ISO 8601",
                correlation_id,
            )
        if client_deadline <= now:
            return _problem(
                504,
                "ROUTING_DEADLINE_EXCEEDED",
                "Routing deadline exceeded",
                correlation_id,
                retryable=True,
            )
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            return _problem(400, "CONSTRAINT_OUT_OF_RANGE", "Content-Type must be application/json", correlation_id)
        if len(raw_body) > MAX_REQUEST_BYTES:
            return _problem(400, "CONSTRAINT_OUT_OF_RANGE", "Routing request is too large", correlation_id)
        try:
            payload = json.loads(
                raw_body,
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return _problem(400, "CONSTRAINT_OUT_OF_RANGE", "Request body must be valid JSON", correlation_id)

        violations = list(self._contract.validate_optimize_request(payload))
        if _contains_identity(payload):
            violations.append(ContractViolation("$", "identity fields are forbidden"))
        if violations:
            return _problem(
                400,
                "CONSTRAINT_OUT_OF_RANGE",
                "Routing request violates the canonical contract",
                correlation_id,
                violations=tuple(violations),
            )
        assert isinstance(payload, dict)

        effective_deadline = min(client_deadline, now + timedelta(seconds=INTERNAL_DEADLINE_SECONDS))
        remaining = (effective_deadline - self._clock.now()).total_seconds()
        if remaining <= 0:
            return _problem(
                504,
                "ROUTING_DEADLINE_EXCEEDED",
                "Routing deadline exceeded",
                correlation_id,
                retryable=True,
            )
        context = RequestContext(
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            client_deadline=client_deadline,
            effective_deadline=effective_deadline,
            optional_enrichment_allowed=remaining > OPTIONAL_ENRICHMENT_RESERVE_SECONDS,
            cancellation=threading.Event(),
        )
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        decision = self._idempotency.reserve(idempotency_key, fingerprint)
        if decision.state is IdempotencyState.CONFLICT:
            return _problem(409, "IDEMPOTENCY_CONFLICT", "Idempotency key reused for another request", correlation_id)
        if decision.state is IdempotencyState.IN_PROGRESS:
            return _problem(409, "IDEMPOTENCY_CONFLICT", "Identical request is already in progress", correlation_id)
        if decision.state is IdempotencyState.CACHED:
            assert decision.response is not None
            return ApiResult(200, decision.response, correlation_id=correlation_id)

        started = self._clock.monotonic()
        try:
            outcome = self._runner.run(
                self._use_case,
                OptimizeCommand(payload),
                context,
                timeout_seconds=remaining,
            )
        except RoutingCapacityExceeded:
            self._idempotency.abandon(idempotency_key, fingerprint)
            return _problem(
                429,
                "RATE_LIMITED",
                "Routing capacity is saturated",
                correlation_id,
                retryable=True,
            )
        except RoutingDeadlineExceeded:
            self._idempotency.abandon(idempotency_key, fingerprint)
            return _problem(
                504,
                "ROUTING_DEADLINE_EXCEEDED",
                "Routing deadline exceeded",
                correlation_id,
                retryable=True,
            )
        except UnsupportedRegionError:
            self._idempotency.abandon(idempotency_key, fingerprint)
            return _problem(
                422,
                "UNSUPPORTED_REGION",
                "Requested region is unsupported",
                correlation_id,
            )
        except RoutingUnavailableError:
            self._idempotency.abandon(idempotency_key, fingerprint)
            return _problem(
                503,
                "TRANSIT_PROVIDER_UNAVAILABLE",
                "Required routing providers are unavailable",
                correlation_id,
                retryable=True,
            )
        except Exception:
            self._idempotency.abandon(idempotency_key, fingerprint)
            return _problem(
                503,
                "TRANSIT_PROVIDER_UNAVAILABLE",
                "Routing backend unavailable",
                correlation_id,
                retryable=True,
            )

        response = dict(outcome.response)
        computation = dict(response.get("computation", {}))
        computation["durationMs"] = max(0, int((self._clock.monotonic() - started) * 1000))
        response["computation"] = computation
        routes = response.get("routes")
        can_degrade_to_partial = (
            isinstance(routes, list)
            and bool(routes)
            and response.get("status") in {"COMPLETE", "PARTIAL"}
        )
        if not outcome.optional_enrichment_complete and can_degrade_to_partial:
            response["status"] = "PARTIAL"
            warnings = list(response.get("warningCodes", []))
            for warning in outcome.warning_codes:
                if warning not in warnings:
                    warnings.append(warning)
            response["warningCodes"] = warnings
        if self._contract.validate_optimize_response(response) or not _semantic_response_is_valid(
            response, payload
        ):
            self._idempotency.abandon(idempotency_key, fingerprint)
            return _problem(
                503,
                "TRANSIT_PROVIDER_UNAVAILABLE",
                "Routing backend produced an invalid result",
                correlation_id,
                retryable=True,
            )
        self._idempotency.complete(idempotency_key, fingerprint, response)
        return ApiResult(200, response, correlation_id=correlation_id)

    def capabilities(self) -> Mapping[str, object]:
        return {
            "generatedAt": self._clock.now().astimezone(timezone.utc).isoformat(),
            "region": {"originSupported": False, "destinationSupported": False},
            "features": dict(self._capability_projection.features),
            "providers": list(self._capability_projection.providers),
            "models": [dict(item) for item in self._capability_projection.models],
            "degraded": list(self._capability_projection.degraded),
        }

    def readiness(self) -> Mapping[str, object]:
        providers_ready = (
            self._backend_state == "production"
            and bool(self._capability_projection.features.get("currentTransit"))
        )
        return {
            "status": "degraded",
            "checks": {
                "contract": "ready",
                "backend": self._backend_state,
                "providers": "ready" if providers_ready else "disabled",
                "models": (
                    "ready"
                    if {
                        item.get("purpose")
                        for item in self._capability_projection.models
                        if item.get("state") == "ACTIVE"
                    }
                    == {"BUS_ETA", "SEAT_RISK"}
                    else "inactive"
                ),
            },
        }

    def version(self) -> Mapping[str, object]:
        return {
            "buildVersion": self._build_version,
            "contractVersion": self._contract.contract_version,
            "rankingPolicyVersion": self._ranking_policy_version,
            "models": [
                {"purpose": item["purpose"], "version": item["version"]}
                for item in self._capability_projection.models
            ],
        }
