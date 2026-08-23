"""Versioned internal optimizer policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CandidateCaps:
    transit_baselines: int = 5
    origin_access_hubs: int = 12
    destination_egress_hubs: int = 12
    upstream_per_route: int = 5
    coarse_combinations: int = 120
    exact_taxi: int = 30
    bus_intelligence: int = 16
    pre_pareto: int = 20
    user_results: int = 4
    provider_calls: int = 64

    def __post_init__(self) -> None:
        values = (
            self.transit_baselines,
            self.origin_access_hubs,
            self.destination_egress_hubs,
            self.upstream_per_route,
            self.coarse_combinations,
            self.exact_taxi,
            self.bus_intelligence,
            self.pre_pareto,
            self.user_results,
            self.provider_calls,
        )
        if any(value <= 0 for value in values):
            raise ValueError("candidate caps must be positive")
        if self.pre_pareto > self.coarse_combinations:
            raise ValueError("pre_pareto cannot exceed coarse_combinations")
        if self.user_results != 4:
            raise ValueError("V1 user_results cap must be exactly four")


@dataclass(frozen=True, slots=True)
class EpsilonPolicy:
    p50_seconds: int = 30
    p90_seconds: int = 60
    taxi_upper_krw: int = 100
    walk_seconds: int = 30
    transfer_risk: float = 0.01
    representative_policy_version: str = "epsilon-scc-lexicographic-1.0.0"

    def __post_init__(self) -> None:
        if min(
            self.p50_seconds,
            self.p90_seconds,
            self.taxi_upper_krw,
            self.walk_seconds,
            self.transfer_risk,
        ) < 0:
            raise ValueError("epsilon values must be non-negative")
        if not self.representative_policy_version:
            raise ValueError("epsilon representative policy version is required")


@dataclass(frozen=True, slots=True)
class RankingPolicy:
    version: str = "rank-0.2.0"
    reliability_floor: float = 0.5
    low_transfer_margin_seconds: int = 180
    budget_near_limit_ratio: float = 0.9
    comfortable_walk_seconds: int = 600
    walk_time_weight: float = 1.25
    taxi_activation_penalty_seconds: int = 120
    minimum_efficient_gain_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("ranking policy version is required")
        if not 0.0 <= self.reliability_floor <= 1.0:
            raise ValueError("reliability_floor must be between 0 and 1")
        if self.low_transfer_margin_seconds < 0:
            raise ValueError("low transfer margin must be non-negative")
        if not 0.0 <= self.budget_near_limit_ratio <= 1.0:
            raise ValueError("budget_near_limit_ratio must be between 0 and 1")
        if self.comfortable_walk_seconds < 0:
            raise ValueError("comfortable_walk_seconds must be non-negative")
        if self.walk_time_weight < 1.0:
            raise ValueError("walk_time_weight must be at least one")
        if self.taxi_activation_penalty_seconds < 0:
            raise ValueError("taxi activation penalty must be non-negative")
        if self.minimum_efficient_gain_seconds < 0:
            raise ValueError("minimum efficient gain must be non-negative")


@dataclass(frozen=True, slots=True)
class ProviderCallBudget:
    limit: int
    consumed: int = 0

    def __post_init__(self) -> None:
        if self.limit <= 0 or not 0 <= self.consumed <= self.limit:
            raise ValueError("invalid provider call budget")

    def reserve(self, count: int = 1) -> "ProviderCallBudget":
        if count < 0 or self.consumed + count > self.limit:
            raise ValueError("provider call cap exceeded")
        return ProviderCallBudget(limit=self.limit, consumed=self.consumed + count)
