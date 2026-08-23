from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET
from journeys.api_common import no_store
from journeys.views import gateway_dependencies


@require_GET
def capabilities(request: HttpRequest) -> JsonResponse:
    _, gateway = gateway_dependencies()
    return no_store(JsonResponse(gateway.capabilities()))
