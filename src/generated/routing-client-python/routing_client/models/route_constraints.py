from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

from ..models.route_constraints_allowed_modes_item import RouteConstraintsAllowedModesItem
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.accessibility import Accessibility
    from ..models.taxi_budget import TaxiBudget


T = TypeVar("T", bound="RouteConstraints")


@_attrs_define
class RouteConstraints:
    """
    Attributes:
        taxi_budget (TaxiBudget):
        max_walk_seconds (int):
        max_transfers (int):
        max_taxi_legs (int):
        allowed_modes (list[RouteConstraintsAllowedModesItem]):
        allow_taxi_bridge (bool | Unset):  Default: False.
        accessibility (Accessibility | Unset):
    """

    taxi_budget: TaxiBudget
    max_walk_seconds: int
    max_transfers: int
    max_taxi_legs: int
    allowed_modes: list[RouteConstraintsAllowedModesItem]
    allow_taxi_bridge: bool | Unset = False
    accessibility: Accessibility | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        taxi_budget = self.taxi_budget.to_dict()

        max_walk_seconds = self.max_walk_seconds

        max_transfers = self.max_transfers

        max_taxi_legs = self.max_taxi_legs

        allowed_modes = []
        for allowed_modes_item_data in self.allowed_modes:
            allowed_modes_item = allowed_modes_item_data.value
            allowed_modes.append(allowed_modes_item)

        allow_taxi_bridge = self.allow_taxi_bridge

        accessibility: dict[str, Any] | Unset = UNSET
        if not isinstance(self.accessibility, Unset):
            accessibility = self.accessibility.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "taxiBudget": taxi_budget,
                "maxWalkSeconds": max_walk_seconds,
                "maxTransfers": max_transfers,
                "maxTaxiLegs": max_taxi_legs,
                "allowedModes": allowed_modes,
            }
        )
        if allow_taxi_bridge is not UNSET:
            field_dict["allowTaxiBridge"] = allow_taxi_bridge
        if accessibility is not UNSET:
            field_dict["accessibility"] = accessibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.accessibility import Accessibility
        from ..models.taxi_budget import TaxiBudget

        d = dict(src_dict)
        taxi_budget = TaxiBudget.from_dict(d.pop("taxiBudget"))

        max_walk_seconds = d.pop("maxWalkSeconds")

        max_transfers = d.pop("maxTransfers")

        max_taxi_legs = d.pop("maxTaxiLegs")

        allowed_modes = []
        _allowed_modes = d.pop("allowedModes")
        for allowed_modes_item_data in _allowed_modes:
            allowed_modes_item = RouteConstraintsAllowedModesItem(allowed_modes_item_data)

            allowed_modes.append(allowed_modes_item)

        allow_taxi_bridge = d.pop("allowTaxiBridge", UNSET)

        _accessibility = d.pop("accessibility", UNSET)
        accessibility: Accessibility | Unset
        if isinstance(_accessibility, Unset):
            accessibility = UNSET
        else:
            accessibility = Accessibility.from_dict(_accessibility)

        route_constraints = cls(
            taxi_budget=taxi_budget,
            max_walk_seconds=max_walk_seconds,
            max_transfers=max_transfers,
            max_taxi_legs=max_taxi_legs,
            allowed_modes=allowed_modes,
            allow_taxi_bridge=allow_taxi_bridge,
            accessibility=accessibility,
        )

        return route_constraints
