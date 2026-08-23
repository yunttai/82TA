from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="SeatRisk")


@_attrs_define
class SeatRisk:
    """
    Attributes:
        no_seat_probability (float):
        low_seat_2_probability (float):
        model_version (str):
        low_seat_5_probability (float | None | Unset):
    """

    no_seat_probability: float
    low_seat_2_probability: float
    model_version: str
    low_seat_5_probability: float | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        no_seat_probability = self.no_seat_probability

        low_seat_2_probability = self.low_seat_2_probability

        model_version = self.model_version

        low_seat_5_probability: float | None | Unset
        if isinstance(self.low_seat_5_probability, Unset):
            low_seat_5_probability = UNSET
        else:
            low_seat_5_probability = self.low_seat_5_probability

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "noSeatProbability": no_seat_probability,
                "lowSeat2Probability": low_seat_2_probability,
                "modelVersion": model_version,
            }
        )
        if low_seat_5_probability is not UNSET:
            field_dict["lowSeat5Probability"] = low_seat_5_probability

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        no_seat_probability = d.pop("noSeatProbability")

        low_seat_2_probability = d.pop("lowSeat2Probability")

        model_version = d.pop("modelVersion")

        def _parse_low_seat_5_probability(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        low_seat_5_probability = _parse_low_seat_5_probability(d.pop("lowSeat5Probability", UNSET))

        seat_risk = cls(
            no_seat_probability=no_seat_probability,
            low_seat_2_probability=low_seat_2_probability,
            model_version=model_version,
            low_seat_5_probability=low_seat_5_probability,
        )

        return seat_risk
