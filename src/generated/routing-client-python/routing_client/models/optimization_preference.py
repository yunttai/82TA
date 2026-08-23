from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

from ..models.optimization_preference_profile import OptimizationPreferenceProfile
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.accessibility import Accessibility


T = TypeVar("T", bound="OptimizationPreference")


@_attrs_define
class OptimizationPreference:
    """
    Attributes:
        profile (OptimizationPreferenceProfile):
        risk_aversion (float | Unset):  Default: 0.5.
        walking_aversion (float | Unset):  Default: 0.5.
        transfer_aversion (float | Unset):  Default: 0.5.
        avoid_high_bus_seat_risk (bool | Unset): User preference passed through by Service. Routing alone decides how
            supported Bus Intelligence affects candidates and ranking. Default: False.
        accessibility (Accessibility | Unset):
    """

    profile: OptimizationPreferenceProfile
    risk_aversion: float | Unset = 0.5
    walking_aversion: float | Unset = 0.5
    transfer_aversion: float | Unset = 0.5
    avoid_high_bus_seat_risk: bool | Unset = False
    accessibility: Accessibility | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        profile = self.profile.value

        risk_aversion = self.risk_aversion

        walking_aversion = self.walking_aversion

        transfer_aversion = self.transfer_aversion

        avoid_high_bus_seat_risk = self.avoid_high_bus_seat_risk

        accessibility: dict[str, Any] | Unset = UNSET
        if not isinstance(self.accessibility, Unset):
            accessibility = self.accessibility.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "profile": profile,
            }
        )
        if risk_aversion is not UNSET:
            field_dict["riskAversion"] = risk_aversion
        if walking_aversion is not UNSET:
            field_dict["walkingAversion"] = walking_aversion
        if transfer_aversion is not UNSET:
            field_dict["transferAversion"] = transfer_aversion
        if avoid_high_bus_seat_risk is not UNSET:
            field_dict["avoidHighBusSeatRisk"] = avoid_high_bus_seat_risk
        if accessibility is not UNSET:
            field_dict["accessibility"] = accessibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.accessibility import Accessibility

        d = dict(src_dict)
        profile = OptimizationPreferenceProfile(d.pop("profile"))

        risk_aversion = d.pop("riskAversion", UNSET)

        walking_aversion = d.pop("walkingAversion", UNSET)

        transfer_aversion = d.pop("transferAversion", UNSET)

        avoid_high_bus_seat_risk = d.pop("avoidHighBusSeatRisk", UNSET)

        _accessibility = d.pop("accessibility", UNSET)
        accessibility: Accessibility | Unset
        if isinstance(_accessibility, Unset):
            accessibility = UNSET
        else:
            accessibility = Accessibility.from_dict(_accessibility)

        optimization_preference = cls(
            profile=profile,
            risk_aversion=risk_aversion,
            walking_aversion=walking_aversion,
            transfer_aversion=transfer_aversion,
            avoid_high_bus_seat_risk=avoid_high_bus_seat_risk,
            accessibility=accessibility,
        )

        return optimization_preference
