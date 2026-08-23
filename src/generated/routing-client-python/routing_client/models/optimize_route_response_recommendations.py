from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="OptimizeRouteResponseRecommendations")


@_attrs_define
class OptimizeRouteResponseRecommendations:
    """
    Attributes:
        fastest (None | str | Unset):
        stable (None | str | Unset):
        efficient (None | str | Unset):
        public_transit_only (None | str | Unset):
    """

    fastest: None | str | Unset = UNSET
    stable: None | str | Unset = UNSET
    efficient: None | str | Unset = UNSET
    public_transit_only: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        fastest: None | str | Unset
        if isinstance(self.fastest, Unset):
            fastest = UNSET
        else:
            fastest = self.fastest

        stable: None | str | Unset
        if isinstance(self.stable, Unset):
            stable = UNSET
        else:
            stable = self.stable

        efficient: None | str | Unset
        if isinstance(self.efficient, Unset):
            efficient = UNSET
        else:
            efficient = self.efficient

        public_transit_only: None | str | Unset
        if isinstance(self.public_transit_only, Unset):
            public_transit_only = UNSET
        else:
            public_transit_only = self.public_transit_only

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if fastest is not UNSET:
            field_dict["fastest"] = fastest
        if stable is not UNSET:
            field_dict["stable"] = stable
        if efficient is not UNSET:
            field_dict["efficient"] = efficient
        if public_transit_only is not UNSET:
            field_dict["publicTransitOnly"] = public_transit_only

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_fastest(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        fastest = _parse_fastest(d.pop("fastest", UNSET))

        def _parse_stable(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        stable = _parse_stable(d.pop("stable", UNSET))

        def _parse_efficient(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        efficient = _parse_efficient(d.pop("efficient", UNSET))

        def _parse_public_transit_only(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        public_transit_only = _parse_public_transit_only(d.pop("publicTransitOnly", UNSET))

        optimize_route_response_recommendations = cls(
            fastest=fastest,
            stable=stable,
            efficient=efficient,
            public_transit_only=public_transit_only,
        )

        return optimize_route_response_recommendations
