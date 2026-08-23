from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from routing_api.application import ApiResult
from routing_api.container import get_admin_control_plane, get_application


def _response(result: ApiResult) -> JsonResponse:
    response = JsonResponse(result.body, status=result.status_code, content_type=result.content_type)
    if result.correlation_id is not None:
        response["X-Correlation-Id"] = result.correlation_id
    return response


def _authorization(request: HttpRequest) -> str | None:
    return request.headers.get("Authorization")


@csrf_exempt
@require_POST
def optimize_routes(request: HttpRequest) -> JsonResponse:
    result = get_application().optimize(
        authorization=_authorization(request),
        correlation_id=request.headers.get("X-Correlation-Id"),
        deadline_header=request.headers.get("X-Request-Deadline"),
        idempotency_key=request.headers.get("Idempotency-Key"),
        content_type=request.headers.get("Content-Type", ""),
        raw_body=request.body,
    )
    return _response(result)


@require_GET
def capabilities(request: HttpRequest) -> JsonResponse:
    app = get_application()
    failure = app.authenticate(_authorization(request), request.headers.get("X-Correlation-Id", "unavailable"))
    return _response(failure) if failure else JsonResponse(app.capabilities())


@require_GET
def live(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_GET
def ready(request: HttpRequest) -> JsonResponse:
    app = get_application()
    failure = app.authenticate(_authorization(request), request.headers.get("X-Correlation-Id", "unavailable"))
    return _response(failure) if failure else JsonResponse(app.readiness())


@require_GET
def version(request: HttpRequest) -> JsonResponse:
    app = get_application()
    failure = app.authenticate(_authorization(request), request.headers.get("X-Correlation-Id", "unavailable"))
    return _response(failure) if failure else JsonResponse(app.version())


@csrf_exempt
@require_POST
def invalidate_cache(request: HttpRequest) -> JsonResponse:
    control = get_admin_control_plane()
    if control is None:
        return JsonResponse({"detail": "not found"}, status=404)
    return _response(
        control.invalidate_cache(
            authorization=_authorization(request),
            correlation_id=request.headers.get("X-Correlation-Id", "unavailable"),
            raw_body=request.body,
        )
    )


@csrf_exempt
@require_POST
def activate_model(request: HttpRequest, version: str) -> JsonResponse:
    control = get_admin_control_plane()
    if control is None:
        return JsonResponse({"detail": "not found"}, status=404)
    return _response(
        control.activate_model(
            authorization=_authorization(request),
            correlation_id=request.headers.get("X-Correlation-Id", "unavailable"),
            version=version,
            raw_body=request.body,
        )
    )
