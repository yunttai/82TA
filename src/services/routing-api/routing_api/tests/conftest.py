"""Explicit source-checkout setup for API integration tests."""

from __future__ import annotations

import os

os.environ["ROUTING_RUNTIME_ENVIRONMENT"] = "TEST"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "routing_api.settings")

import django

from routing_api.workspace_packages import activate_workspace_packages

activate_workspace_packages()
django.setup()
