from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.routing_readiness_response_200_status import RoutingReadinessResponse200Status

if TYPE_CHECKING:
    from ..models.routing_readiness_response_200_checks import RoutingReadinessResponse200Checks


T = TypeVar("T", bound="RoutingReadinessResponse200")


@_attrs_define
class RoutingReadinessResponse200:
    """
    Attributes:
        status (RoutingReadinessResponse200Status):
        checks (RoutingReadinessResponse200Checks):
    """

    status: RoutingReadinessResponse200Status
    checks: RoutingReadinessResponse200Checks
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        status = self.status.value

        checks = self.checks.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "status": status,
                "checks": checks,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.routing_readiness_response_200_checks import RoutingReadinessResponse200Checks

        d = dict(src_dict)
        status = RoutingReadinessResponse200Status(d.pop("status"))

        checks = RoutingReadinessResponse200Checks.from_dict(d.pop("checks"))

        routing_readiness_response_200 = cls(
            status=status,
            checks=checks,
        )

        routing_readiness_response_200.additional_properties = d
        return routing_readiness_response_200

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
