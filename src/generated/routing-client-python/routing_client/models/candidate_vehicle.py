from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.seat_risk import SeatRisk
    from ..models.time_estimate import TimeEstimate


T = TypeVar("T", bound="CandidateVehicle")


@_attrs_define
class CandidateVehicle:
    """
    Attributes:
        vehicle_ref (str):
        eta (TimeEstimate):
        remain_seat_observed (int | None | Unset):
        seat_risk_at_boarding (None | SeatRisk | Unset):
        boardability_proxy (float | None | Unset):
    """

    vehicle_ref: str
    eta: TimeEstimate
    remain_seat_observed: int | None | Unset = UNSET
    seat_risk_at_boarding: None | SeatRisk | Unset = UNSET
    boardability_proxy: float | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.seat_risk import SeatRisk

        vehicle_ref = self.vehicle_ref

        eta = self.eta.to_dict()

        remain_seat_observed: int | None | Unset
        if isinstance(self.remain_seat_observed, Unset):
            remain_seat_observed = UNSET
        else:
            remain_seat_observed = self.remain_seat_observed

        seat_risk_at_boarding: dict[str, Any] | None | Unset
        if isinstance(self.seat_risk_at_boarding, Unset):
            seat_risk_at_boarding = UNSET
        elif isinstance(self.seat_risk_at_boarding, SeatRisk):
            seat_risk_at_boarding = self.seat_risk_at_boarding.to_dict()
        else:
            seat_risk_at_boarding = self.seat_risk_at_boarding

        boardability_proxy: float | None | Unset
        if isinstance(self.boardability_proxy, Unset):
            boardability_proxy = UNSET
        else:
            boardability_proxy = self.boardability_proxy

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "vehicleRef": vehicle_ref,
                "eta": eta,
            }
        )
        if remain_seat_observed is not UNSET:
            field_dict["remainSeatObserved"] = remain_seat_observed
        if seat_risk_at_boarding is not UNSET:
            field_dict["seatRiskAtBoarding"] = seat_risk_at_boarding
        if boardability_proxy is not UNSET:
            field_dict["boardabilityProxy"] = boardability_proxy

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.seat_risk import SeatRisk
        from ..models.time_estimate import TimeEstimate

        d = dict(src_dict)
        vehicle_ref = d.pop("vehicleRef")

        eta = TimeEstimate.from_dict(d.pop("eta"))

        def _parse_remain_seat_observed(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        remain_seat_observed = _parse_remain_seat_observed(d.pop("remainSeatObserved", UNSET))

        def _parse_seat_risk_at_boarding(data: object) -> None | SeatRisk | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                seat_risk_at_boarding_type_0 = SeatRisk.from_dict(data)

                return seat_risk_at_boarding_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SeatRisk | Unset, data)

        seat_risk_at_boarding = _parse_seat_risk_at_boarding(d.pop("seatRiskAtBoarding", UNSET))

        def _parse_boardability_proxy(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        boardability_proxy = _parse_boardability_proxy(d.pop("boardabilityProxy", UNSET))

        candidate_vehicle = cls(
            vehicle_ref=vehicle_ref,
            eta=eta,
            remain_seat_observed=remain_seat_observed,
            seat_risk_at_boarding=seat_risk_at_boarding,
            boardability_proxy=boardability_proxy,
        )

        return candidate_vehicle
