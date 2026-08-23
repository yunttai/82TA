from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.time_estimate_origin import TimeEstimateOrigin
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.confidence import Confidence


T = TypeVar("T", bound="TimeEstimate")


@_attrs_define
class TimeEstimate:
    """
    Attributes:
        p_50_seconds (int):
        p_90_seconds (int):
        confidence (Confidence):
        origin (TimeEstimateOrigin):
        lower_seconds (int | None | Unset):
        upper_seconds (int | None | Unset):
    """

    p_50_seconds: int
    p_90_seconds: int
    confidence: Confidence
    origin: TimeEstimateOrigin
    lower_seconds: int | None | Unset = UNSET
    upper_seconds: int | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        p_50_seconds = self.p_50_seconds

        p_90_seconds = self.p_90_seconds

        confidence = self.confidence.to_dict()

        origin = self.origin.value

        lower_seconds: int | None | Unset
        if isinstance(self.lower_seconds, Unset):
            lower_seconds = UNSET
        else:
            lower_seconds = self.lower_seconds

        upper_seconds: int | None | Unset
        if isinstance(self.upper_seconds, Unset):
            upper_seconds = UNSET
        else:
            upper_seconds = self.upper_seconds

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "p50Seconds": p_50_seconds,
                "p90Seconds": p_90_seconds,
                "confidence": confidence,
                "origin": origin,
            }
        )
        if lower_seconds is not UNSET:
            field_dict["lowerSeconds"] = lower_seconds
        if upper_seconds is not UNSET:
            field_dict["upperSeconds"] = upper_seconds

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.confidence import Confidence

        d = dict(src_dict)
        p_50_seconds = d.pop("p50Seconds")

        p_90_seconds = d.pop("p90Seconds")

        confidence = Confidence.from_dict(d.pop("confidence"))

        origin = TimeEstimateOrigin(d.pop("origin"))

        def _parse_lower_seconds(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        lower_seconds = _parse_lower_seconds(d.pop("lowerSeconds", UNSET))

        def _parse_upper_seconds(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        upper_seconds = _parse_upper_seconds(d.pop("upperSeconds", UNSET))

        time_estimate = cls(
            p_50_seconds=p_50_seconds,
            p_90_seconds=p_90_seconds,
            confidence=confidence,
            origin=origin,
            lower_seconds=lower_seconds,
            upper_seconds=upper_seconds,
        )

        return time_estimate
