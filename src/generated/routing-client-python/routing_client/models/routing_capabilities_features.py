from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="RoutingCapabilitiesFeatures")


@_attrs_define
class RoutingCapabilitiesFeatures:
    """
    Attributes:
        current_transit (bool | Unset):
        future_transit (bool | Unset):
        current_taxi (bool | Unset):
        future_taxi (bool | Unset):
        multi_destination_taxi (bool | Unset):
        bus_seat_risk (bool | Unset):
        bus_eta_model (bool | Unset):
        taxi_bridge (bool | Unset):
        realtime_rerouting (bool | Unset):
    """

    current_transit: bool | Unset = UNSET
    future_transit: bool | Unset = UNSET
    current_taxi: bool | Unset = UNSET
    future_taxi: bool | Unset = UNSET
    multi_destination_taxi: bool | Unset = UNSET
    bus_seat_risk: bool | Unset = UNSET
    bus_eta_model: bool | Unset = UNSET
    taxi_bridge: bool | Unset = UNSET
    realtime_rerouting: bool | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        current_transit = self.current_transit

        future_transit = self.future_transit

        current_taxi = self.current_taxi

        future_taxi = self.future_taxi

        multi_destination_taxi = self.multi_destination_taxi

        bus_seat_risk = self.bus_seat_risk

        bus_eta_model = self.bus_eta_model

        taxi_bridge = self.taxi_bridge

        realtime_rerouting = self.realtime_rerouting

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if current_transit is not UNSET:
            field_dict["currentTransit"] = current_transit
        if future_transit is not UNSET:
            field_dict["futureTransit"] = future_transit
        if current_taxi is not UNSET:
            field_dict["currentTaxi"] = current_taxi
        if future_taxi is not UNSET:
            field_dict["futureTaxi"] = future_taxi
        if multi_destination_taxi is not UNSET:
            field_dict["multiDestinationTaxi"] = multi_destination_taxi
        if bus_seat_risk is not UNSET:
            field_dict["busSeatRisk"] = bus_seat_risk
        if bus_eta_model is not UNSET:
            field_dict["busEtaModel"] = bus_eta_model
        if taxi_bridge is not UNSET:
            field_dict["taxiBridge"] = taxi_bridge
        if realtime_rerouting is not UNSET:
            field_dict["realtimeRerouting"] = realtime_rerouting

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        current_transit = d.pop("currentTransit", UNSET)

        future_transit = d.pop("futureTransit", UNSET)

        current_taxi = d.pop("currentTaxi", UNSET)

        future_taxi = d.pop("futureTaxi", UNSET)

        multi_destination_taxi = d.pop("multiDestinationTaxi", UNSET)

        bus_seat_risk = d.pop("busSeatRisk", UNSET)

        bus_eta_model = d.pop("busEtaModel", UNSET)

        taxi_bridge = d.pop("taxiBridge", UNSET)

        realtime_rerouting = d.pop("realtimeRerouting", UNSET)

        routing_capabilities_features = cls(
            current_transit=current_transit,
            future_transit=future_transit,
            current_taxi=current_taxi,
            future_taxi=future_taxi,
            multi_destination_taxi=multi_destination_taxi,
            bus_seat_risk=bus_seat_risk,
            bus_eta_model=bus_eta_model,
            taxi_bridge=taxi_bridge,
            realtime_rerouting=realtime_rerouting,
        )

        routing_capabilities_features.additional_properties = d
        return routing_capabilities_features

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
