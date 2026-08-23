from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.bus_leg_intelligence_mapping_grade import BusLegIntelligenceMappingGrade
from ..types import UNSET, Unset

T = TypeVar("T", bound="BusLegIntelligenceMapping")


@_attrs_define
class BusLegIntelligenceMapping:
    """
    Attributes:
        gbis_route_id (None | str | Unset):
        boarding_station_id (None | str | Unset):
        alighting_station_id (None | str | Unset):
        score (float | Unset):
        grade (BusLegIntelligenceMappingGrade | Unset):
        mapping_version (str | Unset):
    """

    gbis_route_id: None | str | Unset = UNSET
    boarding_station_id: None | str | Unset = UNSET
    alighting_station_id: None | str | Unset = UNSET
    score: float | Unset = UNSET
    grade: BusLegIntelligenceMappingGrade | Unset = UNSET
    mapping_version: str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        gbis_route_id: None | str | Unset
        if isinstance(self.gbis_route_id, Unset):
            gbis_route_id = UNSET
        else:
            gbis_route_id = self.gbis_route_id

        boarding_station_id: None | str | Unset
        if isinstance(self.boarding_station_id, Unset):
            boarding_station_id = UNSET
        else:
            boarding_station_id = self.boarding_station_id

        alighting_station_id: None | str | Unset
        if isinstance(self.alighting_station_id, Unset):
            alighting_station_id = UNSET
        else:
            alighting_station_id = self.alighting_station_id

        score = self.score

        grade: str | Unset = UNSET
        if not isinstance(self.grade, Unset):
            grade = self.grade.value

        mapping_version = self.mapping_version

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if gbis_route_id is not UNSET:
            field_dict["gbisRouteId"] = gbis_route_id
        if boarding_station_id is not UNSET:
            field_dict["boardingStationId"] = boarding_station_id
        if alighting_station_id is not UNSET:
            field_dict["alightingStationId"] = alighting_station_id
        if score is not UNSET:
            field_dict["score"] = score
        if grade is not UNSET:
            field_dict["grade"] = grade
        if mapping_version is not UNSET:
            field_dict["mappingVersion"] = mapping_version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_gbis_route_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        gbis_route_id = _parse_gbis_route_id(d.pop("gbisRouteId", UNSET))

        def _parse_boarding_station_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        boarding_station_id = _parse_boarding_station_id(d.pop("boardingStationId", UNSET))

        def _parse_alighting_station_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        alighting_station_id = _parse_alighting_station_id(d.pop("alightingStationId", UNSET))

        score = d.pop("score", UNSET)

        _grade = d.pop("grade", UNSET)
        grade: BusLegIntelligenceMappingGrade | Unset
        if isinstance(_grade, Unset):
            grade = UNSET
        else:
            grade = BusLegIntelligenceMappingGrade(_grade)

        mapping_version = d.pop("mappingVersion", UNSET)

        bus_leg_intelligence_mapping = cls(
            gbis_route_id=gbis_route_id,
            boarding_station_id=boarding_station_id,
            alighting_station_id=alighting_station_id,
            score=score,
            grade=grade,
            mapping_version=mapping_version,
        )

        return bus_leg_intelligence_mapping
