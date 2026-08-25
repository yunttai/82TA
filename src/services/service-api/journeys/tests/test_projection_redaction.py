from __future__ import annotations

import copy

from django.test import SimpleTestCase

from journeys.contracts import CanonicalContracts, LockedFixtures
from journeys.projection import _public_geometry, _public_route, project_public_response


class PublicProjectionRedactionTests(SimpleTestCase):
    def test_open_private_objects_cannot_cross_the_public_boundary(self) -> None:
        fixtures = LockedFixtures()
        private = fixtures.get("routing_response")
        route = {
            "routeId": "safe-route",
            "pattern": "TRANSIT_ONLY",
            "totalDuration": {
                "p50Seconds": 600,
                "p90Seconds": 720,
                "confidence": {"score": 0.8, "grade": "MEDIUM"},
                "origin": "PROVIDER_ESTIMATE",
            },
            "taxiCost": {
                "currency": "KRW",
                "expected": 0,
                "lower": 0,
                "upper": 0,
                "origin": "PROVIDER_ESTIMATE",
            },
            "totalFareExpected": 1500,
            "walkSeconds": 0,
            "transferCount": 0,
            "taxiLegCount": 0,
            "reliabilityScore": 0.8,
            "arrivalAt": {
                "p50": "2026-08-23T08:00:00+09:00",
                "p90": "2026-08-23T08:02:00+09:00",
                "rawProviderResponse": {"apiKey": "arrival-private-secret"},
            },
            "dominance": {
                "onParetoFrontier": True,
                "rawProviderResponse": {
                    "apiKey": "dominance-private-secret",
                    "userId": "private-user-id",
                },
            },
            "legs": [
                {
                    "legId": "safe-leg",
                    "sequence": 0,
                    "mode": "BUS",
                    "from": {
                        "name": "Origin",
                        "coordinate": {"lon": 127.187456, "lat": 37.222345},
                    },
                    "to": {
                        "name": "Destination",
                        "coordinate": {"lon": 127.111159, "lat": 37.394761},
                    },
                    "duration": {
                        "p50Seconds": 600,
                        "p90Seconds": 720,
                        "confidence": {"score": 0.8, "grade": "MEDIUM"},
                        "origin": "PROVIDER_ESTIMATE",
                    },
                    "waitDuration": {
                        "p50Seconds": 120,
                        "p90Seconds": 180,
                        "confidence": {"score": 0.8, "grade": "MEDIUM"},
                        "origin": "PROVIDER_ESTIMATE",
                    },
                    "travelDuration": {
                        "p50Seconds": 480,
                        "p90Seconds": 540,
                        "confidence": {"score": 0.8, "grade": "MEDIUM"},
                        "origin": "PROVIDER_ESTIMATE",
                    },
                    "distanceMeters": 10_000,
                    "fare": {
                        "currency": "KRW",
                        "expected": 1500,
                        "lower": 1500,
                        "upper": 1500,
                        "origin": "PROVIDER_ESTIMATE",
                    },
                    "geometry": {
                        "encoding": "GEOJSON",
                        "value": {
                            "type": "Feature",
                            "authorization": "Bearer private-secret",
                            "userEmail": "private@example.invalid",
                        },
                    },
                    "transit": {
                        "routeLabel": "100",
                        "direction": "OUTBOUND",
                        "externalRouteId": "provider-internal-route",
                        "rawPayload": {
                            "authorization": "Bearer private-secret",
                            "artifactUri": "gs://private/model",
                            "userEmail": "private@example.invalid",
                        },
                    },
                    "provenance": [],
                }
            ],
            "reasonCodes": [],
            "warningCodes": [],
        }
        private["routes"] = [route]
        private["recommendations"] = {
            "fastest": "safe-route",
            "stable": None,
            "efficient": None,
            "publicTransitOnly": "safe-route",
        }
        private["paretoRouteIds"] = ["safe-route"]

        projected = project_public_response(
            private,
            CanonicalContracts(),
            fixtures,
            public_request=fixtures.get("public_request"),
        )

        public_leg = projected["recommendations"]["fastest"]["legs"][0]
        self.assertEqual(
            public_leg["transit"],
            {"routeLabel": "100", "routeType": None, "direction": "OUTBOUND"},
        )
        self.assertEqual(public_leg["geometry"], {"encoding": "NONE"})
        canonical_request = fixtures.get("public_request")
        self.assertEqual(public_leg["from"]["name"], canonical_request["origin"]["displayName"])
        self.assertEqual(public_leg["to"]["name"], canonical_request["destination"]["displayName"])
        self.assertEqual(public_leg["waitDuration"]["p50Seconds"], 120)
        self.assertEqual(public_leg["travelDuration"]["p50Seconds"], 480)
        public_route = projected["recommendations"]["fastest"]
        self.assertEqual(
            public_route["arrivalAt"],
            {
                "p50": "2026-08-23T08:00:00+09:00",
                "p90": "2026-08-23T08:02:00+09:00",
            },
        )
        self.assertEqual(public_route["dominance"], {"onParetoFrontier": True})
        self.assertNotIn("private-secret", str(projected))
        self.assertNotIn("private-user-id", str(projected))
        self.assertNotIn("private@example.invalid", str(projected))
        self.assertNotIn("gs://private/model", str(projected))

        private["routes"][0]["legs"][0]["geometry"] = {
            "encoding": "POLYLINE",
            "value": "plate=12GA3456 private@example.invalid token=secret",
        }
        projected_polyline = project_public_response(
            private,
            CanonicalContracts(),
            fixtures,
            public_request=fixtures.get("public_request"),
        )
        self.assertEqual(
            projected_polyline["recommendations"]["fastest"]["legs"][0]["geometry"],
            {"encoding": "NONE"},
        )
        self.assertNotIn("private@example.invalid", str(projected_polyline))

    def test_customer_stop_names_replace_provider_placeholders_without_mutating_route(self) -> None:
        private_route = {
            "legs": [
                {
                    "legId": "taxi-access",
                    "from": {"name": "Origin", "coordinate": {"lon": 127.10, "lat": 37.30}},
                    "to": {"name": "Destination", "coordinate": {"lon": 127.11, "lat": 37.31}},
                    "geometry": {"encoding": "NONE"},
                    "transit": None,
                },
                {
                    "legId": "subway",
                    "from": {"name": "판교(판교테크노밸리)", "coordinate": {"lon": 127.11, "lat": 37.31}},
                    "to": {"name": "어린이대공원(세종대)", "coordinate": {"lon": 127.12, "lat": 37.32}},
                    "geometry": {"encoding": "NONE"},
                    "transit": {
                        "routeLabel": "7호선",
                        "routeType": "SUBWAY",
                        "direction": "Kakao Transit Destination",
                    },
                },
                {
                    "legId": "final-walk",
                    "from": {"name": "어린이대공원(세종대)", "coordinate": {"lon": 127.12, "lat": 37.32}},
                    "to": {"name": "Kakao transit destination", "coordinate": {"lon": 127.13, "lat": 37.33}},
                    "geometry": {"encoding": "NONE"},
                    "transit": None,
                },
            ]
        }
        original = copy.deepcopy(private_route)
        public = _public_route(
            private_route,
            {
                "origin": {"displayName": "드론 기업지원허브센터"},
                "destination": {"displayName": "세종대학교"},
            },
        )

        self.assertEqual(public["legs"][0]["from"]["name"], "드론 기업지원허브센터")
        self.assertEqual(public["legs"][0]["to"]["name"], "판교(판교테크노밸리)")
        self.assertEqual(public["legs"][1]["from"]["name"], "판교(판교테크노밸리)")
        self.assertEqual(public["legs"][-1]["to"]["name"], "세종대학교")
        self.assertIsNone(public["legs"][1]["transit"]["direction"])
        self.assertEqual(public["legs"][1]["transit"]["routeLabel"], "7호선")
        self.assertEqual(private_route, original)
        self.assertNotRegex(str(public), r"(?i)origin|destination|kakao\s+transit")

    def test_valid_polyline_is_reencoded_as_numeric_geojson(self) -> None:
        # Standard 1e5 polyline encoding for two points in the Seoul area.
        def encode(points: list[tuple[float, float]]) -> str:
            output: list[str] = []
            previous_latitude = 0
            previous_longitude = 0
            for latitude, longitude in points:
                next_latitude = round(latitude * 100_000)
                next_longitude = round(longitude * 100_000)
                for delta in (
                    next_latitude - previous_latitude,
                    next_longitude - previous_longitude,
                ):
                    value = ~(delta << 1) if delta < 0 else delta << 1
                    while value >= 0x20:
                        output.append(chr((0x20 | (value & 0x1F)) + 63))
                        value >>= 5
                    output.append(chr(value + 63))
                previous_latitude = next_latitude
                previous_longitude = next_longitude
            return "".join(output)

        geometry = _public_geometry(
            {
                "encoding": "POLYLINE",
                "value": encode([(37.5665, 126.9780), (37.5700, 126.9820)]),
            }
        )
        self.assertEqual(geometry["encoding"], "GEOJSON")
        self.assertEqual(
            geometry["value"]["coordinates"],
            [[126.978, 37.5665], [126.982, 37.57]],
        )
