from django.urls import path

from . import views

urlpatterns = [
    path("api/v1/places/suggest", views.suggest_places, name="suggest-places"),
    path("api/v1/places/reverse-geocode", views.reverse_geocode, name="reverse-geocode"),
]
