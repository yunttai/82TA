from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="Accessibility")


@_attrs_define
class Accessibility:
    """
    Attributes:
        avoid_stairs (bool | Unset):  Default: False.
        wheelchair (bool | Unset):  Default: False.
    """

    avoid_stairs: bool | Unset = False
    wheelchair: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        avoid_stairs = self.avoid_stairs

        wheelchair = self.wheelchair

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if avoid_stairs is not UNSET:
            field_dict["avoidStairs"] = avoid_stairs
        if wheelchair is not UNSET:
            field_dict["wheelchair"] = wheelchair

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        avoid_stairs = d.pop("avoidStairs", UNSET)

        wheelchair = d.pop("wheelchair", UNSET)

        accessibility = cls(
            avoid_stairs=avoid_stairs,
            wheelchair=wheelchair,
        )

        return accessibility
