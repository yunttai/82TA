"""Allowed, bounded V1 route-pattern validation."""

from __future__ import annotations

from .models import CandidateSeed, TRANSIT_MODES


def _core_modes(seed: CandidateSeed) -> tuple[str, ...]:
    return tuple(
        leg.mode for leg in seed.legs if leg.mode not in {"WALK", "WAIT", "TRANSFER"}
    )


def validate_pattern(seed: CandidateSeed) -> None:
    modes = _core_modes(seed)
    taxis = tuple(index for index, mode in enumerate(modes) if mode == "TAXI")
    transits = tuple(index for index, mode in enumerate(modes) if mode in TRANSIT_MODES)
    if not modes:
        raise ValueError("route pattern has no movement leg")

    valid = False
    if seed.pattern == "TRANSIT_ONLY":
        valid = bool(transits) and not taxis
    elif seed.pattern in {"TAXI_TRANSIT", "UPSTREAM_STOP_TAXI_TRANSIT"}:
        valid = len(taxis) == 1 and bool(transits) and taxis[0] < min(transits)
    elif seed.pattern == "TRANSIT_TAXI":
        valid = len(taxis) == 1 and bool(transits) and taxis[0] > max(transits)
    elif seed.pattern == "TAXI_TRANSIT_TAXI":
        valid = (
            len(taxis) == 2
            and bool(transits)
            and taxis[0] < min(transits)
            and taxis[1] > max(transits)
        )
    elif seed.pattern == "TAXI_ONLY":
        valid = bool(taxis) and not transits and all(mode == "TAXI" for mode in modes)
    elif seed.pattern == "TRANSIT_TAXI_BRIDGE_TRANSIT":
        valid = (
            len(taxis) == 1
            and len(transits) >= 2
            and min(transits) < taxis[0] < max(transits)
        )
    if not valid:
        raise ValueError(f"legs do not match declared pattern {seed.pattern}: {modes}")
