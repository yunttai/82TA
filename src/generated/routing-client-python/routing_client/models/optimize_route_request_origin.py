from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.coordinate import Coordinate


T = TypeVar("T", bound="OptimizeRouteRequestOrigin")


@_attrs_define
class OptimizeRouteRequestOrigin:
    """
    Attributes:
        coordinate (Coordinate):
        region_hint (None | str | Unset):
    """

    coordinate: Coordinate
    region_hint: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        coordinate = self.coordinate.to_dict()

        region_hint: None | str | Unset
        if isinstance(self.region_hint, Unset):
            region_hint = UNSET
        else:
            region_hint = self.region_hint

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "coordinate": coordinate,
            }
        )
        if region_hint is not UNSET:
            field_dict["regionHint"] = region_hint

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.coordinate import Coordinate

        d = dict(src_dict)
        coordinate = Coordinate.from_dict(d.pop("coordinate"))

        def _parse_region_hint(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        region_hint = _parse_region_hint(d.pop("regionHint", UNSET))

        optimize_route_request_origin = cls(
            coordinate=coordinate,
            region_hint=region_hint,
        )

        return optimize_route_request_origin
