from django.urls import path

from . import views

urlpatterns = [
    path("api/v1/bike-options", views.bike_options, name="bike-options"),
]
