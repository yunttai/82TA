from __future__ import annotations

import unittest
from datetime import datetime, time, timedelta, timezone

from routing_domain.evaluation import CandidateEvaluationError, CandidateEvaluator
from routing_domain.evaluators import StaticLegEvaluator, TimeBand, TimeBandLegEvaluator
from routing_domain.models import (
    BusWaitContribution,
    CandidateSeed,
    LegCost,
    LegSpec,
    MoneyRange,
    TimeEstimate,
    TransferRequirement,
)


KST = timezone(timedelta(hours=9))
ZERO = MoneyRange.zero()


def cost(
    p50: int,
    p90: int,
    fare: MoneyRange | None = ZERO,
    wait50: int = 0,
    wait90: int = 0,
    next_service_wait: TimeEstimate | None = None,
) -> LegCost:
    return LegCost(
        TimeEstimate(wait50, wait90),
        TimeEstimate(p50, p90),
        fare,
        next_service_wait=next_service_wait,
    )


class RecordingEntryTimeEvaluator:
    """Deterministic spy for an API-owned, request-snapshot-backed evaluator."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, datetime]] = []

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        self.calls.append((leg.leg_id, leg.evaluator_key, leg.topology_ref, entry_at))
        if leg.evaluator_key == "fast-access":
            return cost(120, 120)
        if leg.evaluator_key == "slow-access":
            return cost(720, 720)
        if leg.evaluator_key == "shared-bus":
            threshold = datetime(2026, 8, 23, 7, 10, tzinfo=KST)
            if entry_at < threshold:
                return cost(600, 720, wait50=600, wait90=900)
            return cost(600, 720, wait50=60, wait90=120)
        if leg.evaluator_key == "first-bus":
            return cost(600, 600, wait50=300, wait90=600)
        if leg.evaluator_key == "second-bus":
            threshold = datetime(2026, 8, 23, 7, 12, tzinfo=KST)
            if entry_at < threshold:
                return cost(300, 420, wait50=60, wait90=120)
            return cost(300, 420, wait50=900, wait90=1200)
        raise ValueError(f"no deterministic cost for {leg.evaluator_key}")


class TimeDependentEvaluationTests(unittest.TestCase):
    def test_later_leg_is_evaluated_at_propagated_entry_time(self) -> None:
        departure = datetime(2026, 8, 23, 7, 50, tzinfo=KST)
        first = LegSpec("walk", "WALK", "a", "b", "walk")
        second = LegSpec("bus", "BUS", "b", "c", "bus")
        seed = CandidateSeed("time-dependent", "TRANSIT_ONLY", (first, second), 0, 1800, 0)
        evaluator = TimeBandLegEvaluator(
            bands={"bus": (TimeBand(time(8, 0), time(9, 0), cost(1800, 2100)),)},
            fallback={"walk": cost(900, 900), "bus": cost(600, 900)},
        )
        result = CandidateEvaluator(evaluator).evaluate(seed, departure)
        self.assertEqual(result.legs[1].ready_at_p50.hour, 8)
        self.assertEqual(result.legs[1].duration.p50_seconds, 1800)
        self.assertEqual(result.total_duration.p50_seconds, 2700)

    def test_wait_crossing_time_band_re_evaluates_travel_at_actual_start(self) -> None:
        departure = datetime(2026, 8, 23, 7, 59, tzinfo=KST)
        bus = LegSpec("bus", "BUS", "a", "b", "bus")
        seed = CandidateSeed("wait-crosses-band", "TRANSIT_ONLY", (bus,), 0, 2000, 0)
        before_boundary = cost(600, 900, wait50=120, wait90=120)
        after_boundary = cost(1800, 2100)
        evaluator = TimeBandLegEvaluator(
            bands={
                "bus": (
                    TimeBand(time(7, 0), time(8, 0), before_boundary),
                    TimeBand(time(8, 0), time(9, 0), after_boundary),
                )
            },
            fallback={"bus": after_boundary},
        )
        result = CandidateEvaluator(evaluator).evaluate(seed, departure)
        self.assertEqual(result.legs[0].start_at_p50, datetime(2026, 8, 23, 8, 1, tzinfo=KST))
        self.assertEqual(result.total_duration, TimeEstimate(1920, 2220))

    def test_bus_wait_changes_total_p50_and_p90_separately(self) -> None:
        departure = datetime(2026, 8, 23, 7, 0, tzinfo=KST)
        bus = LegSpec("bus", "BUS", "a", "b", "bus", bus_wait=BusWaitContribution(300, 900))
        seed = CandidateSeed("bus-wait", "TRANSIT_ONLY", (bus,), 0, 1000, 0)
        result = CandidateEvaluator(StaticLegEvaluator({"bus": cost(600, 900)})).evaluate(seed, departure)
        self.assertEqual(result.total_duration, TimeEstimate(900, 1800))
        self.assertEqual(result.legs[0].start_at_p50, departure + timedelta(seconds=300))
        self.assertEqual(result.legs[0].start_at_p90, departure + timedelta(seconds=900))
        self.assertEqual(result.legs[0].wait_duration, TimeEstimate(300, 900))
        self.assertEqual(result.legs[0].travel_duration, TimeEstimate(600, 900))

    def test_taxi_dispatch_wait_and_drive_are_exposed_as_separate_components(self) -> None:
        departure = datetime(2026, 8, 23, 7, 0, tzinfo=KST)
        taxi = LegSpec("taxi", "TAXI", "a", "b", "taxi")
        seed = CandidateSeed("taxi-wait", "TAXI_ONLY", (taxi,), 0, 1_000, 10_000)

        result = CandidateEvaluator(
            StaticLegEvaluator(
                {
                    "taxi": cost(
                        720,
                        900,
                        fare=MoneyRange(5_000, 4_000, 6_000),
                        wait50=120,
                        wait90=240,
                    )
                }
            )
        ).evaluate(seed, departure)

        self.assertEqual(result.legs[0].wait_duration, TimeEstimate(120, 240))
        self.assertEqual(result.legs[0].travel_duration, TimeEstimate(720, 900))
        self.assertEqual(result.legs[0].duration, TimeEstimate(840, 1_140))

    def test_shared_bus_movement_is_re_evaluated_at_each_candidate_entry_time(self) -> None:
        departure = datetime(2026, 8, 23, 7, 0, tzinfo=KST)
        shared_bus = LegSpec(
            "shared-bus-leg",
            "BUS",
            "shared-stop",
            "destination",
            "shared-bus",
            topology_ref="route-100:outbound:10-20",
        )
        fast = CandidateSeed(
            "fast-entry",
            "TRANSIT_ONLY",
            (
                LegSpec("fast-walk", "WALK", "origin", "shared-stop", "fast-access"),
                shared_bus,
            ),
            0,
            1_000,
            0,
        )
        slow = CandidateSeed(
            "slow-entry",
            "TRANSIT_ONLY",
            (
                LegSpec("slow-walk", "WALK", "origin", "shared-stop", "slow-access"),
                shared_bus,
            ),
            0,
            1_000,
            0,
        )
        evaluator = RecordingEntryTimeEvaluator()

        fast_result = CandidateEvaluator(evaluator).evaluate(fast, departure)
        fast_calls = tuple(evaluator.calls)
        slow_result = CandidateEvaluator(evaluator).evaluate(slow, departure)
        slow_calls = tuple(evaluator.calls[len(fast_calls) :])

        self.assertEqual(fast_result.legs[1].ready_at_p50, departure + timedelta(seconds=120))
        self.assertEqual(fast_result.legs[1].start_at_p50, departure + timedelta(seconds=720))
        self.assertEqual(slow_result.legs[1].ready_at_p50, departure + timedelta(seconds=720))
        self.assertEqual(slow_result.legs[1].start_at_p50, departure + timedelta(seconds=780))
        fast_bus_calls = [call for call in fast_calls if call[1] == "shared-bus"]
        slow_bus_calls = [call for call in slow_calls if call[1] == "shared-bus"]
        self.assertEqual(
            [
                (fast_bus_calls[0][0], fast_bus_calls[0][2], fast_bus_calls[0][3]),
                (slow_bus_calls[0][0], slow_bus_calls[0][2], slow_bus_calls[0][3]),
            ],
            [
                ("shared-bus-leg", "route-100:outbound:10-20", departure + timedelta(seconds=120)),
                ("shared-bus-leg", "route-100:outbound:10-20", departure + timedelta(seconds=720)),
            ],
        )

    def test_first_bus_wait_shifts_second_bus_boarding_and_invocations_are_deterministic(self) -> None:
        departure = datetime(2026, 8, 23, 7, 0, tzinfo=KST)
        seed = CandidateSeed(
            "two-bus",
            "TRANSIT_ONLY",
            (
                LegSpec(
                    "first-bus-leg",
                    "BUS",
                    "origin",
                    "transfer-stop",
                    "first-bus",
                    topology_ref="route-1:outbound:1-5",
                ),
                LegSpec(
                    "second-bus-leg",
                    "BUS",
                    "transfer-stop",
                    "destination",
                    "second-bus",
                    topology_ref="route-2:outbound:3-9",
                ),
            ),
            1,
            2_000,
            0,
        )
        first_evaluator = RecordingEntryTimeEvaluator()
        second_evaluator = RecordingEntryTimeEvaluator()

        first_result = CandidateEvaluator(first_evaluator).evaluate(seed, departure)
        second_result = CandidateEvaluator(second_evaluator).evaluate(seed, departure)

        self.assertEqual(first_result, second_result)
        self.assertEqual(first_evaluator.calls, second_evaluator.calls)
        second_leg = first_result.legs[1]
        self.assertEqual(second_leg.ready_at_p50, departure + timedelta(seconds=900))
        self.assertEqual(second_leg.ready_at_p90, departure + timedelta(seconds=1200))
        self.assertEqual(second_leg.start_at_p50, departure + timedelta(seconds=1800))
        self.assertEqual(second_leg.start_at_p90, departure + timedelta(seconds=2400))
        second_bus_calls = [call for call in first_evaluator.calls if call[1] == "second-bus"]
        self.assertEqual(
            second_bus_calls,
            [
                (
                    "second-bus-leg",
                    "second-bus",
                    "route-2:outbound:3-9",
                    departure + timedelta(seconds=900),
                ),
                (
                    "second-bus-leg",
                    "second-bus",
                    "route-2:outbound:3-9",
                    departure + timedelta(seconds=1200),
                ),
                (
                    "second-bus-leg",
                    "second-bus",
                    "route-2:outbound:3-9",
                    departure + timedelta(seconds=1800),
                ),
                (
                    "second-bus-leg",
                    "second-bus",
                    "route-2:outbound:3-9",
                    departure + timedelta(seconds=2400),
                ),
            ],
        )

    def test_transfer_uses_p50_and_conservative_p90_margin(self) -> None:
        departure = datetime(2026, 8, 23, 7, 0, tzinfo=KST)
        first = LegSpec("first", "BUS", "a", "b", "first")
        second = LegSpec(
            "second",
            "SUBWAY",
            "b",
            "c",
            "second",
            scheduled_departure_at=departure + timedelta(seconds=1500),
            transfer_requirement=TransferRequirement(120, 240),
        )
        seed = CandidateSeed("transfer", "TRANSIT_ONLY", (first, second), 1, 2200, 0)
        result = CandidateEvaluator(StaticLegEvaluator({"first": cost(900, 1100), "second": cost(600, 700)})).evaluate(seed, departure)
        margin = result.legs[1].transfer_margin
        self.assertIsNotNone(margin)
        assert margin is not None
        self.assertEqual((margin.p50_seconds, margin.p90_seconds), (480, 160))
        self.assertEqual(result.legs[1].start_at_p50, departure + timedelta(seconds=1500))
        self.assertIn("TRANSFER_MARGIN_LOW", result.warning_codes)

    def test_p50_catch_with_p90_miss_uses_next_service_wait(self) -> None:
        departure = datetime(2026, 8, 23, 7, 0, tzinfo=KST)
        seed = CandidateSeed(
            "missed",
            "TRANSIT_ONLY",
            (
                LegSpec("first", "BUS", "a", "b", "first"),
                LegSpec(
                    "second",
                    "SUBWAY",
                    "b",
                    "c",
                    "second",
                    scheduled_departure_at=departure + timedelta(seconds=1000),
                    transfer_requirement=TransferRequirement(60, 120),
                ),
            ),
            1,
            2000,
            0,
        )
        result = CandidateEvaluator(
            StaticLegEvaluator(
                {
                    "first": cost(700, 900),
                    "second": cost(
                        400,
                        500,
                        next_service_wait=TimeEstimate(0, 0),
                    ),
                }
            )
        ).evaluate(seed, departure)
        margin = result.legs[1].transfer_margin
        self.assertIsNotNone(margin)
        assert margin is not None
        self.assertEqual((margin.p50_seconds, margin.p90_seconds), (240, -20))
        self.assertEqual(result.legs[1].start_at_p50, departure + timedelta(seconds=1000))
        self.assertEqual(result.legs[1].start_at_p90, departure + timedelta(seconds=1020))
        self.assertEqual(result.total_duration, TimeEstimate(1400, 1520))
        self.assertIn("TRANSFER_MARGIN_LOW", result.warning_codes)

    def test_unknown_taxi_upper_is_not_fabricated(self) -> None:
        seed = CandidateSeed(
            "unknown-taxi",
            "TAXI_ONLY",
            (LegSpec("taxi", "TAXI", "a", "b", "taxi"),),
            0,
            600,
            0,
        )
        with self.assertRaisesRegex(CandidateEvaluationError, "TAXI_COST_UNKNOWN"):
            CandidateEvaluator(StaticLegEvaluator({"taxi": cost(600, 900, fare=None)})).evaluate(
                seed, datetime(2026, 8, 23, 7, 0, tzinfo=KST)
            )


if __name__ == "__main__":
    unittest.main()
