"""Infrastructure-owned WSGI adapter for the Service API container."""

import os

from collections.abc import Callable, Iterable

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_api.settings")

django_application = get_wsgi_application()


def application(
    environ: dict[str, object],
    start_response: Callable[[str, list[tuple[str, str]]], object],
) -> Iterable[bytes]:
    """Expose a private process-health path without weakening HTTPS redirects."""

    if environ.get("PATH_INFO") == "/infra/healthz":
        start_response(
            "200 OK",
            [("Content-Type", "text/plain"), ("Content-Length", "3"), ("Cache-Control", "no-store")],
        )
        return [b"ok\n"]
    return django_application(environ, start_response)
