"""Production WSGI entry point with dependency registration before Django."""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "routing_api.settings")

from routing_deployment.bootstrap import bootstrap_from_environment

bootstrap_from_environment()

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
