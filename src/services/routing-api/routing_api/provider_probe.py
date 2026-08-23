"""Explicit local capability probes for fixed Provider endpoints.

Probes verify credentials and response shape. They are not application runtime
transports and cannot promote production capability or runtime evidence.
"""

from __future__ import annotations

import http.client
import json
import ssl
from typing import Callable
from urllib.parse import urlencode

from provider_core.canonical import CanonicalItinerary, Coordinate
from provider_core.named import KakaoMobilityDirectionsAdapter
from provider_core.validation import SchemaValidationError


_KAKAO_MOBILITY_HOST = "apis-navi.kakaomobility.com"
_KAKAO_MOBILITY_PATH = "/v1/directions"
_MAXIMUM_RESPONSE_BYTES = 1_000_000


class ProviderProbeError(RuntimeError):
    pass


def probe_kakao_mobility_directions(
    origin: Coordinate,
    destination: Coordinate,
    credential: str,
    *,
    timeout_seconds: float = 4.0,
    connection_factory: Callable[..., object] = http.client.HTTPSConnection,
) -> tuple[CanonicalItinerary, ...]:
    """Perform one bounded, non-redirecting current Directions capability probe."""

    if not credential or credential != credential.strip():
        raise ProviderProbeError("Kakao Mobility credential is not configured")
    if not 0 < timeout_seconds <= 10:
        raise ValueError("probe timeout must be between zero and ten seconds")

    query = urlencode(
        {
            "origin": f"{origin.lon},{origin.lat}",
            "destination": f"{destination.lon},{destination.lat}",
            "priority": "RECOMMEND",
            "summary": "false",
            "alternatives": "false",
            "road_details": "false",
        }
    )
    connection = connection_factory(
        _KAKAO_MOBILITY_HOST,
        443,
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    response = None
    try:
        connection.request(
            "GET",
            f"{_KAKAO_MOBILITY_PATH}?{query}",
            headers={
                "Authorization": f"KakaoAK {credential}",
                "Accept": "application/json",
            },
        )
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ProviderProbeError("Kakao Mobility redirects are forbidden")
        if response.status != 200:
            raise ProviderProbeError(
                f"Kakao Mobility probe returned HTTP {response.status}"
            )
        content_type = response.getheader("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise ProviderProbeError("Kakao Mobility probe returned non-JSON content")
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            if not content_length.isascii() or not content_length.isdigit():
                raise ProviderProbeError("Kakao Mobility content length is invalid")
            if int(content_length) > _MAXIMUM_RESPONSE_BYTES:
                raise ProviderProbeError("Kakao Mobility response is too large")
        body = response.read(_MAXIMUM_RESPONSE_BYTES + 1)
        if len(body) > _MAXIMUM_RESPONSE_BYTES:
            raise ProviderProbeError("Kakao Mobility response is too large")
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderProbeError("Kakao Mobility response is invalid JSON") from None
        try:
            return KakaoMobilityDirectionsAdapter.normalize_current_response(document)
        except SchemaValidationError:
            raise ProviderProbeError(
                "Kakao Mobility response failed the verified schema"
            ) from None
    except (OSError, http.client.HTTPException, TimeoutError):
        raise ProviderProbeError("Kakao Mobility probe transport failed") from None
    finally:
        if response is not None:
            response.close()
        connection.close()
