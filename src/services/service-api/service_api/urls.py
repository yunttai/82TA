from django.urls import include, path

urlpatterns = [
    path("", include("journeys.urls")),
    path("", include("places.urls")),
    path("", include("operations.urls")),
]
