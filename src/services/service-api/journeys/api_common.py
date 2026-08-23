from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.core.exceptions import RequestDataTooBig
from django.http import HttpRequest, JsonResponse
from django.utils import timezone

from .contracts import CanonicalContracts
from .models import AnonymousSession, AuthenticatedSession, ServiceUser

SAFE_HEADER_VALUE = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")
contracts = CanonicalContracts()


@dataclass(frozen=True)
class ApiProblem(Exception):
    status: int
    code: str
    title: str
    retryable: bool = False
    detail: str | None = None
    violations: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class Subject:
    kind: str
    user: ServiceUser | None = None
    guest: AnonymousSession | None = None


def correlation_id(request: HttpRequest) -> str:
    supplied = request.headers.get("X-Correlation-Id")
    if not supplied:
        return str(uuid.uuid4())
    if not SAFE_HEADER_VALUE.fullmatch(supplied):
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid correlation identifier")
    return supplied


def problem_response(problem: ApiProblem, request: HttpRequest | None = None) -> JsonResponse:
    try:
        correlation = correlation_id(request) if request is not None else str(uuid.uuid4())
    except ApiProblem:
        correlation = str(uuid.uuid4())
    response = JsonResponse(
        {
            "type": f"https://api.example.invalid/problems/{problem.code.lower().replace('_', '-')}",
            "title": problem.title,
            "status": problem.status,
            "code": problem.code,
            "detail": problem.detail,
            "retryable": problem.retryable,
            "correlationId": correlation,
            "violations": list(problem.violations),
            "safeContext": {},
        },
        status=problem.status,
        content_type="application/problem+json",
    )
    response["X-Correlation-Id"] = correlation
    response["Cache-Control"] = "no-store"
    if problem.status == 429:
        response["Retry-After"] = "60"
    return response


def json_body(request: HttpRequest) -> dict[str, Any]:
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


def validate_schema(api: str, schema: str, value: Any) -> None:
    errors = contracts.validate(api, schema, value)
    if not errors:
        return
    violations = tuple(
        {
            "field": ".".join(str(part) for part in error.absolute_path) or "$",
            "message": error.message[:300],
        }
        for error in errors[:20]
    )
    raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Request does not match the API contract", violations=violations)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_subject(request: HttpRequest, *, required: bool = True, user_only: bool = False) -> Subject | None:
    user_id = request.session.get("service_user_id")
    if user_id:
        authenticated_session_id = request.session.get("service_authenticated_session_id")
        session_key = request.session.session_key
        authenticated = (
            AuthenticatedSession.objects.select_related("user")
            .filter(
                id=authenticated_session_id,
                user_id=user_id,
                token_hash=token_digest(session_key),
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
                user__is_active=True,
                user__deleted_at__isnull=True,
            )
            .first()
            if authenticated_session_id and session_key
            else None
        )
        if authenticated is not None:
            return Subject(kind="USER", user=authenticated.user)
        request.session.flush()

    if not user_only:
        token = request.headers.get("X-Guest-Token", "")
        if token:
            guest = AnonymousSession.objects.filter(
                token_hash=token_digest(token),
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).first()
            if guest is not None:
                return Subject(kind="GUEST", guest=guest)
        guest_id = request.session.get("service_guest_id")
        if guest_id:
            guest = AnonymousSession.objects.filter(
                id=guest_id,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).first()
            if guest is not None:
                return Subject(kind="GUEST", guest=guest)
            request.session.pop("service_guest_id", None)
    if required:
        raise ApiProblem(401, "AUTH_REQUIRED", "A valid session is required")
    return None


def create_browser_guest(request: HttpRequest, *, ttl_seconds: int) -> Subject:
    token = secrets.token_urlsafe(48)
    guest = AnonymousSession.objects.create(
        token_hash=token_digest(token),
        expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
    )
    request.session["service_guest_id"] = str(guest.id)
    return Subject(kind="GUEST", guest=guest)


def no_store(response: JsonResponse) -> JsonResponse:
    response["Cache-Control"] = "no-store"
    return response
