from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from identity.artifacts import DataRightsArtifactStore, configured_artifact_store
from journeys.contracts import CanonicalContracts
from journeys.favorite_payload import typed_search_conditions
from journeys.models import (
    AccountAuditEvent,
    AnonymousSession,
    AuthenticatedSession,
    ConsentRecord,
    DataRightsJob,
    FavoriteCreationIdempotency,
    FavoriteJourney,
    RouteFeedback,
    RouteSearch,
    SavedPlace,
    ServiceUser,
    UserPreference,
    UserProfile,
)


GUEST_SEARCH_RETENTION = timedelta(days=7)
MEMBER_SEARCH_RETENTION = timedelta(days=90)
ACCOUNT_DELETION_GRACE = timedelta(days=30)
AUDIT_RETENTION = timedelta(days=365)
_contracts = CanonicalContracts()


@dataclass(frozen=True)
class PurgeReport:
    expired_anonymous_sessions: int = 0
    expired_authenticated_sessions: int = 0
    expired_guest_searches: int = 0
    expired_member_searches: int = 0
    expired_export_artifacts: int = 0
    expired_favorite_creation_idempotency: int = 0
    hard_deleted_accounts: int = 0
    expired_audit_events: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _delete_count(queryset: QuerySet[Any]) -> int:
    count = queryset.count()
    queryset.delete()
    return count


def _purge_expired_favorite_creation_receipts(*, now) -> int:
    receipts = FavoriteCreationIdempotency.objects.filter(expires_at__lte=now)
    owner_ids = list(
        receipts.order_by().values_list("user_id", flat=True).distinct()
    )
    if owner_ids:
        # Keep the global mutation order aligned with atomic creation and account
        # deletion: owner first, then the durable receipt/resource rows.
        list(
            ServiceUser.objects.select_for_update()
            .filter(id__in=owner_ids)
            .order_by("id")
            .values_list("id", flat=True)
        )
    return _delete_count(receipts)


@transaction.atomic
def schedule_user_deletion(*, user_id: UUID | str, requested_at=None) -> ServiceUser:
    requested_at = requested_at or timezone.now()
    user = ServiceUser.objects.select_for_update().get(id=user_id)
    if user.deleted_at is None:
        user.is_active = False
        user.deleted_at = requested_at
        user.save(update_fields=["is_active", "deleted_at"])
        AuthenticatedSession.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=requested_at
        )
        SavedPlace.objects.filter(user=user, deleted_at__isnull=True).update(deleted_at=requested_at)
        FavoriteJourney.objects.filter(user=user, deleted_at__isnull=True).update(
            deleted_at=requested_at
        )
        AccountAuditEvent.objects.create(
            user=user,
            event_type="DATA_DELETION_SCHEDULED",
            safe_metadata={"gracePeriodDays": ACCOUNT_DELETION_GRACE.days},
        )
    return user


def _delete_export_artifact(
    *,
    job: DataRightsJob,
    artifact_store: DataRightsArtifactStore | None,
) -> bool:
    try:
        store = artifact_store or configured_artifact_store()
        store.delete(artifact_ref=job.artifact_ref or "")
    except Exception:
        AccountAuditEvent.objects.create(
            user=job.user,
            event_type="DATA_EXPORT_ARTIFACT_PURGE_FAILED",
            safe_metadata={"jobId": str(job.id), "failureCode": "ARTIFACT_STORE_UNAVAILABLE"},
        )
        return False
    return True


@transaction.atomic
def hard_delete_user_data(
    *,
    user_id: UUID | str,
    artifact_store: DataRightsArtifactStore | None = None,
) -> bool:
    user = ServiceUser.objects.select_for_update().filter(id=user_id).first()
    if user is None:
        return False
    export_jobs = list(
        DataRightsJob.objects.select_for_update().filter(
            user=user,
            job_type=DataRightsJob.JobType.EXPORT,
            artifact_ref__isnull=False,
        )
    )
    for job in export_jobs:
        if not _delete_export_artifact(job=job, artifact_store=artifact_store):
            return False
    AccountAuditEvent.objects.create(
        user=user,
        event_type="DATA_DELETION_COMPLETED",
        safe_metadata={},
    )
    FavoriteCreationIdempotency.objects.filter(user=user).delete()
    user.delete()
    return True


@transaction.atomic
def purge_service_data(
    *,
    now=None,
    artifact_store: DataRightsArtifactStore | None = None,
) -> PurgeReport:
    now = now or timezone.now()
    expired_favorite_creation_idempotency = _purge_expired_favorite_creation_receipts(
        now=now
    )
    expired_guest_searches = _delete_count(
        RouteSearch.objects.filter(
            anonymous_session__isnull=False,
            retention_until__lte=now,
        )
    )
    expired_member_searches = _delete_count(
        RouteSearch.objects.filter(
            user__isnull=False,
            retention_until__lte=now,
        )
    )
    expired_anonymous_sessions = _delete_count(
        AnonymousSession.objects.filter(Q(expires_at__lte=now) | Q(revoked_at__isnull=False))
    )
    expired_authenticated_sessions = _delete_count(
        AuthenticatedSession.objects.filter(Q(expires_at__lte=now) | Q(revoked_at__isnull=False))
    )
    expired_export_artifacts = 0
    expired_export_jobs = list(
        DataRightsJob.objects.select_for_update().filter(
            job_type=DataRightsJob.JobType.EXPORT,
            artifact_ref__isnull=False,
            download_expires_at__lte=now,
        )
    )
    for export_job in expired_export_jobs:
        if not _delete_export_artifact(job=export_job, artifact_store=artifact_store):
            continue
        export_job.artifact_ref = None
        export_job.download_expires_at = None
        export_job.save(update_fields=["artifact_ref", "download_expires_at"])
        AccountAuditEvent.objects.create(
            user=export_job.user,
            event_type="DATA_EXPORT_ARTIFACT_PURGED",
            safe_metadata={"jobId": str(export_job.id)},
        )
        expired_export_artifacts += 1
    account_ids = list(
        ServiceUser.objects.filter(
            is_active=False,
            deleted_at__isnull=False,
            deleted_at__lte=now - ACCOUNT_DELETION_GRACE,
        ).values_list("id", flat=True)
    )
    hard_deleted_accounts = 0
    for account_id in account_ids:
        hard_deleted_accounts += int(
            hard_delete_user_data(user_id=account_id, artifact_store=artifact_store)
        )
    expired_audit_events = _delete_count(
        AccountAuditEvent.objects.filter(created_at__lt=now - AUDIT_RETENTION)
    )
    return PurgeReport(
        expired_anonymous_sessions=expired_anonymous_sessions,
        expired_authenticated_sessions=expired_authenticated_sessions,
        expired_guest_searches=expired_guest_searches,
        expired_member_searches=expired_member_searches,
        expired_export_artifacts=expired_export_artifacts,
        expired_favorite_creation_idempotency=expired_favorite_creation_idempotency,
        hard_deleted_accounts=hard_deleted_accounts,
        expired_audit_events=expired_audit_events,
    )


def export_user_data(*, user_id: UUID | str) -> dict[str, Any]:
    """Return the authenticated subject's portable data without secrets or token hashes."""

    user = ServiceUser.objects.get(id=user_id)
    profile = UserProfile.objects.filter(user=user).first()
    preference = UserPreference.objects.filter(user=user).first()
    saved_places = SavedPlace.objects.filter(user=user).order_by("created_at")
    favorites = FavoriteJourney.objects.filter(user=user).order_by("created_at")
    searches = RouteSearch.objects.filter(user=user).order_by("created_at")
    feedback = RouteFeedback.objects.filter(user=user).order_by("created_at")
    consents = ConsentRecord.objects.filter(user=user).order_by("recorded_at")

    return {
        "account": {
            "id": str(user.id),
            "email": user.email,
            "isActive": user.is_active,
            "createdAt": user.created_at.isoformat(),
            "deletedAt": user.deleted_at.isoformat() if user.deleted_at else None,
        },
        "profile": None
        if profile is None
        else {"locale": profile.locale, "timezone": profile.timezone, "updatedAt": profile.updated_at.isoformat()},
        "preferences": None
        if preference is None
        else {
            "defaultTaxiBudget": preference.default_taxi_budget,
            "maxWalkSeconds": preference.max_walk_seconds,
            "maxTransfers": preference.max_transfers,
            "maxTaxiLegs": preference.max_taxi_legs,
            "optimizationProfile": preference.optimization_profile,
            "accessibility": preference.accessibility,
            "privacy": preference.privacy,
            "version": preference.version,
            "updatedAt": preference.updated_at.isoformat(),
        },
        "savedPlaces": [
            {
                "id": str(place.id),
                "label": place.label,
                "displayName": place.display_name,
                "coordinate": place.coordinate,
                "provider": place.provider,
                "providerPlaceId": place.provider_place_id,
                "isSensitive": place.is_sensitive,
                "createdAt": place.created_at.isoformat(),
                "updatedAt": place.updated_at.isoformat(),
                "deletedAt": place.deleted_at.isoformat() if place.deleted_at else None,
            }
            for place in saved_places
        ],
        "favoriteJourneys": [
            {
                "id": str(favorite.id),
                "nickname": favorite.nickname,
                "originSavedPlaceId": str(favorite.origin_saved_place_id)
                if favorite.origin_saved_place_id
                else None,
                "destinationSavedPlaceId": str(favorite.destination_saved_place_id)
                if favorite.destination_saved_place_id
                else None,
                "defaultConstraints": favorite.default_constraints,
                "searchConditions": typed_search_conditions(
                    favorite.default_constraints,
                    validator=lambda candidate: _contracts.validate(
                        "public", "FavoriteJourneySearchConditionsV1", candidate
                    ),
                ),
                "createdAt": favorite.created_at.isoformat(),
                "updatedAt": favorite.updated_at.isoformat(),
                "deletedAt": favorite.deleted_at.isoformat() if favorite.deleted_at else None,
            }
            for favorite in favorites
        ],
        "routeSearches": [
            {
                "id": str(search.id),
                "originCoordinate": search.origin_coordinate,
                "destinationCoordinate": search.destination_coordinate,
                "originDisplayName": search.origin_display_name,
                "destinationDisplayName": search.destination_display_name,
                "departureTime": search.departure_time.isoformat(),
                "arrivalDeadline": search.arrival_deadline.isoformat() if search.arrival_deadline else None,
                "taxiBudgetMax": search.taxi_budget_max,
                "strictBudget": search.strict_budget,
                "constraints": search.constraints,
                "status": search.status,
                "contractVersion": search.contract_version,
                "saveToHistory": search.save_to_history,
                "retentionUntil": search.retention_until.isoformat(),
                "createdAt": search.created_at.isoformat(),
                "expiresAt": search.expires_at.isoformat(),
                "results": [result.public_result for result in search.results.order_by("created_at")],
            }
            for search in searches.prefetch_related("results")
        ],
        "feedback": [
            {
                "routeSearchId": str(item.route_search_id),
                "selectedRouteId": item.selected_route_id,
                "actualDurationSeconds": item.actual_duration_seconds,
                "actualTaxiCost": item.actual_taxi_cost,
                "arrivedOnTime": item.arrived_on_time,
                "busOutcome": item.bus_outcome,
                "rating": item.rating,
                "comment": item.comment,
                "createdAt": item.created_at.isoformat(),
            }
            for item in feedback
        ],
        "consents": [
            {
                "consentType": consent.consent_type,
                "documentVersion": consent.document_version,
                "accepted": consent.accepted,
                "recordedAt": consent.recorded_at.isoformat(),
            }
            for consent in consents
        ],
    }
