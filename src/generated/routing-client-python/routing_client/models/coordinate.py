from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="Coordinate")


@_attrs_define
class Coordinate:
    """
    Attributes:
        lon (float):
        lat (float):
    """

    lon: float
    lat: float

    def to_dict(self) -> dict[str, Any]:
        lon = self.lon

        lat = self.lat

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "lon": lon,
                "lat": lat,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        lon = d.pop("lon")

        lat = d.pop("lat")

        coordinate = cls(
            lon=lon,
            lat=lat,
        )

        return coordinate
