"""Narrow optimizer fan-in: add Bus Intelligence wait before ranking."""

from __future__ import annotations

from dataclasses import dataclass

from .domain import BusIntelligenceResult


@dataclass(frozen=True, slots=True)
class BusLegTiming:
    p50_seconds: int
    p90_seconds: int

    def __post_init__(self) -> None:
        if self.p50_seconds < 0 or self.p90_seconds < self.p50_seconds:
            raise ValueError("Bus leg timing requires non-negative p90 >= p50")


def apply_bus_intelligence_wait(
    base_in_vehicle_p50_seconds: int,
    base_in_vehicle_p90_seconds: int,
    intelligence: BusIntelligenceResult,
) -> BusLegTiming:
    """Create the time-dependent BUS-leg input consumed by an optimizer.

    Ineligible or unavailable enrichment is not projected as a zero wait; callers
    must use their explicit non-enriched fallback path instead.
    """

    if base_in_vehicle_p50_seconds < 0:
        raise ValueError("base p50 must be non-negative")
    if base_in_vehicle_p90_seconds < base_in_vehicle_p50_seconds:
        raise ValueError("base p90 must be >= base p50")
    if not intelligence.enrichment_applied:
        raise ValueError("cannot apply unavailable Bus Intelligence as zero wait")
    assert intelligence.expected_wait_seconds is not None
    assert intelligence.p90_wait_seconds is not None
    return BusLegTiming(
        p50_seconds=base_in_vehicle_p50_seconds + intelligence.expected_wait_seconds,
        p90_seconds=base_in_vehicle_p90_seconds + intelligence.p90_wait_seconds,
    )
