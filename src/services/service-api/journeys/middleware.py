from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from .proxy import is_trusted_proxy, normalize_ip, trusted_proxy_networks


class TrustedProxyHeadersMiddleware:
    """Strip forwarding headers unless the immediate peer is explicitly trusted."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        peer = normalize_ip(request.META.get("REMOTE_ADDR", ""))
        if not settings.TRUST_PROXY_HEADERS or not is_trusted_proxy(peer, trusted_proxy_networks()):
            request.META.pop("HTTP_X_FORWARDED_FOR", None)
            request.META.pop("HTTP_X_FORWARDED_PROTO", None)
            request.META.pop("HTTP_X_FORWARDED_HOST", None)
            request.META.pop("HTTP_FORWARDED", None)
        return self.get_response(request)
