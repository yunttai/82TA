from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.coordinate import Coordinate


T = TypeVar("T", bound="StopRef")


@_attrs_define
class StopRef:
    """
    Attributes:
        name (str):
        coordinate (Coordinate):
        canonical_stop_id (None | Unset | UUID):
        provider_stop_id (None | str | Unset):
    """

    name: str
    coordinate: Coordinate
    canonical_stop_id: None | Unset | UUID = UNSET
    provider_stop_id: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        coordinate = self.coordinate.to_dict()

        canonical_stop_id: None | str | Unset
        if isinstance(self.canonical_stop_id, Unset):
            canonical_stop_id = UNSET
        elif isinstance(self.canonical_stop_id, UUID):
            canonical_stop_id = str(self.canonical_stop_id)
        else:
            canonical_stop_id = self.canonical_stop_id

        provider_stop_id: None | str | Unset
        if isinstance(self.provider_stop_id, Unset):
            provider_stop_id = UNSET
        else:
            provider_stop_id = self.provider_stop_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "name": name,
                "coordinate": coordinate,
            }
        )
        if canonical_stop_id is not UNSET:
            field_dict["canonicalStopId"] = canonical_stop_id
        if provider_stop_id is not UNSET:
            field_dict["providerStopId"] = provider_stop_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.coordinate import Coordinate

        d = dict(src_dict)
        name = d.pop("name")

        coordinate = Coordinate.from_dict(d.pop("coordinate"))

        def _parse_canonical_stop_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                canonical_stop_id_type_0 = UUID(data)

                return canonical_stop_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        canonical_stop_id = _parse_canonical_stop_id(d.pop("canonicalStopId", UNSET))

        def _parse_provider_stop_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        provider_stop_id = _parse_provider_stop_id(d.pop("providerStopId", UNSET))

        stop_ref = cls(
            name=name,
            coordinate=coordinate,
            canonical_stop_id=canonical_stop_id,
            provider_stop_id=provider_stop_id,
        )

        return stop_ref
