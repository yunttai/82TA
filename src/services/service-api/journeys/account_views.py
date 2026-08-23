from __future__ import annotations

import secrets
import unicodedata
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import rotate_token
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from consent.repository import ConsentRepository
from identity.data_rights import DataRightsJobConflict, DataRightsRepository
from identity.repository import IdentityRepository
from identity.sessions import SessionRepository
from preferences.repository import PreferenceRepository, PreferenceVersionConflict

from .abuse import enforce_rate_limit
from .api_common import (
    ApiProblem,
    current_subject,
    json_body,
    no_store,
    problem_response,
    token_digest,
    validate_schema,
)
from .consent_policy import consent_types, validate_document_version
from .models import (
    ConsentRecord,
    DataRightsJob,
    FavoriteJourney,
    SavedPlace,
    AccountAuditEvent,
    ServiceUser,
)

_DUMMY_PASSWORD_HASH = make_password("82ta-dummy-password-that-is-never-valid")

def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _preference(value) -> dict[str, Any]:
    return {
        "defaultTaxiBudget": value.default_taxi_budget,
        "maxWalkSeconds": value.max_walk_seconds,
        "maxTransfers": value.max_transfers,
        "maxTaxiLegs": value.max_taxi_legs,
        "optimizationProfile": value.optimization_profile,
        "accessibility": value.accessibility,
        "privacy": value.privacy,
        "version": value.version,
        "updatedAt": _iso(value.updated_at),
    }


def _place(value: SavedPlace) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "label": value.label,
        "place": {
            "displayName": value.display_name,
            "coordinate": value.coordinate,
            "provider": value.provider,
            "providerPlaceId": value.provider_place_id,
            "regionCode": None,
        },
        "isSensitive": value.is_sensitive,
        "createdAt": _iso(value.created_at),
        "updatedAt": _iso(value.updated_at),
    }


def _favorite(value: FavoriteJourney) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "nickname": value.nickname,
        "originSavedPlaceId": str(value.origin_saved_place_id),
        "destinationSavedPlaceId": str(value.destination_saved_place_id),
        "defaultConstraints": value.default_constraints,
        "createdAt": _iso(value.created_at),
        "updatedAt": _iso(value.updated_at),
    }


def _consent(value: ConsentRecord) -> dict[str, Any]:
    return {
        "consentType": value.consent_type,
        "documentVersion": value.document_version,
        "accepted": value.accepted,
        "recordedAt": _iso(value.recorded_at),
    }


def _job(value: DataRightsJob) -> dict[str, Any]:
    return {
        "jobId": str(value.id),
        "type": value.job_type,
        "status": value.status,
        "requestedAt": _iso(value.requested_at),
        "completedAt": _iso(value.completed_at),
        "downloadUrl": None,
        "downloadExpiresAt": _iso(value.download_expires_at),
        "failureCode": value.failure_code,
    }


def _normalized_email(value: Any) -> str:
    if not isinstance(value, str):
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid email or password")
    email = value.strip().casefold()
    try:
        validate_email(email)
    except ValidationError:
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid email or password") from None
    return email


@sensitive_variables("payload", "password")
def _credential_payload(request: HttpRequest) -> tuple[str, str]:
    payload = json_body(request)
    validate_schema("public", "EmailCredentialInput", payload)
    password = payload.get("password")
    if not isinstance(password, str):
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid email or password")
    return _normalized_email(payload.get("email")), password


@sensitive_variables("payload", "password")
def _registration_payload(request: HttpRequest) -> tuple[str, str, str, str, dict[str, bool]]:
    payload = json_body(request)
    validate_schema("public", "EmailRegistrationInput", payload)
    nickname = unicodedata.normalize("NFKC", payload["nickname"]).strip()
    if (
        len(nickname) < 2
        or len(nickname) > 20
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in nickname)
    ):
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Nickname must contain 2 to 20 characters")
    document_version = payload["documentVersion"]
    validate_document_version("SERVICE_PRIVACY", document_version)
    if payload["requiredPrivacyAccepted"] is not True:
        raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Privacy notice acceptance is required")
    optional_consents = payload["optionalConsents"]
    for consent_type in optional_consents:
        validate_document_version(consent_type, document_version)
    return _normalized_email(payload["email"]), payload["password"], nickname, document_version, optional_consents


def _start_user_session(request: HttpRequest, user: ServiceUser) -> dict[str, Any]:
    guest_id = request.session.get("service_guest_id")
    if guest_id:
        SessionRepository.revoke_guest(session_id=guest_id)
    previous_user_id = request.session.get("service_user_id")
    previous_session_id = request.session.get("service_authenticated_session_id")
    if previous_user_id and previous_session_id:
        SessionRepository.revoke_authenticated(
            user_id=previous_user_id,
            session_id=previous_session_id,
        )
    request.session.flush()
    rotate_token(request)
    request.session["service_user_id"] = str(user.id)
    request.session.set_expiry(settings.AUTH_SESSION_TTL_SECONDS)
    request.session.save()
    assert request.session.session_key is not None
    expires_at = timezone.now() + timedelta(seconds=settings.AUTH_SESSION_TTL_SECONDS)
    authenticated = SessionRepository.create_authenticated(
        user_id=user.id,
        token_hash=token_digest(request.session.session_key),
        expires_at=expires_at,
    )
    request.session["service_authenticated_session_id"] = str(authenticated.id)
    return {
        "subjectType": "USER",
        "authenticated": True,
        "expiresAt": _iso(expires_at),
        "email": user.email,
        "nickname": user.profile.nickname,
    }


@sensitive_variables("payload", "password", "password_hash")
@sensitive_post_parameters("password")
@require_http_methods(["POST"])
def register_with_email(request: HttpRequest) -> JsonResponse:
    try:
        enforce_rate_limit(
            request,
            scope="auth-register",
            limit=settings.AUTH_RATE_LIMIT_PER_MINUTE,
            title="Too many registration attempts",
        )
        email, password, nickname, document_version, optional_consents = _registration_payload(request)
        password_hash = make_password(password)
        try:
            with transaction.atomic():
                user = IdentityRepository.create_user(
                    email=email, password_hash=password_hash, nickname=nickname
                )
                ConsentRepository.record(
                    user_id=user.id, consent_type="SERVICE_PRIVACY",
                    document_version=document_version, accepted=True,
                )
                for consent_type, accepted in optional_consents.items():
                    ConsentRepository.record(
                        user_id=user.id, consent_type=consent_type,
                        document_version=document_version, accepted=accepted,
                    )
                AccountAuditEvent.objects.create(user=user, event_type="ACCOUNT_REGISTERED", safe_metadata={})
        except IntegrityError:
            raise ApiProblem(409, "ACCOUNT_ALREADY_EXISTS", "An account already exists") from None
        return no_store(JsonResponse(_start_user_session(request, user), status=201))
    except ApiProblem as problem:
        return problem_response(problem, request)


@sensitive_variables("payload", "password", "password_hash")
@sensitive_post_parameters("password")
@require_http_methods(["POST"])
def login_with_email(request: HttpRequest) -> JsonResponse:
    try:
        enforce_rate_limit(
            request,
            scope="auth-login",
            limit=settings.AUTH_RATE_LIMIT_PER_MINUTE,
            title="Too many login attempts",
        )
        email, password = _credential_payload(request)
        user = ServiceUser.objects.filter(email=email, is_active=True, deleted_at__isnull=True).first()
        password_hash = user.password_hash if user is not None and user.password_hash else _DUMMY_PASSWORD_HASH
        if not check_password(password, password_hash) or user is None:
            raise ApiProblem(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
        AccountAuditEvent.objects.create(user=user, event_type="ACCOUNT_LOGIN", safe_metadata={})
        return no_store(JsonResponse(_start_user_session(request, user)))
    except ApiProblem as problem:
        return problem_response(problem, request)


@require_http_methods(["POST"])
def create_guest_session(request: HttpRequest) -> JsonResponse:
    try:
        enforce_rate_limit(
            request,
            scope="guest-session",
            limit=settings.GUEST_SESSION_RATE_LIMIT_PER_MINUTE,
            title="Too many guest sessions",
        )
        token = secrets.token_urlsafe(48)
        expires_at = timezone.now() + timedelta(seconds=settings.GUEST_SESSION_TTL_SECONDS)
        guest = SessionRepository.create_guest(token_hash=token_digest(token), expires_at=expires_at)
        request.session["service_guest_id"] = str(guest.id)
        return no_store(JsonResponse({"guestToken": token, "expiresAt": _iso(expires_at)}, status=201))
    except ApiProblem as problem:
        return problem_response(problem, request)


@require_http_methods(["GET", "DELETE"])
def current_session(request: HttpRequest) -> JsonResponse:
    try:
        subject = current_subject(request)
        assert subject is not None
        if request.method == "DELETE":
            if subject.guest is not None:
                SessionRepository.revoke_guest(session_id=subject.guest.id)
            if subject.user is not None:
                authenticated_session_id = request.session.get("service_authenticated_session_id")
                if authenticated_session_id:
                    SessionRepository.revoke_authenticated(
                        user_id=subject.user.id,
                        session_id=authenticated_session_id,
                    )
                AccountAuditEvent.objects.create(
                    user=subject.user,
                    event_type="ACCOUNT_LOGOUT",
                    safe_metadata={},
                )
                request.session.flush()
            return HttpResponse(status=204)
        expires_at = subject.guest.expires_at if subject.guest else request.session.get_expiry_date()
        return no_store(
            JsonResponse(
                {
                    "subjectType": subject.kind,
                    "authenticated": subject.kind == "USER",
                    "expiresAt": _iso(expires_at),
                    **(
                        {"email": subject.user.email, "nickname": subject.user.profile.nickname}
                        if subject.user is not None else {}
                    ),
                }
            )
        )
    except ApiProblem as problem:
        return problem_response(problem, request)


@require_http_methods(["GET", "PUT"])
def preferences(request: HttpRequest) -> JsonResponse:
    try:
        subject = current_subject(request, user_only=True)
        assert subject and subject.user
        value = PreferenceRepository.get_or_create(user_id=subject.user.id)
        if request.method == "PUT":
            payload = json_body(request)
            validate_schema("public", "UserPreferences", payload)
            etag = request.headers.get("If-Match")
            try:
                expected = int(etag.strip('"')) if etag else value.version
            except ValueError:
                raise ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "If-Match must contain a quoted version") from None
            changes = {
                "default_taxi_budget": payload["defaultTaxiBudget"],
                "max_walk_seconds": payload["maxWalkSeconds"],
                "max_transfers": payload["maxTransfers"],
                "max_taxi_legs": payload["maxTaxiLegs"],
                "optimization_profile": payload["optimizationProfile"],
                "accessibility": payload.get("accessibility", {}),
                "privacy": payload.get("privacy", {}),
            }
            try:
                value = PreferenceRepository.update(
                    user_id=subject.user.id,
                    expected_version=expected,
                    changes=changes,
                )
            except PreferenceVersionConflict:
                raise ApiProblem(409, "PREFERENCE_VERSION_CONFLICT", "Preference version is stale") from None
        response = JsonResponse(_preference(value))
        response["ETag"] = f'"{value.version}"'
        return no_store(response)
    except ApiProblem as problem:
        return problem_response(problem, request)


@require_http_methods(["GET", "POST"])
def saved_places(request: HttpRequest) -> JsonResponse:
    try:
        subject = current_subject(request, user_only=True)
        assert subject and subject.user
        if request.method == "GET":
            values = SavedPlace.objects.filter(user=subject.user, deleted_at__isnull=True).order_by("created_at")
            return no_store(JsonResponse([_place(value) for value in values], safe=False))
        payload = json_body(request)
        validate_schema("public", "SavedPlaceInput", payload)
        place = payload["place"]
        value = SavedPlace(
            user=subject.user,
            label=payload["label"],
            display_name=place["displayName"],
            coordinate=place["coordinate"],
            provider=place.get("provider"),
            provider_place_id=place.get("providerPlaceId"),
            is_sensitive=payload.get("isSensitive", True),
        )
        value.full_clean()
        value.save()
        return no_store(JsonResponse(_place(value), status=201))
    except ApiProblem as problem:
        return problem_response(problem, request)
    except ValidationError:
        return problem_response(ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid saved place"), request)


@require_http_methods(["PATCH", "DELETE"])
def saved_place_detail(request: HttpRequest, saved_place_id: str) -> JsonResponse:
    try:
        subject = current_subject(request, user_only=True)
        assert subject and subject.user
        value = SavedPlace.objects.filter(
            id=saved_place_id,
            user=subject.user,
            deleted_at__isnull=True,
        ).first()
        if value is None:
            raise ApiProblem(404, "SEARCH_NOT_FOUND", "Saved place not found")
        if request.method == "DELETE":
            value.deleted_at = timezone.now()
            value.save(update_fields=["deleted_at"])
            return HttpResponse(status=204)
        payload = json_body(request)
        validate_schema("public", "SavedPlaceUpdate", payload)
        if "label" in payload:
            value.label = payload["label"]
        if "isSensitive" in payload:
            value.is_sensitive = payload["isSensitive"]
        if "place" in payload:
            place = payload["place"]
            value.display_name = place["displayName"]
            value.coordinate = place["coordinate"]
            value.provider = place.get("provider")
            value.provider_place_id = place.get("providerPlaceId")
        value.full_clean()
        value.save()
        return no_store(JsonResponse(_place(value)))
    except (ValueError, ValidationError):
        return problem_response(ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid saved place"), request)
    except ApiProblem as problem:
        return problem_response(problem, request)


def _owned_places(user, identifiers: list[str]) -> bool:
    return (
        SavedPlace.objects.filter(
            user=user,
            id__in=identifiers,
            deleted_at__isnull=True,
        ).count()
        == len(set(identifiers))
    )


@require_http_methods(["GET", "POST"])
def favorite_journeys(request: HttpRequest) -> JsonResponse:
    try:
        subject = current_subject(request, user_only=True)
        assert subject and subject.user
        if request.method == "GET":
            values = FavoriteJourney.objects.filter(user=subject.user, deleted_at__isnull=True).order_by("created_at")
            return no_store(JsonResponse([_favorite(value) for value in values], safe=False))
        payload = json_body(request)
        validate_schema("public", "FavoriteJourneyInput", payload)
        ids = [payload["originSavedPlaceId"], payload["destinationSavedPlaceId"]]
        if not _owned_places(subject.user, ids):
            raise ApiProblem(404, "SEARCH_NOT_FOUND", "Saved place not found")
        value = FavoriteJourney.objects.create(
            user=subject.user,
            nickname=payload["nickname"],
            origin_saved_place_id=ids[0],
            destination_saved_place_id=ids[1],
            default_constraints=payload["defaultConstraints"],
        )
        return no_store(JsonResponse(_favorite(value), status=201))
    except (ValueError, ValidationError):
        return problem_response(ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid favorite journey"), request)
    except ApiProblem as problem:
        return problem_response(problem, request)


@require_http_methods(["PATCH", "DELETE"])
def favorite_journey_detail(request: HttpRequest, favorite_journey_id: str) -> JsonResponse:
    try:
        subject = current_subject(request, user_only=True)
        assert subject and subject.user
        value = FavoriteJourney.objects.filter(
            id=favorite_journey_id,
            user=subject.user,
            deleted_at__isnull=True,
        ).first()
        if value is None:
            raise ApiProblem(404, "SEARCH_NOT_FOUND", "Favorite journey not found")
        if request.method == "DELETE":
            value.deleted_at = timezone.now()
            value.save(update_fields=["deleted_at"])
            return HttpResponse(status=204)
        payload = json_body(request)
        validate_schema("public", "FavoriteJourneyUpdate", payload)
        origin_id = payload.get("originSavedPlaceId", str(value.origin_saved_place_id))
        destination_id = payload.get("destinationSavedPlaceId", str(value.destination_saved_place_id))
        if not _owned_places(subject.user, [origin_id, destination_id]):
            raise ApiProblem(404, "SEARCH_NOT_FOUND", "Saved place not found")
        value.origin_saved_place_id = origin_id
        value.destination_saved_place_id = destination_id
        if "nickname" in payload:
            value.nickname = payload["nickname"]
        if "defaultConstraints" in payload:
            value.default_constraints = payload["defaultConstraints"]
        value.full_clean()
        value.save()
        return no_store(JsonResponse(_favorite(value)))
    except (ValueError, ValidationError):
        return problem_response(ApiProblem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid favorite journey"), request)
    except ApiProblem as problem:
        return problem_response(problem, request)


@require_http_methods(["GET"])
def consents(request: HttpRequest) -> JsonResponse:
    try:
        subject = current_subject(request, user_only=True)
        assert subject and subject.user
        items = []
        for consent_type in sorted(consent_types()):
            value = ConsentRepository.latest(user_id=subject.user.id, consent_type=consent_type)
            if value is not None:
                items.append(_consent(value))
        return no_store(JsonResponse({"items": items}))
    except ApiProblem as problem:
        return problem_response(problem, request)


@require_http_methods(["PUT"])
def consent_detail(request: HttpRequest, consent_type: str) -> JsonResponse:
    try:
        subject = current_subject(request, user_only=True)
        assert subject and subject.user
        payload = json_body(request)
        validate_schema("public", "ConsentInput", payload)
        validate_document_version(consent_type, payload["documentVersion"])
        if consent_type == "SERVICE_PRIVACY" and payload["accepted"] is not True:
            raise ApiProblem(
                400, "CONSTRAINT_OUT_OF_RANGE",
                "Required privacy acceptance can only end through account deletion",
            )
        value = ConsentRepository.record(
            user_id=subject.user.id,
            consent_type=consent_type,
            document_version=payload["documentVersion"],
            accepted=payload["accepted"],
        )
        return no_store(JsonResponse(_consent(value)))
    except ApiProblem as problem:
        return problem_response(problem, request)


def _create_job(request: HttpRequest, job_type: str) -> JsonResponse:
    subject = current_subject(request, user_only=True)
    assert subject and subject.user
    try:
        value = DataRightsRepository.create(user_id=subject.user.id, job_type=job_type)
    except DataRightsJobConflict:
        raise ApiProblem(409, "DATA_RIGHTS_JOB_CONFLICT", "A data-rights job is already active") from None
    return no_store(JsonResponse(_job(value), status=202))


@require_http_methods(["POST"])
def create_export(request: HttpRequest) -> JsonResponse:
    try:
        return _create_job(request, "EXPORT")
    except ApiProblem as problem:
        return problem_response(problem, request)


@require_http_methods(["POST"])
def create_deletion(request: HttpRequest) -> JsonResponse:
    try:
        return _create_job(request, "DELETE")
    except ApiProblem as problem:
        return problem_response(problem, request)


@require_http_methods(["DELETE"])
def delete_user_data(request: HttpRequest) -> JsonResponse:
    try:
        return _create_job(request, "DELETE")
    except ApiProblem as problem:
        return problem_response(problem, request)


def _job_status(request: HttpRequest, job_id: str, job_type: str) -> JsonResponse:
    subject = current_subject(request, user_only=True)
    assert subject and subject.user
    value = DataRightsJob.objects.filter(id=job_id, user=subject.user, job_type=job_type).first()
    if value is None:
        raise ApiProblem(404, "DATA_RIGHTS_JOB_NOT_FOUND", "Data-rights job not found")
    return no_store(JsonResponse(_job(value)))


@require_http_methods(["GET"])
def export_status(request: HttpRequest, job_id: str) -> JsonResponse:
    try:
        return _job_status(request, job_id, "EXPORT")
    except (ApiProblem, ValueError) as problem:
        if isinstance(problem, ApiProblem):
            return problem_response(problem, request)
        return problem_response(ApiProblem(404, "DATA_RIGHTS_JOB_NOT_FOUND", "Data-rights job not found"), request)


@require_http_methods(["GET"])
def deletion_status(request: HttpRequest, job_id: str) -> JsonResponse:
    try:
        return _job_status(request, job_id, "DELETE")
    except (ApiProblem, ValueError) as problem:
        if isinstance(problem, ApiProblem):
            return problem_response(problem, request)
        return problem_response(ApiProblem(404, "DATA_RIGHTS_JOB_NOT_FOUND", "Data-rights job not found"), request)
