from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.provenance_origin import ProvenanceOrigin
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.confidence import Confidence


T = TypeVar("T", bound="Provenance")


@_attrs_define
class Provenance:
    """
    Attributes:
        provider (str):
        origin (ProvenanceOrigin):
        received_at (datetime.datetime):
        confidence (Confidence):
        observed_at (datetime.datetime | None | Unset):
        age_seconds (int | None | Unset):
        fallback_level (int | Unset):  Default: 0.
    """

    provider: str
    origin: ProvenanceOrigin
    received_at: datetime.datetime
    confidence: Confidence
    observed_at: datetime.datetime | None | Unset = UNSET
    age_seconds: int | None | Unset = UNSET
    fallback_level: int | Unset = 0

    def to_dict(self) -> dict[str, Any]:
        provider = self.provider

        origin = self.origin.value

        received_at = self.received_at.isoformat()

        confidence = self.confidence.to_dict()

        observed_at: None | str | Unset
        if isinstance(self.observed_at, Unset):
            observed_at = UNSET
        elif isinstance(self.observed_at, datetime.datetime):
            observed_at = self.observed_at.isoformat()
        else:
            observed_at = self.observed_at

        age_seconds: int | None | Unset
        if isinstance(self.age_seconds, Unset):
            age_seconds = UNSET
        else:
            age_seconds = self.age_seconds

        fallback_level = self.fallback_level

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "provider": provider,
                "origin": origin,
                "receivedAt": received_at,
                "confidence": confidence,
            }
        )
        if observed_at is not UNSET:
            field_dict["observedAt"] = observed_at
        if age_seconds is not UNSET:
            field_dict["ageSeconds"] = age_seconds
        if fallback_level is not UNSET:
            field_dict["fallbackLevel"] = fallback_level

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.confidence import Confidence

        d = dict(src_dict)
        provider = d.pop("provider")

        origin = ProvenanceOrigin(d.pop("origin"))

        received_at = datetime.datetime.fromisoformat(d.pop("receivedAt"))

        confidence = Confidence.from_dict(d.pop("confidence"))

        def _parse_observed_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                observed_at_type_0 = datetime.datetime.fromisoformat(data)

                return observed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        observed_at = _parse_observed_at(d.pop("observedAt", UNSET))

        def _parse_age_seconds(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        age_seconds = _parse_age_seconds(d.pop("ageSeconds", UNSET))

        fallback_level = d.pop("fallbackLevel", UNSET)

        provenance = cls(
            provider=provider,
            origin=origin,
            received_at=received_at,
            confidence=confidence,
            observed_at=observed_at,
            age_seconds=age_seconds,
            fallback_level=fallback_level,
        )

        return provenance
