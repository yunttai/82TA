"""Deterministic bounded candidate admission and coarse pruning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import CandidateSeed, RouteConstraints, TRANSIT_MODES
from .patterns import validate_pattern
from .policy import CandidateCaps


class OptimalityUncertifiedError(ValueError):
    """The bounded exact pool cannot prove a global minimum."""


@dataclass(frozen=True, slots=True)
class CandidateBatch:
    supplied_count: int
    candidates: tuple[CandidateSeed, ...]
    rejected: tuple[tuple[str, str], ...]


class BoundedCandidateGenerator:
    def __init__(self, caps: CandidateCaps | None = None) -> None:
        self.caps = caps or CandidateCaps()

    def generate(
        self,
        seeds: Iterable[CandidateSeed],
        constraints: RouteConstraints,
        *,
        provider_call_count: int = 0,
        exact_evaluation: bool = False,
    ) -> CandidateBatch:
        if not 0 <= provider_call_count <= self.caps.provider_calls:
            raise ValueError("provider call cap exceeded")
        supplied = tuple(seeds)
        ordered = sorted(
            supplied,
            key=lambda seed: (
                seed.coarse_p50_seconds,
                seed.coarse_taxi_upper_krw,
                seed.coarse_risk,
                seed.pattern,
                seed.candidate_key,
            ),
        )
        accepted: list[CandidateSeed] = []
        rejected: list[tuple[str, str]] = []
        topology_seen: set[tuple[tuple[str, str, str, str], ...]] = set()
        upstream_per_route: dict[str, int] = {}
        pattern_counts: dict[str, int] = {}
        origin_access_count = 0
        destination_egress_count = 0
        exact_taxi_count = 0
        bus_intelligence_count = 0

        for seed in ordered:
            try:
                validate_pattern(seed)
            except ValueError:
                rejected.append((seed.candidate_key, "PATTERN_INVALID"))
                continue
            if not exact_evaluation and seed.topology_key in topology_seen:
                rejected.append((seed.candidate_key, "DUPLICATE_TOPOLOGY"))
                continue
            modes = {leg.mode for leg in seed.legs if leg.mode not in {"WAIT", "TRANSFER"}}
            if not modes <= constraints.allowed_modes:
                rejected.append((seed.candidate_key, "MODE_NOT_ALLOWED"))
                continue
            if seed.pattern == "TRANSIT_TAXI_BRIDGE_TRANSIT" and not constraints.allow_taxi_bridge:
                rejected.append((seed.candidate_key, "TAXI_BRIDGE_DISABLED"))
                continue
            taxi_count = sum(leg.mode == "TAXI" for leg in seed.legs)
            if taxi_count > constraints.max_taxi_legs:
                rejected.append((seed.candidate_key, "MAX_TAXI_LEGS"))
                continue
            if seed.transfer_count > constraints.max_transfers:
                rejected.append((seed.candidate_key, "MAX_TRANSFERS"))
                continue
            # V1 always treats the user's budget as a hard upper-fare bound.
            if (
                not exact_evaluation
                and seed.coarse_taxi_upper_krw > constraints.taxi_budget_krw
            ):
                rejected.append((seed.candidate_key, "COARSE_TAXI_BUDGET"))
                continue

            if not exact_evaluation and seed.pattern == "TRANSIT_ONLY":
                if pattern_counts.get(seed.pattern, 0) >= self.caps.transit_baselines:
                    rejected.append((seed.candidate_key, "TRANSIT_BASELINE_CAP"))
                    continue
            if not exact_evaluation and seed.pattern == "UPSTREAM_STOP_TAXI_TRANSIT":
                route_key = next(
                    (
                        f"{leg.mode}:{leg.from_ref}:{leg.to_ref}"
                        for leg in seed.legs
                        if leg.mode in TRANSIT_MODES
                    ),
                    seed.candidate_key,
                )
                if upstream_per_route.get(route_key, 0) >= self.caps.upstream_per_route:
                    rejected.append((seed.candidate_key, "UPSTREAM_PER_ROUTE_CAP"))
                    continue
                upstream_per_route[route_key] = upstream_per_route.get(route_key, 0) + 1

            has_origin_access = seed.pattern in {
                "TAXI_TRANSIT",
                "TAXI_TRANSIT_TAXI",
                "UPSTREAM_STOP_TAXI_TRANSIT",
            }
            has_destination_egress = seed.pattern in {"TRANSIT_TAXI", "TAXI_TRANSIT_TAXI"}
            has_taxi = taxi_count > 0
            has_bus_intelligence = any(leg.bus_wait is not None for leg in seed.legs)
            if (
                not exact_evaluation
                and has_origin_access
                and origin_access_count >= self.caps.origin_access_hubs
            ):
                rejected.append((seed.candidate_key, "ORIGIN_ACCESS_HUB_CAP"))
                continue
            if (
                not exact_evaluation
                and has_destination_egress
                and destination_egress_count >= self.caps.destination_egress_hubs
            ):
                rejected.append((seed.candidate_key, "DESTINATION_EGRESS_HUB_CAP"))
                continue
            if not exact_evaluation and has_taxi and exact_taxi_count >= self.caps.exact_taxi:
                rejected.append((seed.candidate_key, "EXACT_TAXI_CAP"))
                continue
            if (
                not exact_evaluation
                and has_bus_intelligence
                and bus_intelligence_count >= self.caps.bus_intelligence
            ):
                rejected.append((seed.candidate_key, "BUS_INTELLIGENCE_CAP"))
                continue

            topology_seen.add(seed.topology_key)
            pattern_counts[seed.pattern] = pattern_counts.get(seed.pattern, 0) + 1
            origin_access_count += int(has_origin_access)
            destination_egress_count += int(has_destination_egress)
            exact_taxi_count += int(has_taxi)
            bus_intelligence_count += int(has_bus_intelligence)
            accepted.append(seed)
            if len(accepted) >= self.caps.coarse_combinations:
                if not exact_evaluation:
                    break

        if exact_evaluation and len(accepted) > self.caps.coarse_combinations:
            raise OptimalityUncertifiedError("EXACT_CANDIDATE_CAP_UNCERTIFIED")

        admission_cap = (
            self.caps.coarse_combinations
            if exact_evaluation
            else self.caps.pre_pareto
        )
        admitted = tuple(accepted[:admission_cap])
        for seed in accepted[admission_cap:]:
            rejected.append((seed.candidate_key, "PRE_PARETO_CAP"))
        supplied_keys = {seed.candidate_key for seed in accepted}
        # Candidates beyond the hard coarse cap are explicitly accounted for.
        for seed in ordered:
            if seed.candidate_key not in supplied_keys and seed.candidate_key not in {
                key for key, _ in rejected
            }:
                rejected.append((seed.candidate_key, "COARSE_COMBINATION_CAP"))
        return CandidateBatch(
            supplied_count=len(supplied),
            candidates=admitted,
            rejected=tuple(sorted(rejected)),
        )
