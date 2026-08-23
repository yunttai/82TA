"""Allowlisted deterministic fixture and fault scenarios for replay/API tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FixtureFault(StrEnum):
    NONE = "NONE"
    PROVIDER_EMPTY = "PROVIDER_EMPTY"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_SCHEMA_DRIFT = "PROVIDER_SCHEMA_DRIFT"
    MAPPING_LOW = "MAPPING_LOW"
    ETA_UNAVAILABLE = "ETA_UNAVAILABLE"
    SEAT_UNAVAILABLE = "SEAT_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class IntegratedFixtureScenario:
    scenario_id: str
    corridor: str
    fault: FixtureFault = FixtureFault.NONE
    first_no_seat_probability: float = 0.2
    second_no_seat_probability: float = 0.1

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.corridor:
            raise ValueError("fixture scenario identity is required")
        for value in (
            self.first_no_seat_probability,
            self.second_no_seat_probability,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("fixture seat probabilities must be bounded")


def build_r1_r4_fixture_scenarios() -> tuple[IntegratedFixtureScenario, ...]:
    return (
        IntegratedFixtureScenario("R1", "MYONGJI_TO_PANGYO", first_no_seat_probability=0.25),
        IntegratedFixtureScenario("R2", "PANGYO_TO_MYONGJI", first_no_seat_probability=0.35),
        IntegratedFixtureScenario("R3", "GWANGGYO_TO_PANGYO", first_no_seat_probability=0.15),
        IntegratedFixtureScenario("R4", "PANGYO_TO_GWANGGYO", first_no_seat_probability=0.30),
    )


def fixture_scenario(scenario_id: str) -> IntegratedFixtureScenario:
    replay = {item.scenario_id: item for item in build_r1_r4_fixture_scenarios()}
    faults = {
        fault.value: IntegratedFixtureScenario(
            fault.value,
            "SANITIZED_FAULT_INJECTION",
            fault=fault,
        )
        for fault in FixtureFault
        if fault is not FixtureFault.NONE
    }
    try:
        return {**replay, **faults}[scenario_id]
    except KeyError as exc:
        raise ValueError(f"unknown allowlisted fixture scenario: {scenario_id}") from exc
