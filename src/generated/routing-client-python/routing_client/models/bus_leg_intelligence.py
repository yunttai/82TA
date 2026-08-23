from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.bus_leg_intelligence_coverage import BusLegIntelligenceCoverage
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.bus_leg_intelligence_mapping import BusLegIntelligenceMapping
    from ..models.candidate_vehicle import CandidateVehicle


T = TypeVar("T", bound="BusLegIntelligence")


@_attrs_define
class BusLegIntelligence:
    """
    Attributes:
        candidate_vehicles (list[CandidateVehicle]):
        expected_wait_seconds (int):
        p_90_wait_seconds (int):
        coverage (BusLegIntelligenceCoverage):
        warnings (list[str]):
        mapping (BusLegIntelligenceMapping | Unset):
        user_arrival_time (datetime.datetime | None | Unset):
    """

    candidate_vehicles: list[CandidateVehicle]
    expected_wait_seconds: int
    p_90_wait_seconds: int
    coverage: BusLegIntelligenceCoverage
    warnings: list[str]
    mapping: BusLegIntelligenceMapping | Unset = UNSET
    user_arrival_time: datetime.datetime | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        candidate_vehicles = []
        for candidate_vehicles_item_data in self.candidate_vehicles:
            candidate_vehicles_item = candidate_vehicles_item_data.to_dict()
            candidate_vehicles.append(candidate_vehicles_item)

        expected_wait_seconds = self.expected_wait_seconds

        p_90_wait_seconds = self.p_90_wait_seconds

        coverage = self.coverage.value

        warnings = self.warnings

        mapping: dict[str, Any] | Unset = UNSET
        if not isinstance(self.mapping, Unset):
            mapping = self.mapping.to_dict()

        user_arrival_time: None | str | Unset
        if isinstance(self.user_arrival_time, Unset):
            user_arrival_time = UNSET
        elif isinstance(self.user_arrival_time, datetime.datetime):
            user_arrival_time = self.user_arrival_time.isoformat()
        else:
            user_arrival_time = self.user_arrival_time

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "candidateVehicles": candidate_vehicles,
                "expectedWaitSeconds": expected_wait_seconds,
                "p90WaitSeconds": p_90_wait_seconds,
                "coverage": coverage,
                "warnings": warnings,
            }
        )
        if mapping is not UNSET:
            field_dict["mapping"] = mapping
        if user_arrival_time is not UNSET:
            field_dict["userArrivalTime"] = user_arrival_time

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bus_leg_intelligence_mapping import BusLegIntelligenceMapping
        from ..models.candidate_vehicle import CandidateVehicle

        d = dict(src_dict)
        candidate_vehicles = []
        _candidate_vehicles = d.pop("candidateVehicles")
        for candidate_vehicles_item_data in _candidate_vehicles:
            candidate_vehicles_item = CandidateVehicle.from_dict(candidate_vehicles_item_data)

            candidate_vehicles.append(candidate_vehicles_item)

        expected_wait_seconds = d.pop("expectedWaitSeconds")

        p_90_wait_seconds = d.pop("p90WaitSeconds")

        coverage = BusLegIntelligenceCoverage(d.pop("coverage"))

        warnings = cast(list[str], d.pop("warnings"))

        _mapping = d.pop("mapping", UNSET)
        mapping: BusLegIntelligenceMapping | Unset
        if isinstance(_mapping, Unset):
            mapping = UNSET
        else:
            mapping = BusLegIntelligenceMapping.from_dict(_mapping)

        def _parse_user_arrival_time(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                user_arrival_time_type_0 = datetime.datetime.fromisoformat(data)

                return user_arrival_time_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        user_arrival_time = _parse_user_arrival_time(d.pop("userArrivalTime", UNSET))

        bus_leg_intelligence = cls(
            candidate_vehicles=candidate_vehicles,
            expected_wait_seconds=expected_wait_seconds,
            p_90_wait_seconds=p_90_wait_seconds,
            coverage=coverage,
            warnings=warnings,
            mapping=mapping,
            user_arrival_time=user_arrival_time,
        )

        return bus_leg_intelligence
