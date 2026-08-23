from django.urls import path

from . import account_views, views

urlpatterns = [
    path("api/v1/health", views.health, name="public-health"),
    path("api/v1/guest-sessions", account_views.create_guest_session, name="create-guest-session"),
    path("api/v1/session", account_views.current_session, name="current-session"),
    path("api/v1/route-searches", views.create_route_search, name="create-route-search"),
    path("api/v1/route-searches/<str:search_id>", views.get_route_search, name="get-route-search"),
    path(
        "api/v1/route-searches/<str:search_id>/feedback",
        views.submit_route_feedback,
        name="submit-route-feedback",
    ),
    path("api/v1/me/preferences", account_views.preferences, name="preferences"),
    path("api/v1/me/saved-places", account_views.saved_places, name="saved-places"),
    path(
        "api/v1/me/saved-places/<str:saved_place_id>",
        account_views.saved_place_detail,
        name="saved-place-detail",
    ),
    path("api/v1/me/favorite-journeys", account_views.favorite_journeys, name="favorite-journeys"),
    path(
        "api/v1/me/favorite-journeys/<str:favorite_journey_id>",
        account_views.favorite_journey_detail,
        name="favorite-journey-detail",
    ),
    path("api/v1/me/consents", account_views.consents, name="consents"),
    path("api/v1/me/consents/<str:consent_type>", account_views.consent_detail, name="consent-detail"),
    path("api/v1/me/data-exports", account_views.create_export, name="create-data-export"),
    path("api/v1/me/data-exports/<str:job_id>", account_views.export_status, name="data-export-status"),
    path("api/v1/me/data-deletions", account_views.create_deletion, name="create-data-deletion"),
    path("api/v1/me/data-deletions/<str:job_id>", account_views.deletion_status, name="data-deletion-status"),
    path("api/v1/me/data", account_views.delete_user_data, name="delete-user-data"),
]
