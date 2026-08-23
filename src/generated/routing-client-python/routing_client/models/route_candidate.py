from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.route_candidate_pattern import RouteCandidatePattern
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.money_range import MoneyRange
    from ..models.provenance import Provenance
    from ..models.route_candidate_arrival_at import RouteCandidateArrivalAt
    from ..models.route_candidate_dominance import RouteCandidateDominance
    from ..models.route_leg import RouteLeg
    from ..models.time_estimate import TimeEstimate


T = TypeVar("T", bound="RouteCandidate")


@_attrs_define
class RouteCandidate:
    """
    Attributes:
        route_id (str):
        pattern (RouteCandidatePattern):
        total_duration (TimeEstimate):
        taxi_cost (MoneyRange):
        total_fare_expected (int):
        walk_seconds (int):
        transfer_count (int):
        taxi_leg_count (int):
        reliability_score (float):
        legs (list[RouteLeg]):
        reason_codes (list[str]):
        warning_codes (list[str]):
        arrival_at (RouteCandidateArrivalAt | Unset):
        dominance (RouteCandidateDominance | Unset):
        provenance (list[Provenance] | Unset):
    """

    route_id: str
    pattern: RouteCandidatePattern
    total_duration: TimeEstimate
    taxi_cost: MoneyRange
    total_fare_expected: int
    walk_seconds: int
    transfer_count: int
    taxi_leg_count: int
    reliability_score: float
    legs: list[RouteLeg]
    reason_codes: list[str]
    warning_codes: list[str]
    arrival_at: RouteCandidateArrivalAt | Unset = UNSET
    dominance: RouteCandidateDominance | Unset = UNSET
    provenance: list[Provenance] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        route_id = self.route_id

        pattern = self.pattern.value

        total_duration = self.total_duration.to_dict()

        taxi_cost = self.taxi_cost.to_dict()

        total_fare_expected = self.total_fare_expected

        walk_seconds = self.walk_seconds

        transfer_count = self.transfer_count

        taxi_leg_count = self.taxi_leg_count

        reliability_score = self.reliability_score

        legs = []
        for legs_item_data in self.legs:
            legs_item = legs_item_data.to_dict()
            legs.append(legs_item)

        reason_codes = self.reason_codes

        warning_codes = self.warning_codes

        arrival_at: dict[str, Any] | Unset = UNSET
        if not isinstance(self.arrival_at, Unset):
            arrival_at = self.arrival_at.to_dict()

        dominance: dict[str, Any] | Unset = UNSET
        if not isinstance(self.dominance, Unset):
            dominance = self.dominance.to_dict()

        provenance: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.provenance, Unset):
            provenance = []
            for provenance_item_data in self.provenance:
                provenance_item = provenance_item_data.to_dict()
                provenance.append(provenance_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "routeId": route_id,
                "pattern": pattern,
                "totalDuration": total_duration,
                "taxiCost": taxi_cost,
                "totalFareExpected": total_fare_expected,
                "walkSeconds": walk_seconds,
                "transferCount": transfer_count,
                "taxiLegCount": taxi_leg_count,
                "reliabilityScore": reliability_score,
                "legs": legs,
                "reasonCodes": reason_codes,
                "warningCodes": warning_codes,
            }
        )
        if arrival_at is not UNSET:
            field_dict["arrivalAt"] = arrival_at
        if dominance is not UNSET:
            field_dict["dominance"] = dominance
        if provenance is not UNSET:
            field_dict["provenance"] = provenance

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.money_range import MoneyRange
        from ..models.provenance import Provenance
        from ..models.route_candidate_arrival_at import RouteCandidateArrivalAt
        from ..models.route_candidate_dominance import RouteCandidateDominance
        from ..models.route_leg import RouteLeg
        from ..models.time_estimate import TimeEstimate

        d = dict(src_dict)
        route_id = d.pop("routeId")

        pattern = RouteCandidatePattern(d.pop("pattern"))

        total_duration = TimeEstimate.from_dict(d.pop("totalDuration"))

        taxi_cost = MoneyRange.from_dict(d.pop("taxiCost"))

        total_fare_expected = d.pop("totalFareExpected")

        walk_seconds = d.pop("walkSeconds")

        transfer_count = d.pop("transferCount")

        taxi_leg_count = d.pop("taxiLegCount")

        reliability_score = d.pop("reliabilityScore")

        legs = []
        _legs = d.pop("legs")
        for legs_item_data in _legs:
            legs_item = RouteLeg.from_dict(legs_item_data)

            legs.append(legs_item)

        reason_codes = cast(list[str], d.pop("reasonCodes"))

        warning_codes = cast(list[str], d.pop("warningCodes"))

        _arrival_at = d.pop("arrivalAt", UNSET)
        arrival_at: RouteCandidateArrivalAt | Unset
        if isinstance(_arrival_at, Unset):
            arrival_at = UNSET
        else:
            arrival_at = RouteCandidateArrivalAt.from_dict(_arrival_at)

        _dominance = d.pop("dominance", UNSET)
        dominance: RouteCandidateDominance | Unset
        if isinstance(_dominance, Unset):
            dominance = UNSET
        else:
            dominance = RouteCandidateDominance.from_dict(_dominance)

        _provenance = d.pop("provenance", UNSET)
        provenance: list[Provenance] | Unset = UNSET
        if _provenance is not UNSET:
            provenance = []
            for provenance_item_data in _provenance:
                provenance_item = Provenance.from_dict(provenance_item_data)

                provenance.append(provenance_item)

        route_candidate = cls(
            route_id=route_id,
            pattern=pattern,
            total_duration=total_duration,
            taxi_cost=taxi_cost,
            total_fare_expected=total_fare_expected,
            walk_seconds=walk_seconds,
            transfer_count=transfer_count,
            taxi_leg_count=taxi_leg_count,
            reliability_score=reliability_score,
            legs=legs,
            reason_codes=reason_codes,
            warning_codes=warning_codes,
            arrival_at=arrival_at,
            dominance=dominance,
            provenance=provenance,
        )

        return route_candidate
