from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings

from journeys.http_safety import read_bounded_response


class PlaceProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class KakaoLocalAdapter:
    rest_key: str
    base_url: str = "https://dapi.kakao.com"
    timeout_seconds: float = 2.0
    max_response_bytes: int = 512 * 1024

    @property
    def enabled(self) -> bool:
        return bool(self.rest_key)

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            follow_redirects=False,
        )

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"documents": []}
        try:
            with self._client() as client:
                with client.stream(
                    "GET",
                    path,
                    params=params,
                    headers={
                        "Accept-Encoding": "identity",
                        "Authorization": f"KakaoAK {self.rest_key}",
                    },
                ) as response:
                    content = read_bounded_response(
                        response,
                        max_bytes=self.max_response_bytes,
                    )
                response.raise_for_status()
                payload = json.loads(content)
        except (httpx.HTTPError, ValueError) as exc:
            raise PlaceProviderError("Kakao Local request failed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
            raise PlaceProviderError("Kakao Local returned an invalid schema")
        return payload

    def suggest(self, query: str, *, lon: float | None = None, lat: float | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": query, "size": 10}
        if lon is not None and lat is not None:
            params.update({"x": lon, "y": lat, "sort": "distance"})
        documents = self._get("/v2/local/search/keyword.json", params)["documents"]
        items: list[dict[str, Any]] = []
        for document in documents[:10]:
            if not isinstance(document, dict):
                continue
            try:
                raw_display_name = (
                    document.get("place_name")
                    or document.get("road_address_name")
                    or document.get("address_name")
                )
                if (
                    not isinstance(raw_display_name, str)
                    or not raw_display_name.strip()
                    or len(raw_display_name.strip()) > 200
                ):
                    continue
                display_name = raw_display_name.strip()
                lon, lat = float(document["x"]), float(document["y"])
                if not math.isfinite(lon) or not math.isfinite(lat):
                    continue
                if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    continue
                item = {
                    "displayName": display_name,
                    "coordinate": {"lon": lon, "lat": lat},
                    "provider": "KAKAO_LOCAL",
                    "providerPlaceId": str(document.get("id") or "") or None,
                    "regionCode": None,
                }
                if display_name:
                    items.append(item)
            except (KeyError, TypeError, ValueError):
                continue
        return items

    def reverse(self, lon: float, lat: float) -> dict[str, Any]:
        if not self.enabled:
            return {
                "displayName": "선택한 위치",
                "coordinate": {"lon": lon, "lat": lat},
                "provider": None,
                "providerPlaceId": None,
                "regionCode": None,
            }
        documents = self._get(
            "/v2/local/geo/coord2address.json",
            {"x": lon, "y": lat, "input_coord": "WGS84"},
        )["documents"]
        if not documents:
            raise PlaceProviderError("Kakao Local returned no address")
        document = documents[0]
        if not isinstance(document, dict):
            raise PlaceProviderError("Kakao Local returned an invalid address")
        road = document.get("road_address") or {}
        address = document.get("address") or {}
        if not isinstance(road, dict) or not isinstance(address, dict):
            raise PlaceProviderError("Kakao Local returned an invalid address")
        display_name = road.get("address_name") or address.get("address_name")
        if (
            not isinstance(display_name, str)
            or not display_name.strip()
            or len(display_name.strip()) > 200
        ):
            raise PlaceProviderError("Kakao Local returned no display address")
        return {
            "displayName": display_name.strip(),
            "coordinate": {"lon": lon, "lat": lat},
            "provider": "KAKAO_LOCAL",
            "providerPlaceId": None,
            "regionCode": str(address.get("h_code") or address.get("b_code") or "").strip() or None,
        }


def configured_adapter() -> KakaoLocalAdapter:
    return KakaoLocalAdapter(
        rest_key=settings.KAKAO_REST_API_KEY,
        base_url=settings.KAKAO_LOCAL_BASE_URL,
        timeout_seconds=settings.KAKAO_LOCAL_TIMEOUT_SECONDS,
        max_response_bytes=settings.KAKAO_LOCAL_MAX_RESPONSE_BYTES,
    )
