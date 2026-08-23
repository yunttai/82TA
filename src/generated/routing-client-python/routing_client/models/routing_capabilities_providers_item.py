from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.routing_capabilities_providers_item_documentation_state import (
    RoutingCapabilitiesProvidersItemDocumentationState,
)
from ..models.routing_capabilities_providers_item_key_verification_state import (
    RoutingCapabilitiesProvidersItemKeyVerificationState,
)
from ..models.routing_capabilities_providers_item_production_state import (
    RoutingCapabilitiesProvidersItemProductionState,
)

T = TypeVar("T", bound="RoutingCapabilitiesProvidersItem")


@_attrs_define
class RoutingCapabilitiesProvidersItem:
    """
    Attributes:
        provider (str):
        documentation_state (RoutingCapabilitiesProvidersItemDocumentationState):
        key_verification_state (RoutingCapabilitiesProvidersItemKeyVerificationState):
        production_state (RoutingCapabilitiesProvidersItemProductionState):
        health (str):
    """

    provider: str
    documentation_state: RoutingCapabilitiesProvidersItemDocumentationState
    key_verification_state: RoutingCapabilitiesProvidersItemKeyVerificationState
    production_state: RoutingCapabilitiesProvidersItemProductionState
    health: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        provider = self.provider

        documentation_state = self.documentation_state.value

        key_verification_state = self.key_verification_state.value

        production_state = self.production_state.value

        health = self.health

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "provider": provider,
                "documentationState": documentation_state,
                "keyVerificationState": key_verification_state,
                "productionState": production_state,
                "health": health,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        provider = d.pop("provider")

        documentation_state = RoutingCapabilitiesProvidersItemDocumentationState(d.pop("documentationState"))

        key_verification_state = RoutingCapabilitiesProvidersItemKeyVerificationState(d.pop("keyVerificationState"))

        production_state = RoutingCapabilitiesProvidersItemProductionState(d.pop("productionState"))

        health = d.pop("health")

        routing_capabilities_providers_item = cls(
            provider=provider,
            documentation_state=documentation_state,
            key_verification_state=key_verification_state,
            production_state=production_state,
            health=health,
        )

        routing_capabilities_providers_item.additional_properties = d
        return routing_capabilities_providers_item

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
