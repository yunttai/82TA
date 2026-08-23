from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from provider_core.canonical import Coordinate

from routing_api.provider_probe import (
    ProviderProbeError,
    probe_kakao_mobility_directions,
)


class Command(BaseCommand):
    help = "Perform one bounded Kakao Mobility current Directions capability probe"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--origin-lon", required=True, type=float)
        parser.add_argument("--origin-lat", required=True, type=float)
        parser.add_argument("--destination-lon", required=True, type=float)
        parser.add_argument("--destination-lat", required=True, type=float)

    def handle(self, *args, **options):
        try:
            itineraries = probe_kakao_mobility_directions(
                Coordinate(options["origin_lon"], options["origin_lat"]),
                Coordinate(
                    options["destination_lon"], options["destination_lat"]
                ),
                settings.KAKAO_MOBILITY_REST_API_KEY,
            )
        except (ValueError, ProviderProbeError) as exc:
            raise CommandError(str(exc)) from None

        route = itineraries[0] if itineraries else None
        leg = route.legs[0] if route is not None else None
        self.stdout.write(
            json.dumps(
                {
                    "provider": "KAKAO_DIRECTIONS",
                    "keyVerificationState": "KEY_VERIFIED",
                    "routeCount": len(itineraries),
                    "durationSeconds": (
                        leg.duration.p50_seconds if leg is not None else None
                    ),
                    "distanceMeters": (
                        leg.distance_meters if leg is not None else None
                    ),
                    "fareKrw": leg.fare.expected_krw if leg is not None else None,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
