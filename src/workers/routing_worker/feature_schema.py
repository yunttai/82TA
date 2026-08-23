"""Worker-owned full feature schemas composed from Bus-owned context schemas."""

from __future__ import annotations

from bus_intelligence_core import (
    ETA_CONTEXT_FEATURE_NAMES,
    ETA_CONTEXT_SERVING_SCHEMA_VERSION,
    SEAT_RISK_CONTEXT_FEATURE_NAMES,
    SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION,
)


ETA_CORE_FEATURE_NAMES = (
    "route_id",
    "direction",
    "current_station_sequence",
    "target_station_sequence",
    "remaining_stops",
    "recent_segment_seconds_1",
    "recent_segment_seconds_3",
    "recent_segment_seconds_5",
    "historical_segment_seconds",
    "headway_seconds",
    "observed_hour",
    "day_of_week",
    "freshness_seconds",
)
SEAT_CORE_FEATURE_NAMES = (
    "route_id",
    "direction",
    "current_station_sequence",
    "target_station_sequence",
    "remaining_stops",
    "current_remaining_seats",
    "current_crowded_code",
    "capacity_confidence",
    "recent_seat_delta",
    "headway_seconds",
    "observed_hour",
    "day_of_week",
    "freshness_seconds",
)

ETA_SCHEMA_VERSION = (
    f"eta-feature-foundation-v2+{ETA_CONTEXT_SERVING_SCHEMA_VERSION}"
)
SEAT_SCHEMA_VERSION = (
    f"seat-risk-feature-foundation-v2+{SEAT_RISK_CONTEXT_SERVING_SCHEMA_VERSION}"
)
ETA_FEATURE_NAMES = ETA_CORE_FEATURE_NAMES + ETA_CONTEXT_FEATURE_NAMES + (
    "missing_flags",
)
SEAT_FEATURE_NAMES = SEAT_CORE_FEATURE_NAMES + SEAT_RISK_CONTEXT_FEATURE_NAMES + (
    "missing_flags",
)


__all__ = [
    "ETA_CORE_FEATURE_NAMES",
    "ETA_FEATURE_NAMES",
    "ETA_SCHEMA_VERSION",
    "SEAT_CORE_FEATURE_NAMES",
    "SEAT_FEATURE_NAMES",
    "SEAT_SCHEMA_VERSION",
]
