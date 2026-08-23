from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.routing_version_response_200_models_item import RoutingVersionResponse200ModelsItem


T = TypeVar("T", bound="RoutingVersionResponse200")


@_attrs_define
class RoutingVersionResponse200:
    """
    Attributes:
        build_version (str):
        contract_version (str):
        ranking_policy_version (str):
        models (list[RoutingVersionResponse200ModelsItem]):
    """

    build_version: str
    contract_version: str
    ranking_policy_version: str
    models: list[RoutingVersionResponse200ModelsItem]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        build_version = self.build_version

        contract_version = self.contract_version

        ranking_policy_version = self.ranking_policy_version

        models = []
        for models_item_data in self.models:
            models_item = models_item_data.to_dict()
            models.append(models_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "buildVersion": build_version,
                "contractVersion": contract_version,
                "rankingPolicyVersion": ranking_policy_version,
                "models": models,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.routing_version_response_200_models_item import RoutingVersionResponse200ModelsItem

        d = dict(src_dict)
        build_version = d.pop("buildVersion")

        contract_version = d.pop("contractVersion")

        ranking_policy_version = d.pop("rankingPolicyVersion")

        models = []
        _models = d.pop("models")
        for models_item_data in _models:
            models_item = RoutingVersionResponse200ModelsItem.from_dict(models_item_data)

            models.append(models_item)

        routing_version_response_200 = cls(
            build_version=build_version,
            contract_version=contract_version,
            ranking_policy_version=ranking_policy_version,
            models=models,
        )

        routing_version_response_200.additional_properties = d
        return routing_version_response_200

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
