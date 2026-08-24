from __future__ import annotations

from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings

from journeys.abuse import reset_rate_limits
from places import views
from places.adapter import KakaoLocalAdapter, PlaceProviderError


class PlaceApiTests(SimpleTestCase):
    def setUp(self) -> None:
        reset_rate_limits()
        views._place_cache.clear()

    @override_settings(KAKAO_REST_API_KEY="")
    def test_missing_key_uses_safe_empty_suggest_stub(self) -> None:
        response = self.client.get("/api/v1/places/suggest", {"query": "판교"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": []})
        self.assertEqual(response["Cache-Control"], "no-store")

    @override_settings(KAKAO_REST_API_KEY="")
    def test_missing_key_reverse_preserves_only_user_coordinate(self) -> None:
        response = self.client.get(
            "/api/v1/places/reverse-geocode",
            {"lon": "127.111159", "lat": "37.394761"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider"], None)
        self.assertEqual(response.json()["coordinate"]["lon"], 127.111159)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_place_input_validation_is_bounded(self) -> None:
        self.assertEqual(self.client.get("/api/v1/places/suggest", {"query": "가"}).status_code, 400)
        response = self.client.get(
            "/api/v1/places/reverse-geocode",
            {"lon": "https://attacker.invalid", "lat": "37"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("attacker", response.content.decode())
        non_finite = self.client.get(
            "/api/v1/places/reverse-geocode",
            {"lon": "nan", "lat": "37"},
        )
        self.assertEqual(non_finite.status_code, 400)

    def test_kakao_adapter_skips_malformed_and_non_finite_suggestions(self) -> None:
        class FixtureAdapter(KakaoLocalAdapter):
            def _get(self, path, params):
                return {
                    "documents": [
                        None,
                        {},
                        {"place_name": "bad", "x": "nan", "y": "37.2"},
                        {
                            "place_name": "valid",
                            "road_address_name": "경기 성남시 분당구 판교역로 160",
                            "address_name": "경기 성남시 분당구 백현동 530",
                            "x": "127.05",
                            "y": "37.29",
                            "id": "place-1",
                        },
                    ]
                }

        items = FixtureAdapter(rest_key="test").suggest("판교")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["displayName"], "valid")
        self.assertEqual(items[0]["address"], "경기 성남시 분당구 판교역로 160")
        self.assertEqual(items[0]["coordinate"], {"lon": 127.05, "lat": 37.29})

    def test_kakao_adapter_falls_back_to_parcel_address(self) -> None:
        class FixtureAdapter(KakaoLocalAdapter):
            def _get(self, path, params):
                return {
                    "documents": [{
                        "place_name": "센트럴",
                        "road_address_name": "",
                        "address_name": "경기 수원시 영통구 이의동 1338",
                        "x": "127.05",
                        "y": "37.29",
                    }]
                }

        items = FixtureAdapter(rest_key="test").suggest("센트럴")
        self.assertEqual(items[0]["address"], "경기 수원시 영통구 이의동 1338")

    def test_kakao_adapter_rejects_malformed_reverse_shape(self) -> None:
        class FixtureAdapter(KakaoLocalAdapter):
            def _get(self, path, params):
                return {"documents": [{"address": "not-an-object"}]}

        with self.assertRaises(PlaceProviderError):
            FixtureAdapter(rest_key="test").reverse(127.05, 37.29)

    def test_kakao_response_declared_over_limit_is_rejected_without_reading(self) -> None:
        class NeverRead(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError("oversized declared response must not be consumed")

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Length": "1025"},
                stream=NeverRead(),
            )
        )
        client = httpx.Client(base_url="https://dapi.kakao.com", transport=transport)
        adapter = KakaoLocalAdapter(rest_key="test", max_response_bytes=1024)

        with (
            patch.object(KakaoLocalAdapter, "_client", return_value=client),
            self.assertRaises(PlaceProviderError),
        ):
            adapter.suggest("판교")

    def test_chunked_oversized_kakao_error_is_bounded(self) -> None:
        class OversizedChunks(httpx.SyncByteStream):
            def __iter__(self):
                yield b"x" * 800
                yield b"y" * 300

        transport = httpx.MockTransport(
            lambda request: httpx.Response(502, stream=OversizedChunks())
        )
        client = httpx.Client(base_url="https://dapi.kakao.com", transport=transport)
        adapter = KakaoLocalAdapter(rest_key="test", max_response_bytes=1024)

        with (
            patch.object(KakaoLocalAdapter, "_client", return_value=client),
            self.assertRaises(PlaceProviderError),
        ):
            adapter.reverse(127.05, 37.29)

    def test_compressed_kakao_response_is_rejected_before_body_read(self) -> None:
        class NeverReadCompressed(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError("encoded response must not be decompressed or consumed")

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["Accept-Encoding"], "identity")
            return httpx.Response(
                200,
                headers={"Content-Encoding": "br"},
                stream=NeverReadCompressed(),
            )

        client = httpx.Client(
            base_url="https://dapi.kakao.com",
            transport=httpx.MockTransport(handler),
        )
        adapter = KakaoLocalAdapter(rest_key="test", max_response_bytes=1024)
        with (
            patch.object(KakaoLocalAdapter, "_client", return_value=client),
            self.assertRaises(PlaceProviderError),
        ):
            adapter.suggest("판교")

    @override_settings(KAKAO_REST_API_KEY="", PLACE_RATE_LIMIT_PER_MINUTE=2)
    def test_rotating_place_queries_share_a_bounded_client_bucket(self) -> None:
        first = self.client.get("/api/v1/places/suggest", {"query": "판교역"}, REMOTE_ADDR="198.51.100.20")
        second = self.client.get("/api/v1/places/suggest", {"query": "광교역"}, REMOTE_ADDR="198.51.100.20")
        limited = self.client.get("/api/v1/places/suggest", {"query": "강남역"}, REMOTE_ADDR="198.51.100.20")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["code"], "RATE_LIMITED")
        self.assertEqual(limited["Retry-After"], "60")
        self.assertNotIn("강남역", limited.content.decode())

    @override_settings(KAKAO_REST_API_KEY="", PLACE_RATE_LIMIT_PER_MINUTE=1)
    def test_suggest_and_reverse_share_the_same_place_budget(self) -> None:
        first = self.client.get("/api/v1/places/suggest", {"query": "판교역"}, REMOTE_ADDR="198.51.100.21")
        limited = self.client.get(
            "/api/v1/places/reverse-geocode",
            {"lon": "127.111159", "lat": "37.394761"},
            REMOTE_ADDR="198.51.100.21",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["safeContext"], {})
