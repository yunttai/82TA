from django.urls import path

from routing_api import views


urlpatterns = [
    path("v1/routes/optimize", views.optimize_routes),
    path("v1/capabilities", views.capabilities),
    path("v1/health/live", views.live),
    path("v1/health/ready", views.ready),
    path("v1/version", views.version),
    path("internal/admin/cache/invalidate", views.invalidate_cache),
    path("internal/admin/models/<str:version>/activate", views.activate_model),
]
