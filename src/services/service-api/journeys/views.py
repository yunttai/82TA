from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from consent.repository import ConsentRepository

from .abuse import enforce_rate_limit, rate_limit_cache
from .api_common import ApiProblem, create_browser_guest, current_subject
from .cache import BoundedTTLCache
from .consent_policy import is_current_accepted
from .contracts import CanonicalContracts, ContractError, LockedFixtures
from .coordination import CoordinationUnavailable, redis_coordination
from .gateway import (
    HttpRoutingGateway,
    ReplayMiss,
    ReplayRoutingGateway,
    RoutingEnvelope,
    RoutingGatewayError,
    StubRoutingGateway,
)
from .models import RouteFeedback, RouteSearch, RouteSearchResult
from .projection import project_public_response

_SAFE_CORRELATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_contracts = CanonicalContracts()
_fixtures: LockedFixtures | None = None
_gateway: Any = None
_idempotency_lock = threading.Lock()
_idempotency = BoundedTTLCache[str, tuple[str, dict[str, Any]]](
    max_entries=settings.IDEMPOTENCY_CACHE_MAX_ENTRIES,
    ttl_seconds=settings.IDEMPOTENCY_CACHE_TTL_SECONDS,
)
_rate_buckets = rate_limit_cache()


def _problem(problem: ApiProblem, correlation_id: str) -> JsonResponse:
    response = JsonResponse(
        {
            "type": f"https://api.example.invalid/problems/{problem.code.lower().replace('_', '-')}",
            "title": problem.title,
            "status": problem.status,
            "code": problem.code,
            "detail": problem.detail,
            "retryable": problem.retryable,
            "correlationId": correlation_id,
            "violations": list(problem.violations),
            "safeContext": {},
        },
        status=problem.status,
        content_type="application/problem+json",
    )
    response["X-Correlation-Id"] = correlation_id
    response["Cache-Control"] = "no-store"
    if problem.status == 429:
        response["Retry-After"] = "60"
    return response


def _correlation_id(request: HttpRequest) -> str:
    supplied = request.headers.get("X-Correlation-Id")
    if supplied is None or supplied == "":
        return str(uuid.uuid4())
    if not _SAFE_CORRELATION.fullmatch(supplied):
        raise ApiProblem(
            400,
            "CONSTRAINT_OUT_OF_RANGE",
            "Invalid correlation identifier",
            violations=({"field": "X-Correlation-Id", "message": "must be an opaque 1-128 character identifier"},),
        )
    return supplied


def _enforce_rate_limit(request: HttpRequest) -> None:
    enforce_rate_limit(
        request,
        scope="route-search",
        limit=settings.PUBLIC_RATE_LIMIT_PER_MINUTE,
        title="Too many route searches",
    )


def _idempotency_key(request: HttpRequest) -> str:
    key = request.headers.get("Idempotency-Key", "")
    if not (8 <= len(key) <= 128) or any(ord(character) < 0x20 or ord(character) == 0x7F for character in key):
        raise ApiProblem(
            400,
            "CONSTRAINT_OUT_OF_RANGE",
            "Invalid idempotency key",
            violations=({"field": "Idempotency-Key", "message": "must be 8-128 characters without controls"},),
        )
    return key


def _routing_idempotency_key(owner_key: str) -> str:
    """Return an opaque, owner-scoped key without disclosing Service identity."""

    return hmac.new(
        str(settings.SECRET_KEY).encode("utf-8"),
        owner_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _begin_idempotency(
    *,
    owner_key: str,
    fingerprint: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if settings.COORDINATION_BACKEND == "redis":
        try:
            decision = redis_coordination().begin_idempotency(
                owner_key=owner_key,
                fingerprint=fingerprint,
            )
        except CoordinationUnavailable:
            raise ApiProblem(
                429,
                "RATE_LIMITED",
                "Request coordination is temporarily unavailable",
                retryable=True,
            ) from None
        if decision.state == "REPLAY":
            return decision.response, None
        if decision.state == "CONFLICT":
            raise ApiProblem(409, "IDEMPOTENCY_CONFLICT", "Idempotency key was used with another request")
        if decision.state == "IN_PROGRESS":
            raise ApiProblem(409, "IDEMPOTENCY_CONFLICT", "An identical request is still processing")
        return None, decision.lease_token

    with _idempotency_lock:
        previous = _idempotency.get(owner_key)
    if previous:
        previous_fingerprint, previous_response = previous
        if previous_fingerprint != fingerprint:
            raise ApiProblem(409, "IDEMPOTENCY_CONFLICT", "Idempotency key was used with another request")
        return previous_response, None
    return None, None


def _complete_idempotency(
    *,
    owner_key: str,
    fingerprint: str,
    lease_token: str | None,
    response: dict[str, Any],
) -> None:
    if settings.COORDINATION_BACKEND == "redis":
        if lease_token is not None:
            redis_coordination().complete_idempotency(
                owner_key=owner_key,
                fingerprint=fingerprint,
                lease_token=lease_token,
                response=response,
            )
        return
    with _idempotency_lock:
        _idempotency.set(owner_key, (fingerprint, response))


def _abandon_idempotency(*, owner_key: str | None, lease_token: str | None) -> None:
    if settings.COORDINATION_BACKEND == "redis" and owner_key and lease_token:
        redis_coordination().abandon_idempotency(
            owner_key=owner_key,
            lease_token=lease_token,
        )


def _request_body(request: HttpRequest) -> dict[str, Any]:
    if not request.content_type or request.content_type.split(";", 1)[0].strip() != "application/json":
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Content-Type must be application/json")
    try:
        value = json.loads(request.body)
    except RequestDataTooBig:
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Request body exceeds the size limit") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Malformed JSON body") from None
    if not isinstance(value, dict):
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Request body must be an object")
    return value


def _validation_problem(errors: list[Any]) -> ApiProblem:
    paths = [".".join(str(part) for part in error.absolute_path) for error in errors]
    if any("coordinate" in path for path in paths):
        code, title = "INVALID_COORDINATE", "Invalid coordinate"
    elif any(path.startswith("departure") or path == "arrivalDeadline" for path in paths):
        code, title = "UNSUPPORTED_TIME", "Invalid time constraint"
    else:
        code, title = "CONSTRAINT_OUT_OF_RANGE", "Invalid route search request"
    violations = tuple(
        {"field": path or "$", "message": error.message[:300]}
        for path, error in zip(paths[:20], errors[:20], strict=True)
    )
    return ApiProblem(400, code, title, violations=violations)


def _dependencies() -> tuple[LockedFixtures, Any]:
    global _fixtures, _gateway
    if _fixtures is None:
        _fixtures = LockedFixtures()
    if _gateway is None:
        if settings.ROUTING_GATEWAY_MODE == "stub":
            _gateway = StubRoutingGateway(_fixtures)
        elif settings.ROUTING_GATEWAY_MODE == "replay":
            _gateway = ReplayRoutingGateway(_fixtures)
        elif settings.ROUTING_GATEWAY_MODE == "http":
            _gateway = HttpRoutingGateway(_contracts)
        else:
            raise ContractError("unsupported RoutingGateway mode")
    return _fixtures, _gateway


def gateway_dependencies() -> tuple[LockedFixtures, Any]:
    return _dependencies()


def _request_summary(search: RouteSearch) -> dict[str, Any] | None:
    constraints = search.constraints if isinstance(search.constraints, dict) else {}
    preferences = constraints.get("preferences")
    candidate = {
        "originDisplayName": search.origin_display_name,
        "destinationDisplayName": search.destination_display_name,
        "departureTime": search.departure_time.isoformat(),
        "arrivalDeadline": (
            search.arrival_deadline.isoformat() if search.arrival_deadline else None
        ),
        "taxiBudget": {
            "currency": "KRW",
            "maxAmount": search.taxi_budget_max,
            "strict": search.strict_budget,
        },
        "preferences": preferences,
    }
    if _contracts.validate("public", "RouteSearchRequestSummary", candidate):
        return None
    return candidate


def _search_response(search: RouteSearch) -> dict[str, Any]:
    now = timezone.now()
    metadata = search.constraints.get("_publicMetadata", {}) if isinstance(search.constraints, dict) else {}
    rows = list(search.results.order_by("created_at"))
    recommendations = {"fastest": None, "stable": None, "efficient": None, "publicTransitOnly": None}
    names = {
        "FASTEST": "fastest",
        "STABLE": "stable",
        "EFFICIENT": "efficient",
        "PUBLIC_TRANSIT_ONLY": "publicTransitOnly",
    }
    for row in rows:
        key = names.get(row.recommendation_type)
        if key:
            recommendations[key] = row.public_result
    baseline = recommendations["publicTransitOnly"]
    response = {
        "contractVersion": search.contract_version,
        "searchId": str(search.id),
        "status": "EXPIRED" if search.expires_at <= now else search.status,
        "generatedAt": metadata.get("generatedAt", search.created_at.isoformat()),
        "expiresAt": search.expires_at.isoformat(),
        "baseline": baseline,
        "recommendations": recommendations,
        "paretoFrontier": metadata.get("paretoFrontier", []),
        "warnings": metadata.get("warnings", []),
        "support": metadata.get("support") or _dependencies()[1].capabilities(allow_network=False),
        "history": {
            "saved": search.save_to_history,
            "ownerKind": "USER" if search.user_id else "GUEST",
            "retainedUntil": search.retention_until.isoformat(),
        },
    }
    summary = _request_summary(search)
    if summary is not None:
        response["requestSummary"] = summary
    return response


@transaction.atomic
def _persist_search(
    payload: dict[str, Any],
    public_response: dict[str, Any],
    subject: Any,
    routing_request_id: str,
) -> dict[str, Any]:
    saved = bool(payload.get("saveToHistory", False))
    retention_days = settings.MEMBER_HISTORY_RETENTION_DAYS if saved else 0
    now = timezone.now()
    expires_at = datetime.fromisoformat(public_response["expiresAt"])
    retention_until = (
        now + timedelta(days=retention_days)
        if saved
        else min(expires_at, now + timedelta(seconds=settings.ROUTE_RESULT_TTL_SECONDS))
    )
    search = RouteSearch.objects.create_owned(
        user=subject.user,
        anonymous_session=subject.guest,
        origin_coordinate=payload["origin"]["coordinate"],
        destination_coordinate=payload["destination"]["coordinate"],
        origin_display_name=payload["origin"]["displayName"],
        destination_display_name=payload["destination"]["displayName"],
        departure_time=datetime.fromisoformat(payload["departure"]["time"]),
        arrival_deadline=(
            datetime.fromisoformat(payload["arrivalDeadline"])
            if payload.get("arrivalDeadline")
            else None
        ),
        taxi_budget_max=payload["taxiBudget"]["maxAmount"],
        strict_budget=payload["taxiBudget"]["strict"],
        constraints={
            "preferences": payload["preferences"],
            "_publicMetadata": {
                "generatedAt": public_response["generatedAt"],
                "warnings": public_response["warnings"],
                "support": public_response["support"],
                "paretoFrontier": public_response.get("paretoFrontier", []),
            },
        },
        status=public_response["status"],
        routing_request_id=routing_request_id,
        contract_version=public_response["contractVersion"],
        save_to_history=saved,
        now=now,
        retention_until=retention_until,
        expires_at=expires_at,
    )
    mapping = {
        "fastest": "FASTEST",
        "stable": "STABLE",
        "efficient": "EFFICIENT",
        "publicTransitOnly": "PUBLIC_TRANSIT_ONLY",
    }
    seen: set[tuple[str, str]] = set()
    for key, recommendation_type in mapping.items():
        route = public_response["recommendations"].get(key)
        if not route or (recommendation_type, route["routeId"]) in seen:
            continue
        seen.add((recommendation_type, route["routeId"]))
        RouteSearchResult.objects.create(
            route_search=search,
            recommendation_type=recommendation_type,
            routing_route_id=route["routeId"],
            p50_seconds=route["totalDuration"]["p50Seconds"],
            p90_seconds=route["totalDuration"]["p90Seconds"],
            taxi_cost_expected=route["taxiCost"]["expected"],
            taxi_cost_upper=route["taxiCost"]["upper"],
            reliability_score=route["reliabilityScore"],
            public_result=route,
        )
    public_response = dict(public_response)
    public_response["searchId"] = str(search.id)
    public_response["history"] = {
        "saved": saved,
        "ownerKind": subject.kind,
        "retainedUntil": retention_until.isoformat(),
    }
    summary = _request_summary(search)
    if summary is not None:
        public_response["requestSummary"] = summary
    return public_response


@require_GET
@ensure_csrf_cookie
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    correlation_id = request.headers.get("X-Correlation-Id")
    if not correlation_id or not _SAFE_CORRELATION.fullmatch(correlation_id):
        correlation_id = str(uuid.uuid4())
    return _problem(ApiProblem(403, "FORBIDDEN", "CSRF verification failed"), correlation_id)


@require_http_methods(["GET", "POST"])
def create_route_search(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return list_route_searches(request)
    try:
        correlation_id = _correlation_id(request)
    except ApiProblem as problem:
        return _problem(problem, str(uuid.uuid4()))

    owner_key: str | None = None
    lease_token: str | None = None
    idempotency_finished = False
    fingerprint = ""
    routing_request_id: str | None = None
    subject = None
    try:
        _enforce_rate_limit(request)
        subject = current_subject(request, required=False)
        if subject is None:
            subject = create_browser_guest(request, ttl_seconds=settings.GUEST_SESSION_TTL_SECONDS)
        idempotency_key = _idempotency_key(request)
        payload = _request_body(request)
        errors = _contracts.validate("public", "PublicRouteSearchRequest", payload)
        if errors:
            raise _validation_problem(errors)
        if payload["departure"]["type"] == "ARRIVE_BY":
            raise ApiProblem(
                400,
                "ARRIVE_BY_UNSUPPORTED",
                "ARRIVE_BY is not supported by the current Routing contract",
                violations=({"field": "departure.type", "message": "use DEPART_AT"},),
            )

        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        owner_key = f"{subject.kind}:{subject.user.id if subject.user else subject.guest.id}:{idempotency_key}"
        previous_response, lease_token = _begin_idempotency(
            owner_key=owner_key,
            fingerprint=fingerprint,
        )
        if previous_response is not None:
            response = JsonResponse(previous_response)
            response["X-Correlation-Id"] = correlation_id
            response["Cache-Control"] = "no-store"
            return response

        if payload.get("saveToHistory"):
            if subject.user is None:
                raise ApiProblem(403, "CONSENT_REQUIRED", "History requires an authenticated user")
            consent = ConsentRepository.latest(user_id=subject.user.id, consent_type="SEARCH_HISTORY")
            if not is_current_accepted("SEARCH_HISTORY", consent):
                raise ApiProblem(403, "CONSENT_REQUIRED", "SEARCH_HISTORY consent is required")

        fixtures, gateway = _dependencies()
        routing_idempotency_key = _routing_idempotency_key(owner_key)
        routing_response = gateway.optimize(
            payload,
            RoutingEnvelope(
                correlation_id=correlation_id,
                idempotency_key=routing_idempotency_key,
                request_deadline=(
                    datetime.now(UTC) + timedelta(milliseconds=settings.ROUTING_DEADLINE_MILLISECONDS)
                ).isoformat(),
            ),
        )
        public_response = project_public_response(
            routing_response,
            _contracts,
            fixtures,
            support=gateway.capabilities(allow_network=False),
            public_request=payload,
        )
        routing_request_id = gateway.last_forwarded_request["requestId"]
        public_response = _persist_search(
            payload,
            public_response,
            subject,
            routing_request_id=routing_request_id,
        )
        _complete_idempotency(
            owner_key=owner_key,
            fingerprint=fingerprint,
            lease_token=lease_token,
            response=public_response,
        )
        idempotency_finished = True
        response = JsonResponse(public_response)
        response["X-Correlation-Id"] = correlation_id
        response["Cache-Control"] = "no-store"
        return response
    except ReplayMiss:
        return _problem(
            ApiProblem(
                503,
                "TRANSIT_PROVIDER_UNAVAILABLE",
                "No canonical replay is available for this request",
                retryable=True,
            ),
            correlation_id,
        )
    except ContractError:
        return _problem(
            ApiProblem(502, "PROVIDER_BAD_RESPONSE", "Routing response failed contract validation", retryable=True),
            correlation_id,
        )
    except RoutingGatewayError as error:
        return _problem(
            ApiProblem(error.status, error.code, "Routing request failed", retryable=error.retryable),
            correlation_id,
        )
    except IntegrityError:
        existing = None
        if routing_request_id and subject is not None:
            ownership = (
                {"user": subject.user}
                if subject.user is not None
                else {"anonymous_session": subject.guest}
            )
            existing = RouteSearch.objects.filter(
                routing_request_id=routing_request_id,
                **ownership,
            ).first()
        if existing is not None and owner_key:
            public_response = _search_response(existing)
            _complete_idempotency(
                owner_key=owner_key,
                fingerprint=fingerprint,
                lease_token=lease_token,
                response=public_response,
            )
            idempotency_finished = True
            response = JsonResponse(public_response)
            response["X-Correlation-Id"] = correlation_id
            response["Cache-Control"] = "no-store"
            return response
        return _problem(ApiProblem(409, "IDEMPOTENCY_CONFLICT", "Search already exists"), correlation_id)
    except ApiProblem as problem:
        return _problem(problem, correlation_id)
    finally:
        if not idempotency_finished:
            _abandon_idempotency(owner_key=owner_key, lease_token=lease_token)


@require_GET
def list_route_searches(request: HttpRequest) -> JsonResponse:
    try:
        subject = current_subject(request, user_only=True)
        assert subject and subject.user
        items = [
            _search_response(search)
            for search in RouteSearch.objects.filter(
                user=subject.user,
                save_to_history=True,
                retention_until__gt=timezone.now(),
            ).order_by("-created_at")[:100]
        ]
        response = JsonResponse({"items": items})
        response["Cache-Control"] = "no-store"
        return response
    except Exception as error:
        if hasattr(error, "status"):
            return _problem(error, str(uuid.uuid4()))
        raise


@require_GET
def get_route_search(request: HttpRequest, search_id: str) -> JsonResponse:
    try:
        subject = current_subject(request)
        assert subject is not None
        query = RouteSearch.objects.filter(id=search_id)
        query = query.filter(user=subject.user) if subject.user else query.filter(anonymous_session=subject.guest)
        search = query.first()
        if search is None:
            raise ApiProblem(404, "SEARCH_NOT_FOUND", "Route search not found")
        response = JsonResponse(_search_response(search))
        response["Cache-Control"] = "no-store"
        return response
    except (ValueError, ApiProblem) as error:
        problem = error if isinstance(error, ApiProblem) else ApiProblem(404, "SEARCH_NOT_FOUND", "Route search not found")
        return _problem(problem, str(uuid.uuid4()))


@require_POST
def submit_route_feedback(request: HttpRequest, search_id: str) -> JsonResponse:
    try:
        subject = current_subject(request)
        assert subject is not None
        query = RouteSearch.objects.filter(id=search_id)
        query = query.filter(user=subject.user) if subject.user else query.filter(anonymous_session=subject.guest)
        search = query.first()
        if search is None:
            raise ApiProblem(404, "SEARCH_NOT_FOUND", "Route search not found")
        payload = _request_body(request)
        errors = _contracts.validate("public", "RouteFeedbackInput", payload)
        if errors:
            raise _validation_problem(errors)
        if not search.results.filter(routing_route_id=payload["selectedRouteId"]).exists():
            raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "selectedRouteId is not part of this search")
        if subject.user:
            consent = ConsentRepository.latest(user_id=subject.user.id, consent_type="ROUTING_FEEDBACK")
            if not is_current_accepted("ROUTING_FEEDBACK", consent):
                raise ApiProblem(403, "CONSENT_REQUIRED", "ROUTING_FEEDBACK consent is required")
        RouteFeedback.objects.create(
            route_search=search,
            user=subject.user,
            selected_route_id=payload["selectedRouteId"],
            actual_duration_seconds=payload.get("actualDurationSeconds"),
            actual_taxi_cost=payload.get("actualTaxiCost"),
            arrived_on_time=payload.get("arrivedOnTime"),
            bus_outcome=payload.get("busOutcome"),
            rating=payload.get("rating"),
            comment=payload.get("comment"),
        )
        return HttpResponse(status=204)
    except IntegrityError:
        return _problem(ApiProblem(409, "IDEMPOTENCY_CONFLICT", "Feedback was already submitted"), str(uuid.uuid4()))
    except (ValueError, ApiProblem) as error:
        problem = error if isinstance(error, ApiProblem) else ApiProblem(404, "SEARCH_NOT_FOUND", "Route search not found")
        return _problem(problem, str(uuid.uuid4()))
