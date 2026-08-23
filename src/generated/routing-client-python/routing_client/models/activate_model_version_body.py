from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.activate_model_version_body_environment import ActivateModelVersionBodyEnvironment
from ..models.activate_model_version_body_purpose import ActivateModelVersionBodyPurpose
from ..types import UNSET, Unset

T = TypeVar("T", bound="ActivateModelVersionBody")


@_attrs_define
class ActivateModelVersionBody:
    """
    Attributes:
        purpose (ActivateModelVersionBodyPurpose):
        environment (ActivateModelVersionBodyEnvironment):
        traffic_fraction (float | Unset):  Default: 1.0.
    """

    purpose: ActivateModelVersionBodyPurpose
    environment: ActivateModelVersionBodyEnvironment
    traffic_fraction: float | Unset = 1.0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        purpose = self.purpose.value

        environment = self.environment.value

        traffic_fraction = self.traffic_fraction

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "purpose": purpose,
                "environment": environment,
            }
        )
        if traffic_fraction is not UNSET:
            field_dict["trafficFraction"] = traffic_fraction

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        purpose = ActivateModelVersionBodyPurpose(d.pop("purpose"))

        environment = ActivateModelVersionBodyEnvironment(d.pop("environment"))

        traffic_fraction = d.pop("trafficFraction", UNSET)

        activate_model_version_body = cls(
            purpose=purpose,
            environment=environment,
            traffic_fraction=traffic_fraction,
        )

        activate_model_version_body.additional_properties = d
        return activate_model_version_body

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
