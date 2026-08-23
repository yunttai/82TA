from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.optimize_route_request import OptimizeRouteRequest
from ...models.optimize_route_response import OptimizeRouteResponse
from ...models.problem_details import ProblemDetails
from ...types import Response


def _get_kwargs(
    *,
    body: OptimizeRouteRequest,
    x_correlation_id: str,
    x_request_deadline: str,
    idempotency_key: str,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    headers["X-Correlation-Id"] = x_correlation_id

    headers["X-Request-Deadline"] = x_request_deadline

    headers["Idempotency-Key"] = idempotency_key

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/routes/optimize",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> OptimizeRouteResponse | ProblemDetails | None:
    if response.status_code == 200:
        response_200 = OptimizeRouteResponse.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ProblemDetails.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = ProblemDetails.from_dict(response.json())

        return response_401

    if response.status_code == 409:
        response_409 = ProblemDetails.from_dict(response.json())

        return response_409

    if response.status_code == 422:
        response_422 = ProblemDetails.from_dict(response.json())

        return response_422

    if response.status_code == 429:
        response_429 = ProblemDetails.from_dict(response.json())

        return response_429

    if response.status_code == 503:
        response_503 = ProblemDetails.from_dict(response.json())

        return response_503

    if response.status_code == 504:
        response_504 = ProblemDetails.from_dict(response.json())

        return response_504

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[OptimizeRouteResponse | ProblemDetails]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: OptimizeRouteRequest,
    x_correlation_id: str,
    x_request_deadline: str,
    idempotency_key: str,
) -> Response[OptimizeRouteResponse | ProblemDetails]:
    """
    Args:
        x_correlation_id (str):
        x_request_deadline (str):
        idempotency_key (str):
        body (OptimizeRouteRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OptimizeRouteResponse | ProblemDetails]
    """

    kwargs = _get_kwargs(
        body=body,
        x_correlation_id=x_correlation_id,
        x_request_deadline=x_request_deadline,
        idempotency_key=idempotency_key,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: OptimizeRouteRequest,
    x_correlation_id: str,
    x_request_deadline: str,
    idempotency_key: str,
) -> OptimizeRouteResponse | ProblemDetails | None:
    """
    Args:
        x_correlation_id (str):
        x_request_deadline (str):
        idempotency_key (str):
        body (OptimizeRouteRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OptimizeRouteResponse | ProblemDetails
    """

    return sync_detailed(
        client=client,
        body=body,
        x_correlation_id=x_correlation_id,
        x_request_deadline=x_request_deadline,
        idempotency_key=idempotency_key,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: OptimizeRouteRequest,
    x_correlation_id: str,
    x_request_deadline: str,
    idempotency_key: str,
) -> Response[OptimizeRouteResponse | ProblemDetails]:
    """
    Args:
        x_correlation_id (str):
        x_request_deadline (str):
        idempotency_key (str):
        body (OptimizeRouteRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[OptimizeRouteResponse | ProblemDetails]
    """

    kwargs = _get_kwargs(
        body=body,
        x_correlation_id=x_correlation_id,
        x_request_deadline=x_request_deadline,
        idempotency_key=idempotency_key,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: OptimizeRouteRequest,
    x_correlation_id: str,
    x_request_deadline: str,
    idempotency_key: str,
) -> OptimizeRouteResponse | ProblemDetails | None:
    """
    Args:
        x_correlation_id (str):
        x_request_deadline (str):
        idempotency_key (str):
        body (OptimizeRouteRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        OptimizeRouteResponse | ProblemDetails
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            x_correlation_id=x_correlation_id,
            x_request_deadline=x_request_deadline,
            idempotency_key=idempotency_key,
        )
    ).parsed
