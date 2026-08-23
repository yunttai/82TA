"""Deterministic canonical-domain fixture builders for R1-R4 replay.

They deliberately contain no Provider payloads.  External replay tests can
replace the static cost port while preserving the seeds and constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .evaluators import StaticLegEvaluator
from .models import (
    BusWaitContribution,
    CandidateSeed,
    LegCost,
    LegSpec,
    MoneyRange,
    RouteConstraints,
    TimeEstimate,
)

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True, slots=True)
class ReplayScenario:
    replay_id: str
    corridor: str
    departure_at: datetime
    constraints: RouteConstraints
    seeds: tuple[CandidateSeed, ...]
    evaluator: StaticLegEvaluator


def _cost(p50: int, p90: int, fare_upper: int = 0, reliability: float = 0.95) -> LegCost:
    expected = int(fare_upper * 0.9)
    lower = int(fare_upper * 0.8)
    return LegCost(
        wait=TimeEstimate(0, 0),
        travel=TimeEstimate(p50, p90),
        fare=MoneyRange(expected, lower, fare_upper),
        reliability_score=reliability,
    )


def _scenario(replay_id: str, corridor: str, hour: int, minute: int) -> ReplayScenario:
    suffix = replay_id.lower()
    public = CandidateSeed(
        candidate_key=f"{suffix}-public",
        pattern="TRANSIT_ONLY",
        legs=(
            LegSpec(
                leg_id=f"{suffix}-walk",
                mode="WALK",
                from_ref=f"{suffix}-origin",
                to_ref=f"{suffix}-stop",
                evaluator_key=f"{suffix}-walk-cost",
                distance_meters=600,
            ),
            LegSpec(
                leg_id=f"{suffix}-bus",
                mode="BUS",
                from_ref=f"{suffix}-stop",
                to_ref=f"{suffix}-destination",
                evaluator_key=f"{suffix}-bus-cost",
                distance_meters=20_000,
                bus_wait=BusWaitContribution(420, 900),
            ),
        ),
        transfer_count=0,
        coarse_p50_seconds=3_000,
        coarse_taxi_upper_krw=0,
        coarse_risk=0.2,
    )
    taxi_access = CandidateSeed(
        candidate_key=f"{suffix}-taxi-access",
        pattern="TAXI_TRANSIT",
        legs=(
            LegSpec(
                leg_id=f"{suffix}-taxi",
                mode="TAXI",
                from_ref=f"{suffix}-origin",
                to_ref=f"{suffix}-upstream",
                evaluator_key=f"{suffix}-taxi-cost",
                distance_meters=4_000,
            ),
            LegSpec(
                leg_id=f"{suffix}-fast-bus",
                mode="BUS",
                from_ref=f"{suffix}-upstream",
                to_ref=f"{suffix}-destination",
                evaluator_key=f"{suffix}-fast-bus-cost",
                distance_meters=22_000,
                bus_wait=BusWaitContribution(180, 360),
            ),
        ),
        transfer_count=0,
        coarse_p50_seconds=2_200,
        coarse_taxi_upper_krw=7_000,
        coarse_risk=0.1,
    )
    costs = {
        f"{suffix}-walk-cost": _cost(480, 600),
        f"{suffix}-bus-cost": _cost(2_100, 2_700, reliability=0.78),
        f"{suffix}-taxi-cost": _cost(600, 840, fare_upper=7_000, reliability=0.9),
        f"{suffix}-fast-bus-cost": _cost(1_500, 1_900, reliability=0.94),
    }
    return ReplayScenario(
        replay_id=replay_id,
        corridor=corridor,
        departure_at=datetime(2026, 8, 24, hour, minute, tzinfo=KST),
        constraints=RouteConstraints(
            taxi_budget_krw=10_000,
            strict_taxi_budget=True,
            max_walk_seconds=900,
            max_transfers=3,
            max_taxi_legs=2,
            allowed_modes=frozenset({"WALK", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"}),
            allow_taxi_bridge=True,
        ),
        seeds=(public, taxi_access),
        evaluator=StaticLegEvaluator(costs),
    )


def build_r1_r4_scenarios() -> tuple[ReplayScenario, ...]:
    return (
        _scenario("R1", "MYONGJI_TO_PANGYO", 7, 40),
        _scenario("R2", "PANGYO_TO_MYONGJI", 18, 10),
        _scenario("R3", "GWANGGYO_TO_PANGYO", 8, 5),
        _scenario("R4", "PANGYO_TO_GWANGGYO", 19, 20),
    )
