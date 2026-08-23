from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..models.geometry_encoding import GeometryEncoding
from ..types import UNSET, Unset

T = TypeVar("T", bound="Geometry")


@_attrs_define
class Geometry:
    """
    Attributes:
        encoding (GeometryEncoding):
        value (Any | Unset):
    """

    encoding: GeometryEncoding
    value: Any | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        encoding = self.encoding.value

        value = self.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "encoding": encoding,
            }
        )
        if value is not UNSET:
            field_dict["value"] = value

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        encoding = GeometryEncoding(d.pop("encoding"))

        value = d.pop("value", UNSET)

        geometry = cls(
            encoding=encoding,
            value=value,
        )

        return geometry
