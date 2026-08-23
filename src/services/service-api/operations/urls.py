from django.urls import path

from . import views

urlpatterns = [path("api/v1/support/capabilities", views.capabilities, name="public-capabilities")]
