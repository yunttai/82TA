from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="RouteCandidateArrivalAt")


@_attrs_define
class RouteCandidateArrivalAt:
    """
    Attributes:
        p50 (datetime.datetime | None | Unset):
        p90 (datetime.datetime | None | Unset):
    """

    p50: datetime.datetime | None | Unset = UNSET
    p90: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        p50: None | str | Unset
        if isinstance(self.p50, Unset):
            p50 = UNSET
        elif isinstance(self.p50, datetime.datetime):
            p50 = self.p50.isoformat()
        else:
            p50 = self.p50

        p90: None | str | Unset
        if isinstance(self.p90, Unset):
            p90 = UNSET
        elif isinstance(self.p90, datetime.datetime):
            p90 = self.p90.isoformat()
        else:
            p90 = self.p90

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if p50 is not UNSET:
            field_dict["p50"] = p50
        if p90 is not UNSET:
            field_dict["p90"] = p90

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_p50(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                p50_type_0 = datetime.datetime.fromisoformat(data)

                return p50_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        p50 = _parse_p50(d.pop("p50", UNSET))

        def _parse_p90(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                p90_type_0 = datetime.datetime.fromisoformat(data)

                return p90_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        p90 = _parse_p90(d.pop("p90", UNSET))

        route_candidate_arrival_at = cls(
            p50=p50,
            p90=p90,
        )

        route_candidate_arrival_at.additional_properties = d
        return route_candidate_arrival_at

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
