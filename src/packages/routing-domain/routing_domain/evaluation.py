"""Sequential, time-dependent candidate evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta
from math import prod

from .models import (
    CandidateSeed,
    EvaluatedCandidate,
    EvaluatedLeg,
    MoneyRange,
    TimeEstimate,
    TransferMargin,
)
from .ports import LegEvaluator
from .policy import RankingPolicy


class CandidateEvaluationError(ValueError):
    pass


def _seconds(later: datetime, earlier: datetime) -> int:
    return int((later - earlier).total_seconds())


class CandidateEvaluator:
    def __init__(self, leg_evaluator: LegEvaluator, policy: RankingPolicy | None = None) -> None:
        self.leg_evaluator = leg_evaluator
        self.policy = policy or RankingPolicy()

    def evaluate(self, seed: CandidateSeed, departure_at: datetime) -> EvaluatedCandidate:
        if departure_at.tzinfo is None or departure_at.utcoffset() is None:
            raise CandidateEvaluationError("departure_at must be timezone-aware")
        current_p50 = departure_at
        current_p90 = departure_at
        evaluated: list[EvaluatedLeg] = []
        taxi_ranges: list[MoneyRange] = []
        fares: list[MoneyRange] = []
        reliabilities: list[float] = []
        warning_codes: set[str] = set()
        transfer_risks: list[float] = []
        walk_seconds = 0

        for sequence, leg in enumerate(seed.legs):
            requirement = leg.transfer_requirement
            ready_p50 = current_p50 + timedelta(seconds=requirement.p50_seconds)
            ready_p90 = current_p90 + timedelta(seconds=requirement.p90_seconds)
            margin: TransferMargin | None = None
            if leg.scheduled_departure_at is not None:
                margin = TransferMargin(
                    p50_seconds=_seconds(leg.scheduled_departure_at, ready_p50),
                    p90_seconds=_seconds(leg.scheduled_departure_at, ready_p90),
                )
                if margin.p50_seconds < 0 or margin.p90_seconds < 0:
                    raise CandidateEvaluationError("TRANSFER_INFEASIBLE")
                transfer_risks.append(1.0 / (1.0 + margin.p90_seconds / 60.0))
                if margin.p90_seconds < self.policy.low_transfer_margin_seconds:
                    warning_codes.add("TRANSFER_MARGIN_LOW")

            # Wait is evaluated at the propagated ready time. A scheduled
            # departure already defines its wait and needs no port lookup here.
            ready_p50_cost = (
                None if margin is not None else self.leg_evaluator.evaluate(leg, ready_p50)
            )
            ready_p90_cost = (
                None if margin is not None else self.leg_evaluator.evaluate(leg, ready_p90)
            )

            bus_p50 = leg.bus_wait.expected_wait_seconds if leg.bus_wait else 0
            bus_p90 = leg.bus_wait.p90_wait_seconds if leg.bus_wait else 0
            base_wait_p50 = (
                margin.p50_seconds
                if margin is not None
                else ready_p50_cost.wait.p50_seconds
            )
            base_wait_p90 = (
                margin.p90_seconds
                if margin is not None
                else ready_p90_cost.wait.p90_seconds
            )
            wait_p50 = base_wait_p50 + bus_p50
            wait_p90 = base_wait_p90 + bus_p90
            start_p50 = ready_p50 + timedelta(seconds=wait_p50)
            # A later quantile must never imply an earlier movement start.
            start_p90 = max(
                ready_p90 + timedelta(seconds=wait_p90),
                start_p50,
            )

            # Time-dependent travel/fare/reliability are evaluated at the
            # actual movement start, after wait and transfer propagation.
            travel_p50_cost = self.leg_evaluator.evaluate(leg, start_p50)
            travel_p90_cost = self.leg_evaluator.evaluate(leg, start_p90)
            if travel_p50_cost.fare is None or travel_p90_cost.fare is None:
                if leg.mode == "TAXI":
                    raise CandidateEvaluationError("TAXI_COST_UNKNOWN")
                raise CandidateEvaluationError("FARE_UNKNOWN")
            if travel_p50_cost.fare != travel_p90_cost.fare:
                fare = MoneyRange(
                    expected_krw=travel_p50_cost.fare.expected_krw,
                    lower_krw=min(
                        travel_p50_cost.fare.lower_krw,
                        travel_p90_cost.fare.lower_krw,
                    ),
                    upper_krw=max(
                        travel_p50_cost.fare.upper_krw,
                        travel_p90_cost.fare.upper_krw,
                    ),
                )
            else:
                fare = travel_p50_cost.fare

            end_p50 = start_p50 + timedelta(seconds=travel_p50_cost.travel.p50_seconds)
            raw_end_p90 = start_p90 + timedelta(seconds=travel_p90_cost.travel.p90_seconds)
            end_p90 = max(raw_end_p90, end_p50)
            duration = TimeEstimate(
                p50_seconds=_seconds(end_p50, current_p50),
                p90_seconds=max(
                    _seconds(end_p50, current_p50),
                    _seconds(end_p90, current_p90),
                ),
            )
            evaluated_costs = tuple(
                cost
                for cost in (
                    ready_p50_cost,
                    ready_p90_cost,
                    travel_p50_cost,
                    travel_p90_cost,
                )
                if cost is not None
            )
            reliability = min(cost.reliability_score for cost in evaluated_costs)
            leg_warnings = tuple(
                sorted(
                    {
                        warning
                        for cost in evaluated_costs
                        for warning in cost.warning_codes
                    }
                )
            )
            warning_codes.update(leg_warnings)
            evaluated.append(
                EvaluatedLeg(
                    leg_id=leg.leg_id,
                    sequence=sequence,
                    mode=leg.mode,
                    from_ref=leg.from_ref,
                    to_ref=leg.to_ref,
                    ready_at_p50=ready_p50,
                    ready_at_p90=ready_p90,
                    start_at_p50=start_p50,
                    start_at_p90=start_p90,
                    end_at_p50=end_p50,
                    end_at_p90=end_p90,
                    duration=duration,
                    fare=fare,
                    distance_meters=leg.distance_meters,
                    reliability_score=reliability,
                    transfer_margin=margin,
                    warning_codes=leg_warnings,
                )
            )
            current_p50 = end_p50
            current_p90 = end_p90
            fares.append(fare)
            reliabilities.append(reliability)
            if leg.mode == "TAXI":
                taxi_ranges.append(fare)
            if leg.mode == "WALK":
                walk_seconds += travel_p50_cost.travel.p50_seconds

        taxi_cost = MoneyRange(
            expected_krw=sum(item.expected_krw for item in taxi_ranges),
            lower_krw=sum(item.lower_krw for item in taxi_ranges),
            upper_krw=sum(item.upper_krw for item in taxi_ranges),
        )
        reliability_score = prod(reliabilities) if reliabilities else 1.0
        transfer_risk = max([1.0 - reliability_score, *transfer_risks])
        total = TimeEstimate(
            p50_seconds=_seconds(current_p50, departure_at),
            p90_seconds=_seconds(current_p90, departure_at),
        )
        return EvaluatedCandidate(
            route_id=seed.route_id,
            candidate_key=seed.candidate_key,
            pattern=seed.pattern,
            topology_key=seed.topology_key,
            departure_at=departure_at,
            arrival_at_p50=current_p50,
            arrival_at_p90=current_p90,
            total_duration=total,
            taxi_cost=taxi_cost,
            total_fare_expected_krw=sum(item.expected_krw for item in fares),
            walk_seconds=walk_seconds,
            transfer_count=seed.transfer_count,
            taxi_leg_count=len(taxi_ranges),
            reliability_score=reliability_score,
            transfer_risk=transfer_risk,
            legs=tuple(evaluated),
            warning_codes=tuple(sorted(warning_codes)),
        )
