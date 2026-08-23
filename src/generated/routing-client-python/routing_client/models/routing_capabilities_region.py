from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="RoutingCapabilitiesRegion")


@_attrs_define
class RoutingCapabilitiesRegion:
    """
    Attributes:
        origin_supported (bool | Unset):
        destination_supported (bool | Unset):
    """

    origin_supported: bool | Unset = UNSET
    destination_supported: bool | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        origin_supported = self.origin_supported

        destination_supported = self.destination_supported

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if origin_supported is not UNSET:
            field_dict["originSupported"] = origin_supported
        if destination_supported is not UNSET:
            field_dict["destinationSupported"] = destination_supported

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        origin_supported = d.pop("originSupported", UNSET)

        destination_supported = d.pop("destinationSupported", UNSET)

        routing_capabilities_region = cls(
            origin_supported=origin_supported,
            destination_supported=destination_supported,
        )

        routing_capabilities_region.additional_properties = d
        return routing_capabilities_region

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
