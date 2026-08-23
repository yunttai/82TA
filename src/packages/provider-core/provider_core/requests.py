"""Validated provider-port inputs with no user identity or caller-selected URL."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from .canonical import Coordinate, require_aware


@dataclass(frozen=True, slots=True)
class TransitSearchRequest:
    origin: Coordinate
    destination: Coordinate
    departure_time: datetime
    max_itineraries: int = 5

    def __post_init__(self) -> None:
        require_aware(self.departure_time, "departure_time")
        if not isinstance(self.max_itineraries, int) or isinstance(self.max_itineraries, bool) or not 1 <= self.max_itineraries <= 10:
            raise ValueError("max_itineraries must be an integer between one and ten")

    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "departureTime": self.departure_time.isoformat(),
                "destination": {"lat": self.destination.lat, "lon": self.destination.lon},
                "maxItineraries": self.max_itineraries,
                "origin": {"lat": self.origin.lat, "lon": self.origin.lon},
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
